"""HTTP endpoints for the donation ledger.

Handlers read the request, call one service method and return JSON; nothing
else. The public impact endpoint returns aggregates only. Every endpoint that
exposes a donor's name sits behind @require_admin.

Two POST routes are public on purpose, and are the only writes without
@require_admin: starting a card checkout, and the Stripe webhook, which is
authenticated by its signature instead.

There is no PUT or DELETE route. Because GET /<id> exists, Flask answers those
methods with 405 Method Not Allowed, which states the rule: a ledger entry
cannot be changed.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from domains.donations.models import (
    Donation,
    ImpactSummary,
    OfflineMethods,
    ValidationError,
    format_jod,
)
from domains.donations.service import (
    DonationNotFound,
    DonationService,
    InvalidWebhookSignature,
    PaymentProviderError,
    PaymentsUnavailable,
)
from security import require_admin


def create_donations_blueprint(service: DonationService, offline: OfflineMethods) -> Blueprint:
    bp = Blueprint("donations", __name__, url_prefix="/api/donations")

    # --- public --------------------------------------------------------------

    @bp.get("/offline-methods")
    def offline_methods():
        return jsonify(_offline(offline))

    @bp.get("/impact")
    def impact():
        return jsonify(_impact(service.impact()))

    # Exception 1 of 2 to "every write gets @require_admin" (CLAUDE.md, Auth):
    # donors are members of the public. It writes nothing to the ledger.
    @bp.post("/checkout")
    def start_checkout():
        if not request.is_json:
            return jsonify(error="unsupported_media_type", detail="send application/json"), 415
        session = service.start_checkout(request.get_json(silent=True))
        return jsonify(checkout_url=session.url), 201

    # Exception 2 of 2 (CLAUDE.md, Auth): Stripe cannot send the admin
    # password, so the signature over the raw body authenticates the call
    # instead. get_data() must come before anything parses the body, because
    # the signature covers the exact bytes.
    @bp.post("/stripe/webhook")
    def stripe_webhook():
        outcome = service.handle_webhook(request.get_data(), request.headers.get("Stripe-Signature"))
        return jsonify(status=outcome.value)

    # --- staff ---------------------------------------------------------------

    @bp.post("")
    @require_admin
    def record_donation():
        donation = service.record(request.get_json(silent=True))
        return jsonify(_donation(donation)), 201

    @bp.get("")
    @require_admin
    def list_donations():
        donations = service.list_donations(request.args.get("limit"), request.args.get("offset"))
        return jsonify(donations=[_donation(d) for d in donations])

    @bp.get("/<int:donation_id>")
    @require_admin
    def get_donation(donation_id: int):
        return jsonify(_donation(service.get(donation_id)))

    # --- errors --------------------------------------------------------------

    @bp.errorhandler(ValidationError)
    def bad_request(error: ValidationError):
        return jsonify(error="validation_failed", detail=str(error)), 400

    @bp.errorhandler(DonationNotFound)
    def not_found(error: DonationNotFound):
        return jsonify(error="not_found", detail=str(error)), 404

    @bp.errorhandler(InvalidWebhookSignature)
    def bad_signature(error: InvalidWebhookSignature):
        return jsonify(error="invalid_signature"), 400

    @bp.errorhandler(PaymentsUnavailable)
    def payments_unavailable(error: PaymentsUnavailable):
        return jsonify(error="payments_unavailable", detail=str(error)), 503

    @bp.errorhandler(PaymentProviderError)
    def provider_error(error: PaymentProviderError):
        return jsonify(error="payment_provider_error", detail=str(error)), 502

    return bp


def _money(amount_fils: int) -> dict:
    """Every amount leaves the API in both forms, so the frontend displays the
    string and never does arithmetic on money."""
    return {"amount_fils": amount_fils, "amount_jod": format_jod(amount_fils)}


def _donation(donation: Donation) -> dict:
    return {
        "id": donation.id,
        "donor_name": donation.donor_name,
        **_money(donation.amount_fils),
        "purpose": donation.purpose.value,
        "earmarked_animal_id": donation.earmarked_animal_id,
        "received_on": donation.received_on.isoformat(),
    }


def _offline(methods: OfflineMethods) -> dict:
    """Each option is null when not configured, so the page can hide it."""
    return {
        "cliq": {"alias": methods.cliq_alias} if methods.cliq_alias else None,
        "bank": (
            {
                "bank_name": methods.bank_name,
                "iban": methods.bank_iban,
                "account_name": methods.bank_account_name,
            }
            if methods.has_bank
            else None
        ),
    }


def _impact(summary: ImpactSummary) -> dict:
    return {
        "total_raised": _money(summary.total_raised_fils),
        "donation_count": summary.donation_count,
        "animals_helped": summary.animals_helped,
        "by_purpose": {
            purpose.value: _money(total) for purpose, total in summary.totals_by_purpose_fils.items()
        },
    }
