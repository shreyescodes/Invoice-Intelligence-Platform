"""Train the invoice anomaly/duplicate-detection model, tracked in MLflow.

TODO(phase 5):
1. Pull historical invoices from the analytics warehouse (once phase 4
   has been populating it for a while — or generate synthetic training
   data with a few injected duplicates/price anomalies to start).
2. Engineer features: amount deviation from vendor's rolling average,
   days-since-last-invoice for that vendor, exact-duplicate flag
   (vendor_id, invoice_number, amount all match a prior invoice),
   SAP match delta from validate_po_sap.py.
3. Train something simple first — IsolationForest or a logistic
   regression on hand-labeled anomalies — before reaching for anything
   fancier. The point of this project is the platform around the
   model, not a leaderboard-chasing model.
4. Log the run with MLflow: params, metrics (precision/recall on a
   held-out set — false positives here mean the finance team ignores
   your alerts, so care about precision), and the model artifact.
5. Register the best run's model in the MLflow Model Registry, then
   (once you're touching real Azure ML) push it to the Azure ML model
   registry too — mlflow.azureml has a bridge for this, or export/
   import via MLmodel format. This is the "Exposure to ... MLflow, and
   Azure ML" line item, made concrete: track locally, register in both
   places, know the difference between the two registries.

Run with: python -m src.ml.train_anomaly_model
Then check http://localhost:5001 (the mlflow container) for the run.
"""

import mlflow

from src.core.config import get_settings


def train() -> None:
    settings = get_settings()
    mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
    mlflow.set_experiment("invoice-anomaly-detection")

    with mlflow.start_run():
        from decimal import Decimal
        historical_data = [
            {"vendor_id": "V001", "subtotal": Decimal("100"), "tax_amount": Decimal("10"), "total_amount": Decimal("110")},
            {"vendor_id": "V002", "subtotal": Decimal("200"), "tax_amount": Decimal("20"), "total_amount": Decimal("220")},
            {"vendor_id": "V003", "subtotal": Decimal("500"), "tax_amount": Decimal("50"), "total_amount": Decimal("550")},
            {"vendor_id": "V001", "subtotal": Decimal("100"), "tax_amount": Decimal("1000"), "total_amount": Decimal("1100")} # Anomaly
        ] * 10
        
        from src.ml.anomaly import detector
        detector.train(historical_data)
        
        print("Model trained and logged to MLflow successfully.")


if __name__ == "__main__":
    train()
