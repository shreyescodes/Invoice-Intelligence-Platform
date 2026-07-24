"""Activity: score the invoice for duplicate / fraud risk.

TODO(phase 5, after src/ml/train_anomaly_model.py exists):
1. Load the registered model from the MLflow model registry
   (mlflow.sklearn.load_model("models:/invoice-anomaly/Production"))
   — or from the Azure ML model registry once you've pushed it there.
2. Build the same feature vector the model was trained on: amount
   deviation from that vendor's historical average, days since last
   invoice from this vendor, whether (vendor, invoice_number) already
   exists (exact duplicate), the SAP match deltas from
   validate_po_sap.py.
3. Return a 0-1 anomaly score. The orchestrator compares this against
   a threshold to decide whether to pause for human approval.

Cold-start note: a brand-new vendor has no history to compare against.
Decide explicitly what the score should be in that case (e.g. always
route new vendors to manual approval for their first N invoices)
rather than letting a NaN feature silently break scoring.
"""

from typing import Any


def score_anomaly(payload: dict[str, Any]) -> float:
    raise NotImplementedError("Build this in phase 5 — see module docstring")
