# =============================================================================
# Fonction OpenFaaS : authenticate
# Rôle : Vérifier l'identité d'un utilisateur (mot de passe + TOTP + expiration)
#
# Entrée  (JSON) : { "username": "alice", "password": "...", "totp_code": "123456" }
# Sortie  (JSON) : { "status": "ok"|"expired"|"error", "message": "..." }
#
# Flux complet :
#   1. Reçoit username + password + totp_code via POST HTTP
#   2. Récupère la ligne utilisateur en BDD
#   3. Déchiffre le mot de passe stocké (Fernet) et compare avec la saisie
#   4. Déchiffre le secret TOTP (Fernet) et vérifie le code TOTP fourni
#   5. Vérifie que le compte n'a pas expiré (> 6 mois depuis gendate)
#      → Si expiré : marque expired=1 en BDD, retourne {"status": "expired"}
#      → Si valide  : retourne {"status": "ok"}
# =============================================================================

import json
import os
import time
import hmac

import psycopg2
import pyotp
from cryptography.fernet import Fernet, InvalidToken

# Durée de vie d'un compte : 183 jours (≈ 6 mois)
ACCOUNT_TTL_SECONDS = 183 * 24 * 3600

# Connexion PostgreSQL réutilisée entre les appels (OpenFaaS garde le process actif)
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
    Retourne une connexion PostgreSQL active.
    Crée la connexion si elle n'existe pas encore ou si elle a été fermée.
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
        password = str(body.get("password", "")).strip()
        totp_code = str(body.get("totp_code", "")).strip()
    except (json.JSONDecodeError, AttributeError):
        return {"statusCode": 400, "body": json.dumps({"status": "error", "message": "JSON invalide"})}

    if not username or not password or not totp_code:
        return {"statusCode": 400, "body": json.dumps({"status": "error", "message": "username, password et totp_code requis"})}

    # ------------------------------------------------------------------
    # ÉTAPE 2 — Récupération de l'utilisateur en base de données
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

    # Message générique pour ne pas révéler si le compte existe
    if row is None:
        return {"statusCode": 401, "body": json.dumps({"status": "error", "message": "Identifiants incorrects"})}

    db_password_enc, db_mfa_enc, gendate, expired_flag = row

    # ------------------------------------------------------------------
    # ÉTAPE 3 — Vérification du mot de passe
    # On déchiffre le mot de passe stocké puis on compare avec hmac.compare_digest
    # pour éviter les attaques par timing sur la comparaison de chaînes.
    # ------------------------------------------------------------------
    fernet = Fernet(_read_secret("FERNET_KEY").encode())
    try:
        db_password_clear = fernet.decrypt(db_password_enc.encode()).decode()
    except InvalidToken:
        return {"statusCode": 500, "body": json.dumps({"status": "error", "message": "Erreur de déchiffrement"})}

    if not hmac.compare_digest(db_password_clear, password):
        return {"statusCode": 401, "body": json.dumps({"status": "error", "message": "Identifiants incorrects"})}

    # ------------------------------------------------------------------
    # ÉTAPE 4 — Vérification du code TOTP
    # On déchiffre le secret TOTP stocké, puis on vérifie le code avec pyotp.
    # pyotp.TOTP.verify() accepte une fenêtre ±30 s pour compenser les décalages
    # d'horloge entre le smartphone et le serveur.
    # ------------------------------------------------------------------
    try:
        db_mfa_secret = fernet.decrypt(db_mfa_enc.encode()).decode()
    except InvalidToken:
        return {"statusCode": 500, "body": json.dumps({"status": "error", "message": "Erreur de déchiffrement MFA"})}

    totp = pyotp.TOTP(db_mfa_secret)
    if not totp.verify(totp_code, valid_window=1):
        return {"statusCode": 401, "body": json.dumps({"status": "error", "message": "Code TOTP invalide"})}

    # ------------------------------------------------------------------
    # ÉTAPE 5 — Vérification de l'expiration du compte (6 mois)
    # Si le compte est déjà marqué expired=1 ou si la date de création
    # dépasse 183 jours, on force expired=1 en BDD et on refuse la connexion.
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
    # ÉTAPE 6 — Authentification réussie
    # ------------------------------------------------------------------
    return {
        "statusCode": 200,
        "body": json.dumps({
            "status": "ok",
            "message": "Authentification réussie",
        }),
    }
