"""
Test local du TOTP — sans BDD, sans OpenFaaS
Lance avec : python test_totp.py
"""
import pyotp

# --- Étape 1 : génération du secret (ce que fait generate-2fa) ---
secret = pyotp.random_base32()
print("Secret généré    :", secret)

# --- Étape 2 : génération du code (ce que fait Google Authenticator) ---
totp = pyotp.TOTP(secret)
code = totp.now()
print("Code actuel      :", code)

# --- Étape 3 : vérification (ce que fera authenticate) ---
valide = totp.verify(code)
print("Code valide ?    :", valide)  # doit afficher True

# --- Étape 4 : test avec un mauvais code ---
faux_code = "000000"
print("Faux code valide ?", totp.verify(faux_code))  # doit afficher False
