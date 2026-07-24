"""Activity: post the approved invoice as a journal entry / SAP posting.

TODO(phase 3): POST to the mock SAP service's invoice-posting
endpoint. This is the activity where idempotency matters most — if
the Durable Functions runtime retries this activity after a transient
failure, make sure it doesn't create a duplicate posting. Two options:
pass a deterministic idempotency key (the invoice id) that the mock
service deduplicates on, or check-before-post.
"""

from typing import Any


def post_to_sap(extracted_invoice: dict[str, Any]) -> dict[str, Any]:
    raise NotImplementedError("Build this in phase 3 — see module docstring")
