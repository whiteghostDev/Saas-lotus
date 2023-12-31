# Generated by Django 4.0.5 on 2023-02-19 03:13

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        (
            "metering_billing",
            "0196_remove_idempotencecheck_unique_idempotency_id_per_org_raw_and_more",
        ),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                CREATE OR REPLACE FUNCTION update_customer_uuid_function() RETURNS TRIGGER AS $$
                BEGIN
                    NEW.uuidv5_customer_id := uuid_generate_v5('D1337E57-E6A0-4650-B1C3-D6487AFFB8CA'::uuid, NEW.customer_id::text);
                    RETURN NEW;
                END;
                $$ LANGUAGE plpgsql;

                CREATE TRIGGER update_customer_uuid_trigger
                BEFORE INSERT OR UPDATE ON metering_billing_customer
                FOR EACH ROW
                EXECUTE FUNCTION update_customer_uuid_function();
            """,
            reverse_sql="""
                DROP TRIGGER update_customer_uuid_trigger ON metering_billing_customer;
                DROP FUNCTION update_customer_uuid_function();
            """,
        )
    ]
