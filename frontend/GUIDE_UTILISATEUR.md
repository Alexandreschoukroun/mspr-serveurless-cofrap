# Guide d'Utilisation - Portail COFRAP Auth

Ce document explique comment utiliser l'application web d'authentification COFRAP.

L'application est composée de trois vues principales que vous pouvez sélectionner via le menu de navigation.

---

## 1. Créer un compte (Inscription)

1. Allez sur l'onglet **Inscription**.
2. Entrez un nom d'utilisateur (Username) de votre choix.
3. Cliquez sur **Générer les accès**.
4. Deux QR Codes s'affichent à l'écran :
   - Le premier contient votre **mot de passe sécurisé**. Vous devez le scanner pour le copier/sauvegarder, car il ne vous sera plus jamais affiché.
   - Le second contient la **clé secrète 2FA (TOTP)**. Vous devez le scanner avec une application d'authentification comme Google Authenticator ou Authy.
 
---

## 2. Se Connecter (Authentification)

1. Allez sur l'onglet **Connexion**.
2. Renseignez votre **Nom d'utilisateur**.
3. Renseignez votre **Mot de passe** (celui généré à l'étape 1).
4. Renseignez le **Code 2FA à 6 chiffres** généré en temps réel par votre application (Google Authenticator).
5. Cliquez sur **Se connecter**.
6. Si tout est correct, un message vert de succès apparaît.


---

## 3. Renouveler ses accès (Expiration)

Cette vue est "cachée" par défaut. Elle n'apparaît que si vous essayez de vous connecter (étape 2) et que le serveur vous indique que votre compte a **expiré** (vos codes datent de plus de 6 mois).
1. Un message rouge vous indique que le compte a expiré.
2. Cliquez sur le bouton **Régénérer mes accès**.
3. Comme pour l'inscription, **deux nouveaux QR Codes** apparaissent.
4. Vous devez scanner ces nouveaux QR Codes pour remplacer vos anciens accès.

---

## Architecture de Sécurité

- **Zéro mot de passe en clair** : La base de données PostgreSQL ne contient aucun mot de passe ou secret 2FA lisible. Tout est chiffré par le backend avant d'être sauvegardé.
- **Accès unique** : Les QR Codes générés lors de l'inscription ou du renouvellement ne sont affichés qu'une seule fois. Si l'utilisateur perd son mot de passe ou son téléphone, les accès actuels sont perdus.
- **Cycle de vie Serverless** : Chaque action (générer un mot de passe, se connecter) est une fonction indépendante exécutée à la demande sur le cluster K3s par OpenFaaS.
