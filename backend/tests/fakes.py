"""Test doubles.

`FakeErp` serves the ERP API over an httpx MockTransport using the mock service's own store
(erp-mock/erp_mock), so the backend client is exercised against the same contract it uses in
docker-compose.
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

ERP_MOCK_DIR = Path(__file__).resolve().parents[2] / "erp-mock"
if str(ERP_MOCK_DIR) not in sys.path:
    sys.path.insert(0, str(ERP_MOCK_DIR))

from erp_mock.main import SEED_FILE, ErpStore, SupplierInvoiceIn  # noqa: E402
from fastapi import HTTPException  # noqa: E402


class FakeErp:
    def __init__(self) -> None:
        self.store = ErpStore(json.loads(SEED_FILE.read_text(encoding="utf-8")))
        self.unavailable = 0  # respond 503 to this many upcoming requests
        self.down = False
        self.requests: list[httpx.Request] = []
        self.transport = httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.down:
            raise httpx.ConnectError("connection refused", request=request)
        if self.unavailable > 0:
            self.unavailable -= 1
            return httpx.Response(503, json={"detail": "unavailable"})
        if request.headers.get("x-api-key") != "dev-erp-key":
            return httpx.Response(401, json={"detail": "bad key"})
        try:
            return self._route(request)
        except HTTPException as exc:
            return httpx.Response(exc.status_code, json={"detail": exc.detail})

    def _route(self, request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        suppliers = {"value": list(self.store.suppliers.values())}
        routes: list[tuple[str, str, Callable[..., httpx.Response]]] = [
            ("GET", r"/health", lambda _: httpx.Response(200, json={"status": "ok"})),
            ("GET", r"/api/company", lambda _: httpx.Response(200, json=self.store.company)),
            ("GET", r"/api/suppliers", lambda _: httpx.Response(200, json=suppliers)),
            ("GET", r"/api/suppliers/(?P<sid>[^/]+)", self._supplier),
            ("GET", r"/api/purchase-orders", self._purchase_orders),
            ("GET", r"/api/purchase-orders/(?P<po>[^/]+)", self._purchase_order),
            ("POST", r"/api/supplier-invoices", self._post),
        ]
        for verb, pattern, handler in routes:
            match = re.fullmatch(pattern, path)
            if verb == method and match:
                return handler(request, **match.groupdict())
        return httpx.Response(404, json={"detail": "not found"})

    def _supplier(self, _: httpx.Request, sid: str) -> httpx.Response:
        supplier = self.store.suppliers.get(sid)
        return httpx.Response(200, json=supplier) if supplier else httpx.Response(404, json={"detail": "nf"})

    def _purchase_orders(self, request: httpx.Request) -> httpx.Response:
        supplier = request.url.params.get("supplier")
        orders = [po for po in self.store.purchase_orders.values() if supplier in (None, po["Supplier"])]
        return httpx.Response(200, json={"value": orders})

    def _purchase_order(self, _: httpx.Request, po: str) -> httpx.Response:
        order = self.store.purchase_orders.get(po)
        return httpx.Response(200, json=order) if order else httpx.Response(404, json={"detail": "nf"})

    def _post(self, request: httpx.Request) -> httpx.Response:
        payload = SupplierInvoiceIn.model_validate_json(request.content)
        record, created = self.store.post_invoice(request.headers["idempotency-key"], payload)
        return httpx.Response(201 if created else 200, json=record)

    def posted_invoices(self) -> list[dict[str, Any]]:
        return list(self.store.invoices.values())


class FakeLLM:
    model = "fake-model"

    def __init__(self, replies: list[str] | Callable[[str, str], str]) -> None:
        self._replies = replies
        self.calls: list[tuple[str, str]] = []

    def complete(self, system: str, user: str, *, json_mode: bool = False) -> str:
        self.calls.append((system, user))
        if callable(self._replies):
            return self._replies(system, user)
        return self._replies.pop(0)
