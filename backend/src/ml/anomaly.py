"""Machine Learning anomaly scoring for invoices.

Uses an Isolation Forest to flag unusual invoices based on features
like amount, tax ratio, and whether it matches historical patterns for
the specific vendor.
"""

import hashlib
import io
import logging
from decimal import Decimal

import joblib  # type: ignore[import-untyped]
import numpy as np
from sklearn.linear_model import SGDOneClassSVM  # type: ignore[import-untyped]

from src.core.db import get_blob_service_client

logger = logging.getLogger(__name__)

class InvoiceAnomalyDetector:
    def __init__(self):
        # SGDOneClassSVM: online unsupervised anomaly detection
        # nu=0.05 implies we expect 5% of invoices to be anomalous
        self.model = SGDOneClassSVM(
            nu=0.05,
            random_state=42
        )
        self._is_trained = False
        self._model_loaded = False

    def _get_blob_client(self):
        blob_service = get_blob_service_client()
        container_client = blob_service.get_container_client("ml-models")
        if not container_client.exists():
            container_client.create_container()
        return container_client.get_blob_client("isolation_forest.joblib")

    def _load_model(self):
        if self._model_loaded:
            return
            
        self._model_loaded = True
        try:
            blob_client = self._get_blob_client()
            if blob_client.exists():
                stream = blob_client.download_blob().readall()
                self.model = joblib.load(io.BytesIO(stream))
                self._is_trained = True
                logger.info("Successfully loaded ML model from Blob Storage.")
            else:
                logger.info("No saved ML model found in Blob Storage. Using fallback heuristics.")
        except Exception as e:
            logger.warning(f"Failed to load ML model from Blob Storage: {e}")

    def _save_model(self):
        try:
            blob_client = self._get_blob_client()
            stream = io.BytesIO()
            joblib.dump(self.model, stream)
            stream.seek(0)
            blob_client.upload_blob(stream, overwrite=True)
            logger.info("Successfully saved trained ML model to Blob Storage.")
        except Exception as e:
            logger.error(f"Failed to save ML model to Blob Storage: {e}")

    def _extract_features(self, vendor_id: str, subtotal: Decimal, tax_amount: Decimal, total_amount: Decimal) -> np.ndarray:
        # Features:
        # 1. Total amount (float)
        # 2. Tax ratio (tax / subtotal)
        # 3. Vendor encoding (deterministic hash)
        
        total_float = float(total_amount)
        sub_float = float(subtotal) if subtotal > 0 else 1.0
        tax_float = float(tax_amount)
        
        tax_ratio = tax_float / sub_float
        
        # Deterministic hashing instead of Python's built-in randomized hash()
        vendor_hash_int = int(hashlib.sha256(vendor_id.encode("utf-8")).hexdigest(), 16)
        vendor_hash = float(vendor_hash_int % 1000) / 1000.0
        
        return np.array([[total_float, tax_ratio, vendor_hash]])

    def train(self, historical_data: list[dict]):
        """Train the model on a list of historical invoice dictionaries."""
        if not historical_data:
            return
            
        features = []
        for inv in historical_data:
            f = self._extract_features(
                inv.get("vendor_id", ""),
                inv.get("subtotal", Decimal("0")),
                inv.get("tax_amount", Decimal("0")),
                inv.get("total_amount", Decimal("0"))
            )
            features.append(f[0])
            
        X = np.array(features)
        self.model.partial_fit(X)
        self._is_trained = True
        self._save_model()

        import mlflow
        if mlflow.active_run():
            mlflow.log_param("nu", self.model.nu)
            mlflow.log_metric("training_samples", len(X))
            mlflow.sklearn.log_model(self.model, "model", registered_model_name="invoice-anomaly")

    def score(self, vendor_id: str, subtotal: Decimal, tax_amount: Decimal, total_amount: Decimal) -> float:
        """
        Returns a normalized anomaly score between 0.0 and 1.0.
        0.0 = completely normal
        1.0 = highly anomalous
        """
        if not self._is_trained:
            self._load_model()
            
        if not self._is_trained:
            # Fallback to heuristics if untrained and no model found in storage
            if total_amount > Decimal("50000"):
                return 0.9  # High amount
            if tax_amount > subtotal:
                return 1.0  # Impossible tax
            return 0.1 # Normal

        X = self._extract_features(vendor_id, subtotal, tax_amount, total_amount)
        
        # decision_function returns positive for normal, negative for anomalies
        raw_score = self.model.decision_function(X)[0]
        
        # Normalize roughly to 0-1 where 1 is anomalous. 
        # A negative raw_score means anomaly. If it's -10, normalized is high. If it's +10, normalized is 0.
        import math
        clipped_score = max(min(raw_score, 100.0), -100.0)
        # Sigmoid inversion: positive (normal) -> ~0, negative (anomaly) -> ~1
        normalized = 1.0 / (1.0 + math.exp(clipped_score))
        
        # Clip between 0 and 1
        return float(max(0.0, min(1.0, normalized)))

# Singleton instance
detector = InvoiceAnomalyDetector()
