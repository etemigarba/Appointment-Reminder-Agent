"""Stripe REST client (raw HTTP, no SDK) — checkout, customer, portal."""

from __future__ import annotations

import httpx

STRIPE_API_BASE = "https://api.stripe.com/v1"
DEFAULT_TIMEOUT_SECONDS = 15.0


class StripeClient:
    def __init__(self, secret_key: str, *, transport: httpx.BaseTransport | None = None) -> None:
        self._client = httpx.Client(
            base_url=STRIPE_API_BASE,
            headers={"Authorization": f"Bearer {secret_key}"},
            timeout=DEFAULT_TIMEOUT_SECONDS,
            transport=transport,
        )

    def ensure_customer(self, tenant_id: str, email: str, existing_customer_id: str | None) -> str:
        if existing_customer_id:
            return existing_customer_id
        response = self._client.post(
            "/customers",
            data={"email": email, "metadata[tenant_id]": tenant_id},
        )
        response.raise_for_status()
        return response.json()["id"]

    def create_checkout_session(
        self,
        *,
        customer_id: str,
        price_id: str,
        success_url: str,
        cancel_url: str,
    ) -> dict:
        response = self._client.post(
            "/checkout/sessions",
            data={
                "mode": "subscription",
                "customer": customer_id,
                "line_items[0][price]": price_id,
                "line_items[0][quantity]": "1",
                "success_url": success_url,
                "cancel_url": cancel_url,
            },
        )
        if response.status_code >= 400:
            raise StripeError(response.status_code, response.text[:300])
        return response.json()

    def create_portal_session(self, *, customer_id: str, return_url: str) -> dict:
        response = self._client.post(
            "/billing_portal/sessions",
            data={"customer": customer_id, "return_url": return_url},
        )
        if response.status_code >= 400:
            raise StripeError(response.status_code, response.text[:300])
        return response.json()


class StripeError(RuntimeError):
    def __init__(self, status_code: int, body: str) -> None:
        super().__init__(f"stripe_{status_code}: {body}")
        self.status_code = status_code
