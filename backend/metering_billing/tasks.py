from __future__ import absolute_import, unicode_literals

import datetime
import logging
from datetime import timezone
from decimal import Decimal, InvalidOperation

import posthog
from celery import shared_task
from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.core.cache import cache
from django.db.models import Count, Q
from metering_billing.invoice import generate_invoice
from metering_billing.models import (
    Backtest,
    Customer,
    CustomerBalanceAdjustment,
    Event,
    Invoice,
    Organization,
    PlanComponent,
    Subscription,
    SubscriptionRecord,
)
from metering_billing.payment_providers import PAYMENT_PROVIDER_MAP
from metering_billing.serializers.backtest_serializers import (
    AllSubstitutionResultsSerializer,
)
from metering_billing.utils import (
    date_as_max_dt,
    date_as_min_dt,
    dates_bwn_two_dts,
    make_all_dates_times_strings,
    make_all_datetimes_dates,
    make_all_decimals_floats,
    now_utc,
)
from metering_billing.utils.enums import (
    BACKTEST_STATUS,
    CUSTOMER_BALANCE_ADJUSTMENT_STATUS,
    FLAT_FEE_BILLING_TYPE,
    INVOICE_STATUS,
    SUBSCRIPTION_STATUS,
)

logger = logging.getLogger("django.server")
EVENT_CACHE_FLUSH_COUNT = settings.EVENT_CACHE_FLUSH_COUNT
EVENT_CACHE_FLUSH_SECONDS = settings.EVENT_CACHE_FLUSH_SECONDS
POSTHOG_PERSON = settings.POSTHOG_PERSON


@shared_task
def calculate_invoice():
    # GENERAL PHILOSOPHY: this task is for periodic maintenance of ending susbcriptions. We only end and re-start subscriptions when they're scheduled to end, if for some other reason they end early then it is up to the other process to handle the invoice creationg and .
    # get ending subs
    now_minus_30 = now_utc() + relativedelta(
        minutes=-30
    )  # grace period of 30 minutes for sending events
    subs_to_bill = list(
        Subscription.objects.filter(
            Q(end_date__lt=now_minus_30),
        )
    )

    # now generate invoices and new subs
    for old_subscription in subs_to_bill:
        old_sub_records = old_subscription.get_subscription_records_to_bill()
        new_sub = Subscription.objects.create(
            organization=old_subscription.organization,
            day_anchor=old_subscription.day_anchor,
            month_anchor=old_subscription.month_anchor,
            customer=old_subscription.customer,
            billing_cadence=old_subscription.billing_cadence,
            start_date=date_as_min_dt(
                old_subscription.end_date + relativedelta(days=+1)
            ),
            end_date=old_subscription.get_new_sub_end_date(),
        )
        # Generate the invoice
        try:
            generate_invoice(
                old_subscription,
                old_sub_records,
                charge_next_plan=True,
                generate_next_subscription_record=True,
            )
            now = now_utc()
        except Exception as e:
            logger.error(
                "Error generating invoice for subscription {}. Error was {}".format(
                    old_subscription, e
                )
            )
            continue
        num_subscription_records_active = SubscriptionRecord.objects.filter(
            organization=old_subscription.organization,
            status=SUBSCRIPTION_STATUS.ACTIVE,
            end_date__gte=old_subscription.end_date,
        ).count()
        if not (num_subscription_records_active > 0):
            new_sub.delete()
        else:
            new_sub.handle_remove_plan()
        # End the old subscription and delete draft invoices
        Invoice.objects.filter(
            issue_date__lt=now,
            payment_status=INVOICE_STATUS.DRAFT,
            subscription=old_subscription,
            organization=old_subscription.organization,
        ).delete()


@shared_task
def zero_out_expired_balance_adjustments():
    now = now_utc()
    expired_balance_adjustments = CustomerBalanceAdjustment.objects.filter(
        expiration_date__lt=now,
        amount__gt=0,
        status=CUSTOMER_BALANCE_ADJUSTMENT_STATUS.ACTIVE,
    )
    for ba in expired_balance_adjustments:
        ba.zero_out(reason="expired")


@shared_task
def update_invoice_status():
    incomplete_invoices = Invoice.objects.filter(
        Q(payment_status=INVOICE_STATUS.UNPAID), external_payment_obj_id__isnull=False
    )
    for incomplete_invoice in incomplete_invoices:
        pp = incomplete_invoice.external_payment_obj_type
        if pp in PAYMENT_PROVIDER_MAP and PAYMENT_PROVIDER_MAP[pp].working():
            status = PAYMENT_PROVIDER_MAP[pp].update_payment_object_status(
                incomplete_invoice.external_payment_obj_id
            )
            if status == INVOICE_STATUS.PAID:
                incomplete_invoice.payment_status = INVOICE_STATUS.PAID
                incomplete_invoice.save()


@shared_task
def run_backtest(backtest_id):
    try:
        backtest = Backtest.objects.get(backtest_id=backtest_id)
        backtest_substitutions = backtest.backtest_substitutions.all()
        queries = [Q(billing_plan=x.original_plan) for x in backtest_substitutions]
        query = queries.pop()
        start_date = date_as_min_dt(backtest.start_date)
        end_date = date_as_max_dt(backtest.end_date)
        for item in queries:
            query |= item
        all_subs_time_period = (
            SubscriptionRecord.objects.filter(
                query,
                start_date__lte=end_date,
                end_date__gte=start_date,
                end_date__lte=end_date,
                organization=backtest.organization,
            )
            .prefetch_related("billing_plan")
            .prefetch_related("billing_plan__plan_components")
        )
        all_results = {
            "substitution_results": [],
        }
        logger.info(
            "Running backtest for {} substitutions".format(len(backtest_substitutions))
        )
        for subst in backtest_substitutions:
            outer_results = {
                "substitution_name": f"{str(subst.original_plan)} --> {str(subst.new_plan)}",
                "original_plan": {
                    "plan_name": str(subst.original_plan),
                    "plan_id": subst.original_plan.version_id,
                    "plan_revenue": Decimal(0),
                },
                "new_plan": {
                    "plan_name": str(subst.new_plan),
                    "plan_id": subst.new_plan.version_id,
                    "plan_revenue": Decimal(0),
                },
            }
            # since we can have at most one new plan per old plan, the old plan uniquely
            # identifies the substitutiont
            subst_subscriptions = all_subs_time_period.filter(
                billing_plan=subst.original_plan
            )
            inner_results = {
                "cumulative_revenue": {},
                "revenue_by_metric": {},
                "top_customers": {},
            }
            for sub in subst_subscriptions:
                # create if not seen
                customer = sub.customer
                if customer not in inner_results["top_customers"]:
                    inner_results["top_customers"][customer] = {
                        "original_plan_revenue": Decimal(0),
                        "new_plan_revenue": Decimal(0),
                    }
                end_date = sub.end_date
                if end_date not in inner_results["cumulative_revenue"]:
                    inner_results["cumulative_revenue"][end_date] = {
                        "original_plan_revenue": Decimal(0),
                        "new_plan_revenue": Decimal(0),
                    }
                ## PROCESS OLD SUB
                old_usage_revenue = sub.get_usage_and_revenue()
                # cumulative revenue
                inner_results["cumulative_revenue"][end_date][
                    "original_plan_revenue"
                ] += old_usage_revenue["total_amount_due"]
                # customer revenue
                inner_results["top_customers"][customer][
                    "original_plan_revenue"
                ] += old_usage_revenue["total_amount_due"]
                # per metric
                for component_pk, component_dict in old_usage_revenue["components"]:
                    metric = PlanComponent.objects.get(pk=component_pk).billable_metric
                    metric_name = metric.billable_metric_name
                    if metric_name not in inner_results["revenue_by_metric"]:
                        inner_results["revenue_by_metric"][metric_name] = {
                            "original_plan_revenue": Decimal(0),
                            "new_plan_revenue": Decimal(0),
                        }
                    inner_results["revenue_by_metric"][metric_name][
                        "original_plan_revenue"
                    ] += component_dict["revenue"]
                if "flat_fees" not in inner_results["revenue_by_metric"]:
                    inner_results["revenue_by_metric"]["flat_fees"] = {
                        "original_plan_revenue": Decimal(0),
                        "new_plan_revenue": Decimal(0),
                    }
                inner_results["revenue_by_metric"]["flat_fees"][
                    "original_plan_revenue"
                ] += old_usage_revenue["flat_amount_due"]
                ## PROCESS NEW SUB
                sub.billing_plan = subst.new_plan
                sub.save()
                new_usage_revenue = sub.get_usage_and_revenue()
                # revert it so we don't accidentally change the past lol
                sub.billing_plan = subst.original_plan
                sub.save()
                # cumulative revenue
                inner_results["cumulative_revenue"][end_date][
                    "new_plan_revenue"
                ] += new_usage_revenue["total_amount_due"]
                # customer revenue
                inner_results["top_customers"][customer][
                    "new_plan_revenue"
                ] += new_usage_revenue["total_amount_due"]
                # per metric
                for component_pk, component_dict in new_usage_revenue["components"]:
                    metric = PlanComponent.objects.get(pk=component_pk).billable_metric
                    metric_name = metric.billable_metric_name
                    if metric_name not in inner_results["revenue_by_metric"]:
                        inner_results["revenue_by_metric"][metric_name] = {
                            "new_plan_revenue": Decimal(0),
                            "original_plan_revenue": Decimal(0),
                        }
                    inner_results["revenue_by_metric"][metric_name][
                        "new_plan_revenue"
                    ] += component_dict["revenue"]
                inner_results["revenue_by_metric"]["flat_fees"][
                    "new_plan_revenue"
                ] += new_usage_revenue["flat_amount_due"]
            # change cumulative revenue to be cumulative and in fronted format
            cum_rev_dict_list = []
            cum_rev = inner_results.pop("cumulative_revenue")
            cum_rev_lst = sorted(cum_rev.items(), key=lambda x: x[0], reverse=True)
            date_cumrev_list = []
            for date, cum_rev_dict in cum_rev_lst:
                date_cumrev_list.append((date.date(), cum_rev_dict))
            cum_rev_lst = date_cumrev_list
            try:
                every_date = list(
                    dates_bwn_two_dts(cum_rev_lst[-1][0], cum_rev_lst[0][0])
                )
            except IndexError:
                every_date = []
            if cum_rev_lst:
                date, rev_dict = cum_rev_lst.pop(-1)
                last_dict = {**rev_dict, "date": date}
            else:
                rev_dict = {}
            for date in every_date:
                if (
                    date < cum_rev_lst[-1][0]
                ):  # have not reached the next data point yet, dont add
                    new_dict = last_dict.copy()
                    new_dict["date"] = date
                elif (
                    date == cum_rev_lst[-1][0]
                ):  # have reached the next data point, add it
                    date, rev_dict = cum_rev_lst.pop()
                    new_dict = {**rev_dict, "date": date}
                    new_dict["original_plan_revenue"] += last_dict[
                        "original_plan_revenue"
                    ]
                    new_dict["new_plan_revenue"] += last_dict["new_plan_revenue"]
                    last_dict = new_dict
                else:
                    raise Exception("should not be greater than the most recent date")
                cum_rev_dict_list.append(new_dict)
            inner_results["cumulative_revenue"] = cum_rev_dict_list
            # change metric revenue to be in frontend format
            metric_rev = inner_results.pop("revenue_by_metric")
            metric_rev = [
                {**rev_dict, "metric_name": metric_name}
                for metric_name, rev_dict in metric_rev.items()
            ]
            inner_results["revenue_by_metric"] = metric_rev
            # change top customers to be in frontend format
            top_cust_dict = {}
            top_cust = inner_results.pop("top_customers")
            top_original = sorted(
                top_cust.items(),
                key=lambda x: x[1]["original_plan_revenue"],
                reverse=True,
            )[:5]
            top_cust_dict["original_plan_revenue"] = [
                {
                    "customer_id": customer.customer_id,
                    "customer_name": customer.customer_name,
                    "value": rev_dict.get("original_plan_revenue", 0),
                }
                for customer, rev_dict in top_original
            ]
            top_new = sorted(
                top_cust.items(), key=lambda x: x[1]["new_plan_revenue"], reverse=True
            )[:5]
            top_cust_dict["new_plan_revenue"] = [
                {
                    "customer_id": customer.customer_id,
                    "customer_name": customer.customer_name,
                    "value": rev_dict.get("new_plan_revenue", 0),
                }
                for customer, rev_dict in top_new
            ]
            all_pct_change = []
            for customer, rev_dict in top_cust.items():
                try:
                    pct_change = (
                        rev_dict.get("new_plan_revenue", 0)
                        / rev_dict.get("original_plan_revenue", 0)
                        - 1
                    )
                except ZeroDivisionError:
                    pct_change = None
                all_pct_change.append((customer, pct_change))
            all_pct_change = sorted(
                [tup for tup in all_pct_change if tup[1] is not None],
                key=lambda x: x[1],
            )
            top_cust_dict["biggest_pct_increase"] = [
                {
                    "customer_id": customer.customer_id,
                    "customer_name": customer.customer_name,
                    "value": pct_change,
                }
                for customer, pct_change in all_pct_change[-5:]
            ][::-1]
            top_cust_dict["biggest_pct_decrease"] = [
                {
                    "customer_id": customer.customer_id,
                    "customer_name": customer.customer_name,
                    "value": pct_change,
                }
                for customer, pct_change in all_pct_change[:5]
            ]
            inner_results["top_customers"] = top_cust_dict
            # now add the inner results to the outer results
            outer_results["results"] = inner_results
            try:
                outer_results["original_plan"]["plan_revenue"] = inner_results[
                    "cumulative_revenue"
                ][-1]["original_plan_revenue"]
            except IndexError:
                outer_results["original_plan"]["plan_revenue"] = Decimal(0)
            try:
                outer_results["new_plan"]["plan_revenue"] = inner_results[
                    "cumulative_revenue"
                ][-1]["new_plan_revenue"]
            except IndexError:
                outer_results["new_plan"]["plan_revenue"] = Decimal(0)
            try:
                outer_results["pct_revenue_change"] = (
                    outer_results["new_plan"]["plan_revenue"]
                    / outer_results["original_plan"]["plan_revenue"]
                    - 1
                )
            except (ZeroDivisionError, InvalidOperation):
                outer_results["pct_revenue_change"] = None
            all_results["substitution_results"].append(outer_results)
        all_results["original_plans_revenue"] = sum(
            x["original_plan"]["plan_revenue"]
            for x in all_results["substitution_results"]
        )
        all_results["new_plans_revenue"] = sum(
            x["new_plan"]["plan_revenue"] for x in all_results["substitution_results"]
        )
        try:
            all_results["pct_revenue_change"] = (
                all_results["new_plans_revenue"] / all_results["original_plans_revenue"]
                - 1
            )
        except (ZeroDivisionError, InvalidOperation):
            all_results["pct_revenue_change"] = None
        all_results = make_all_decimals_floats(all_results)
        all_results = make_all_datetimes_dates(all_results)
        all_results = make_all_dates_times_strings(all_results)
        serializer = AllSubstitutionResultsSerializer(data=all_results)
        try:
            serializer.is_valid(raise_exception=True)
        except:
            logger.error("errors", serializer.errors, "all results", all_results)
            raise Exception
        results = make_all_dates_times_strings(serializer.validated_data)
        backtest.backtest_results = results
        backtest.status = BACKTEST_STATUS.COMPLETED
        backtest.save()
    except Exception as e:
        backtest.status = BACKTEST_STATUS.FAILED
        backtest.save()
        raise e


@shared_task
def run_generate_invoice(subscription_pk, subscription_record_pk_set, **kwargs):
    subscription = Subscription.objects.get(pk=subscription_pk)
    subscription_record_set = SubscriptionRecord.objects.filter(
        pk__in=subscription_record_pk_set, organization=subscription.organization
    )
    generate_invoice(subscription, subscription_record_set, **kwargs)
