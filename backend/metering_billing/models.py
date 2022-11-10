import datetime
import uuid
from decimal import Decimal
from typing import TypedDict

from dateutil import parser
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Count, Q, Sum
from django.db.models.constraints import UniqueConstraint
from djmoney.models.fields import MoneyField
from metering_billing.invoice import generate_invoice
from metering_billing.utils import (
    backtest_uuid,
    calculate_end_date,
    convert_to_decimal,
    customer_uuid,
    dates_bwn_two_dts,
    invoice_uuid,
    metric_uuid,
    now_plus_day,
    now_utc,
    periods_bwn_twodates,
    plan_uuid,
    plan_version_uuid,
    product_uuid,
    subscription_uuid,
)
from metering_billing.utils.enums import (
    BACKTEST_STATUS,
    CATEGORICAL_FILTER_OPERATORS,
    EVENT_TYPE,
    FLAT_FEE_BILLING_TYPE,
    INVOICE_STATUS,
    MAKE_PLAN_VERSION_ACTIVE_TYPE,
    METRIC_AGGREGATION,
    METRIC_GRANULARITY,
    METRIC_TYPE,
    NUMERIC_FILTER_OPERATORS,
    PAYMENT_PLANS,
    PAYMENT_PROVIDERS,
    PLAN_DURATION,
    PLAN_STATUS,
    PLAN_VERSION_STATUS,
    PRICE_ADJUSTMENT_TYPE,
    PRODUCT_STATUS,
    REPLACE_IMMEDIATELY_TYPE,
    SUBSCRIPTION_STATUS,
    USAGE_BILLING_FREQUENCY,
    USAGE_CALC_GRANULARITY,
)
from rest_framework_api_key.models import AbstractAPIKey
from simple_history.models import HistoricalRecords


class Organization(models.Model):
    company_name = models.CharField(max_length=100, blank=False, null=False)
    payment_provider_ids = models.JSONField(default=dict, blank=True, null=True)
    created = models.DateField(default=now_utc)
    payment_plan = models.CharField(
        max_length=40,
        choices=PAYMENT_PLANS.choices,
        default=PAYMENT_PLANS.SELF_HOSTED_FREE,
    )
    history = HistoricalRecords()

    def __str__(self):
        return self.company_name

    def save(self, *args, **kwargs):
        for k, _ in self.payment_provider_ids.items():
            if k not in PAYMENT_PROVIDERS:
                raise ValueError(
                    f"Payment provider {k} is not supported. Supported payment providers are: {PAYMENT_PROVIDERS}"
                )
        super(Organization, self).save(*args, **kwargs)

    @property
    def users(self):
        return self.org_users


class Alert(models.Model):
    type = models.CharField(max_length=20, default="webhook")
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="org_alerts"
    )
    webhook_url = models.CharField(max_length=300, blank=True, null=True)
    name = models.CharField(max_length=100, default=" ")
    history = HistoricalRecords()


class User(AbstractUser):
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="org_users",
    )
    email = models.EmailField(unique=True)
    history = HistoricalRecords()


class Product(models.Model):
    """
    This model is used to store the products that are available to be purchased.
    """

    name = models.CharField(max_length=100, null=False, blank=False)
    description = models.TextField(null=True, blank=True)
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="org_products"
    )
    product_id = models.CharField(default=product_uuid, max_length=100, unique=True)
    status = models.CharField(choices=PRODUCT_STATUS.choices, max_length=40)
    history = HistoricalRecords()

    class Meta:
        unique_together = ("organization", "product_id")

    def __str__(self):
        return f"{self.name}"


class Customer(models.Model):
    """
    Customer Model

    This model represents a customer.

    Attributes:
        name (str): The name of the customer.
        customer_id (str): A :model:`metering_billing.Organization`'s internal designation for the customer.
        payment_provider_id (str): The id of the payment provider the customer is using.
        properties (dict): An extendable dictionary of properties, useful for filtering, etc.
    """

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, null=False, related_name="org_customers"
    )
    customer_name = models.CharField(max_length=100)
    email = models.EmailField(max_length=100, blank=True, null=True)
    customer_id = models.CharField(
        max_length=50, blank=True, null=False, default=customer_uuid
    )
    integrations = models.JSONField(default=dict, blank=True, null=True)
    properties = models.JSONField(default=dict, blank=True, null=True)
    history = HistoricalRecords()

    class Meta:
        unique_together = ("organization", "customer_id")

    def __str__(self) -> str:
        return str(self.customer_name) + " " + str(self.customer_id)

    def save(self, *args, **kwargs):
        for k, v in self.integrations.items():
            if k not in PAYMENT_PROVIDERS:
                raise ValueError(
                    f"Payment provider {k} is not supported. Supported payment providers are: {PAYMENT_PROVIDERS}"
                )
            id = v.get("id")
            if id is None:
                raise ValueError(f"Payment provider {k} id was not provided")
        super(Customer, self).save(*args, **kwargs)

    def get_billing_plan_names(self) -> str:
        subscription_set = Subscription.objects.filter(
            customer=self, status=SUBSCRIPTION_STATUS.ACTIVE
        )
        if subscription_set is None:
            return "None"
        return [str(sub.billing_plan) for sub in subscription_set]

    def get_usage_and_revenue(self):
        customer_subscriptions = (
            Subscription.objects.filter(
                customer=self,
                status=SUBSCRIPTION_STATUS.ACTIVE,
                organization=self.organization,
            )
            .prefetch_related("billing_plan__components")
            .prefetch_related("billing_plan__components__billable_metric")
            .select_related("billing_plan")
        )
        subscription_usages = {"subscriptions": []}
        for subscription in customer_subscriptions:
            sub_dict = subscription.get_usage_and_revenue()
            del sub_dict["components"]
            sub_dict["billing_plan_name"] = subscription.billing_plan.plan.plan_name
            subscription_usages["subscriptions"].append(sub_dict)

        return subscription_usages

    def get_currency_balance(self, currency):
        now = now_utc()
        balance = self.customer_balance_adjustments.filter(
            Q(expires_at__gte=now) | Q(expires_at__isnull=True),
            effective_at__lte=now,
            amount_currency=currency,
        ).aggregate(balance=Sum("amount"))["balance"] or Decimal(0)
        return balance


class CustomerBalanceAdjustment(models.Model):
    """
    This model is used to store the customer balance adjustments.
    """

    customer = models.ForeignKey(
        Customer, on_delete=models.CASCADE, related_name="customer_balance_adjustments"
    )
    amount = MoneyField(decimal_places=10, max_digits=20)
    description = models.TextField(null=True, blank=True)
    created = models.DateTimeField(default=now_utc)
    effective_at = models.DateTimeField(default=now_utc)
    expires_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.customer.customer_name} {self.amount} {self.created}"

    class Meta:
        ordering = ["-created"]

    class Meta:
        unique_together = ("customer", "created")

    def __str__(self):
        return f"{self.customer} {self.amount} {self.created}"

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError(
                "you may not edit an existing %s" % self._meta.model_name
            )
        super(CustomerBalanceAdjustment, self).save(*args, **kwargs)


class Event(models.Model):
    """
    Event object. An explanation of the Event's fields follows:
    event_name: The type of event that occurred.
    time_created: The time at which the event occurred.
    customer: The customer that the event occurred to.
    idempotency_id: A unique identifier for the event.
    """

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, null=False, related_name="+"
    )
    customer = models.ForeignKey(
        Customer, on_delete=models.CASCADE, null=False, related_name="+"
    )
    event_name = models.CharField(max_length=200, null=False)
    time_created = models.DateTimeField()
    properties = models.JSONField(default=dict, blank=True, null=True)
    idempotency_id = models.CharField(max_length=255, unique=True)

    class Meta:
        ordering = ["time_created", "idempotency_id"]

    def __str__(self):
        return str(self.event_name) + "-" + str(self.idempotency_id)


class NumericFilter(models.Model):
    property_name = models.CharField(max_length=100)
    operator = models.CharField(max_length=10, choices=NUMERIC_FILTER_OPERATORS.choices)
    comparison_value = models.FloatField()


class CategoricalFilter(models.Model):
    property_name = models.CharField(max_length=100)
    operator = models.CharField(
        max_length=10, choices=CATEGORICAL_FILTER_OPERATORS.choices
    )
    comparison_value = models.JSONField()


class BillableMetric(models.Model):
    # meta
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        null=False,
        related_name="org_billable_metrics",
    )
    event_name = models.CharField(max_length=200)
    metric_type = models.CharField(
        max_length=20,
        choices=METRIC_TYPE.choices,
        default=METRIC_TYPE.COUNTER,
    )
    properties = models.JSONField(default=dict, blank=True, null=True)
    billable_metric_name = models.CharField(
        max_length=200, null=False, blank=True, default=metric_uuid
    )
    event_type = models.CharField(
        max_length=20,
        choices=EVENT_TYPE.choices,
        default=EVENT_TYPE.TOTAL,
        null=True,
        blank=True,
    )

    # metric type specific
    usage_aggregation_type = models.CharField(
        max_length=10,
        choices=METRIC_AGGREGATION.choices,
        default=METRIC_AGGREGATION.COUNT,
    )
    billable_aggregation_type = models.CharField(
        max_length=10,
        choices=METRIC_AGGREGATION.choices,
        default=METRIC_AGGREGATION.SUM,
        null=True,
        blank=True,
    )
    property_name = models.CharField(max_length=200, blank=True, null=True)
    granularity = models.CharField(
        choices=METRIC_GRANULARITY.choices,
        default=METRIC_GRANULARITY.TOTAL,
        max_length=10,
        null=True,
        blank=True,
    )

    # filters
    numeric_filters = models.ManyToManyField(NumericFilter, blank=True)
    categorical_filters = models.ManyToManyField(CategoricalFilter, blank=True)

    # records
    history = HistoricalRecords()

    class Meta:
        unique_together = ("organization", "billable_metric_name")

    def __str__(self):
        return self.billable_metric_name

    def get_aggregation_type(self):
        return self.aggregation_type

    def get_usage(
        self,
        start_date,
        end_date,
        granularity,
        customer=None,
    ) -> dict[Customer.customer_name, dict[datetime.datetime, float]]:
        from metering_billing.billable_metrics import METRIC_HANDLER_MAP

        handler = METRIC_HANDLER_MAP[self.metric_type](self)
        usage = handler.get_usage(
            results_granularity=granularity,
            start_date=start_date,
            end_date=end_date,
            customer=customer,
        )

        return usage

    def get_current_usage(self, subscription):
        from metering_billing.billable_metrics import METRIC_HANDLER_MAP

        handler = METRIC_HANDLER_MAP[self.metric_type](self)

        usage = handler.get_current_usage(subscription)

        return usage

    def get_earned_usage_per_day(self, subscription):
        from metering_billing.billable_metrics import METRIC_HANDLER_MAP

        handler = METRIC_HANDLER_MAP[self.metric_type](self)

        usage = handler.get_earned_usage_per_day(subscription)

        return usage


class UsageRevenueSummary(TypedDict):
    revenue: Decimal
    usage_qty: Decimal


class PlanComponent(models.Model):
    billable_metric = models.ForeignKey(
        BillableMetric, on_delete=models.CASCADE, related_name="+"
    )
    free_metric_units = models.DecimalField(
        decimal_places=10, max_digits=20, blank=True, null=True
    )
    cost_per_batch = models.DecimalField(
        decimal_places=10, max_digits=20, blank=True, null=True
    )
    metric_units_per_batch = models.DecimalField(
        decimal_places=10, max_digits=20, blank=True, null=True
    )
    max_metric_units = models.DecimalField(
        decimal_places=10, max_digits=20, blank=True, null=True
    )

    def __str__(self):
        return str(self.billable_metric)

    def calculate_total_revenue(
        self, subscription
    ) -> dict[datetime.datetime, UsageRevenueSummary]:
        billable_metric = self.billable_metric
        usage = billable_metric.get_usage(
            granularity=USAGE_CALC_GRANULARITY.TOTAL,
            start_date=subscription.start_date,
            end_date=subscription.end_date,
            customer=subscription.customer,
        )
        # extract usage
        usage = usage.get(subscription.customer.customer_name, {})
        if len(usage) > 1:  # this means it's a stateful metric
            usage_qty = sum(usage.values())
            revenue = 0
            for usage in usage.values():
                billable_units = max(usage - self.free_metric_units, 0)
                billable_batches = billable_units // self.metric_units_per_batch
                usage_revenue = billable_batches * self.cost_per_batch
                revenue += convert_to_decimal(usage_revenue)
        elif len(usage) == 1:
            _, usage_qty = list(usage.items())[0]
            usage_qty = convert_to_decimal(usage_qty)
            if (
                self.cost_per_batch == 0
                or self.cost_per_batch is None
                or self.metric_units_per_batch == 0
                or self.metric_units_per_batch is None
            ):
                revenue = Decimal(0)
            else:
                free_units = self.free_metric_units or Decimal(0)
                billable_units = max(usage_qty - free_units, 0)
                billable_batches = billable_units // self.metric_units_per_batch
                usage_revenue = billable_batches * self.cost_per_batch
                revenue = convert_to_decimal(usage_revenue)
        else:
            usage_qty = Decimal(0)
            revenue = Decimal(0)

        # calculate revenue

        # wrap up and return
        revenue_dict = {
            "revenue": revenue,
            "usage_qty": convert_to_decimal(usage_qty),
        }

        return revenue_dict

    def calculate_earned_revenue_per_day(
        self, subscription
    ) -> dict[datetime.datetime, UsageRevenueSummary]:
        billable_metric = self.billable_metric
        usage = billable_metric.get_earned_usage_per_day(subscription)

        usage = usage.get(subscription.customer.customer_name, {})

        period_revenue_dict = {
            period: {}
            for period in periods_bwn_twodates(
                USAGE_CALC_GRANULARITY.DAILY,
                subscription.start_date,
                subscription.end_date,
            )
        }
        free_units_usage_left = self.free_metric_units
        remainder_billable_units = 0
        for period in period_revenue_dict:
            period_usage = usage.get(period, 0)
            qty = convert_to_decimal(period_usage)
            period_revenue_dict[period] = {"usage_qty": qty, "revenue": 0}
            if (
                self.cost_per_batch == 0
                or self.cost_per_batch is None
                or self.metric_units_per_batch == 0
                or self.metric_units_per_batch is None
            ):
                continue
            else:
                billable_units = max(
                    qty - free_units_usage_left + remainder_billable_units, 0
                )
                billable_batches = billable_units // self.metric_units_per_batch
                remainder_billable_units = (
                    billable_units - billable_batches * self.metric_units_per_batch
                )
                free_units_usage_left = max(0, free_units_usage_left - qty)
                if billable_metric.metric_type == METRIC_TYPE.STATEFUL:
                    usage_revenue = (
                        billable_batches
                        * self.cost_per_batch
                        / len(period_revenue_dict)
                    )
                else:
                    usage_revenue = billable_batches * self.cost_per_batch
                period_revenue_dict[period]["revenue"] = convert_to_decimal(
                    usage_revenue
                )
                if billable_metric.metric_type == METRIC_TYPE.STATEFUL:
                    free_units_usage_left = self.free_metric_units
                    remainder_billable_units = 0
        return period_revenue_dict


class Feature(models.Model):
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, null=False, related_name="org_features"
    )
    feature_name = models.CharField(max_length=200, null=False)
    feature_description = models.CharField(max_length=200, blank=True, null=True)

    class Meta:
        unique_together = ("organization", "feature_name")

    def __str__(self):
        return str(self.feature_name)


class Invoice(models.Model):
    cost_due = MoneyField(
        decimal_places=10, max_digits=20, default_currency="USD", default=0.0
    )
    issue_date = models.DateTimeField(max_length=100, default=now_utc)
    invoice_pdf = models.FileField(upload_to="invoices/", null=True, blank=True)
    org_connected_to_cust_payment_provider = models.BooleanField(default=False)
    cust_connected_to_payment_provider = models.BooleanField(default=False)
    payment_status = models.CharField(max_length=40, choices=INVOICE_STATUS.choices)
    invoice_id = models.CharField(
        max_length=100, null=False, blank=True, default=invoice_uuid, unique=True
    )
    external_payment_obj = models.JSONField(default=dict, blank=True, null=True)
    external_payment_obj_id = models.CharField(max_length=200, blank=True, null=True)
    external_payment_obj_type = models.CharField(
        choices=PAYMENT_PROVIDERS.choices, max_length=40, null=True, blank=True
    )
    line_items = models.JSONField()
    organization = models.JSONField()
    customer = models.JSONField()
    subscription = models.JSONField()
    history = HistoricalRecords()

    def __str__(self):
        return str(self.invoice_id)


class APIToken(AbstractAPIKey):
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="org_api_keys"
    )
    name = models.CharField(max_length=200, default="latest_token")

    class Meta(AbstractAPIKey.Meta):
        verbose_name = "API Token"
        verbose_name_plural = "API Tokens"

    def __str__(self):
        return str(self.name) + " " + str(self.organization.company_name)


class OrganizationInviteToken(models.Model):
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="user_invite_token"
    )
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="org_invite_token",
    )
    email = models.EmailField()
    token = models.CharField(max_length=250, default=uuid.uuid4)
    expire_at = models.DateTimeField(default=now_plus_day, null=False, blank=False)


class PlanVersion(models.Model):
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        null=False,
        related_name="org_plan_versions",
    )
    description = models.CharField(max_length=200, null=True, blank=True)
    version = models.PositiveSmallIntegerField()
    flat_fee_billing_type = models.CharField(
        max_length=40, choices=FLAT_FEE_BILLING_TYPE.choices
    )
    usage_billing_frequency = models.CharField(
        max_length=40, choices=USAGE_BILLING_FREQUENCY.choices, null=True, blank=True
    )
    plan = models.ForeignKey("Plan", on_delete=models.CASCADE, related_name="versions")
    status = models.CharField(max_length=40, choices=PLAN_VERSION_STATUS.choices)
    replace_with = models.ForeignKey(
        "self", on_delete=models.CASCADE, null=True, blank=True
    )
    flat_rate = MoneyField(decimal_places=10, max_digits=20, default_currency="USD")
    components = models.ManyToManyField(PlanComponent, blank=True)
    features = models.ManyToManyField(Feature, blank=True)
    price_adjustment = models.ForeignKey(
        "PriceAdjustment", on_delete=models.CASCADE, null=True, blank=True
    )
    created_on = models.DateTimeField(default=now_utc)
    created_by = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="created_plan_versions",
        null=True,
        blank=True,
    )
    version_id = models.CharField(max_length=250, default=plan_version_uuid)
    history = HistoricalRecords()

    class Meta:
        unique_together = ("organization", "version_id")

    def __str__(self) -> str:
        return str(self.plan) + " v" + str(self.version)

    def num_active_subs(self):
        cnt = self.bp_subscriptions.filter(status=SUBSCRIPTION_STATUS.ACTIVE).count()
        return cnt


class PriceAdjustment(models.Model):
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="org_price_adjustments"
    )
    price_adjustment_name = models.CharField(max_length=200, null=False)
    price_adjustment_description = models.CharField(
        max_length=200, blank=True, null=True
    )
    price_adjustment_type = models.CharField(
        max_length=40, choices=PRICE_ADJUSTMENT_TYPE.choices
    )
    price_adjustment_amount = models.DecimalField(
        max_digits=20,
        decimal_places=10,
    )

    def __str__(self):
        if self.price_adjustment_name != "":
            return str(self.price_adjustment_name)
        else:
            return (
                str(self.price_adjustment_amount)
                + " "
                + str(self.price_adjustment_type)
            )

    def apply(self, amount):
        if self.price_adjustment_type == PRICE_ADJUSTMENT_TYPE.PERCENTAGE:
            return amount * (1 + self.price_adjustment_amount / 100)
        elif self.price_adjustment_type == PRICE_ADJUSTMENT_TYPE.FIXED:
            return amount + self.price_adjustment_amount
        elif self.price_adjustment_type == PRICE_ADJUSTMENT_TYPE.PRICE_OVERRIDE:
            return self.price_adjustment_amount


class Plan(models.Model):
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="org_plans"
    )
    plan_name = models.CharField(max_length=100, null=False, blank=False)
    plan_duration = models.CharField(choices=PLAN_DURATION.choices, max_length=40)
    display_version = models.ForeignKey(
        "PlanVersion", on_delete=models.CASCADE, related_name="+", null=True, blank=True
    )
    parent_product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="product_plans",
        null=True,
        blank=True,
    )
    status = models.CharField(
        choices=PLAN_STATUS.choices, max_length=40, default=PLAN_STATUS.ACTIVE
    )
    plan_id = models.CharField(default=plan_uuid, max_length=100, unique=True)
    created_on = models.DateTimeField(default=now_utc)
    created_by = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="created_plans",
        null=True,
        blank=True,
    )
    parent_plan = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="child_plans",
    )
    target_customer = models.ForeignKey(
        Customer,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="custom_plans",
    )

    history = HistoricalRecords()

    class Meta:
        constraints = [
            models.CheckConstraint(
                check=(Q(parent_plan__isnull=True) & Q(target_customer__isnull=True))
                | Q(parent_plan__isnull=False) & Q(target_customer__isnull=False),
                name="both_null_or_both_not_null",
            )
        ]

    def __str__(self):
        return f"{self.plan_name}"

    def active_subs_by_version(self):
        versions = self.versions.all().prefetch_related("bp_subscriptions")
        versions_count = versions.annotate(
            active_subscriptions=Count(
                "bp_subscription",
                filter=Q(bp_subscription__status=SUBSCRIPTION_STATUS.ACTIVE),
                output_field=models.IntegerField(),
            )
        )
        return versions_count

    def version_numbers(self):
        return self.versions.all().values_list("version", flat=True)

    def make_version_active(
        self, plan_version, make_active_type=None, replace_immediately_type=None
    ):
        self._handle_existing_versions(
            plan_version, make_active_type, replace_immediately_type
        )
        self.display_version = plan_version
        self.save()
        if plan_version.status != PLAN_VERSION_STATUS.ACTIVE:
            plan_version.status = PLAN_VERSION_STATUS.ACTIVE
            plan_version.save()

    def _handle_existing_versions(
        self, new_version, make_active_type, replace_immediately_type
    ):
        # To dos:
        # 1. make retiring plans update to new version
        # 2a. if on renewal, update active plan to be retiring w/ new version replacing
        # 2b. if grandfather, grandfather currently active plan
        # 2c. if immediataely, then go through immediate replacement flow
        if make_active_type in [
            MAKE_PLAN_VERSION_ACTIVE_TYPE.REPLACE_ON_ACTIVE_VERSION_RENEWAL,
            MAKE_PLAN_VERSION_ACTIVE_TYPE.GRANDFATHER_ACTIVE,
        ]:
            # 1
            replace_with_lst = [PLAN_VERSION_STATUS.RETIRING]
            # 2a
            if (
                make_active_type
                == MAKE_PLAN_VERSION_ACTIVE_TYPE.REPLACE_ON_ACTIVE_VERSION_RENEWAL
            ):
                replace_with_lst.append(PLAN_VERSION_STATUS.ACTIVE)
            self.versions.all().filter(
                ~Q(pk=new_version.pk), status__in=replace_with_lst
            ).update(replace_with=new_version, status=PLAN_VERSION_STATUS.RETIRING)
            # 2b
            if make_active_type == MAKE_PLAN_VERSION_ACTIVE_TYPE.GRANDFATHER_ACTIVE:
                prev_active = self.versions.all().get(
                    ~Q(pk=new_version.pk), status=PLAN_VERSION_STATUS.ACTIVE
                )
                if prev_active.num_active_subs() > 0:
                    prev_active.status = PLAN_VERSION_STATUS.GRANDFATHERED
                else:
                    prev_active.status = PLAN_VERSION_STATUS.INACTIVE
                prev_active.save()
        else:
            # 2c
            versions = (
                self.versions.all()
                .filter(
                    ~Q(pk=new_version.pk),
                    status__in=[
                        PLAN_VERSION_STATUS.ACTIVE,
                        PLAN_VERSION_STATUS.RETIRING,
                    ],
                )
                .prefetch_related("bp_subscriptions")
            )
            versions.update(status=PLAN_VERSION_STATUS.INACTIVE, replace_with=None)
            for version in versions:
                for sub in version.bp_subscriptions.filter(
                    status=SUBSCRIPTION_STATUS.ACTIVE
                ):
                    if (
                        replace_immediately_type
                        == REPLACE_IMMEDIATELY_TYPE.CHANGE_SUBSCRIPTION_PLAN
                    ):
                        sub.switch_subscription_bp(billing_plan=new_version)
                    else:
                        sub.end_subscription_now(
                            bill=replace_immediately_type
                            == REPLACE_IMMEDIATELY_TYPE.END_CURRENT_SUBSCRIPTION_AND_BILL
                        )
                        Subscription.objects.create(
                            billing_plan=new_version,
                            organization=self.organization,
                            customer=sub.customer,
                            start_date=sub.end_date,
                            status=SUBSCRIPTION_STATUS.ACTIVE,
                            auto_renew=True,
                            is_new=False,
                        )


class ExternalPlanLink(models.Model):
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="org_external_plan_links",
    )
    plan = models.ForeignKey(
        Plan, on_delete=models.CASCADE, related_name="external_links"
    )
    source = models.CharField(choices=PAYMENT_PROVIDERS.choices, max_length=40)
    external_plan_id = models.CharField(max_length=100)

    def __str__(self):
        return f"{self.plan} - {self.source} - {self.external_plan_id}"

    class Meta:
        unique_together = ("organization", "source", "external_plan_id")


class Subscription(models.Model):
    """
    Subscription object. An explanation of the Subscription's fields follows:
    customer: The customer that the subscription belongs to.
    plan_name: The name of the plan that the subscription is for.
    start_date: The date at which the subscription started.
    end_date: The date at which the subscription will end.
    status: The status of the subscription, active or ended.
    """

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        null=False,
        related_name="org_subscriptions",
    )
    customer = models.ForeignKey(
        Customer,
        on_delete=models.CASCADE,
        null=False,
        related_name="customer_subscriptions",
    )
    billing_plan = models.ForeignKey(
        PlanVersion,
        on_delete=models.CASCADE,
        null=False,
        related_name="bp_subscriptions",
        related_query_name="bp_subscription",
    )
    start_date = models.DateTimeField()
    end_date = models.DateTimeField()
    scheduled_end_date = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=20,
        choices=SUBSCRIPTION_STATUS.choices,
        default=SUBSCRIPTION_STATUS.NOT_STARTED,
    )
    auto_renew = models.BooleanField(default=True)
    is_new = models.BooleanField(default=True)
    subscription_id = models.CharField(
        max_length=100, null=False, blank=True, default=subscription_uuid
    )
    prorated_flat_costs_dict = models.JSONField(default=dict, blank=True, null=True)
    flat_fee_already_billed = models.DecimalField(
        decimal_places=10, max_digits=20, default=Decimal(0)
    )
    history = HistoricalRecords()

    class Meta:
        unique_together = ("organization", "subscription_id")

    def __str__(self):
        return f"{self.customer.customer_name}  {self.billing_plan.plan.plan_name} : {self.start_date.date()} to {self.end_date.date()}"

    def save(self, *args, **kwargs):
        if not self.end_date:
            self.end_date = calculate_end_date(
                self.billing_plan.plan.plan_duration, self.start_date
            )
        if not self.scheduled_end_date:
            self.scheduled_end_date = self.end_date
        if self.status == SUBSCRIPTION_STATUS.ACTIVE or not self.pk:
            flat_fee_dictionary = self.prorated_flat_costs_dict
            today = now_utc().date()
            dates_bwn = list(
                dates_bwn_two_dts(self.start_date, self.scheduled_end_date)
            )
            for day in dates_bwn:
                if isinstance(day, datetime.datetime):
                    day = day.date()
                if day >= today or not self.pk:
                    flat_fee_dictionary[str(day)] = {
                        "plan_version_id": self.billing_plan.version_id,
                        "amount": float(self.billing_plan.flat_rate.amount)
                        / len(dates_bwn),
                    }
        super(Subscription, self).save(*args, **kwargs)

    def get_usage_and_revenue(self):
        sub_dict = {}
        sub_dict["components"] = []
        # set up the billing plan for this subscription
        plan = self.billing_plan
        # set up other details of the subscription
        plan_start_date = self.start_date
        plan_end_date = self.end_date
        # extract other objects that we need when calculating usage
        customer = self.customer
        plan_components_qs = plan.components.all()
        # For each component of the plan, calculate usage/revenue
        for plan_component in plan_components_qs:
            plan_component_summary = plan_component.calculate_total_revenue(self)
            sub_dict["components"].append((plan_component.pk, plan_component_summary))
        sub_dict["usage_amount_due"] = Decimal(0)
        for component_pk, component_dict in sub_dict["components"]:
            sub_dict["usage_amount_due"] += component_dict["revenue"]
        sub_dict["flat_amount_due"] = plan.flat_rate.amount
        sub_dict["total_amount_due"] = (
            sub_dict["flat_amount_due"] + sub_dict["usage_amount_due"]
        )
        return sub_dict

    def end_subscription_now(self, bill=True):
        if self.status != SUBSCRIPTION_STATUS.ACTIVE:
            raise Exception(
                "Subscription needs to be active to end it. Subscription status is {}".format(
                    self.status
                )
            )
        self.auto_renew = False
        self.end_date = now_utc()
        if bill:
            generate_invoice(self)
        self.status = SUBSCRIPTION_STATUS.ENDED
        self.save()

    def turn_off_auto_renew(self):
        self.auto_renew = False
        self.save()

    def switch_subscription_bp(self, new_version):
        self.billing_plan = new_version
        self.scheduled_end_date = self.end_date = calculate_end_date(
            new_version.plan.plan_duration, self.start_date
        )
        self.save()
        if new_version.flat_fee_billing_type == FLAT_FEE_BILLING_TYPE.IN_ADVANCE:
            invoice = generate_invoice(self)
            self.flat_fee_already_billed += Decimal(invoice.cost_due)


class Backtest(models.Model):
    """
    This model is used to store the results of a backtest.
    """

    backtest_name = models.CharField(max_length=100, null=False, blank=False)
    start_date = models.DateField(null=False, blank=False)
    end_date = models.DateField(null=False, blank=False)
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, null=False, related_name="org_backtests"
    )
    time_created = models.DateTimeField(default=now_utc)
    backtest_id = models.CharField(
        max_length=100, null=False, blank=True, default=backtest_uuid, unique=True
    )
    kpis = models.JSONField(default=list)
    backtest_results = models.JSONField(default=dict, null=True, blank=True)
    status = models.CharField(
        choices=BACKTEST_STATUS.choices,
        default=BACKTEST_STATUS.RUNNING,
        max_length=40,
    )
    history = HistoricalRecords()

    def __str__(self):
        return f"{self.backtest_name} - {self.start_date}"


class BacktestSubstitution(models.Model):
    """
    This model is used to substitute a backtest for a live trading session.
    """

    backtest = models.ForeignKey(
        Backtest, on_delete=models.CASCADE, related_name="backtest_substitutions"
    )
    original_plan = models.ForeignKey(
        PlanVersion, on_delete=models.CASCADE, related_name="+"
    )
    new_plan = models.ForeignKey(
        PlanVersion, on_delete=models.CASCADE, related_name="+"
    )
    history = HistoricalRecords()

    def __str__(self):
        return f"{self.backtest}"


class OrganizationSetting(models.Model):
    """
    This model is used to store settings for an organization.
    """

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="org_settings"
    )
    setting_id = models.CharField(default=uuid.uuid4, max_length=100, unique=True)
    setting_name = models.CharField(max_length=100, null=False, blank=False)
    setting_value = models.CharField(max_length=100, null=False, blank=False)
    setting_group = models.CharField(max_length=100, null=True, blank=True)
    history = HistoricalRecords()

    def save(self, *args, **kwargs):
        if self.setting_value.lower() == "true":
            self.setting_value = "true"
        elif self.setting_value.lower() == "false":
            self.setting_value = "false"
        super(OrganizationSetting, self).save(*args, **kwargs)

    def __str__(self):
        return f"{self.setting_name} - {self.setting_value}"

    class Meta:
        unique_together = ("organization", "setting_name")
        constraints = [
            UniqueConstraint(
                fields=[
                    "organization",
                    "setting_name",
                    "setting_group",
                ],
                name="unique_with_group",
            ),
            UniqueConstraint(
                fields=[
                    "organization",
                    "setting_name",
                ],
                condition=Q(setting_group=None),
                name="unique_without_group",
            ),
        ]
