import os
import requests
from infrastructure.secret_store import SecretStore

class GoogleDriveClient:
    """
    Isole l'intégration avec Google Drive pour télécharger et verser des documents.
    """

    @staticmethod
    def get_access_token() -> str:
        """Récupère un access token d'API Google à partir du refresh token."""
        client_id = SecretStore.get_secret("GMAIL_CLIENT_ID")
        client_secret = SecretStore.get_secret("GMAIL_CLIENT_SECRET")
        refresh_token = SecretStore.get_secret("GMAIL_REFRESH_TOKEN")
        
        if not client_id or not client_secret or not refresh_token:
            raise ValueError("Identifiants Google Cloud manquants pour l'obtention du jeton d'accès.")
            
        url = "https://oauth2.googleapis.com/token"
        data = {
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token"
        }
        
        response = requests.post(url, data=data, timeout=15)
        if response.status_code == 200:
            return response.json().get("access_token", "")
        else:
            raise Exception(f"Échec de l'obtention du token Google : {response.status_code} - {response.text}")

    @classmethod
    def download_file(cls, file_id: str, dest_path: str) -> bool:
        """
        Télécharge le contenu brut d'un fichier stocké sur Google Drive.
        """
        if not file_id:
            return False
            
        try:
            access_token = cls.get_access_token()
            url = f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media"
            headers = {"Authorization": f"Bearer {access_token}"}
            
            print(f"📥 [DRIVE] Téléchargement du fichier {file_id}...")
            response = requests.get(url, headers=headers, timeout=30)
            if response.status_code == 200:
                with open(dest_path, "wb") as f:
                    f.write(response.content)
                print("✅ [DRIVE] Téléchargement réussi.")
                return True
            else:
                print(f"❌ [DRIVE] Erreur lors du téléchargement : {response.status_code} - {response.text}")
                return False
        except Exception as e:
            print(f"❌ [DRIVE] Exception lors du téléchargement : {e}")
            return False

    @classmethod
    def upload_file(cls, file_id: str, src_path: str) -> bool:
        """
        Met à jour (écrase le contenu) d'un fichier existant sur Google Drive.
        Conserve l'identifiant du fichier intact.
        """
        if not file_id or not os.path.exists(src_path):
            return False
            
        try:
            access_token = cls.get_access_token()
            url = f"https://www.googleapis.com/upload/drive/v3/files/{file_id}?uploadType=media"
            
            # Détection dynamique du Content-Type
            content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            if src_path.endswith(".db") or src_path.endswith(".sqlite3"):
                content_type = "application/x-sqlite3"
                
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": content_type
            }
            
            print(f"📤 [DRIVE] Mise à jour du fichier {file_id} ({content_type})...")
            with open(src_path, "rb") as f:
                response = requests.patch(url, headers=headers, data=f, timeout=30)
            if response.status_code == 200:
                print("✅ [DRIVE] Mise à jour Google Drive réussie.")
                return True
            else:
                print(f"❌ [DRIVE] Erreur lors du versement : {response.status_code} - {response.text}")
                return False
        except Exception as e:
            print(f"❌ [DRIVE] Exception lors du versement : {e}")
            return False

    @classmethod
    def create_file(cls, name: str, src_path: str) -> str:
        """
        Crée un nouveau fichier sur Google Drive et renvoie son ID unique.
        """
        if not os.path.exists(src_path):
            return None
            
        try:
            import json
            access_token = cls.get_access_token()
            url = "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart"
            
            mime_type = "application/octet-stream"
            if src_path.endswith(".db") or src_path.endswith(".sqlite3"):
                mime_type = "application/x-sqlite3"
            elif src_path.endswith(".xlsx"):
                mime_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                
            metadata = {
                "name": name,
                "mimeType": mime_type
            }
            
            headers = {
                "Authorization": f"Bearer {access_token}"
            }
            
            files = {
                "metadata": ("metadata", json.dumps(metadata), "application/json"),
                "file": (os.path.basename(src_path), open(src_path, "rb"), mime_type)
            }
            
            print(f"📤 [DRIVE] Création d'un nouveau fichier '{name}' sur Google Drive...")
            response = requests.post(url, headers=headers, files=files, timeout=30)
            
            if response.status_code == 200:
                new_id = response.json().get("id", "")
                print(f"✅ [DRIVE] Fichier créé avec succès. ID : {new_id}")
                return new_id
            else:
                print(f"❌ [DRIVE] Échec de la création du fichier : {response.status_code} - {response.text}")
                return None
        except Exception as e:
            print(f"❌ [DRIVE] Exception lors de la création du fichier : {e}")
            return None

    @classmethod
    def get_file_name(cls, file_id: str) -> str:
        """
        Récupère le nom d'un fichier sur Google Drive à partir de son ID unique.
        """
        if not file_id:
            return ""
            
        try:
            access_token = cls.get_access_token()
            url = f"https://www.googleapis.com/drive/v3/files/{file_id}"
            headers = {"Authorization": f"Bearer {access_token}"}
            
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                return response.json().get("name", "")
            else:
                return ""
        except Exception:
            return ""
