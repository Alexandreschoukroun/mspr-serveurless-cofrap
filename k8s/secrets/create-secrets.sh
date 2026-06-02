#!/usr/bin/env bash
# Crée les deux Secrets Kubernetes nécessaires aux fonctions COFRAP.
# À exécuter UNE SEULE FOIS après l'installation du cluster.
#
# Usage :
#   chmod +x create-secrets.sh
#   ./create-secrets.sh
#
# Prérequis : kubectl configuré sur le bon contexte K3s.

set -euo pipefail

NAMESPACE="openfaas-fn"

# ---------------------------------------------------------------------------
# Vérification du namespace
# ---------------------------------------------------------------------------
if ! kubectl get namespace "$NAMESPACE" &>/dev/null; then
  echo "[ERREUR] Le namespace '$NAMESPACE' n'existe pas."
  echo "         Déployer OpenFaaS avant de créer les secrets."
  exit 1
fi

# ---------------------------------------------------------------------------
# Saisie interactive des valeurs sensibles
# (évite de les écrire dans un fichier ou l'historique shell)
# ---------------------------------------------------------------------------
echo "=== Secret : db-credentials ==="
read -rp "DB_HOST (ex: postgresql.openfaas-fn.svc.cluster.local) : " DB_HOST
read -rp "DB_NAME (ex: cofrapdb) : " DB_NAME
read -rp "DB_USER (ex: cofrapuser) : " DB_USER
read -rsp "DB_PASSWORD : " DB_PASSWORD
echo ""

echo ""
echo "=== Secret : encryption-key ==="
echo "Génération automatique d'une clé Fernet..."
FERNET_KEY=$(python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
echo "Clé générée (à conserver en lieu sûr) : $FERNET_KEY"
echo ""

# ---------------------------------------------------------------------------
# Création des Secrets via kubectl
# --from-literal crée un Secret dont chaque clé = un fichier dans le pod.
# OpenFaaS monte ces fichiers dans /var/openfaas/secrets/.
# ---------------------------------------------------------------------------
kubectl create secret generic db-credentials \
  --namespace="$NAMESPACE" \
  --from-literal=DB_HOST="$DB_HOST" \
  --from-literal=DB_NAME="$DB_NAME" \
  --from-literal=DB_USER="$DB_USER" \
  --from-literal=DB_PASSWORD="$DB_PASSWORD" \
  --save-config \
  --dry-run=client -o yaml | kubectl apply -f -

echo "[OK] Secret 'db-credentials' créé dans le namespace '$NAMESPACE'."

kubectl create secret generic encryption-key \
  --namespace="$NAMESPACE" \
  --from-literal=FERNET_KEY="$FERNET_KEY" \
  --save-config \
  --dry-run=client -o yaml | kubectl apply -f -

echo "[OK] Secret 'encryption-key' créé dans le namespace '$NAMESPACE'."

echo ""
echo "=== Secrets créés avec succès ==="
echo "IMPORTANT : conservez la clé Fernet dans un gestionnaire de mots de passe."
echo "Elle est nécessaire pour déchiffrer les mots de passe en BDD."
