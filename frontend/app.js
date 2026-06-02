/**
 * Application Frontend COFRAP (Vanilla JS)
 * Communication avec OpenFaaS API Gateway via Fetch API.
 */

const app = {
    // URL de l'API Gateway OpenFaaS (A configurer selon l'environnement, ici par défaut local/K3s)
    API_BASE_URL: "http://openfaas.cofrap.example.com/function",

    // Initialisation
    init() {
        this.bindEvents();
        this.showView('auth'); // Vue par défaut
    },

    // Gestion des événements
    bindEvents() {
        // Formulaire Créer
        document.getElementById('form-create').addEventListener('submit', (e) => {
            e.preventDefault();
            this.handleCreateAccount();
        });

        // Formulaire Authentification
        document.getElementById('form-auth').addEventListener('submit', (e) => {
            e.preventDefault();
            this.handleAuthentication();
        });

        // Formulaire Renouveler
        document.getElementById('form-renew').addEventListener('submit', (e) => {
            e.preventDefault();
            this.handleRenewal();
        });
    },

    // Navigation entre les vues
    showView(viewName) {
        // Masquer toutes les vues
        document.querySelectorAll('.view-section').forEach(el => el.classList.remove('active'));
        // Afficher la vue demandée
        document.getElementById(`view-${viewName}`).classList.add('active');
        
        // Mettre à jour l'apparence du menu de navigation
        document.querySelectorAll('.nav-link').forEach(el => el.classList.remove('active', 'fw-bold'));
        const navLink = document.getElementById(`nav-${viewName}`);
        if (navLink) navLink.classList.add('active', 'fw-bold');

        this.hideAlert();
    },

    // Afficher une notification globale (Succès ou Erreur)
    showAlert(message, type = 'danger') {
        const alertBox = document.getElementById('global-alert');
        alertBox.className = `alert alert-${type} mt-3`;
        alertBox.textContent = message;
        alertBox.classList.remove('d-none');
    },

    hideAlert() {
        const alertBox = document.getElementById('global-alert');
        alertBox.classList.add('d-none');
    },

    // Helper pour les appels API
    async apiCall(endpoint, payload) {
        try {
            const response = await fetch(`${this.API_BASE_URL}/${endpoint}`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(payload)
            });

            const data = await response.json();
            return { ok: response.ok, status: response.status, data };
        } catch (error) {
            console.error(`Erreur réseau sur ${endpoint}:`, error);
            return { ok: false, status: 500, data: { message: "Erreur de connexion au serveur." } };
        }
    },

    // =========================================================
    // LOGIQUE METIER
    // =========================================================

    // 1. CREER UN COMPTE
    async handleCreateAccount() {
        const username = document.getElementById('create-username').value.trim();
        if (!username) return;

        const btn = document.getElementById('btn-create-submit');
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm" aria-hidden="true"></span> Génération...';
        this.hideAlert();

        try {
            // Etape 1 : Générer le mot de passe
            const pwdResponse = await this.apiCall('generate-password', { username });
            
            if (!pwdResponse.ok) {
                throw new Error(pwdResponse.data.message || "Erreur lors de la création de l'utilisateur.");
            }

            // Etape 2 : Générer le 2FA
            const mfaResponse = await this.apiCall('generate-2fa', { username });
            
            if (!mfaResponse.ok) {
                throw new Error(mfaResponse.data.message || "Erreur lors de la génération du 2FA.");
            }

            // Succès : Affichage des QR Codes
            document.getElementById('qr-password-img').src = `data:image/png;base64,${pwdResponse.data.qr_password}`;
            document.getElementById('qr-2fa-img').src = `data:image/png;base64,${mfaResponse.data.qr_2fa}`;
            
            document.getElementById('create-qr-container').classList.remove('d-none');
            this.showAlert("Compte créé avec succès. Veuillez scanner vos QR Codes.", "success");
            
            // On vide le formulaire pour éviter les recréations accidentelles
            document.getElementById('form-create').reset();

        } catch (error) {
            this.showAlert(error.message, "danger");
        } finally {
            btn.disabled = false;
            btn.innerText = 'Générer les accès';
        }
    },

    // 2. AUTHENTIFICATION
    async handleAuthentication() {
        const username = document.getElementById('auth-username').value.trim();
        const password = document.getElementById('auth-password').value;
        const totp = document.getElementById('auth-totp').value.trim();

        if (!username || !password || !totp) return;

        const btn = document.getElementById('btn-auth-submit');
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm" aria-hidden="true"></span> Connexion...';
        this.hideAlert();

        try {
            // Appel à la fonction d'authentification (déduite de l'architecture)
            const authResponse = await this.apiCall('authenticate', { username, password, totp_code: totp });

            if (authResponse.ok) {
                this.showAlert("Authentification réussie ! Bienvenue.", "success");
                // Logique post-login (ex: redirection, stockage du JWT, etc.)
            } else {
                // Vérifier si l'erreur est liée à l'expiration (> 6 mois)
                // Le backend renvoie { "status": "expired" } en HTTP 403
                const isExpired = authResponse.status === 403 && authResponse.data.status === "expired";
                
                if (isExpired || (authResponse.data.message && authResponse.data.message.toLowerCase().includes('expiré'))) {
                    // Bascule vers la vue de renouvellement
                    document.getElementById('renew-username').value = username;
                    this.showView('renew');
                    this.showAlert("Votre compte a expiré. Vous devez regénérer vos accès.", "warning");
                } else {
                    throw new Error(authResponse.data.message || "Identifiants invalides.");
                }
            }
        } catch (error) {
            this.showAlert(error.message, "danger");
        } finally {
            btn.disabled = false;
            btn.innerText = 'Se connecter';
        }
    },

    // 3. RENOUVELLEMENT (SIMILAIRE A LA CREATION MAIS POUR COMPTE EXISTANT)
    async handleRenewal() {
        const username = document.getElementById('renew-username').value.trim();
        if (!username) return;

        const btn = document.getElementById('btn-renew-submit');
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm" aria-hidden="true"></span> Renouvellement...';
        this.hideAlert();

        try {
            // Note: Côté backend, il faudrait idéalement un endpoint "renew" spécifique 
            // ou bien un comportement adapté dans generate-password si l'utilisateur existe déjà.
            // Pour le TP, s'il faut réutiliser les mêmes fonctions, on simule l'appel :
            
            // /!\ Attention : generate-password plante actuellement si l'user existe (UniqueViolation).
            // Il vous faudra potentiellement adapter le handler backend pour faire un UPDATE 
            // au lieu d'un INSERT si l'utilisateur est expiré. 
            // Je fais les appels ici comme demandé par le workflow Front-End.
            
            const pwdResponse = await this.apiCall('generate-password', { username, renew: true });
            if (!pwdResponse.ok) throw new Error(pwdResponse.data.message || "Erreur au renouvellement du mot de passe.");

            const mfaResponse = await this.apiCall('generate-2fa', { username });
            if (!mfaResponse.ok) throw new Error(mfaResponse.data.message || "Erreur au renouvellement du 2FA.");

            // Affichage des nouveaux QR Codes
            document.getElementById('renew-qr-password-img').src = `data:image/png;base64,${pwdResponse.data.qr_password}`;
            document.getElementById('renew-qr-2fa-img').src = `data:image/png;base64,${mfaResponse.data.qr_2fa}`;
            
            document.getElementById('renew-qr-container').classList.remove('d-none');
            this.showAlert("Renouvellement réussi. Scannez vos nouveaux codes.", "success");

        } catch (error) {
            this.showAlert(error.message, "danger");
            console.error("Il faut s'assurer que le backend autorise l'écrasement (UPDATE) si le compte est expiré.", error);
        } finally {
            btn.disabled = false;
            btn.innerText = 'Régénérer mes accès';
        }
    }
};

// Lancer l'application au chargement du DOM
document.addEventListener('DOMContentLoaded', () => {
    app.init();
});
