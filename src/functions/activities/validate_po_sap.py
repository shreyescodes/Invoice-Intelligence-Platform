"""Activity: validate the extracted invoice against SAP PO / vendor data.

TODO(phase 3):
1. Call the mock SAP service (src/mock_sap) for the PO number on the
   extracted invoice — GET /PurchaseOrders('{po_number}').
2. Also look up the vendor via GET /BusinessPartners — reference the
   real field shapes from SAP Business Accelerator Hub
   (api.sap.com — Business Partner API, Purchase Order API under the
   S/4HANA package) so your mock matches a real SAP OData response,
   not a shape you invented.
3. Do the 3-way match: PO quantity/price vs invoice quantity/price,
   flag mismatches beyond a tolerance. Return the match result plus
   which fields disagreed and by how much — score_anomaly.py needs
   these deltas, not just a pass/fail.
"""

from typing import Any


def validate_po_sap(extracted_invoice: dict[str, Any]) -> dict[str, Any]:
    raise NotImplementedError("Build this in phase 3 — see module docstring")
