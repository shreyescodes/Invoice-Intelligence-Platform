"""Demo data: users, a year of invoice history, and fresh invoices that exercise every pipeline path.

History is written straight to the database (it represents invoices processed before the demo
started). The fresh invoices are rendered from live ERP purchase orders and go through the real
upload -> extraction -> validation -> scoring -> approval pipeline.
"""

from __future__ import annotations

import hashlib
import random
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import utcnow
from app.demo.accounts import DEMO_ACCOUNTS
from app.demo.invoice_pdf import InvoiceDocument, Line, Party, Style, render_invoice_pdf
from app.models import (
    AuditEvent,
    CheckStatus,
    Invoice,
    InvoiceCheck,
    InvoiceLineItem,
    InvoiceStatus,
    User,
    UserRole,
    Vendor,
)
from app.observability import get_logger
from app.security import hash_password
from app.services.anomaly import AnomalyModel, HistoricalInvoice, build_features, explain
from app.services.erp import ErpClient, PurchaseOrder, Supplier
from app.services.invoices import InvoiceService, invoice_number_key
from app.services.storage import DocumentStore
from app.services.vendors import sync_vendors

log = get_logger(__name__)

HISTORY_DAYS = 365
MANUAL_COMMENTS = (
    "Verified against GRN and contract rates",
    "Approved - matches the signed work order",
    "Confirmed with requester, OK to pay",
    "Rate revision agreed in last vendor review",
)
REJECT_COMMENTS = ("Duplicate of an invoice already paid", "Pricing not agreed with procurement")


def fiscal_year(d: date) -> str:
    start = d.year if d.month >= 4 else d.year - 1
    return f"{start % 100:02d}-{(start + 1) % 100:02d}"


@dataclass(frozen=True, slots=True)
class Item:
    description: str
    hsn: str
    price: Decimal
    qty: tuple[int, int]
    unit: str = "EA"
    probability: float = 1.0


@dataclass(frozen=True, slots=True)
class VendorProfile:
    style: Style
    tax_rate: Decimal
    cadence_days: int
    items: tuple[Item, ...]
    number: Callable[[int, date], str]
    monthly_label: bool = False  # recurring services carry the month in the description
    first_number: int = 100


PROFILES: dict[str, VendorProfile] = {
    "100010": VendorProfile(
        "classic",
        Decimal(18),
        14,
        (
            Item("Hydraulic hose assembly 3/4 in", "4009", Decimal("1450.00"), (10, 50)),
            Item("Inductive proximity sensor M18", "8536", Decimal("2350.00"), (4, 16), probability=0.6),
            Item("Deep groove ball bearing 6205-2RS", "8482", Decimal("185.00"), (60, 240), probability=0.5),
            Item("Pneumatic cylinder 50 x 100 mm", "8412", Decimal("4200.00"), (2, 8), probability=0.4),
        ),
        lambda n, d: f"KIC/{fiscal_year(d)}/{n:04d}",
        first_number=388,
    ),
    "100011": VendorProfile(
        "modern",
        Decimal(18),
        30,
        (
            Item("Managed Kubernetes cluster", "998315", Decimal("48000.00"), (1, 1), "MON"),
            Item("Object storage 10 TB-month", "998315", Decimal("9500.00"), (1, 1), "MON"),
            Item("Premium support plan", "998316", Decimal("15000.00"), (1, 1), "MON"),
        ),
        lambda n, d: f"BPC-{d.year}-{n:04d}",
        monthly_label=True,
        first_number=912,
    ),
    "100012": VendorProfile(
        "compact",
        Decimal(12),
        9,
        (
            Item("FTL transport Chennai to Bengaluru (32 ft)", "996511", Decimal("28000.00"), (1, 4), "TRP"),
            Item("Loading and unloading charges", "996719", Decimal("3500.00"), (1, 4), "TRP"),
        ),
        lambda n, d: f"GFL/CHN/{n:04d}",
        first_number=1142,
    ),
    "100013": VendorProfile(
        "classic",
        Decimal(18),
        30,
        (
            Item("Housekeeping services", "998533", Decimal("185000.00"), (1, 1), "MON"),
            Item("Pest control treatment", "998531", Decimal("12000.00"), (1, 1), probability=0.35),
        ),
        lambda n, d: f"MFS-DEL-{d:%y}-{n:04d}",
        monthly_label=True,
        first_number=61,
    ),
    "100014": VendorProfile(
        "modern",
        Decimal(18),
        30,
        (
            Item("MPLS link 100 Mbps", "998422", Decimal("36000.00"), (1, 1), "MON"),
            Item("SIP trunk 30 channels", "998413", Decimal("8500.00"), (1, 1), "MON"),
        ),
        lambda n, d: f"OTS/{d:%y}/{d:%m}/{n:04d}",
        monthly_label=True,
        first_number=31,
    ),
    "100015": VendorProfile(
        "compact",
        Decimal(5),
        15,
        (
            Item("Employee lunch (per plate)", "996331", Decimal("145.00"), (880, 1080)),
            Item("Evening snacks (per serving)", "996331", Decimal("60.00"), (650, 900)),
        ),
        lambda n, d: f"SCC-{n:04d}",
        first_number=1418,
    ),
    "100016": VendorProfile(
        "classic",
        Decimal(18),
        26,
        (
            Item("Laptop 14 in i7 / 16 GB / 512 GB SSD", "8471", Decimal("92500.00"), (1, 3)),
            Item("27 in IPS monitor", "8528", Decimal("21800.00"), (1, 4), probability=0.6),
            Item("USB-C docking station", "8473", Decimal("11200.00"), (1, 3), probability=0.5),
        ),
        lambda n, d: f"VIT-HYD-{d:%y}-{n:04d}",
        first_number=291,
    ),
    "100017": VendorProfile(
        "compact",
        Decimal(18),
        13,
        (
            Item("A4 copier paper 75 gsm (ream)", "4802", Decimal("285.00"), (20, 80), "RM"),
            Item("Toner cartridge HP 26A", "8443", Decimal("4350.00"), (1, 4), probability=0.7),
            Item("Whiteboard markers (box of 10)", "9608", Decimal("420.00"), (2, 10), "BOX", probability=0.5),
        ),
        lambda n, d: f"SOS/{n:04d}",
        first_number=1047,
    ),
}

UNKNOWN_VENDOR = Supplier(
    erp_id="",
    name="Nimbus Print & Signage",
    tax_id="27AAHFN5512C1Z0",
    city="Mumbai",
    currency="INR",
    payment_terms_days=15,
    street="Shop 4, Kamala Mills Compound, Lower Parel",
    postal_code="400013",
    region="Maharashtra",
)


def supplier_party(supplier: Supplier) -> Party:
    address = [supplier.street or "", f"{supplier.city} {supplier.postal_code}, {supplier.region}"]
    return Party(supplier.name, [a for a in address if a.strip()], supplier.tax_id)


def buyer_party(company: dict[str, object]) -> Party:
    address = company.get("Address", [])
    return Party(
        str(company["CompanyName"]),
        [str(a) for a in address] if isinstance(address, list) else [],
        str(company.get("TaxNumber") or "") or None,
    )


def ensure_users(session: Session) -> dict[str, User]:
    users: dict[str, User] = {}
    for account in DEMO_ACCOUNTS:
        user = session.scalar(select(User).where(User.email == account["email"]))
        if user is None:
            user = User(
                email=account["email"],
                full_name=account["name"],
                role=UserRole(account["role"]),
                password_hash=hash_password(account["password"]),
            )
            session.add(user)
        users[account["role"]] = user
    session.flush()
    return users


def _document(
    profile: VendorProfile,
    supplier: Supplier,
    buyer: Party,
    number: str,
    invoice_date: date,
    lines: list[Line],
    po: str | None,
    **overrides: object,
) -> InvoiceDocument:
    return InvoiceDocument(
        style=profile.style,
        vendor=supplier_party(supplier),
        buyer=buyer,
        invoice_number=number,
        invoice_date=invoice_date,
        due_date=invoice_date + timedelta(days=supplier.payment_terms_days),
        po_number=po,
        lines=lines,
        tax_rate=profile.tax_rate,
        intra_state=bool(supplier.tax_id and buyer.tax_id and supplier.tax_id[:2] == buyer.tax_id[:2]),
        bank_details=supplier.bank_account,
        **overrides,  # type: ignore[arg-type]
    )


def _at(d: date, rng: random.Random, start_hour: int = 9) -> datetime:
    return datetime.combine(d, time(start_hour), tzinfo=UTC) + timedelta(minutes=rng.randint(0, 8 * 60))


# --- History ---------------------------------------------------------------------------------------


@dataclass(slots=True)
class SeedReport:
    users: int = 0
    vendors: int = 0
    history: int = 0
    uploaded: list[str] = field(default_factory=list)
    duplicate_numbers: dict[str, str] = field(default_factory=dict)


def seed_history(
    session: Session,
    store: DocumentStore,
    erp: ErpClient,
    model: AnomalyModel,
    users: dict[str, User],
    report: SeedReport,
    today: date,
    seed: int = 42,
) -> None:
    rng = random.Random(seed)
    buyer = buyer_party(erp.get_company())
    suppliers = {s.erp_id: s for s in erp.list_suppliers()}
    vendors = {v.erp_id: v for v in session.scalars(select(Vendor))}
    clerk, approver = users["clerk"], users["approver"]
    po_counter = 4500010400

    for erp_id, profile in PROFILES.items():
        supplier, vendor = suppliers.get(erp_id), vendors.get(erp_id)
        if supplier is None or vendor is None:
            continue
        history: list[HistoricalInvoice] = []
        number = profile.first_number
        current = today - timedelta(days=HISTORY_DAYS) + timedelta(days=rng.randint(0, profile.cadence_days))
        while current < today - timedelta(days=12):
            lines = []
            for item in profile.items:
                if rng.random() > item.probability:
                    continue
                description = f"{item.description} - {current:%b %Y}" if profile.monthly_label else item.description
                lines.append(Line(description, Decimal(rng.randint(*item.qty)), item.price, item.hsn, item.unit))
            if not lines:
                item = profile.items[0]
                lines.append(Line(item.description, Decimal(item.qty[0]), item.price, item.hsn, item.unit))
            po_counter += 1
            invoice_no = profile.number(number, current)
            doc = _document(profile, supplier, buyer, invoice_no, current, lines, str(po_counter))
            _store_history_invoice(session, store, model, doc, vendor, history, clerk, approver, rng, today)
            report.duplicate_numbers.setdefault(erp_id, invoice_no)
            report.history += 1
            number += 1
            jitter = max(1, int(profile.cadence_days * 0.15))
            current += timedelta(days=profile.cadence_days + rng.randint(-jitter, jitter))
    session.flush()


def _store_history_invoice(
    session: Session,
    store: DocumentStore,
    model: AnomalyModel,
    doc: InvoiceDocument,
    vendor: Vendor,
    history: list[HistoricalInvoice],
    clerk: User,
    approver: User,
    rng: random.Random,
    today: date,
) -> None:
    pdf = render_invoice_pdf(doc)
    invoice_id = uuid.uuid4()
    received = _at(doc.invoice_date + timedelta(days=rng.randint(0, 3)), rng)
    received = min(received, utcnow() - timedelta(days=1))
    key = f"invoices/{received:%Y/%m}/{invoice_id}.pdf"
    store.put(key, pdf, "application/pdf")

    features = build_features(doc.total, doc.subtotal, doc.tax_total, doc.invoice_date, len(doc.lines), history)
    score = model.score(features)
    roll = rng.random()
    over_limit = doc.total > Decimal("250000")
    rejected = roll < 0.025
    auto = not rejected and not over_limit and score < 0.5 and roll < 0.93
    processed = received + timedelta(seconds=rng.randint(4, 40))
    decided = processed if auto else processed + timedelta(hours=rng.uniform(2, 40))
    posted = None if rejected else decided + timedelta(seconds=rng.randint(3, 50))

    reasons: list[str] = []
    if not auto:
        if over_limit:
            reasons.append("Amount exceeds the auto-approval limit of 250,000")
        if score >= 0.5:
            reasons.append(f"Anomaly score {score:.2f} is above the review threshold (0.50)")
        if not reasons:
            reasons.append("Line 1 is billed at a price that differs from the PO by more than 2.0%")

    invoice = Invoice(
        id=invoice_id,
        status=InvoiceStatus.REJECTED if rejected else InvoiceStatus.POSTED,
        file_name=f"{doc.invoice_number.replace('/', '-')}.pdf",
        content_type="application/pdf",
        file_size=len(pdf),
        file_sha256=hashlib.sha256(pdf).hexdigest(),
        storage_key=key,
        uploaded_by_id=clerk.id,
        vendor_id=vendor.id,
        vendor_name=vendor.name,
        vendor_tax_id=vendor.tax_id,
        invoice_number=doc.invoice_number,
        invoice_number_key=invoice_number_key(doc.invoice_number),
        po_number=doc.po_number,
        invoice_date=doc.invoice_date,
        due_date=doc.due_date,
        currency="INR",
        subtotal=doc.subtotal,
        tax_amount=doc.tax_total,
        total_amount=doc.total,
        extraction_method="pdf_text",
        extraction_confidence=round(rng.uniform(0.93, 0.99), 3),
        field_confidence={
            "vendor_name": 1.0,
            "invoice_number": 0.95,
            "invoice_date": 0.95,
            "total_amount": 0.99,
            "subtotal": 0.99,
            "tax_amount": 0.99,
            "po_number": 0.95,
        },
        anomaly_score=score,
        anomaly_reasons=explain(features, score),
        review_reasons=reasons,
        model_version=model.version,
        auto_approved=auto,
        decided_by_id=None if auto else approver.id,
        decided_at=decided,
        decision_comment=None if auto else rng.choice(REJECT_COMMENTS if rejected else MANUAL_COMMENTS),
        erp_document_number=None if posted is None else str(5105500000 + rng.randint(1, 99999)),
        posted_at=posted,
        processed_at=processed,
        created_at=received,
        updated_at=posted or decided,
        line_items=[
            InvoiceLineItem(
                line_no=i + 1,
                description=li.description,
                quantity=li.quantity,
                unit_price=li.unit_price,
                amount=li.amount,
                po_item=str((i + 1) * 10),
            )
            for i, li in enumerate(doc.lines)
        ],
        checks=[
            InvoiceCheck(code=code, status=CheckStatus.PASS, message=message)
            for code, message in (
                ("REQUIRED_FIELDS", "All mandatory header fields were extracted"),
                ("VENDOR_MATCH", f"Matched to vendor {vendor.erp_id} by tax ID"),
                ("DUPLICATE", "No duplicate found for this vendor"),
                ("LINE_TOTALS", f"{len(doc.lines)} line items add up to the subtotal"),
                ("INVOICE_TOTAL", "Subtotal plus tax equals the invoice total"),
                ("TAX_RATE", f"Tax rate {doc.tax_rate}% matches a GST slab"),
                ("DATES", "Invoice and due dates are plausible"),
                ("PO_MATCH", f"All lines matched to PO {doc.po_number}"),
                ("PRICE_MATCH", "Unit prices are within 2.0% of the PO"),
                ("GOODS_RECEIPT", "Billed quantities are covered by goods receipts"),
            )
        ],
    )
    session.add(invoice)
    events: list[tuple[str, InvoiceStatus | None, InvoiceStatus, User | None, datetime, str | None]] = [
        ("uploaded", None, InvoiceStatus.RECEIVED, clerk, received, None),
        ("processing_started", InvoiceStatus.RECEIVED, InvoiceStatus.PROCESSING, None, processed, None),
    ]
    if auto:
        events.append(("auto_approved", InvoiceStatus.PROCESSING, InvoiceStatus.APPROVED, None, processed, None))
    else:
        events.append(("routed_to_review", InvoiceStatus.PROCESSING, InvoiceStatus.NEEDS_REVIEW, None, processed, None))
        final = InvoiceStatus.REJECTED if rejected else InvoiceStatus.APPROVED
        events.append(
            (
                "rejected" if rejected else "approved",
                InvoiceStatus.NEEDS_REVIEW,
                final,
                approver,
                decided,
                invoice.decision_comment,
            )
        )
    if posted is not None:
        events.append(("posted_to_erp", InvoiceStatus.APPROVED, InvoiceStatus.POSTED, None, posted, None))
    for action, from_s, to_s, actor, at, comment in events:
        session.add(
            AuditEvent(
                invoice_id=invoice_id,
                actor_id=actor.id if actor else None,
                action=action,
                from_status=from_s.value if from_s else None,
                to_status=to_s.value,
                comment=comment,
                created_at=at,
            )
        )
    if not rejected:
        history.insert(0, HistoricalInvoice(doc.invoice_date, float(doc.total), float(doc.tax_rate) / 100))


# --- Fresh invoices that go through the pipeline -----------------------------------------------------


@dataclass(frozen=True, slots=True)
class Scenario:
    slug: str
    supplier_id: str | None  # None = vendor that is not in the ERP
    po_number: str | None
    invoice_number: Callable[[SeedReport], str]
    days_ago: int
    build_lines: Callable[[PurchaseOrder | None], list[Line]]
    overrides: dict[str, object] = field(default_factory=dict)
    describe: str = ""


def _po_lines(
    po: PurchaseOrder | None,
    *,
    qty: dict[str, Decimal] | None = None,
    price: dict[str, Decimal] | None = None,
    hsn: str = "9983",
) -> list[Line]:
    assert po is not None
    qty, price = qty or {}, price or {}
    return [
        Line(
            item.description,
            qty.get(item.item, item.received_quantity - item.invoiced_quantity),
            price.get(item.item, item.net_price),
            hsn,
            item.unit,
        )
        for item in po.items
        if qty.get(item.item, Decimal(1)) > 0
    ]


SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        "kaveri-clean",
        "100010",
        "4500012101",
        lambda r: "KIC/26-27/0412",
        9,
        lambda po: _po_lines(po, hsn="4009"),
        describe="matches PO and goods receipt: auto-approved",
    ),
    Scenario(
        "bluepeak-clean",
        "100011",
        "4500012102",
        lambda r: "BPC-2026-0931",
        7,
        lambda po: _po_lines(po, hsn="998315"),
        describe="recurring cloud services: auto-approved",
    ),
    Scenario(
        "sharda-clean",
        "100017",
        "4500012103",
        lambda r: "SOS/1102",
        6,
        lambda po: _po_lines(po, hsn="4802"),
        describe="office supplies: auto-approved",
    ),
    Scenario(
        "meridian-clean",
        "100013",
        "4500012106",
        lambda r: "MFS-DEL-26-0073",
        4,
        lambda po: _po_lines(po, hsn="998533"),
        describe="monthly facility services: auto-approved",
    ),
    Scenario(
        "vertex-price-variance",
        "100016",
        "4500012104",
        lambda r: "VIT-HYD-26-0318",
        8,
        lambda po: _po_lines(po, price={"10": Decimal("103600.00")}, hsn="8471"),
        describe="laptops billed 12% above PO price",
    ),
    Scenario(
        "ganesh-short-receipt",
        "100012",
        "4500012105",
        lambda r: "GFL/CHN/1187",
        5,
        lambda po: _po_lines(po, qty={"10": Decimal(6), "20": Decimal(6)}, hsn="996511"),
        describe="bills 6 trips, only 4 received",
    ),
    Scenario(
        "saffron-duplicate",
        "100015",
        "4500012108",
        lambda r: r.duplicate_numbers.get("100015", "SCC-1418"),
        3,
        lambda po: _po_lines(po, qty={"10": Decimal(1050), "20": Decimal(850)}, hsn="996331"),
        describe="re-uses an invoice number that was already paid",
    ),
    Scenario(
        "orbit-amount-anomaly",
        "100014",
        "4500012107",
        lambda r: "OTS/26/10/0045",
        2,
        lambda po: _po_lines(po, hsn="998422"),
        describe="about 9x the vendor's usual amount",
    ),
    Scenario(
        "meridian-no-po",
        "100013",
        None,
        lambda r: "MFS-DEL-26-0074",
        2,
        lambda po: [Line("Deep cleaning - plant floor (one time)", Decimal(1), Decimal("64000.00"), "998533")],
        describe="no purchase order reference",
    ),
    Scenario(
        "kaveri-line-total-mismatch",
        "100010",
        "4500012109",
        lambda r: "KIC/26-27/0419",
        1,
        lambda po: _po_lines(po, hsn="8482"),
        overrides={"subtotal_override": Decimal("58200.00")},
        describe="subtotal printed 200 higher than the line items",
    ),
    Scenario(
        "nimbus-unknown-vendor",
        None,
        None,
        lambda r: "NPS/2026/118",
        1,
        lambda po: [
            Line("Vinyl banner 6 x 3 ft", Decimal(12), Decimal("1850.00"), "4911"),
            Line("Acrylic signage board", Decimal(2), Decimal("7500.00"), "3926"),
        ],
        describe="vendor is not in the vendor master",
    ),
)


# Written to samples/invoices for trying the upload flow by hand, but never uploaded by the seed.
SAMPLE_ONLY: tuple[Scenario, ...] = (
    Scenario(
        "sharda-stationery-try-me",
        "100017",
        "4500012110",
        lambda r: "SOS/1109",
        0,
        lambda po: _po_lines(po, hsn="4802"),
        describe="clean invoice to upload yourself",
    ),
)


def render_scenarios(
    erp: ErpClient, report: SeedReport, today: date, scenarios: tuple[Scenario, ...] = SCENARIOS, start: int = 1
) -> list[tuple[str, bytes]]:
    buyer = buyer_party(erp.get_company())
    suppliers = {s.erp_id: s for s in erp.list_suppliers()}
    documents: list[tuple[str, bytes]] = []
    for index, scenario in enumerate(scenarios, start=start):
        supplier = suppliers[scenario.supplier_id] if scenario.supplier_id else UNKNOWN_VENDOR
        profile = PROFILES.get(scenario.supplier_id or "", PROFILES["100017"])
        po = erp.get_purchase_order(scenario.po_number) if scenario.po_number else None
        invoice_date = today - timedelta(days=scenario.days_ago)
        doc = _document(
            profile,
            supplier,
            buyer,
            scenario.invoice_number(report),
            invoice_date,
            scenario.build_lines(po),
            scenario.po_number,
            **scenario.overrides,
        )
        documents.append((f"{index:02d}-{scenario.slug}.pdf", render_invoice_pdf(doc)))
    return documents


def seed(
    session: Session,
    settings: Settings,
    store: DocumentStore,
    erp: ErpClient,
    model: AnomalyModel,
    *,
    history: bool = True,
    scenarios: bool = True,
    today: date | None = None,
) -> SeedReport:
    today = today or utcnow().date()
    report = SeedReport()
    users = ensure_users(session)
    report.users = len(users)
    report.vendors = sync_vendors(session, erp)
    session.commit()

    if session.scalar(select(Invoice.id).limit(1)) is not None:
        log.info("seed_skipped_existing_invoices")
        return report
    if history:
        seed_history(session, store, erp, model, users, report, today)
        session.commit()
    if scenarios:
        service = InvoiceService(session, settings, store)
        for name, pdf in render_scenarios(erp, report, today):
            invoice = service.ingest(pdf, name, users["clerk"])
            report.uploaded.append(str(invoice.id))
    return report


def write_samples(erp: ErpClient, out_dir: Path, today: date | None = None) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    report = SeedReport(duplicate_numbers={"100015": "SCC-1418"})
    paths = []
    day = today or utcnow().date()
    documents = render_scenarios(erp, report, day) + render_scenarios(
        erp, report, day, SAMPLE_ONLY, start=len(SCENARIOS) + 1
    )
    for name, pdf in documents:
        path = out_dir / name
        path.write_bytes(pdf)
        paths.append(path)
    return paths
