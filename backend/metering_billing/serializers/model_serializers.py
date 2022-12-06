from datetime import timedelta
from decimal import Decimal
from typing import Union

from actstream.models import Action
from dateutil.relativedelta import relativedelta
from django.db.models import Q
from metering_billing.billable_metrics import METRIC_HANDLER_MAP
from metering_billing.exceptions import DuplicateMetric
from metering_billing.invoice import generate_invoice
from metering_billing.models import (
    CategoricalFilter,
    Customer,
    CustomerBalanceAdjustment,
    Event,
    ExternalPlanLink,
    Feature,
    Invoice,
    InvoiceLineItem,
    Metric,
    NumericFilter,
    Organization,
    OrganizationInviteToken,
    OrganizationSetting,
    Plan,
    PlanComponent,
    PlanVersion,
    PriceAdjustment,
    PriceTier,
    PricingUnit,
    Product,
    Subscription,
    User,
    WebhookEndpoint,
    WebhookTrigger,
)
from metering_billing.payment_providers import PAYMENT_PROVIDER_MAP
from metering_billing.utils import calculate_end_date, now_utc
from metering_billing.utils.enums import *
from rest_framework import serializers

from .serializer_utils import (
    SlugRelatedFieldWithOrganization,
    SlugRelatedFieldWithOrganizationOrNull,
)


class OrganizationUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("username", "email", "role", "status")

    role = serializers.SerializerMethodField()
    status = serializers.ChoiceField(
        choices=ORGANIZATION_STATUS.choices, default=ORGANIZATION_STATUS.ACTIVE
    )

    def get_role(self, obj) -> str:
        return "Admin"


class OrganizationInvitedUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("email", "role")

    role = serializers.SerializerMethodField()

    def get_role(self, obj) -> str:
        return "Admin"


class PricingUnitSerializer(serializers.ModelSerializer):
    class Meta:
        model = PricingUnit
        fields = ("code", "name", "symbol")

    def validate(self, attrs):
        super().validate(attrs)
        code_exists = PricingUnit.objects.filter(
            Q(organization=self.context["organization"]) | Q(organization__isnull=True),
            code=attrs["code"],
        ).exists()
        if code_exists:
            raise serializers.ValidationError("Pricing unit code already exists")
        return attrs

    def create(self, validated_data):
        return PricingUnit.objects.create(**validated_data)


class OrganizationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organization
        fields = (
            "organization_id",
            "company_name",
            "payment_plan",
            "payment_provider_ids",
            "users",
            "default_currency",
        )

    users = serializers.SerializerMethodField()
    default_currency = PricingUnitSerializer()

    def get_users(self, obj) -> OrganizationUserSerializer(many=True):
        users = User.objects.filter(organization=obj)
        users_data = list(OrganizationUserSerializer(users, many=True).data)
        now = now_utc()
        invited_users = OrganizationInviteToken.objects.filter(
            organization=obj, expire_at__gt=now
        )
        invited_users_data = OrganizationInvitedUserSerializer(
            invited_users, many=True
        ).data
        invited_users_data = [
            {**x, "status": ORGANIZATION_STATUS.INVITED, "username": ""}
            for x in invited_users_data
        ]
        return users_data + invited_users_data


class OrganizationUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organization
        fields = ("default_currency_code",)

    default_currency_code = SlugRelatedFieldWithOrganizationOrNull(
        slug_field="code", queryset=PricingUnit.objects.all(), source="default_currency"
    )

    def update(self, instance, validated_data):
        assert (
            type(validated_data.get("default_currency")) == PricingUnit
            or validated_data.get("default_currency") is None
        )
        instance.default_currency = validated_data.get(
            "default_currency", instance.default_currency
        )
        instance.save()
        return instance


class CustomerUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Customer
        fields = ("default_currency_code",)

    default_currency_code = SlugRelatedFieldWithOrganizationOrNull(
        slug_field="code", queryset=PricingUnit.objects.all(), source="default_currency"
    )

    def update(self, instance, validated_data):
        assert (
            type(validated_data.get("default_currency")) == PricingUnit
            or validated_data.get("default_currency") is None
        )
        instance.default_currency = validated_data.get(
            "default_currency", instance.default_currency
        )
        instance.save()
        return instance


class EventSerializer(serializers.ModelSerializer):
    class Meta:
        model = Event
        fields = (
            "event_name",
            "properties",
            "time_created",
            "idempotency_id",
            "customer_id",
        )

    customer_id = SlugRelatedFieldWithOrganization(
        slug_field="customer_id",
        queryset=Customer.objects.all(),
        write_only=True,
        source="customer",
    )
    customer = serializers.SerializerMethodField()

    def get_customer(self, obj) -> str:
        try:
            ret = obj.customer.customer_id
        except:
            ret = obj.cust_id
        return ret


class WebhookTriggerSerializer(serializers.ModelSerializer):
    class Meta:
        model = WebhookTrigger
        fields = [
            "trigger_name",
        ]


class WebhookEndpointSerializer(serializers.ModelSerializer):
    class Meta:
        model = WebhookEndpoint
        fields = (
            "webhook_endpoint_id",
            "name",
            "webhook_url",
            "webhook_secret",
            "triggers",
            "triggers_in",
        )
        extra_kwargs = {
            "webhook_endpoint_id": {"read_only": True},
            "webhook_secret": {"read_only": True},
            "triggers": {"read_only": True},
            "triggers_in": {"write_only": True},
        }

    triggers_in = serializers.ListField(
        child=serializers.ChoiceField(choices=WEBHOOK_TRIGGER_EVENTS.choices),
        write_only=True,
        required=True,
    )
    triggers = WebhookTriggerSerializer(
        many=True,
        read_only=True,
    )

    def validate(self, attrs):
        if len(attrs.get("triggers_in", [])) == 0:
            raise serializers.ValidationError("At least one trigger must be specified")
        return super().validate(attrs)

    def create(self, validated_data):
        triggers_in = validated_data.pop("triggers_in")
        trigger_objs = []
        for trigger in triggers_in:
            wh_trigger_obj = WebhookTrigger(trigger_name=trigger)
            trigger_objs.append(wh_trigger_obj)
        webhook_endpoint = WebhookEndpoint.objects.create_with_triggers(
            **validated_data, triggers=trigger_objs
        )
        return webhook_endpoint

    def update(self, instance, validated_data):
        triggers_in = validated_data.pop("triggers_in")
        instance.name = validated_data.get("name", instance.name)
        instance.webhook_url = validated_data.get("webhook_url", instance.webhook_url)
        for trigger in instance.triggers.all():
            if trigger.trigger_name not in triggers_in:
                trigger.delete()
            else:
                triggers_in.remove(trigger.trigger_name)
        for trigger in triggers_in:
            WebhookTrigger.objects.create(
                webhook_endpoint=instance, trigger_name=trigger
            )
        instance.save()
        return instance


## USER
class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("username", "email", "company_name", "organization_id")

    organization_id = serializers.CharField(source="organization.id")
    company_name = serializers.CharField(source="organization.company_name")


## CUSTOMER
class FilterActiveSubscriptionSerializer(serializers.ListSerializer):
    def to_representation(self, data):
        data = [x for x in data if x.status == SUBSCRIPTION_STATUS.ACTIVE]
        return super(FilterActiveSubscriptionSerializer, self).to_representation(data)


class SubscriptionCustomerSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = Subscription
        fields = ("billing_plan_name", "plan_version", "end_date", "auto_renew")
        list_serializer_class = FilterActiveSubscriptionSerializer

    billing_plan_name = serializers.CharField(source="billing_plan.plan.plan_name")
    plan_version = serializers.CharField(source="billing_plan.version")


class CustomerSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = Customer
        fields = (
            "customer_name",
            "customer_id",
            "subscriptions",
        )

    subscriptions = SubscriptionCustomerSummarySerializer(read_only=True, many=True)


class SubscriptionCustomerDetailSerializer(SubscriptionCustomerSummarySerializer):
    class Meta(SubscriptionCustomerSummarySerializer.Meta):
        model = Subscription
        fields = SubscriptionCustomerSummarySerializer.Meta.fields + (
            "subscription_id",
            "start_date",
            "status",
        )


class CustomerWithRevenueSerializer(serializers.ModelSerializer):
    class Meta:
        model = Customer
        fields = ("customer_id", "total_amount_due", "next_amount_due")

    total_amount_due = serializers.SerializerMethodField()
    next_amount_due = serializers.SerializerMethodField()

    def get_total_amount_due(self, obj) -> float:
        total_amount_due = float(self.context.get("total_amount_due"))
        return total_amount_due

    def get_next_amount_due(self, obj) -> float:
        next_amount_due = float(self.context.get("next_amount_due"))
        return next_amount_due


class CustomerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Customer
        fields = (
            "customer_name",
            "customer_id",
            "email",
            "payment_provider",
            "payment_provider_id",
            "properties",
            "integrations",
            "default_currency_code",
        )
        extra_kwargs = {
            "customer_id": {"required": True},
            "email": {"required": True},
        }

    payment_provider_id = serializers.CharField(
        required=False, allow_null=True, write_only=True
    )
    email = serializers.EmailField(required=True)
    default_currency_code = SlugRelatedFieldWithOrganizationOrNull(
        slug_field="code",
        queryset=PricingUnit.objects.all(),
        required=False,
        source="default_currency",
        write_only=True,
    )

    def validate(self, data):
        super().validate(data)
        payment_provider = data.get("payment_provider", None)
        payment_provider_id = data.get("payment_provider_id", None)
        if payment_provider or payment_provider_id:
            # if not PAYMENT_PROVIDER_MAP[payment_provider].organization_connected(
            #     self.context["organization"]
            # ):
            #     raise serializers.ValidationError(
            #         "Specified payment provider not connected to organization"
            #     )
            # if payment_provider and not payment_provider_id:
            #     raise serializers.ValidationError(
            #         "Payment provider ID required when payment provider is specified"
            #     )
            if payment_provider_id and not payment_provider:
                raise serializers.ValidationError(
                    "Payment provider required when payment provider ID is specified"
                )

        return data

    def create(self, validated_data):
        pp_id = validated_data.pop("payment_provider_id", None)
        customer = Customer.objects.create(**validated_data)
        if pp_id:
            customer_properties = customer.properties
            customer_properties[validated_data["payment_provider"]] = {}
            customer_properties[validated_data["payment_provider"]]["id"] = pp_id
            customer.properties = customer_properties
            customer.save()
        else:
            if "payment_provider" in validated_data:
                PAYMENT_PROVIDER_MAP[
                    validated_data["payment_provider"]
                ].create_customer(customer)
        return customer

    def update(self, instance, validated_data, behavior="merge"):
        instance.customer_id = validated_data.get(
            "customer_id", instance.customer_id if behavior == "merge" else None
        )
        instance.customer_name = validated_data.get(
            "customer_name", instance.customer_name if behavior == "merge" else None
        )
        instance.email = validated_data.get(
            "email", instance.email if behavior == "merge" else None
        )
        instance.payment_provider = validated_data.get(
            "payment_provider",
            instance.payment_provider if behavior == "merge" else None,
        )
        instance.properties = (
            {**instance.properties, **validated_data.get("properties", {})}
            if behavior == "merge"
            else validated_data.get("properties", {})
        )
        if "payment_provider_id" in validated_data:
            if not (instance.payment_provider in instance.integrations):
                instance.integrations[instance.payment_provider] = {}
            instance.integrations[instance.payment_provider]["id"] = validated_data.get(
                "payment_provider_id"
            )
        return instance


## BILLABLE METRIC
class CategoricalFilterSerializer(serializers.ModelSerializer):
    class Meta:
        model = CategoricalFilter
        fields = ("property_name", "operator", "comparison_value")

    comparison_value = serializers.ListField(child=serializers.CharField())


class NumericFilterSerializer(serializers.ModelSerializer):
    class Meta:
        model = NumericFilter
        fields = ("property_name", "operator", "comparison_value")


class MetricUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Metric
        fields = (
            "billable_metric_name",
            "status",
        )

    def validate(self, data):
        data = super().validate(data)
        if data.get("status") == METRIC_STATUS.ARCHIVED:
            all_active_plan_versions = PlanVersion.objects.filter(
                organization=self.context["organization"],
                plan__in=Plan.objects.filter(status=PLAN_STATUS.ACTIVE),
            ).prefetch_related("plan_components", "plan_components__billable_metric")
            for plan_version in all_active_plan_versions:
                if plan_version.num_active_subs() == 0:
                    continue
                for component in plan_version.plan_components.all():
                    if component.billable_metric == self.instance:
                        raise serializers.ValidationError(
                            "Cannot archive metric that is used in active plan"
                        )
        return data

    def update(self, instance, validated_data):
        instance.billable_metric_name = validated_data.get(
            "billable_metric_name", instance.billable_metric_name
        )
        instance.status = validated_data.get("status", instance.status)
        instance.save()
        return instance


class MetricSerializer(serializers.ModelSerializer):
    class Meta:
        model = Metric
        fields = (
            "metric_id",
            "event_name",
            "property_name",
            "usage_aggregation_type",
            "billable_aggregation_type",
            "granularity",
            "event_type",
            "metric_type",
            "billable_metric_name",
            "numeric_filters",
            "categorical_filters",
            "properties",
            "is_cost_metric",
        )
        extra_kwargs = {
            "metric_type": {"required": True},
            "usage_aggregation_type": {"required": True},
            "event_name": {"required": True},
            "metric_id": {"read_only": True},
        }

    numeric_filters = NumericFilterSerializer(
        many=True, allow_null=True, required=False, read_only=False
    )
    categorical_filters = CategoricalFilterSerializer(
        many=True, allow_null=True, required=False, read_only=False
    )
    granularity = serializers.ChoiceField(
        choices=METRIC_GRANULARITY.choices,
        required=False,
    )
    event_type = serializers.ChoiceField(
        choices=EVENT_TYPE.choices,
        required=False,
    )
    properties = serializers.JSONField(allow_null=True, required=False)

    def validate(self, data):
        super().validate(data)
        metric_type = data["metric_type"]
        data = METRIC_HANDLER_MAP[metric_type].validate_data(data)
        return data

    def custom_name(self, validated_data) -> str:
        name = validated_data.get("billable_metric_name", None)
        if name in [None, "", " "]:
            name = f"[{validated_data['metric_type'][:4]}]"
            name += " " + validated_data["usage_aggregation_type"] + " of"
            if validated_data["property_name"] not in ["", " ", None]:
                name += " " + validated_data["property_name"] + " of"
            name += " " + validated_data["event_name"]
            validated_data["billable_metric_name"] = name[:200]
        return name

    def create(self, validated_data):
        # edit custom name and pop filters + properties
        validated_data["billable_metric_name"] = self.custom_name(validated_data)
        num_filter_data = validated_data.pop("numeric_filters", [])
        cat_filter_data = validated_data.pop("categorical_filters", [])

        bm, created = Metric.objects.get_or_create(**validated_data)
        if not created:
            raise DuplicateMetric

        # get filters
        for num_filter in num_filter_data:
            try:
                nf, _ = NumericFilter.objects.get_or_create(**num_filter)
            except NumericFilter.MultipleObjectsReturned:
                nf = NumericFilter.objects.filter(**num_filter).first()
            bm.numeric_filters.add(nf)
        for cat_filter in cat_filter_data:
            try:
                cf, _ = CategoricalFilter.objects.get_or_create(**cat_filter)
            except CategoricalFilter.MultipleObjectsReturned:
                cf = CategoricalFilter.objects.filter(**cat_filter).first()
            bm.categorical_filters.add(cf)
        bm.save()

        return bm


class ExternalPlanLinkSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExternalPlanLink
        fields = ("plan_id", "source", "external_plan_id")

    plan_id = SlugRelatedFieldWithOrganization(
        slug_field="plan_id",
        source="plan",
        queryset=Plan.objects.all(),
        write_only=True,
    )

    def validate(self, data):
        super().validate(data)
        query = ExternalPlanLink.objects.filter(
            organization=self.context["organization"],
            source=data["source"],
            external_plan_id=data["external_plan_id"],
        )
        if query.exists():
            plan_name = data["plan"].plan_name
            raise serializers.ValidationError(
                f"This external plan link already exists in plan {plan_name}"
            )
        return data


class InitialExternalPlanLinkSerializer(ExternalPlanLinkSerializer):
    class Meta(ExternalPlanLinkSerializer.Meta):
        model = ExternalPlanLink
        fields = tuple(
            set(ExternalPlanLinkSerializer.Meta.fields)
            - set(
                [
                    "plan_id",
                ]
            )
        )


## FEATURE
class FeatureSerializer(serializers.ModelSerializer):
    class Meta:
        model = Feature
        fields = (
            "feature_name",
            "feature_description",
        )


class PriceTierSerializer(serializers.ModelSerializer):
    class Meta:
        model = PriceTier
        fields = (
            "type",
            "range_start",
            "range_end",
            "cost_per_batch",
            "metric_units_per_batch",
            "batch_rounding_type",
        )

    def validate(self, data):
        data = super().validate(data)
        rs = data.get("range_start", None)
        assert rs is not None and rs >= Decimal(0), "range_start must be >= 0"
        re = data.get("range_end", None)
        if not re:
            re = Decimal("Infinity")
        assert re > rs
        if data.get("type") == PRICE_TIER_TYPE.FLAT:
            assert data.get("cost_per_batch") is not None
            data["metric_units_per_batch"] = None
            data["batch_rounding_type"] = None
        elif data.get("type") == PRICE_TIER_TYPE.FREE:
            data["cost_per_batch"] = None
            data["metric_units_per_batch"] = None
            data["batch_rounding_type"] = None
        elif data.get("type") == PRICE_TIER_TYPE.PER_UNIT:
            assert data.get("metric_units_per_batch")
            assert data.get("cost_per_batch") is not None
            data["batch_rounding_type"] = data.get(
                "batch_rounding_type", BATCH_ROUNDING_TYPE.NO_ROUNDING
            )
        else:
            raise serializers.ValidationError("Invalid price tier type")
        return data

    def create(self, validated_data):
        return PriceTier.objects.create(**validated_data)


## PLAN COMPONENT
class PlanComponentSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlanComponent
        fields = (
            "billable_metric_name",
            "billable_metric",
            "tiers",
            "separate_by",
            "proration_granularity",
        )
        read_only_fields = ["billable_metric"]

    separate_by = serializers.ListField(child=serializers.CharField(), required=False)
    proration_granularity = serializers.ChoiceField(
        choices=METRIC_GRANULARITY.choices,
        required=False,
        default=METRIC_GRANULARITY.TOTAL,
    )

    # READ-ONLY
    billable_metric = MetricSerializer(read_only=True)

    # WRITE-ONLY
    billable_metric_name = SlugRelatedFieldWithOrganization(
        slug_field="billable_metric_name",
        write_only=True,
        source="billable_metric",
        queryset=Metric.objects.all(),
    )

    # both
    tiers = PriceTierSerializer(many=True)

    def validate(self, data):
        data = super().validate(data)
        try:
            tiers = data.get("tiers")
            assert len(tiers) > 0, "Must have at least one price tier"
            tiers_sorted = sorted(tiers, key=lambda x: x["range_start"])
            assert tiers_sorted[0]["range_start"] == 0, "First tier must start at 0"
            assert all(
                x["range_end"] for x in tiers_sorted[:-1]
            ), "All tiers must have an end, last one is the only one allowed to have open end"
            for i, tier in enumerate(tiers_sorted[:-1]):
                assert tiers_sorted[i + 1]["range_start"] - tier[
                    "range_end"
                ] <= Decimal(1), "All tiers must be contiguous"

            pr_gran = data.get("proration_granularity")
            metric_granularity = data.get("billable_metric").granularity
            if pr_gran == METRIC_GRANULARITY.SECOND:
                if metric_granularity == METRIC_GRANULARITY.SECOND:
                    data["proration_granularity"] = METRIC_GRANULARITY.TOTAL
            elif pr_gran == METRIC_GRANULARITY.MINUTE:
                assert metric_granularity not in [
                    METRIC_GRANULARITY.SECOND,
                ], "Metric granularity cannot be finer than proration granularity"
                if metric_granularity == METRIC_GRANULARITY.MINUTE:
                    data["proration_granularity"] = METRIC_GRANULARITY.TOTAL
            elif pr_gran == METRIC_GRANULARITY.HOUR:
                assert metric_granularity not in [
                    METRIC_GRANULARITY.SECOND,
                    METRIC_GRANULARITY.MINUTE,
                ], "Metric granularity cannot be finer than proration granularity"
                if metric_granularity == METRIC_GRANULARITY.HOUR:
                    data["proration_granularity"] = METRIC_GRANULARITY.TOTAL
            elif pr_gran == METRIC_GRANULARITY.DAY:
                assert metric_granularity not in [
                    METRIC_GRANULARITY.SECOND,
                    METRIC_GRANULARITY.MINUTE,
                    METRIC_GRANULARITY.HOUR,
                ], "Metric granularity cannot be finer than proration granularity"
                if metric_granularity == METRIC_GRANULARITY.DAY:
                    data["proration_granularity"] = METRIC_GRANULARITY.TOTAL
            elif pr_gran == METRIC_GRANULARITY.MONTH:
                assert metric_granularity not in [
                    METRIC_GRANULARITY.SECOND,
                    METRIC_GRANULARITY.MINUTE,
                    METRIC_GRANULARITY.HOUR,
                    METRIC_GRANULARITY.DAY,
                ], "Metric granularity cannot be finer than proration granularity"
                if metric_granularity == METRIC_GRANULARITY.MONTH:
                    data["proration_granularity"] = METRIC_GRANULARITY.TOTAL
            elif pr_gran == METRIC_GRANULARITY.QUARTER:
                assert metric_granularity not in [
                    METRIC_GRANULARITY.SECOND,
                    METRIC_GRANULARITY.MINUTE,
                    METRIC_GRANULARITY.HOUR,
                    METRIC_GRANULARITY.DAY,
                    METRIC_GRANULARITY.MONTH,
                ], "Metric granularity cannot be finer than proration granularity"
                if metric_granularity == METRIC_GRANULARITY.QUARTER:
                    data["proration_granularity"] = METRIC_GRANULARITY.TOTAL
            elif pr_gran == METRIC_GRANULARITY.YEAR:
                assert metric_granularity not in [
                    METRIC_GRANULARITY.SECOND,
                    METRIC_GRANULARITY.MINUTE,
                    METRIC_GRANULARITY.HOUR,
                    METRIC_GRANULARITY.DAY,
                    METRIC_GRANULARITY.MONTH,
                    METRIC_GRANULARITY.QUARTER,
                ], "Metric granularity cannot be finer than proration granularity"
                if metric_granularity == METRIC_GRANULARITY.YEAR:
                    data["proration_granularity"] = METRIC_GRANULARITY.TOTAL
        except AssertionError as e:
            raise serializers.ValidationError(str(e))
        return data

    def create(self, validated_data):
        tiers = validated_data.pop("tiers")
        pc = PlanComponent.objects.create(**validated_data)
        for tier in tiers:
            tier = PriceTierSerializer().create(tier)
            assert type(tier) is PriceTier
            tier.plan_component = pc
            tier.save()
        return pc


class ProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = ("name", "description", "product_id", "status")


class PlanVersionUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlanVersion
        fields = (
            "description",
            "status",
            "make_active_type",
            "replace_immediately_type",
            "transition_to_plan_id",
            "transition_to_plan_version_id",
        )

    make_active_type = serializers.ChoiceField(
        choices=MAKE_PLAN_VERSION_ACTIVE_TYPE.choices,
        required=False,
    )
    replace_immediately_type = serializers.ChoiceField(
        choices=REPLACE_IMMEDIATELY_TYPE.choices, required=False
    )
    status = serializers.ChoiceField(
        choices=[PLAN_VERSION_STATUS.ACTIVE, PLAN_VERSION_STATUS.ARCHIVED],
        required=False,
    )
    transition_to_plan_id = SlugRelatedFieldWithOrganization(
        slug_field="plan_id",
        queryset=Plan.objects.all(),
        write_only=True,
        required=False,
    )
    transition_to_plan_version_id = SlugRelatedFieldWithOrganization(
        slug_field="version_id",
        queryset=PlanVersion.objects.all(),
        write_only=True,
        required=False,
    )

    def validate(self, data):
        transition_to_plan_id = data.get("transition_to_plan_id")
        transition_to_plan_version_id = data.get("transition_to_plan_version_id")
        assert not (
            transition_to_plan_id and transition_to_plan_version_id
        ), "Can't specify both transition_to_plan_id and transition_to_plan_version_id"
        data = super().validate(data)
        if (
            data.get("status") == PLAN_VERSION_STATUS.ARCHIVED
            and self.instance.num_active_subs() > 0
        ):
            raise serializers.ValidationError(
                "Can't archive a plan with active subscriptions."
            )
        if (
            data.get("status") == PLAN_VERSION_STATUS.ACTIVE
            and data.get("make_active_type")
            == MAKE_PLAN_VERSION_ACTIVE_TYPE.REPLACE_IMMEDIATELY
            and not data.get("immediate_active_type")
        ):
            raise serializers.ValidationError(
                f"immediate_active_type must be specified when make_active_type is {MAKE_PLAN_VERSION_ACTIVE_TYPE.REPLACE_IMMEDIATELY}"
            )
        return data

    def update(self, instance, validated_data):
        instance.description = validated_data.get("description", instance.description)
        instance.status = validated_data.get("status", instance.status)
        if validated_data.get("status") == PLAN_VERSION_STATUS.ACTIVE:
            parent_plan = instance.plan
            parent_plan.make_version_active(
                instance,
                validated_data.get("make_active_type"),
                validated_data.get("replace_immediately_type"),
            )
        transition_to_plan = validated_data.get("transition_to_plan_id", None)
        transition_to_plan_version = validated_data.get(
            "transition_to_plan_version_id", None
        )
        if transition_to_plan:
            instance.transition_to = transition_to_plan
        elif transition_to_plan_version:
            instance.transition_to = transition_to_plan_version
        instance.save()
        return instance


class PriceAdjustmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = PriceAdjustment
        fields = (
            "price_adjustment_name",
            "price_adjustment_description",
            "price_adjustment_type",
            "price_adjustment_amount",
        )

    price_adjustment_name = serializers.CharField(default="")


class PlanVersionSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlanVersion
        fields = (
            "description",
            "plan_id",
            "flat_fee_billing_type",
            "flat_rate",
            "components",
            "features",
            "price_adjustment",
            "usage_billing_frequency",
            # write only
            "make_active",
            "make_active_type",
            "replace_immediately_type",
            "transition_to_plan_id",
            # "transition_to_plan_version_id",
            # read-only
            "version",
            "version_id",
            "active_subscriptions",
            "created_by",
            "created_on",
            "status",
            "replace_with",
            "transition_to",
        )
        read_only_fields = (
            "version",
            "version_id",
            "active_subscriptions",
            "created_by",
            "created_on",
            "status",
            "replace_with",
            "transition_to",
        )
        extra_kwargs = {
            "make_active_type": {"write_only": True},
            "replace_immediately_type": {"write_only": True},
        }

    components = PlanComponentSerializer(
        many=True, allow_null=True, required=False, source="plan_components"
    )
    features = FeatureSerializer(many=True, allow_null=True, required=False)
    price_adjustment = PriceAdjustmentSerializer(required=False)
    plan_id = SlugRelatedFieldWithOrganization(
        slug_field="plan_id",
        queryset=Plan.objects.all(),
        source="plan",
        required=False,
    )

    # WRITE ONLY
    make_active = serializers.BooleanField(write_only=True)
    make_active_type = serializers.ChoiceField(
        choices=MAKE_PLAN_VERSION_ACTIVE_TYPE.choices, required=False, write_only=True
    )
    replace_immediately_type = serializers.ChoiceField(
        choices=REPLACE_IMMEDIATELY_TYPE.choices, required=False, write_only=True
    )
    transition_to_plan_id = SlugRelatedFieldWithOrganization(
        slug_field="plan_id",
        queryset=Plan.objects.all(),
        write_only=True,
        required=False,
    )
    # READ-ONLY
    active_subscriptions = serializers.IntegerField(read_only=True)
    created_by = serializers.SerializerMethodField(read_only=True)
    replace_with = serializers.SerializerMethodField(read_only=True)
    transition_to = serializers.SerializerMethodField(read_only=True)

    def get_created_by(self, obj) -> str:
        if obj.created_by != None:
            return obj.created_by.username
        else:
            return None

    def get_replace_with(self, obj) -> Union[int, None]:
        if obj.replace_with != None:
            return obj.replace_with.version
        else:
            return None

    def get_transition_to(self, obj) -> Union[str, None]:
        if obj.transition_to != None:
            return str(obj.transition_to.display_version)
        else:
            return None

    def validate(self, data):
        data = super().validate(data)
        # make sure every plan component has a unique metric
        if data.get("plan_components"):
            component_metrics = []
            for component in data.get("plan_components"):
                if component.get("billable_metric") in component_metrics:
                    raise serializers.ValidationError(
                        "Plan components must have unique metrics."
                    )
                else:
                    component_metrics.append(component.get("metric"))
        if data.get("make_active") and not data.get("make_active_type"):
            raise serializers.ValidationError(
                "make_active_type must be specified when make_active is True"
            )
        if data.get(
            "make_active_type"
        ) == MAKE_PLAN_VERSION_ACTIVE_TYPE.REPLACE_IMMEDIATELY and not data.get(
            "replace_immediately_type"
        ):
            raise serializers.ValidationError(
                f"replace_immediately_type must be specified when make_active_type is {MAKE_PLAN_VERSION_ACTIVE_TYPE.REPLACE_IMMEDIATELY}"
            )
        return data

    def create(self, validated_data):
        components_data = validated_data.pop("plan_components", [])
        if len(components_data) > 0:
            components = PlanComponentSerializer(many=True).create(components_data)
            assert type(components[0]) is PlanComponent
        else:
            components = []
        features_data = validated_data.pop("features", [])
        price_adjustment_data = validated_data.pop("price_adjustment", None)
        make_active = validated_data.pop("make_active", False)
        make_active_type = validated_data.pop("make_active_type", None)
        replace_immediately_type = validated_data.pop("replace_immediately_type", None)
        transition_to_plan = validated_data.get("transition_to_plan_id", None)
        validated_data["version"] = len(validated_data["plan"].versions.all()) + 1
        if "status" not in validated_data:
            validated_data["status"] = (
                PLAN_VERSION_STATUS.ACTIVE
                if make_active
                else PLAN_VERSION_STATUS.INACTIVE
            )
        if transition_to_plan:
            validated_data.pop("transition_to_plan_id")
        billing_plan = PlanVersion.objects.create(**validated_data)
        if transition_to_plan:
            billing_plan.transition_to = transition_to_plan
        # elif transition_to_plan_version:
        #     billing_plan.transition_to = transition_to_plan_version
        org = billing_plan.organization
        for component in components:
            component.plan_version = billing_plan
            component.save()
        for feature_data in features_data:
            feature_data["organization"] = org
            try:
                f, _ = Feature.objects.get_or_create(**feature_data)
            except Feature.MultipleObjectsReturned:
                f = Feature.objects.filter(**feature_data).first()
            billing_plan.features.add(f)
        if price_adjustment_data:
            price_adjustment_data["organization"] = org
            try:
                pa, _ = PriceAdjustment.objects.get_or_create(**price_adjustment_data)
            except PriceAdjustment.MultipleObjectsReturned:
                pa = PriceAdjustment.objects.filter(**price_adjustment_data).first()
            billing_plan.price_adjustment = pa
        billing_plan.save()
        if make_active:
            billing_plan.plan.make_version_active(
                billing_plan, make_active_type, replace_immediately_type
            )
        return billing_plan


class InitialPlanVersionSerializer(PlanVersionSerializer):
    class Meta(PlanVersionSerializer.Meta):
        model = PlanVersion
        fields = tuple(
            set(PlanVersionSerializer.Meta.fields)
            - set(
                [
                    "plan_id",
                    "replace_plan_version_id",
                    "make_active",
                    "make_active_type",
                    "replace_immediately_type",
                ]
            )
        )


class PlanNameAndIDSerializer(serializers.ModelSerializer):
    class Meta:
        model = Plan
        fields = (
            "plan_name",
            "plan_id",
        )


class CustomerNameAndIDSerializer(serializers.ModelSerializer):
    class Meta:
        model = Customer
        fields = (
            "customer_name",
            "customer_id",
        )


class PlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = Plan
        fields = (
            "plan_name",
            "plan_duration",
            "product_id",
            "plan_id",
            "status",
            # write only
            "initial_external_links",
            "initial_version",
            "parent_plan_id",
            "target_customer_id",
            # read-only
            "external_links",
            "parent_plan",
            "target_customer",
            "created_on",
            "created_by",
            "display_version",
            "num_versions",
            "active_subscriptions",
        )
        read_only_fields = (
            "parent_plan",
            "target_customer",
            "created_on",
            "created_by",
            "display_version",
        )
        extra_kwargs = {
            "initial_version": {"write_only": True},
            "parent_plan_id": {"write_only": True},
            "target_customer_id": {"write_only": True},
        }

    product_id = SlugRelatedFieldWithOrganization(
        slug_field="product_id",
        queryset=Product.objects.all(),
        read_only=False,
        source="parent_product",
        required=False,
        allow_null=True,
    )

    # WRITE ONLY
    initial_version = InitialPlanVersionSerializer(write_only=True)
    parent_plan_id = SlugRelatedFieldWithOrganization(
        slug_field="plan_id",
        queryset=Plan.objects.all(),
        write_only=True,
        source="parent_plan",
        required=False,
    )
    target_customer_id = SlugRelatedFieldWithOrganization(
        slug_field="customer_id",
        queryset=Customer.objects.all(),
        write_only=True,
        source="target_customer",
        required=False,
    )
    initial_external_links = InitialExternalPlanLinkSerializer(
        many=True, required=False, write_only=True
    )

    # READ ONLY
    parent_plan = PlanNameAndIDSerializer(read_only=True)
    target_customer = CustomerNameAndIDSerializer(read_only=True)
    created_by = serializers.SerializerMethodField(read_only=True)
    display_version = PlanVersionSerializer(read_only=True)
    num_versions = serializers.SerializerMethodField(read_only=True)
    active_subscriptions = serializers.SerializerMethodField(read_only=True)
    external_links = ExternalPlanLinkSerializer(many=True, read_only=True)

    def get_created_by(self, obj) -> str:
        if obj.created_by:
            return obj.created_by.username
        else:
            return None

    def get_num_versions(self, obj) -> int:
        return len(obj.version_numbers())

    def get_active_subscriptions(self, obj) -> int:
        return sum(x.active_subscriptions for x in obj.active_subs_by_version())

    def validate(self, data):
        # we'll feed the version data into the serializer later, checking now breaks it
        plan_version = data.pop("initial_version")
        initial_external_links = data.get("initial_external_links")
        if initial_external_links:
            data.pop("initial_external_links")
        super().validate(data)
        target_cust_null = data.get("target_customer") is None
        parent_plan_null = data.get("parent_plan") is None
        if any([target_cust_null, parent_plan_null]) and not all(
            [target_cust_null, parent_plan_null]
        ):
            raise serializers.ValidationError(
                "either both or none of target_customer and parent_plan must be set"
            )
        data["initial_version"] = plan_version
        for component in plan_version.get("components", {}):
            proration_granularity = component.proration_granularity
            metric_granularity = component.metric.granularity
            if plan_version.plan_duration == PLAN_DURATION.MONTHLY:
                assert metric_granularity not in [
                    METRIC_GRANULARITY.YEAR,
                    METRIC_GRANULARITY.QUARTER,
                ]
            elif plan_version.plan_duration == PLAN_DURATION.QUARTERLY:
                assert metric_granularity not in [METRIC_GRANULARITY.YEAR]
        if initial_external_links:
            data["initial_external_links"] = initial_external_links
        return data

    def create(self, validated_data):
        display_version_data = validated_data.pop("initial_version")
        initial_external_links = validated_data.get("initial_external_links")
        transition_to_plan_id = validated_data.get("transition_to_plan_id")
        if initial_external_links:
            validated_data.pop("initial_external_links")
        if transition_to_plan_id:
            display_version_data.pop("transition_to_plan_id")
        plan = Plan.objects.create(**validated_data)
        try:
            display_version_data["status"] = PLAN_VERSION_STATUS.ACTIVE
            display_version_data["plan"] = plan
            display_version_data["organization"] = validated_data["organization"]
            display_version_data["created_by"] = validated_data["created_by"]
            plan_version = InitialPlanVersionSerializer().create(display_version_data)
            if initial_external_links:
                for link_data in initial_external_links:
                    link_data["plan"] = plan
                    link_data["organization"] = validated_data["organization"]
                    ExternalPlanLinkSerializer(
                        context={"organization": validated_data["organization"]}
                    ).validate(link_data)
                    ExternalPlanLinkSerializer().create(link_data)
            plan.display_version = plan_version
            plan.save()
            return plan
        except Exception as e:
            plan.delete()
            raise e


class PlanUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Plan
        fields = (
            "plan_name",
            "status",
        )

    status = serializers.ChoiceField(choices=[PLAN_STATUS.ACTIVE, PLAN_STATUS.ARCHIVED])

    def validate(self, data):
        data = super().validate(data)
        if data.get("status") == PLAN_STATUS.ARCHIVED:
            versions_count = self.instance.active_subs_by_version()
            cnt = sum([version.active_subscriptions for version in versions_count])
            if cnt > 0:
                raise serializers.ValidationError(
                    "Cannot archive a plan with active subscriptions"
                )
        return data

    def update(self, instance, validated_data):
        instance.plan_name = validated_data.get("plan_name", instance.plan_name)
        instance.status = validated_data.get("status", instance.status)
        instance.save()
        return instance


class PlanDetailSerializer(PlanSerializer):
    class Meta(PlanSerializer.Meta):
        model = Plan
        fields = tuple(
            set(PlanSerializer.Meta.fields).union(set(["versions"]))
            - set(
                [
                    "display_version",
                    "initial_version",
                    "parent_plan_id",
                    "target_customer_id",
                ]
            )
        )

    versions = serializers.SerializerMethodField()

    def get_versions(self, obj) -> PlanVersionSerializer(many=True):
        return PlanVersionSerializer(
            obj.versions.all().order_by("version"), many=True
        ).data


## SUBSCRIPTION
class SubscriptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Subscription
        fields = (
            "customer_id",
            "customer",
            "plan_id",
            "start_date",
            "end_date",
            "scheduled_end_date",
            "status",
            "auto_renew",
            "is_new",
            "subscription_id",
            "align_to_next_period_start",
        )
        read_only_fields = (
            "customer",
            "scheduled_end_date",
        )

    start_date = serializers.DateTimeField()
    end_date = serializers.DateTimeField(required=False)
    auto_renew = serializers.BooleanField(required=False)
    is_new = serializers.BooleanField(required=False)
    subscription_id = serializers.CharField(required=False)

    # WRITE ONLY
    customer_id = SlugRelatedFieldWithOrganization(
        slug_field="customer_id",
        read_only=False,
        source="customer",
        queryset=Customer.objects.all(),
        write_only=True,
    )
    plan_id = SlugRelatedFieldWithOrganization(
        slug_field="plan_id",
        read_only=False,
        source="billing_plan.plan",
        queryset=Plan.objects.all(),
        write_only=True,
    )
    align_to_next_period_start = serializers.BooleanField(
        required=False, default=False, write_only=True
    )

    # READ ONLY
    customer = CustomerSerializer(read_only=True)

    def validate(self, data):
        # extract the plan version from the plan
        data["billing_plan"] = data["billing_plan"]["plan"].display_version
        # check no existing subs
        sd = data["start_date"]
        ed = calculate_end_date(data["billing_plan"].plan.plan_duration, sd)
        num_existing_subs = Subscription.objects.filter(
            Q(start_date__range=(sd, ed)) | Q(end_date__range=(sd, ed)),
            customer__customer_id=data["customer"].customer_id,
            billing_plan__version_id=data["billing_plan"].version_id,
            status=SUBSCRIPTION_STATUS.ACTIVE,
        ).count()
        if num_existing_subs > 0:
            raise serializers.ValidationError(
                f"Customer already has an active subscription to this plan"
            )
        # check that if the plan is designed for a specific customer, that the customer is that customer
        tc = data["billing_plan"].plan.target_customer
        if tc is not None and tc != data["customer"]:
            raise serializers.ValidationError(
                f"This plan is for a customer with customer_id {tc.customer_id}, not {data['customer'].customer_id}"
            )
        return data

    def create(self, validated_data):
        align_to_next_period_start = validated_data.pop(
            "align_to_next_period_start", False
        )
        sub = super().create(validated_data)
        if align_to_next_period_start:
            sub.end_date = calculate_end_date(
                sub.billing_plan.plan.plan_duration,
                sub.start_date,
                clip_to_period_end=True,
            )
            sub.save()
        # new subscription means we need to create an invoice if its pay in advance
        if sub.billing_plan.flat_fee_billing_type == FLAT_FEE_BILLING_TYPE.IN_ADVANCE:
            if align_to_next_period_start:
                generate_invoice(
                    sub,
                    flat_fee_cutoff_date=sub.end_date - relativedelta(days=1),
                    include_usage=False,
                )
            else:
                generate_invoice(sub, include_usage=False)
        return sub


class SubscriptionDetailSerializer(SubscriptionSerializer):
    class Meta(SubscriptionSerializer.Meta):
        model = Subscription
        fields = tuple(
            set(SubscriptionSerializer.Meta.fields).union(set(["billing_plan"]))
        )

    billing_plan = PlanVersionSerializer(read_only=True)


class SubscriptionInvoiceSerializer(SubscriptionSerializer):
    class Meta(SubscriptionSerializer.Meta):
        model = Subscription
        fields = fields = tuple(
            set(SubscriptionSerializer.Meta.fields)
            - set(
                [
                    "customer_id",
                    "plan_id",
                    "billing_plan",
                    "auto_renew",
                ]
            )
        )


class SubscriptionUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Subscription
        fields = ("plan_id", "status", "auto_renew", "replace_immediately_type")

    plan_id = SlugRelatedFieldWithOrganization(
        slug_field="plan_id",
        read_only=False,
        source="billing_plan.plan",
        queryset=Plan.objects.all(),
        write_only=True,
        required=False,
    )
    status = serializers.ChoiceField(
        choices=[SUBSCRIPTION_STATUS.ENDED], required=False
    )
    auto_renew = serializers.BooleanField(required=False)
    replace_immediately_type = serializers.ChoiceField(
        choices=REPLACE_IMMEDIATELY_TYPE.choices, write_only=True
    )

    def validate(self, data):
        data = super().validate(data)
        # extract the plan version from the plan
        if data.get("billing_plan"):
            data["billing_plan"] = data["billing_plan"]["plan"].display_version
        if data.get("status") and data.get("billing_plan"):
            raise serializers.ValidationError(
                "Can only change one of status and plan version"
            )
        if (data.get("status") or data.get("billing_plan")) and not data.get(
            "replace_immediately_type"
        ):
            raise serializers.ValidationError(
                "To specify status or plan_id change, must specify replace_immediately_type"
            )
        if (
            data.get("status")
            and data.get("replace_immediately_type")
            == REPLACE_IMMEDIATELY_TYPE.CHANGE_SUBSCRIPTION_PLAN
        ):
            raise serializers.ValidationError(
                "Cannot use CHANGE_SUBSCRIPTION_PLAN replace type with ending a subscription"
            )
        return data

    def update(self, instance, validated_data):
        instance.auto_renew = validated_data.get("auto_renew", instance.auto_renew)
        new_bp = validated_data.get("billing_plan")
        if (
            validated_data.get("replace_immediately_type")
            == REPLACE_IMMEDIATELY_TYPE.CHANGE_SUBSCRIPTION_PLAN
        ):
            instance.switch_subscription_bp(new_bp)
        elif validated_data.get("status") or new_bp:
            replace_type = validated_data.get("replace_immediately_type")
            prorate = new_bp is not None
            bill_usage = (
                replace_type
                == REPLACE_IMMEDIATELY_TYPE.END_CURRENT_SUBSCRIPTION_AND_BILL
            )
            instance.end_subscription_now(prorate=prorate, bill_usage=bill_usage)
            if new_bp is not None:
                Subscription.objects.create(
                    billing_plan=new_bp,
                    organization=instance.organization,
                    customer=instance.customer,
                    start_date=instance.end_date,
                    status=SUBSCRIPTION_STATUS.ACTIVE,
                    auto_renew=True,
                    is_new=False,
                )
        instance.save()
        return instance


class ExperimentalToActiveRequestSerializer(serializers.Serializer):
    version_id = SlugRelatedFieldWithOrganization(
        queryset=PlanVersion.objects.filter(plan__status=PLAN_STATUS.EXPERIMENTAL),
        slug_field="version_id",
        read_only=False,
    )


class SubscriptionActionSerializer(SubscriptionSerializer):
    class Meta(SubscriptionSerializer.Meta):
        model = Subscription
        fields = SubscriptionSerializer.Meta.fields + ("string_repr", "object_type")

    string_repr = serializers.SerializerMethodField()
    object_type = serializers.SerializerMethodField()

    def get_string_repr(self, obj):
        return obj.subscription_id

    def get_object_type(self, obj):
        return "Subscription"


class UserActionSerializer(OrganizationUserSerializer):
    class Meta(OrganizationUserSerializer.Meta):
        model = User
        fields = OrganizationUserSerializer.Meta.fields + ("string_repr",)

    string_repr = serializers.SerializerMethodField()

    def get_string_repr(self, obj):
        return obj.username


class PlanVersionActionSerializer(PlanVersionSerializer):
    class Meta(PlanVersionSerializer.Meta):
        model = PlanVersion
        fields = PlanVersionSerializer.Meta.fields + ("string_repr", "object_type")

    string_repr = serializers.SerializerMethodField()
    object_type = serializers.SerializerMethodField()

    def get_string_repr(self, obj):
        return obj.plan.plan_name + " v" + str(obj.version)

    def get_object_type(self, obj):
        return "Plan Version"


class PlanActionSerializer(PlanSerializer):
    class Meta(PlanSerializer.Meta):
        model = Plan
        fields = PlanSerializer.Meta.fields + ("string_repr", "object_type")

    string_repr = serializers.SerializerMethodField()
    object_type = serializers.SerializerMethodField()

    def get_string_repr(self, obj):
        return obj.plan_name

    def get_object_type(self, obj):
        return "Plan"


class MetricActionSerializer(MetricSerializer):
    class Meta(MetricSerializer.Meta):
        model = Metric
        fields = MetricSerializer.Meta.fields + ("string_repr", "object_type")

    string_repr = serializers.SerializerMethodField()
    object_type = serializers.SerializerMethodField()

    def get_string_repr(self, obj):
        return obj.billable_metric_name

    def get_object_type(self, obj):
        return "Metric"


class CustomerActionSerializer(CustomerSerializer):
    class Meta(CustomerSerializer.Meta):
        model = Customer
        fields = CustomerSerializer.Meta.fields + ("string_repr", "object_type")

    string_repr = serializers.SerializerMethodField()
    object_type = serializers.SerializerMethodField()

    def get_string_repr(self, obj):
        return obj.customer_name

    def get_object_type(self, obj):
        return "Customer"


GFK_MODEL_SERIALIZER_MAPPING = {
    User: UserActionSerializer,
    PlanVersion: PlanVersionActionSerializer,
    Plan: PlanActionSerializer,
    Subscription: SubscriptionActionSerializer,
    Metric: MetricActionSerializer,
    Customer: CustomerActionSerializer,
}


class ActivityGenericRelatedField(serializers.Field):
    """
    DRF Serializer field that serializers GenericForeignKey fields on the :class:`~activity.models.Action`
    of known model types to their respective ActionSerializer implementation.
    """

    def to_representation(self, value):
        serializer_cls = GFK_MODEL_SERIALIZER_MAPPING.get(type(value), None)
        return (
            serializer_cls(value, context=self.context).data
            if serializer_cls
            else str(value)
        )


class ActionSerializer(serializers.ModelSerializer):
    """
    DRF serializer for :class:`~activity.models.Action`.
    """

    actor = ActivityGenericRelatedField(read_only=True)
    action_object = ActivityGenericRelatedField(read_only=True)
    target = ActivityGenericRelatedField(read_only=True)

    class Meta:
        model = Action
        fields = (
            "id",
            "actor",
            "verb",
            "action_object",
            "target",
            "public",
            "description",
            "timestamp",
        )


class OrganizationSettingSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrganizationSetting
        fields = ("setting_id", "setting_name", "setting_value", "setting_group")
        read_only_fields = ("setting_id", "setting_name", "setting_group")

    def update(self, instance, validated_data):
        instance.setting_value = validated_data.get(
            "setting_value", instance.setting_value
        )
        instance.save()
        return instance


class InvoiceUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Invoice
        fields = ("payment_status",)

    payment_status = serializers.ChoiceField(
        choices=[INVOICE_STATUS.PAID, INVOICE_STATUS.UNPAID], required=True
    )

    def validate(self, data):
        data = super().validate(data)
        if self.instance.external_payment_obj_id is not None:
            raise serializers.ValidationError(
                f"Can't manually update connected invoices. This invoice is connected to {self.instance.external_payment_obj_type}"
            )
        return data

    def update(self, instance, validated_data):
        instance.payment_status = validated_data.get(
            "payment_status", instance.payment_status
        )
        instance.save()
        return instance


## INVOICE
class InvoiceLineItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = InvoiceLineItem
        fields = (
            "name",
            "start_date",
            "end_date",
            "quantity",
            "subtotal",
            "billing_type",
            "plan_version_id",
            "metadata",
        )

    plan_version_id = serializers.CharField(
        source="associated_plan_version.plan_version_id", read_only=True
    )


class InvoiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Invoice
        fields = (
            "invoice_id",
            "cost_due",
            "pricing_unit",
            "issue_date",
            "payment_status",
            "cust_connected_to_payment_provider",
            "org_connected_to_cust_payment_provider",
            "external_payment_obj_id",
            "external_payment_obj_type",
            "line_items",
            "customer",
            "subscription",
        )

    cost_due = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
    )
    pricing_unit = PricingUnitSerializer()
    customer = CustomerSerializer(read_only=True)
    subscription = SubscriptionSerializer(read_only=True)
    line_items = InvoiceLineItemSerializer(
        many=True, read_only=True, source="inv_line_items"
    )


class DraftInvoiceSerializer(InvoiceSerializer):
    class Meta(InvoiceSerializer.Meta):
        model = Invoice
        fields = tuple(
            set(InvoiceSerializer.Meta.fields)
            - set(
                [
                    "invoice_id",
                    "issue_date",
                    "external_payment_obj_id",
                    "external_payment_obj_type",
                ]
            )
        )

    payment_status = serializers.ChoiceField(
        choices=[INVOICE_STATUS.DRAFT], required=True
    )


class CustomerBalanceAdjustmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomerBalanceAdjustment
        fields = (
            "adjustment_id",
            "customer_id",
            "amount",
            "pricing_unit_code",
            "pricing_unit",
            "description",
            "effective_at",
            "expires_at",
            "status",
            "parent_adjustment_id",
        )

    customer_id = SlugRelatedFieldWithOrganization(
        slug_field="customer_id",
        queryset=Customer.objects.all(),
        required=True,
        source="customer",
    )
    pricing_unit_code = SlugRelatedFieldWithOrganizationOrNull(
        slug_field="code",
        queryset=PricingUnit.objects.all(),
        required=True,
        source="pricing_unit",
        write_only=True,
    )
    pricing_unit = PricingUnitSerializer(read_only=True)
    parent_adjustment_id = SlugRelatedFieldWithOrganization(
        slug_field="adjustment_id",
        required=False,
        source="parent_adjustment",
        read_only=True,
    )

    def validate(self, data):
        data = super().validate(data)
        amount = data.get("amount", 0)
        customer = data["customer"]
        if amount <= 0:
            raise serializers.ValidationError("Amount must be non-zero")
        return data


class CustomerDetailSerializer(serializers.ModelSerializer):
    class Meta:
        model = Customer
        fields = (
            "customer_id",
            "email",
            "customer_name",
            "invoices",
            "total_amount_due",
            "next_amount_due",
            "subscriptions",
            "integrations",
            "default_currency",
        )

    subscriptions = serializers.SerializerMethodField()
    invoices = serializers.SerializerMethodField()
    total_amount_due = serializers.SerializerMethodField()
    next_amount_due = serializers.SerializerMethodField()
    default_currency = PricingUnitSerializer()

    def get_subscriptions(self, obj) -> SubscriptionCustomerDetailSerializer(many=True):
        return SubscriptionCustomerDetailSerializer(
            obj.customer_subscriptions.filter(status=SUBSCRIPTION_STATUS.ACTIVE),
            many=True,
        ).data

    def get_invoices(self, obj) -> InvoiceSerializer(many=True):
        timeline = self.context.get("invoices")
        timeline = InvoiceSerializer(timeline, many=True).data
        return timeline

    def get_total_amount_due(self, obj) -> float:
        total_amount_due = float(self.context.get("total_amount_due"))
        return total_amount_due

    def get_next_amount_due(self, obj) -> float:
        next_amount_due = float(self.context.get("next_amount_due"))
        return next_amount_due
