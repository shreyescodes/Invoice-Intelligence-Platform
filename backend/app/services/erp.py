"""ERP clients: the domain types the pipeline works with, a resilient HTTP base, and the client for the
SAP S/4HANA-shaped API served by erp-mock. The ERPNext client lives in erpnext.py."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Protocol
from urllib.parse import quote

import httpx

from app.config import Settings
from app.observability import ERP_REQUESTS, get_logger

log = get_logger(__name__)


class ErpError(Exception):
    pass


class ErpUnavailableError(ErpError):
    """Network failure, timeout, 5xx or 429: safe to retry later."""


class ErpRejectedError(ErpError):
    """The ERP refused the request for a business reason (4xx). Retrying will not help."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(f"ERP rejected request ({status_code}): {detail}")
        self.status_code = status_code
        self.detail = detail


@dataclass(frozen=True, slots=True)
class Supplier:
    erp_id: str
    name: str
    tax_id: str | None
    city: str | None
    currency: str
    payment_terms_days: int
    street: str | None = None
    postal_code: str | None = None
    region: str | None = None
    bank_account: str | None = None


@dataclass(frozen=True, slots=True)
class PurchaseOrderItem:
    item: str
    description: str
    quantity: Decimal
    unit: str
    net_price: Decimal
    received_quantity: Decimal
    invoiced_quantity: Decimal

    @property
    def open_quantity(self) -> Decimal:
        """Quantity received but not yet invoiced - the ceiling for a 3-way match."""
        return self.received_quantity - self.invoiced_quantity


@dataclass(frozen=True, slots=True)
class PurchaseOrder:
    number: str
    supplier_id: str
    currency: str
    order_date: date | None
    items: tuple[PurchaseOrderItem, ...]


@dataclass(frozen=True, slots=True)
class PostingResult:
    document_number: str
    fiscal_year: str


def _supplier(raw: dict[str, Any]) -> Supplier:
    return Supplier(
        erp_id=str(raw["Supplier"]),
        name=raw["SupplierName"],
        tax_id=raw.get("TaxNumber") or None,
        city=raw.get("City"),
        currency=raw.get("Currency", "INR"),
        payment_terms_days=int(raw.get("PaymentTermsDays", 30)),
        street=raw.get("Street"),
        postal_code=raw.get("PostalCode"),
        region=raw.get("Region"),
        bank_account=raw.get("BankAccount"),
    )


def _purchase_order(raw: dict[str, Any]) -> PurchaseOrder:
    return PurchaseOrder(
        number=raw["PurchaseOrder"],
        supplier_id=str(raw["Supplier"]),
        currency=raw.get("DocumentCurrency", "INR"),
        order_date=date.fromisoformat(raw["PurchaseOrderDate"]) if raw.get("PurchaseOrderDate") else None,
        items=tuple(
            PurchaseOrderItem(
                item=str(i["PurchaseOrderItem"]),
                description=i["Description"],
                quantity=Decimal(str(i["OrderQuantity"])),
                unit=i.get("Unit", "EA"),
                net_price=Decimal(str(i["NetPrice"])),
                received_quantity=Decimal(str(i.get("ReceivedQuantity", "0"))),
                invoiced_quantity=Decimal(str(i.get("InvoicedQuantity", "0"))),
            )
            for i in raw.get("Items", [])
        ),
    )


class Erp(Protocol):
    def list_suppliers(self) -> list[Supplier]: ...
    def get_supplier(self, erp_id: str) -> Supplier | None: ...
    def get_company(self) -> dict[str, Any]: ...
    def list_purchase_orders(self, supplier_id: str | None = None) -> list[PurchaseOrder]: ...
    def get_purchase_order(self, number: str) -> PurchaseOrder | None: ...
    def post_supplier_invoice(self, idempotency_key: str, payload: dict[str, Any]) -> PostingResult: ...
    def ping(self) -> None: ...
    def close(self) -> None: ...


class HttpErp:
    """HTTP plumbing shared by the ERP clients: timeouts, metrics and quick retries."""

    def __init__(
        self,
        base_url: str,
        headers: dict[str, str],
        timeout: float = 10.0,
        transport: httpx.BaseTransport | None = None,
        attempts: int = 3,
        backoff_seconds: float = 0.5,
    ) -> None:
        self.attempts = attempts
        self.backoff_seconds = backoff_seconds
        self._http = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Accept": "application/json", **headers},
            timeout=httpx.Timeout(timeout, connect=min(timeout, 5.0)),
            transport=transport,
        )

    def close(self) -> None:
        self._http.close()

    def _call(self, operation: str, send: Callable[[], httpx.Response]) -> httpx.Response:
        """Send with a few quick retries for transient failures. Longer outages surface as
        ErpUnavailableError and are retried by the job queue with exponential backoff."""
        for attempt in range(1, self.attempts + 1):
            try:
                return self._send_once(operation, send)
            except ErpUnavailableError:
                if attempt == self.attempts:
                    raise
                time.sleep(self.backoff_seconds * 2 ** (attempt - 1))
        raise AssertionError("unreachable")

    def _send_once(self, operation: str, send: Callable[[], httpx.Response]) -> httpx.Response:
        try:
            response = send()
        except httpx.TransportError as exc:
            ERP_REQUESTS.labels(operation, "unavailable").inc()
            raise ErpUnavailableError(f"ERP unreachable during {operation}: {exc}") from exc
        if response.status_code >= 500 or response.status_code == 429:
            ERP_REQUESTS.labels(operation, "unavailable").inc()
            raise ErpUnavailableError(f"ERP returned {response.status_code} during {operation}")
        ERP_REQUESTS.labels(operation, "ok" if response.is_success else f"http_{response.status_code}").inc()
        return response

    @staticmethod
    def _detail(response: httpx.Response) -> str:
        try:
            return str(response.json().get("detail", response.text))
        except ValueError:
            return response.text


class ErpClient(HttpErp):
    """SAP S/4HANA-shaped API (erp-mock)."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout: float = 10.0,
        transport: httpx.BaseTransport | None = None,
        attempts: int = 3,
        backoff_seconds: float = 0.5,
    ) -> None:
        super().__init__(base_url, {"X-API-Key": api_key}, timeout, transport, attempts, backoff_seconds)

    @classmethod
    def from_settings(cls, settings: Settings) -> ErpClient:
        return cls(settings.erp_base_url, settings.erp_api_key.get_secret_value(), settings.erp_timeout_seconds)

    def list_suppliers(self) -> list[Supplier]:
        response = self._call("list_suppliers", lambda: self._http.get("/api/suppliers"))
        if not response.is_success:
            raise ErpRejectedError(response.status_code, self._detail(response))
        return [_supplier(s) for s in response.json()["value"]]

    def get_supplier(self, erp_id: str) -> Supplier | None:
        response = self._call("get_supplier", lambda: self._http.get(f"/api/suppliers/{erp_id}"))
        if response.status_code == 404:
            return None
        if not response.is_success:
            raise ErpRejectedError(response.status_code, self._detail(response))
        return _supplier(response.json())

    def get_company(self) -> dict[str, Any]:
        response = self._call("get_company", lambda: self._http.get("/api/company"))
        if not response.is_success:
            raise ErpRejectedError(response.status_code, self._detail(response))
        return dict(response.json())

    def list_purchase_orders(self, supplier_id: str | None = None) -> list[PurchaseOrder]:
        params = {"supplier": supplier_id} if supplier_id else None
        response = self._call("list_purchase_orders", lambda: self._http.get("/api/purchase-orders", params=params))
        if not response.is_success:
            raise ErpRejectedError(response.status_code, self._detail(response))
        return [_purchase_order(po) for po in response.json()["value"]]

    def get_purchase_order(self, number: str) -> PurchaseOrder | None:
        response = self._call(
            "get_purchase_order", lambda: self._http.get(f"/api/purchase-orders/{quote(number, safe='')}")
        )
        if response.status_code == 404:
            return None
        if not response.is_success:
            raise ErpRejectedError(response.status_code, self._detail(response))
        return _purchase_order(response.json())

    def post_supplier_invoice(self, idempotency_key: str, payload: dict[str, Any]) -> PostingResult:
        """Posting is idempotent on `idempotency_key`, so a retry after a timeout cannot double-book."""
        response = self._call(
            "post_supplier_invoice",
            lambda: self._http.post(
                "/api/supplier-invoices", json=payload, headers={"Idempotency-Key": idempotency_key}
            ),
        )
        if not response.is_success:
            raise ErpRejectedError(response.status_code, self._detail(response))
        body = response.json()
        log.info("erp_invoice_posted", document=body["SupplierInvoice"], idempotency_key=idempotency_key)
        return PostingResult(document_number=str(body["SupplierInvoice"]), fiscal_year=str(body["FiscalYear"]))

    def ping(self) -> None:
        self._call("health", lambda: self._http.get("/health")).raise_for_status()


def build_erp_client(settings: Settings) -> Erp:
    if settings.erp_provider == "erpnext":
        from app.services.erpnext import ErpNextClient

        return ErpNextClient.from_settings(settings)
    return ErpClient.from_settings(settings)
