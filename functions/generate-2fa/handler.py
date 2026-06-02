# =============================================================================
# Fonction OpenFaaS : generate-2fa
# Rôle : Générer un secret TOTP pour un utilisateur existant,
#        le chiffrer en BDD et retourner un QR code compatible Google Authenticator
#
# Entrée  (JSON) : { "username": "alice" }
# Sortie  (JSON) : { "qr_2fa": "<base64 PNG>", "status": "ok" }
#
# Flux complet :
#   1. Reçoit un username (l'utilisateur doit déjà exister en BDD)
#   2. Génère un secret TOTP aléatoire (32 caractères base32)
#   3. Chiffre ce secret avec Fernet avant de le stocker en BDD
#   4. Met à jour la colonne mfa de l'utilisateur dans PostgreSQL
#   5. Génère un QR code au format otpauth:// (compatible Google Authenticator)
#   6. Retourne le QR code encodé en base64
#
# Cette fonction est appelée APRÈS generate-password lors de la création de compte.
# =============================================================================

import json
import os
import io
import base64

import psycopg2
import pyotp
import qrcode
from cryptography.fernet import Fernet

# Nom de l'application affiché dans Google Authenticator
ISSUER = "COFRAP"

_conn = None


def _read_secret(key: str) -> str:
    """
    Lit une valeur sensible depuis les secrets Kubernetes montés par OpenFaaS.
    Fallback sur les variables d'environnement pour les tests locaux.
    """
    path = f"/var/openfaas/secrets/{key}"
    try:
        with open(path) as f:
            return f.read().strip()
    except FileNotFoundError:
        return os.environ.get(key, "")


def _get_db():
    """
    Retourne une connexion PostgreSQL active, réutilisée entre les appels.
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
    Point d'entrée appelé par OpenFaaS à chaque requête HTTP POST.
    """

    # ------------------------------------------------------------------
    # ÉTAPE 1 — Lecture et validation du corps de la requête
    # ------------------------------------------------------------------
    try:
        body = json.loads(event.body)
        username = str(body.get("username", "")).strip()
    except (json.JSONDecodeError, AttributeError):
        return {"statusCode": 400, "body": json.dumps({"status": "error", "message": "JSON invalide"})}

    if not username:
        return {"statusCode": 400, "body": json.dumps({"status": "error", "message": "username requis"})}

    # ------------------------------------------------------------------
    # ÉTAPE 2 — Génération du secret TOTP
    # pyotp.random_base32() génère une clé secrète de 32 caractères base32.
    # C'est cette clé qui est partagée entre le serveur et l'app d'auth (Google Authenticator).
    # À partir de cette clé + l'heure actuelle, on calcule un code à 6 chiffres valide 30s.
    # ------------------------------------------------------------------
    totp_secret = pyotp.random_base32()

    # ------------------------------------------------------------------
    # ÉTAPE 3 — Chiffrement du secret TOTP avec Fernet
    # Le secret TOTP ne doit jamais être stocké en clair en BDD.
    # La clé Fernet vient du secret K8s "encryption-key" → fichier FERNET_KEY.
    # ------------------------------------------------------------------
    fernet = Fernet(_read_secret("FERNET_KEY").encode())
    encrypted_secret = fernet.encrypt(totp_secret.encode()).decode()

    # ------------------------------------------------------------------
    # ÉTAPE 4 — Mise à jour de la colonne mfa en base de données
    # On UPDATE (et non INSERT) car l'utilisateur a déjà été créé par generate-password.
    # Si l'utilisateur n'existe pas, rowcount == 0 → on retourne une erreur.
    # ------------------------------------------------------------------
    try:
        conn = _get_db()
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE users SET mfa = %s WHERE username = %s",
                (encrypted_secret, username),
            )
            # rowcount indique le nombre de lignes modifiées
            if cur.rowcount == 0:
                conn.rollback()
                return {"statusCode": 404, "body": json.dumps({"status": "error", "message": "Utilisateur introuvable"})}
        conn.commit()
    except Exception as e:
        return {"statusCode": 500, "body": json.dumps({"status": "error", "message": str(e)})}

    # ------------------------------------------------------------------
    # ÉTAPE 5 — Génération du QR code au format otpauth://
    # Ce format est le standard reconnu par Google Authenticator, Authy, etc.
    # L'URL encode : le secret TOTP, l'issuer (COFRAP) et le nom du compte.
    # L'utilisateur scanne ce QR avec son app d'authentification.
    # ------------------------------------------------------------------
    # Exemple d'URL générée : otpauth://totp/COFRAP:alice?secret=JBSWY3DPEHPK3PXP&issuer=COFRAP
    otp_uri = pyotp.totp.TOTP(totp_secret).provisioning_uri(
        name=username,
        issuer_name=ISSUER,
    )

    qr = qrcode.QRCode(version=1, box_size=8, border=4)
    qr.add_data(otp_uri)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")

    # Encodage en base64 en mémoire (pas d'écriture sur disque)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    qr_b64 = base64.b64encode(buf.getvalue()).decode()

    # ------------------------------------------------------------------
    # ÉTAPE 6 — Réponse JSON au frontend
    # Le frontend affiche le QR avec : <img src="data:image/png;base64,{qr_2fa}">
    # ------------------------------------------------------------------
    return {
        "statusCode": 200,
        "body": json.dumps({"qr_2fa": qr_b64, "status": "ok"}),
    }
