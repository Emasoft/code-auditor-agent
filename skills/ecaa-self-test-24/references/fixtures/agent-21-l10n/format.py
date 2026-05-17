# ruff: noqa
# Intentionally contains the bugs each detector should catch.
from datetime import datetime


def format_date(dt: datetime) -> str:
    return dt.strftime("%m/%d/%Y")


def format_money(amount: float) -> str:
    return f"${amount:.2f}"


def format_number(n: float) -> str:
    return f"{n:,.2f}"
