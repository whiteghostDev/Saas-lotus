# Generated by Django 4.0.5 on 2022-11-22 02:04

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        (
            "metering_billing",
            "0079_rename_historicalbillablemetric_historicalmetric_and_more",
        ),
    ]

    operations = [
        migrations.AddField(
            model_name="historicalmetric",
            name="is_cost_metric",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="metric",
            name="is_cost_metric",
            field=models.BooleanField(default=False),
        ),
    ]
