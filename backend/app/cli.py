"""Operational commands: `iip <command>` (or `python -m app.cli <command>`)."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from pathlib import Path

from sqlalchemy import select


def _migrate(_: argparse.Namespace) -> None:
    from alembic import command
    from alembic.config import Config

    # Non-editable installs (the container image) put the package in site-packages, away from alembic.ini.
    candidates = [
        Path(os.environ.get("ALEMBIC_CONFIG", "alembic.ini")),
        Path(__file__).resolve().parent.parent / "alembic.ini",
    ]
    ini = next((c for c in candidates if c.is_file()), None)
    if ini is None:
        sys.exit("alembic.ini not found; run from the backend directory or set ALEMBIC_CONFIG.")
    config = Config(str(ini))
    config.attributes["configure_logger"] = False
    command.upgrade(config, "head")
    print("Database is at the latest revision.")


def _create_user(args: argparse.Namespace) -> None:
    from app.db import session_scope
    from app.models import User, UserRole
    from app.security import hash_password

    password = os.environ.get(args.password_env) if args.password_env else None
    password = password or getpass.getpass("Password: ")
    if len(password) < 12:
        sys.exit("Passwords must be at least 12 characters.")
    with session_scope() as session:
        if session.scalar(select(User).where(User.email == args.email.lower())):
            sys.exit(f"A user with email {args.email} already exists.")
        session.add(
            User(
                email=args.email.lower(),
                full_name=args.name,
                role=UserRole(args.role),
                password_hash=hash_password(password),
            )
        )
    print(f"Created {args.role} {args.email}.")


def _sync_vendors(_: argparse.Namespace) -> None:
    from app.config import get_settings
    from app.db import session_scope
    from app.services.erp import build_erp_client
    from app.services.vendors import sync_vendors

    with session_scope() as session:
        count = sync_vendors(session, build_erp_client(get_settings()))
    print(f"Synchronised {count} vendors from the ERP.")


def _train(args: argparse.Namespace) -> None:
    import numpy as np

    from app.config import get_settings
    from app.db import session_scope
    from app.models import Invoice, InvoiceStatus
    from app.services.anomaly import (
        HistoricalInvoice,
        build_features,
        evaluate,
        fit,
        synthetic_dataset,
        train_default_model,
    )

    settings = get_settings()
    if not args.from_db:
        model = train_default_model()
    else:
        rows: list[tuple[float, ...]] = []
        with session_scope() as session:
            invoices = session.scalars(
                select(Invoice)
                .where(
                    Invoice.status.in_([InvoiceStatus.APPROVED, InvoiceStatus.POSTED]),
                    Invoice.invoice_date.is_not(None),
                    Invoice.total_amount.is_not(None),
                )
                .order_by(Invoice.vendor_id, Invoice.invoice_date)
            ).all()
            history: dict[object, list[HistoricalInvoice]] = {}
            for inv in invoices:
                if inv.invoice_date is None or inv.total_amount is None:
                    continue
                past = history.setdefault(inv.vendor_id, [])
                features = build_features(
                    inv.total_amount, inv.subtotal, inv.tax_amount, inv.invoice_date, len(inv.line_items), past
                )
                rows.append(features.values)
                rate = float(inv.tax_amount or 0) / float(inv.subtotal) if inv.subtotal else 0.0
                past.insert(0, HistoricalInvoice(inv.invoice_date, float(inv.total_amount), rate))
        if len(rows) < 200:
            sys.exit(f"Only {len(rows)} approved invoices in the database; need at least 200 to retrain.")
        model = fit(np.array(rows), source="database")
        test_x, test_y = synthetic_dataset(n_vendors=40, seed=106, anomaly_rate=0.06)
        model.metadata.evaluation = evaluate(model, test_x, test_y)
    path = model.save(settings.model_dir)
    print(f"Saved {path}")
    print(json.dumps(model.metadata.evaluation, indent=2))


def _seed(args: argparse.Namespace) -> None:
    from app.config import get_settings
    from app.db import get_session_factory
    from app.demo.seed import SCENARIOS, seed
    from app.runtime import build_pipeline_services

    settings = get_settings()
    services = build_pipeline_services(settings)
    session = get_session_factory()()
    try:
        report = seed(
            session, settings, services.store, services.erp, services.anomaly_model, history=not args.no_history
        )
    finally:
        session.close()
    print(
        f"Users: {report.users}  vendors: {report.vendors}  history invoices: {report.history}  "
        f"uploaded for processing: {len(report.uploaded)}"
    )
    for scenario in SCENARIOS[: len(report.uploaded)]:
        print(f"  - {scenario.slug}: {scenario.describe}")
    if args.process and report.uploaded:
        from app.worker import Worker

        processed = Worker(get_session_factory(), services).drain()
        print(f"Processed {processed} jobs.")


def _samples(args: argparse.Namespace) -> None:
    from app.config import get_settings
    from app.demo.seed import write_samples
    from app.services.erp import build_erp_client

    for path in write_samples(build_erp_client(get_settings()), Path(args.out)):
        print(path)


def _openapi(args: argparse.Namespace) -> None:
    from app.main import create_app

    spec = json.dumps(create_app().openapi(), indent=2, sort_keys=False) + "\n"
    if args.out == "-":
        sys.stdout.write(spec)
    else:
        Path(args.out).write_bytes(spec.encode("utf-8"))  # LF endings on every OS for the CI drift check
        print(f"Wrote {args.out}")


def _worker(_: argparse.Namespace) -> None:
    from app.worker import main as worker_main

    worker_main()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="iip", description="Invoice Intelligence Platform operations")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("migrate", help="apply database migrations").set_defaults(func=_migrate)

    p = sub.add_parser("create-user", help="create a user account")
    p.add_argument("--email", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--role", choices=["admin", "approver", "clerk", "viewer"], required=True)
    p.add_argument("--password-env", help="read the password from this environment variable")
    p.set_defaults(func=_create_user)

    sub.add_parser("sync-vendors", help="replicate the ERP supplier master").set_defaults(func=_sync_vendors)

    p = sub.add_parser("train-anomaly", help="train and save the anomaly model")
    p.add_argument("--from-db", action="store_true", help="train on approved invoices instead of synthetic data")
    p.set_defaults(func=_train)

    p = sub.add_parser("seed", help="load demo users, history and sample invoices")
    p.add_argument("--no-history", action="store_true")
    p.add_argument("--process", action="store_true", help="run the pipeline in-process for the new uploads")
    p.set_defaults(func=_seed)

    p = sub.add_parser("generate-samples", help="write the demo scenario PDFs to a directory")
    p.add_argument("--out", default="samples/invoices")
    p.set_defaults(func=_samples)

    p = sub.add_parser("export-openapi", help="write the OpenAPI document")
    p.add_argument("--out", default="-")
    p.set_defaults(func=_openapi)

    sub.add_parser("worker", help="run the background worker").set_defaults(func=_worker)

    args = parser.parse_args(argv)
    from app.config import get_settings
    from app.observability import configure_logging

    configure_logging(get_settings())
    args.func(args)


if __name__ == "__main__":
    main()
