# Generated by Django 4.0.6 on 2022-07-27 02:29

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("billing", "0002_customer_balance_customer_balance_currency_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="customer",
            name="billing_configuration",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
