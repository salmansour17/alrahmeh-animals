"""HTTP endpoints for the donation ledger.

Handlers read the request, call one service method and return JSON; nothing
else. The public impact endpoint returns aggregates only. Every endpoint that
exposes a donor's name sits behind @require_admin.

There is no PUT or DELETE route. Because GET /<id> exists, Flask answers those
methods with 405 Method Not Allowed, which states the rule: a ledger entry
cannot be changed.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from domains.donations.models import Donation, ImpactSummary, ValidationError, format_jod
from domains.donations.service import DonationNotFound, DonationService
from security import require_admin


def create_donations_blueprint(service: DonationService) -> Blueprint:
    bp = Blueprint("donations", __name__, url_prefix="/api/donations")

    # --- public --------------------------------------------------------------

    @bp.get("/impact")
    def impact():
        return jsonify(_impact(service.impact()))

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


def _impact(summary: ImpactSummary) -> dict:
    return {
        "total_raised": _money(summary.total_raised_fils),
        "donation_count": summary.donation_count,
        "animals_helped": summary.animals_helped,
        "by_purpose": {
            purpose.value: _money(total) for purpose, total in summary.totals_by_purpose_fils.items()
        },
    }
