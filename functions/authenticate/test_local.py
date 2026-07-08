"""
Local test using an in-memory SQLite database (no need for PostgreSQL or OpenFaaS).
Run with: python test_local.py
"""
import json
import os
import sys
import time
import sqlite3
import unittest.mock as mock
from cryptography.fernet import Fernet
import pyotp

# ---------------------------------------------------------------------------
# SQLite adapter -> psycopg2 interface
# handler.py uses %s as a placeholder (psycopg2 style);
# SQLite expects ? — we translate it on the fly in the cursor.
# ---------------------------------------------------------------------------

class _Cursor:
    def __init__(self, cur):
        self._cur = cur

    def execute(self, sql, params=()):
        self._cur.execute(sql.replace("%s", "?"), params)

    def fetchone(self):
        return self._cur.fetchone()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass


class _Conn:
    def __init__(self, conn):
        self._conn = conn
        self.closed = False

    def cursor(self):
        class _CM:
            def __init__(cm, conn):
                cm._conn = conn
            def __enter__(cm):
                return _Cursor(cm._conn.cursor())
            def __exit__(cm, *_):
                pass
        return _CM(self._conn)

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()


# ---------------------------------------------------------------------------
# SQLite database and test data setup
# ---------------------------------------------------------------------------

key = Fernet.generate_key()
fernet = Fernet(key)

totp_secret = pyotp.random_base32()
plain_password = "MonMotDePasse24CharsXXXX"

enc_password = fernet.encrypt(plain_password.encode()).decode()
enc_mfa = fernet.encrypt(totp_secret.encode()).decode()

# Creates the users table in SQLite (same schema as PostgreSQL)
_sqlite = sqlite3.connect(":memory:")
_sqlite.execute("""
    CREATE TABLE users (
        username TEXT PRIMARY KEY,
        password TEXT NOT NULL,
        mfa      TEXT NOT NULL,
        gendate  INTEGER NOT NULL,
        expired  INTEGER NOT NULL DEFAULT 0
    )
""")
_sqlite.execute(
    "INSERT INTO users VALUES (?, ?, ?, ?, ?)",
    ("alice", enc_password, enc_mfa, int(time.time()) - 3600, 0),
)
# Expired account: created 200 days ago
_sqlite.execute(
    "INSERT INTO users VALUES (?, ?, ?, ?, ?)",
    ("bob", enc_password, enc_mfa, int(time.time()) - 200 * 86400, 0),
)
_sqlite.commit()

db_adapter = _Conn(_sqlite)

# Environment variables simulating K8s secrets
os.environ["FERNET_KEY"] = key.decode()
os.environ["DB_HOST"] = "localhost"
os.environ["DB_NAME"] = "cofrapdb"
os.environ["DB_USER"] = "cofrapuser"
os.environ["DB_PASSWORD"] = "testpassword"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class FakeEvent:
    def __init__(self, payload):
        self.body = json.dumps(payload)


class FakeContext:
    pass


def run_test(label, payload, expected_status, expected_http):
    if "handler" in sys.modules:
        del sys.modules["handler"]
    with mock.patch("handler._get_db", return_value=db_adapter):
        from handler import handle
        result = handle(FakeEvent(payload), FakeContext())
    body = json.loads(result["body"])
    ok = body["status"] == expected_status and result["statusCode"] == expected_http
    mark = "OK  " if ok else "FAIL"
    print(f"[{mark}] {label:<35} | HTTP {result['statusCode']} | {body['message']}")
    return ok


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

print("\n=== Tests authenticate ===\n")

totp_now = pyotp.TOTP(totp_secret).now()

run_test(
    "Successful auth",
    {"username": "alice", "password": plain_password, "totp_code": totp_now},
    "ok", 200,
)
run_test(
    "Wrong password",
    {"username": "alice", "password": "wrong_password", "totp_code": totp_now},
    "error", 401,
)
run_test(
    "Wrong TOTP code",
    {"username": "alice", "password": plain_password, "totp_code": "000000"},
    "error", 401,
)
run_test(
    "Nonexistent user",
    {"username": "inconnu", "password": plain_password, "totp_code": totp_now},
    "error", 401,
)
run_test(
    "Expired account (>183 days)",
    {"username": "bob", "password": plain_password, "totp_code": pyotp.TOTP(totp_secret).now()},
    "expired", 403,
)
run_test(
    "Missing fields",
    {"username": "alice"},
    "error", 400,
)
run_test(
    "Invalid JSON",
    "pas du json",
    "error", 400,
)

print()
