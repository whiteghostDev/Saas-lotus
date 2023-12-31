# Generated by Django 4.0.5 on 2022-12-10 04:11

from django.db import migrations, models

import metering_billing.utils.utils


class Migration(migrations.Migration):
    dependencies = [
        ("metering_billing", "0108_auto_20221210_0410"),
    ]

    operations = [
        migrations.AlterField(
            model_name="event",
            name="idempotency_id",
            field=models.CharField(
                default=metering_billing.utils.utils.event_uuid, max_length=255
            ),
        ),
        migrations.AlterUniqueTogether(
            name="customer",
            unique_together={
                ("organization", "customer_id"),
                ("organization", "email"),
            },
        ),
    ]
