"""Thin async client for the Crypto Pay API (https://help.send.tg/en/articles/10279948-crypto-pay-api).

Replaces the unmaintained ``AsyncPayments`` SDK. Only implements the
handful of methods we actually use (``createInvoice``, ``getInvoices``,
``transfer``) plus a generic ``_call`` helper so future endpoints are
cheap to add.

The API returns ``{"ok": true, "result": ...}`` on success and
``{"ok": false, "error": {"code": int, "name": str}}`` on failure.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)

MAINNET_BASE = "https://pay.crypt.bot/api"
TESTNET_BASE = "https://testnet-pay.crypt.bot/api"


class CryptoPayError(Exception):
    """Raised when the Crypto Pay API returns an error or the request fails."""

    def __init__(self, message: str, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class Invoice:
    invoice_id: int
    status: str  # "active" | "paid" | "expired"
    asset: str
    amount: str
    pay_url: str
    bot_invoice_url: str | None
    mini_app_invoice_url: str | None
    web_app_invoice_url: str | None
    description: str | None
    payload: str | None
    paid_at: str | None
    created_at: str | None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "Invoice":
        return cls(
            invoice_id=int(data["invoice_id"]),
            status=data.get("status", "active"),
            asset=data.get("asset", ""),
            amount=str(data.get("amount", "")),
            pay_url=data.get("pay_url") or data.get("bot_invoice_url") or "",
            bot_invoice_url=data.get("bot_invoice_url"),
            mini_app_invoice_url=data.get("mini_app_invoice_url"),
            web_app_invoice_url=data.get("web_app_invoice_url"),
            description=data.get("description"),
            payload=data.get("payload"),
            paid_at=data.get("paid_at"),
            created_at=data.get("created_at"),
        )


@dataclass(frozen=True, slots=True)
class Transfer:
    transfer_id: int
    user_id: int
    asset: str
    amount: str
    status: str
    completed_at: str | None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "Transfer":
        return cls(
            transfer_id=int(data["transfer_id"]),
            user_id=int(data["user_id"]),
            asset=data["asset"],
            amount=str(data["amount"]),
            status=data.get("status", "completed"),
            completed_at=data.get("completed_at"),
        )


class CryptoPay:
    """Async Crypto Pay client.

    Usage:

        async with CryptoPay(token) as cp:
            invoice = await cp.create_invoice(asset="USDT", amount=1.5)
    """

    def __init__(
        self,
        token: str,
        *,
        testnet: bool = False,
        timeout: float = 15.0,
        base_url: str | None = None,
    ) -> None:
        if not token:
            raise CryptoPayError("Crypto Pay token is empty")
        self._token = token
        self._base = base_url or (TESTNET_BASE if testnet else MAINNET_BASE)
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "CryptoPay":
        self._client = httpx.AsyncClient(
            base_url=self._base,
            timeout=self._timeout,
            headers={"Crypto-Pay-API-Token": self._token},
        )
        return self

    async def __aexit__(self, *exc: Any) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _call(self, method: str, payload: dict[str, Any] | None = None) -> Any:
        client = self._client
        owns_client = False
        if client is None:
            client = httpx.AsyncClient(
                base_url=self._base,
                timeout=self._timeout,
                headers={"Crypto-Pay-API-Token": self._token},
            )
            owns_client = True
        try:
            response = await client.post(f"/{method}", json=payload or {})
        except httpx.HTTPError as exc:
            raise CryptoPayError(f"Crypto Pay HTTP error: {exc}") from exc
        finally:
            if owns_client:
                await client.aclose()

        try:
            body = response.json()
        except ValueError as exc:
            raise CryptoPayError(
                f"Crypto Pay returned non-JSON (HTTP {response.status_code})"
            ) from exc

        if not body.get("ok"):
            err = body.get("error") or {}
            raise CryptoPayError(
                err.get("name") or f"HTTP {response.status_code}",
                code=err.get("code"),
            )
        return body.get("result")

    # ── API methods ──────────────────────────────────────

    async def get_me(self) -> dict[str, Any]:
        return await self._call("getMe")

    async def create_invoice(
        self,
        *,
        asset: str,
        amount: float | str,
        description: str | None = None,
        payload: str | None = None,
        expires_in: int | None = None,
        allow_comments: bool | None = None,
        allow_anonymous: bool | None = None,
    ) -> Invoice:
        data: dict[str, Any] = {"asset": asset, "amount": str(amount)}
        if description is not None:
            data["description"] = description
        if payload is not None:
            data["payload"] = payload
        if expires_in is not None:
            data["expires_in"] = expires_in
        if allow_comments is not None:
            data["allow_comments"] = allow_comments
        if allow_anonymous is not None:
            data["allow_anonymous"] = allow_anonymous
        result = await self._call("createInvoice", data)
        return Invoice.from_api(result)

    async def get_invoices(
        self,
        *,
        invoice_ids: list[int] | None = None,
        asset: str | None = None,
        status: str | None = None,
        offset: int = 0,
        count: int = 100,
    ) -> list[Invoice]:
        data: dict[str, Any] = {"offset": offset, "count": count}
        if invoice_ids:
            data["invoice_ids"] = ",".join(str(i) for i in invoice_ids)
        if asset:
            data["asset"] = asset
        if status:
            data["status"] = status
        result = await self._call("getInvoices", data)
        items = result.get("items") if isinstance(result, dict) else result
        return [Invoice.from_api(item) for item in (items or [])]

    async def transfer(
        self,
        *,
        user_id: int,
        asset: str,
        amount: float | str,
        spend_id: str,
        comment: str | None = None,
        disable_send_notification: bool | None = None,
    ) -> Transfer:
        data: dict[str, Any] = {
            "user_id": user_id,
            "asset": asset,
            "amount": str(amount),
            "spend_id": spend_id,
        }
        if comment is not None:
            data["comment"] = comment
        if disable_send_notification is not None:
            data["disable_send_notification"] = disable_send_notification
        result = await self._call("transfer", data)
        return Transfer.from_api(result)

    async def get_balance(self) -> list[dict[str, Any]]:
        result = await self._call("getBalance")
        return list(result or [])


__all__ = ["CryptoPay", "CryptoPayError", "Invoice", "Transfer"]
