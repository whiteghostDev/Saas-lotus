# Generated by Django 4.0.5 on 2022-12-15 05:20

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("metering_billing", "0122_auto_20221215_0516"),
    ]

    operations = [migrations.RenameModel("Event", "OldEvent")]
