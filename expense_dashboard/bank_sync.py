from __future__ import annotations

import base64
import hashlib
import json
import os
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pandas as pd
from cryptography.fernet import Fernet, InvalidToken


PLAID_URLS = {
    "sandbox": "https://sandbox.plaid.com",
    "production": "https://production.plaid.com",
}


class BankSyncError(RuntimeError):
    pass


@dataclass(frozen=True)
class PlaidConfig:
    client_id: str
    secret: str
    environment: str = "sandbox"

    @classmethod
    def from_environment(cls) -> "PlaidConfig | None":
        client_id = os.getenv("PLAID_CLIENT_ID", "").strip()
        secret = os.getenv("PLAID_SECRET", "").strip()
        environment = os.getenv("PLAID_ENV", "sandbox").strip().lower()
        if not client_id or not secret:
            return None
        if environment not in PLAID_URLS:
            raise BankSyncError("PLAID_ENV must be 'sandbox' or 'production'.")
        return cls(client_id, secret, environment)


def _fernet(key: str | None = None) -> Fernet:
    secret = key or os.getenv("PLAID_TOKEN_ENCRYPTION_KEY", "")
    if not secret:
        raise BankSyncError("PLAID_TOKEN_ENCRYPTION_KEY is not configured.")
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_access_token(token: str, key: str | None = None) -> str:
    return _fernet(key).encrypt(token.encode("utf-8")).decode("ascii")


def decrypt_access_token(token: str, key: str | None = None) -> str:
    try:
        return _fernet(key).decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise BankSyncError("The stored bank token could not be decrypted.") from exc


class PlaidClient:
    def __init__(self, config: PlaidConfig, timeout: int = 30):
        self.config = config
        self.timeout = timeout

    def _post(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = {
            "client_id": self.config.client_id,
            "secret": self.config.secret,
            **payload,
        }
        request = Request(
            f"{PLAID_URLS[self.config.environment]}{endpoint}",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            try:
                message = json.loads(detail).get("error_message", detail)
            except json.JSONDecodeError:
                message = detail
            raise BankSyncError(f"Plaid request failed: {message}") from exc
        except URLError as exc:
            raise BankSyncError(f"Could not reach Plaid: {exc.reason}") from exc

    def create_link_token(self, user_id: str) -> str:
        response = self._post(
            "/link/token/create",
            {
                "client_name": "Expense Dashboard",
                "country_codes": ["US"],
                "language": "en",
                "products": ["transactions"],
                "user": {"client_user_id": user_id},
                "transactions": {"days_requested": 730},
            },
        )
        return response["link_token"]

    def exchange_public_token(self, public_token: str) -> dict[str, str]:
        response = self._post(
            "/item/public_token/exchange", {"public_token": public_token}
        )
        return {
            "access_token": response["access_token"],
            "item_id": response["item_id"],
        }

    def get_item_name(self, access_token: str) -> str:
        item = self._post("/item/get", {"access_token": access_token})["item"]
        institution_id = item.get("institution_id")
        if not institution_id:
            return "Connected bank"
        institution = self._post(
            "/institutions/get_by_id",
            {"institution_id": institution_id, "country_codes": ["US"]},
        )
        return institution["institution"]["name"]

    def sync_transactions(
        self, access_token: str, cursor: str | None = None
    ) -> tuple[list[dict], list[dict], list[str], str]:
        added: list[dict] = []
        modified: list[dict] = []
        removed: list[str] = []
        next_cursor = cursor
        while True:
            payload: dict[str, Any] = {
                "access_token": access_token,
                "count": 500,
                "options": {"include_original_description": True},
            }
            if next_cursor:
                payload["cursor"] = next_cursor
            response = self._post("/transactions/sync", payload)
            added.extend(response.get("added", []))
            modified.extend(response.get("modified", []))
            removed.extend(row["transaction_id"] for row in response.get("removed", []))
            next_cursor = response["next_cursor"]
            if not response.get("has_more", False):
                return added, modified, removed, next_cursor


def plaid_transactions_frame(rows: list[dict], institution_name: str) -> pd.DataFrame:
    records = []
    for row in rows:
        if row.get("pending"):
            continue
        description = (
            row.get("merchant_name")
            or row.get("original_description")
            or row.get("name")
            or "Bank transaction"
        )
        records.append(
            {
                "external_id": row["transaction_id"],
                "date": row.get("authorized_date") or row["date"],
                "amount": abs(float(row["amount"])),
                "description": str(description).strip(),
                "source": institution_name,
            }
        )
    return pd.DataFrame(records)
