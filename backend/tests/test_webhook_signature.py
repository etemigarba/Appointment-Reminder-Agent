"""Twilio signature computation matches the documented HMAC-SHA1 spec."""

import base64
import hashlib
import hmac

from app.api.webhooks import compute_twilio_signature


def test_signature_matches_manual_hmac():
    token = "SECRET"
    url = "https://example.com/webhooks/twilio"
    params = {"From": "+15551234567", "To": "+15550001111", "Body": "hi"}

    expected = base64.b64encode(
        hmac.new(
            token.encode(),
            (url + "BodyhiFrom+15551234567To+15550001111").encode(),
            hashlib.sha1,
        ).digest()
    ).decode()

    assert compute_twilio_signature(token, url, params) == expected


def test_different_params_change_signature():
    a = compute_twilio_signature("t", "https://x", {"A": "1"})
    b = compute_twilio_signature("t", "https://x", {"A": "2"})

    assert a != b
