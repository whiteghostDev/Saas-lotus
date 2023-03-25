from api.serializers.model_serializers import (
    FeatureSerializer,
    LightweightCustomerSerializer,
    LightweightMetricSerializer,
    LightweightPlanVersionSerializer,
    SubscriptionFilterSerializer,
)
from metering_billing.models import (
    Customer,
    Feature,
    Metric,
    PlanVersion,
    SubscriptionRecord,
)
from metering_billing.serializers.serializer_utils import (
    SlugRelatedFieldWithOrganization,
    SlugRelatedFieldWithOrganizationPK,
    TimezoneFieldMixin,
)
from rest_framework import serializers


class AccessMethodsSubscriptionRecordSerializer(
    TimezoneFieldMixin, serializers.ModelSerializer
):
    class Meta:
        model = SubscriptionRecord
        fields = (
            "start_date",
            "end_date",
            "subscription_filters",
            "plan",
        )
        extra_kwargs = {
            "start_date": {"required": True, "read_only": True},
            "end_date": {"required": True, "read_only": True},
            "subscription_filters": {"required": True, "read_only": True},
            "plan": {"required": True, "read_only": True},
        }

    subscription_filters = SubscriptionFilterSerializer(many=True)
    plan = LightweightPlanVersionSerializer(source="billing_plan")


class MetricAccessPerSubscriptionSerializer(serializers.Serializer):
    subscription = AccessMethodsSubscriptionRecordSerializer()
    metric_usage = serializers.DecimalField(
        help_text="The current usage of the metric. Keep in mind the current usage of the metric can be different from the billable usage of the metric. For examnple, for a gauge metric, the `metric_usage` is the current value of the gauge, while the billable usage is the accumulated tiem at each gauge level at the end of the subscription.",
        max_digits=20,
        decimal_places=10,
        min_value=0,
    )
    metric_free_limit = serializers.DecimalField(
        allow_null=True,
        help_text="If you specified a free tier of usage for this metric, this is the amount of usage that is free. Will be 0 if you didn't specify a free limit for this metric or this subscription doesn't have access to this metric, and null if the free tier is unlimited.",
        max_digits=20,
        decimal_places=10,
        min_value=0,
    )
    metric_total_limit = serializers.DecimalField(
        allow_null=True,
        help_text="The total limit of the metric. Will be 0 if this subscription doesn't have access to this metric, and null if there is no limit to this metric.",
        max_digits=20,
        decimal_places=10,
        min_value=0,
    )


class MetricAccessResponseSerializer(serializers.Serializer):
    customer = LightweightCustomerSerializer()
    access = serializers.BooleanField(
        help_text="Whether or not the customer has access to this metric. The default behavior for this is whether all of the customer's plans (that have access to the metric) are below the total limit of the metric. If you have specified subscription filters, then this will be whether all of the customer's plans that match the subscription filters are below the total limit of the metric. You can customize the behavior of this flag by setting a policy in your Organization settings in the frontend."
    )
    metric = LightweightMetricSerializer()
    access_per_subscription = MetricAccessPerSubscriptionSerializer(many=True)


class MetricAccessRequestSerializer(serializers.Serializer):
    customer_id = SlugRelatedFieldWithOrganizationPK(
        slug_field="customer_id",
        queryset=Customer.objects.all(),
        help_text="The customer_id of the customer you want to check access.",
    )
    metric_id = SlugRelatedFieldWithOrganizationPK(
        slug_field="metric_id",
        queryset=Metric.objects.all(),
        help_text="The metric_id of the metric you want to check access for.",
    )
    subscription_filters = SubscriptionFilterSerializer(
        many=True,
        required=False,
        help_text="Used if you want to restrict the access check to only plans that fulfill certain subscription filter criteria. If your billing model does not have the ability multiple plans or subscriptions per customer, this is likely not relevant for you. ",
    )

    def validate(self, data):
        data = super().validate(data)
        data["metric"] = data.pop("metric_id", None)
        data["customer"] = data.pop("customer_id", None)
        return data


class FeatureAccessPerSubscriptionSerializer(serializers.Serializer):
    subscription = AccessMethodsSubscriptionRecordSerializer()
    access = serializers.BooleanField()


class FeatureAccessResponseSerializer(serializers.Serializer):
    customer = LightweightCustomerSerializer()
    access = serializers.BooleanField(
        help_text="Whether or not the customer has access to this feature. The default behavior for this is whether any of the customer's plans have access to this feature. If you have specified subscription filters, then this will be whether any of the customer's plans that match the subscription filters have access to this feature. You can customize the behavior of this flag by setting a policy in your Organization settings in the frontend."
    )
    feature = FeatureSerializer()
    access_per_subscription = FeatureAccessPerSubscriptionSerializer(many=True)


class FeatureAccessRequestSerializer(serializers.Serializer):
    customer_id = SlugRelatedFieldWithOrganizationPK(
        slug_field="customer_id",
        queryset=Customer.objects.all(),
        help_text="The customer_id of the customer you want to check access.",
    )
    feature_id = SlugRelatedFieldWithOrganizationPK(
        slug_field="feature_id",
        queryset=Feature.objects.all(),
        help_text="The feature_id of the feature you want to check access for.",
    )
    subscription_filters = SubscriptionFilterSerializer(
        many=True,
        required=False,
        help_text="The subscription filters that are applied to this plan's relationship with the customer. If your billing model does not have the ability multiple plans or subscriptions per customer, this is likely not relevant for you. ",
    )

    def validate(self, data):
        data = super().validate(data)
        data["feature"] = data.pop("feature_id", None)
        data["customer"] = data.pop("customer_id", None)
        return data


class CustomerDeleteResponseSerializer(serializers.Serializer):
    customer_id = serializers.CharField()
    deleted = serializers.DateTimeField()
    email = serializers.EmailField(allow_blank=True, allow_null=True)
    num_subscriptions_deleted = serializers.IntegerField()
    num_addons_deleted = serializers.IntegerField()


class VersionSelectorSerializer(serializers.Serializer):
    version_ids = SlugRelatedFieldWithOrganization(
        slug_field="version_id",
        queryset=PlanVersion.plan_versions.all(),
        required=False,
        many=True,
        help_text="The version_ids of the plan versions you want to add the feature to. If you want to apply to all versions, use the all_versions parameter.",
        source="plan_versions",
    )
    all_versions = serializers.BooleanField(
        help_text="Whether or not to apply this feature to all versions of the feature. If you want to apply to specific versions, use the version_ids parameter.",
        required=False,
        default=False,
    )

    def validate(self, data):
        # make sure they don't use both version_ids and all_versions
        if len(data.get("version_ids", [])) > 0 and data.get("all_versions") is True:
            raise serializers.ValidationError(
                "You cannot use both version_ids and all_versions."
            )
        data = super().validate(data)
        data["plan_versions"] = PlanVersion.objects.filter(
            id__in=[x.id for x in data.get("plan_versions", [])]
        )
        return data


class AddFeatureToPlanSerializer(VersionSelectorSerializer):
    feature_id = SlugRelatedFieldWithOrganization(
        slug_field="feature_id",
        queryset=Feature.objects.all(),
        help_text="The feature_id of the feature you want to add to the plan.",
        source="feature",
        required=True,
    )


class AddFeatureSerializer(serializers.Serializer):
    feature_id = SlugRelatedFieldWithOrganization(
        slug_field="feature_id",
        queryset=Feature.objects.all(),
        help_text="The feature_id of the feature you want to add to the plan.",
        source="feature",
        required=True,
    )


class AddFeatureToAddOnSerializer(AddFeatureToPlanSerializer):
    version_ids = SlugRelatedFieldWithOrganization(
        slug_field="version_id",
        queryset=PlanVersion.addon_versions.all(),
        required=False,
        many=True,
        help_text="The version_ids of the AddOn versions you want to add the feature to. If you want to apply to all versions, use the all_versions parameter.",
    )
    all_versions = None


class ChangeActiveDatesSerializer(VersionSelectorSerializer):
    active_from = serializers.DateTimeField(
        help_text="The date and time that the feature should be active from. If you want to make this inactive, you can pass null here.",
        required=False,
        allow_null=True,
    )
    active_to = serializers.DateTimeField(
        help_text="The date and time that the feature should be active until. If you want to make this active indefinitely, you can pass null here.",
        required=False,
        allow_null=True,
    )


class ChangePrepaidUnitsSerializer(serializers.Serializer):
    units = serializers.DecimalField(
        required=True,
        help_text="The new prepaid units for the customer.",
        max_digits=20,
        decimal_places=10,
    )
    invoice_now = serializers.BooleanField(
        required=False,
        help_text="Whether or not to immediately invoice the customer for the change in prepaid units.",
        default=True,
    )
