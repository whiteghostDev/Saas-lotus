import base64
import itertools
import json
import time
import uuid
from datetime import datetime, timedelta

import pytest
import stripe
from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db.models import F, Prefetch, Q
from django.urls import reverse
from metering_billing.invoice import generate_invoice
from metering_billing.models import (
    Customer,
    ExternalPlanLink,
    Invoice,
    Organization,
    Subscription,
)
from metering_billing.tasks import calculate_invoice, update_invoice_status
from metering_billing.utils import now_utc
from metering_billing.utils.enums import (
    INVOICE_STATUS,
    PAYMENT_PROVIDERS,
    SUBSCRIPTION_STATUS,
)
from model_bakery import baker
from rest_framework.test import APIClient

STRIPE_SECRET_KEY = settings.STRIPE_SECRET_KEY
SELF_HOSTED = settings.SELF_HOSTED
stripe.api_key = STRIPE_SECRET_KEY


@pytest.fixture
def integration_test_common_setup(
    generate_org_and_api_key,
    add_customers_to_org,
    add_users_to_org,
    add_product_to_org,
    add_plan_to_product,
    add_plan_version_to_plan,
):
    def do_integration_test_common_setup():
        setup_dict = {}
        org, _ = generate_org_and_api_key()
        setup_dict["org"] = org
        (customer,) = add_customers_to_org(org, n=1)
        setup_dict["customer"] = customer
        event_properties = (
            {"num_characters": 350, "peak_bandwith": 65},
            {"num_characters": 125, "peak_bandwith": 148},
            {"num_characters": 543, "peak_bandwith": 16},
        )
        product = add_product_to_org(org)
        setup_dict["product"] = product
        plan = add_plan_to_product(product)
        setup_dict["plan"] = plan
        plan_version = add_plan_version_to_plan(plan)
        setup_dict["plan_version"] = plan_version
        plan.display_version = plan_version
        plan.save()

        client = APIClient()
        (user,) = add_users_to_org(org, n=1)
        client.force_authenticate(user=user)
        setup_dict["user"] = user
        setup_dict["client"] = client

        return setup_dict

    return do_integration_test_common_setup


@pytest.mark.django_db(transaction=True)
class TestStripeIntegration:
    def test_stripe_end_to_end(self, integration_test_common_setup):
        from metering_billing.payment_providers import PAYMENT_PROVIDER_MAP

        setup_dict = integration_test_common_setup()

        stripe_connector = PAYMENT_PROVIDER_MAP[PAYMENT_PROVIDERS.STRIPE]
        stripe_connector.initialize_settings(setup_dict["org"])
        # when self hosted make sure everything works
        assert SELF_HOSTED == True
        assert stripe_connector.working()
        assert stripe_connector.organization_connected(setup_dict["org"])

        # when not self hosted make sure org connected is not true, but working is
        stripe_connector.self_hosted = False
        assert not stripe_connector.organization_connected(setup_dict["org"])
        assert stripe_connector.working()

        # set back to self hosted and confirm customers are not initially connected
        stripe_connector.self_hosted = True
        assert not stripe_connector.customer_connected(setup_dict["customer"])

        # test create customer in stripe
        assert Customer.objects.all().count() == 1
        stripe_connector.create_customer(setup_dict["customer"])
        assert Customer.objects.all().count() == 1
        assert setup_dict["customer"].integrations["stripe"]["id"]
        assert stripe.Customer.retrieve(
            setup_dict["customer"].integrations["stripe"]["id"]
        )
        assert stripe_connector.customer_connected(setup_dict["customer"])

        # test import customer from stripe
        stripe_customer = stripe.Customer.create(
            email=f"{str(uuid.uuid4())[:10]}@example.com",
            description="Test Customer for pytest",
            name="Test Customer",
            payment_method="pm_card_visa",
            invoice_settings={"default_payment_method": "pm_card_visa"},
        )
        assert stripe_connector.import_customers(setup_dict["org"]) > 0
        Customer.objects.filter(
            ~Q(integrations__stripe__id=stripe_customer.id)
        ).delete()
        assert Customer.objects.all().count() == 1
        assert Customer.objects.all()[0].organization == setup_dict["org"]
        new_cust = Customer.objects.get(email=stripe_customer.email)
        assert stripe_connector.customer_connected(new_cust)
        assert new_cust.organization == setup_dict["org"]

        # now lets generate an invoice + for this customer
        subscription = Subscription.objects.create(
            organization=setup_dict["org"],
            customer=new_cust,
            billing_plan=setup_dict["plan_version"],
            start_date=now_utc() - timedelta(days=35),
            end_date=now_utc() - timedelta(days=5),
            status="ended",
        )
        invoice = generate_invoice(subscription)
        assert invoice.payment_status == INVOICE_STATUS.UNPAID
        assert invoice.external_payment_obj_type == PAYMENT_PROVIDERS.STRIPE
        try:
            stripe_pi = stripe.PaymentIntent.retrieve(invoice.external_payment_obj_id)
        except Exception as e:
            assert False, "Payment intent not found for reason: {}".format(e)

        # update the status of the invoice
        new_status = stripe_connector.update_payment_object_status(
            invoice.external_payment_obj_id
        )
        assert new_status == INVOICE_STATUS.UNPAID
        # now add payment method
        stripe.PaymentIntent.confirm(
            invoice.external_payment_obj_id,
            payment_method="pm_card_visa",
        )
        new_status = stripe_connector.update_payment_object_status(
            invoice.external_payment_obj_id
        )
        assert new_status == INVOICE_STATUS.PAID
        # try adding a new payment intent and loading it
        stripe_connector.import_payment_objects(setup_dict["org"])
        pi_before = (
            Invoice.objects.exclude(external_payment_obj_id__isnull=True)
            .exclude(external_payment_obj_id__exact="")
            .count()
        )
        stripe_pi2 = stripe.PaymentIntent.create(
            amount=5000,
            currency="usd",
            payment_method="pm_card_visa",
            customer=new_cust.integrations["stripe"]["id"],
        )
        stripe_connector.import_payment_objects(setup_dict["org"])
        pi_after = (
            Invoice.objects.exclude(external_payment_obj_id__isnull=True)
            .exclude(external_payment_obj_id__exact="")
            .count()
        )
        assert pi_after == pi_before + 1

        # now lets test out out
        product = stripe.Product.create(name="Test Product")
        price = stripe.Price.create(
            unit_amount=5000,
            currency="usd",
            product=product.id,
            recurring={"interval": "month"},
        )
        assert new_cust.integrations["stripe"]["id"] == stripe_customer.id
        stripe_sub = stripe.Subscription.create(
            customer=stripe_customer.id,
            items=[
                {"price": price.id},
            ],
        )
        time.sleep(20)
        ExternalPlanLink.objects.create(
            plan=setup_dict["plan"],
            external_plan_id=product.id,
            source=PAYMENT_PROVIDERS.STRIPE,
            organization=setup_dict["org"],
        )

        assert stripe_sub.cancel_at_period_end == False
        stripe_connector.transfer_subscriptions(setup_dict["org"], end_now=False)

        time.sleep(10)
        stripe_sub = stripe.Subscription.retrieve(stripe_sub.id)
        assert stripe_sub.cancel_at_period_end == True
        assert (
            Subscription.objects.filter(
                organization=setup_dict["org"],
                status=SUBSCRIPTION_STATUS.NOT_STARTED,
                billing_plan=setup_dict["plan"].display_version,
            ).count()
            == 1
        )
        stripe.Subscription.modify(
            stripe_sub.id,
            cancel_at_period_end=False,
        )

        # now lets test out the replace now
        Subscription.objects.filter(
            organization=setup_dict["org"],
            status=SUBSCRIPTION_STATUS.NOT_STARTED,
            billing_plan=setup_dict["plan"].display_version,
        ).delete()
        stripe_connector.transfer_subscriptions(setup_dict["org"], end_now=True)
        time.sleep(10)
        stripe_sub = stripe.Subscription.retrieve(stripe_sub.id)
        assert (
            Subscription.objects.filter(
                organization=setup_dict["org"],
                status=SUBSCRIPTION_STATUS.ACTIVE,
                billing_plan=setup_dict["plan"].display_version,
            ).count()
            == 1
        )
        assert stripe_sub.status == "canceled"

        # delete everything that we created
        stripe.Customer.delete(stripe_customer.id)


# @pytest.mark.django_db
# class TestUpdateInvoiceStatusStripe:
#     def test_update_invoice_status_stripe(self, integration_test_common_setup):
#         setup_dict = integration_test_common_setup()

#         c_id = setup_dict["customer"].payment_providers["stripe"]["id"]
#         payment_intent = stripe.PaymentIntent.create(
#             amount=5000,
#             currency="usd",
#             payment_method_types=["card"],
#             payment_method="pm_card_visa",
#             confirm=True,
#             customer=c_id,
#             off_session=True,
#         )

#         # Create the invoice
#         invoice = baker.make(
#             Invoice,
#             issue_date=setup_dict["subscription"].end_date,
#             payment_status=INVOICE_STATUS.UNPAID,
#             external_payment_obj_id=payment_intent.id,
#             organization={"company_name": "bogus"},
#         )

#         assert invoice.payment_status != INVOICE_STATUS.PAID

#         update_invoice_status()

#         invoice = Invoice.objects.filter(id=invoice.id).first()
#         assert invoice.payment_status == INVOICE_STATUS.PAID


# @pytest.mark.django_db(transaction=True)
# class TestSyncCustomersStripe:
#     def test_add_customers_update_existing(self, integration_test_common_setup):
#         setup_dict = integration_test_common_setup()
#         setup_dict["customer"].payment_providers["stripe"] = {"id": "bogus"}
#         setup_dict["customer"].save()
#         customers_before = Customer.objects.all().count()

#         payload = {}
#         response = setup_dict["client"].post(
#             reverse("sync_customers"),
#             data=json.dumps(payload, cls=DjangoJSONEncoder),
#             content_type="application/json",
#         )

#         customers_after = Customer.objects.all().count()
#         assert response.status_code == 201
#         assert customers_after == customers_before
#         customer = Customer.objects.get(organization=setup_dict["org"])
#         cust_d = customer.integrations["stripe"]
#         assert "id" in cust_d
#         assert cust_d["id"] != "bogus"
#         assert "email" in cust_d
#         assert "metadata" in cust_d
#         assert "name" in cust_d
#         assert "currency" in cust_d
#         sources = customer.sources
#         assert "stripe" in sources
#         assert "lotus" in sources

#     def test_add_customers_create_new(self, integration_test_common_setup):
#         setup_dict = integration_test_common_setup()
#         setup_dict["customer"].delete()
#         customers_before = Customer.objects.all().count()

#         payload = {}
#         response = setup_dict["client"].post(
#             reverse("sync_customers"),
#             data=json.dumps(payload, cls=DjangoJSONEncoder),
#             content_type="application/json",
#         )

#         customers_after = Customer.objects.all().count()
#         assert response.status_code == 201
#         assert customers_after == customers_before + 1
#         customer = Customer.objects.get(organization=setup_dict["org"])
#         cust_d = customer.integrations["stripe"]
#         assert "id" in cust_d
#         assert "email" in cust_d
#         assert "metadata" in cust_d
#         assert "name" in cust_d
#         assert "currency" in cust_d
#         sources = customer.sources
#         assert "stripe" in sources
#         assert "lotus" not in sources
