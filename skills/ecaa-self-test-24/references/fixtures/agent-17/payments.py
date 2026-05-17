# ruff: noqa
# Intentionally contains the bugs each detector should catch.
# NEW MODULE — breaks the local convention used by orders.py / users.py /
# products.py (all of which return Result[Value, Error]). This file raises
# exceptions instead. The architecture-consistency reviewer should flag
# the inconsistency.
def get_payment(id: int):
    if not exists(id):
        raise PaymentNotFoundError(id)
    return Payment(id)
