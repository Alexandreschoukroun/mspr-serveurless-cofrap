#!/usr/bin/env bash
# Creates the two Kubernetes Secrets required by the COFRAP functions.
# Run ONLY ONCE after the cluster installation.
#
# Usage:
#   chmod +x create-secrets.sh
#   ./create-secrets.sh
#
# Prerequisite: kubectl configured on the correct K3s context.

set -euo pipefail

NAMESPACE="openfaas-fn"

# ---------------------------------------------------------------------------
# Namespace check
# ---------------------------------------------------------------------------
if ! kubectl get namespace "$NAMESPACE" &>/dev/null; then
  echo "[ERREUR] Le namespace '$NAMESPACE' n'existe pas."
  echo "         Déployer OpenFaaS avant de créer les secrets."
  exit 1
fi

# ---------------------------------------------------------------------------
# Interactive input of sensitive values
# (avoids writing them to a file or the shell history)
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
# Creating the Secrets via kubectl
# --from-literal creates a Secret where each key = a file in the pod.
# OpenFaaS mounts these files under /var/openfaas/secrets/.
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
