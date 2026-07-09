# =============================================================================
# OpenFaaS function: generate-2fa
# Role: Generate a TOTP secret for an existing user,
#        encrypt it in the DB and return a Google Authenticator-compatible QR code
#
# Input   (JSON) : { "username": "alice" }
# Output  (JSON) : { "qr_2fa": "<base64 PNG>", "status": "ok" }
#
# Full flow:
#   1. Receives a username (the user must already exist in the DB)
#   2. Generates a random TOTP secret (32 base32 characters)
#   3. Encrypts this secret with Fernet before storing it in the DB
#   4. Updates the user's mfa column in PostgreSQL
#   5. Generates a QR code in otpauth:// format (compatible with Google Authenticator)
#   6. Returns the QR code encoded in base64
#
# This function is called AFTER generate-password during account creation.
# =============================================================================

import json
import os
import io
import base64

import psycopg2
import pyotp
import qrcode
from cryptography.fernet import Fernet

# Application name shown in Google Authenticator
ISSUER = "COFRAP"

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
    Returns an active PostgreSQL connection, reused across calls.
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
    except (json.JSONDecodeError, AttributeError):
        return {"statusCode": 400, "body": json.dumps({"status": "error", "message": "JSON invalide"})}

    if not username:
        return {"statusCode": 400, "body": json.dumps({"status": "error", "message": "username requis"})}

    # ------------------------------------------------------------------
    # STEP 2 — Generate the TOTP secret
    # pyotp.random_base32() generates a 32-character base32 secret key.
    # This is the key shared between the server and the auth app (Google Authenticator).
    # From this key + the current time, a 6-digit code valid for 30s is computed.
    # ------------------------------------------------------------------
    totp_secret = pyotp.random_base32()

    # ------------------------------------------------------------------
    # STEP 3 — Encrypt the TOTP secret with Fernet
    # The TOTP secret must never be stored in plaintext in the DB.
    # The Fernet key comes from the K8s secret "encryption-key" -> FERNET_KEY file.
    # ------------------------------------------------------------------
    fernet = Fernet(_read_secret("FERNET_KEY").encode())
    encrypted_secret = fernet.encrypt(totp_secret.encode()).decode()

    # ------------------------------------------------------------------
    # STEP 4 — Update the mfa column in the database
    # UPDATE (not INSERT) since the user was already created by generate-password.
    # If the user doesn't exist, rowcount == 0 -> an error is returned.
    # ------------------------------------------------------------------
    try:
        conn = _get_db()
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE users SET mfa = %s WHERE username = %s",
                (encrypted_secret, username),
            )
            # rowcount indicates the number of rows modified
            if cur.rowcount == 0:
                conn.rollback()
                return {"statusCode": 404, "body": json.dumps({"status": "error", "message": "Utilisateur introuvable"})}
        conn.commit()
    except Exception as e:
        return {"statusCode": 500, "body": json.dumps({"status": "error", "message": str(e)})}

    # ------------------------------------------------------------------
    # STEP 5 — Generate the QR code in otpauth:// format
    # This format is the standard recognized by Google Authenticator, Authy, etc.
    # The URL encodes: the TOTP secret, the issuer (COFRAP), and the account name.
    # The user scans this QR code with their authenticator app.
    # ------------------------------------------------------------------
    # Example generated URL: otpauth://totp/COFRAP:alice?secret=JBSWY3DPEHPK3PXP&issuer=COFRAP
    otp_uri = pyotp.totp.TOTP(totp_secret).provisioning_uri(
        name=username,
        issuer_name=ISSUER,
    )

    qr = qrcode.QRCode(version=1, box_size=8, border=4)
    qr.add_data(otp_uri)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")

    # Base64 encoding in memory (no disk write)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    qr_b64 = base64.b64encode(buf.getvalue()).decode()

    # ------------------------------------------------------------------
    # STEP 6 — JSON response to the frontend
    # The frontend displays the QR code with: <img src="data:image/png;base64,{qr_2fa}">
    # ------------------------------------------------------------------
    return {
        "statusCode": 200,
        "body": json.dumps({"qr_2fa": qr_b64, "status": "ok"}),
    }
