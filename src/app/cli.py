"""The `niscala-api` command line."""

import argparse
import sys
from collections.abc import Sequence
from datetime import UTC

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_engine
from app.models import Lease
from app.schemas.auth import UserRole
from app.schemas.subscriptions import PaidPlanCode
from app.services import rent_bills
from app.services.accounts import find_by_email
from app.services.subscriptions import grant_subscription


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
    return parser


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


def main(argv: Sequence[str] | None = None) -> int:
    """Run a command and return the process exit code."""
    args = _build_parser().parse_args(argv)
    if args.command == "seed-rent-bills":
        return _seed_rent_bills(args.email, args.months)
    return _grant_subscription(args.email, PaidPlanCode(args.plan), args.days)
