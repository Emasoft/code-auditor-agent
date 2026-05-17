# ruff: noqa
# Intentionally contains the bugs each detector should catch.
import jwt

JWT_SECRET = "supersecret"

def sign(payload):
    return jwt.encode(payload, JWT_SECRET, algorithm="none")
