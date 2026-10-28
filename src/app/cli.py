"""The `niscala-api` command line."""

import argparse
import os
import sys
from collections.abc import Sequence
from datetime import UTC

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_engine
from app.errors import ApiError
from app.models import Lease
from app.schemas.auth import UserRole
from app.schemas.subscriptions import PaidPlanCode
from app.services import demo, rent_bills
from app.services.accounts import create_admin, find_by_email
from app.services.subscriptions import grant_subscription

PASSWORD_VARIABLE = "NISCALA_ADMIN_PASSWORD"


def _positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="niscala-api")
    commands = parser.add_subparsers(dest="command", required=True)
    grant = commands.add_parser(
        "grant-subscription", help="give an owner a paid plan for a number of days"
    )
    grant.add_argument("email")
    grant.add_argument("plan", choices=[plan.value for plan in PaidPlanCode])
    grant.add_argument("--days", type=_positive_int, default=30)
    seed = commands.add_parser(
        "seed-rent-bills",
        help="create rent bills for a tenant's active lease, for development",
    )
    seed.add_argument("email")
    seed.add_argument("--months", type=_positive_int, default=12)
    commands.add_parser(
        "seed-demo",
        help="create a demo owner, property, room and active tenant, for development",
    )
    admin = commands.add_parser(
        "create-admin",
        help="create an admin account; the password comes from --password "
        "or the NISCALA_ADMIN_PASSWORD environment variable",
    )
    admin.add_argument("email")
    admin.add_argument("--name", required=True)
    admin.add_argument("--password")
    return parser


def _create_admin(email: str, name: str, password: str | None) -> int:
    if password is None:
        password = os.environ.get(PASSWORD_VARIABLE) or None
    if password is None:
        print(f"Pass --password or set {PASSWORD_VARIABLE}", file=sys.stderr)
        return 1
    with Session(get_engine()) as db:
        try:
            user = create_admin(db, name, email, password)
        except ApiError as error:
            print(
                f"Cannot create admin {email.strip().lower()}: "
                f"{error.message} ({error.code})",
                file=sys.stderr,
            )
            return 1
        db.commit()
        print(f"Created admin {user.email}")
        return 0


def _grant_subscription(email: str, plan: PaidPlanCode, days: int) -> int:
    with Session(get_engine()) as db:
        user = find_by_email(db, email)
        if user is None or user.role != UserRole.OWNER:
            print(
                f"No owner account with email {email.strip().lower()}", file=sys.stderr
            )
            return 1
        row = grant_subscription(db, user, plan, days)
        db.commit()
        ends_at = row.ends_at.astimezone(UTC).isoformat()
        print(f"Granted {plan.value} to {user.email} until {ends_at}")
        return 0


def _seed_rent_bills(email: str, months: int) -> int:
    with Session(get_engine()) as db:
        user = find_by_email(db, email)
        lease = (
            user
            and db.scalars(
                select(Lease).where(
                    Lease.tenant_id == user.id, Lease.ended_at.is_(None)
                )
            ).first()
        )
        if lease is None or lease.start_date is None:
            print(
                f"No tenant with email {email.strip().lower()} has an active lease "
                "with a start date",
                file=sys.stderr,
            )
            return 1
        created = rent_bills.seed_rent_bills(db, lease, months)
        db.commit()
        print(f"Created {created} rent bills for {user.email}")
        return 0


def _seed_demo() -> int:
    with Session(get_engine()) as db:
        try:
            demo.seed_demo(db)
        except demo.DemoConflict as conflict:
            print(conflict, file=sys.stderr)
            return 1
        db.commit()
    print(f"Owner: {demo.OWNER_EMAIL} / {demo.PASSWORD}")
    print(f"Tenant: {demo.TENANT_EMAIL} / {demo.PASSWORD}")
    print(f"Property: {demo.PROPERTY_NAME}")
    print(f"Room: {demo.ROOM_NUMBER}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run a command and return the process exit code."""
    args = _build_parser().parse_args(argv)
    if args.command == "create-admin":
        return _create_admin(args.email, args.name, args.password)
    if args.command == "seed-rent-bills":
        return _seed_rent_bills(args.email, args.months)
    if args.command == "seed-demo":
        return _seed_demo()
    return _grant_subscription(args.email, PaidPlanCode(args.plan), args.days)
