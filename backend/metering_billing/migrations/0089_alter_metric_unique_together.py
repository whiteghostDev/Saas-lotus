# Generated by Django 4.0.5 on 2022-11-28 21:04

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("metering_billing", "0088_auto_20221128_2100"),
    ]

    operations = [
        migrations.AlterUniqueTogether(
            name="metric",
            unique_together={("organization", "metric_id")},
        ),
    ]
