# Generated by Django 4.0.5 on 2022-10-16 19:38

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("metering_billing", "0048_remove_organizationinvitetoken_is_valid_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="historicalorganization",
            name="company_name",
            field=models.CharField(max_length=100),
        ),
        migrations.AlterField(
            model_name="organization",
            name="company_name",
            field=models.CharField(max_length=100),
        ),
    ]
