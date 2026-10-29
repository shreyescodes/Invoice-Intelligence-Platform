"""Straight-through-processing policy: when may an invoice be approved without a human?"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.config import Settings
from app.models import CheckStatus, UserRole
from app.services.validation import CheckOutcome


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    auto_approve: bool
    reasons: list[str]


def evaluate_policy(
    checks: list[CheckOutcome],
    anomaly_score: float | None,
    total: Decimal | None,
    confidence: float,
    settings: Settings,
) -> PolicyDecision:
    """Auto-approve only when every check passed, the amount is within the auto-approval limit, the
    extraction is confident and the anomaly model sees nothing unusual. Anything else goes to a human,
    with every reason listed so the reviewer knows what to look at."""
    reasons = [c.message for c in checks if c.status is CheckStatus.FAIL]
    reasons += [c.message for c in checks if c.status is CheckStatus.WARN]
    if anomaly_score is not None and anomaly_score >= settings.anomaly_review_threshold:
        reasons.append(
            f"Anomaly score {anomaly_score:.2f} is above the review threshold ({settings.anomaly_review_threshold:.2f})"
        )
    if total is not None and total > settings.auto_approve_limit:
        reasons.append(f"Amount exceeds the auto-approval limit of {settings.auto_approve_limit:,.0f}")
    if confidence < settings.min_extraction_confidence:
        reasons.append(f"Extraction confidence {confidence:.0%} is below {settings.min_extraction_confidence:.0%}")
    return PolicyDecision(auto_approve=not reasons, reasons=reasons)


def approval_limit(role: UserRole, settings: Settings) -> Decimal | None:
    """Delegation of authority: the largest invoice a role may approve (None = unlimited)."""
    if role is UserRole.ADMIN:
        return None
    if role is UserRole.APPROVER:
        return settings.approver_limit
    return Decimal("0")
