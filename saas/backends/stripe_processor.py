# Copyright (c) 2013, The DjaoDjin Team
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
#   * Redistributions of source code must retain the above copyright notice,
#     this list of conditions and the following disclaimer.
#   * Redistributions in binary form must reproduce the above copyright notice,
#     this list of conditions and the following disclaimer in the documentation
#     and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO,
# THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
# PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR
# CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
# EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
# PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS;
# OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY,
# WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR
# OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF
# ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

import datetime, json, logging, re

import stripe
from django.http import Http404
from django.conf import settings
from rest_framework.decorators import api_view
from rest_framework.response import Response

from saas.charge import (
    charge_succeeded,
    charge_failed,
    charge_refunded,
    charge_captured,
    charge_dispute_created,
    charge_dispute_updated,
    charge_dispute_closed)
from saas.settings import STRIPE_PRIV_KEY


LOGGER = logging.getLogger(__name__)

stripe.api_key = STRIPE_PRIV_KEY


def list_customers(org_pat=r'.*'):
    """
    Returns a list of Stripe.Customer objects whose description field
    matches *org_pat*.
    """
    customers = []
    nb_customers_listed = 0
    response = stripe.Customer.all()
    all_custs = response['data']
    while len(all_custs) > 0:
        for cust in all_custs:
            # We use the description field to store extra information
            # that connects the Stripe customer back to our database.
            if re.match(org_pat, cust.description):
                customers.append(cust)
        nb_customers_listed = nb_customers_listed + len(all_custs)
        response = stripe.Customer.all(offset=nb_customers_listed)
        all_custs = response['data']
    return customers


def create_charge(customer, amount, descr=None):
    """
    Create a charge on the default card associated to the customer.
    """
    processor_charge = stripe.Charge.create(
        amount=amount, currency="usd",
        customer=customer.processor_id,
        description=descr)
    return (processor_charge.id, processor_charge.created,
            processor_charge.card.last4,
            datetime.date(processor_charge.card.exp_year,
                          processor_charge.card.exp_month, 1))


def create_charge_on_card(card, amount, descr=None):
    """
    Create a charge on a specified card.
    """
    processor_charge = stripe.Charge.create(
        amount=amount, currency="usd",
        card=card, description=descr)
    return (processor_charge.id, processor_charge.created,
            processor_charge.card.last4,
            datetime.date(processor_charge.card.exp_year,
                          processor_charge.card.exp_month, 1))


def create_customer(name, card):
    processor_customer = stripe.Customer.create(description=name, card=card)
    return processor_customer.id


def update_card(customer, card):
    processor_customer = stripe.Customer.retrieve(customer.processor_id)
    processor_customer.card = card
    processor_customer.save()


def retrieve_card(customer):
    last4 = "N/A"
    exp_date = "N/A"
    if customer.processor_id:
        processor_customer = stripe.Customer.retrieve(customer.processor_id, expand=['default_card'])
        if processor_customer.default_card:
            last4 = '***-%s' % str(processor_customer.default_card.last4)
            exp_date = "%02d/%04d" % (processor_customer.default_card.exp_month,
                                      processor_customer.default_card.exp_year)
    return last4, exp_date


@api_view(['POST'])
def processor_hook(request):
    # Attempt to validate the event by posting it back to Stripe.
    if settings.DEBUG:
        event = stripe.Event.construct_from(request.DATA, STRIPE_PRIV_KEY)
    else:
        event = stripe.Event.retrieve(request.DATA['id'])
    if not event:
        LOGGER.error("Posted stripe event %s FAIL", request.DATA['id'])
        raise Http404
    LOGGER.info("Posted stripe event %s PASS", event.id)

    if event.type == 'charge.succeeded':
        charge_succeeded(event.data.object.id)
    elif event.type == 'charge.failed':
        charge_failed(event.data.object.id)
    elif event.type == 'charge.refunded':
        charge_refunded(event.data.object.id)
    elif event.type == 'charge.captured':
        charge_captured(event.data.object.id)
    elif event.type == 'charge.dispute.created':
        charge_dispute_created(event.data.object.id)
    elif event.type == 'charge.dispute.updated':
        charge_dispute_updated(event.data.object.id)
    elif event.type == 'charge.dispute.closed':
        charge_dispute_closed(event.data.object.id)

    return Response("OK")
