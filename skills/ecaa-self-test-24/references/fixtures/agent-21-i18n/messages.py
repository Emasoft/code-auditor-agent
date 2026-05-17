# ruff: noqa
# Intentionally contains the bugs each detector should catch.
def greet(name: str) -> str:
    return f"Hello, {name}!"


def pluralize(count: int) -> str:
    return f"{count} item" if count == 1 else f"{count} items"


def status_message(status: str) -> str:
    return f"Your order is currently {status.upper()}."
