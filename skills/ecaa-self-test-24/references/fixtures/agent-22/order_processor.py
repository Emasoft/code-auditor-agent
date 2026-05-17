# ruff: noqa
# Intentionally contains the bugs each detector should catch.
import random

_stats = {"processed": 0, "failed": 0}
_active_orders: list = []


def process_order(order_id):
    _stats["processed"] += 1
    _active_orders.append(order_id)
    db.save_order(order_id)
    if random.random() < 0.1:
        charge_payment(order_id)
        _stats["processed"] += 1
    return order_id


def handle_checkout(order_id):
    return process_order(order_id)


def retry_failed_order(order_id):
    return process_order(order_id)


def admin_reprocess(order_id):
    return process_order(order_id)
