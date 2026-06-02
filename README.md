# MSPR Bloc 2 — COFRAP Serverless

**EPSI EISI I2 — TPRE921**

Système d'authentification serverless : génération de mots de passe, 2FA TOTP, et authentification avec expiration de compte.

## Stack

- **Fonctions** : Python 3.11 sur OpenFaaS Community
- **Infra** : K3s baremetal (2 VMs GCP Compute Engine e2-small)
- **BDD** : PostgreSQL 16 (Helm Bitnami)
- **Registre** : Docker Hub
- **Frontend** : HTML5 + Vanilla JS + Bootstrap 5

## Structure

```
functions/
  generate-password/   # Génère mdp 24 chars + QR code
  generate-2fa/        # Génère secret TOTP + QR code
  authenticate/        # Vérifie mdp + TOTP + expiration 6 mois
frontend/              # Portail web
k8s/                   # Manifests Kubernetes (secrets, etc.)
stack.yml              # Config déploiement OpenFaaS
```

## Équipe

| Membre | Rôle |
|--------|------|
| Jihan | Projet Manager |
| Justin | Lead Ingénieur Cloud & DevOps |
| Mathieu | Développeur back/front |
| Alexandre | Développeur back/front |
