import os
from paths import CODE_ROOT
import glob
import json
import webbrowser
import urllib.request
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler

PORT = 8080
REDIRECT_URI = f"http://localhost:{PORT}/"

# Variables globales pour transmettre les données entre le serveur HTTP et le script principal
auth_code = None
client_id = None
client_secret = None

class OAuth2CallbackHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Désactiver les logs polluants du serveur HTTP de la console
        return

    def do_GET(self):
        global auth_code
        query = urllib.parse.urlparse(self.path).query
        params = urllib.parse.parse_qs(query)
        
        if "code" in params:
            auth_code = params["code"][0]
            
            # Page de succès stylisée
            html_content = """
            <!DOCTYPE html>
            <html lang="fr">
            <head>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                <title>Authentification Réussie - Amicale Laïque de Jonage</title>
                <style>
                    body {
                        font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                        background-color: #F0F4F8;
                        color: #1F2937;
                        display: flex;
                        justify-content: center;
                        align-items: center;
                        height: 100vh;
                        margin: 0;
                    }
                    .card {
                        background: white;
                        padding: 40px;
                        border-radius: 12px;
                        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
                        text-align: center;
                        max-width: 500px;
                        width: 100%;
                    }
                    .icon {
                        font-size: 64px;
                        color: #059669;
                        margin-bottom: 20px;
                    }
                    h1 {
                        color: #1E3A8A;
                        font-size: 24px;
                        margin-bottom: 10px;
                    }
                    p {
                        color: #4B5563;
                        font-size: 16px;
                        line-height: 1.5;
                        margin-bottom: 25px;
                    }
                    .badge {
                        display: inline-block;
                        background-color: #D1FAE5;
                        color: #065F46;
                        padding: 6px 16px;
                        border-radius: 9999px;
                        font-weight: bold;
                        font-size: 14px;
                    }
                </style>
            </head>
            <body>
                <div class="card">
                    <div class="icon">🟢</div>
                    <h1>Authentification Réussie !</h1>
                    <p>Vous avez autorisé avec succès l'application de gestion de l'Amicale Laïque de Jonage à envoyer des e-mails en votre nom.</p>
                    <div class="badge">Le refresh token a été récupéré avec succès</div>
                    <p style="margin-top: 20px; font-size: 14px; color: #9CA3AF;">Vous pouvez maintenant fermer cet onglet et retourner à la console Python.</p>
                </div>
            </body>
            </html>
            """
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html_content.encode("utf-8"))
        else:
            self.send_response(400)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"Code d'autorisation manquant dans la requete.")

def update_env_file(updates):
    """Met à jour le fichier .env local avec les nouvelles variables."""
    env_path = os.path.join(CODE_ROOT, ".env")
    existing_lines = []
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            existing_lines = f.readlines()
            
    updated_keys = set()
    new_lines = []
    
    for line in existing_lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            k, v = stripped.split("=", 1)
            k = k.strip()
            if k in updates:
                new_lines.append(f"{k}={updates[k]}\n")
                updated_keys.add(k)
                continue
        new_lines.append(line)
        
    for k, v in updates.items():
        if k not in updated_keys:
            new_lines.append(f"{k}={v}\n")
            
    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)

def run_helper():
    global client_id, client_secret, auth_code
    
    print("\n==========================================================")
    print(" 🎓 ASSISTANT D'AUTHENTIFICATION AUTOMATIQUE GMAIL OAUTH2 ")
    print("==========================================================")
    
    # 1. Trouver le fichier client_secret JSON dans le dossier
    json_files = glob.glob(os.path.join(CODE_ROOT, "client_secret_*.json"))
    if not json_files:
        print("❌ ERREUR : Aucun fichier 'client_secret_*.json' trouvé dans le dossier actuel.")
        print("Veuillez y déposer le fichier client_secret téléchargé depuis Google Cloud Console.")
        return
        
    secret_file = json_files[0]
    print(f"📁 Fichier détecté : {secret_file}")
    
    # 2. Charger les clés du fichier JSON
    try:
        with open(secret_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        config_type = "installed" if "installed" in data else "web"
        client_id = data[config_type]["client_id"]
        client_secret = data[config_type]["client_secret"]
    except Exception as e:
        print(f"❌ ERREUR lors de la lecture du fichier secret : {e}")
        return
        
    print(f"🔑 Client ID chargé : {client_id[:25]}...")
    
    # 3. Construire l'URL de consentement Google
    auth_base_url = "https://accounts.google.com/o/oauth2/auth"
    scopes = [
        "https://www.googleapis.com/auth/gmail.send",
        "https://mail.google.com/",
        "https://www.googleapis.com/auth/userinfo.email",
        "https://www.googleapis.com/auth/drive",
        "https://www.googleapis.com/auth/contacts"
    ]
    
    params = {
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": " ".join(scopes),
        "access_type": "offline",
        "prompt": "consent"
    }
    
    auth_url = f"{auth_base_url}?{urllib.parse.urlencode(params)}"
    
    # 4. Lancer un mini serveur HTTP temporaire
    server = HTTPServer(("localhost", PORT), OAuth2CallbackHandler)
    
    # 5. Ouvrir automatiquement le navigateur pour que l'utilisateur donne son consentement
    print("\n🌐 Ouverture de votre navigateur Internet pour l'autorisation Google...")
    webbrowser.open(auth_url)
    print("\n⚠️ IMPORTANCE CRITIQUE :")
    print("--------------------------------------------------------------------------------")
    print(" Sur l'écran de consentement de Google dans votre navigateur, vous DEVEZ")
    print(" impérativement COCHER LA CASE d'autorisation suivante :")
    print("   [x] Lire, envoyer, supprimer et gérer de manière permanente vos e-mails...")
    print(" ")
    print(" Si vous ne cochez pas cette case, Google bloquera l'envoi d'e-mails (Erreur 403).")
    print("--------------------------------------------------------------------------------\n")
    print("👉 Veuillez vous connecter à votre compte Gmail dans le navigateur, cocher la case d'autorisation et valider.")
    print("Attente du consentement de l'utilisateur (en attente sur l'onglet de votre navigateur)...")
    
    # Gérer la requête de redirection (bloquant jusqu'à réception du code)
    server.handle_request()
    server.server_close()
    
    if not auth_code:
        print("❌ ERREUR : Aucun code d'autorisation n'a été reçu.")
        return
        
    # 6. Échanger le code d'autorisation contre les jetons (Access & Refresh tokens)
    print("\n🔄 Échange du code contre les jetons de sécurité permanents auprès de Google...")
    token_url = "https://oauth2.googleapis.com/token"
    exchange_params = {
        "code": auth_code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": REDIRECT_URI,
        "grant_type": "authorization_code"
    }
    exchange_data = urllib.parse.urlencode(exchange_params).encode("utf-8")
    req = urllib.request.Request(token_url, data=exchange_data)
    
    try:
        with urllib.request.urlopen(req) as response:
            tokens = json.loads(response.read().decode("utf-8"))
    except Exception as e:
        print(f"❌ ERREUR lors de l'échange de jeton : {e}")
        return
        
    refresh_token = tokens.get("refresh_token")
    access_token = tokens.get("access_token")
    
    if not refresh_token:
        print("❌ ERREUR : Google n'a pas retourné de 'refresh_token'.")
        print("💡 Astuce : Allez sur la page des autorisations de votre compte Google, révoquez l'accès de l'application et relancez ce script.")
        return
        
    # 7. Récupérer l'adresse e-mail de l'utilisateur de manière automatique
    print("📧 Récupération de votre adresse Gmail d'envoi officielle...")
    userinfo_url = f"https://www.googleapis.com/oauth2/v3/userinfo?access_token={access_token}"
    try:
        with urllib.request.urlopen(userinfo_url) as response:
            user_info = json.loads(response.read().decode("utf-8"))
            gmail_email = user_info.get("email", "")
    except Exception:
        gmail_email = ""
        
    if not gmail_email:
        print("⚠️ Impossible de récupérer l'e-mail de manière automatique.")
        gmail_email = input("Veuillez saisir votre adresse Gmail d'envoi complète : ").strip()
        
    print(f"✅ Adresse Gmail détectée : {gmail_email}")
    
    # 8. Mettre à jour le fichier .env
    updates = {
        "GMAIL_CLIENT_ID": client_id,
        "GMAIL_CLIENT_SECRET": client_secret,
        "GMAIL_REFRESH_TOKEN": refresh_token,
        "GMAIL_USER_EMAIL": gmail_email
    }
    
    try:
        update_env_file(updates)
        print("\n==========================================================")
        print(" 🎉 FÉLICITATIONS ! CONFIGURATION GMAIL OAUTH2 TERMINÉE ! ")
        print("==========================================================")
        print("Les variables suivantes ont été automatiquement injectées dans votre fichier .env :")
        print(f"- GMAIL_CLIENT_ID     : {client_id[:25]}...")
        print("- GMAIL_CLIENT_SECRET : **********")
        print(f"- GMAIL_REFRESH_TOKEN : {refresh_token[:25]}...")
        print(f"- GMAIL_USER_EMAIL    : {gmail_email}")
        print("\nVotre application est maintenant configurée pour utiliser Gmail OAuth2 de manière sécurisée !")
        print("Vous pouvez dès à présent relancer l'application et utiliser le Mode Email !")
        print("==========================================================\n")
    except Exception as env_err:
        print(f"❌ Échec de la mise à jour du fichier .env : {env_err}")

if __name__ == "__main__":
    run_helper()
