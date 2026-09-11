import os
import base64
import smtplib
import requests
import json
import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from paths import DATA_ROOT
from infrastructure.secret_store import SecretStore

class EmailRepository:
    """
    Service gérant la transmission sécurisée des courriels et l'audit d'envoi.
    """

    # Journal d'audit dans data/ : persistant, survit aux mises à jour de l'application
    AUDIT_FILE_PATH = os.path.join(DATA_ROOT, "email_audit.log")

    @classmethod
    def log_audit(cls, to_email: str, subject: str, status: str, error_message: str = "") -> None:
        """Enregistre un événement d'envoi de mail dans le journal d'audit."""
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = {
            "timestamp": timestamp,
            "to": to_email,
            "subject": subject,
            "status": status,
            "error": error_message
        }
        try:
            with open(cls.AUDIT_FILE_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
        except Exception as e:
            print(f"⚠️ Impossible d'écrire dans le journal d'audit des e-mails : {e}")

    @classmethod
    def send_email(cls, to_email: str, subject: str, body: str, attachment_path: str = "", html_body: str = None, inline_images: list = None, from_email: str = None, from_name: str = None) -> bool:
        """
        Envoie un e-mail avec pièce jointe en sélectionnant dynamiquement le meilleur canal configuré (Gmail API ou SMTP).
        Si html_body est fourni, une version HTML (multipart/alternative) est jointe au texte brut,
        avec les images inline éventuelles (liste de tuples (chemin, Content-ID)).
        `from_email` permet de choisir l'adresse d'expédition (doit être un alias vérifié du compte émetteur).
        `from_name` permet d'afficher un nom lisible dans la colonne « De » des messageries.
        """
        # Récupérer les identifiants depuis le SecretStore
        gmail_user = SecretStore.get_secret("GMAIL_USER_EMAIL")
        gmail_client_id = SecretStore.get_secret("GMAIL_CLIENT_ID")
        gmail_refresh = SecretStore.get_secret("GMAIL_REFRESH_TOKEN")
        
        smtp_host = SecretStore.get_secret("SMTP_HOST")
        smtp_port = SecretStore.get_secret("SMTP_PORT")
        smtp_user = SecretStore.get_secret("SMTP_USER")
        smtp_password = SecretStore.get_secret("SMTP_PASSWORD")
        smtp_from = SecretStore.get_secret("SMTP_FROM_EMAIL") or smtp_user

        use_oauth2 = bool(gmail_user and gmail_client_id and gmail_refresh)

        # Adresse d'expédition : adresse choisie dans l'IHM si fournie, sinon le compte configuré
        effective_from = (from_email or "").strip() or (gmail_user if use_oauth2 else smtp_from)

        # Construction du message MIME
        from email.utils import formataddr
        msg = MIMEMultipart()
        msg["Subject"] = subject
        msg["To"] = to_email
        # En-tête « De » : nom d'affichage lisible + adresse (format RFC 2822, accents encodés proprement)
        sender_name = (from_name or "").strip()
        if sender_name:
            try:
                msg["From"] = formataddr((sender_name, effective_from))
            except Exception:
                msg["From"] = effective_from
        else:
            msg["From"] = effective_from

        if html_body:
            # Version riche : texte brut + HTML, avec logos intégrés en pièces jointes inline
            from email.mime.image import MIMEImage
            alt_part = MIMEMultipart("alternative")
            alt_part.attach(MIMEText(body, "plain", "utf-8"))
            related_part = MIMEMultipart("related")
            related_part.attach(MIMEText(html_body, "html", "utf-8"))
            for img_path, img_cid in (inline_images or []):
                if img_path and os.path.exists(img_path):
                    with open(img_path, "rb") as f_img:
                        img_part = MIMEImage(f_img.read())
                    img_part.add_header("Content-ID", f"<{img_cid}>")
                    img_part.add_header("Content-Disposition", "inline", filename=os.path.basename(img_path))
                    related_part.attach(img_part)
            alt_part.attach(related_part)
            msg.attach(alt_part)
        else:
            msg.attach(MIMEText(body, "plain"))

        # Ajout des pièces jointes (prend en charge un chemin unique sous forme de chaîne ou une liste de chemins)
        attachments = []
        if attachment_path:
            if isinstance(attachment_path, list):
                attachments = attachment_path
            else:
                attachments = [attachment_path]

        for path in attachments:
            if path and os.path.exists(path):
                filename = os.path.basename(path)
                try:
                    # Nettoyer le nom du fichier pour n'avoir que de l'ASCII propre (évite le bug "noname" de Gmail avec les accents)
                    import unicodedata
                    ascii_filename = unicodedata.normalize('NFKD', filename).encode('ascii', 'ignore').decode('ascii')
                    if not ascii_filename:
                        ascii_filename = "attachment.dat"
                        
                    with open(path, "rb") as f:
                        part = MIMEBase("application", "octet-stream")
                        part.set_payload(f.read())
                    encoders.encode_base64(part)
                    part.add_header("Content-Disposition", f"attachment; filename={ascii_filename}")
                    msg.attach(part)
                except Exception as e:
                    cls.log_audit(to_email, subject, "FAIL", f"Erreur de lecture de la pièce jointe {filename} : {e}")
                    raise Exception(f"Impossible de lire la pièce jointe {filename} : {e}")

        if use_oauth2:
            try:
                # Mode Gmail REST API (sécurisé, port 443)
                from infrastructure.google_drive_client import GoogleDriveClient
                access_token = GoogleDriveClient.get_access_token()
                
                raw_message = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
                url = f"https://gmail.googleapis.com/gmail/v1/users/{gmail_user}/messages/send"
                headers = {
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json"
                }
                payload = {"raw": raw_message}
                
                response = requests.post(url, headers=headers, json=payload, timeout=15)
                if response.status_code == 200:
                    cls.log_audit(to_email, subject, "SUCCESS")
                    return True
                else:
                    err_msg = f"API Gmail HTTP {response.status_code} - {response.text}"
                    cls.log_audit(to_email, subject, "FAIL", err_msg)
                    raise Exception(err_msg)
            except Exception as e:
                cls.log_audit(to_email, subject, "FAIL", str(e))
                raise e
        else:
            # Mode SMTP Classique
            if not smtp_host or not smtp_user or not smtp_password:
                cls.log_audit(to_email, subject, "FAIL", "Configuration SMTP / Gmail OAuth2 manquante.")
                raise ValueError("Aucune configuration d'envoi d'e-mails (Gmail OAuth2 ou SMTP classique) n'est valide.")
                
            try:
                port = int(smtp_port) if smtp_port else 587
                if port == 465:
                    server = smtplib.SMTP_SSL(smtp_host, port, timeout=15)
                else:
                    server = smtplib.SMTP(smtp_host, port, timeout=15)
                    server.ehlo()
                    # Toujours activer starttls si disponible sur le serveur
                    try:
                        server.starttls()
                        server.ehlo()
                    except Exception:
                        pass
                
                server.login(smtp_user, smtp_password)
                # Diviser les e-mails en liste pour assurer l'envoi SMTP multipart.
                # L'enveloppe SMTP reste le compte authentifié (contrainte des serveurs),
                # l'adresse d'expédition choisie figure dans l'en-tête « From » du message.
                recipients = [em.strip() for em in to_email.split(",") if em.strip()]
                server.sendmail(smtp_from, recipients, msg.as_string())
                server.quit()
                
                cls.log_audit(to_email, subject, "SUCCESS")
                return True
            except Exception as e:
                cls.log_audit(to_email, subject, "FAIL", str(e))
                raise e
