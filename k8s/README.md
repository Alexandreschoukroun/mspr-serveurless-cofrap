# Infrastructure Kubernetes — COFRAP Serverless

Mise en place complète de l'infrastructure sur un cluster **K3s baremetal** (2 VMs GCP e2-small) :
OpenFaaS + PostgreSQL + déploiement des 3 fonctions Python.

## Prérequis

| Outil | Version minimale | Installation |
|---|---|---|
| `kubectl` | 1.28+ | [doc officielle](https://kubernetes.io/docs/tasks/tools/) |
| `helm` | 3.12+ | `curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 \| bash` |
| `faas-cli` | 0.16+ | `curl -sSL https://cli.openfaas.com \| sh` |
| `docker` | 24+ | [doc officielle](https://docs.docker.com/engine/install/) |
| `gh` (GitHub CLI) | 2.0+ | [doc officielle](https://cli.github.com/) — optionnel, pour gérer les secrets Actions |
| `python3` + `cryptography` | 3.11+ | `pip install cryptography` (pour générer la clé Fernet) |

**Vérifier que kubectl pointe sur le bon cluster :**
```bash
kubectl config current-context
kubectl get nodes
```

---

## Structure du répertoire

```
k8s/
├── openfaas/
│   ├── namespaces.yaml       # Namespaces openfaas + openfaas-fn
│   ├── values.yaml           # Helm values OpenFaaS (tuning cluster e2-small)
│   └── gateway-ingress.yaml  # Ingress Traefik vers le gateway
├── postgresql/
│   └── values.yaml           # Helm Bitnami PostgreSQL + init schéma
└── secrets/
    ├── db-credentials.yaml.example   # Template secret BDD
    ├── encryption-key.yaml.example   # Template secret Fernet
    ├── create-secrets.sh             # Script interactif de création
    └── .gitignore                    # Protège contre le commit de vraies valeurs
```

---

## Étape 1 — Namespaces OpenFaaS

OpenFaaS utilise deux namespaces distincts :
- `openfaas` : composants système (gateway, faas-netes, idler…)
- `openfaas-fn` : pods des fonctions déployées + secrets

```bash
kubectl apply -f openfaas/namespaces.yaml
```

---

## Étape 2 — Installation OpenFaaS via Helm

### Ajouter le repo Helm

```bash
helm repo add openfaas https://openfaas.github.io/faas-netes/
helm repo update
```

### Installer le chart

```bash
helm upgrade --install openfaas openfaas/openfaas \
  --namespace openfaas \
  --values openfaas/values.yaml
```

### Vérifier l'installation

```bash
# Attendre que tous les pods soient Running
kubectl rollout status deploy/gateway -n openfaas

# Récupérer le mot de passe admin généré automatiquement
OPENFAAS_PASSWORD=$(kubectl get secret -n openfaas basic-auth \
  -o jsonpath="{.data.basic-auth-password}" | base64 -d)
echo "Mot de passe admin OpenFaaS : $OPENFAAS_PASSWORD"
```

### Configurer faas-cli

```bash
# Remplacer <GATEWAY_HOSTNAME> par l'hostname de l'Ingress (voir étape 3)
export OPENFAAS_URL=http://<GATEWAY_HOSTNAME>

faas-cli login --username admin --password "$OPENFAAS_PASSWORD"
```

> **Note scale-to-zero** : `faasIdler` est activé dans `values.yaml`. Les fonctions sans trafic
> depuis 5 minutes descendent à 0 replica (démarrage ~2 s au prochain appel).
> Désactiver avec `faasIdler.create: false` si la latence à froid est inacceptable.

---

## Étape 3 — Ingress Traefik + Cloudflare

K3s intègre Traefik v2. Le domaine est résolu via Cloudflare qui proxie le trafic
vers l'IP externe du nœud GCP.

### Configuration Cloudflare

1. Récupérer l'IP externe du nœud GCP :
```bash
kubectl get nodes -o wide
# Colonne EXTERNAL-IP
```

2. Dans le dashboard Cloudflare, créer un enregistrement DNS :
   - **Type** : A
   - **Nom** : `openfaas` (ou le sous-domaine souhaité)
   - **Contenu** : IP externe GCP
   - **Proxy** : activé (nuage orange)

3. Dans **SSL/TLS > Overview**, choisir le mode :
   - `Flexible` — Cloudflare ↔ cluster en HTTP (le plus simple, aucune cert à gérer)
   - `Full` — Cloudflare ↔ cluster en HTTPS (recommandé en production)

### Déployer l'Ingress

```bash
# Remplacer le placeholder par le FQDN Cloudflare, ex: openfaas.cofrap.example.com
sed -i 's/<GATEWAY_HOSTNAME>/openfaas.cofrap.example.com/' openfaas/gateway-ingress.yaml

kubectl apply -f openfaas/gateway-ingress.yaml
```

### Mode Full SSL (optionnel, production)

Si le mode Cloudflare est `Full` ou `Full Strict`, Traefik doit présenter un certificat TLS.
Installer cert-manager et un certificat Let's Encrypt :

```bash
# Installer cert-manager
helm repo add jetstack https://charts.jetstack.io && helm repo update
helm upgrade --install cert-manager jetstack/cert-manager \
  --namespace cert-manager --create-namespace \
  --set crds.enabled=true

# Créer un ClusterIssuer Let's Encrypt (remplacer l'email)
kubectl apply -f - <<EOF
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-prod
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory
    email: tene.justin@gmail.com
    privateKeySecretRef:
      name: letsencrypt-prod
    solvers:
      - http01:
          ingress:
            class: traefik
EOF
```

Puis décommenter les sections `tls:` et les annotations Traefik dans `openfaas/gateway-ingress.yaml`,
et ajouter l'annotation cert-manager :
```yaml
annotations:
  cert-manager.io/cluster-issuer: letsencrypt-prod
```

### Vérifier

```bash
curl -u admin:"$OPENFAAS_PASSWORD" https://openfaas.cofrap.example.com/healthz
# Attendu : OK
```

---

## Étape 4 — Installation PostgreSQL (Bitnami Helm)

### Éditer les mots de passe dans values.yaml

Avant de déployer, remplacer les placeholders dans `postgresql/values.yaml` :
```yaml
auth:
  postgresPassword: "<POSTGRES_ADMIN_PASSWORD>"   # mot de passe du superuser postgres
  password: "<COFRAP_DB_PASSWORD>"                 # mot de passe de cofrapuser
```

> Ces valeurs sont uniquement dans `values.yaml` lors du premier `helm install`.
> Après installation, elles sont stockées dans un Secret K8s géré par Bitnami.
> Ne pas committer `postgresql/values.yaml` avec de vraies valeurs — utiliser
> des variables d'environnement ou un gestionnaire de secrets (ex: Vault, SOPS).

### Ajouter le repo Bitnami

```bash
helm repo add bitnami https://charts.bitnami.com/bitnami
helm repo update
```

### Déployer PostgreSQL dans openfaas-fn

```bash
helm upgrade --install postgresql bitnami/postgresql \
  --namespace openfaas-fn \
  --values postgresql/values.yaml
```

### Vérifier

```bash
kubectl rollout status statefulset/postgresql-primary -n openfaas-fn

# Tester la connexion depuis un pod temporaire
kubectl run pg-test --rm -it --restart=Never \
  --image=postgres:16 \
  --namespace=openfaas-fn \
  -- psql -h postgresql -U cofrapuser -d cofrapdb -c "\dt"
# Attendu : liste la table users
```

**Nom DNS interne** utilisable par les fonctions :
```
postgresql.openfaas-fn.svc.cluster.local
```
C'est la valeur à mettre dans `DB_HOST` lors de la création des secrets (étape 5).

---

## Étape 5 — Création des secrets fonctions

Les deux secrets doivent être dans le namespace `openfaas-fn`.

### Option A — Script interactif (recommandé)

```bash
chmod +x secrets/create-secrets.sh
./secrets/create-secrets.sh
```

Le script :
1. Demande les credentials BDD de manière interactive (pas d'historique shell)
2. Génère automatiquement une clé Fernet aléatoire
3. Crée les deux Secrets dans `openfaas-fn` via `kubectl apply`

### Option B — Création manuelle via kubectl

```bash
# Générer la clé Fernet
FERNET_KEY=$(python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")

# Secret BDD
kubectl create secret generic db-credentials \
  --namespace=openfaas-fn \
  --from-literal=DB_HOST="postgresql.openfaas-fn.svc.cluster.local" \
  --from-literal=DB_NAME="cofrapdb" \
  --from-literal=DB_USER="cofrapuser" \
  --from-literal=DB_PASSWORD="<mot_de_passe_cofrapuser>"

# Secret chiffrement
kubectl create secret generic encryption-key \
  --namespace=openfaas-fn \
  --from-literal=FERNET_KEY="$FERNET_KEY"
```

### Option C — À partir des templates YAML

```bash
# Copier les templates
cp secrets/db-credentials.yaml.example secrets/db-credentials.yaml
cp secrets/encryption-key.yaml.example secrets/encryption-key.yaml

# Éditer en remplaçant les placeholders <BASE64_...> par les valeurs encodées
# Encoder : echo -n "valeur" | base64
vim secrets/db-credentials.yaml
vim secrets/encryption-key.yaml

kubectl apply -f secrets/db-credentials.yaml
kubectl apply -f secrets/encryption-key.yaml

# NE PAS committer db-credentials.yaml et encryption-key.yaml (protégés par .gitignore)
```

### Vérifier les secrets

```bash
kubectl get secrets -n openfaas-fn
# Attendu : db-credentials et encryption-key dans la liste

# Vérifier les clés présentes (pas les valeurs)
kubectl describe secret db-credentials -n openfaas-fn
kubectl describe secret encryption-key -n openfaas-fn
```

---

## Étape 6 — Déploiement des fonctions

Les 3 fonctions sont déployées via le pipeline GitHub Actions (`.github/workflows/deploy.yml`)
ou manuellement avec `faas-cli`. Les images sont publiées sur **ghcr.io/tenjustin** et
référencées dans `stack.yml`.

### Référence des fonctions

| Fonction | Rôle | Entrée (JSON) | Sortie (JSON) |
|---|---|---|---|
| `generate-password` | Crée un utilisateur en BDD, génère un mot de passe chiffré (Fernet) et retourne un QR code PNG (affiché **une seule fois**) | `{"username": "alice"}` | `{"qr_password": "<base64 PNG>", "status": "ok"}` |
| `generate-2fa` | Génère un secret TOTP pour un utilisateur existant, le chiffre en BDD et retourne un QR code compatible Google Authenticator | `{"username": "alice"}` | `{"qr_2fa": "<base64 PNG>", "status": "ok"}` |
| `authenticate` | Vérifie l'identité : mot de passe + TOTP + expiration du compte (> 6 mois) | `{"username": "alice", "password": "...", "totp_code": "123456"}` | `{"status": "ok"\|"expired"\|"error", "message": "..."}` |

**Ordre d'utilisation lors de la création d'un compte** :
1. `generate-password` → crée l'utilisateur et retourne le QR mot de passe
2. `generate-2fa` → associe le TOTP et retourne le QR à scanner dans Google Authenticator
3. `authenticate` → connexion normale à chaque usage

---

### Déploiement automatique (GitHub Actions — recommandé)

Un `push` sur la branche `main` déclenche automatiquement :
1. Build des 3 images via `faas-cli build -f stack.yml`
2. Push sur `ghcr.io` avec le `GITHUB_TOKEN` automatique
3. Déploiement sur le gateway OpenFaaS

**Secrets GitHub à configurer** (`Settings → Secrets → Actions`) :

| Secret | Valeur |
|---|---|
| `OPENFAAS_URL` | URL publique du gateway, ex. `https://openfaas.cofrap.example.com` |
| `OPENFAAS_PASSWORD` | Mot de passe admin récupéré à l'étape 2 |

### Déploiement manuel

#### Prérequis

- Authentifié sur ghcr.io :
  ```bash
  echo "<GITHUB_TOKEN>" | docker login ghcr.io -u <GITHUB_USERNAME> --password-stdin
  ```
- `OPENFAAS_URL` exporté et faas-cli authentifié (voir étape 2)

#### Déployer une fonction spécifique

```bash
# Depuis la racine du projet (là où se trouve stack.yml)
faas-cli template store pull python3-http

faas-cli build -f stack.yml --filter generate-password
faas-cli push -f stack.yml --filter generate-password
faas-cli deploy -f stack.yml --filter generate-password
```

#### Déployer les 3 fonctions d'un coup

```bash
faas-cli template store pull python3-http
faas-cli up -f stack.yml
# Équivalent à : build + push + deploy pour toutes les fonctions
```

### Vérifier le déploiement

```bash
faas-cli list
# Attendu :
# Function            Invocations    Replicas
# authenticate        0              1
# generate-2fa        0              1
# generate-password   0              1
```

#### Tester les 3 fonctions

```bash
# 1. Créer un utilisateur (retourne un QR code PNG en base64)
curl -u admin:"$OPENFAAS_PASSWORD" \
  -X POST https://<GATEWAY_HOSTNAME>/function/generate-password \
  -H "Content-Type: application/json" \
  -d '{"username": "testuser"}'
# Attendu : {"qr_password": "<base64>", "status": "ok"}

# 2. Activer le 2FA (retourne un QR code otpauth:// pour Google Authenticator)
curl -u admin:"$OPENFAAS_PASSWORD" \
  -X POST https://<GATEWAY_HOSTNAME>/function/generate-2fa \
  -H "Content-Type: application/json" \
  -d '{"username": "testuser"}'
# Attendu : {"qr_2fa": "<base64>", "status": "ok"}

# 3. Authentifier (mot de passe en clair + code TOTP à 6 chiffres)
curl -u admin:"$OPENFAAS_PASSWORD" \
  -X POST https://<GATEWAY_HOSTNAME>/function/authenticate \
  -H "Content-Type: application/json" \
  -d '{"username": "testuser", "password": "<mot_de_passe>", "totp_code": "123456"}'
# Attendu : {"status": "ok", "message": "..."}
# Si compte expiré (> 6 mois) : {"status": "expired", "message": "..."}
```

### Mettre à jour une fonction

Modifier le handler puis pousser sur `main` — le pipeline CI/CD se charge du reste.
Pour un déploiement manuel :

```bash
faas-cli build -f stack.yml --filter <nom_fonction>
faas-cli push -f stack.yml --filter <nom_fonction>
faas-cli deploy -f stack.yml --filter <nom_fonction>
```

---

## Récapitulatif des commandes (ordre d'exécution)

```bash
# 1. Namespaces
kubectl apply -f k8s/openfaas/namespaces.yaml

# 2. OpenFaaS
helm repo add openfaas https://openfaas.github.io/faas-netes/ && helm repo update
helm upgrade --install openfaas openfaas/openfaas \
  --namespace openfaas --values k8s/openfaas/values.yaml

# 3. Ingress (après avoir remplacé <GATEWAY_HOSTNAME> par le FQDN Cloudflare)
sed -i 's/<GATEWAY_HOSTNAME>/openfaas.cofrap.example.com/' k8s/openfaas/gateway-ingress.yaml
kubectl apply -f k8s/openfaas/gateway-ingress.yaml

# 4. PostgreSQL (après avoir renseigné les mots de passe dans values.yaml)
helm repo add bitnami https://charts.bitnami.com/bitnami && helm repo update
helm upgrade --install postgresql bitnami/postgresql \
  --namespace openfaas-fn --values k8s/postgresql/values.yaml

# 5. Secrets
./k8s/secrets/create-secrets.sh

# 6. Fonctions — via GitHub Actions (push sur main) ou manuellement :
faas-cli template store pull python3-http
faas-cli up -f stack.yml
```

---

## Désinstallation

```bash
# Supprimer les fonctions
faas-cli remove -f stack.yml

# Supprimer les Helm releases
helm uninstall openfaas -n openfaas
helm uninstall postgresql -n openfaas-fn

# Supprimer les namespaces (supprime aussi les secrets et PVCs)
kubectl delete namespace openfaas openfaas-fn
```

> **Attention** : la suppression du namespace `openfaas-fn` supprime aussi le PersistentVolumeClaim
> de PostgreSQL. Les données BDD sont perdues si pas de backup préalable.
