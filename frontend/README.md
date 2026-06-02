# Documentation Frontend COFRAP

Ce dossier contient l'interface utilisateur web pour le portail d'authentification COFRAP. L'application est développée en HTML5 pur et Vanilla JavaScript, sans étape de build complexe.

## Prérequis

- **Python 3** (ou un autre serveur web local comme `http-server` via Node.js).
- **Backend OpenFaaS** fonctionnel et accessible.

## Comment lancer le Frontend en local

Pour des raisons de sécurité liées à la politique CORS des navigateurs et aux requêtes `fetch`, vous ne pouvez pas simplement double-cliquer sur le fichier `index.html`. Vous devez utiliser un serveur web local.

### Étape 1 : Ouvrir un terminal

Ouvrez un terminal ou une invite de commande et placez-vous dans le dossier `frontend` :

```bash
cd frontend
```

### Étape 2 : Lancer un serveur web local

Utilisez le module HTTP intégré à Python pour lancer un petit serveur. **Il est fortement conseillé d'utiliser le port 3000** (ou un autre port différent de 8080) pour éviter d'entrer en conflit avec le port par défaut d'OpenFaaS :

```bash
python -m http.server 3000
```

### Étape 3 : Accéder à l'application

Ouvrez votre navigateur web préféré et rendez-vous à l'adresse suivante :

[http://localhost:3000](http://localhost:3000)

## Configuration vers le Backend

Par défaut, le fichier `app.js` est configuré pour communiquer avec un cluster OpenFaaS local :

```javascript
API_BASE_URL: "http://127.0.0.1:8080/function",
```

Si votre backend OpenFaaS est hébergé sur une machine virtuelle distante (par exemple une VM GCP), vous devez ouvrir le fichier `app.js` et remplacer `127.0.0.1:8080` par l'adresse IP publique ou le nom de domaine de votre instance OpenFaaS.

```javascript
// Exemple :
API_BASE_URL: "http://34.120.x.x:8080/function",
```
