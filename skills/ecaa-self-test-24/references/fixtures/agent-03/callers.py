# ruff: noqa
# Intentionally contains the bugs each detector should catch.
# Two call sites that still reference the OLD public name `get_user`,
# which the diff renamed to `fetch_user` without updating them. The
# rename is a breaking change for these callers.
from api import get_user

def list_recent():
    return [get_user(uid) for uid in recent_user_ids()]


def admin_view(uid):
    return get_user(uid).to_dict()
