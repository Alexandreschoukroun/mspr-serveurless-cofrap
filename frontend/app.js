/**
 * COFRAP Frontend Application (Vanilla JS)
 * Communicates with the OpenFaaS API Gateway via the Fetch API.
 */

const app = {
    // OpenFaaS gateway URL — overridable via config.js mounted from a k8s ConfigMap
    API_BASE_URL: (window.COFRAP_CONFIG && window.COFRAP_CONFIG.OPENFAAS_URL) || "http://openfaas.k3s.homelab/function",

    // Storage key for the "colorblind mode" preference in the browser
    COLORBLIND_STORAGE_KEY: 'cofrap_colorblind_mode',

    // Initialization
    init() {
        this.bindEvents();
        this.applyColorblindMode(localStorage.getItem(this.COLORBLIND_STORAGE_KEY) || 'none');
        this.showView('auth'); // Default view
    },

    // Event handling
    bindEvents() {
        // Create form
        document.getElementById('form-create').addEventListener('submit', (e) => {
            e.preventDefault();
            this.handleCreateAccount();
        });

        // Authentication form
        document.getElementById('form-auth').addEventListener('submit', (e) => {
            e.preventDefault();
            this.handleAuthentication();
        });

        // Renew form
        document.getElementById('form-renew').addEventListener('submit', (e) => {
            e.preventDefault();
            this.handleRenewal();
        });
    },

    // Navigation between views
    showView(viewName) {
        // Hide all views
        document.querySelectorAll('.view-section').forEach(el => el.classList.remove('active'));
        // Show the requested view
        document.getElementById(`view-${viewName}`).classList.add('active');

        // Update the navigation menu appearance
        document.querySelectorAll('.nav-link').forEach(el => el.classList.remove('active', 'fw-bold'));
        const navLink = document.getElementById(`nav-${viewName}`);
        if (navLink) navLink.classList.add('active', 'fw-bold');

        this.hideAlert();
    },

    // Show a global notification (Success or Error)
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

    // Changes the colorblind mode among: 'none', 'protanopia', 'deuteranopia', 'tritanopia'
    // and remembers the preference for future visits.
    setColorblindMode(mode) {
        this.applyColorblindMode(mode);
        localStorage.setItem(this.COLORBLIND_STORAGE_KEY, mode);
    },

    applyColorblindMode(mode) {
        document.body.classList.remove('colorblind-protanopia', 'colorblind-deuteranopia', 'colorblind-tritanopia');
        if (mode && mode !== 'none') {
            document.body.classList.add(`colorblind-${mode}`);
        }
        const select = document.getElementById('colorblind-select');
        if (select) select.value = mode || 'none';
    },

    // Shows/hides the plaintext password for the 'create' or 'renew' view
    togglePasswordVisibility(view) {
        const container = document.getElementById(`password-plain-${view}`);
        const btn = document.getElementById(`btn-toggle-password-${view}`);
        const isHidden = container.classList.contains('d-none');

        container.classList.toggle('d-none', !isHidden);
        btn.setAttribute('aria-pressed', String(isHidden));
        btn.textContent = isHidden ? 'Masquer le mot de passe en clair' : 'Afficher le mot de passe en clair';
    },

    // Copies the plaintext password to the clipboard
    async copyPassword(view) {
        const input = document.getElementById(`password-plain-input-${view}`);
        try {
            await navigator.clipboard.writeText(input.value);
            this.showAlert('Mot de passe copié dans le presse-papiers.', 'success');
        } catch (error) {
            console.error('Erreur lors de la copie du mot de passe:', error);
            this.showAlert('Impossible de copier automatiquement, veuillez sélectionner le texte manuellement.', 'warning');
        }
    },

    // Helper for API calls
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
    // BUSINESS LOGIC
    // =========================================================

    // 1. CREATE AN ACCOUNT
    async handleCreateAccount() {
        const username = document.getElementById('create-username').value.trim();
        if (!username) return;

        const btn = document.getElementById('btn-create-submit');
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm" aria-hidden="true"></span> Génération...';
        this.hideAlert();

        try {
            // Step 1: Generate the password
            const pwdResponse = await this.apiCall('generate-password', { username });

            if (!pwdResponse.ok) {
                throw new Error(pwdResponse.data.message || "Erreur lors de la création de l'utilisateur.");
            }

            // Step 2: Generate the 2FA
            const mfaResponse = await this.apiCall('generate-2fa', { username });

            if (!mfaResponse.ok) {
                throw new Error(mfaResponse.data.message || "Erreur lors de la génération du 2FA.");
            }

            // Success: display the QR codes
            document.getElementById('qr-password-img').src = `data:image/png;base64,${pwdResponse.data.qr_password}`;
            document.getElementById('qr-2fa-img').src = `data:image/png;base64,${mfaResponse.data.qr_2fa}`;
            document.getElementById('password-plain-input-create').value = pwdResponse.data.password || '';
            document.getElementById('password-plain-create').classList.add('d-none');
            document.getElementById('btn-toggle-password-create').setAttribute('aria-pressed', 'false');
            document.getElementById('btn-toggle-password-create').textContent = 'Afficher le mot de passe en clair';

            document.getElementById('create-qr-container').classList.remove('d-none');
            this.showAlert("Compte créé avec succès. Veuillez scanner vos QR Codes.", "success");
            
            // Clear the form to avoid accidental re-creation
            document.getElementById('form-create').reset();

        } catch (error) {
            this.showAlert(error.message, "danger");
        } finally {
            btn.disabled = false;
            btn.innerText = 'Générer les accès';
        }
    },

    // 2. AUTHENTICATION
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
            // Call the authentication function (inferred from the architecture)
            const authResponse = await this.apiCall('authenticate', { username, password, totp_code: totp });

            if (authResponse.ok) {
                this.showAlert("Authentification réussie ! Bienvenue.", "success");
                // Post-login logic (e.g. redirect, store the JWT, etc.)
            } else {
                // Check whether the error is related to expiration (> 6 months)
                // The backend returns { "status": "expired" } with HTTP 403
                const isExpired = authResponse.status === 403 && authResponse.data.status === "expired";

                if (isExpired || (authResponse.data.message && authResponse.data.message.toLowerCase().includes('expiré'))) {
                    // Switch to the renewal view
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

    // 3. RENEWAL (SIMILAR TO CREATION BUT FOR AN EXISTING ACCOUNT)
    async handleRenewal() {
        const username = document.getElementById('renew-username').value.trim();
        if (!username) return;

        const btn = document.getElementById('btn-renew-submit');
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm" aria-hidden="true"></span> Renouvellement...';
        this.hideAlert();

        try {
            // Note: On the backend side, a dedicated "renew" endpoint would ideally be needed,
            // or adapted behavior in generate-password when the user already exists.
            // For this assignment, since the same functions need to be reused, the call is simulated here:

            // /!\ Warning: generate-password currently crashes if the user already exists (UniqueViolation).
            // The backend handler will potentially need to be adapted to do an UPDATE
            // instead of an INSERT if the user is expired.
            // The calls are made here as required by the Front-End workflow.

            const pwdResponse = await this.apiCall('generate-password', { username, renew: true });
            if (!pwdResponse.ok) throw new Error(pwdResponse.data.message || "Erreur au renouvellement du mot de passe.");

            const mfaResponse = await this.apiCall('generate-2fa', { username });
            if (!mfaResponse.ok) throw new Error(mfaResponse.data.message || "Erreur au renouvellement du 2FA.");

            // Display the new QR codes
            document.getElementById('renew-qr-password-img').src = `data:image/png;base64,${pwdResponse.data.qr_password}`;
            document.getElementById('renew-qr-2fa-img').src = `data:image/png;base64,${mfaResponse.data.qr_2fa}`;
            document.getElementById('password-plain-input-renew').value = pwdResponse.data.password || '';
            document.getElementById('password-plain-renew').classList.add('d-none');
            document.getElementById('btn-toggle-password-renew').setAttribute('aria-pressed', 'false');
            document.getElementById('btn-toggle-password-renew').textContent = 'Afficher le mot de passe en clair';

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

// Start the application once the DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    app.init();
});
