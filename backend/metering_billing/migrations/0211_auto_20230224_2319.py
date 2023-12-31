# Generated by Django 4.0.5 on 2023-02-24 23:19

from django.db import migrations


def set_not_before(apps, schema_editor):
    PlanVersion = apps.get_model("metering_billing", "PlanVersion")
    for version in PlanVersion.objects.all():
        if version.created_on:
            version.active_from = version.created_on
            version.save()

    Plan = apps.get_model("metering_billing", "Plan")
    for version in Plan.objects.all():
        if version.created_on:
            version.active_from = version.created_on
            version.save()


def set_not_after(apps, schema_editor):
    from metering_billing.utils import now_utc

    PlanVersion = apps.get_model("metering_billing", "PlanVersion")
    for version in PlanVersion.objects.all():
        if version.status == "active":
            version.active_to = None
        else:
            if version.status == "archived":
                version.deleted = now_utc()
            version.active_to = now_utc()
        version.save()

    Plan = apps.get_model("metering_billing", "Plan")
    for plan in Plan.objects.all():
        if plan.status == "active":
            plan.active_to = None
        else:
            if plan.status == "archived":
                plan.deleted = now_utc()
            plan.active_to = now_utc()
        plan.save()


class Migration(migrations.Migration):
    dependencies = [
        ("metering_billing", "0210_remove_historicalplan_display_version_and_more"),
    ]

    operations = [
        migrations.RunPython(set_not_before),
        migrations.RunPython(set_not_after),
    ]
