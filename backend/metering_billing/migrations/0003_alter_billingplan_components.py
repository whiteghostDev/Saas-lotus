# Generated by Django 4.0.5 on 2022-09-06 04:38

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("metering_billing", "0002_alter_billingplan_flat_rate_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="billingplan",
            name="components",
            field=models.ManyToManyField(
                blank=True, to="metering_billing.plancomponent"
            ),
        ),
    ]
