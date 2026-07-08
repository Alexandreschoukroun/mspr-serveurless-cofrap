"""
Local test without OpenFaaS or PostgreSQL.
Run with: python test_local.py
"""
import json
import os
import base64
from cryptography.fernet import Fernet

# Generates a temporary Fernet key for the test
key = Fernet.generate_key().decode()

# Environment variables simulating K8s secrets
os.environ["FERNET_KEY"] = key
os.environ["DB_HOST"] = "localhost"
os.environ["DB_NAME"] = "cofrapdb"
os.environ["DB_USER"] = "cofrapuser"
os.environ["DB_PASSWORD"] = "testpassword"


class FakeEvent:
    body = json.dumps({"username": "alice"})


class FakeContext:
    pass


# Patch psycopg2 to avoid a real connection
import unittest.mock as mock

fake_cursor = mock.MagicMock()
fake_conn = mock.MagicMock()
fake_conn.cursor.return_value.__enter__ = lambda s: fake_cursor
fake_conn.cursor.return_value.__exit__ = mock.MagicMock(return_value=False)
fake_conn.closed = False

with mock.patch("psycopg2.connect", return_value=fake_conn):
    from handler import handle
    result = handle(FakeEvent(), FakeContext())

print("Status code :", result["statusCode"])
body = json.loads(result["body"])
print("Status      :", body["status"])
print("QR password : [base64 PNG,", len(body.get("qr_password", "")), "chars]")

# Checks that the QR code is a valid PNG
qr_bytes = base64.b64decode(body["qr_password"])
assert qr_bytes[:4] == b"\x89PNG", "The QR code is not a valid PNG"
print("Valid PNG   : OK")
