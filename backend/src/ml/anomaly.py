"""Machine Learning anomaly scoring for invoices.

Uses an Isolation Forest to flag unusual invoices based on features
like amount, tax ratio, and whether it matches historical patterns for
the specific vendor.
"""

import os
from decimal import Decimal

import joblib
import numpy as np
from sklearn.ensemble import IsolationForest

MODEL_PATH = os.path.join(os.path.dirname(__file__), "isolation_forest.joblib")

class InvoiceAnomalyDetector:
    def __init__(self):
        # Isolation Forest: unsupervised anomaly detection
        # contamination=0.05 implies we expect 5% of invoices to be anomalous
        self.model = IsolationForest(
            n_estimators=100, 
            contamination=0.05,
            random_state=42
        )
        self._is_trained = False
        self._load_model()

    def _load_model(self):
        if os.path.exists(MODEL_PATH):
            self.model = joblib.load(MODEL_PATH)
            self._is_trained = True

    def _save_model(self):
        joblib.dump(self.model, MODEL_PATH)

    def _extract_features(self, vendor_id: str, subtotal: Decimal, tax_amount: Decimal, total_amount: Decimal) -> np.ndarray:
        # Features:
        # 1. Total amount (float)
        # 2. Tax ratio (tax / subtotal)
        # 3. Vendor encoding (simple hash for now, though one-hot is better for real ML)
        
        total_float = float(total_amount)
        sub_float = float(subtotal) if subtotal > 0 else 1.0
        tax_float = float(tax_amount)
        
        tax_ratio = tax_float / sub_float
        vendor_hash = float(hash(vendor_id) % 1000) / 1000.0
        
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
        self.model.fit(X)
        self._is_trained = True
        self._save_model()

    def score(self, vendor_id: str, subtotal: Decimal, tax_amount: Decimal, total_amount: Decimal) -> float:
        """
        Returns a normalized anomaly score between 0.0 and 1.0.
        0.0 = completely normal
        1.0 = highly anomalous
        """
        if not self._is_trained:
            # Fallback to heuristics if untrained
            if total_amount > Decimal("50000"):
                return 0.9  # High amount
            if tax_amount > subtotal:
                return 1.0  # Impossible tax
            return 0.1 # Normal

        X = self._extract_features(vendor_id, subtotal, tax_amount, total_amount)
        
        # decision_function returns negative values for anomalies, positive for normal
        raw_score = self.model.decision_function(X)[0]
        
        # Normalize roughly to 0-1 where 1 is anomalous
        # raw_score is usually between -0.5 and 0.5
        normalized = 0.5 - raw_score
        
        # Clip between 0 and 1
        return float(max(0.0, min(1.0, normalized)))

# Singleton instance
detector = InvoiceAnomalyDetector()
