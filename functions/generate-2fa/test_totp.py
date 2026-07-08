"""
Local TOTP test — no DB, no OpenFaaS
Run with: python test_totp.py
"""
import pyotp

# --- Step 1: secret generation (what generate-2fa does) ---
secret = pyotp.random_base32()
print("Generated secret :", secret)

# --- Step 2: code generation (what Google Authenticator does) ---
totp = pyotp.TOTP(secret)
code = totp.now()
print("Current code     :", code)

# --- Step 3: verification (what authenticate will do) ---
valide = totp.verify(code)
print("Code valid?      :", valide)  # should print True

# --- Step 4: test with a wrong code ---
faux_code = "000000"
print("Wrong code valid?", totp.verify(faux_code))  # should print False
