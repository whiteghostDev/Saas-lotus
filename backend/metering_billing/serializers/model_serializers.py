from datetime import timedelta
from decimal import Decimal
from typing import Union

import api.serializers.model_serializers as api_serializers
from actstream.models import Action
from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.db.models import Q
from metering_billing.aggregation.billable_metrics import METRIC_HANDLER_MAP
from metering_billing.exceptions import DuplicateMetric, ServerError
from metering_billing.invoice import generate_invoice
from metering_billing.models import *
from metering_billing.payment_providers import PAYMENT_PROVIDER_MAP
from metering_billing.serializers.serializer_utils import (
    SlugRelatedFieldWithOrganization,
)
from metering_billing.utils import calculate_end_date, now_utc
from metering_billing.utils.enums import *
from rest_framework import serializers
from rest_framework.exceptions import APIException, ValidationError

SVIX_CONNECTOR = settings.SVIX_CONNECTOR


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


class PricingUnitSerializer(api_serializers.PricingUnitSerializer):
    class Meta(api_serializers.PricingUnitSerializer.Meta):
        fields = api_serializers.PricingUnitSerializer.Meta.fields

    def validate(self, attrs):
        super().validate(attrs)
        code_exists = PricingUnit.objects.filter(
            Q(organization=self.context["organization"]),
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
            "available_currencies",
            "tax_rate",
        )

    users = serializers.SerializerMethodField()
    default_currency = PricingUnitSerializer()
    available_currencies = serializers.SerializerMethodField()

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

    def get_available_currencies(self, obj) -> PricingUnitSerializer(many=True):
        return PricingUnitSerializer(
            PricingUnit.objects.filter(organization=obj), many=True
        ).data


class APITokenSerializer(serializers.ModelSerializer):
    class Meta:
        model = APIToken
        fields = ("name", "prefix", "expiry_date", "created")

    extra_kwargs = {"prefix": {"read_only": True}, "created": {"read_only": True}}

    def validate(self, attrs):
        super().validate(attrs)
        now = now_utc()
        if attrs.get("expiry_date") and attrs["expiry_date"] < now:
            raise serializers.ValidationError("Expiry date cannot be in the past")
        return attrs

    def create(self, validated_data):
        api_key, key = APIToken.objects.create_key(**validated_data)
        num_matching_prefix = APIToken.objects.filter(prefix=api_key.prefix).count()
        while num_matching_prefix > 1:
            api_key.delete()
            api_key, key = APIToken.objects.create_key(**validated_data)
            num_matching_prefix = APIToken.objects.filter(prefix=api_key.prefix).count()
        return api_key, key


class OrganizationUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organization
        fields = ("default_currency_code", "address", "tax_rate")

    default_currency_code = SlugRelatedFieldWithOrganization(
        slug_field="code", queryset=PricingUnit.objects.all(), source="default_currency"
    )
    address = api_serializers.AddressSerializer(required=False, allow_null=True)

    def update(self, instance, validated_data):
        assert (
            type(validated_data.get("default_currency")) == PricingUnit
            or validated_data.get("default_currency") is None
        )
        instance.default_currency = validated_data.get(
            "default_currency", instance.default_currency
        )
        address = validated_data.pop("address", None)
        if address:
            cur_properties = instance.properties or {}
            new_properties = {**cur_properties, "address": address}
            instance.properties = new_properties
        instance.tax_rate = validated_data.get("tax_rate", instance.tax_rate)
        instance.save()
        return instance


class CustomerUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Customer
        fields = ("default_currency_code",)

    default_currency_code = SlugRelatedFieldWithOrganization(
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


class EventSerializer(api_serializers.EventSerializer):
    class Meta(api_serializers.EventSerializer.Meta):
        fields = api_serializers.EventSerializer.Meta.fields


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
        if SVIX_CONNECTOR is None:
            raise serializers.ValidationError(
                "Webhook endpoints are not supported in this environment"
            )
        return super().validate(attrs)

    def create(self, validated_data):
        if not validated_data.get("organization").webhooks_provisioned:
            validated_data.get("organization").provision_webhooks()
        if not validated_data.get("organization").webhooks_provisioned:
            raise serializers.ValidationError(
                "Webhook endpoints are not supported in this environment or are not currently available."
            )
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


# USER
class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("username", "email", "company_name", "organization_id")

    organization_id = serializers.CharField(source="organization.organization_id")
    company_name = serializers.CharField(source="organization.company_name")


# CUSTOMER


class SubscriptionCustomerSummarySerializer(
    api_serializers.SubscriptionCustomerSummarySerializer
):
    class Meta(api_serializers.SubscriptionCustomerSummarySerializer.Meta):
        fields = api_serializers.SubscriptionCustomerSummarySerializer.Meta.fields


class SubscriptionCustomerDetailSerializer(
    api_serializers.SubscriptionCustomerDetailSerializer
):
    class Meta(api_serializers.SubscriptionCustomerDetailSerializer.Meta):
        fields = api_serializers.SubscriptionCustomerDetailSerializer.Meta.fields


class CustomerWithRevenueSerializer(serializers.ModelSerializer):
    class Meta:
        model = Customer
        fields = (
            "customer_id",
            "total_amount_due",
        )

    total_amount_due = serializers.SerializerMethodField()

    def get_total_amount_due(self, obj) -> float:
        total_amount_due = float(self.context.get("total_amount_due"))
        return total_amount_due


class CustomerSerializer(api_serializers.CustomerSerializer):
    def update(self, instance, validated_data, behavior="merge"):
        instance.customer_id = validated_data.get(
            "customer_id", instance.customer_id if behavior == "merge" else None
        )
        instance.tax_rate = validated_data.get(
            "tax_rate", instance.tax_rate if behavior == "merge" else None
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


class CategoricalFilterSerializer(api_serializers.CategoricalFilterSerializer):
    class Meta(api_serializers.CategoricalFilterSerializer.Meta):
        fields = api_serializers.CategoricalFilterSerializer.Meta.fields


class SubscriptionCategoricalFilterSerializer(
    api_serializers.SubscriptionCategoricalFilterSerializer
):
    class Meta(api_serializers.SubscriptionCategoricalFilterSerializer.Meta):
        fields = api_serializers.SubscriptionCategoricalFilterSerializer.Meta.fields


class NumericFilterSerializer(api_serializers.NumericFilterSerializer):
    class Meta(api_serializers.NumericFilterSerializer.Meta):
        fields = api_serializers.NumericFilterSerializer.Meta.fields


class MetricUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Metric
        fields = (
            "billable_metric_name",
            "status",
        )

    def validate(self, data):
        data = super().validate(data)
        active_plan_versions_with_metric = []
        if data.get("status") == METRIC_STATUS.ARCHIVED:
            all_active_plan_versions = PlanVersion.objects.filter(
                ~Q(status=PLAN_VERSION_STATUS.ARCHIVED),
                organization=self.context["organization"],
                plan__in=Plan.objects.filter(
                    organization=self.context["organization"], status=PLAN_STATUS.ACTIVE
                ),
            ).prefetch_related("plan_components", "plan_components__billable_metric")
            for plan_version in all_active_plan_versions:
                for component in plan_version.plan_components.all():
                    if component.billable_metric == self.instance:
                        active_plan_versions_with_metric.append(str(plan_version))
        if len(active_plan_versions_with_metric) > 0:
            raise serializers.ValidationError(
                f"Cannot archive metric. It is currently used in the following plan versions: {', '.join(active_plan_versions_with_metric)}"
            )
        return data

    def update(self, instance, validated_data):
        instance.billable_metric_name = validated_data.get(
            "billable_metric_name", instance.billable_metric_name
        )
        instance.status = validated_data.get("status", instance.status)
        instance.save()
        if instance.status == METRIC_STATUS.ARCHIVED:
            METRIC_HANDLER_MAP[instance.metric_type].archive_metric(instance)
        return instance


class MetricSerializer(api_serializers.MetricSerializer):
    class Meta(api_serializers.MetricSerializer.Meta):
        fields = tuple(
            set(api_serializers.MetricSerializer.Meta.fields) - {"aggregation_type"}
        ) + (
            "usage_aggregation_type",
            "billable_aggregation_type",
        )


class MetricCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Metric
        fields = (
            "event_name",
            "property_name",
            "usage_aggregation_type",
            "billable_aggregation_type",
            "granularity",
            "event_type",
            "metric_type",
            "metric_name",
            "proration",
            "properties",
            "is_cost_metric",
            "custom_sql",
        )
        extra_kwargs = {
            "event_name": {"write_only": True, "required": True},
            "property_name": {"write_only": True},
            "usage_aggregation_type": {"write_only": True},
            "billable_aggregation_type": {"write_only": True},
            "granularity": {"write_only": True},
            "event_type": {"write_only": True},
            "metric_type": {"required": True, "write_only": True},
            "metric_name": {"write_only": True},
            "properties": {"write_only": True},
            "is_cost_metric": {"write_only": True},
            "custom_sql": {"write_only": True},
            "proration": {"write_only": True, "required": False, "allow_null": True},
        }

    metric_name = serializers.CharField(source="billable_metric_name")
    # granularity = serializers.ChoiceField(
    #     choices=METRIC_GRANULARITY.choices,
    #     required=False,
    # )
    # event_type = serializers.ChoiceField(
    #     choices=EVENT_TYPE.choices,
    #     required=False,
    # )
    # properties = serializers.JSONField(allow_null=True, required=False)

    def validate(self, data):
        data = super().validate(data)
        metric_type = data["metric_type"]
        data = METRIC_HANDLER_MAP[metric_type].validate_data(data)
        return data

    def create(self, validated_data):
        metric_type = validated_data["metric_type"]
        metric = METRIC_HANDLER_MAP[metric_type].create_metric(validated_data)
        return metric


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


class InitialExternalPlanLinkSerializer(
    api_serializers.InitialExternalPlanLinkSerializer
):
    class Meta(api_serializers.InitialExternalPlanLinkSerializer.Meta):
        fields = api_serializers.InitialExternalPlanLinkSerializer.Meta.fields


# FEATURE
class FeatureSerializer(api_serializers.FeatureSerializer):
    class Meta(api_serializers.FeatureSerializer.Meta):
        fields = api_serializers.FeatureSerializer.Meta.fields


class PriceTierSerializer(api_serializers.PriceTierSerializer):
    class Meta(api_serializers.PriceTierSerializer.Meta):
        fields = api_serializers.PriceTierSerializer.Meta.fields

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


class PriceTierCreateSerializer(serializers.ModelSerializer):
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


# PLAN COMPONENT
class PlanComponentSerializer(api_serializers.PlanComponentSerializer):
    class Meta(api_serializers.PlanComponentSerializer.Meta):
        fields = tuple(
            set(api_serializers.PlanComponentSerializer.Meta.fields)
            - {"billable_metric", "pricing_unit"}
        ) + ("metric_id",)
        extra_kwargs = {**api_serializers.PlanComponentSerializer.Meta.extra_kwargs}

    metric_id = SlugRelatedFieldWithOrganization(
        slug_field="metric_id",
        write_only=True,
        source="billable_metric",
        queryset=Metric.objects.all(),
    )
    tiers = PriceTierCreateSerializer(many=True, required=False)

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
        source="transition_to",
    )

    def validate(self, data):
        transition_to_plan_id = data.get("transition_to_plan_id")
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
        if transition_to_plan:
            instance.transition_to = transition_to_plan
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


class PlanVersionSerializer(api_serializers.PlanVersionSerializer):
    class Meta(api_serializers.PlanVersionSerializer.Meta):
        fields = api_serializers.PlanVersionSerializer.Meta.fields + (
            "version_id",
            "plan_id",
        )
        extra_kwargs = {**api_serializers.PlanVersionSerializer.Meta.extra_kwargs}

    plan_id = serializers.CharField(source="plan.plan_id", read_only=True)


class PlanVersionCreateSerializer(serializers.ModelSerializer):
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
            "day_anchor",
            "month_anchor",
            "make_active",
            "make_active_type",
            "replace_immediately_type",
            "transition_to_plan_id",
            "currency_code",
        )
        extra_kwargs = {
            "description": {"write_only": True},
            "plan_id": {"write_only": True},
            "flat_fee_billing_type": {"write_only": True},
            "flat_rate": {"write_only": True},
            "components": {"write_only": True},
            "features": {"write_only": True},
            "price_adjustment": {"write_only": True},
            "usage_billing_frequency": {"write_only": True},
            "day_anchor": {"write_only": True},
            "month_anchor": {"write_only": True},
            "make_active": {"write_only": True},
            "make_active_type": {"write_only": True},
            "replace_immediately_type": {"write_only": True},
            "transition_to_plan_id": {"write_only": True},
            "currency_code": {"write_only": True},
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
    make_active = serializers.BooleanField()
    make_active_type = serializers.ChoiceField(
        choices=MAKE_PLAN_VERSION_ACTIVE_TYPE.choices,
        required=False,
    )
    replace_immediately_type = serializers.ChoiceField(
        choices=REPLACE_IMMEDIATELY_TYPE.choices,
        required=False,
    )
    transition_to_plan_id = SlugRelatedFieldWithOrganization(
        slug_field="plan_id",
        queryset=Plan.objects.all(),
        required=False,
    )
    currency_code = SlugRelatedFieldWithOrganization(
        slug_field="code",
        queryset=PricingUnit.objects.all(),
        required=False,
    )

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
        pricing_unit = validated_data.pop("currency_code", None)
        components_data = validated_data.pop("plan_components", [])
        if len(components_data) > 0:
            if pricing_unit is not None:
                data = [
                    {**component_data, "pricing_unit": pricing_unit}
                    for component_data in components_data
                ]
            else:
                data = components_data
            components = PlanComponentSerializer(many=True).create(data)
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
        billing_plan = PlanVersion.objects.create(
            **validated_data, pricing_unit=pricing_unit
        )
        if transition_to_plan:
            billing_plan.transition_to = transition_to_plan
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


class InitialPlanVersionSerializer(PlanVersionCreateSerializer):
    class Meta(PlanVersionCreateSerializer.Meta):
        model = PlanVersion
        fields = tuple(
            set(PlanVersionCreateSerializer.Meta.fields)
            - set(
                [
                    "plan_id",
                    "version_id",
                    "make_active",
                    "make_active_type",
                    "replace_immediately_type",
                ]
            )
        )


class PlanNameAndIDSerializer(api_serializers.PlanNameAndIDSerializer):
    class Meta(api_serializers.PlanNameAndIDSerializer.Meta):
        fields = api_serializers.PlanNameAndIDSerializer.Meta.fields


class LightweightCustomerSerializer(api_serializers.LightweightCustomerSerializer):
    class Meta(api_serializers.LightweightCustomerSerializer.Meta):
        fields = api_serializers.LightweightCustomerSerializer.Meta.fields


class PlanSerializer(api_serializers.PlanSerializer):
    class Meta(api_serializers.PlanSerializer.Meta):
        fields = api_serializers.PlanSerializer.Meta.fields + ("versions",)

    versions = serializers.SerializerMethodField()

    def get_versions(self, obj) -> PlanVersionSerializer(many=True):
        return PlanVersionSerializer(
            obj.versions.all().order_by("version"), many=True
        ).data


class PlanCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Plan
        fields = (
            "plan_name",
            "plan_duration",
            "plan_id",
            "status",
            "initial_external_links",
            "initial_version",
            "parent_plan_id",
            "target_customer_id",
        )
        extra_kwargs = {
            "plan_name": {"write_only": True},
            "plan_duration": {"write_only": True},
            "plan_id": {"write_only": True},
            "status": {"write_only": True},
            "initial_external_links": {"write_only": True},
            "initial_version": {"write_only": True},
            "parent_plan_id": {"write_only": True},
            "target_customer_id": {"write_only": True},
        }

    initial_version = InitialPlanVersionSerializer()
    parent_plan_id = SlugRelatedFieldWithOrganization(
        slug_field="plan_id",
        queryset=Plan.objects.all(),
        source="parent_plan",
        required=False,
    )
    target_customer_id = SlugRelatedFieldWithOrganization(
        slug_field="customer_id",
        queryset=Customer.objects.all(),
        source="target_customer",
        required=False,
    )
    initial_external_links = InitialExternalPlanLinkSerializer(
        many=True, required=False
    )

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
            raise ServerError(e)


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


class SubscriptionRecordSerializer(api_serializers.SubscriptionRecordSerializer):
    class Meta(api_serializers.SubscriptionRecordSerializer.Meta):
        fields = api_serializers.SubscriptionRecordSerializer.Meta.fields


class SubscriptionRecordSerializer(api_serializers.SubscriptionRecordSerializer):
    class Meta(api_serializers.SubscriptionRecordSerializer.Meta):
        fields = api_serializers.SubscriptionRecordSerializer.Meta.fields


class LightweightPlanVersionSerializer(
    api_serializers.LightweightPlanVersionSerializer
):
    class Meta(api_serializers.LightweightPlanVersionSerializer.Meta):
        fields = api_serializers.LightweightPlanVersionSerializer.Meta.fields


class LightweightSubscriptionRecordSerializer(
    api_serializers.LightweightSubscriptionRecordSerializer
):
    class Meta(api_serializers.LightweightSubscriptionRecordSerializer.Meta):
        fields = api_serializers.LightweightSubscriptionRecordSerializer.Meta.fields


class SubscriptionSerializer(api_serializers.SubscriptionSerializer):
    class Meta(api_serializers.SubscriptionSerializer.Meta):
        fields = api_serializers.SubscriptionSerializer.Meta.fields


class SubscriptionInvoiceSerializer(api_serializers.SubscriptionInvoiceSerializer):
    class Meta(api_serializers.SubscriptionInvoiceSerializer.Meta):
        fields = api_serializers.SubscriptionInvoiceSerializer.Meta.fields


class SubscriptionRecordUpdateSerializer(
    api_serializers.SubscriptionRecordUpdateSerializer
):
    class Meta(api_serializers.SubscriptionRecordUpdateSerializer.Meta):
        fields = api_serializers.SubscriptionRecordUpdateSerializer.Meta.fields


class SubscriptionRecordFilterSerializer(
    api_serializers.SubscriptionRecordFilterSerializer
):
    pass


class SubscriptionRecordFilterSerializerDelete(
    api_serializers.SubscriptionRecordFilterSerializerDelete
):
    pass


class SubscriptionRecordCancelSerializer(
    api_serializers.SubscriptionRecordCancelSerializer
):
    pass


class ListSubscriptionRecordFilter(api_serializers.ListSubscriptionRecordFilter):
    pass


# class ExperimentalToActiveRequestSerializer(serializers.Serializer):
#     version_id = SlugRelatedFieldWithOrganization(
#         queryset=PlanVersion.objects.filter(plan__status=PLAN_STATUS.EXPERIMENTAL),
#         slug_field="version_id",
#         read_only=False,
#     )


class SubscriptionActionSerializer(SubscriptionRecordSerializer):
    class Meta(SubscriptionRecordSerializer.Meta):
        model = SubscriptionRecord
        fields = SubscriptionRecordSerializer.Meta.fields + (
            "string_repr",
            "object_type",
        )

    string_repr = serializers.SerializerMethodField()
    object_type = serializers.SerializerMethodField()

    def get_string_repr(self, obj):
        return obj.subscription_id

    def get_object_type(self, obj):
        return "SubscriptionRecord"


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


class CustomerSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = Customer
        fields = (
            "customer_name",
            "customer_id",
            "subscriptions",
        )

    subscriptions = serializers.SerializerMethodField()

    def get_subscriptions(
        self, obj
    ) -> SubscriptionCustomerSummarySerializer(many=True, required=False):
        sub_obj = obj.subscription_records_filtered
        return SubscriptionCustomerSummarySerializer(sub_obj, many=True).data


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
    SubscriptionRecord: SubscriptionActionSerializer,
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


class InvoiceUpdateSerializer(api_serializers.InvoiceUpdateSerializer):
    class Meta(api_serializers.InvoiceUpdateSerializer.Meta):
        fields = api_serializers.InvoiceUpdateSerializer.Meta.fields


class InvoiceLineItemSerializer(api_serializers.InvoiceLineItemSerializer):
    class Meta(api_serializers.InvoiceLineItemSerializer.Meta):
        fields = api_serializers.InvoiceLineItemSerializer.Meta.fields


class LightweightInvoiceLineItemSerializer(
    api_serializers.LightweightInvoiceLineItemSerializer
):
    class Meta(api_serializers.LightweightInvoiceLineItemSerializer.Meta):
        fields = api_serializers.LightweightInvoiceLineItemSerializer.Meta.fields


class InvoiceSerializer(api_serializers.InvoiceSerializer):
    class Meta(api_serializers.InvoiceSerializer.Meta):
        fields = api_serializers.InvoiceSerializer.Meta.fields


class LightweightInvoiceSerializer(api_serializers.LightweightInvoiceSerializer):
    class Meta(api_serializers.LightweightInvoiceSerializer.Meta):
        fields = api_serializers.LightweightInvoiceSerializer.Meta.fields


class InvoiceListFilterSerializer(api_serializers.InvoiceListFilterSerializer):
    pass


class GroupedLineItemSerializer(serializers.Serializer):
    plan_name = serializers.CharField()
    subscription_filters = SubscriptionCategoricalFilterSerializer(many=True)
    subtotal = serializers.DecimalField(max_digits=10, decimal_places=2)
    start_date = serializers.DateTimeField()
    end_date = serializers.DateTimeField()
    sub_items = LightweightInvoiceLineItemSerializer(many=True)


class DraftInvoiceSerializer(InvoiceSerializer):
    class Meta(InvoiceSerializer.Meta):
        model = Invoice
        fields = tuple(
            set(InvoiceSerializer.Meta.fields)
            - set(
                [
                    "seller",
                    "customer",
                    "payment_status",
                    "invoice_number",
                    "external_payment_obj_id",
                    "external_payment_obj_type",
                ]
            )
        )

    line_items = serializers.SerializerMethodField()

    def get_line_items(self, obj) -> GroupedLineItemSerializer(many=True):
        associated_subscription_records = (
            obj.line_items.filter(associated_subscription_record__isnull=False)
            .values_list("associated_subscription_record", flat=True)
            .distinct()
        )
        srs = []
        for associated_subscription_record in associated_subscription_records:
            line_items = obj.line_items.filter(
                associated_subscription_record=associated_subscription_record
            ).order_by("name", "start_date", "subtotal")
            sr = line_items[0].associated_subscription_record
            grouped_line_item_dict = {
                "plan_name": sr.billing_plan.plan.plan_name,
                "subscription_filters": sr.filters.all(),
                "subtotal": line_items.aggregate(Sum("subtotal"))["subtotal__sum"] or 0,
                "start_date": sr.start_date,
                "end_date": sr.end_date,
                "sub_items": line_items,
            }
            srs.append(grouped_line_item_dict)
        data = GroupedLineItemSerializer(srs, many=True).data
        return data


class CustomerBalanceAdjustmentSerializer(
    api_serializers.CustomerBalanceAdjustmentSerializer
):
    class Meta(api_serializers.CustomerBalanceAdjustmentSerializer.Meta):
        fields = api_serializers.CustomerBalanceAdjustmentSerializer.Meta.fields
