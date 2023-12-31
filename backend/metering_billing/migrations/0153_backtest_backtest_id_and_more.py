# Generated by Django 4.0.5 on 2023-01-14 20:36

import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        (
            "metering_billing",
            "0152_rename_backtest_id_backtest_backtest_id_old_and_more",
        ),
    ]

    operations = [
        migrations.AddField(
            model_name="backtest",
            name="backtest_id",
            field=models.UUIDField(default=uuid.uuid4, editable=False),
        ),
        migrations.AddField(
            model_name="customerbalanceadjustment",
            name="adjustment_id",
            field=models.UUIDField(default=uuid.uuid4, editable=False),
        ),
        migrations.AddField(
            model_name="feature",
            name="feature_id",
            field=models.UUIDField(default=uuid.uuid4, editable=False),
        ),
        migrations.AddField(
            model_name="historicalbacktest",
            name="backtest_id",
            field=models.UUIDField(default=uuid.uuid4, editable=False),
        ),
        migrations.AddField(
            model_name="historicalinvoice",
            name="invoice_id",
            field=models.UUIDField(default=uuid.uuid4, editable=False),
        ),
        migrations.AddField(
            model_name="historicalmetric",
            name="metric_id",
            field=models.UUIDField(default=uuid.uuid4, editable=False),
        ),
        migrations.AddField(
            model_name="historicalorganization",
            name="organization_id",
            field=models.UUIDField(default=uuid.uuid4, editable=False),
        ),
        migrations.AddField(
            model_name="historicalorganizationsetting",
            name="setting_id",
            field=models.UUIDField(default=uuid.uuid4, editable=False),
        ),
        migrations.AddField(
            model_name="historicalplan",
            name="plan_id",
            field=models.UUIDField(default=uuid.uuid4, editable=False),
        ),
        migrations.AddField(
            model_name="historicalplanversion",
            name="version_id",
            field=models.UUIDField(default=uuid.uuid4, editable=False),
        ),
        migrations.AddField(
            model_name="historicalsubscriptionrecord",
            name="subscription_record_id",
            field=models.UUIDField(default=uuid.uuid4, editable=False),
        ),
        migrations.AddField(
            model_name="invoice",
            name="invoice_id",
            field=models.UUIDField(default=uuid.uuid4, editable=False),
        ),
        migrations.AddField(
            model_name="invoicelineitem",
            name="invoice_line_item_id",
            field=models.UUIDField(default=uuid.uuid4, editable=False),
        ),
        migrations.AddField(
            model_name="metric",
            name="metric_id",
            field=models.UUIDField(default=uuid.uuid4, editable=False),
        ),
        migrations.AddField(
            model_name="organization",
            name="organization_id",
            field=models.UUIDField(default=uuid.uuid4, editable=False),
        ),
        migrations.AddField(
            model_name="organizationsetting",
            name="setting_id",
            field=models.UUIDField(default=uuid.uuid4, editable=False),
        ),
        migrations.AddField(
            model_name="plan",
            name="plan_id",
            field=models.UUIDField(default=uuid.uuid4, editable=False),
        ),
        migrations.AddField(
            model_name="planversion",
            name="version_id",
            field=models.UUIDField(default=uuid.uuid4, editable=False),
        ),
        migrations.AddField(
            model_name="subscription",
            name="subscription_id",
            field=models.UUIDField(default=uuid.uuid4, editable=False),
        ),
        migrations.AddField(
            model_name="subscriptionrecord",
            name="subscription_record_id",
            field=models.UUIDField(default=uuid.uuid4, editable=False),
        ),
        migrations.AddField(
            model_name="tag",
            name="tag_id",
            field=models.UUIDField(default=uuid.uuid4, editable=False),
        ),
        migrations.AddField(
            model_name="usagealert",
            name="usage_alert_id",
            field=models.UUIDField(default=uuid.uuid4, editable=False),
        ),
        migrations.AddField(
            model_name="webhookendpoint",
            name="webhook_endpoint_id",
            field=models.UUIDField(default=uuid.uuid4, editable=False),
        ),
        migrations.AddField(
            model_name="webhookendpoint",
            name="webhook_secret",
            field=models.UUIDField(default=uuid.uuid4, editable=False),
        ),
    ]
