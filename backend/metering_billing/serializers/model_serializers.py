import logging
from decimal import Decimal

import api.serializers.model_serializers as api_serializers
from actstream.models import Action
from django.conf import settings
from django.core.cache import cache
from django.db.models import DecimalField, Q, Sum
from metering_billing.aggregation.billable_metrics import METRIC_HANDLER_MAP
from metering_billing.exceptions import DuplicateOrganization, ServerError
from metering_billing.models import (
    AddOnSpecification,
    Address,
    APIToken,
    Customer,
    ExternalPlanLink,
    Feature,
    Invoice,
    Metric,
    Organization,
    OrganizationSetting,
    Plan,
    PlanComponent,
    PlanVersion,
    PriceAdjustment,
    PriceTier,
    PricingUnit,
    Product,
    RecurringCharge,
    SubscriptionRecord,
    Tag,
    TeamInviteToken,
    UsageAlert,
    User,
    WebhookEndpoint,
    WebhookTrigger,
)
from metering_billing.serializers.serializer_utils import (
    OrganizationSettingUUIDField,
    OrganizationUUIDField,
    PlanUUIDField,
    PlanVersionUUIDField,
    SlugRelatedFieldWithOrganization,
    TimezoneFieldMixin,
    TimeZoneSerializerField,
    WebhookEndpointUUIDField,
    WebhookSecretUUIDField,
)
from metering_billing.utils import now_utc
from metering_billing.utils.enums import (
    BATCH_ROUNDING_TYPE,
    MAKE_PLAN_VERSION_ACTIVE_TYPE,
    METRIC_GRANULARITY,
    METRIC_STATUS,
    ORGANIZATION_SETTING_GROUPS,
    ORGANIZATION_SETTING_NAMES,
    ORGANIZATION_STATUS,
    PAYMENT_PROCESSORS,
    PLAN_DURATION,
    PLAN_STATUS,
    PLAN_VERSION_STATUS,
    PRICE_TIER_TYPE,
    REPLACE_IMMEDIATELY_TYPE,
    TAG_GROUP,
    TAX_PROVIDER,
    WEBHOOK_TRIGGER_EVENTS,
)
from rest_framework import serializers
from rest_framework.exceptions import ValidationError

SVIX_CONNECTOR = settings.SVIX_CONNECTOR
logger = logging.getLogger("django.server")


class TagSerializer(api_serializers.TagSerializer):
    pass


class OrganizationUserSerializer(TimezoneFieldMixin, serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("username", "email", "role", "status")

    role = serializers.SerializerMethodField()
    status = serializers.ChoiceField(
        choices=ORGANIZATION_STATUS.choices, default=ORGANIZATION_STATUS.ACTIVE
    )

    def get_role(self, obj) -> str:
        return "Admin"


class OrganizationInvitedUserSerializer(
    TimezoneFieldMixin, serializers.ModelSerializer
):
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


class LightweightOrganizationSerializer(
    TimezoneFieldMixin, serializers.ModelSerializer
):
    class Meta:
        model = Organization
        fields = (
            "organization_id",
            "organization_name",
            "organization_type",
            "current",
        )

    organization_id = OrganizationUUIDField()
    organization_type = serializers.SerializerMethodField()
    current = serializers.SerializerMethodField()

    def get_organization_type(
        self, obj
    ) -> serializers.ChoiceField(choices=Organization.OrganizationType.labels):
        org_type = obj.organization_type
        if org_type == Organization.OrganizationType.PRODUCTION:
            return Organization.OrganizationType.PRODUCTION.label
        elif org_type == Organization.OrganizationType.DEVELOPMENT:
            return Organization.OrganizationType.DEVELOPMENT.label
        elif org_type == Organization.OrganizationType.INTERNAL_DEMO:
            return Organization.OrganizationType.INTERNAL_DEMO.label
        elif org_type == Organization.OrganizationType.EXTERNAL_DEMO:
            return Organization.OrganizationType.EXTERNAL_DEMO.label

    def get_current(self, obj) -> serializers.BooleanField():
        return obj == self.context.get("organization")


class LightweightUserSerializer(TimezoneFieldMixin, serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("username", "email")


class OrganizationSettingSerializer(TimezoneFieldMixin, serializers.ModelSerializer):
    class Meta:
        model = OrganizationSetting
        fields = ("setting_id", "setting_name", "setting_values", "setting_group")
        extra_kwargs = {
            "setting_id": {"required": True},
            "setting_name": {"required": True},
            "setting_group": {"required": True},
            "setting_values": {"required": True},
        }

    setting_id = OrganizationSettingUUIDField()
    setting_name = serializers.ChoiceField(
        choices=ORGANIZATION_SETTING_NAMES.choices, required=True
    )
    setting_group = serializers.ChoiceField(
        choices=ORGANIZATION_SETTING_GROUPS.choices, required=False
    )


class OrganizationSerializer(TimezoneFieldMixin, serializers.ModelSerializer):
    class Meta:
        model = Organization
        fields = (
            "organization_id",
            "organization_name",
            "users",
            "default_currency",
            "available_currencies",
            "plan_tags",
            "tax_rate",
            "payment_grace_period",
            "linked_organizations",
            "current_user",
            "address",
            "team_name",
            "subscription_filter_keys",
            "timezone",
            "stripe_account_id",
            "braintree_merchant_id",
            "tax_providers",
        )

    organization_id = OrganizationUUIDField()
    users = serializers.SerializerMethodField()
    default_currency = PricingUnitSerializer()
    available_currencies = serializers.SerializerMethodField()
    plan_tags = serializers.SerializerMethodField()
    payment_grace_period = serializers.SerializerMethodField()
    linked_organizations = serializers.SerializerMethodField()
    current_user = serializers.SerializerMethodField()
    address = serializers.SerializerMethodField()
    team_name = serializers.SerializerMethodField()
    subscription_filter_keys = serializers.SerializerMethodField()
    timezone = TimeZoneSerializerField(use_pytz=True)
    stripe_account_id = serializers.SerializerMethodField()
    braintree_merchant_id = serializers.SerializerMethodField()
    tax_providers = serializers.SerializerMethodField()

    def get_tax_providers(
        self, obj
    ) -> serializers.ListField(
        child=serializers.ChoiceField(choices=TAX_PROVIDER.labels), required=True
    ):
        return obj.get_readable_tax_providers()

    def get_stripe_account_id(
        self, obj
    ) -> serializers.CharField(required=True, allow_null=True):
        if obj.stripe_integration:
            return obj.stripe_integration.stripe_account_id
        return None

    def get_braintree_merchant_id(
        self, obj
    ) -> serializers.CharField(required=True, allow_null=True):
        if obj.braintree_integration:
            return obj.braintree_integration.braintree_merchant_id
        return None

    def get_subscription_filter_keys(
        self, obj
    ) -> serializers.ListField(child=serializers.CharField()):
        if not obj.subscription_filters_setting_provisioned:
            return []
        else:
            setting = obj.settings.get(
                setting_name=ORGANIZATION_SETTING_NAMES.SUBSCRIPTION_FILTER_KEYS
            )
            return setting.setting_values

    def get_team_name(self, obj) -> str:
        team = obj.team
        if team is None:
            return obj.organization_name
        return team.name

    def get_address(
        self, obj
    ) -> api_serializers.AddressSerializer(allow_null=True, required=False):
        d = obj.get_address()
        if d is None:
            return None
        else:
            return api_serializers.AddressSerializer(d).data

    def get_current_user(self, obj) -> LightweightUserSerializer():
        user = self.context.get("user")
        return LightweightUserSerializer(user).data

    def get_linked_organizations(
        self, obj
    ) -> LightweightOrganizationSerializer(many=True):
        team = obj.team
        if team is None:
            linked = [obj]
        else:
            linked = team.organizations.all()
        return LightweightOrganizationSerializer(
            linked, many=True, context={"organization": obj}
        ).data

    def get_payment_grace_period(
        self, obj
    ) -> serializers.IntegerField(
        min_value=0, max_value=365, required=False, allow_null=True
    ):
        grace_period_setting = OrganizationSetting.objects.filter(
            organization=obj,
            setting_name=ORGANIZATION_SETTING_NAMES.PAYMENT_GRACE_PERIOD,
            setting_group=ORGANIZATION_SETTING_GROUPS.BILLING,
        ).first()
        if grace_period_setting:
            val = grace_period_setting.setting_values.get("value")
        else:
            val = 0
        return val

    def get_users(self, obj) -> OrganizationUserSerializer(many=True):
        users = User.objects.filter(team=obj.team)
        users_data = OrganizationUserSerializer(users, many=True).data
        now = now_utc()
        invited_users = TeamInviteToken.objects.filter(team=obj.team, expire_at__gt=now)
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

    def get_plan_tags(self, obj) -> TagSerializer(many=True):
        data = TagSerializer(obj.tags.filter(tag_group=TAG_GROUP.PLAN), many=True).data
        return data


class OrganizationCreateSerializer(TimezoneFieldMixin, serializers.ModelSerializer):
    class Meta:
        model = Organization
        fields = ("organization_name", "default_currency_code", "organization_type")

    default_currency_code = SlugRelatedFieldWithOrganization(
        slug_field="code",
        queryset=PricingUnit.objects.all(),
        source="default_currency",
        required=False,
    )
    organization_type = serializers.ChoiceField(
        choices=["development", "production"], default="development", required=False
    )

    def validate(self, data):
        data = super().validate(data)
        existing_org_num = Organization.objects.filter(
            organization_name=data["organization_name"],
        ).count()
        if existing_org_num > 0:
            raise DuplicateOrganization("Organization with company name already exists")
        if data["organization_type"] == "development":
            data["organization_type"] = Organization.OrganizationType.DEVELOPMENT
        elif data["organization_type"] == "production":
            data["organization_type"] = Organization.OrganizationType.PRODUCTION
        else:
            raise ValidationError("Invalid organization type")
        return data

    def create(self, validated_data):
        existing_organization = self.context["organization"]
        team = existing_organization.team
        organization = Organization.objects.create(
            organization_name=validated_data["organization_name"],
            default_currency=validated_data.get("default_currency", None),
            organization_type=validated_data["organization_type"],
            team=team,
        )
        return organization


class APITokenSerializer(TimezoneFieldMixin, serializers.ModelSerializer):
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


class OrganizationUpdateSerializer(TimezoneFieldMixin, serializers.ModelSerializer):
    class Meta:
        model = Organization
        fields = (
            "default_currency_code",
            "address",
            "tax_rate",
            "payment_grace_period",
            "plan_tags",
            "subscription_filter_keys",
            "timezone",
            "payment_provider",
            "payment_provider_id",
            "nango_connected",
            "tax_providers",
        )

    default_currency_code = SlugRelatedFieldWithOrganization(
        slug_field="code", queryset=PricingUnit.objects.all(), source="default_currency"
    )
    address = api_serializers.AddressSerializer(required=False, allow_null=True)
    plan_tags = serializers.ListField(child=TagSerializer(), required=False)
    payment_grace_period = serializers.IntegerField(
        min_value=0, max_value=365, required=False, allow_null=True
    )
    subscription_filter_keys = serializers.ListField(
        child=serializers.CharField(), required=False
    )
    timezone = TimeZoneSerializerField(use_pytz=True)
    payment_provider = serializers.ChoiceField(
        choices=PAYMENT_PROCESSORS.choices,
        required=False,
        help_text="To udpate a payment provider's ID, specify the payment provider you want to update in this field, and the payment_provider_id in the corresponding field.",
    )
    payment_provider_id = serializers.CharField(required=False)
    nango_connected = serializers.BooleanField(required=False)
    tax_providers = serializers.ListField(
        child=serializers.ChoiceField(choices=TAX_PROVIDER.labels),
        required=False,
        allow_empty=True,
        allow_null=True,
    )

    def validate(self, attrs):
        attrs = super().validate(attrs)
        # if payment_provider is specified, payment_provider_id must be specified, and vice versa
        if (
            attrs.get("payment_provider") is not None
            and attrs.get("payment_provider_id") is None
        ) or (
            attrs.get("payment_provider") is None
            and attrs.get("payment_provider_id") is not None
        ):
            raise serializers.ValidationError(
                "If payment_provider is specified, payment_provider_id must be specified."
            )
        tax_providers = attrs.get("tax_providers")
        if tax_providers:
            if len(set(tax_providers)) != len(tax_providers):
                raise serializers.ValidationError("Tax providers must be distinct.")
        return attrs

    def update(self, instance, validated_data):
        from metering_billing.tasks import update_subscription_filter_settings_task

        assert (
            type(validated_data.get("default_currency")) == PricingUnit
            or validated_data.get("default_currency") is None
        )
        instance.default_currency = validated_data.get(
            "default_currency", instance.default_currency
        )
        new_tz = validated_data.get("timezone", instance.timezone)
        if new_tz != instance.timezone:
            cache.delete(f"tz_organization_{instance.id}")
        instance.timezone = new_tz

        address = validated_data.pop("address", None)
        if address:
            new_address, _ = Address.objects.get_or_create(
                **address, organization=instance
            )
            instance.address = new_address
        tax_providers = validated_data.pop("tax_providers", None)
        if tax_providers is not None:
            instance.tax_providers = tax_providers
        plan_tags = validated_data.pop("plan_tags", None)
        if plan_tags is not None:
            plan_tag_names_lower = [x["tag_name"].lower() for x in plan_tags]
            existing_tags = instance.tags.filter(tag_group=TAG_GROUP.PLAN)
            existing_tags_lower = [x.tag_name.lower() for x in existing_tags]
            for tag in existing_tags:
                if tag.tag_name.lower() not in plan_tag_names_lower:
                    tag.delete()
            for plan_tag in plan_tags:
                if plan_tag["tag_name"].lower() not in existing_tags_lower:
                    tag, _ = Tag.objects.get_or_create(
                        organization=instance,
                        tag_name=plan_tag["tag_name"],
                        tag_group=TAG_GROUP.PLAN,
                        tag_hex=plan_tag["tag_hex"],
                        tag_color=plan_tag["tag_color"],
                    )

        instance.tax_rate = validated_data.get("tax_rate", instance.tax_rate)
        payment_grace_period = validated_data.get("payment_grace_period", None)
        if payment_grace_period is not None:
            grace_period_setting = OrganizationSetting.objects.filter(
                organization=instance,
                setting_name=ORGANIZATION_SETTING_NAMES.PAYMENT_GRACE_PERIOD,
                setting_group=ORGANIZATION_SETTING_GROUPS.BILLING,
            ).first()
            if grace_period_setting:
                grace_period_setting.setting_values = {"value": payment_grace_period}
                grace_period_setting.save()
            else:
                OrganizationSetting.objects.create(
                    organization=instance,
                    setting_name=ORGANIZATION_SETTING_NAMES.PAYMENT_GRACE_PERIOD,
                    setting_group=ORGANIZATION_SETTING_GROUPS.BILLING,
                    setting_values={"value": payment_grace_period},
                )
        subscription_filter_keys = validated_data.get("subscription_filter_keys", None)
        if subscription_filter_keys is not None:
            prohibited_keys = [
                "alter",
                "create",
                "drop",
                "delete",
                "insert",
                "replace",
                "truncate",
                "update",
                "union",
            ]
            if any(key.lower() in prohibited_keys for key in subscription_filter_keys):
                raise serializers.ValidationError(
                    "Subscription filter keys cannot contain SQL keywords"
                )
            update_subscription_filter_settings_task.delay(
                instance.pk,
                subscription_filter_keys,
            )
        instance.save()
        return instance


class CustomerUpdateSerializer(TimezoneFieldMixin, serializers.ModelSerializer):
    class Meta:
        model = Customer
        fields = (
            "default_currency_code",
            "billing_address",
            "shipping_address",
            "tax_rate",
            "timezone",
        )

    default_currency_code = SlugRelatedFieldWithOrganization(
        slug_field="code", queryset=PricingUnit.objects.all(), source="default_currency"
    )
    billing_address = api_serializers.AddressSerializer(required=False, allow_null=True)
    shipping_address = api_serializers.AddressSerializer(
        required=False, allow_null=True
    )
    timezone = TimeZoneSerializerField(use_pytz=True)

    def update(self, instance, validated_data):
        assert (
            type(validated_data.get("default_currency")) == PricingUnit
            or validated_data.get("default_currency") is None
        )
        instance.default_currency = validated_data.get(
            "default_currency", instance.default_currency
        )
        instance.tax_rate = validated_data.get("tax_rate", instance.tax_rate)
        tz = validated_data.get("timezone", None)
        if tz != instance.timezone:
            cache.delete(f"tz_customer_{instance.id}")
        if tz:
            instance.timezone = tz
            instance.timezone_set = True
        billing_address = validated_data.pop("billing_address", None)
        if billing_address:
            new_address, _ = Address.objects.get_or_create(
                **billing_address, organization=instance.organization
            )
            instance.billing_address = new_address
        shipping_address = validated_data.pop("shipping_address", None)
        if shipping_address:
            new_address, _ = Address.objects.get_or_create(
                **shipping_address, organization=instance.organization
            )
            instance.shipping_address = new_address

        instance.save()
        return instance


class EventSerializer(api_serializers.EventSerializer):
    class Meta(api_serializers.EventSerializer.Meta):
        fields = api_serializers.EventSerializer.Meta.fields


class WebhookTriggerSerializer(TimezoneFieldMixin, serializers.ModelSerializer):
    class Meta:
        model = WebhookTrigger
        fields = [
            "trigger_name",
        ]


class WebhookEndpointSerializer(TimezoneFieldMixin, serializers.ModelSerializer):
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
    webhook_endpoint_id = WebhookEndpointUUIDField(read_only=True)
    webhook_secret = WebhookSecretUUIDField(read_only=True)

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
class UserSerializer(TimezoneFieldMixin, serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("username", "email", "organization_name", "organization_id")

    organization_id = OrganizationUUIDField(source="organization.organization_id")
    organization_name = serializers.CharField(source="organization.organization_name")


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


class CustomerWithRevenueSerializer(TimezoneFieldMixin, serializers.ModelSerializer):
    class Meta:
        model = Customer
        fields = (
            "customer_id",
            "total_amount_due",
        )

    total_amount_due = serializers.SerializerMethodField()

    def get_total_amount_due(self, obj) -> Decimal:
        try:
            return obj.total_amount_due or 0
        except AttributeError:
            return (
                obj.invoices.filter(payment_status=Invoice.PaymentStatus.UNPAID)
                .aggregate(
                    unpaid_inv_amount=Sum("cost_due", output_field=DecimalField())
                )
                .get("unpaid_inv_amount")
            )


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


class MetricUpdateSerializer(TimezoneFieldMixin, serializers.ModelSerializer):
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


class MetricCreateSerializer(TimezoneFieldMixin, serializers.ModelSerializer):
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
            "categorical_filters",
            "numeric_filters",
        )
        extra_kwargs = {
            "event_name": {"write_only": True, "required": False, "allow_blank": False},
            "property_name": {
                "write_only": True,
                "allow_blank": False,
            },
            "usage_aggregation_type": {"write_only": True, "allow_null": True},
            "billable_aggregation_type": {"write_only": True, "allow_blank": False},
            "granularity": {"write_only": True, "allow_blank": False},
            "event_type": {"write_only": True, "allow_blank": False},
            "metric_type": {"required": True, "write_only": True},
            "metric_name": {"write_only": True},
            "properties": {"write_only": True},
            "is_cost_metric": {"write_only": True, "default": False},
            "custom_sql": {"write_only": True},
            "proration": {
                "write_only": True,
                "required": False,
                "allow_null": True,
                "allow_blank": False,
            },
            "categorical_filters": {"write_only": True, "required": False},
            "numeric_filters": {"write_only": True, "required": False},
        }

    metric_name = serializers.CharField(source="billable_metric_name")
    numeric_filters = NumericFilterSerializer(many=True, required=False)
    categorical_filters = CategoricalFilterSerializer(many=True, required=False)

    def validate(self, data):
        data = super().validate(data)
        metric_type = data["metric_type"]
        data = METRIC_HANDLER_MAP[metric_type].validate_data(data)
        return data

    def create(self, validated_data):
        metric_type = validated_data["metric_type"]
        metric = METRIC_HANDLER_MAP[metric_type].create_metric(validated_data)
        return metric


class ExternalPlanLinkSerializer(TimezoneFieldMixin, serializers.ModelSerializer):
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


class PriceTierCreateSerializer(TimezoneFieldMixin, serializers.ModelSerializer):
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

    type = serializers.ChoiceField(
        choices=PRICE_TIER_TYPE.choices,
        required=True,
    )
    batch_rounding_type = serializers.ChoiceField(
        choices=BATCH_ROUNDING_TYPE.choices,
        default=BATCH_ROUNDING_TYPE.NO_ROUNDING,
        required=False,
        allow_null=True,
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
            data["type"] = PriceTier.PriceTierType.FLAT
        elif data.get("type") == PRICE_TIER_TYPE.FREE:
            data["cost_per_batch"] = None
            data["metric_units_per_batch"] = None
            data["batch_rounding_type"] = None
            data["type"] = PriceTier.PriceTierType.FREE
        elif data.get("type") == PRICE_TIER_TYPE.PER_UNIT:
            assert data.get("metric_units_per_batch")
            assert data.get("cost_per_batch") is not None
            data["batch_rounding_type"] = data.get(
                "batch_rounding_type", PriceTier.BatchRoundingType.NO_ROUNDING
            )
            if data["batch_rounding_type"] == BATCH_ROUNDING_TYPE.NO_ROUNDING:
                data["batch_rounding_type"] = PriceTier.BatchRoundingType.NO_ROUNDING
            elif data["batch_rounding_type"] == BATCH_ROUNDING_TYPE.ROUND_UP:
                data["batch_rounding_type"] = PriceTier.BatchRoundingType.ROUND_UP
            elif data["batch_rounding_type"] == BATCH_ROUNDING_TYPE.ROUND_DOWN:
                data["batch_rounding_type"] = PriceTier.BatchRoundingType.ROUND_DOWN
            elif data["batch_rounding_type"] == BATCH_ROUNDING_TYPE.ROUND_NEAREST:
                data["batch_rounding_type"] = PriceTier.BatchRoundingType.ROUND_NEAREST
            else:
                raise serializers.ValidationError(
                    "Invalid batch rounding type for price tier"
                )
            data["type"] = PriceTier.PriceTierType.PER_UNIT
        else:
            raise serializers.ValidationError("Invalid price tier type")
        return data

    def create(self, validated_data):
        return PriceTier.objects.create(**validated_data)


# PLAN COMPONENT
class PlanComponentCreateSerializer(api_serializers.PlanComponentSerializer):
    class Meta:
        model = PlanComponent
        fields = (
            "metric_id",
            "tiers",
        )
        extra_kwargs = {
            "metric_id": {"required": True, "write_only": True},
            "tiers": {"required": True, "write_only": True},
        }

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
            tier = {**tier, "organization": self.context["organization"]}
            tier = PriceTierCreateSerializer(context=self.context).create(tier)
            assert type(tier) is PriceTier
            tier.plan_component = pc
            tier.save()
        return pc


class ProductSerializer(TimezoneFieldMixin, serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = ("name", "description", "product_id", "status")


class PlanVersionUpdateSerializer(TimezoneFieldMixin, serializers.ModelSerializer):
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
        data.get("transition_to_plan_id")
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


class PriceAdjustmentSerializer(TimezoneFieldMixin, serializers.ModelSerializer):
    class Meta:
        model = PriceAdjustment
        fields = (
            "price_adjustment_name",
            "price_adjustment_description",
            "price_adjustment_type",
            "price_adjustment_amount",
        )

    price_adjustment_name = serializers.CharField(default="")


class FeatureCreateSerializer(TimezoneFieldMixin, serializers.ModelSerializer):
    class Meta:
        model = Feature
        fields = ("feature_name", "feature_description")


class RecurringChargeCreateSerializer(TimezoneFieldMixin, serializers.ModelSerializer):
    class Meta:
        model = RecurringCharge
        fields = (
            "name",
            "charge_timing",
            "charge_behavior",
            "amount",
            "pricing_unit_code",
        )
        extra_kwargs = {
            "name": {"required": True},
            "charge_timing": {"required": True},
            "charge_behavior": {"required": False},
            "amount": {"required": True},
            "pricing_unit_code": {"required": False},
        }

    charge_timing = serializers.ChoiceField(
        choices=RecurringCharge.ChargeTimingType.labels, required=True
    )
    charge_behavior = serializers.ChoiceField(
        choices=RecurringCharge.ChargeBehaviorType.labels,
        default=RecurringCharge.ChargeBehaviorType.PRORATE.label,
    )
    pricing_unit_code = SlugRelatedFieldWithOrganization(
        slug_field="code",
        queryset=PricingUnit.objects.all(),
        required=False,
    )
    name = serializers.CharField(required=True)
    amount = serializers.DecimalField(
        max_digits=20, decimal_places=10, min_value=0, required=True
    )

    def validate(self, attrs):
        if (
            attrs.get("charge_timing")
            == RecurringCharge.ChargeTimingType.IN_ADVANCE.label
        ):
            attrs["charge_timing"] = RecurringCharge.ChargeTimingType.IN_ADVANCE
        elif (
            attrs.get("charge_timing")
            == RecurringCharge.ChargeTimingType.IN_ARREARS.label
        ):
            attrs["charge_timing"] = RecurringCharge.ChargeTimingType.IN_ARREARS
        else:
            raise serializers.ValidationError(
                f"Invalid charge_timing: {attrs.get('charge_timing')}"
            )
        if (
            attrs.get("charge_behavior")
            == RecurringCharge.ChargeBehaviorType.PRORATE.label
        ):
            attrs["charge_behavior"] = RecurringCharge.ChargeBehaviorType.PRORATE
        elif (
            attrs.get("charge_behavior")
            == RecurringCharge.ChargeBehaviorType.CHARGE_FULL.label
        ):
            attrs["charge_behavior"] = RecurringCharge.ChargeBehaviorType.CHARGE_FULL
        else:
            raise serializers.ValidationError(
                f"Invalid charge_behavior: {attrs.get('charge_behavior')}"
            )
        return attrs

    def create(self, validated_data):
        return super().create(validated_data)


class PlanVersionCreateSerializer(TimezoneFieldMixin, serializers.ModelSerializer):
    class Meta:
        model = PlanVersion
        fields = (
            "description",
            "plan_id",
            "recurring_charges",
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
            "recurring_charges": {"write_only": True},
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

    components = PlanComponentCreateSerializer(
        many=True, allow_null=True, required=False, source="plan_components"
    )
    recurring_charges = RecurringChargeCreateSerializer(
        many=True, allow_null=True, required=False
    )
    features = SlugRelatedFieldWithOrganization(
        slug_field="feature_id",
        queryset=Feature.objects.all(),
        many=True,
        allow_null=True,
        required=False,
    )
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
        recurring_charge_data = validated_data.pop("recurring_charges", [])
        features_data = validated_data.pop("features", [])
        price_adjustment_data = validated_data.pop("price_adjustment", None)
        make_active = validated_data.pop("make_active", False)
        make_active_type = validated_data.pop("make_active_type", None)
        replace_immediately_type = validated_data.pop("replace_immediately_type", None)
        transition_to_plan = validated_data.pop("transition_to_plan_id", None)

        validated_data["version"] = validated_data["plan"].versions.all().count() + 1
        if "status" not in validated_data:
            validated_data["status"] = (
                PLAN_VERSION_STATUS.ACTIVE
                if make_active
                else PLAN_VERSION_STATUS.INACTIVE
            )
        billing_plan = PlanVersion.objects.create(
            **validated_data, pricing_unit=pricing_unit
        )
        if transition_to_plan:
            billing_plan.transition_to = transition_to_plan
        org = billing_plan.organization
        if len(components_data) > 0:
            components_data = [
                {
                    **component_data,
                    "pricing_unit": pricing_unit,
                    "organization": org,
                    "plan_version": billing_plan,
                }
                for component_data in components_data
            ]
            components = PlanComponentCreateSerializer(
                many=True, context=self.context
            ).create(components_data)
            assert type(components[0]) is PlanComponent
        if len(recurring_charge_data) > 0:
            charges_data = [
                {
                    **recurring_charge,
                    "pricing_unit": pricing_unit,
                    "organization": org,
                    "plan_version": billing_plan,
                }
                for recurring_charge in recurring_charge_data
            ]
            charges = RecurringChargeCreateSerializer(
                many=True, context=self.context
            ).create(charges_data)
            assert type(charges[0]) is RecurringCharge
        for f in features_data:
            assert type(f) is Feature
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


class LightweightPlanVersionSerializer(
    api_serializers.LightweightPlanVersionSerializer
):
    class Meta(api_serializers.LightweightPlanVersionSerializer.Meta):
        fields = api_serializers.LightweightPlanVersionSerializer.Meta.fields


class UsageAlertSerializer(api_serializers.UsageAlertSerializer):
    class Meta(api_serializers.UsageAlertSerializer.Meta):
        fields = api_serializers.UsageAlertSerializer.Meta.fields


class PlanVersionDetailSerializer(api_serializers.PlanVersionSerializer):
    class Meta(api_serializers.PlanVersionSerializer.Meta):
        fields = api_serializers.PlanVersionSerializer.Meta.fields + (
            "version_id",
            "plan_id",
            "alerts",
            "active_subscriptions",
        )
        extra_kwargs = {**api_serializers.PlanVersionSerializer.Meta.extra_kwargs}

    plan_id = PlanUUIDField(source="plan.plan_id", read_only=True)
    alerts = serializers.SerializerMethodField()
    version_id = PlanVersionUUIDField(read_only=True)
    active_subscriptions = serializers.SerializerMethodField()

    def get_alerts(self, obj) -> UsageAlertSerializer(many=True):
        return UsageAlertSerializer(obj.usage_alerts, many=True).data

    def get_active_subscriptions(self, obj) -> int:
        try:
            return obj.active_subscriptions
        except AttributeError:
            return obj.num_active_subs() or 0


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


class PlanDetailSerializer(api_serializers.PlanSerializer):
    class Meta(api_serializers.PlanSerializer.Meta):
        fields = api_serializers.PlanSerializer.Meta.fields + (
            "versions",
            "taxjar_code",
        )

    display_version = serializers.SerializerMethodField()
    versions = serializers.SerializerMethodField()

    def get_display_version(self, obj) -> PlanVersionDetailSerializer:
        try:
            display = [
                x for x in obj.versions_prefetched if x.pk == obj.display_version_id
            ][0]
            return PlanVersionDetailSerializer(display).data
        except AttributeError as e:
            logger.error(f"AttributeError on plan: {e}")
            return PlanVersionDetailSerializer(obj.display_version).data

    def get_versions(self, obj) -> PlanVersionDetailSerializer(many=True):
        try:
            return PlanVersionDetailSerializer(obj.versions_prefetched, many=True).data
        except AttributeError as e:
            logger.error(f"AttributeError on plan: {e}")
            return PlanVersionDetailSerializer(
                obj.versions.all().order_by("version"), many=True
            ).data


class PlanCreateSerializer(TimezoneFieldMixin, serializers.ModelSerializer):
    class Meta:
        model = Plan
        fields = (
            "plan_name",
            "plan_duration",
            "status",
            "initial_external_links",
            "initial_version",
            "parent_plan_id",
            "target_customer_id",
            "tags",
        )
        extra_kwargs = {
            "plan_name": {"write_only": True},
            "plan_duration": {"write_only": True},
            "status": {"write_only": True},
            "initial_external_links": {"write_only": True},
            "initial_version": {"write_only": True},
            "parent_plan_id": {"write_only": True},
            "target_customer_id": {"write_only": True},
            "tags": {"write_only": True},
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
    tags = serializers.ListField(child=TagSerializer(), required=False)

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
            component.proration_granularity
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
        tags = validated_data.get("tags")
        if initial_external_links:
            validated_data.pop("initial_external_links")
        if transition_to_plan_id:
            display_version_data.pop("transition_to_plan_id")
        if tags:
            validated_data.pop("tags")
        plan = Plan.objects.create(**validated_data)
        try:
            display_version_data["status"] = PLAN_VERSION_STATUS.ACTIVE
            display_version_data["plan"] = plan
            display_version_data["organization"] = validated_data["organization"]
            display_version_data["created_by"] = validated_data["created_by"]
            plan_version = InitialPlanVersionSerializer(context=self.context).create(
                display_version_data
            )
            if initial_external_links:
                for link_data in initial_external_links:
                    link_data["plan"] = plan
                    link_data["organization"] = validated_data["organization"]
                    ExternalPlanLinkSerializer(
                        context={"organization": validated_data["organization"]}
                    ).validate(link_data)
                    ExternalPlanLinkSerializer().create(link_data)
            if tags and len(tags) > 0:
                cond = Q(tag_name__iexact=tags[0]["tag_name"].lower())
                for tag in tags[1:]:
                    cond |= Q(tag_name__iexact=tag["tag_name"].lower())
                existing_tags = Tag.objects.filter(
                    cond,
                    organization=plan.organization,
                    tag_group=TAG_GROUP.PLAN,
                )
                for tag in tags:
                    if not existing_tags.filter(
                        tag_name__iexact=tag["tag_name"].lower()
                    ).exists():
                        tag_obj = Tag.objects.create(
                            organization=plan.organization,
                            tag_name=tag["tag_name"],
                            tag_group=TAG_GROUP.PLAN,
                            tag_color=tag["tag_color"],
                            tag_hex=tag["tag_hex"],
                        )
                    else:
                        tag_obj = existing_tags.get(
                            tag_name__iexact=tag["tag_name"].lower()
                        )
                    plan.tags.add(tag_obj)
            plan.display_version = plan_version
            plan.save()
            return plan
        except Exception as e:
            plan.delete()
            raise ServerError(e)


class PlanUpdateSerializer(TimezoneFieldMixin, serializers.ModelSerializer):
    class Meta:
        model = Plan
        fields = (
            "plan_name",
            "status",
            "tags",
            "taxjar_code",
        )
        extra_kwargs = {
            "plan_name": {"required": False},
            "status": {"required": False},
            "tags": {"required": False},
            "taxjar_code": {"required": False},
        }

    status = serializers.ChoiceField(
        choices=[PLAN_STATUS.ACTIVE, PLAN_STATUS.ARCHIVED], required=False
    )
    tags = serializers.ListField(child=TagSerializer(), required=False, source=None)

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
        instance.taxjar_code = validated_data.get("taxjar_code", instance.taxjar_code)
        tags = validated_data.get("tags")
        if tags is not None:
            tags_lower = [tag["tag_name"].lower() for tag in tags]
            existing_tags = instance.tags.all()
            existing_tag_names = [tag.tag_name.lower() for tag in existing_tags]
            for tag in tags:
                if tag["tag_name"].lower() not in existing_tag_names:
                    try:
                        tag_obj = Tag.objects.get(
                            organization=instance.organization,
                            tag_name__iexact=tag["tag_name"].lower(),
                            tag_group=TAG_GROUP.PLAN,
                        )
                    except Tag.DoesNotExist:
                        tag_obj = Tag.objects.create(
                            organization=instance.organization,
                            tag_name=tag["tag_name"],
                            tag_group=TAG_GROUP.PLAN,
                            tag_hex=tag["tag_hex"],
                            tag_color=tag["tag_color"],
                        )
                    instance.tags.add(tag_obj)
            for existing_tag in existing_tags:
                if existing_tag.tag_name.lower() not in tags_lower:
                    instance.tags.remove(existing_tag)
        instance.save()
        return instance


class SubscriptionRecordSerializer(api_serializers.SubscriptionRecordSerializer):
    class Meta(api_serializers.SubscriptionRecordSerializer.Meta):
        fields = api_serializers.SubscriptionRecordSerializer.Meta.fields


class LightweightSubscriptionRecordSerializer(
    api_serializers.LightweightSubscriptionRecordSerializer
):
    class Meta(api_serializers.LightweightSubscriptionRecordSerializer.Meta):
        fields = api_serializers.LightweightSubscriptionRecordSerializer.Meta.fields


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


class PlanVersionActionSerializer(PlanVersionDetailSerializer):
    class Meta(PlanVersionDetailSerializer.Meta):
        model = PlanVersion
        fields = PlanVersionDetailSerializer.Meta.fields + (
            "string_repr",
            "object_type",
        )

    string_repr = serializers.SerializerMethodField()
    object_type = serializers.SerializerMethodField()

    def get_string_repr(self, obj):
        return obj.plan.plan_name + " v" + str(obj.version)

    def get_object_type(self, obj):
        return "Plan Version"


class PlanActionSerializer(PlanDetailSerializer):
    class Meta(PlanDetailSerializer.Meta):
        model = Plan
        fields = PlanDetailSerializer.Meta.fields + ("string_repr", "object_type")

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


class CustomerSummarySerializer(TimezoneFieldMixin, serializers.ModelSerializer):
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


class ActionSerializer(TimezoneFieldMixin, serializers.ModelSerializer):
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


class OrganizationSettingUpdateSerializer(
    TimezoneFieldMixin, serializers.ModelSerializer
):
    class Meta:
        model = OrganizationSetting
        fields = ("setting_values",)

    def update(self, instance, validated_data):
        setting_values = validated_data.get("setting_values")
        if instance.setting_name == ORGANIZATION_SETTING_NAMES.SUBSCRIPTION_FILTER_KEYS:
            if not isinstance(setting_values, list):
                raise serializers.ValidationError(
                    "Setting values must be a list of strings"
                )
            if not all(isinstance(item, str) for item in setting_values):
                raise serializers.ValidationError(
                    "Setting values must be a list of strings"
                )
            current_setting_values = set(instance.setting_values)
            new_setting_values = set(setting_values)
            validated_data["setting_values"] = list(
                current_setting_values.union(new_setting_values)
            )
        elif instance.setting_name in [
            ORGANIZATION_SETTING_NAMES.GENERATE_CUSTOMER_IN_STRIPE_AFTER_LOTUS,
            ORGANIZATION_SETTING_NAMES.GENERATE_CUSTOMER_IN_BRAINTREE_AFTER_LOTUS,
        ]:
            if not isinstance(setting_values, bool):
                raise serializers.ValidationError("Setting values must be a boolean")
            setting_values = {"value": setting_values}
        instance.setting_values = setting_values
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
                    "invoice_pdf",
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


class AddOnSerializer(api_serializers.AddOnSerializer):
    pass


class AddOnCreateSerializer(TimezoneFieldMixin, serializers.ModelSerializer):
    class Meta:
        model = Plan
        fields = (
            "addon_name",
            "description",
            "recurring_charges",
            "components",
            "features",
            "currency_code",
            "invoice_when",
            "billing_frequency",
        )
        extra_kwargs = {
            "addon_name": {"write_only": True, "required": True},
            "description": {"write_only": True, "required": True, "allow_null": True},
            "recurring_charges": {"write_only": True, "required": True},
            "components": {"write_only": True, "required": True},
            "features": {"write_only": True, "required": True},
            "currency_code": {"write_only": True, "allow_null": True},
            "invoice_when": {"write_only": True, "required": True},
            "billing_frequency": {"write_only": True, "required": True},
        }

    addon_name = serializers.CharField(
        help_text="The name of the add-on plan.",
    )
    description = serializers.CharField(
        help_text="The description of the add-on plan.",
        allow_null=True,
    )
    components = PlanComponentCreateSerializer(
        many=True, allow_null=True, required=False
    )
    recurring_charges = RecurringChargeCreateSerializer(
        many=True, allow_null=True, required=False
    )
    features = SlugRelatedFieldWithOrganization(
        slug_field="feature_id",
        queryset=Feature.objects.all(),
        many=True,
        required=False,
    )
    currency_code = SlugRelatedFieldWithOrganization(
        slug_field="code",
        queryset=PricingUnit.objects.all(),
        required=False,
        allow_null=True,
    )
    invoice_when = serializers.ChoiceField(
        choices=AddOnSpecification.FlatFeeInvoicingBehaviorOnAttach.labels
    )
    billing_frequency = serializers.ChoiceField(
        choices=AddOnSpecification.BillingFrequency.labels
    )

    def validate(self, data):
        data = super().validate(data)
        # make sure every plan component has a unique metric
        if data.get("components"):
            component_metrics = []
            for component in data.get("components"):
                if component.get("billable_metric") in component_metrics:
                    raise serializers.ValidationError(
                        "Plan components must have unique metrics."
                    )
                else:
                    component_metrics.append(component.get("metric"))
        # if tehres any paid components add on must have a currency code
        pricing_unit = data.pop("currency_code", None)
        if pricing_unit is None:
            no_flat_rate = data.get("flat_rate") == Decimal(0)
            no_paid_components = True
            for component in data.get("plan_components", []):
                for tier in component["tiers"]:
                    if tier["type"] != PRICE_TIER_TYPE.FREE:
                        no_paid_components = False
                        break
                if not no_paid_components:
                    break
            if not (no_flat_rate and no_paid_components):
                raise serializers.ValidationError(
                    "A currency code is required for paid add-ons."
                )
        # convert string fields to int fields
        if (
            data.get("billing_frequency")
            == AddOnSpecification.BillingFrequency.ONE_TIME.label
        ):
            data["billing_frequency"] = AddOnSpecification.BillingFrequency.ONE_TIME
        elif (
            data.get("billing_frequency")
            == AddOnSpecification.BillingFrequency.RECURRING.label
        ):
            data["billing_frequency"] = AddOnSpecification.BillingFrequency.RECURRING

        if (
            data.get("invoice_when")
            == AddOnSpecification.FlatFeeInvoicingBehaviorOnAttach.INVOICE_ON_ATTACH.label
        ):
            data[
                "invoice_when"
            ] = AddOnSpecification.FlatFeeInvoicingBehaviorOnAttach.INVOICE_ON_ATTACH
        elif (
            data.get("invoice_when")
            == AddOnSpecification.FlatFeeInvoicingBehaviorOnAttach.INVOICE_ON_SUBSCRIPTION_END.label
        ):
            data[
                "invoice_when"
            ] = (
                AddOnSpecification.FlatFeeInvoicingBehaviorOnAttach.INVOICE_ON_SUBSCRIPTION_END
            )

        return data

    def create(self, validated_data):
        now = now_utc()
        org = validated_data["organization"]
        # invoice_when, billing_frequency
        addon_spec_data = {
            "organization": org,
            "billing_frequency": validated_data["billing_frequency"],
            "flat_fee_invoicing_behavior_on_attach": validated_data["invoice_when"],
        }
        addon_spec = AddOnSpecification.objects.create(**addon_spec_data)
        # start off by cretaing the plan
        plan_create_data = {
            "organization": org,
            "plan_name": validated_data["addon_name"],
            "status": PLAN_STATUS.ACTIVE,
            "created_by": validated_data["created_by"],
            "created_on": now,
            "addon_spec": addon_spec,
        }
        plan = Plan.addons.create(**plan_create_data)

        # create the plan version
        plan_version_data = {
            "organization": org,
            "plan": plan,
            "description": validated_data["description"],
            "status": PLAN_VERSION_STATUS.ACTIVE,
            "created_by": validated_data["created_by"],
            "created_on": now,
            "version": 1,
        }
        pricing_unit = validated_data.pop("currency_code", None)
        billing_plan = PlanVersion.objects.create(
            **plan_version_data, pricing_unit=pricing_unit
        )
        # create components
        components_data = validated_data.pop("components", [])
        if len(components_data) > 0:
            if pricing_unit is not None:
                data = [
                    {
                        **component_data,
                        "pricing_unit": pricing_unit,
                        "plan_version": billing_plan,
                        "organization": org,
                    }
                    for component_data in components_data
                ]
            else:
                data = components_data
            PlanComponentCreateSerializer(
                many=True, context={**self.context, "organization": org}
            ).create(data)
        else:
            pass
        # create features
        features_data = validated_data.pop("features", [])
        for f in features_data:
            billing_plan.features.add(f)
        # create the flat rates
        recurring_charges = validated_data.pop("recurring_charges", [])
        if len(recurring_charges) > 0:
            charges_data = [
                {
                    **recurring_charge,
                    "pricing_unit": pricing_unit,
                    "organization": org,
                    "plan_version": billing_plan,
                }
                for recurring_charge in recurring_charges
            ]
            charges = RecurringChargeCreateSerializer(
                many=True, context=self.context
            ).create(charges_data)
            assert type(charges[0]) is RecurringCharge
        plan.display_version = billing_plan
        plan.save()
        return plan


class UsageAlertCreateSerializer(TimezoneFieldMixin, serializers.ModelSerializer):
    class Meta:
        model = UsageAlert
        fields = (
            "metric_id",
            "plan_version_id",
            "threshold",
        )

    metric_id = SlugRelatedFieldWithOrganization(
        slug_field="metric_id", queryset=Metric.objects.all(), source="metric"
    )
    plan_version_id = SlugRelatedFieldWithOrganization(
        slug_field="version_id",
        queryset=PlanVersion.objects.all(),
        source="plan_version",
    )

    def create(self, validated_data):
        metric = validated_data.pop("metric")
        plan_version = validated_data.pop("plan_version")
        usage_alert = UsageAlert.objects.create(
            metric=metric,
            plan_version=plan_version,
            **validated_data,
        )
        return usage_alert
        return usage_alert
        return usage_alert
        return usage_alert
        return usage_alert
