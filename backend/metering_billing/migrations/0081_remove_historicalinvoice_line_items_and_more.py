# Generated by Django 4.0.5 on 2022-11-24 04:55

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("metering_billing", "0080_historicalmetric_is_cost_metric_and_more"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="historicalinvoice",
            name="line_items",
        ),
        migrations.RemoveField(
            model_name="invoice",
            name="line_items",
        ),
    ]
