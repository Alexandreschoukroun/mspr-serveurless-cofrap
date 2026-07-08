# =============================================================================
# OpenFaaS function: generate-password
# Role: Create a new user in the DB with a secure password
#        and return that password as a QR code (shown ONLY once)
#
# Input   (JSON) : { "username": "alice" }
# Output  (JSON) : { "qr_password": "<base64 PNG>", "password": "<plaintext password>", "status": "ok" }
#
# Full flow:
#   1. Receives a username via POST HTTP
#   2. Generates a random 24-character password
#   3. Encrypts this password with Fernet (AES-128) before storing it in the DB
#   4. Inserts the user row into PostgreSQL
#   5. Generates a PNG QR code of the PLAINTEXT password (for the user to scan)
#   6. Returns the QR code encoded in base64
# =============================================================================

import json
import os
import secrets
import string
import time
import io
import base64

import psycopg2
import psycopg2.errors
import qrcode
from cryptography.fernet import Fernet

# Character set for the password: uppercase + lowercase + digits + special characters
# secrets.choice() is cryptographically secure (unlike random.choice)
CHARSET = string.ascii_letters + string.digits + "!@#$%&*"

# PostgreSQL connection reused across calls (OpenFaaS keeps the process alive)
_conn = None


def _read_secret(key: str) -> str:
    """
    Reads a sensitive value from the Kubernetes secrets mounted by OpenFaaS.

    In production (OpenFaaS on K3s):
      K8s secrets are mounted as files under /var/openfaas/secrets/
      E.g.: the "db-credentials" secret with key "DB_HOST"
           -> file /var/openfaas/secrets/DB_HOST

    Locally (tests):
      If the file doesn't exist, falls back to environment variables.
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
    This avoids opening a new connection on every function call.
    """
    global _conn
    if _conn is None or _conn.closed:
        _conn = psycopg2.connect(
            host=_read_secret("DB_HOST"),         # Internal IP of the PostgreSQL service in K8s
            database=_read_secret("DB_NAME"),     # cofrapdb
            user=_read_secret("DB_USER"),         # cofrapuser
            password=_read_secret("DB_PASSWORD"),
            connect_timeout=5,
        )
    return _conn


def handle(event, context):
    """
    Entry point called by OpenFaaS on every HTTP POST request.
    event.body contains the JSON sent by the frontend.
    """

    # ------------------------------------------------------------------
    # STEP 1 — Read and validate the request body
    # ------------------------------------------------------------------
    try:
        body = json.loads(event.body)
        username = str(body.get("username", "")).strip()
    except (json.JSONDecodeError, AttributeError):
        # The body is not valid JSON
        return {"statusCode": 400, "body": json.dumps({"status": "error", "message": "JSON invalide"})}

    if not username:
        return {"statusCode": 400, "body": json.dumps({"status": "error", "message": "username requis"})}

    # ------------------------------------------------------------------
    # STEP 2 — Generate the random password (24 characters)
    # secrets.choice is cryptographically secure (uses /dev/urandom)
    # ------------------------------------------------------------------
    password = "".join(secrets.choice(CHARSET) for _ in range(24))

    # ------------------------------------------------------------------
    # STEP 3 — Encrypt the password with Fernet (AES-128-CBC)
    # The encrypted password will be stored in the DB.
    # The Fernet key comes from the K8s secret "encryption-key" -> FERNET_KEY file.
    # Fernet guarantees that without the key, the ciphertext is unreadable.
    # ------------------------------------------------------------------
    fernet = Fernet(_read_secret("FERNET_KEY").encode())
    encrypted_pwd = fernet.encrypt(password.encode()).decode()

    # ------------------------------------------------------------------
    # STEP 4 — Insert into the PostgreSQL database
    # - password  : ENCRYPTED password (never stored in plaintext in the DB)
    # - mfa       : empty for now, filled in by generate-2fa afterward
    # - gendate   : Unix creation timestamp (used to compute the 6-month expiration)
    # - expired   : 0 = valid account
    # ------------------------------------------------------------------
    gendate = int(time.time())
    try:
        conn = _get_db()
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO users (username, password, mfa, gendate, expired) VALUES (%s, %s, %s, %s, %s)",
                (username, encrypted_pwd, "", gendate, 0),
            )
        conn.commit()
    except psycopg2.errors.UniqueViolation:
        # The UNIQUE constraint on username prevents duplicates in the DB
        _conn.rollback()
        return {"statusCode": 409, "body": json.dumps({"status": "error", "message": "Utilisateur déjà existant"})}
    except Exception as e:
        return {"statusCode": 500, "body": json.dumps({"status": "error", "message": str(e)})}

    # ------------------------------------------------------------------
    # STEP 5 — Generate the QR code with the PLAINTEXT password
    # The user will scan this QR code with their phone to save their password.
    # IMPORTANT: this QR code is shown ONLY ONCE on the frontend.
    # The PNG image is base64-encoded so it can be carried inside JSON.
    # ------------------------------------------------------------------
    qr = qrcode.QRCode(version=1, box_size=8, border=4)
    qr.add_data(password)       # The plaintext password goes into the QR code
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")

    buf = io.BytesIO()          # In-memory buffer (no disk write)
    img.save(buf, format="PNG")
    qr_b64 = base64.b64encode(buf.getvalue()).decode()

    # ------------------------------------------------------------------
    # STEP 6 — JSON response to the frontend
    # The frontend will display the image with: <img src="data:image/png;base64,{qr_password}">
    # The "password" field (plaintext) is returned alongside the QR code to provide
    # an accessible alternative for people who cannot scan/read a QR code
    # (visual impairment, no second device, etc.).
    # ------------------------------------------------------------------
    return {
        "statusCode": 200,
        "body": json.dumps({"qr_password": qr_b64, "password": password, "status": "ok"}),
    }
