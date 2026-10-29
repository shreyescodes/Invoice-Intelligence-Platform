"""Invoice anomaly scoring.

Features are computed relative to the vendor's own history (amount vs. its median, tax rate vs. its
usual rate, gap since its previous invoice), so a single unsupervised model works across vendors of
very different sizes. An IsolationForest scores the feature vector; the raw score is calibrated to
0-1 so that 0.5 sits on the model's contamination boundary. Reviewers see plain-language reasons
derived from the same features, never just a number.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.metrics import precision_score, recall_score, roc_auc_score

from app.observability import get_logger

log = get_logger(__name__)

MODEL_VERSION = "iforest-v1"
FEATURE_NAMES = (
    "log_amount",
    "amount_ratio_log",
    "amount_robust_z",
    "tax_rate",
    "tax_rate_delta",
    "days_since_last_log",
    "round_amount",
    "line_count",
)
HISTORY_LIMIT = 24
_NO_HISTORY_GAP_DAYS = 30.0


@dataclass(frozen=True, slots=True)
class HistoricalInvoice:
    invoice_date: date
    total: float
    tax_rate: float


@dataclass(frozen=True, slots=True)
class InvoiceFeatures:
    values: tuple[float, ...]
    vendor_median: float | None
    vendor_tax_rate: float | None
    days_since_last: float | None
    history_size: int

    def as_dict(self) -> dict[str, float]:
        return dict(zip(FEATURE_NAMES, self.values, strict=True))


def build_features(
    total: Decimal | float,
    subtotal: Decimal | float | None,
    tax: Decimal | float | None,
    invoice_date: date,
    line_count: int,
    history: list[HistoricalInvoice],
) -> InvoiceFeatures:
    total_f = float(total)
    subtotal_f = float(subtotal) if subtotal else total_f
    tax_rate = float(tax) / subtotal_f if tax is not None and subtotal_f > 0 else 0.0

    prior = [h for h in history if h.invoice_date <= invoice_date][:HISTORY_LIMIT]
    median: float | None = None
    usual_tax: float | None = None
    gap: float | None = None
    ratio_log = robust_z = tax_delta = 0.0
    if prior:
        amounts = np.array([h.total for h in prior])
        median = float(np.median(amounts))
        mad = float(np.median(np.abs(amounts - median))) * 1.4826
        ratio_log = math.log(max(total_f, 1.0) / max(median, 1.0))
        robust_z = float(np.clip((total_f - median) / max(mad, 0.05 * median, 1.0), -10, 10))
        usual_tax = float(np.median([h.tax_rate for h in prior]))
        tax_delta = abs(tax_rate - usual_tax)
        gap = float((invoice_date - max(h.invoice_date for h in prior)).days)

    round_amount = 1.0 if total_f >= 10_000 and total_f % 1000 == 0 else 0.0
    values = (
        math.log1p(max(total_f, 0.0)),
        ratio_log,
        robust_z,
        tax_rate,
        tax_delta,
        math.log1p(max(gap if gap is not None else _NO_HISTORY_GAP_DAYS, 0.0)),
        round_amount,
        float(line_count),
    )
    return InvoiceFeatures(values, median, usual_tax, gap, len(prior))


UNEXPLAINED_REASON = "Unusual combination of amount, tax rate and timing for this vendor"


def explain(features: InvoiceFeatures, score: float | None = None, threshold: float = 0.5) -> list[str]:
    """Human-readable drivers, most significant first. A flagged score always gets at least one reason."""
    f = features.as_dict()
    reasons: list[tuple[float, str]] = []
    if features.history_size == 0:
        reasons.append((0.5, "First invoice from this vendor - no history to compare against"))
    if features.vendor_median:
        ratio = math.exp(f["amount_ratio_log"])
        if ratio >= 2.5:
            reasons.append((ratio, f"Amount is {ratio:.1f}x this vendor's median of {features.vendor_median:,.0f}"))
        elif ratio <= 0.4:
            reasons.append((1 / ratio, f"Amount is unusually low ({ratio:.0%} of the vendor median)"))
    if features.vendor_tax_rate is not None and f["tax_rate_delta"] > 0.015:
        reasons.append(
            (
                f["tax_rate_delta"] * 100,
                f"Tax rate {f['tax_rate']:.1%} differs from this vendor's usual {features.vendor_tax_rate:.1%}",
            )
        )
    if features.days_since_last is not None and features.days_since_last <= 3 and features.history_size >= 3:
        reasons.append((3.0, f"Second invoice from this vendor within {features.days_since_last:.0f} day(s)"))
    if f["round_amount"]:
        reasons.append((1.0, "Total is a round number"))
    ordered = [text for _, text in sorted(reasons, key=lambda r: r[0], reverse=True)]
    if not ordered and score is not None and score >= threshold:
        ordered.append(UNEXPLAINED_REASON)
    return ordered


@dataclass(slots=True)
class ModelMetadata:
    version: str
    trained_at: str
    training_rows: int
    contamination: float
    threshold_raw: float
    scale: float
    feature_names: list[str]
    evaluation: dict[str, float] = field(default_factory=dict)
    source: str = "synthetic"


class AnomalyModel:
    def __init__(self, estimator: IsolationForest, metadata: ModelMetadata) -> None:
        self.estimator = estimator
        self.metadata = metadata

    @property
    def version(self) -> str:
        return self.metadata.version

    def raw_scores(self, matrix: np.ndarray) -> np.ndarray:
        return np.asarray(-self.estimator.score_samples(matrix))  # higher = more anomalous

    def score_matrix(self, matrix: np.ndarray) -> np.ndarray:
        z = (self.raw_scores(matrix) - self.metadata.threshold_raw) / self.metadata.scale
        return np.asarray(1.0 / (1.0 + np.exp(-np.clip(z, -30, 30))))

    def score(self, features: InvoiceFeatures) -> float:
        return round(float(self.score_matrix(np.array([features.values]))[0]), 4)

    def save(self, directory: Path) -> Path:
        """Write atomically: several processes (seed, worker replicas) may train on first start."""
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{self.metadata.version}.joblib"
        suffix = f".{os.getpid()}.tmp"
        model_tmp = path.with_name(path.name + suffix)
        meta_tmp = path.with_suffix(".json" + suffix)
        joblib.dump(self.estimator, model_tmp)
        meta_tmp.write_text(json.dumps(asdict(self.metadata), indent=2), encoding="utf-8")
        os.replace(meta_tmp, path.with_suffix(".json"))
        os.replace(model_tmp, path)
        return path

    @classmethod
    def load(cls, path: Path) -> AnomalyModel:
        metadata = ModelMetadata(**json.loads(path.with_suffix(".json").read_text(encoding="utf-8")))
        if tuple(metadata.feature_names) != FEATURE_NAMES:
            raise ValueError(f"model {path} was trained on a different feature set")
        return cls(joblib.load(path), metadata)


def fit(
    matrix: np.ndarray,
    *,
    contamination: float = 0.03,
    seed: int = 7,
    source: str = "synthetic",
    n_estimators: int = 300,
) -> AnomalyModel:
    estimator = IsolationForest(n_estimators=n_estimators, contamination=contamination, random_state=seed, n_jobs=1)
    estimator.fit(matrix)
    raw = -estimator.score_samples(matrix)
    threshold = float(-estimator.offset_)
    # Map the median training invoice to ~0.1 and the contamination boundary to 0.5.
    scale = max((threshold - float(np.median(raw))) / math.log(9), 1e-3)
    metadata = ModelMetadata(
        version=MODEL_VERSION,
        trained_at=datetime.now(UTC).isoformat(timespec="seconds"),
        training_rows=int(matrix.shape[0]),
        contamination=contamination,
        threshold_raw=threshold,
        scale=scale,
        feature_names=list(FEATURE_NAMES),
        source=source,
    )
    return AnomalyModel(estimator, metadata)


def evaluate(model: AnomalyModel, matrix: np.ndarray, labels: np.ndarray, threshold: float = 0.5) -> dict[str, float]:
    scores = model.score_matrix(matrix)
    predicted = scores >= threshold
    return {
        "precision": round(float(precision_score(labels, predicted, zero_division=0)), 3),
        "recall": round(float(recall_score(labels, predicted, zero_division=0)), 3),
        "roc_auc": round(float(roc_auc_score(labels, scores)), 3),
        "rows": float(len(labels)),
        "anomaly_rate": round(float(labels.mean()), 3),
    }


# --- Synthetic training data ---------------------------------------------------------------------


def synthetic_dataset(
    n_vendors: int = 60, invoices_per_vendor: int = 30, anomaly_rate: float = 0.04, seed: int = 11
) -> tuple[np.ndarray, np.ndarray]:
    """Invoice streams for synthetic vendors with a known share of injected anomalies.

    Each vendor has its own typical amount, tax slab and billing cadence. Anomalies are the patterns
    AP teams care about: inflated amounts, wrong tax rates, rapid re-billing and round-sum invoices.
    """
    rng = np.random.default_rng(seed)
    rows: list[tuple[float, ...]] = []
    labels: list[int] = []
    slabs = (0.05, 0.12, 0.18, 0.18, 0.18, 0.28)
    start = date(2024, 1, 1)
    for _ in range(n_vendors):
        base = float(rng.lognormal(mean=10.8, sigma=1.1))
        spread = float(rng.uniform(0.08, 0.35))
        tax_rate = float(rng.choice(slabs))
        cadence = int(rng.integers(7, 35))
        lines = int(rng.integers(1, 5))
        history: list[HistoricalInvoice] = []
        current = start + timedelta(days=int(rng.integers(0, 20)))
        for _ in range(invoices_per_vendor):
            current += timedelta(days=max(1, int(rng.normal(cadence, cadence * 0.2))))
            subtotal = round(base * float(rng.lognormal(0, spread)), 2)
            rate = tax_rate
            invoice_date = current
            line_count = max(1, lines + int(rng.integers(-1, 2)))
            anomalous = rng.random() < anomaly_rate and len(history) >= 4
            if anomalous:
                kind = rng.integers(0, 4)
                if kind == 0:
                    subtotal *= float(rng.uniform(4, 12))
                elif kind == 1:
                    rate = float(rng.choice([s for s in (0.0, 0.05, 0.12, 0.18, 0.28) if abs(s - tax_rate) > 0.05]))
                elif kind == 2:
                    invoice_date = history[0].invoice_date + timedelta(days=int(rng.integers(0, 2)))
                    subtotal *= float(rng.uniform(1.5, 3))
                else:
                    subtotal = round(subtotal * float(rng.uniform(2, 4)), -4) or 10_000.0
            tax = round(subtotal * rate, 2)
            total = subtotal + tax
            features = build_features(total, subtotal, tax, invoice_date, line_count, history)
            rows.append(features.values)
            labels.append(int(anomalous))
            if not anomalous:
                history.insert(0, HistoricalInvoice(invoice_date, total, rate))
    return np.array(rows), np.array(labels)


def train_default_model(seed: int = 7) -> AnomalyModel:
    train_x, _ = synthetic_dataset(seed=seed + 4)
    model = fit(train_x, seed=seed)
    test_x, test_y = synthetic_dataset(n_vendors=40, seed=seed + 99, anomaly_rate=0.06)
    model.metadata.evaluation = evaluate(model, test_x, test_y)
    return model


def load_or_train(model_dir: Path) -> AnomalyModel:
    path = model_dir / f"{MODEL_VERSION}.joblib"
    if path.exists():
        try:
            return AnomalyModel.load(path)
        except (ValueError, OSError, KeyError, TypeError) as exc:
            log.warning("anomaly_model_unloadable", path=str(path), error=str(exc))
    model = train_default_model()
    model.save(model_dir)
    log.info("anomaly_model_trained", path=str(path), **model.metadata.evaluation)
    return model


def metadata_dict(model: AnomalyModel) -> dict[str, Any]:
    return asdict(model.metadata)


def read_metadata(model_dir: Path) -> dict[str, Any] | None:
    """Model metadata without loading the estimator (the API only displays it)."""
    path = model_dir / f"{MODEL_VERSION}.json"
    try:
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data
