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
from sklearn.ensemble import IsolationForest

from src.core.config import get_settings


def train() -> None:
    settings = get_settings()
    mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
    mlflow.set_experiment("invoice-anomaly-detection")

    with mlflow.start_run():
        # TODO: replace with real feature matrix from the warehouse
        raise NotImplementedError("Build feature loading + training — see module docstring")

        # Sketch of what the rest looks like once features exist:
        # model = IsolationForest(contamination=0.05, random_state=42)
        # model.fit(X_train)
        # mlflow.log_param("contamination", 0.05)
        # mlflow.log_metric("precision_at_threshold", precision)
        # mlflow.sklearn.log_model(model, "model", registered_model_name="invoice-anomaly")


if __name__ == "__main__":
    train()
