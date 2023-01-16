# Generated by Django 4.0.5 on 2023-01-15 08:08

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("metering_billing", "0158_alter_backtest_backtest_id_and_more"),
    ]

    operations = [
        migrations.RenameField(
            model_name="pricetier",
            old_name="batch_rounding_type",
            new_name="batch_rounding_type_old",
        ),
        migrations.RenameField(
            model_name="pricetier",
            old_name="type",
            new_name="type_old",
        ),
        migrations.RemoveField(
            model_name="historicalorganization",
            name="payment_plan",
        ),
        migrations.RemoveField(
            model_name="organization",
            name="payment_plan",
        ),
    ]
