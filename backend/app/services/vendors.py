"""Vendor master replication from the ERP and matching of extracted vendors against it."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from rapidfuzz import fuzz, process
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import utcnow
from app.models import Vendor
from app.observability import get_logger
from app.services.erp import Erp

log = get_logger(__name__)

NAME_MATCH_THRESHOLD = 90
_LEGAL_SUFFIXES = re.compile(r"\b(?:pvt|private|ltd|limited|llp|inc|llc|co|company|corp|corporation)\b\.?", re.I)


def normalize_tax_id(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = re.sub(r"[^A-Za-z0-9]", "", value).upper()
    return cleaned or None


def normalize_name(value: str) -> str:
    return re.sub(r"\s+", " ", _LEGAL_SUFFIXES.sub(" ", value.replace("&", " and "))).strip().lower()


@dataclass(frozen=True, slots=True)
class VendorMatch:
    vendor: Vendor | None
    method: Literal["tax_id", "name"] | None
    score: float = 0.0


def match_vendor(session: Session, name: str | None, tax_id: str | None) -> VendorMatch:
    normalized_tax_id = normalize_tax_id(tax_id)
    if normalized_tax_id:
        vendor = session.scalar(select(Vendor).where(Vendor.tax_id == normalized_tax_id, Vendor.is_active))
        if vendor is not None:
            return VendorMatch(vendor, "tax_id", 100.0)
    if name:
        vendors = list(session.scalars(select(Vendor).where(Vendor.is_active)))
        choices = {v.id: normalize_name(v.name) for v in vendors}
        best = process.extractOne(
            normalize_name(name), choices, scorer=fuzz.token_sort_ratio, score_cutoff=NAME_MATCH_THRESHOLD
        )
        if best is not None:
            vendor_id = best[2]
            return VendorMatch(next(v for v in vendors if v.id == vendor_id), "name", float(best[1]))
    return VendorMatch(None, None)


def sync_vendors(session: Session, erp: Erp) -> int:
    """Upsert the ERP supplier master into the local vendor table. Returns the number of vendors seen."""
    suppliers = erp.list_suppliers()
    existing = {v.erp_id: v for v in session.scalars(select(Vendor))}
    now = utcnow()
    seen: set[str] = set()
    for supplier in suppliers:
        seen.add(supplier.erp_id)
        vendor = existing.get(supplier.erp_id)
        if vendor is None:
            vendor = Vendor(erp_id=supplier.erp_id)
            session.add(vendor)
        vendor.name = supplier.name
        vendor.tax_id = normalize_tax_id(supplier.tax_id)
        vendor.city = supplier.city
        vendor.currency = supplier.currency
        vendor.payment_terms_days = supplier.payment_terms_days
        vendor.is_active = True
        vendor.synced_at = now
    for erp_id, vendor in existing.items():
        if erp_id not in seen and vendor.is_active:
            vendor.is_active = False
            vendor.synced_at = now
    session.flush()
    log.info("vendors_synced", count=len(suppliers))
    return len(suppliers)
