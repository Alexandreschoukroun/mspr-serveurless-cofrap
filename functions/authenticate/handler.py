# =============================================================================
# OpenFaaS function: authenticate
# Role: Verify a user's identity (password + TOTP + expiration)
#
# Input   (JSON) : { "username": "alice", "password": "...", "totp_code": "123456" }
# Output  (JSON) : { "status": "ok"|"expired"|"error", "message": "..." }
#
# Full flow:
#   1. Receives username + password + totp_code via POST HTTP
#   2. Fetches the user row from the DB
#   3. Decrypts the stored password (Fernet) and compares it with the input
#   4. Decrypts the TOTP secret (Fernet) and verifies the provided TOTP code
#   5. Checks that the account hasn't expired (> 6 months since gendate)
#      -> If expired: marks expired=1 in the DB, returns {"status": "expired"}
#      -> If valid  : returns {"status": "ok"}
# =============================================================================

import json
import os
import time
import hmac

import psycopg2
import pyotp
from cryptography.fernet import Fernet, InvalidToken

# Account lifetime: 183 days (approx. 6 months)
ACCOUNT_TTL_SECONDS = 183 * 24 * 3600

# PostgreSQL connection reused across calls (OpenFaaS keeps the process alive)
_conn = None


def _read_secret(key: str) -> str:
    """
    Reads a sensitive value from the Kubernetes secrets mounted by OpenFaaS.
    Falls back to environment variables for local tests.
    """
    path = f"/var/openfaas/secrets/{key}"
    try:
        with open(path) as f:
            return f.read().strip()
    except FileNotFoundError:
        return os.environ.get(key, "")


def _get_db():
    """
    Returns an active PostgreSQL connection.
    Creates the connection if it doesn't exist yet or if it was closed.
    """
    global _conn
    if _conn is None or _conn.closed:
        _conn = psycopg2.connect(
            host=_read_secret("DB_HOST"),
            database=_read_secret("DB_NAME"),
            user=_read_secret("DB_USER"),
            password=_read_secret("DB_PASSWORD"),
            connect_timeout=5,
        )
    return _conn


def handle(event, context):
    """
    Entry point called by OpenFaaS on every HTTP POST request.
    """

    # ------------------------------------------------------------------
    # STEP 1 — Read and validate the request body
    # ------------------------------------------------------------------
    try:
        body = json.loads(event.body)
        username = str(body.get("username", "")).strip()
        password = str(body.get("password", "")).strip()
        totp_code = str(body.get("totp_code", "")).strip()
    except (json.JSONDecodeError, AttributeError):
        return {"statusCode": 400, "body": json.dumps({"status": "error", "message": "JSON invalide"})}

    if not username or not password or not totp_code:
        return {"statusCode": 400, "body": json.dumps({"status": "error", "message": "username, password et totp_code requis"})}

    # ------------------------------------------------------------------
    # STEP 2 — Fetch the user from the database
    # ------------------------------------------------------------------
    try:
        conn = _get_db()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT password, mfa, gendate, expired FROM users WHERE username = %s",
                (username,),
            )
            row = cur.fetchone()
    except Exception as e:
        return {"statusCode": 500, "body": json.dumps({"status": "error", "message": str(e)})}

    # Generic message so as not to reveal whether the account exists
    if row is None:
        return {"statusCode": 401, "body": json.dumps({"status": "error", "message": "Identifiants incorrects"})}

    db_password_enc, db_mfa_enc, gendate, expired_flag = row

    # ------------------------------------------------------------------
    # STEP 3 — Password verification
    # Decrypts the stored password then compares it with hmac.compare_digest
    # to avoid timing attacks on the string comparison.
    # ------------------------------------------------------------------
    fernet = Fernet(_read_secret("FERNET_KEY").encode())
    try:
        db_password_clear = fernet.decrypt(db_password_enc.encode()).decode()
    except InvalidToken:
        return {"statusCode": 500, "body": json.dumps({"status": "error", "message": "Erreur de déchiffrement"})}

    if not hmac.compare_digest(db_password_clear, password):
        return {"statusCode": 401, "body": json.dumps({"status": "error", "message": "Identifiants incorrects"})}

    # ------------------------------------------------------------------
    # STEP 4 — TOTP code verification
    # Decrypts the stored TOTP secret, then verifies the code with pyotp.
    # pyotp.TOTP.verify() accepts a ±30s window to compensate for clock
    # drift between the smartphone and the server.
    # ------------------------------------------------------------------
    try:
        db_mfa_secret = fernet.decrypt(db_mfa_enc.encode()).decode()
    except InvalidToken:
        return {"statusCode": 500, "body": json.dumps({"status": "error", "message": "Erreur de déchiffrement MFA"})}

    totp = pyotp.TOTP(db_mfa_secret)
    if not totp.verify(totp_code, valid_window=1):
        return {"statusCode": 401, "body": json.dumps({"status": "error", "message": "Code TOTP invalide"})}

    # ------------------------------------------------------------------
    # STEP 5 — Account expiration check (6 months)
    # If the account is already marked expired=1 or if the creation date
    # exceeds 183 days, forces expired=1 in the DB and refuses the login.
    # ------------------------------------------------------------------
    now = int(time.time())
    account_expired = bool(expired_flag) or (now - gendate) > ACCOUNT_TTL_SECONDS

    if account_expired:
        try:
            conn = _get_db()
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE users SET expired = 1 WHERE username = %s",
                    (username,),
                )
            conn.commit()
        except Exception as e:
            return {"statusCode": 500, "body": json.dumps({"status": "error", "message": str(e)})}

        return {
            "statusCode": 403,
            "body": json.dumps({
                "status": "expired",
                "message": "Compte expiré. Veuillez renouveler vos identifiants.",
            }),
        }

    # ------------------------------------------------------------------
    # STEP 6 — Successful authentication
    # ------------------------------------------------------------------
    return {
        "statusCode": 200,
        "body": json.dumps({
            "status": "ok",
            "message": "Authentification réussie",
        }),
    }
