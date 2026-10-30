"""Prepare a fresh ERPNext site (deploy/erpnext) for the live tests and print the settings they need.

    uv run python -m tests.integration.erpnext_bootstrap --url http://localhost:8180 >> "$GITHUB_ENV"

Runs the setup wizard for an Indian company, issues an API key, and books what an AP clerk would find
in a real ERP: a supplier with GSTIN, address and payment terms, stock items, and two submitted
purchase orders with goods receipts (one fully received, one partially).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date, timedelta
from typing import Any
from urllib.parse import quote

import httpx

COMPANY = "Acme Manufacturing India Pvt Ltd"
ABBR = "AMI"
SUPPLIER = {
    "supplier_name": "Kaveri Industrial Components Ltd",
    "tax_id": "29AABCK4321P1Z9",
    "address_line1": "No. 42, Peenya Industrial Area",
    "city": "Bengaluru",
    "state": "Karnataka",
    "pincode": "560058",
}
ITEMS = {
    "HOSE-34": "Hydraulic hose assembly 3/4 in",
    "PROX-M18": "Inductive proximity sensor M18",
    "VALVE-12": "Solenoid valve 1/2 in 24V DC",
}
# (item, ordered, received, rate)
RECEIVED_PO = [("HOSE-34", 40, 40, 1450), ("PROX-M18", 10, 10, 2350)]
PARTIAL_PO = [("VALVE-12", 6, 4, 3200)]


class Site:
    def __init__(self, url: str) -> None:
        self.http = httpx.Client(base_url=url, timeout=300)

    def _ok(self, response: httpx.Response) -> dict[str, Any]:
        if not response.is_success:
            sys.exit(
                f"{response.request.method} {response.request.url} -> {response.status_code}\n{response.text[:4000]}"
            )
        return dict(response.json())

    def wait(self, timeout: float = 600) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                if self.http.get("/api/method/ping").json().get("message") == "pong":
                    return
            except (httpx.HTTPError, ValueError):
                pass
            time.sleep(5)
        sys.exit("ERPNext did not come up")

    def login(self) -> None:
        self._ok(self.http.post("/api/method/login", json={"usr": "Administrator", "pwd": "admin"}))

    def call(self, method: str, **data: Any) -> Any:
        return self._ok(self.http.post(f"/api/method/{method}", json=data)).get("message")

    def insert(self, doctype: str, doc: dict[str, Any]) -> dict[str, Any]:
        return dict(self._ok(self.http.post(f"/api/resource/{quote(doctype)}", json=doc))["data"])

    def update(self, doctype: str, name: str, values: dict[str, Any]) -> None:
        self._ok(self.http.put(f"/api/resource/{quote(doctype)}/{quote(name, safe='')}", json=values))

    def find(self, doctype: str, filters: list[list[Any]]) -> str:
        params = {"filters": json.dumps(filters), "limit_page_length": "1"}
        rows = self._ok(self.http.get(f"/api/resource/{quote(doctype)}", params=params))["data"]
        if not rows:
            sys.exit(f"no {doctype} matching {filters}")
        return str(rows[0]["name"])


def indian_fiscal_year(today: date) -> tuple[date, date]:
    start = date(today.year if today.month >= 4 else today.year - 1, 4, 1)
    return start, date(start.year + 1, 3, 31)


def purchase_order(site: Site, supplier: str, warehouse: str, lines: list[tuple[str, int, int, int]]) -> str:
    today = date.today()
    po = site.insert(
        "Purchase Order",
        {
            "supplier": supplier,
            "company": COMPANY,
            "transaction_date": (today - timedelta(days=20)).isoformat(),
            "schedule_date": (today - timedelta(days=10)).isoformat(),
            "set_warehouse": warehouse,
            "items": [
                {
                    "item_code": item,
                    "qty": ordered,
                    "rate": rate,
                    "uom": "Nos",
                    "conversion_factor": 1,
                    "warehouse": warehouse,
                    "schedule_date": (today - timedelta(days=10)).isoformat(),
                }
                for item, ordered, _, rate in lines
            ],
            "docstatus": 1,
        },
    )
    rows = {row["item_code"]: row["name"] for row in po["items"]}
    site.insert(
        "Purchase Receipt",
        {
            "supplier": supplier,
            "company": COMPANY,
            "posting_date": (today - timedelta(days=8)).isoformat(),
            "set_warehouse": warehouse,
            "items": [
                {
                    "item_code": item,
                    "qty": received,
                    "received_qty": received,
                    "rate": rate,
                    "uom": "Nos",
                    "conversion_factor": 1,
                    "warehouse": warehouse,
                    "purchase_order": po["name"],
                    "purchase_order_item": rows[item],
                }
                for item, _, received, rate in lines
            ],
            "docstatus": 1,
        },
    )
    return str(po["name"])


def bootstrap(url: str) -> dict[str, str]:
    site = Site(url)
    site.wait()
    site.login()

    fy_start, fy_end = indian_fiscal_year(date.today())
    site.call(
        "frappe.desk.page.setup_wizard.setup_wizard.setup_complete",
        args={
            "language": "English",
            "country": "India",
            "timezone": "Asia/Kolkata",
            "currency": "INR",
            "company_name": COMPANY,
            "company_abbr": ABBR,
            "chart_of_accounts": "Standard",
            "fy_start_date": fy_start.isoformat(),
            "fy_end_date": fy_end.isoformat(),
        },
    )
    keys = site.call("frappe.core.doctype.user.user.generate_keys", user="Administrator")

    duties = site.find("Account", [["company", "=", COMPANY], ["account_name", "=", "Duties and Taxes"]])
    tax_account = site.insert(
        "Account",
        {"account_name": "Input GST", "parent_account": duties, "company": COMPANY, "account_type": "Tax"},
    )["name"]
    warehouse = site.find("Warehouse", [["company", "=", COMPANY], ["warehouse_name", "=", "Stores"]])

    site.insert("Supplier Group", {"supplier_group_name": "Components", "parent_supplier_group": "All Supplier Groups"})
    site.insert("Item Group", {"item_group_name": "Components", "parent_item_group": "All Item Groups"})
    terms = {"invoice_portion": 100, "due_date_based_on": "Day(s) after invoice date", "credit_days": 45}
    site.insert("Payment Term", {"payment_term_name": "Net 45", **terms})
    site.insert("Payment Terms Template", {"template_name": "Net 45", "terms": [{"payment_term": "Net 45", **terms}]})

    supplier = site.insert(
        "Supplier",
        {
            "supplier_name": SUPPLIER["supplier_name"],
            "supplier_group": "Components",
            "supplier_type": "Company",
            "country": "India",
            "tax_id": SUPPLIER["tax_id"],
            "payment_terms": "Net 45",
            "default_currency": "INR",
        },
    )["name"]
    address = site.insert(
        "Address",
        {
            "address_title": SUPPLIER["supplier_name"],
            "address_type": "Billing",
            "address_line1": SUPPLIER["address_line1"],
            "city": SUPPLIER["city"],
            "state": SUPPLIER["state"],
            "pincode": SUPPLIER["pincode"],
            "country": "India",
            "is_primary_address": 1,
            "links": [{"link_doctype": "Supplier", "link_name": supplier}],
        },
    )["name"]
    site.update("Supplier", supplier, {"supplier_primary_address": address})

    for code, name in ITEMS.items():
        site.insert(
            "Item",
            {"item_code": code, "item_name": name, "item_group": "Components", "stock_uom": "Nos", "is_stock_item": 1},
        )

    return {
        "ERPNEXT_URL": url,
        "ERPNEXT_API_KEY": keys["api_key"],
        "ERPNEXT_API_SECRET": keys["api_secret"],
        "ERPNEXT_COMPANY": COMPANY,
        "ERPNEXT_TAX_ACCOUNT": tax_account,
        "ERPNEXT_SUPPLIER": supplier,
        "ERPNEXT_PO_RECEIVED": purchase_order(site, supplier, warehouse, RECEIVED_PO),
        "ERPNEXT_PO_PARTIAL": purchase_order(site, supplier, warehouse, PARTIAL_PO),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8180")
    for key, value in bootstrap(parser.parse_args().url).items():
        sys.stdout.write(f"{key}={value}\n")


if __name__ == "__main__":
    main()
