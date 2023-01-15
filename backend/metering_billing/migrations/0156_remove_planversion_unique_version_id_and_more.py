# Generated by Django 4.0.5 on 2023-01-15 01:07

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("metering_billing", "0155_remove_metric_unique_org_metric_id_and_more"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="customerbalanceadjustment",
            index=models.Index(
                fields=["organization", "adjustment_id"],
                name="metering_bi_organiz_9f8c02_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="customerbalanceadjustment",
            index=models.Index(
                fields=["organization", "customer", "pricing_unit", "-expires_at"],
                name="metering_bi_organiz_f37320_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="customerbalanceadjustment",
            index=models.Index(
                fields=["status", "expires_at"], name="metering_bi_status_9da89e_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="invoice",
            index=models.Index(
                fields=["organization", "payment_status"],
                name="metering_bi_organiz_526b67_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="invoice",
            index=models.Index(
                fields=["organization", "customer"],
                name="metering_bi_organiz_c3288b_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="invoice",
            index=models.Index(
                fields=["organization", "invoice_number"],
                name="metering_bi_organiz_ac23d0_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="invoice",
            index=models.Index(
                fields=["organization", "invoice_id"],
                name="metering_bi_organiz_c74b11_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="invoice",
            index=models.Index(
                fields=["organization", "external_payment_obj_id"],
                name="metering_bi_organiz_696910_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="invoice",
            index=models.Index(
                fields=["organization", "subscription", "-issue_date"],
                name="metering_bi_organiz_af373b_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="metric",
            index=models.Index(
                fields=["organization", "status"], name="metering_bi_organiz_1afd87_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="metric",
            index=models.Index(
                fields=["organization", "is_cost_metric"],
                name="metering_bi_organiz_cf4e53_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="metric",
            index=models.Index(
                fields=["organization", "metric_id"],
                name="metering_bi_organiz_abe2df_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="organization",
            index=models.Index(
                fields=["organization_name"], name="metering_bi_organiz_c79d3f_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="organization",
            index=models.Index(
                fields=["organization_type"], name="metering_bi_organiz_fa1601_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="organization",
            index=models.Index(
                fields=["organization_id"], name="metering_bi_organiz_f1b906_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="organization",
            index=models.Index(fields=["team"], name="metering_bi_team_id_64b8cc_idx"),
        ),
        migrations.AddIndex(
            model_name="plan",
            index=models.Index(
                fields=["organization", "status"], name="metering_bi_organiz_b5d6d8_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="plan",
            index=models.Index(
                fields=["organization", "plan_id"],
                name="metering_bi_organiz_5f4b15_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="planversion",
            index=models.Index(
                fields=["organization", "status", "plan"],
                name="metering_bi_organiz_847d79_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="planversion",
            index=models.Index(
                fields=["organization", "version_id"],
                name="metering_bi_organiz_911922_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="subscription",
            index=models.Index(
                fields=["-end_date"], name="metering_bi_end_dat_6b686d_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="subscription",
            index=models.Index(
                fields=["organization", "customer", "start_date", "end_date"],
                name="metering_bi_organiz_c71f40_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="webhookendpoint",
            index=models.Index(
                fields=["organization", "webhook_endpoint_id"],
                name="metering_bi_organiz_ba861d_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="webhooktrigger",
            index=models.Index(
                fields=["organization", "webhook_endpoint", "trigger_name"],
                name="unique_webhook_trigger",
            ),
        ),
    ]
