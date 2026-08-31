import requests
from infrastructure.google_drive_client import GoogleDriveClient

class GoogleContactsClient:
    """
    Client pour l'API Google People (Google Contacts) permettant de gérer les listes de contacts.
    Réutilise les jetons d'authentification Gmail OAuth2.
    """
    @classmethod
    def get_access_token(cls) -> str:
        """Récupère le jeton d'accès OAuth2 actif via le client Drive (authentification partagée)."""
        return GoogleDriveClient.get_access_token()

    @classmethod
    def get_or_create_group(cls, group_name: str) -> str:
        """
        Recherche un groupe de contacts par son nom exact. 
        S'il existe, retourne son resourceName. S'il n'existe pas, le crée et le retourne.
        """
        access_token = cls.get_access_token()
        if not access_token:
            raise Exception("Jeton d'accès Google OAuth2 introuvable. Veuillez vous reconnecter dans les Paramètres.")

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        
        # 1. Rechercher si le groupe existe déjà (limité aux 100 premiers groupes)
        try:
            url = "https://people.googleapis.com/v1/contactGroups?pageSize=100"
            res = requests.get(url, headers=headers, timeout=10)
            if res.status_code == 200:
                groups = res.json().get("contactGroups", [])
                for g in groups:
                    if g.get("formattedName") == group_name:
                        print(f"🔍 [CONTACTS] Groupe existant trouvé : {group_name} ({g.get('resourceName')})")
                        return g.get("resourceName")
            elif res.status_code != 404:
                err_msg = res.json().get("error", {}).get("message", res.text)
                raise Exception(f"Erreur de recherche Google Contacts ({res.status_code}) : {err_msg}")
        except Exception as e:
            if "Erreur de recherche" in str(e):
                raise e
            print(f"⚠️ [CONTACTS] Erreur lors de la recherche du groupe : {e}")

        # 2. Créer le groupe s'il n'existe pas
        url = "https://people.googleapis.com/v1/contactGroups"
        body = {
            "contactGroup": {
                "name": group_name
            }
        }
        res = requests.post(url, headers=headers, json=body, timeout=10)
        if res.status_code == 200:
            new_resource = res.json().get("resourceName")
            print(f"✅ [CONTACTS] Groupe créé avec succès : {new_resource}")
            return new_resource
        else:
            err_msg = res.json().get("error", {}).get("message", res.text)
            raise Exception(f"Erreur de création Google Contacts ({res.status_code}) : {err_msg}")

    @classmethod
    def find_contact_by_email(cls, email: str) -> str:
        """Recherche un contact existant dans l'annuaire par son adresse e-mail et retourne son resourceName."""
        if not email:
            return None

        access_token = cls.get_access_token()
        if not access_token:
            return None

        headers = {"Authorization": f"Bearer {access_token}"}
        # Rechercher par e-mail dans les contacts
        url = f"https://people.googleapis.com/v1/people:searchContacts?query={email}&readMask=emailAddresses"
        try:
            res = requests.get(url, headers=headers, timeout=10)
            if res.status_code == 200:
                results = res.json().get("results", [])
                for r in results:
                    person = r.get("person", {})
                    emails = person.get("emailAddresses", [])
                    for em in emails:
                        if em.get("value", "").lower() == email.lower():
                            return person.get("resourceName")
        except Exception as e:
            print(f"⚠️ [CONTACTS] Erreur lors de la recherche du contact {email} : {e}")
        return None

    @classmethod
    def create_contact(cls, first_name: str, last_name: str, email: str, phone: str = "") -> str:
        """Crée un nouveau contact dans l'annuaire Google Contacts et retourne son resourceName unique."""
        access_token = cls.get_access_token()
        if not access_token:
            return None

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        url = "https://people.googleapis.com/v1/people:createContact"
        
        body = {
            "names": [
                {
                    "givenName": first_name,
                    "familyName": last_name
                }
            ],
            "emailAddresses": [
                {
                    "value": email,
                    "type": "home"
                }
            ]
        }
        
        # Nettoyer et formater le numéro de téléphone s'il existe
        if phone:
            phone_str = str(phone).strip()
            if phone_str:
                body["phoneNumbers"] = [
                    {
                        "value": phone_str,
                        "type": "mobile"
                    }
                ]
            
        try:
            res = requests.post(url, headers=headers, json=body, timeout=10)
            if res.status_code == 200:
                res_name = res.json().get("resourceName")
                print(f"✅ [CONTACTS] Contact créé : {first_name} {last_name} ({res_name})")
                return res_name
            else:
                print(f"❌ [CONTACTS] Échec de la création du contact : {res.status_code} - {res.text}")
        except Exception as e:
            print(f"⚠️ [CONTACTS] Exception lors de la création du contact {first_name} {last_name} : {e}")
        return None

    @classmethod
    def add_members_to_group(cls, group_resource_name: str, contact_resource_names: list) -> bool:
        """Associe une liste de contacts (resourceNames) à un groupe de contacts (contactGroup)."""
        if not group_resource_name or not contact_resource_names:
            return False
            
        access_token = cls.get_access_token()
        if not access_token:
            return False

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        
        url = f"https://people.googleapis.com/v1/{group_resource_name}/members:modify"
        body = {
            "resourceNamesToAdd": contact_resource_names
        }
        
        try:
            res = requests.post(url, headers=headers, json=body, timeout=10)
            if res.status_code == 200:
                print(f"✅ [CONTACTS] {len(contact_resource_names)} contacts ajoutés au groupe {group_resource_name}.")
                return True
            else:
                print(f"❌ [CONTACTS] Échec de l'association au groupe : {res.status_code} - {res.text}")
        except Exception as e:
            print(f"⚠️ [CONTACTS] Exception lors de l'ajout des membres au groupe : {e}")
        return False
