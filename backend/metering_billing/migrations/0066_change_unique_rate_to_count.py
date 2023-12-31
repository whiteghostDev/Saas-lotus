# Generated by Django 4.0.5 on 2022-11-10 20:41

from django.db import migrations


def migrate_stateful_other_to_max(apps, schema_editor):
    BillableMetric = apps.get_model("metering_billing", "BillableMetric")
    BillableMetric.objects.filter(
        metric_type="rate",
        usage_aggregation_type="unique",
    ).update(usage_aggregation_type="count", property_name=None)


class Migration(migrations.Migration):
    dependencies = [
        (
            "metering_billing",
            "0065_remove_billablemetric_unique_with_property_name_and_more",
        ),
    ]

    operations = [
        migrations.RunPython(migrate_stateful_other_to_max),
    ]
