"""Thin async client for the Crystalpay v3 invoice API.

We only need a handful of endpoints — ``invoice/create`` and
``invoice/info`` for the wallet-deposit flow, plus a webhook-signature
helper exposed as a module-level function so the FastAPI router can
use it without spinning up an ``httpx.AsyncClient``.

Crystalpay v3 authenticates by sending the cashbox login + secret in
the JSON body of every request; there is no header-based auth. Errors
surface as ``{"error": true, "errors": [...]}`` (or, for older
responses, ``{"error": true, "message": "..."}``) and we raise
:class:`CrystalpayError` in both shapes.

See https://docs.crystalpay.io/ for the upstream contract.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)

API_BASE = "https://api.crystalpay.io/v3"

# Crystalpay terminal invoice states.
INVOICE_STATE_PAID = "payed"
INVOICE_STATE_UNAVAILABLE = "unavailable"
INVOICE_STATE_FAILED = "failed"
INVOICE_TERMINAL_STATES = frozenset(
    {INVOICE_STATE_PAID, INVOICE_STATE_UNAVAILABLE, INVOICE_STATE_FAILED}
)


class CrystalpayError(Exception):
    """Raised when the Crystalpay API returns an error or a request fails."""


@dataclass(frozen=True, slots=True)
class CrystalpayInvoice:
    """Subset of the ``invoice/create`` / ``invoice/info`` response we use."""

    id: str
    url: str
    state: str
    type: str | None = None
    amount: str | None = None
    currency: str | None = None
    description: str | None = None
    raw: dict[str, Any] | None = None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "CrystalpayInvoice":
        return cls(
            id=str(data.get("id") or ""),
            url=str(data.get("url") or ""),
            state=str(data.get("state") or ""),
            type=data.get("type"),
            amount=str(data["amount"]) if data.get("amount") is not None else None,
            currency=data.get("currency"),
            description=data.get("description"),
            raw=data,
        )


class Crystalpay:
    """Async Crystalpay v3 client.

    Usage::

        async with Crystalpay(login, secret) as cp:
            inv = await cp.create_invoice(
                amount=10.0,
                currency="USDT",
                lifetime=30,
                callback_url="https://example.com/webhook",
            )
    """

    def __init__(
        self,
        login: str,
        secret: str,
        *,
        base_url: str | None = None,
        timeout: float = 15.0,
    ) -> None:
        if not login or not secret:
            raise CrystalpayError("Crystalpay credentials are empty")
        self._login = login
        self._secret = secret
        self._base = base_url or API_BASE
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "Crystalpay":
        self._client = httpx.AsyncClient(base_url=self._base, timeout=self._timeout)
        return self

    async def __aexit__(self, *exc: Any) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _call(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        # Crystalpay v3 expects ``auth_login`` + ``auth_secret`` in the
        # JSON body on every request; there is no header-based auth.
        body = {"auth_login": self._login, "auth_secret": self._secret, **payload}
        client = self._client
        owns_client = False
        if client is None:
            client = httpx.AsyncClient(base_url=self._base, timeout=self._timeout)
            owns_client = True
        try:
            response = await client.post(f"/{method}/", json=body)
        except httpx.HTTPError as exc:
            raise CrystalpayError(f"Crystalpay HTTP error: {exc}") from exc
        finally:
            if owns_client:
                await client.aclose()

        try:
            data = response.json()
        except ValueError as exc:
            raise CrystalpayError(
                f"Crystalpay returned non-JSON (HTTP {response.status_code})"
            ) from exc

        if not isinstance(data, dict):
            raise CrystalpayError("Crystalpay returned non-object body")
        if data.get("error"):
            # v3 returns an ``errors`` array; older responses used a
            # single ``message`` string. Surface whichever is present.
            errors = data.get("errors")
            if isinstance(errors, list) and errors:
                message = "; ".join(str(e) for e in errors)
            else:
                message = str(data.get("message") or "Crystalpay error")
            raise CrystalpayError(message)
        return data

    async def create_invoice(
        self,
        *,
        amount: float | str,
        type_: str = "purchase",
        lifetime: int = 30,
        currency: str | None = None,
        callback_url: str | None = None,
        description: str | None = None,
        extra: str | None = None,
    ) -> CrystalpayInvoice:
        """Create a new Crystalpay invoice.

        ``lifetime`` is the invoice's TTL in **minutes** per the
        upstream API. ``type_`` is the invoice purpose — ``"purchase"``
        is the generic one-off payment that fits the wallet-deposit
        flow. ``callback_url`` is optional (Crystalpay only fires the
        webhook when set).
        """
        payload: dict[str, Any] = {
            "amount": str(amount),
            "type": type_,
            "lifetime": int(lifetime),
        }
        if currency is not None:
            payload["currency"] = currency
        if callback_url is not None:
            payload["callback_url"] = callback_url
        if description is not None:
            payload["description"] = description
        if extra is not None:
            payload["extra"] = extra
        data = await self._call("invoice/create", payload)
        # Crystalpay v3 wraps the invoice in either a top-level dict
        # with ``id``/``url``/``state`` or in a ``response`` /
        # ``result`` envelope, depending on the endpoint version we
        # hit. Normalise both shapes.
        inv = _unwrap_invoice(data)
        return CrystalpayInvoice.from_api(inv)

    async def get_invoice(self, invoice_id: str) -> CrystalpayInvoice:
        """Fetch the current state of an invoice. Used by polling fallback."""
        data = await self._call("invoice/info", {"id": invoice_id})
        inv = _unwrap_invoice(data)
        return CrystalpayInvoice.from_api(inv)


def _unwrap_invoice(data: dict[str, Any]) -> dict[str, Any]:
    """Pluck the invoice dict out of whatever envelope Crystalpay sent."""
    for key in ("response", "result", "invoice"):
        nested = data.get(key)
        if isinstance(nested, dict) and ("id" in nested or "state" in nested):
            return nested
    return data


def verify_webhook_signature(invoice_id: str, salt: str | None, signature: str | None) -> bool:
    """Validate a Crystalpay webhook signature.

    Crystalpay signs webhook bodies as ``sha1(f"{id}:{secret}")`` where
    ``secret`` is the cashbox's API secret. ``hmac.compare_digest`` is
    used to avoid leaking the comparison through timing.

    Both ``salt`` and ``signature`` are accepted as ``None`` to fail
    closed when the caller hasn't extracted them from the payload yet.
    """
    if not invoice_id or not salt or not signature:
        return False
    # Crystalpay v3 signs webhook bodies as ``sha1(f"{id}:{secret}")``;
    # we cannot pick a stronger algorithm because the upstream protocol
    # is the source of truth. The salt is the cashbox API secret, so
    # the construction is HMAC-equivalent for an attacker who lacks
    # the secret. Suppressed B324: the choice of SHA-1 is dictated by
    # the external API contract, not by us.
    expected = hashlib.sha1(  # noqa: S324  # nosec B324
        f"{invoice_id}:{salt}".encode()
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


__all__ = [
    "Crystalpay",
    "CrystalpayError",
    "CrystalpayInvoice",
    "INVOICE_STATE_FAILED",
    "INVOICE_STATE_PAID",
    "INVOICE_STATE_UNAVAILABLE",
    "INVOICE_TERMINAL_STATES",
    "verify_webhook_signature",
]
