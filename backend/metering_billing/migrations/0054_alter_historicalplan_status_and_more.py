# Generated by Django 4.0.5 on 2022-10-27 01:10

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("metering_billing", "0053_historicalplan_parent_plan_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="historicalplan",
            name="status",
            field=models.CharField(
                choices=[
                    ("active", "Active"),
                    ("archived", "Archived"),
                    ("experimental", "Experimental"),
                ],
                default="active",
                max_length=40,
            ),
        ),
        migrations.AlterField(
            model_name="historicalsubscription",
            name="end_date",
            field=models.DateTimeField(),
        ),
        migrations.AlterField(
            model_name="historicalsubscription",
            name="start_date",
            field=models.DateTimeField(),
        ),
        migrations.AlterField(
            model_name="plan",
            name="parent_product",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="product_plans",
                to="metering_billing.product",
            ),
        ),
        migrations.AlterField(
            model_name="plan",
            name="status",
            field=models.CharField(
                choices=[
                    ("active", "Active"),
                    ("archived", "Archived"),
                    ("experimental", "Experimental"),
                ],
                default="active",
                max_length=40,
            ),
        ),
        migrations.AlterField(
            model_name="subscription",
            name="end_date",
            field=models.DateTimeField(),
        ),
        migrations.AlterField(
            model_name="subscription",
            name="start_date",
            field=models.DateTimeField(),
        ),
    ]
