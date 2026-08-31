import base64
import urllib.parse
import urllib.request
import json
import smtplib
import os
import requests
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

def get_oauth2_access_token(client_id, client_secret, refresh_token):
    """
    Obtient un nouvel access token de Google en utilisant le refresh token.
    """
    url = "https://oauth2.googleapis.com/token"
    params = {
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token"
    }
    data = urllib.parse.urlencode(params).encode("utf-8")
    req = urllib.request.Request(url, data=data)
    try:
        with urllib.request.urlopen(req) as response:
            res = json.loads(response.read().decode("utf-8"))
            return res.get("access_token")
    except Exception as e:
        raise Exception(f"Échec de l'obtention de l'access token OAuth2 : {e}")

def send_email_with_attachment(to_email, subject, body, attachment_path, smtp_config):
    """
    Envoie un e-mail avec une pièce jointe via l'API Gmail HTTPS (recommandé pour contourner les pare-feux)
    ou via SMTP classique si OAuth2 n'est pas activé.
    """
    # Vérifier si OAuth2 Gmail est activé dans la config
    gmail_client_id = smtp_config.get("GMAIL_CLIENT_ID", "").strip()
    gmail_client_secret = smtp_config.get("GMAIL_CLIENT_SECRET", "").strip()
    gmail_refresh_token = smtp_config.get("GMAIL_REFRESH_TOKEN", "").strip()
    gmail_user = smtp_config.get("GMAIL_USER_EMAIL", "").strip()
    
    use_oauth2 = bool(gmail_client_id and gmail_client_secret and gmail_refresh_token and gmail_user)
    
    # Construction de l'e-mail au format MIME standard
    msg = MIMEMultipart()
    from_email = gmail_user if use_oauth2 else (smtp_config.get("SMTP_FROM_EMAIL", "").strip() or smtp_config.get("SMTP_USER", "").strip())
    msg['From'] = from_email
    msg['To'] = to_email
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain', 'utf-8'))
    
    if attachment_path and os.path.exists(attachment_path):
        filename = os.path.basename(attachment_path)
        with open(attachment_path, "rb") as attachment:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(attachment.read())
            encoders.encode_base64(part)
            part.add_header("Content-Disposition", f"attachment; filename= {filename}")
            msg.attach(part)
    else:
        raise FileNotFoundError(f"Le fichier d'attestation à joindre est introuvable : {attachment_path}")
        
    if use_oauth2:
        # --- MODE GMAIL API HTTPS (Port 443 - Garanti ouvert sur tous les pare-feux d'entreprise) ---
        print(f"Connexion sécurisée via l'API Gmail HTTPS pour {gmail_user}...")
        access_token = get_oauth2_access_token(gmail_client_id, gmail_client_secret, gmail_refresh_token)
        if not access_token:
            raise Exception("L'access token retourné par Google est vide.")
            
        # Encoder l'e-mail complet au format web-safe base64
        raw_message = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
        
        # URL officielle d'envoi de messages de l'API Gmail REST
        url = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        payload = {
            "raw": raw_message
        }
        
        # Envoi de la requête POST HTTPS (port 443 standard)
        response = requests.post(url, headers=headers, json=payload, timeout=15)
        if response.status_code != 200:
            raise Exception(f"Erreur API Gmail HTTP ({response.status_code}) : {response.text}")
            
        print("E-mail envoyé avec succès via l'API Gmail REST HTTPS !")
        
    else:
        # --- MODE SMTP CLASSIQUE ---
        host = smtp_config.get("SMTP_HOST", "").strip()
        port_str = smtp_config.get("SMTP_PORT", "587").strip()
        user = smtp_config.get("SMTP_USER", "").strip()
        password = smtp_config.get("SMTP_PASSWORD", "").strip()
        
        if not host or not user or not password:
            raise Exception("Configuration SMTP incomplète dans le .env (Host, User ou Password manquant).")
            
        try:
            port = int(port_str)
        except ValueError:
            port = 587
            
        if port == 465:
            server = smtplib.SMTP_SSL(host, port, timeout=12)
        else:
            server = smtplib.SMTP(host, port, timeout=12)
            server.ehlo()
            if port == 587 or host.endswith("gmail.com") or host.endswith("office365.com"):
                server.starttls()
                server.ehlo()
                
        server.login(user, password)
        server.sendmail(from_email, to_email, msg.as_string())
        server.quit()
