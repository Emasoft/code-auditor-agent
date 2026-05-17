# ruff: noqa
# Intentionally contains the bugs each detector should catch.
password = "admin123"

def login(user_id, provided, cur):
    if provided != password:
        return None
    cur.execute(f"SELECT * FROM users WHERE id = {user_id}")
    return cur.fetchone()
