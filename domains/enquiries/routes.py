"""HTTP endpoints for enquiries.

The public can send a message and learn nothing else: the answer is the same
{"status": "received"} whether it was stored or a honeypot was caught. Reading
messages and marking them handled are staff-only.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from domains.enquiries.models import Enquiry, ValidationError
from domains.enquiries.service import EnquiryNotFound, EnquiryService
from security import require_admin

RECEIVED = {"status": "received"}


def create_enquiries_blueprint(service: EnquiryService) -> Blueprint:
    bp = Blueprint("enquiries", __name__, url_prefix="/api/enquiries")

    # Exception 4 of 4 to "every write gets @require_admin" (CLAUDE.md, Auth):
    # anyone may write to the rescue. It only stores a message for staff.
    @bp.post("")
    def send_enquiry():
        if not request.is_json:
            return jsonify(error="unsupported_media_type", detail="send application/json"), 415
        service.receive(request.get_json(silent=True))
        return jsonify(RECEIVED), 201

    @bp.get("")
    @require_admin
    def list_enquiries():
        enquiries = service.list_enquiries(
            request.args.get("handled"), request.args.get("limit"), request.args.get("offset")
        )
        return jsonify(enquiries=[_enquiry(e) for e in enquiries])

    @bp.post("/<int:enquiry_id>/handled")
    @require_admin
    def mark_handled(enquiry_id: int):
        return jsonify(_enquiry(service.mark_handled(enquiry_id)))

    @bp.errorhandler(ValidationError)
    def bad_request(error: ValidationError):
        return jsonify(error="validation_failed", detail=str(error)), 400

    @bp.errorhandler(EnquiryNotFound)
    def not_found(error: EnquiryNotFound):
        return jsonify(error="not_found", detail=str(error)), 404

    return bp


def _enquiry(enquiry: Enquiry) -> dict:
    """Staff view of a message, sender included. Only returned by staff routes."""
    return {
        "id": enquiry.id,
        "topic": enquiry.topic.value,
        "name": enquiry.name,
        "email": enquiry.email,
        "subject": enquiry.subject,
        "message": enquiry.message,
        "handled": enquiry.handled,
        "received_at": enquiry.received_at,
    }
