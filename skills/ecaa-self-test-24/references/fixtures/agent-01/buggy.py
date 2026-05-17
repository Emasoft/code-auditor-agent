# ruff: noqa
# Intentionally contains the bugs each detector should catch.
def divide(a: int, b: int) -> int:
    # Bug: signature claims int but `/` always yields float.
    # Should be `a // b` for integer division.
    return a / b
