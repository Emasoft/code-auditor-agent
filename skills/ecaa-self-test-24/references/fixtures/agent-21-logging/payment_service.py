# ruff: noqa
# Intentionally contains the bugs each detector should catch.
import logging

logger = logging.getLogger(__name__)


def process_payment(card_number, cvv, amount):
    logger.info(f"Processing payment for card {card_number}, amount {amount}")
    logger.debug(f"CVV: {cvv}")
    # PCI-DSS violation: full PAN and CVV must NEVER be logged.
    return {"status": "ok"}
