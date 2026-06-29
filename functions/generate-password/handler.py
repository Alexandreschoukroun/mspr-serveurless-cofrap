# =============================================================================
# Fonction OpenFaaS : generate-password
# Rôle : Créer un nouvel utilisateur dans la BDD avec un mot de passe sécurisé
#        et retourner ce mot de passe sous forme de QR code (affiché UNE seule fois)
#
# Entrée  (JSON) : { "username": "alice" }
# Sortie  (JSON) : { "qr_password": "<base64 PNG>", "password": "<mot de passe en clair>", "status": "ok" }
#
# Flux complet :
#   1. Reçoit un username via POST HTTP
#   2. Génère un mot de passe aléatoire de 24 caractères
#   3. Chiffre ce mot de passe avec Fernet (AES-128) avant de le stocker en BDD
#   4. Insère la ligne utilisateur dans PostgreSQL
#   5. Génère un QR code PNG du mot de passe EN CLAIR (pour que l'user le scanne)
#   6. Retourne le QR code encodé en base64
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

# Jeu de caractères pour le mot de passe : majuscules + minuscules + chiffres + spéciaux
# secrets.choice() est cryptographiquement sûr (contrairement à random.choice)
CHARSET = string.ascii_letters + string.digits + "!@#$%&*"

# Connexion PostgreSQL réutilisée entre les appels (OpenFaaS garde le process actif)
_conn = None


def _read_secret(key: str) -> str:
    """
    Lit une valeur sensible depuis les secrets Kubernetes montés par OpenFaaS.

    En production (OpenFaaS sur K3s) :
      Les secrets K8s sont montés comme fichiers dans /var/openfaas/secrets/
      Ex : le secret "db-credentials" avec la clé "DB_HOST"
           → fichier /var/openfaas/secrets/DB_HOST

    En local (tests) :
      Si le fichier n'existe pas, on cherche dans les variables d'environnement.
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
    Cela évite d'ouvrir une nouvelle connexion à chaque appel de la fonction.
    """
    global _conn
    if _conn is None or _conn.closed:
        _conn = psycopg2.connect(
            host=_read_secret("DB_HOST"),         # IP interne du service PostgreSQL dans K8s
            database=_read_secret("DB_NAME"),     # cofrapdb
            user=_read_secret("DB_USER"),         # cofrapuser
            password=_read_secret("DB_PASSWORD"),
            connect_timeout=5,
        )
    return _conn


def handle(event, context):
    """
    Point d'entrée appelé par OpenFaaS à chaque requête HTTP POST.
    event.body contient le JSON envoyé par le frontend.
    """

    # ------------------------------------------------------------------
    # ÉTAPE 1 — Lecture et validation du corps de la requête
    # ------------------------------------------------------------------
    try:
        body = json.loads(event.body)
        username = str(body.get("username", "")).strip()
    except (json.JSONDecodeError, AttributeError):
        # Le corps n'est pas du JSON valide
        return {"statusCode": 400, "body": json.dumps({"status": "error", "message": "JSON invalide"})}

    if not username:
        return {"statusCode": 400, "body": json.dumps({"status": "error", "message": "username requis"})}

    # ------------------------------------------------------------------
    # ÉTAPE 2 — Génération du mot de passe aléatoire (24 caractères)
    # secrets.choice est cryptographiquement sûr (utilise /dev/urandom)
    # ------------------------------------------------------------------
    password = "".join(secrets.choice(CHARSET) for _ in range(24))

    # ------------------------------------------------------------------
    # ÉTAPE 3 — Chiffrement du mot de passe avec Fernet (AES-128-CBC)
    # Le mot de passe chiffré sera stocké en BDD.
    # La clé Fernet vient du secret K8s "encryption-key" → fichier FERNET_KEY.
    # Fernet garantit que sans la clé, le chiffré est illisible.
    # ------------------------------------------------------------------
    fernet = Fernet(_read_secret("FERNET_KEY").encode())
    encrypted_pwd = fernet.encrypt(password.encode()).decode()

    # ------------------------------------------------------------------
    # ÉTAPE 4 — Insertion en base de données PostgreSQL
    # - password  : mot de passe CHIFFRÉ (jamais en clair en BDD)
    # - mfa       : vide pour l'instant, rempli par generate-2fa ensuite
    # - gendate   : timestamp Unix de création (sert à calculer l'expiration à 6 mois)
    # - expired   : 0 = compte valide
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
        # La contrainte UNIQUE sur username empêche les doublons en BDD
        _conn.rollback()
        return {"statusCode": 409, "body": json.dumps({"status": "error", "message": "Utilisateur déjà existant"})}
    except Exception as e:
        return {"statusCode": 500, "body": json.dumps({"status": "error", "message": str(e)})}

    # ------------------------------------------------------------------
    # ÉTAPE 5 — Génération du QR code avec le mot de passe EN CLAIR
    # L'utilisateur scannera ce QR avec son téléphone pour mémoriser son mdp.
    # IMPORTANT : ce QR est affiché UNE SEULE FOIS côté frontend.
    # On encode l'image PNG en base64 pour pouvoir la transporter dans du JSON.
    # ------------------------------------------------------------------
    qr = qrcode.QRCode(version=1, box_size=8, border=4)
    qr.add_data(password)       # Le mot de passe en clair va dans le QR
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")

    buf = io.BytesIO()          # Buffer en mémoire (pas d'écriture disque)
    img.save(buf, format="PNG")
    qr_b64 = base64.b64encode(buf.getvalue()).decode()

    # ------------------------------------------------------------------
    # ÉTAPE 6 — Réponse JSON au frontend
    # Le frontend affichera l'image avec : <img src="data:image/png;base64,{qr_password}">
    # Le champ "password" (texte en clair) est renvoyé en plus du QR code pour permettre
    # une alternative accessible aux personnes ne pouvant pas scanner/lire un QR code
    # (déficience visuelle, absence de second appareil, etc.).
    # ------------------------------------------------------------------
    return {
        "statusCode": 200,
        "body": json.dumps({"qr_password": qr_b64, "password": password, "status": "ok"}),
    }
