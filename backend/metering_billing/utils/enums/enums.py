from django.db import models
from django.utils.translation import gettext_lazy as _


class INVOICE_STATUS(models.TextChoices):
    DRAFT = ("draft", _("Draft"))
    PAID = ("paid", _("Paid"))
    UNPAID = ("unpaid", _("Unpaid"))


class PAYMENT_PLANS(models.TextChoices):
    SELF_HOSTED_FREE = ("self_hosted_free", _("Self-Hosted Free"))
    CLOUD = ("cloud", _("Cloud"))
    SELF_HOSTED_ENTERPRISE = ("self_hosted_enterprise", _("Self-Hosted Enterprise"))


class METRIC_AGGREGATION(models.TextChoices):
    COUNT = ("count", _("Count"))
    SUM = ("sum", _("Sum"))
    MAX = ("max", _("Max"))
    MIN = ("min", _("Min"))
    UNIQUE = ("unique", _("Unique"))
    LATEST = ("latest", _("Latest"))
    AVERAGE = ("average", _("Average"))


class PRICE_ADJUSTMENT_TYPE(models.TextChoices):
    PERCENTAGE = ("percentage", _("Percentage"))
    FIXED = ("fixed", _("Fixed"))
    PRICE_OVERRIDE = ("price_override", _("Price Override"))


class PAYMENT_PROVIDERS(models.TextChoices):
    STRIPE = ("stripe", _("Stripe"))


class METRIC_TYPE(models.TextChoices):
    AGGREGATION = ("aggregation", _("Aggregatable"))
    STATEFUL = ("stateful", _("State Logging"))


class PLAN_DURATION(models.TextChoices):
    MONTHLY = ("monthly", _("Monthly"))
    QUARTERLY = ("quarterly", _("Quarterly"))
    YEARLY = ("yearly", _("Yearly"))


class USAGE_BILLING_FREQUENCY(models.TextChoices):
    MONTHLY = ("monthly", _("Monthly"))
    QUARTERLY = ("quarterly", _("Quarterly"))
    YEARLY = ("yearly", _("Yearly"))


class FLAT_FEE_BILLING_TYPE(models.TextChoices):
    IN_ARREARS = ("in_arrears", _("In Arrears"))
    IN_ADVANCE = ("in_advance", _("In Advance"))


class REVENUE_CALC_GRANULARITY(models.TextChoices):
    DAILY = ("day", _("Daily"))
    TOTAL = ("total", _("Total"))


class PRORATION_GRANULARITY(models.TextChoices):
    MONTHLY = ("monthly", _("Monthly"))
    WEEKLY = ("weekly", _("Weekly"))
    DAILY = ("daily", _("Daily"))
    HOURLY = ("hourly", _("Hourly"))
    NONE = ("none", _("None"))


class NUMERIC_FILTER_OPERATORS(models.TextChoices):
    GTE = ("gte", _("Greater than or equal to"))
    GT = ("gt", _("Greater than"))
    EQ = ("eq", _("Equal to"))
    LT = ("lt", _("Less than"))
    LTE = ("lte", _("Less than or equal to"))


class CATEGORICAL_FILTER_OPERATORS(models.TextChoices):
    ISIN = ("isin", _("Is in"))
    ISNOTIN = ("isnotin", _("Is not in"))


class SUBSCRIPTION_STATUS(models.TextChoices):
    ACTIVE = ("active", _("Active"))
    ENDED = ("ended", _("Ended"))
    NOT_STARTED = ("not_started", _("Not Started"))


class PLAN_VERSION_STATUS(models.TextChoices):
    ACTIVE = ("active", _("Active"))
    RETIRING = ("retiring", _("Retiring"))
    GRANDFATHERED = ("grandfathered", _("Grandfathered"))
    ARCHIVED = ("archived", _("Archived"))
    INACTIVE = ("inactive", _("Inactive"))


class PLAN_STATUS(models.TextChoices):
    ACTIVE = ("active", _("Active"))
    ARCHIVED = ("archived", _("Archived"))
    EXPERIMENTAL = ("experimental", _("Experimental"))


class BACKTEST_KPI(models.TextChoices):
    TOTAL_REVENUE = ("total_revenue", _("Total Revenue"))


class BACKTEST_STATUS(models.TextChoices):
    RUNNING = ("running", _("Running"))
    COMPLETED = ("completed", _("Completed"))
    FAILED = ("failed", _("Failed"))


class PRODUCT_STATUS(models.TextChoices):
    ACTIVE = ("active", _("Active"))
    DEPRECATED = ("deprecated", _("Deprecated"))


class MAKE_PLAN_VERSION_ACTIVE_TYPE(models.TextChoices):
    REPLACE_IMMEDIATELY = ("replace_immediately", _("Replace Immediately"))
    REPLACE_ON_ACTIVE_VERSION_RENEWAL = (
        "replace_on_active_version_renewal",
        _("Replace on Active Version Renewal"),
    )
    GRANDFATHER_ACTIVE = ("grandfather_active", _("Grandfather Active"))


class REPLACE_IMMEDIATELY_TYPE(models.TextChoices):
    END_CURRENT_SUBSCRIPTION_AND_BILL = (
        "end_current_subscription_and_bill",
        _("End Current Subscription and Bill"),
    )
    END_CURRENT_SUBSCRIPTION_DONT_BILL = (
        "end_current_subscription_dont_bill",
        _("End Current Subscription and Don't Bill"),
    )
    CHANGE_SUBSCRIPTION_PLAN = (
        "change_subscription_plan",
        _("Change Subscription Plan"),
    )
