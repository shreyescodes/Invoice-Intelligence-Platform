"""Client for a real ERPNext site (v15/v16) over its REST API.

| Platform | ERPNext |
|---|---|
| `Supplier.erp_id` | `Supplier.name`; `tax_id` holds the GSTIN / VAT number |
| `PurchaseOrderItem.item` | the Purchase Order Item row name (`po_detail`) |
| received quantity | `Purchase Order Item.received_qty`, maintained by submitted Purchase Receipts |
| invoiced quantity | quantity on submitted Purchase Invoice Items that point at the row |
| supplier invoice | a Purchase Invoice, submitted on insert; the idempotency key is kept in `remarks` |
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import date
from decimal import Decimal
from functools import cached_property
from typing import Any
from urllib.parse import quote

import httpx

from app.config import Settings
from app.observability import get_logger
from app.services.erp import ErpRejectedError, HttpErp, PostingResult, PurchaseOrder, PurchaseOrderItem, Supplier

log = get_logger(__name__)

_TAGS = re.compile(r"<[^>]+>")
_RATE = Decimal("0.000001")


def _dec(value: Any) -> Decimal:
    return Decimal(str(value or 0))


class ErpNextClient(HttpErp):
    def __init__(
        self,
        base_url: str,
        api_key: str,
        api_secret: str,
        *,
        tax_account: str,
        company: str | None = None,
        timeout: float = 10.0,
        transport: httpx.BaseTransport | None = None,
        attempts: int = 3,
        backoff_seconds: float = 0.5,
    ) -> None:
        headers = {"Authorization": f"token {api_key}:{api_secret}"}
        super().__init__(base_url, headers, timeout, transport, attempts, backoff_seconds)
        self.tax_account = tax_account
        self._company_name = company
        self._credit_days_by_template: dict[str, int] = {}

    @classmethod
    def from_settings(cls, settings: Settings) -> ErpNextClient:
        if settings.erp_api_secret is None or not settings.erpnext_tax_account:
            raise ValueError("ERP_PROVIDER=erpnext needs ERP_API_SECRET and ERPNEXT_TAX_ACCOUNT")
        return cls(
            settings.erp_base_url,
            settings.erp_api_key.get_secret_value(),
            settings.erp_api_secret.get_secret_value(),
            tax_account=settings.erpnext_tax_account,
            company=settings.erpnext_company,
            timeout=settings.erp_timeout_seconds,
        )

    # --- REST plumbing -----------------------------------------------------------

    @staticmethod
    def _detail(response: httpx.Response) -> str:
        """Frappe reports validation errors in `_server_messages`, a JSON list of JSON objects."""
        try:
            body = response.json()
        except ValueError:
            return response.text[:500]
        messages: list[str] = []
        for item in json.loads(body.get("_server_messages") or "[]"):
            try:
                messages.append(str(json.loads(item).get("message", item)))
            except (ValueError, AttributeError):
                messages.append(str(item))
        if not messages:
            messages.append(str(body.get("exception") or body.get("message") or response.text[:500]))
        return _TAGS.sub("", "; ".join(messages)).strip()

    def _json(self, response: httpx.Response) -> dict[str, Any]:
        if not response.is_success:
            raise ErpRejectedError(response.status_code, self._detail(response))
        return dict(response.json())

    @staticmethod
    def _path(doctype: str, name: str | None = None) -> str:
        path = f"/api/resource/{quote(doctype)}"
        return f"{path}/{quote(name, safe='')}" if name is not None else path

    def _list(
        self,
        operation: str,
        doctype: str,
        fields: list[str],
        filters: list[list[Any]],
        *,
        parent: str | None = None,
        limit: int = 0,
    ) -> list[dict[str, Any]]:
        params = {"fields": json.dumps(fields), "filters": json.dumps(filters), "limit_page_length": str(limit)}
        if parent:
            params["parent"] = parent
        response = self._call(operation, lambda: self._http.get(self._path(doctype), params=params))
        return list(self._json(response)["data"])

    def _doc(self, operation: str, doctype: str, name: str) -> dict[str, Any] | None:
        response = self._call(operation, lambda: self._http.get(self._path(doctype, name)))
        if response.status_code == 404:
            return None
        return dict(self._json(response)["data"])

    # --- Master data -------------------------------------------------------------

    @cached_property
    def company(self) -> dict[str, Any]:
        name = self._company_name
        if name is None:
            names = [row["name"] for row in self._list("get_company", "Company", ["name"], [])]
            if len(names) != 1:
                raise ErpRejectedError(400, f"the site has {len(names)} companies; set ERPNEXT_COMPANY")
            name = names[0]
        doc = self._doc("get_company", "Company", name)
        if doc is None:
            raise ErpRejectedError(404, f"Company {name} not found")
        return doc

    def get_company(self) -> dict[str, Any]:
        return {
            "CompanyName": self.company["company_name"],
            "Address": [],
            "TaxNumber": self.company.get("tax_id"),
            "Currency": self.company["default_currency"],
        }

    def _credit_days(self, template: str | None) -> int:
        if not template:
            return 30
        if template not in self._credit_days_by_template:
            doc = self._doc("get_payment_terms", "Payment Terms Template", template) or {}
            days = [int(term.get("credit_days") or 0) for term in doc.get("terms", [])]
            self._credit_days_by_template[template] = max(days, default=30)
        return self._credit_days_by_template[template]

    def _supplier(self, raw: dict[str, Any]) -> Supplier:
        address_name = raw.get("supplier_primary_address")
        address = (self._doc("get_address", "Address", address_name) if address_name else None) or {}
        return Supplier(
            erp_id=str(raw["name"]),
            name=raw["supplier_name"],
            tax_id=raw.get("tax_id") or None,
            city=address.get("city"),
            currency=raw.get("default_currency") or self.company["default_currency"],
            payment_terms_days=self._credit_days(raw.get("payment_terms")),
            street=address.get("address_line1"),
            postal_code=address.get("pincode"),
            region=address.get("state"),
        )

    def list_suppliers(self) -> list[Supplier]:
        fields = ["name", "supplier_name", "tax_id", "default_currency", "payment_terms", "supplier_primary_address"]
        return [self._supplier(row) for row in self._list("list_suppliers", "Supplier", fields, [["disabled", "=", 0]])]

    def get_supplier(self, erp_id: str) -> Supplier | None:
        doc = self._doc("get_supplier", "Supplier", erp_id)
        return self._supplier(doc) if doc else None

    # --- Purchase orders -----------------------------------------------------------

    def _submitted_po(self, number: str) -> dict[str, Any] | None:
        doc = self._doc("get_purchase_order", "Purchase Order", number)
        return doc if doc and doc.get("docstatus") == 1 else None

    def _invoiced_quantities(self, po_number: str) -> dict[str, Decimal]:
        rows = self._list(
            "get_invoiced_quantities",
            "Purchase Invoice Item",
            ["po_detail", "qty"],
            [["purchase_order", "=", po_number], ["docstatus", "=", 1]],
            parent="Purchase Invoice",
        )
        invoiced: dict[str, Decimal] = defaultdict(Decimal)
        for row in rows:
            invoiced[row["po_detail"]] += _dec(row["qty"])
        return invoiced

    def _purchase_order(self, doc: dict[str, Any]) -> PurchaseOrder:
        invoiced = self._invoiced_quantities(doc["name"])
        return PurchaseOrder(
            number=doc["name"],
            supplier_id=doc["supplier"],
            currency=doc["currency"],
            order_date=date.fromisoformat(doc["transaction_date"]) if doc.get("transaction_date") else None,
            items=tuple(
                PurchaseOrderItem(
                    item=row["name"],
                    description=row.get("item_name") or _TAGS.sub("", row.get("description") or ""),
                    quantity=_dec(row["qty"]),
                    unit=row.get("uom") or "Nos",
                    net_price=_dec(row["rate"]),
                    received_quantity=_dec(row.get("received_qty")),
                    invoiced_quantity=invoiced.get(row["name"], Decimal(0)),
                )
                for row in doc.get("items", [])
            ),
        )

    def list_purchase_orders(self, supplier_id: str | None = None) -> list[PurchaseOrder]:
        filters: list[list[Any]] = [["docstatus", "=", 1]]
        if supplier_id:
            filters.append(["supplier", "=", supplier_id])
        names = [row["name"] for row in self._list("list_purchase_orders", "Purchase Order", ["name"], filters)]
        return [self._purchase_order(doc) for name in names if (doc := self._submitted_po(name))]

    def get_purchase_order(self, number: str) -> PurchaseOrder | None:
        doc = self._submitted_po(number)
        return self._purchase_order(doc) if doc else None

    # --- Posting -------------------------------------------------------------------

    def _posting_result(self, name: str, posting_date: str) -> PostingResult:
        years = self._list(
            "get_fiscal_year",
            "Fiscal Year",
            ["name"],
            [["year_start_date", "<=", posting_date], ["year_end_date", ">=", posting_date]],
            limit=1,
        )
        return PostingResult(document_number=name, fiscal_year=years[0]["name"] if years else posting_date[:4])

    def _purchase_invoice(self, marker: str, payload: dict[str, Any]) -> dict[str, Any]:
        po_number = payload.get("PurchaseOrder")
        po = self._submitted_po(po_number) if po_number else None
        if po is None:
            raise ErpRejectedError(422, f"{po_number!r} is not a submitted purchase order")
        rows = {row["name"]: row for row in po["items"]}
        items: list[dict[str, Any]] = []
        net = Decimal(0)
        for line in payload["Items"]:
            row = rows.get(line["PurchaseOrderItem"])
            if row is None:
                raise ErpRejectedError(422, f"purchase order {po_number} has no item {line['PurchaseOrderItem']}")
            quantity, amount = Decimal(line["Quantity"]), Decimal(line["Amount"])
            net += amount
            items.append(
                {
                    "item_code": row["item_code"],
                    "qty": float(quantity),
                    "rate": float((amount / quantity).quantize(_RATE)),
                    "uom": row["uom"],
                    "conversion_factor": row.get("conversion_factor") or 1,
                    "purchase_order": po["name"],
                    "po_detail": row["name"],
                }
            )
        tax = Decimal(payload["InvoiceGrossAmount"]) - net
        if tax < 0:
            raise ErpRejectedError(422, f"invoice total is {abs(tax)} below the sum of its lines")
        taxes = [
            {
                "charge_type": "Actual",
                "account_head": self.tax_account,
                "description": "Tax as invoiced",
                "tax_amount": float(tax),
                "category": "Total",
                "add_deduct_tax": "Add",
            }
        ]
        return {
            "supplier": payload["Supplier"],
            "company": po["company"],
            "bill_no": payload.get("SupplierInvoiceIDByInvcgParty"),
            "bill_date": payload.get("DocumentDate"),
            "currency": payload.get("DocumentCurrency") or po["currency"],
            "conversion_rate": po.get("conversion_rate") or 1,
            "items": items,
            "taxes": taxes if tax > 0 else [],
            "disable_rounded_total": 1,
            "remarks": f"Posted by Invoice Intelligence Platform ({marker})",
            "docstatus": 1,
        }

    def post_supplier_invoice(self, idempotency_key: str, payload: dict[str, Any]) -> PostingResult:
        """Looks for an invoice already posted under the key first, so a retry cannot double-book.
        The job queue runs one posting per invoice at a time, which keeps the check-then-insert safe."""
        marker = f"iip:{idempotency_key}"
        existing = self._list(
            "find_supplier_invoice",
            "Purchase Invoice",
            ["name", "posting_date"],
            [["remarks", "like", f"%{marker}%"], ["docstatus", "=", 1]],
            limit=1,
        )
        if existing:
            log.info("erp_invoice_already_posted", document=existing[0]["name"], idempotency_key=idempotency_key)
            return self._posting_result(existing[0]["name"], existing[0]["posting_date"])
        body = self._purchase_invoice(marker, payload)
        response = self._call(
            "post_supplier_invoice", lambda: self._http.post(self._path("Purchase Invoice"), json=body)
        )
        created = self._json(response)["data"]
        if abs(_dec(created.get("grand_total")) - Decimal(payload["InvoiceGrossAmount"])) > Decimal("0.01"):
            log.warning(
                "erp_invoice_total_differs",
                document=created["name"],
                erp_total=str(created.get("grand_total")),
                invoice_total=payload["InvoiceGrossAmount"],
            )
        log.info("erp_invoice_posted", document=created["name"], idempotency_key=idempotency_key)
        return self._posting_result(created["name"], created["posting_date"])

    def ping(self) -> None:
        self._json(self._call("health", lambda: self._http.get("/api/method/ping")))
