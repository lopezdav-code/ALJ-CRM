import os
import requests
import urllib3
from dotenv import load_dotenv

# Désactiver les avertissements SSL lors de l'utilisation de verify=False
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Charger les variables d'environnement depuis le fichier .env
load_dotenv()

CLIENT_ID = os.getenv("HELLOASSO_CLIENT_ID")
CLIENT_SECRET = os.getenv("HELLOASSO_CLIENT_SECRET")
ORG_SLUG = os.getenv("HELLOASSO_ORG_SLUG")
BASE_URL = "https://api.helloasso.com/v5"

def get_access_token():
    """Récupère un jeton d'accès OAuth2 auprès de HelloAsso."""
    if not CLIENT_ID or not CLIENT_SECRET:
        return None
        
    url = "https://api.helloasso.com/oauth2/token"
    data = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "client_credentials"
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    
    try:
        response = requests.post(url, data=data, headers=headers, verify=False)
        response.raise_for_status()
        return response.json().get("access_token")
    except requests.exceptions.RequestException as e:
        print(f"Erreur d'authentification: {e}")
        return None

def fetch_all_pages(url, headers, params=None):
    """Gère la pagination de l'API HelloAsso pour récupérer toutes les données."""
    if params is None:
        params = {}
        
    # L'API HelloAsso utilise pageSize=100 maximum généralement, mettons une taille correcte
    params['pageSize'] = 100
    
    results = []
    continuation_token = None
    page_count = 1
    
    print(f"Début de la récupération : {url}")
    
    while True:
        if continuation_token:
            params['continuationToken'] = continuation_token
            
        try:
            print(f" -> Requête page {page_count}...")
            response = requests.get(url, headers=headers, params=params, verify=False)
            response.raise_for_status()
            data = response.json()
            
            page_data = data.get("data", [])
            
            # Condition de sortie PRIMORDIALE : si la page est vide, on a fini.
            if not page_data:
                print(" -> Fin : plus aucune donnée sur cette page.")
                break
                
            results.extend(page_data)
            
            pagination = data.get("pagination", {})
            new_token = pagination.get("continuationToken")
            
            # S'il n'y a plus de token, ou s'il est identique au précédent (boucle infinie)
            if not new_token or new_token == continuation_token:
                print(" -> Fin : plus de token de continuation.")
                break
                
            continuation_token = new_token
            page_count += 1
                
        except requests.exceptions.RequestException as e:
            print(f"Erreur lors de la requête paginée: {e}")
            break
            
    print(f"Récupération terminée. Total éléments: {len(results)}")
    return results

def get_campaigns():
    """Récupère la liste complète des campagnes (formulaires) de l'organisation."""
    token = get_access_token()
    if not token:
        return []
        
    url = f"{BASE_URL}/organizations/{ORG_SLUG}/forms"
    headers = {"Authorization": f"Bearer {token}"}
    return fetch_all_pages(url, headers)

def get_payments(campaign_type, campaign_slug):
    """Récupère tous les paiements associés à une campagne spécifique."""
    token = get_access_token()
    if not token:
        return []
        
    url = f"{BASE_URL}/organizations/{ORG_SLUG}/forms/{campaign_type}/{campaign_slug}/payments"
    headers = {"Authorization": f"Bearer {token}"}
    return fetch_all_pages(url, headers)

def get_items(campaign_type, campaign_slug):
    """Récupère tous les articles (inscrits/participants) d'une campagne spécifique."""
    token = get_access_token()
    if not token:
        return []
        
    url = f"{BASE_URL}/organizations/{ORG_SLUG}/forms/{campaign_type}/{campaign_slug}/items"
    headers = {"Authorization": f"Bearer {token}"}
    return fetch_all_pages(url, headers, params={"withDetails": "true"})
