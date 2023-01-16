import uuid

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers
from rest_framework.exceptions import ValidationError


class SlugRelatedFieldWithOrganization(serializers.SlugRelatedField):
    def get_queryset(self):
        queryset = self.queryset
        org = self.context.get("organization", None)
        queryset = queryset.filter(organization=org)
        return queryset

    def to_internal_value(self, data):
        from metering_billing.models import (
            CustomerBalanceAdjustment,
            Metric,
            Plan,
            PlanVersion,
        )

        if self.queryset.model is CustomerBalanceAdjustment:
            data = BalanceAdjustmentUUIDField().to_internal_value(data)
        elif self.queryset.model is Metric:
            data = MetricUUIDField().to_internal_value(data)
        elif self.queryset.model is Plan:
            data = PlanUUIDField().to_internal_value(data)
        elif self.queryset.model is PlanVersion:
            data = PlanVersionUUIDField().to_internal_value(data)
        return super().to_internal_value(data)

    def to_representation(self, obj):
        from metering_billing.models import (
            CustomerBalanceAdjustment,
            Metric,
            Plan,
            PlanVersion,
        )

        repr = super().to_representation(obj)
        if isinstance(obj, CustomerBalanceAdjustment):
            return BalanceAdjustmentUUIDField().to_representation(obj.adjustment_id)
        elif isinstance(obj, Metric):
            return MetricUUIDField().to_representation(obj.metric_id)
        elif isinstance(obj, Plan):
            return PlanUUIDField().to_representation(obj.plan_id)
        elif isinstance(obj, PlanVersion):
            return PlanVersionUUIDField().to_representation(obj.version_id)
        return repr


class SlugRelatedFieldWithOrganizationPK(SlugRelatedFieldWithOrganization):
    def get_queryset(self):
        queryset = self.queryset
        org = self.context.get("organization_pk", None)
        queryset = queryset.filter(organization_id=org)
        return queryset


class EmailSerializer(serializers.Serializer):
    email = serializers.EmailField()

    class Meta:
        fields = ("email",)


class UUIDPrefixField(serializers.UUIDField):
    def __init__(self, prefix: str, *args, **kwargs):
        self.prefix = prefix
        super().__init__(*args, **kwargs)
        self.uuid_format = "hex"

    def to_internal_value(self, data) -> uuid.UUID:
        if not isinstance(data, (str, uuid.UUID)):
            raise ValidationError(
                "Input must be a string beginning with the prefix {} and followed by the compact hex representation of the UUID, not including hyphens.".format(
                    self.prefix
                )
            )
        if isinstance(data, str):
            data = data.replace("-", "")
            data = data.replace(f"{self.prefix}", "")
            try:
                data = uuid.UUID(data)
            except ValueError:
                raise ValidationError(
                    "Input must be a string beginning with the prefix {} and followed by the compact hex representation of the UUID, not including hyphens.".format(
                        self.prefix
                    )
                )
        data = super().to_internal_value(data)
        return data

    def to_representation(self, value) -> str:
        return self.prefix + value.hex


@extend_schema_field(serializers.RegexField(regex=r"org_[0-9a-f]{32}"))
class OrganizationUUIDField(UUIDPrefixField):
    def __init__(self, *args, **kwargs):
        super().__init__("org_", *args, **kwargs)


@extend_schema_field(serializers.RegexField(regex=r"btest_[0-9a-f]{32}"))
class BacktestUUIDField(UUIDPrefixField):
    def __init__(self, *args, **kwargs):
        super().__init__("btest_", *args, **kwargs)


@extend_schema_field(serializers.RegexField(regex=r"baladj_[0-9a-f]{32}"))
class BalanceAdjustmentUUIDField(UUIDPrefixField):
    def __init__(self, *args, **kwargs):
        super().__init__("baladj_", *args, **kwargs)


@extend_schema_field(serializers.RegexField(regex=r"metric_[0-9a-f]{32}"))
class MetricUUIDField(UUIDPrefixField):
    def __init__(self, *args, **kwargs):
        super().__init__("metric_", *args, **kwargs)


@extend_schema_field(serializers.RegexField(regex=r"orgset_[0-9a-f]{32}"))
class OrganizationSettingUUIDField(UUIDPrefixField):
    def __init__(self, *args, **kwargs):
        super().__init__("orgset_", *args, **kwargs)


@extend_schema_field(serializers.RegexField(regex=r"plan_[0-9a-f]{32}"))
class PlanUUIDField(UUIDPrefixField):
    def __init__(self, *args, **kwargs):
        super().__init__("plan_", *args, **kwargs)


@extend_schema_field(serializers.RegexField(regex=r"plan_version_[0-9a-f]{32}"))
class PlanVersionUUIDField(UUIDPrefixField):
    def __init__(self, *args, **kwargs):
        super().__init__("plan_version_", *args, **kwargs)


@extend_schema_field(serializers.RegexField(regex=r"sub_[0-9a-f]{32}"))
class SubscriptionUUIDField(UUIDPrefixField):
    def __init__(self, *args, **kwargs):
        super().__init__("sub_", *args, **kwargs)


@extend_schema_field(serializers.RegexField(regex=r"sr_[0-9a-f]{32}"))
class SubscriptionRecordUUIDField(UUIDPrefixField):
    def __init__(self, *args, **kwargs):
        super().__init__("sr_", *args, **kwargs)


@extend_schema_field(serializers.RegexField(regex=r"usg_alert_[0-9a-f]{32}"))
class UsageAlertUUIDField(UUIDPrefixField):
    def __init__(self, *args, **kwargs):
        super().__init__("usg_alert_", *args, **kwargs)


@extend_schema_field(serializers.RegexField(regex=r"whend_[0-9a-f]{32}"))
class WebhookEndpointUUIDField(UUIDPrefixField):
    def __init__(self, *args, **kwargs):
        super().__init__("whend_", *args, **kwargs)


@extend_schema_field(serializers.RegexField(regex=r"whsec_[0-9a-f]{32}"))
class WebhookSecretUUIDField(UUIDPrefixField):
    def __init__(self, *args, **kwargs):
        super().__init__("whsec_", *args, **kwargs)
