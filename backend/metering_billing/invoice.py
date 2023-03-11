import logging
from collections.abc import Iterable
from decimal import Decimal

import sentry_sdk
from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.db.models import Q, Sum
from django.db.models.query import QuerySet

from metering_billing.kafka.producer import Producer
from metering_billing.payment_processors import PAYMENT_PROCESSOR_MAP
from metering_billing.taxes import get_lotus_tax_rates, get_taxjar_tax_rates
from metering_billing.utils import (
    calculate_end_date,
    convert_to_datetime,
    date_as_min_dt,
    now_utc,
)
from metering_billing.utils.enums import (
    CHARGEABLE_ITEM_TYPE,
    CUSTOMER_BALANCE_ADJUSTMENT_STATUS,
    INVOICE_CHARGE_TIMING_TYPE,
    ORGANIZATION_SETTING_GROUPS,
    ORGANIZATION_SETTING_NAMES,
    TAX_PROVIDER,
)
from metering_billing.webhooks import invoice_created_webhook

logger = logging.getLogger("django.server")

POSTHOG_PERSON = settings.POSTHOG_PERSON
META = settings.META
DEBUG = settings.DEBUG
# LOTUS_HOST = settings.LOTUS_HOST
# LOTUS_API_KEY = settings.LOTUS_API_KEY
# if LOTUS_HOST and LOTUS_API_KEY:
#     lotus_python.api_key = LOTUS_API_KEY
#     lotus_python.host = LOTUS_HOST
kafka_producer = Producer()


def generate_invoice(
    subscription_records,
    draft=False,
    charge_next_plan=False,
    generate_next_subscription_record=False,
    issue_date=None,
):
    """
    Generate an invoice for a subscription.
    """
    from metering_billing.models import Invoice, PricingUnit
    from metering_billing.tasks import generate_invoice_pdf_async

    if not issue_date:
        issue_date = now_utc()
    if not isinstance(subscription_records, (QuerySet, Iterable)):
        subscription_records = [subscription_records]

    if len(subscription_records) == 0:
        return None

    try:
        customers = subscription_records.values("customer").distinct().count()
    except AttributeError:
        customers = len({x.customer for x in subscription_records})
    assert (
        customers == 1
    ), "All subscription records must belong to the same customer when invoicing."
    try:
        organizations = subscription_records.values("organization").distinct().count()
    except AttributeError:
        organizations = len({x.organization for x in subscription_records})
    assert (
        organizations == 1
    ), "All subscription records must belong to the same organization when invoicing."
    organization = subscription_records[0].organization
    customer = subscription_records[0].customer
    due_date = calculate_due_date(issue_date, organization)

    try:
        distinct_currencies_pks = (
            subscription_records.order_by()
            .values_list("billing_plan__pricing_unit", flat=True)
            .distinct()
        )
        distinct_currencies = PricingUnit.objects.filter(pk__in=distinct_currencies_pks)
    except AttributeError:
        distinct_currencies = {
            x.billing_plan.pricing_unit for x in subscription_records
        }

    invoices = {}
    for currency in distinct_currencies:
        # create kwargs for invoice
        invoice_kwargs = {
            "issue_date": issue_date,
            "organization": organization,
            "customer": customer,
            "payment_status": Invoice.PaymentStatus.DRAFT
            if draft
            else Invoice.PaymentStatus.UNPAID,
            "currency": currency,
            "due_date": due_date,
        }
        # Create the invoice
        invoice = Invoice.objects.create(**invoice_kwargs)
        invoices[currency] = invoice
    for subscription_record in subscription_records:
        invoice = invoices[subscription_record.billing_plan.pricing_unit]
        invoice.subscription_records.add(subscription_record)
        # flat fee calculation for current plan
        calculate_subscription_record_flat_fees(subscription_record, invoice)
        # usage calculation
        calculate_subscription_record_usage_fees(subscription_record, invoice)
        # next plan flat fee calculation
        next_bp = find_next_billing_plan(subscription_record)
        sr_renews = check_subscription_record_renews(subscription_record, issue_date)
        if sr_renews:
            if generate_next_subscription_record:
                # actually make one, when we're actually invoicing
                next_subscription_record = create_next_subscription_record(
                    subscription_record, next_bp
                )
            else:
                # this is just a placeholder e.g. for previewing draft invoices
                next_subscription_record = subscription_record
            if charge_next_plan:
                # this can be both for actual invoicing or just for drafts to see whats next
                charge_next_plan_flat_fee(
                    subscription_record, next_subscription_record, next_bp, invoice
                )
    for invoice in invoices.values():
        apply_plan_discounts(invoice)
        apply_taxes(invoice, customer, organization, draft)
        apply_customer_balance_adjustments(invoice, customer, organization, draft)
        finalize_invoice_amount(invoice, draft)

        if not draft:
            generate_external_payment_obj(invoice)
            for subscription_record in subscription_records:
                if subscription_record.end_date <= now_utc():
                    subscription_record.fully_billed = True
                    subscription_record.save()
            try:
                generate_invoice_pdf_async.delay(invoice.pk)
            except Exception as e:
                sentry_sdk.capture_exception(e)

            invoice_created_webhook(invoice, organization)
            kafka_producer.produce_invoice(invoice)

    return list(invoices.values())


def calculate_subscription_record_flat_fees(subscription_record, invoice):
    from metering_billing.models import InvoiceLineItem, RecurringCharge

    for recurring_charge in subscription_record.billing_plan.recurring_charges.all():
        flat_fee_due = recurring_charge.calculate_amount_due(subscription_record)
        amt_already_billed = recurring_charge.amount_already_invoiced(
            subscription_record
        )
        logger.info(
            f"amt_already_billed: {amt_already_billed}, flat_fee_due: {flat_fee_due}"
        )
        if abs(float(amt_already_billed) - float(flat_fee_due)) < 0.01:
            # already billed the correct amount
            pass
        elif (
            subscription_record.end_date > invoice.issue_date
            and recurring_charge.charge_timing
            == RecurringCharge.ChargeTimingType.IN_ARREARS
        ):
            # if this is an in arrears charge, and the end date is after the invoice date, then we don't charge
            pass
        else:
            billing_plan = subscription_record.billing_plan
            billing_plan_name = billing_plan.plan.plan_name
            billing_plan_version = billing_plan.version
            start = subscription_record.start_date
            end = subscription_record.end_date
            qty = subscription_record.quantity
            if flat_fee_due > 0:
                InvoiceLineItem.objects.create(
                    name=f"{billing_plan_name} v{billing_plan_version} Flat Fee",
                    start_date=convert_to_datetime(start, date_behavior="min"),
                    end_date=convert_to_datetime(end, date_behavior="max"),
                    quantity=qty if qty > 1 else None,
                    base=flat_fee_due,
                    billing_type=recurring_charge.get_charge_timing_display(),
                    chargeable_item_type=CHARGEABLE_ITEM_TYPE.RECURRING_CHARGE,
                    invoice=invoice,
                    associated_subscription_record=subscription_record,
                    associated_plan_version=billing_plan,
                    associated_recurring_charge=recurring_charge,
                    organization=subscription_record.organization,
                )
            if amt_already_billed > 0:
                InvoiceLineItem.objects.create(
                    name=f"{billing_plan_name} v{billing_plan_version} Flat Fee Already Invoiced",
                    start_date=invoice.issue_date,
                    end_date=invoice.issue_date,
                    quantity=qty if qty > 1 else None,
                    base=-amt_already_billed,
                    billing_type=recurring_charge.get_charge_timing_display(),
                    chargeable_item_type=CHARGEABLE_ITEM_TYPE.RECURRING_CHARGE,
                    invoice=invoice,
                    associated_subscription_record=subscription_record,
                    associated_plan_version=billing_plan,
                    associated_recurring_charge=recurring_charge,
                    organization=subscription_record.organization,
                )


def calculate_subscription_record_usage_fees(subscription_record, invoice):
    from metering_billing.models import InvoiceLineItem

    billing_plan = subscription_record.billing_plan
    # only calculate this for parent plans! addons should never calculate
    if subscription_record.invoice_usage_charges:
        for plan_component in billing_plan.plan_components.all():
            usg_rev = plan_component.calculate_total_revenue(subscription_record)
            qty = usg_rev["usage_qty"]
            rev = usg_rev["revenue"]
            logger.info(
                f"plan_component: {plan_component.billable_metric.billable_metric_name} usage_qty: {qty} revenue: {rev}",
            )
            InvoiceLineItem.objects.create(
                name=str(plan_component.billable_metric.billable_metric_name),
                start_date=subscription_record.usage_start_date,
                end_date=subscription_record.end_date,
                quantity=usg_rev["usage_qty"] or 0,
                base=usg_rev["revenue"],
                billing_type=INVOICE_CHARGE_TIMING_TYPE.IN_ARREARS,
                chargeable_item_type=CHARGEABLE_ITEM_TYPE.USAGE_CHARGE,
                invoice=invoice,
                associated_subscription_record=subscription_record,
                associated_plan_version=billing_plan,
                organization=subscription_record.organization,
            )


def find_next_billing_plan(subscription_record):
    if subscription_record.billing_plan.transition_to:
        next_bp = subscription_record.billing_plan.transition_to.display_version
    elif subscription_record.billing_plan.replace_with:
        next_bp = subscription_record.billing_plan.replace_with
    else:
        next_bp = subscription_record.billing_plan
    return next_bp


def check_subscription_record_renews(subscription_record, issue_date):
    if subscription_record.end_date < issue_date:
        return False
    if subscription_record.parent is None:
        return subscription_record.auto_renew
    else:
        return subscription_record.auto_renew and subscription_record.parent.auto_renew


def create_next_subscription_record(subscription_record, next_bp):
    from metering_billing.models import SubscriptionRecord

    timezone = subscription_record.customer.timezone
    subrec_dict = {
        "organization": subscription_record.organization,
        "customer": subscription_record.customer,
        "billing_plan": next_bp,
        "start_date": date_as_min_dt(
            subscription_record.end_date + relativedelta(days=1), timezone
        ),
        "is_new": False,
        "quantity": subscription_record.quantity,
    }
    next_subscription_record = SubscriptionRecord.objects.create(**subrec_dict)
    for f in subscription_record.filters.all():
        next_subscription_record.filters.add(f)
    return next_subscription_record


def charge_next_plan_flat_fee(
    subscription_record, next_subscription_record, next_bp, invoice
):
    from metering_billing.models import InvoiceLineItem, RecurringCharge

    timezone = subscription_record.customer.timezone
    for recurring_charge in next_bp.recurring_charges.all():
        charge_in_advance = (
            recurring_charge.charge_timing
            == RecurringCharge.ChargeTimingType.IN_ADVANCE
        )
        if next_bp.plan.addon_spec:
            next_bp_duration = find_next_billing_plan(
                subscription_record.parent
            ).plan.plan_duration
            name = f"{next_bp.plan.plan_name} ({recurring_charge.name}) - Next Period [Add-on]"
        else:
            next_bp_duration = next_bp.plan.plan_duration
            name = f"{next_bp.plan.plan_name} v{next_bp.version} ({recurring_charge.name}) - Next Period"
        if charge_in_advance and recurring_charge.amount > 0:
            new_start = date_as_min_dt(
                subscription_record.end_date + relativedelta(days=1), timezone
            )
            base = recurring_charge.amount * next_subscription_record.quantity
            qty = next_subscription_record.quantity
            qty = qty if qty > 1 else None
            InvoiceLineItem.objects.create(
                name=name,
                start_date=new_start,
                end_date=calculate_end_date(next_bp_duration, new_start, timezone),
                quantity=qty,
                base=base,
                billing_type=INVOICE_CHARGE_TIMING_TYPE.IN_ADVANCE,
                chargeable_item_type=CHARGEABLE_ITEM_TYPE.RECURRING_CHARGE,
                invoice=invoice,
                associated_subscription_record=next_subscription_record,
                associated_plan_version=next_bp,
                organization=subscription_record.organization,
            )


def apply_plan_discounts(invoice):
    from metering_billing.models import (
        InvoiceLineItem,
        InvoiceLineItemAdjustment,
        PlanVersion,
        SubscriptionRecord,
    )
    from metering_billing.utils.enums import PRICE_ADJUSTMENT_TYPE

    distinct_pvs = (
        invoice.line_items.filter(
            associated_subscription_record__isnull=False,
            associated_plan_version__isnull=False,
        )
        .values("associated_plan_version")
        .distinct()
    )
    pvs = PlanVersion.objects.filter(
        id__in=[pv["associated_plan_version"] for pv in distinct_pvs]
    ).select_related("price_adjustment")
    for pv in pvs:
        if pv.price_adjustment:
            price_adj_name = str(pv.price_adjustment)
            if (
                pv.price_adjustment.price_adjustment_type
                == PRICE_ADJUSTMENT_TYPE.PERCENTAGE
            ):
                for line_item in invoice.line_items.filter(associated_plan_version=pv):
                    discount_amount = pv.price_adjustment.apply(line_item.base)
                    InvoiceLineItemAdjustment.objects.create(
                        invoice_line_item=line_item,
                        adjustment_type=InvoiceLineItemAdjustment.AdjustmentType.PLAN_ADJUSTMENT,
                        amount=discount_amount,
                        account=21000,
                        organization=invoice.organization,
                    )
            else:
                distinct_srs = (
                    invoice.line_items.filter(associated_plan_version=pv)
                    .values("associated_subscription_record")
                    .distinct()
                )
                sub_records = SubscriptionRecord.objects.filter(
                    id__in=[sr["associated_subscription_record"] for sr in distinct_srs]
                )
                for sr in sub_records:
                    if (
                        pv.price_adjustment.price_adjustment_type
                        == PRICE_ADJUSTMENT_TYPE.FIXED
                    ):
                        billing_line_items = invoice.line_items.filter(
                            ~Q(
                                chargeable_item_type=CHARGEABLE_ITEM_TYPE.PLAN_ADJUSTMENT
                            ),
                            associated_subscription_record=sr,
                            associated_plan_version=pv,
                        )
                        print("billing_line_items", billing_line_items)
                        total_due = (
                            billing_line_items.aggregate(tot=Sum("base"))["tot"] or 0
                        )
                        print("total_due", total_due)
                        past_discount_items = InvoiceLineItem.objects.filter(
                            chargeable_item_type=CHARGEABLE_ITEM_TYPE.PLAN_ADJUSTMENT,
                            associated_subscription_record=sr,
                            associated_plan_version=pv,
                        )
                        print("past_discount_items", past_discount_items)
                        new_total = pv.price_adjustment.apply(total_due)
                        print("new_total", new_total)
                        already_discounted = (
                            past_discount_items.aggregate(tot=Sum("base"))["tot"] or 0
                        )
                        print("already_discounted", already_discounted)
                        discount_amount = new_total - total_due
                        print("discount_amount", discount_amount)
                        real_discount = discount_amount - already_discounted
                        print("real_discount", real_discount)
                    else:
                        # this is everything we've charged with the plan/subscription
                        all_plan_line_items = InvoiceLineItem.objects.filter(
                            ~Q(
                                chargeable_item_type=CHARGEABLE_ITEM_TYPE.PLAN_ADJUSTMENT
                            ),
                            associated_subscription_record=sr,
                            associated_plan_version=pv,
                        )
                        total_due = (
                            all_plan_line_items.aggregate(tot=Sum("base"))["tot"] or 0
                        )
                        # here, we take it to a fixed price
                        new_total = pv.price_adjustment.apply(total_due)
                        # the total discount is the difference between the two
                        discount_amount = new_total - total_due
                        # but we need to make sure we don't double discount
                        past_discount_items = InvoiceLineItem.objects.filter(
                            chargeable_item_type=CHARGEABLE_ITEM_TYPE.PLAN_ADJUSTMENT,
                            associated_subscription_record=sr,
                            associated_plan_version=pv,
                        )
                        already_discounted = (
                            past_discount_items.aggregate(tot=Sum("base"))["tot"] or 0
                        )
                        real_discount = discount_amount - already_discounted
                    if real_discount != 0:
                        InvoiceLineItem.objects.create(
                            name=f"{pv.plan.plan_name} {price_adj_name}",
                            start_date=invoice.issue_date,
                            end_date=invoice.issue_date,
                            quantity=None,
                            base=real_discount,
                            billing_type=INVOICE_CHARGE_TIMING_TYPE.IN_ARREARS,
                            chargeable_item_type=CHARGEABLE_ITEM_TYPE.PLAN_ADJUSTMENT,
                            invoice=invoice,
                            associated_subscription_record=sr,
                            organization=sr.organization,
                        )


def apply_taxes(invoice, customer, organization, draft):
    """
    Apply taxes to an invoice
    """
    from metering_billing.models import Invoice, InvoiceLineItemAdjustment, Organization

    if invoice.payment_status == Invoice.PaymentStatus.PAID:
        return
    order_of_tax_providers_to_check = (
        customer.get_tax_provider_values() + organization.get_tax_provider_values()
    )
    if len(order_of_tax_providers_to_check) == 0:
        return
    subscription_records = {
        x.associated_subscription_record
        for x in invoice.line_items.all().select_related(
            "associated_subscription_record"
        )
    }

    tax_rate_dict = {}
    for sr in subscription_records:
        current_base = (
            invoice.line_items.filter(associated_subscription_record=sr).aggregate(
                tot=Sum("base")
            )["tot"]
            or 0
        )
        plan = sr.billing_plan.plan
        tax_rate = tax_rate_dict.get(plan, None)
        if tax_rate is None or not draft:
            for tax_provider in order_of_tax_providers_to_check:
                if tax_provider == TAX_PROVIDER.LOTUS:
                    txr, success = get_lotus_tax_rates(
                        customer,
                        organization,
                    )
                    if success:
                        tax_rate = txr
                        break
                elif (
                    tax_provider == TAX_PROVIDER.TAXJAR
                    and organization.organization_type
                    == Organization.OrganizationType.PRODUCTION
                ):
                    txr, success = get_taxjar_tax_rates(
                        customer, organization, plan, draft, current_base
                    )
                    if success:
                        tax_rate = txr
                        break
        tax_rate = tax_rate or Decimal(0)
        tax_rate_dict[plan] = tax_rate
        if tax_rate == 0:
            continue

        for line_item in invoice.line_items.filter(associated_subscription_record=sr):
            tax_amount = line_item.base * (tax_rate / Decimal(100))
            InvoiceLineItemAdjustment.objects.create(
                invoice_line_item=line_item,
                adjustment_type=InvoiceLineItemAdjustment.AdjustmentType.SALES_TAX,
                amount=tax_amount,
                account=41100,
                organization=invoice.organization,
            )


def apply_customer_balance_adjustments(invoice, customer, organization, draft):
    """
    Apply customer balance adjustments to an invoice
    """
    from metering_billing.models import (
        CustomerBalanceAdjustment,
        Invoice,
        InvoiceLineItem,
    )

    issue_date = invoice.issue_date
    issue_date_fmt = issue_date.strftime("%Y-%m-%d")
    if invoice.payment_status == Invoice.PaymentStatus.PAID or draft:
        return
    amount = invoice.line_items.aggregate(tot=Sum("amount"))["tot"] or 0
    if amount < 0:
        InvoiceLineItem.objects.create(
            name="Granted Credit",
            start_date=invoice.issue_date,
            end_date=invoice.issue_date,
            quantity=None,
            base=-amount,
            billing_type=INVOICE_CHARGE_TIMING_TYPE.ONE_TIME,
            chargeable_item_type=CHARGEABLE_ITEM_TYPE.CUSTOMER_ADJUSTMENT,
            invoice=invoice,
            organization=organization,
        )
        if not draft:
            CustomerBalanceAdjustment.objects.create(
                organization=organization,
                customer=customer,
                amount=-amount,
                description=f"Credit Grant from invoice {invoice.invoice_number} generated on {issue_date_fmt}",
                created=issue_date,
                effective_at=issue_date,
                status=CUSTOMER_BALANCE_ADJUSTMENT_STATUS.ACTIVE,
            )
    elif amount > 0:
        customer_balance = CustomerBalanceAdjustment.get_pricing_unit_balance(
            customer, invoice.currency
        )
        balance_adjustment = min(amount, customer_balance)
        if balance_adjustment > 0:
            if draft:
                leftover = 0
            else:
                leftover = CustomerBalanceAdjustment.draw_down_amount(
                    customer,
                    balance_adjustment,
                    invoice.currency,
                    description=f"Balance decrease from invoice {invoice.invoice_number} generated on {issue_date_fmt}",
                )
            if -balance_adjustment + leftover != 0:
                InvoiceLineItem.objects.create(
                    name="Applied Credit",
                    start_date=issue_date,
                    end_date=issue_date,
                    quantity=None,
                    base=-balance_adjustment + leftover,
                    billing_type=INVOICE_CHARGE_TIMING_TYPE.ONE_TIME,
                    chargeable_item_type=CHARGEABLE_ITEM_TYPE.CUSTOMER_ADJUSTMENT,
                    invoice=invoice,
                    organization=organization,
                )


def generate_balance_adjustment_invoice(balance_adjustment, draft=False):
    """
    Generate an invoice for a subscription.
    """
    from metering_billing.models import Invoice, InvoiceLineItem
    from metering_billing.tasks import generate_invoice_pdf_async

    issue_date = balance_adjustment.created
    customer = balance_adjustment.customer
    organization = balance_adjustment.organization
    due_date = calculate_due_date(issue_date, organization)
    # create kwargs for invoice
    invoice_kwargs = {
        "issue_date": issue_date,
        "organization": organization,
        "customer": customer,
        "payment_status": Invoice.PaymentStatus.DRAFT
        if draft
        else Invoice.PaymentStatus.UNPAID,
        "currency": balance_adjustment.amount_paid_currency,
        "due_date": due_date,
    }
    # Create the invoice
    invoice = Invoice.objects.create(**invoice_kwargs)

    # Create the invoice line item
    InvoiceLineItem.objects.create(
        name=f"Credit Grant: {balance_adjustment.amount_paid_currency.symbol}{balance_adjustment.amount}",
        start_date=issue_date,
        end_date=issue_date,
        quantity=None,
        base=balance_adjustment.amount_paid,
        billing_type=INVOICE_CHARGE_TIMING_TYPE.ONE_TIME,
        chargeable_item_type=CHARGEABLE_ITEM_TYPE.ONE_TIME_CHARGE,
        invoice=invoice,
        organization=organization,
    )

    apply_taxes(invoice, customer, organization, draft)
    finalize_invoice_amount(invoice, draft)

    if not draft:
        generate_external_payment_obj(invoice)
        try:
            generate_invoice_pdf_async.delay(invoice.pk)
        except Exception as e:
            sentry_sdk.capture_exception(e)
        invoice_created_webhook(invoice, organization)
        kafka_producer.produce_invoice(invoice)

    return invoice


### GENERAL UTILITY FUNCTIONS ###


def generate_external_payment_obj(invoice):
    customer = invoice.customer
    pp = customer.payment_provider
    if pp in PAYMENT_PROCESSOR_MAP and PAYMENT_PROCESSOR_MAP[pp].working():
        pp_connector = PAYMENT_PROCESSOR_MAP[pp]
        customer_conn = pp_connector.customer_connected(customer)
        org_conn = pp_connector.organization_connected(invoice.organization)
        if customer_conn and org_conn:
            external_id = pp_connector.create_payment_object(invoice)
            if external_id:
                invoice.external_payment_obj_id = external_id
                invoice.external_payment_obj_type = pp
                invoice.save()


def calculate_due_date(issue_date, organization):
    from metering_billing.models import OrganizationSetting

    due_date = issue_date
    grace_period_setting = OrganizationSetting.objects.filter(
        organization=organization,
        setting_name=ORGANIZATION_SETTING_NAMES.PAYMENT_GRACE_PERIOD,
        setting_group=ORGANIZATION_SETTING_GROUPS.BILLING,
    ).first()
    if grace_period_setting:
        due_date += relativedelta(
            days=int(grace_period_setting.setting_values["value"])
        )
        return due_date


def finalize_invoice_amount(invoice, draft):
    from metering_billing.models import Invoice

    invoice.amount = invoice.line_items.aggregate(tot=Sum("amount"))["tot"] or 0
    if abs(invoice.amount) < 0.01 and not draft:
        invoice.payment_status = Invoice.PaymentStatus.PAID
    invoice.save()
