import os
import sys
import json
import time
import datetime
from typing import List, Dict, Any

# S'assurer que le dossier src est dans sys.path (exécution directe, docker ou package)
_src_dir = os.path.dirname(os.path.abspath(__file__))
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from typing import Optional

from fastapi import FastAPI, Body, BackgroundTasks, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, Response

# Importer les fonctions de notre script existant
from helloasso_api import get_campaigns, get_items
from infrastructure.sqlite_repository import SqliteRepository

from dotenv import load_dotenv
load_dotenv()

from domain.constants import get_active_season, APP_VERSION
from domain.utils import json_for_script
from infrastructure.secret_store import SecretStore
from infrastructure import runtime_env

# Inconsistent dev mode (Firebase emulator) or dev mode on Cloud Run: stop immediately.
runtime_env.validate()


def get_target_slug():
    """Slug de la campagne d'adhésion : lu à chaque appel pour prendre en compte
    les modifications faites dans la page Paramètres sans redémarrer l'application."""
    slug = (SecretStore.get_secret("CAMPAIGN_SLUG") or "").strip()
    if not slug:
        slug = f"adhesion-escalade-{get_active_season()}-amicale-laique-escalade-2"
    if "helloasso.com" in slug.lower():
        slug = [s for s in slug.split("/") if s.strip()][-1]
    return slug

app = FastAPI(title="Admin Escalade API")

# Access control (Firebase token + firestore.rules roles): enforced on Cloud Run and in the
# Docker image (ALJ_API_AUTH=required), off for the desktop app's local server, which is
# protected by local_guard_middleware instead (loopback hosts, same-origin writes).
from infrastructure.cloud_database import CloudDatabase
from starlette.concurrency import run_in_threadpool


# Routes that only read/write Firestore collections (competitions, coaches, projections,
# HelloAsso mirror) through CompetitionFirestoreRepository: they never touch the SQLite
# cache, so they must not wait for its refresh (a full rebuild after a cold start).
FIRESTORE_ONLY_PREFIXES = ("/api/competitions", "/api/coaches", "/api/competition-members",
                           "/api/helloasso/items")


def uses_sqlite_cache(path: str) -> bool:
    """True for the data routes served from the SQLite cache of the crm_* collections."""
    if any(path == p or path.startswith(p + "/") for p in FIRESTORE_ONLY_PREFIXES):
        return False
    return path.startswith("/api/") or path in ("/map", "/pivot")


async def cloud_db_middleware(request, call_next):
    """Base principale dans Firestore : le cache SQLite du serveur est mis à jour
    avant les routes de données, et les écritures sont envoyées juste après.
    Enregistré avant le contrôle d'accès : il ne s'exécute qu'après lui."""
    relevant = uses_sqlite_cache(request.url.path)
    # Cloud Run, or local dev on the emulator: the cache follows Firestore as in production
    server_mode = os.environ.get("K_SERVICE") or runtime_env.is_dev()
    if relevant and server_mode and CloudDatabase.is_enabled():
        await run_in_threadpool(CloudDatabase.ensure_fresh, 30)
    response = await call_next(request)
    if relevant and request.method not in ("GET", "HEAD", "OPTIONS") and CloudDatabase.is_enabled():
        await run_in_threadpool(CloudDatabase.after_write)
    return response


app.middleware("http")(cloud_db_middleware)

from infrastructure.api_auth import auth_middleware, local_guard_middleware
app.middleware("http")(auth_middleware)
# Unauthenticated local server only accepts loopback hosts and same-origin writes
app.middleware("http")(local_guard_middleware)


async def security_headers_middleware(request, call_next):
    """Baseline browser protections on every response (including errors from the guards)."""
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    # Pages may only be framed by the site itself (clickjacking); srcdoc frames are unaffected
    response.headers.setdefault("Content-Security-Policy", "frame-ancestors 'self'")
    return response


app.middleware("http")(security_headers_middleware)  # outermost

# Data routes of the web front end (competitions, coaches, HelloAsso links): src/api/
from api.competitions import router as competitions_router
from api.responses import service_error_handler
from services.errors import ServiceError
app.include_router(competitions_router)
app.add_exception_handler(ServiceError, service_error_handler)

GENERIC_ERROR = "Erreur interne du serveur (détails dans les journaux)."


def internal_error(e: Exception, where: str) -> str:
    """Logs the exception server-side; the client only gets a generic message
    (no paths, SQL or third-party details, notably on the public webhook)."""
    print(f"❌ [{where}] {type(e).__name__}: {e}")
    return GENERIC_ERROR


def client_error(e: Exception, where: str) -> str:
    """Validation errors (ValueError) are meant for the user; anything else stays generic."""
    return str(e) if isinstance(e, ValueError) else internal_error(e, where)

def geocode_missing_addresses(addresses: List[str]):
    """Géocode les adresses manquantes en tâche de fond avec limitation stricte de débit."""
    print(f"🌍 [GEOCODING] Début du géocodage en tâche de fond pour {len(addresses)} adresses...")
    try:
        from geopy.geocoders import Nominatim
        geolocator = Nominatim(user_agent="alj_escalade_manager")
    except Exception as e:
        print(f"❌ [GEOCODING] Impossible de charger geopy/Nominatim : {e}")
        return

    for i, address in enumerate(addresses):
        # Pause de 1.5s entre chaque appel pour respecter les CGU Nominatim
        time.sleep(1.5)
        try:
            print(f"🌍 [GEOCODING] ({i+1}/{len(addresses)}) Recherche de l'adresse : {address}")
            location = geolocator.geocode(address, timeout=10)
            if location:
                lat, lon = location.latitude, location.longitude
                print(f"✅ [GEOCODING] Trouvé : {lat}, {lon}")
                SqliteRepository.save_geocode(address, lat, lon)
            else:
                print(f"⚠️ [GEOCODING] Adresse non résolue : {address}")
                # Enregistrer des coordonnées nulles pour éviter de requêter indéfiniment cette mauvaise adresse
                SqliteRepository.save_geocode(address, None, None)
        except Exception as e:
            print(f"❌ [GEOCODING] Erreur lors du géocodage de '{address}' : {e}")
    if CloudDatabase.is_enabled():
        CloudDatabase.flush_only()
    print("🌍 [GEOCODING] Tâche de fond terminée.")

# No CORS: every page calls the API from its own origin. Allowing other origins would let any
# website read the local (unauthenticated) desktop server.

@app.get("/api/dashboard")
def get_dashboard_data(background_tasks: BackgroundTasks = None, force_refresh: bool = False):
    """Route principale renvoyant toutes les données formatées pour le frontend."""
    print("-> Interrogation de l'API HelloAsso...")
    
    campaigns = get_campaigns()
    target_slug = get_target_slug()
    target_camp = next((c for c in campaigns if c.get('formSlug') == target_slug), None)
    
    if not target_camp:
        return {"error": "Campagne introuvable"}
        
    c_type = target_camp.get('formType')
    items = get_items(c_type, target_slug)
    
    inscrits = [i for i in items if i.get('type') in ('Registration', 'Membership')]
    
    participants = []
    tariffs_count = {}
    map_data_dict = {}

    # Charger le cache géographique depuis SQLite
    geocache = SqliteRepository.get_geocache()
    missing_addresses = set()

    for item in inscrits:
        flat_item = {
            "order_ref": item.get("order", {}).get("id"),
            "order_date": item.get("order", {}).get("date"),
            "status": item.get("state"),
            "tarif_name": item.get("name") or "".strip(),
            "amount": item.get("amount", 0) / 100,
            "user_firstName": item.get("user", {}).get("firstName") or "",
            "user_lastName": item.get("user", {}).get("lastName") or "",
            "payer_firstName": item.get("payer", {}).get("firstName") or "",
            "payer_lastName": item.get("payer", {}).get("lastName") or "",
            "payer_email": item.get("payer", {}).get("email") or "",
        }
        
        # Parse HelloAsso checkout options for insurance selections
        options = item.get("options", [])
        flat_item["opt_Assurance Base"] = "Non"
        flat_item["opt_Montant Assurance Base"] = 0.0
        flat_item["opt_Assurance Base +"] = "Non"
        flat_item["opt_Montant Assurance Base +"] = 0.0
        flat_item["opt_Assurance Base ++"] = "Non"
        flat_item["opt_Montant Assurance Base ++"] = 0.0
        flat_item["opt_Assurance Option ski de piste"] = "Non"
        flat_item["opt_Montant Assurance Option ski de piste"] = 0.0
        flat_item["opt_Assurance Option VTT"] = "Non"
        flat_item["opt_Montant Assurance Option VTT"] = 0.0
        flat_item["opt_Assurance Option Trail"] = "Non"
        flat_item["opt_Montant Assurance Option Trail"] = 0.0
        
        for opt in options:
            opt_name = opt.get("name") or "".strip()
            opt_amount = opt.get("amount", 0) / 100
            if "Assurance Base ++" in opt_name:
                flat_item["opt_Assurance Base ++"] = "Oui"
                flat_item["opt_Montant Assurance Base ++"] = opt_amount
            elif "Assurance Base +" in opt_name:
                flat_item["opt_Assurance Base +"] = "Oui"
                flat_item["opt_Montant Assurance Base +"] = opt_amount
            elif "Assurance Base" in opt_name:
                flat_item["opt_Assurance Base"] = "Oui"
                flat_item["opt_Montant Assurance Base"] = opt_amount
            elif "ski de piste" in opt_name.lower():
                flat_item["opt_Assurance Option ski de piste"] = "Oui"
                flat_item["opt_Montant Assurance Option ski de piste"] = opt_amount
            elif "vtt" in opt_name.lower():
                flat_item["opt_Assurance Option VTT"] = "Oui"
                flat_item["opt_Montant Assurance Option VTT"] = opt_amount
            elif "trail" in opt_name.lower():
                flat_item["opt_Assurance Option Trail"] = "Oui"
                flat_item["opt_Montant Assurance Option Trail"] = opt_amount
        
        custom_fields = item.get("customFields", [])
        city = ""
        zip_code = ""
        address = ""
        
        for field in custom_fields:
            name = field.get("name") or ""
            val = field.get("answer", field.get("value") or "")
            flat_item[f"champ_{name}"] = val
            
            if name.lower() == "ville":
                city = val.strip().upper()
            elif name.lower() == "code postal":
                zip_code = val.strip()
            elif "adresse" in name.lower() and "rue" in name.lower():
                address = val.strip()

        flat_item["city"] = city
        flat_item["address"] = address
        flat_item["zip"] = zip_code

        # Résoudre l'adresse complète du membre
        full_address = ""
        if address and city:
            full_address = f"{address}, {zip_code}, {city}, France"
        elif city:
            full_address = f"{city}, {zip_code}, France"
        
        flat_item["full_address"] = full_address

        lat, lon = None, None
        if full_address:
            if full_address in geocache:
                coords = geocache[full_address]
                lat, lon = coords[0], coords[1]
            else:
                missing_addresses.add(full_address)
        
        flat_item["lat"] = lat
        flat_item["lon"] = lon

        # Résoudre également au niveau de la ville seule (statistiques de secours)
        city_address = f"{city}, {zip_code}, France" if city else ""
        city_lat, city_lon = None, None
        if city_address:
            if city_address in geocache:
                city_coords = geocache[city_address]
                city_lat, city_lon = city_coords[0], city_coords[1]
            else:
                missing_addresses.add(city_address)
        
        flat_item["city_lat"] = city_lat
        flat_item["city_lon"] = city_lon

        participants.append(flat_item)
        
        # Comptage par Tarif
        t_name = flat_item["tarif_name"]
        tariffs_count[t_name] = tariffs_count.get(t_name, 0) + 1
        
        # Préparation des données Cartographiques (Groupement par coordonnées exactes)
        if lat is not None and lon is not None:
            addr_key = f"{lat:.6f},{lon:.6f}"
            if addr_key not in map_data_dict:
                map_data_dict[addr_key] = {
                    "address": full_address,
                    "city": city,
                    "zip": zip_code,
                    "lat": lat,
                    "lon": lon,
                    "count": 0,
                    "members": [],
                    "groups": set()
                }
            map_data_dict[addr_key]["count"] += 1
            map_data_dict[addr_key]["members"].append(f"{flat_item['user_firstName']} {flat_item['user_lastName']} ({t_name})")
            map_data_dict[addr_key]["groups"].add(t_name)

    # S'il y a des adresses manquantes et un gestionnaire de tâches de fond, lancer le géocodage
    if missing_addresses and background_tasks:
        background_tasks.add_task(geocode_missing_addresses, list(missing_addresses))

    # Convertir le set des groupes en liste pour la sérialisation JSON
    for data in map_data_dict.values():
        data["groups"] = list(data["groups"])

    map_data = list(map_data_dict.values())
    tariffs = [{"name": k, "count": v} for k, v in tariffs_count.items()]

    dashboard_data = {
        "campaign": target_camp,
        "total_inscrits": len(participants),
        "participants": participants,
        "tariffs": tariffs,
        "map_data": map_data
    }

    return dashboard_data

def get_sqlite_map_data(background_tasks: BackgroundTasks = None) -> List[Dict[str, Any]]:
    """Génère les points cartographiques directement depuis la base SQLite (Source unique de vérité)."""
    try:
        from infrastructure.sqlite_repository import SqliteRepository
        raw_data = SqliteRepository.load_direct_data()
        
        map_data_dict = {}
        geocache = SqliteRepository.get_geocache()
        missing_addresses = set()
        
        for row in raw_data:
            # Ignorer les annulés pour la carte
            status = row.get("status", "Validé")
            if "annul" in str(status).lower():
                continue
                
            firstName = (row.get("first_name") or "").strip().title()
            lastName = (row.get("last_name") or "").strip().upper()
            t_name = row.get("tarif_name") or "".strip() or "Aucun"
            
            addr = row.get("address") or ""
            city = row.get("city") or ""
            zip_code = row.get("zip_code") or ""
            
            # Formater l'adresse de façon normalisée et insensible à la casse
            from domain.utils import clean_city_name
            city_clean = clean_city_name(city)
            city_upper = city_clean.upper()
            addr_clean = str(addr).strip() if addr else ""
            zip_clean = str(zip_code).strip() if zip_code else ""
            
            full_address = ""
            if addr_clean and city_upper:
                full_address = f"{addr_clean}, {zip_clean}, {city_upper}, France"
            elif city_upper:
                full_address = f"{city_upper}, {zip_clean}, France"
                
            full_address = " ".join(full_address.split())
            if not full_address or full_address == "France":
                continue
                
            lat, lon = None, None
            if full_address in geocache:
                coords = geocache[full_address]
                lat, lon = coords[0], coords[1]
            else:
                # Si l'adresse contient un nom de rue, on tente de la géocoder en tâche de fond
                missing_addresses.add(full_address)
                
            if lat is not None and lon is not None:
                addr_key = f"{lat:.6f},{lon:.6f}"
                if addr_key not in map_data_dict:
                    map_data_dict[addr_key] = {
                        "address": f"{addr_clean}, {zip_clean} {city_upper}" if addr_clean else city_upper,
                        "city": city_upper,
                        "zip": zip_clean,
                        "lat": lat,
                        "lon": lon,
                        "count": 0,
                        "members": [],
                        "groups": set()
                    }
                map_data_dict[addr_key]["count"] += 1
                map_data_dict[addr_key]["members"].append(f"{firstName} {lastName} ({t_name})")
                map_data_dict[addr_key]["groups"].add(t_name)

        # Lancer le géocodage asynchrone pour les adresses manquantes en tâche de fond !
        if missing_addresses and background_tasks:
            background_tasks.add_task(geocode_missing_addresses, list(missing_addresses))

        # Convertir les sets en listes pour JSON
        for data in map_data_dict.values():
            data["groups"] = list(data["groups"])
            
        return list(map_data_dict.values())
        
    except Exception as e:
        print(f"⚠️ Erreur lors de la génération cartographique SQLite : {e}")
        return []

@app.get("/map", response_class=HTMLResponse)
def get_map(background_tasks: BackgroundTasks):
    """Renvoie la page de cartographie Leaflet interactive branchée sur SQLite."""
    map_points = get_sqlite_map_data(background_tasks)
    map_points_json = json_for_script(map_points)

    html_content = """<!DOCTYPE html>
<html>
<head>
    <title>ALJ Escalade - Cartographie des Adhérents</title>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    
    <!-- CDN Leaflet -->
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    
    <!-- CDN Leaflet MarkerCluster -->
    <link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.4.1/dist/MarkerCluster.css" />
    <link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.4.1/dist/MarkerCluster.Default.css" />
    <script src="https://unpkg.com/leaflet.markercluster@1.4.1/dist/leaflet.markercluster.js"></script>
    
    <style>
        html, body {
            height: 100%;
            margin: 0;
            padding: 0;
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background-color: #F8FAFC;
        }
        #header {
            background-color: #163A5F;
            color: white;
            padding: 10px 20px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            height: 50px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            position: relative;
            z-index: 1000;
        }
        #header h1 {
            margin: 0;
            font-size: 18px;
            font-weight: 600;
        }
        .header-controls {
            display: flex;
            align-items: center;
            gap: 15px;
        }
        .multiselect {
            position: relative;
            user-select: none;
            width: 250px;
        }
        .selectBox {
            position: relative;
            cursor: pointer;
        }
        .selectBox select {
            width: 100%;
            padding: 6px 12px;
            border-radius: 4px;
            border: 1px solid #CBD5E1;
            font-size: 13px;
            background-color: white;
            color: #1E293B;
            outline: none;
            font-weight: bold;
            cursor: pointer;
            appearance: none;
            -webkit-appearance: none;
            -moz-appearance: none;
        }
        .overSelect {
            position: absolute;
            left: 0;
            right: 0;
            top: 0;
            bottom: 0;
        }
        #checkboxes {
            display: none;
            position: absolute;
            background-color: white;
            border: 1px solid #CBD5E1;
            border-radius: 4px;
            max-height: 400px;
            overflow-y: auto;
            z-index: 2000;
            width: 100%;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
            color: #1E293B;
            top: 100%;
            right: 0;
            margin-top: 2px;
        }
        #checkboxes label {
            display: flex;
            align-items: center;
            padding: 8px 10px;
            font-size: 13px;
            cursor: pointer;
            border-bottom: 1px solid #F1F5F9;
            margin: 0;
        }
        #checkboxes label:hover {
            background-color: #F8FAFC;
        }
        #checkboxes input {
            margin-right: 8px;
            cursor: pointer;
        }
        #header .stats {
            font-size: 13px;
            background-color: rgba(255,255,255,0.15);
            padding: 6px 12px;
            border-radius: 4px;
            font-weight: bold;
        }
        #map {
            height: calc(100% - 70px);
            width: 100%;
        }
        .popup-title {
            font-weight: bold;
            color: #163A5F;
            font-size: 14px;
            margin-bottom: 5px;
            border-bottom: 1px solid #E2E8F0;
            padding-bottom: 3px;
        }
        .popup-address {
            color: #64748B;
            font-size: 11px;
            margin-bottom: 8px;
        }
        .popup-members-list {
            margin: 0;
            padding-left: 15px;
            font-size: 12px;
            color: #1E293B;
        }
        .popup-members-list li {
            margin-bottom: 2px;
        }
    </style>
</head>
<body>

    <div id="header">
        <h1>📍 Cartographie ALJ Escalade</h1>
        <div class="header-controls">
            <div class="multiselect">
                <div class="selectBox" onclick="toggleCheckboxes()">
                    <select>
                        <option id="dropdown-title">🧗 Tous les groupes</option>
                    </select>
                    <div class="overSelect"></div>
                </div>
                <div id="checkboxes">
                    <!-- Checkboxes injéctées ici par le JS -->
                </div>
            </div>
            <div class="stats" id="stats-badge">Chargement...</div>
        </div>
    </div>

    <div id="map"></div>

    <script>
        // Injecter les données de cartographie générées côté serveur
        const mapData = {MAP_DATA_JSON};

        // Member data comes from the public HelloAsso form: always escaped before HTML insertion
        const escHtml = s => (s == null ? "" : String(s)).replace(/[&<>"']/g,
            c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

        // Fermer le menu si clic en dehors
        let expanded = false;
        document.addEventListener('click', function(event) {
            const multiselect = document.querySelector('.multiselect');
            if (expanded && !multiselect.contains(event.target)) {
                document.getElementById("checkboxes").style.display = "none";
                expanded = false;
            }
        });

        function toggleCheckboxes() {
            const checkboxes = document.getElementById("checkboxes");
            if (!expanded) {
                checkboxes.style.display = "block";
                expanded = true;
            } else {
                checkboxes.style.display = "none";
                expanded = false;
            }
        }

        // Extraire tous les groupes uniques pour peupler le menu déroulant
        const allGroups = new Set();
        mapData.forEach(point => {
            if (point.groups) {
                point.groups.forEach(g => allGroups.add(g));
            }
        });
        
        const checkboxesContainer = document.getElementById('checkboxes');
        
        // Option "Tous les groupes"
        const allLabel = document.createElement('label');
        allLabel.innerHTML = `<input type="checkbox" id="check-all" value="ALL" checked onchange="handleAllChange()"> <b>🧗 Sélectionner Tout</b>`;
        checkboxesContainer.appendChild(allLabel);

        Array.from(allGroups).sort().forEach(group => {
            const label = document.createElement('label');
            const cb = document.createElement('input');
            cb.type = 'checkbox';
            cb.className = 'group-checkbox';
            cb.value = group;
            cb.checked = true;
            cb.addEventListener('change', applyFilter);
            label.append(cb, ' ' + group);
            checkboxesContainer.appendChild(label);
        });

        function handleAllChange() {
            const checkAll = document.getElementById('check-all').checked;
            const cbs = document.querySelectorAll('.group-checkbox');
            cbs.forEach(cb => cb.checked = checkAll);
            applyFilter();
        }

        // Initialiser la carte Leaflet centrée par défaut sur Jonage
        const map = L.map('map').setView([45.795, 5.045], 13);

        // Fond de carte OpenStreetMap France (100% libre, gratuit, sans clé API ni filigrane)
        const osmFr = L.tileLayer('https://{s}.tile.openstreetmap.fr/osmfr/{z}/{x}/{y}.png', {
            maxZoom: 20,
            attribution: '&copy; OpenStreetMap France | &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
        });

        // Fond alternatif Esri World Street Map (ultra-rapide, sans clé API)
        const esriStreet = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}', {
            maxZoom: 19,
            attribution: 'Tiles &copy; Esri &mdash; Source: Esri, DeLorme, NAVTEQ, USGS'
        });

        osmFr.addTo(map);

        L.control.layers({
            "OpenStreetMap France": osmFr,
            "Plan Esri": esriStreet
        }, null, { position: 'topright' }).addTo(map);

        let markers = L.markerClusterGroup({
            showCoverageOnHover: false,
            spiderfyOnMaxZoom: true
        });
        map.addLayer(markers);

        function renderMap(selectedGroups, allChecked) {
            markers.clearLayers();
            let totalMembersOnMap = 0;
            let totalUniqueLocations = 0;

            mapData.forEach(point => {
                if (point.lat && point.lon) {
                    
                    // Filtrage : est-ce que ce foyer possède un membre appartenant à l'un des groupes cochés ?
                    let membersToDisplay = point.members;
                    if (!allChecked) {
                        if (selectedGroups.length === 0) {
                            return; // Ignorer car aucun groupe
                        }
                        membersToDisplay = point.members.filter(m => {
                            return selectedGroups.some(g => m.includes(`(${g})`));
                        });
                        if (membersToDisplay.length === 0) {
                            return; // Ignorer cette adresse car personne ne correspond aux filtres
                        }
                    }

                    totalUniqueLocations++;
                    totalMembersOnMap += membersToDisplay.length;

                    // Créer un marqueur
                    const marker = L.marker([point.lat, point.lon]);

                    // Contenu du Popup stylisé
                    const popupContent = `
                        <div class="popup-title">${membersToDisplay.length} Adhérent${membersToDisplay.length > 1 ? 's' : ''}</div>
                        <div class="popup-address">📍 ${escHtml(point.address)}</div>
                        <ul class="popup-members-list">
                            ${membersToDisplay.map(name => `<li>${escHtml(name)}</li>`).join('')}
                        </ul>
                    `;

                    marker.bindPopup(popupContent);
                    markers.addLayer(marker);
                }
            });

            // Ajuster la vue de la carte pour englober tous les marqueurs si présents
            const groupBounds = markers.getBounds();
            if (groupBounds.isValid()) {
                map.fitBounds(groupBounds, { padding: [50, 50] });
            }

            // Mettre à jour le badge du header
            const suffix = allChecked ? '' : ` (Filtre: ${selectedGroups.length} groupe(s))`;
            document.getElementById('stats-badge').innerText = `${totalMembersOnMap} adhérents répartis sur ${totalUniqueLocations} adresses${suffix}`;
        }

        function applyFilter(event) {
            const checkAllCb = document.getElementById('check-all');
            const cbs = document.querySelectorAll('.group-checkbox');
            
            let selectedGroups = [];
            let allChecked = true;
            
            cbs.forEach(cb => {
                if (cb.checked) {
                    selectedGroups.push(cb.value);
                } else {
                    allChecked = false;
                }
            });
            
            // Sync the "All" checkbox state safely
            if (checkAllCb.checked !== allChecked && event && event.target.id !== 'check-all') {
                 checkAllCb.checked = allChecked;
            }

            // Update dropdown title
            const title = document.getElementById('dropdown-title');
            if (allChecked || selectedGroups.length === cbs.length) {
                title.innerText = "🧗 Tous les groupes";
            } else if (selectedGroups.length === 0) {
                title.innerText = "⚠️ Aucun groupe sélectionné";
            } else {
                title.innerText = `🧗 ${selectedGroups.length} groupe(s) filtré(s)`;
            }

            renderMap(selectedGroups, allChecked);
        }

        // Rendu initial (Tous les groupes)
        applyFilter();
    </script>
</body>
</html>
""".replace("{MAP_DATA_JSON}", map_points_json)
    return HTMLResponse(content=html_content)

@app.get("/pivot", response_class=HTMLResponse)
def get_pivot_table(season: str = "2026-2027"):
    """Renvoie la page du Tableau Croisé Dynamique interactif via PivotTable.js."""
    try:
        from infrastructure.sqlite_repository import SqliteRepository
        from domain.constants import get_active_season
        from domain.age_rules import parse_birth_date, age_at, get_season_start_date
        from domain.models import normalize_gender
        from domain.utils import clean_city_name
        
        target_season = (season or "").strip()
        if not target_season or target_season.lower() in ("default", "active"):
            target_season = get_active_season()

        raw_data = SqliteRepository.load_direct_data(target_season)
        ref_date = get_season_start_date(target_season)
        
        # Préparer un tableau de données plat et épuré pour le TCD
        pivot_records = []
        for row in raw_data:
            # 1. Normaliser et fusionner les statuts HelloAsso (Processed, Validated, Terminé, Traité -> Validé)
            status_raw = str(row.get("status", "Validé")).strip()
            status_lower = status_raw.lower()
            if status_lower in ("processed", "validated", "validé", "enregistré", "registered", "terminé", "termine", "traité", "traite"):
                status_clean = "Validé"
            elif status_lower in ("canceled", "cancelled", "annulé", "annule"):
                status_clean = "Annulé"
            elif status_lower in ("refused", "refusé", "refuse"):
                status_clean = "Refusé"
            else:
                status_clean = status_raw.title()
                
            # 2. Normaliser les noms de villes pour fusionner "Saint-Maurice..." et "Saint Maurice..."
            city_raw = row.get("city") or "Inconnue"
            city_clean = clean_city_name(city_raw)
            
            # 3. Type d'adhésion (Nouveau vs Déjà membre)
            already_member = row.get("already_member", 0)
            inscription_type = "Déjà Membre" if already_member > 0 else "Nouvelle Inscription"
            
            # 4. Saison
            season_name = row.get("season_name", "Inconnue")
            
            # 5. Date d'inscription (normalisée en ISO AAAA-MM-JJ pour un tri
            #    et un filtrage chronologiques dans le TCD ; format source variable)
            date_iso = ""
            date_raw = str(row.get("order_date") or "").strip()
            if date_raw:
                try:
                    import datetime as _datetime
                    date_iso = _datetime.datetime.strptime(date_raw[:10], "%Y-%m-%d").strftime("%Y-%m-%d")
                except ValueError:
                    date_iso = ""
            month_iso = date_iso[:7] if date_iso else ""

            # 6. Âge de l'adhérent (calculé au début de la saison de référence)
            b_date = parse_birth_date(row.get("birth_date") or row.get("birth_date_raw") or row.get("champ_Date de naissance de l'adhérent"))
            computed_age = age_at(b_date, ref_date)
            age_val = computed_age if computed_age is not None else "Inconnu"

            # 7. Tranche d'Âge (regroupement par décennies & mineurs, ordonné pour le tri TCD)
            if computed_age is None:
                tranche_age = "Inconnue"
            elif computed_age < 10:
                tranche_age = "0 à 9 ans (< 10 ans)"
            elif computed_age < 18:
                tranche_age = "10 à 17 ans"
            elif computed_age < 25:
                tranche_age = "18 à 24 ans"
            elif computed_age < 30:
                tranche_age = "25 à 29 ans"
            elif computed_age < 40:
                tranche_age = "30 à 39 ans"
            elif computed_age < 50:
                tranche_age = "40 à 49 ans"
            elif computed_age < 65:
                tranche_age = "50 à 64 ans"
            else:
                tranche_age = "65 ans et plus"
            
            pivot_records.append({
                "Nom": (row.get("last_name") or "").strip().upper(),
                "Prénom": (row.get("first_name") or "").strip().title(),
                "Sexe": normalize_gender(row.get("gender")) or "Inconnu",
                "Âge": age_val,
                "Tranche d'Âge": tranche_age,
                "Ville": city_clean,
                "Groupe / Tarif": str(row.get("tarif_name") or "").strip() or "Aucun",
                "Statut": status_clean,
                "Saison": season_name,
                "Type d'Adhésion": inscription_type,
                "Date d'Inscription": date_iso or "Inconnue",
                "Mois d'Inscription": month_iso or "Inconnue",
            })
            
        pivot_data_json = json_for_script(pivot_records)
    except Exception as ex:
        print(f"⚠️ Erreur lors de la préparation des données TCD : {ex}")
        pivot_data_json = "[]"

    html_content = """<!DOCTYPE html>
<html>
<head>
    <title>ALJ Escalade - Tableau Croisé Dynamique</title>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    
    <!-- jQuery et jQuery UI (Requis par PivotTable.js) -->
    <script src="https://cdnjs.cloudflare.com/ajax/libs/jquery/3.6.0/jquery.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/jqueryui/1.12.1/jquery-ui.min.js"></script>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/jqueryui/1.12.1/jquery-ui.min.css">
    
    <!-- PivotTable.js (CSS & JS) -->
    <link rel="stylesheet" type="text/css" href="https://cdnjs.cloudflare.com/ajax/libs/pivottable/2.23.0/pivot.min.css">
    <script type="text/javascript" src="https://cdnjs.cloudflare.com/ajax/libs/pivottable/2.23.0/pivot.min.js"></script>
    
    <style>
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            margin: 25px;
            background-color: #F8FAFC;
            color: #1E293B;
        }
        .header {
            background-color: #1E3A8A;
            color: #FFFFFF;
            padding: 15px 25px;
            border-radius: 8px;
            margin-bottom: 25px;
            box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1);
        }
        .header h1 {
            margin: 0;
            font-size: 20px;
            font-weight: bold;
        }
        .header p {
            margin: 5px 0 0 0;
            font-size: 13px;
            color: #BFDBFE;
        }
        .container {
            background-color: #FFFFFF;
            border: 1px solid #E2E8F0;
            border-radius: 8px;
            padding: 20px;
            box-shadow: 0 1px 3px 0 rgb(0 0 0 / 0.1);
            overflow: auto;
        }
        /* Style personnalisé pour les tables PivotTable.js */
        table.pvtTable {
            font-family: inherit;
            border-collapse: collapse;
            font-size: 13px;
        }
        table.pvtTable tr th, table.pvtTable tr th.pvtAxisLabel, table.pvtTable tr th.pvtTotalLabel {
            background-color: #F1F5F9;
            border: 1px solid #CBD5E1;
            color: #334155;
            font-weight: bold;
            padding: 6px 10px;
        }
        table.pvtTable tr td {
            color: #475569;
            border: 1px solid #CBD5E1;
            padding: 6px 10px;
            background-color: #FFFFFF;
        }
        .pvtValActive {
            background-color: #3B82F6 !important;
            color: #FFFFFF !important;
        }
        .pvtRowLabel, .pvtColLabel {
            font-weight: 500;
        }
        select.pvtAttrDropdown, select.pvtAggregator {
            font-family: inherit;
            padding: 4px 8px;
            border: 1px solid #CBD5E1;
            border-radius: 4px;
            background-color: #FFFFFF;
            color: #334155;
            font-size: 12px;
            margin: 3px;
        }
        .pvtVals {
            display: inline-block;
        }
    </style>
</head>
<body>

    <div class="header">
        <h1>📊 Tableau Croisé Dynamique — ALJ Escalade</h1>
        <p>Glissez et déposez les étiquettes ci-dessous pour filtrer et croiser à volonté les adhérents (par Groupe / Tarif, Sexe, Statut, Âge, Tranche d'Âge, Ville, etc.)</p>
    </div>

    <div class="container">
        <div id="output"></div>
    </div>

    <script type="text/javascript">
        $(function(){
            const pivotData = {PIVOT_DATA_JSON};
            
            $("#output").pivotUI(pivotData, {
                rows: ["Groupe / Tarif"],
                cols: ["Statut", "Sexe"],
                exclusions: {
                    "Groupe / Tarif": ["Liste d'attente cours"],
                    "Statut": ["Annulé"]
                },
                aggregatorName: "Count",
                rendererName: "Table"
            });
        });
    </script>
</body>
</html>
""".replace("{PIVOT_DATA_JSON}", pivot_data_json)
    return HTMLResponse(content=html_content)

@app.get("/api/planning")
def get_planning():
    """Récupère le planning depuis la BDD SQLite."""
    try:
        from infrastructure.sqlite_repository import SqliteRepository
        return SqliteRepository.load_planning_data(log_debug=False)
    except Exception as e:
        return {"error": internal_error(e, "get_planning")}


@app.post("/api/planning/item")
def save_planning_item_api(item: Dict[str, Any] = Body(...)):
    """Crée ou met à jour un créneau unique dans la table planning."""
    try:
        from infrastructure.sqlite_repository import SqliteRepository
        saved_item = SqliteRepository.save_planning_item(item)
        return {"status": "success", "message": "Créneau enregistré avec succès.", "item": saved_item}
    except Exception as e:
        return JSONResponse(status_code=400, content={"status": "error", "message": internal_error(e, "save_planning_item_api")})


@app.delete("/api/planning/item/{item_id}")
def delete_planning_item_api(item_id: int):
    """Supprime un créneau de planning par son ID."""
    try:
        from infrastructure.sqlite_repository import SqliteRepository
        ok = SqliteRepository.delete_planning_item(item_id)
        if not ok:
            return JSONResponse(status_code=404, content={"status": "error", "message": f"Créneau #{item_id} introuvable."})
        return {"status": "success", "message": f"Créneau #{item_id} supprimé avec succès."}
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": internal_error(e, "delete_planning_item_api")})


@app.get("/api/planning/export")
def export_planning_api(mode: str = Query("grid"), season: Optional[str] = Query(None)):
    """Exporte le planning au format Excel (grille visuelle hebdomadaire ou liste tabulaire)."""
    import os
    import tempfile
    import shutil
    from infrastructure.sqlite_repository import SqliteRepository
    from infrastructure.planning_excel_export import export_planning_excel, export_planning_list_excel
    from domain.constants import get_active_season

    target_season = season or get_active_season()
    planning_data = SqliteRepository.load_planning_data(log_debug=False)

    tmp_dir = tempfile.mkdtemp(prefix="alj_plan_export_")
    try:
        if mode == "list":
            filename = f"Planning_Liste_{target_season}.xlsx"
            out_path = os.path.join(tmp_dir, filename)
            export_planning_list_excel(planning_data, target_season, out_path)
        else:
            filename = f"Planning_Grille_{target_season}.xlsx"
            out_path = os.path.join(tmp_dir, filename)
            export_planning_excel(planning_data, target_season, out_path)

        with open(out_path, "rb") as f:
            content_bytes = f.read()

        return Response(
            content=content_bytes,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Access-Control-Expose-Headers": "Content-Disposition"
            }
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

# Fichiers web statiques (annuaire, logo...) également servis sous /annuaire/.
# L'annuaire lit la base des adhérents dans Firestore (connexion Google du coach).
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
_web_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")
if os.path.isdir(_web_dir):
    app.mount("/annuaire", StaticFiles(directory=_web_dir, html=True), name="annuaire")

# Ressources communes du portail bureau (CSS, modules JavaScript) : web/shared/.
_shared_dir = os.path.join(_web_dir, "shared")
if os.path.isdir(_shared_dir):
    app.mount("/static-web", StaticFiles(directory=_shared_dir), name="static-web")

_competitions_page_path = os.path.join(_web_dir, "competitions.html")
_annuaire_page_path = os.path.join(_web_dir, "index.html")

# Portail « bureau » (ordinateur) : pages publiques, les données restent protégées
# (lecture Firestore avec le compte Google, appels API avec jeton).
_bureau_dir = os.path.join(_web_dir, "bureau")
_BUREAU_PAGES = {
    "": "index.html",
    "adherents": "adherents.html",
    "communications": "communications.html",
    "competitions": "competitions.html",
    "planning": "planning.html",
    "outils": "outils.html",
    "parametres": "parametres.html"
}


def _bureau_file(page: str):
    name = _BUREAU_PAGES.get(page)
    p = os.path.join(_bureau_dir, name) if name else ""
    if p and os.path.exists(p):
        return FileResponse(p, media_type="text/html")
    return HTMLResponse("<h1>Page bureau introuvable</h1>", status_code=404)

@app.get("/bureau", response_class=HTMLResponse, include_in_schema=False)
@app.get("/bureau/", response_class=HTMLResponse, include_in_schema=False)
def get_bureau_home():
    """Accueil du portail bureau (ordinateur)."""
    return _bureau_file("")

@app.get("/bureau/{page}", response_class=HTMLResponse, include_in_schema=False)
def get_bureau_page(page: str):
    """Pages du portail bureau : seules les pages de _BUREAU_PAGES sont servies."""
    return _bureau_file(page)

@app.get("/index", response_class=HTMLResponse)
def get_annuaire_page():
    """Annuaire des adhérents (lecture seule) : lit la base principale dans
    Firestore (collections crm_*) avec le compte Google du coach."""
    if os.path.exists(_annuaire_page_path):
        return FileResponse(_annuaire_page_path, media_type="text/html")
    return HTMLResponse("<h1>Page web/index.html introuvable</h1>", status_code=404)

@app.get("/manifest.webmanifest")
def get_manifest():
    """Manifeste PWA pour installation sur smartphone."""
    p = os.path.join(_web_dir, "manifest.webmanifest")
    if os.path.exists(p):
        return FileResponse(p, media_type="application/manifest+json")
    return HTMLResponse("Not found", status_code=404)

@app.get("/sw.js")
def get_sw():
    """Service Worker PWA pour cache hors-ligne."""
    p = os.path.join(_web_dir, "sw.js")
    if os.path.exists(p):
        return FileResponse(p, media_type="application/javascript")
    return HTMLResponse("Not found", status_code=404)

@app.get("/runtime-config.js", include_in_schema=False)
def get_runtime_config():
    """Browser runtime configuration (Firebase emulator in dev, nothing in production)."""
    payload = json.dumps(runtime_env.client_config(), ensure_ascii=False)
    return Response(
        content=f"window.ALJ_RUNTIME = Object.freeze({payload});\n",
        media_type="application/javascript",
        headers={"Cache-Control": "no-store"},
    )

@app.get("/health")
def health_check():
    """Vérification de santé (Cloud Run probes, uptime, monitoring)."""
    return {
        "status": "healthy",
        "service": "alj-escalade-api",
        "version": APP_VERSION,
        "season": get_active_season(),
        "timestamp": datetime.datetime.now().isoformat()
    }


@app.get("/")
def root_route():
    """Point d'entrée racine : redirige vers la PWA Mobile des compétitions."""
    if os.path.exists(_competitions_page_path):
        return RedirectResponse(url="/competitions", status_code=302)
    return {
        "service": "ALJ Escalade Cloud API",
        "version": APP_VERSION,
        "docs_url": "/docs",
        "health_url": "/health",
        "competitions_url": "/competitions",
        "annuaire_url": "/index"
    }


def _read_web_version() -> str:
    """Version de la page web (balise <meta name="alj-web-version"> de competitions.html)."""
    import re
    try:
        with open(_competitions_page_path, "r", encoding="utf-8") as f:
            m = re.search(r'<meta name="alj-web-version" content="([^"]+)"', f.read(4000))
        return m.group(1) if m else ""
    except OSError:
        return ""


@app.get("/api/web-version")
def get_web_version():
    """Version en ligne de la page web (jamais mise en cache par le service worker)."""
    return {"web_version": _read_web_version(), "app_version": APP_VERSION}


@app.get("/competitions", response_class=HTMLResponse)
def get_competitions_page():
    """Page web de gestion des compétitions : données en temps réel depuis
    Google Cloud Firestore (même base que l'application de bureau)."""
    if os.path.exists(_competitions_page_path):
        return FileResponse(_competitions_page_path, media_type="text/html")
    return HTMLResponse("<h1>Page web/competitions.html introuvable</h1>", status_code=404)

@app.post("/api/planning")
def update_planning(planning_data: List[Dict[str, Any]] = Body(...)):
    """Met à jour le planning dans la BDD SQLite."""
    try:
        SqliteRepository.save_planning_data(planning_data)
        return {"status": "success", "message": "Planning mis à jour"}
    except Exception as e:
        return {"error": internal_error(e, "update_planning")}


# --------------------------------------------------------------------------
# Micro-service Cloud & Mobile : Webhooks HelloAsso & Envoi d'Emails
# --------------------------------------------------------------------------
from infrastructure.helloasso_webhook_service import HelloAssoWebhookService
from infrastructure.email_dispatch_service import EmailDispatchService


@app.get("/webhooks/helloasso")
def webhook_helloasso_ping():
    """Répond aux vérifications de connectivité HelloAsso (ping HTTP 200)."""
    return {
        "status": "active",
        "endpoint": "helloasso-webhook-receiver",
        "supported_events": ["Payment", "Order"],
        "timestamp": datetime.datetime.now().isoformat()
    }


@app.post("/webhooks/helloasso")
async def webhook_helloasso(payload: Dict[str, Any] = Body(...),
                            token: Optional[str] = Query(None)):
    """Point de terminaison Webhook pour les notifications HelloAsso (Payment & Order).
    Réconcilie en temps réel le paiement avec les participants de la compétition.

    Authenticité : jeton secret dans l'URL (?token=...) et/ou relecture des articles
    auprès de l'API HelloAsso (voir HelloAssoWebhookService.handle_notification).
    """
    from infrastructure.helloasso_webhook_service import WebhookRejected
    if not isinstance(token, str):  # appel direct de la fonction (tests)
        token = None
    try:
        return HelloAssoWebhookService.handle_notification(payload, token=token)
    except WebhookRejected as e:
        print(f"⛔ [WEBHOOK_HELLOASSO] Notification refusée ({e.status_code}) : {e.message}")
        return JSONResponse({"status": "rejected", "message": e.message}, status_code=e.status_code)
    except Exception as e:
        return {"status": "error", "message": internal_error(e, "webhook_helloasso")}


@app.post("/api/competitions/{comp_id}/check-all-paid")
def check_competition_all_paid_api(comp_id: int):
    """Vérifie si tous les compétiteurs ont payé et envoie l'e-mail récapitulatif si applicable."""
    try:
        from infrastructure.helloasso_webhook_service import HelloAssoWebhookService
        notified = HelloAssoWebhookService.check_and_notify_all_paid(comp_id)
        return {
            "status": "success",
            "competition_id": comp_id,
            "notified": notified
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": internal_error(e, "check_competition_all_paid_api")})


@app.get("/api/email-templates")
def get_email_templates():
    """Retourne la liste des modèles d'e-mails configurés."""
    try:
        return {"status": "success", "templates": EmailDispatchService.list_templates()}
    except Exception as e:
        return {"status": "error", "message": internal_error(e, "get_email_templates")}


@app.post("/api/email-templates")
def save_email_template_api(data: Dict[str, Any] = Body(...)):
    """Crée ou met à jour un modèle d'e-mail dans la BDD SQLite (synchronisé avec Firestore)."""
    try:
        from infrastructure.sqlite_repository import SqliteRepository
        name = str(data.get("name") or "").strip()
        old_name = str(data.get("old_name") or "").strip() or None
        subject = str(data.get("subject") or "").strip()
        body = str(data.get("body") or "").strip()
        sender_email = str(data.get("sender_email") or "").strip()
        sender_name = str(data.get("sender_name") or "").strip()

        if not name:
            return JSONResponse(status_code=400, content={"status": "error", "message": "Le nom du modèle est obligatoire."})
        if not subject:
            return JSONResponse(status_code=400, content={"status": "error", "message": "Le sujet du modèle est obligatoire."})

        ok = SqliteRepository.save_email_template(
            name=name,
            subject=subject,
            body=body,
            sender_email=sender_email,
            sender_name=sender_name,
            old_name=old_name
        )
        if not ok:
            return JSONResponse(status_code=500, content={"status": "error", "message": f"Impossible d'enregistrer le modèle '{name}'."})

        return {
            "status": "success",
            "message": f"Modèle d'e-mail '{name}' enregistré avec succès.",
            "template": {
                "name": name,
                "subject": subject,
                "body": body,
                "sender_email": sender_email,
                "sender_name": sender_name
            }
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": internal_error(e, "save_email_template_api")})


@app.delete("/api/email-templates/{template_name}")
def delete_email_template_api(template_name: str):
    """Supprime un modèle d'e-mail par son nom."""
    try:
        from infrastructure.sqlite_repository import SqliteRepository
        import urllib.parse
        clean_name = urllib.parse.unquote(template_name).strip()
        if not clean_name:
            return JSONResponse(status_code=400, content={"status": "error", "message": "Nom de modèle invalide."})

        ok = SqliteRepository.delete_email_template(clean_name)
        if not ok:
            return JSONResponse(status_code=404, content={"status": "error", "message": f"Modèle '{clean_name}' introuvable ou déjà supprimé."})

        return {"status": "success", "message": f"Modèle '{clean_name}' supprimé avec succès."}
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": internal_error(e, "delete_email_template_api")})


@app.get("/api/whatsapp-template")
def get_whatsapp_template_api():
    """Retourne le texte d'invitation WhatsApp mémorisé."""
    try:
        from infrastructure.sqlite_repository import SqliteRepository
        text = SqliteRepository.get_whatsapp_template()
        return {"status": "success", "template": text or ""}
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": internal_error(e, "get_whatsapp_template_api")})


@app.post("/api/whatsapp-template")
def save_whatsapp_template_api(data: Dict[str, Any] = Body(...)):
    """Enregistre le texte d'invitation WhatsApp."""
    try:
        from infrastructure.sqlite_repository import SqliteRepository
        text = str(data.get("template") or "").strip()
        ok = SqliteRepository.save_whatsapp_template(text)
        if not ok:
            return JSONResponse(status_code=500, content={"status": "error", "message": "Impossible d'enregistrer le texte WhatsApp."})
        return {"status": "success", "message": "Texte WhatsApp enregistré avec succès.", "template": text}
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": internal_error(e, "save_whatsapp_template_api")})


@app.post("/api/preview-email")
def preview_email(data: Dict[str, Any] = Body(...)):
    """Génère un aperçu fidèle d'un e-mail personnalisé pour un destinataire et une compétition."""
    try:
        preview_data = EmailDispatchService.preview(
            template_name=data.get("template_name"),
            subject=data.get("subject"),
            body=data.get("body"),
            recipient=data.get("recipient"),
            competition_id=data.get("competition_id"),
            add_signature=data.get("add_signature", True)
        )
        return {"status": "success", "preview": preview_data}
    except Exception as e:
        return {"status": "error", "message": internal_error(e, "preview_email")}


@app.get("/api/email-status")
def get_email_status():
    """Vérifie l'état de la configuration d'envoi d'e-mails (sans exposer de secrets)."""
    gmail_user = SecretStore.get_secret("GMAIL_USER_EMAIL")
    gmail_client_id = SecretStore.get_secret("GMAIL_CLIENT_ID")
    gmail_refresh = SecretStore.get_secret("GMAIL_REFRESH_TOKEN")

    smtp_host = SecretStore.get_secret("SMTP_HOST")
    smtp_user = SecretStore.get_secret("SMTP_USER")
    smtp_password = SecretStore.get_secret("SMTP_PASSWORD")

    use_oauth2 = bool(gmail_user and gmail_client_id and gmail_refresh)
    use_smtp = bool(smtp_host and smtp_user and smtp_password)

    return {
        "status": "success",
        "configured": use_oauth2 or use_smtp,
        "mode": "gmail_oauth2" if use_oauth2 else ("smtp" if use_smtp else "none"),
        "sender": gmail_user if use_oauth2 else (smtp_user if use_smtp else ""),
    }


@app.post("/api/send-email")
def send_email_api(request: Request, data: Dict[str, Any] = Body(...)):
    """Déclenche l'envoi d'e-mails sécurisé via Gmail API ou SMTP avec injection de variables."""
    from infrastructure.api_auth import has_role
    claims = getattr(request.state, "user", None)  # None: token check off (local desktop server)
    reason = EmailDispatchService.unauthorized_send_reason(
        data.get("recipients"), data.get("sender_email"),
        is_admin=claims is None or has_role(claims, "admin"))
    if reason:
        return JSONResponse(status_code=403, content={"status": "error", "message": reason})
    try:
        result = EmailDispatchService.dispatch_emails(
            template_name=data.get("template_name"),
            subject=data.get("subject"),
            body=data.get("body"),
            recipient_ids=data.get("recipient_ids"),
            recipients=data.get("recipients"),
            competition_id=data.get("competition_id"),
            sender_email=data.get("sender_email"),
            sender_name=data.get("sender_name"),
            add_signature=data.get("add_signature", True)
        )
        return result
    except Exception as e:
        return {"status": "error", "message": internal_error(e, "send_email_api")}


@app.post("/api/helloasso/sync")
def sync_helloasso_api():
    """Synchronise la campagne annuelle HelloAsso vers Firestore."""
    try:
        from infrastructure.competition_firestore_repository import CompetitionFirestoreRepository as Repo
        from domain import competition_matching

        slug = Repo.get_app_setting("HELLOASSO_ANNUAL_CAMPAIGN")
        if not (slug or "").strip():
            return {"status": "error", "message": "Aucune campagne annuelle configurée. Veuillez configurer le slug de la campagne."}

        ident = competition_matching.parse_campaign_identifier(slug)
        from helloasso_api import get_items
        items = get_items(ident["form_type"], ident["slug"]) or []
        summarized = competition_matching.summarize_items(items)

        Repo.sync_helloasso_mirror(summarized, items, ident["slug"])

        competitions = [{"id": c.id, "id_ffme": c.id_ffme, "nom": c.nom}
                        for c in Repo.list_competitions()]
        adherents = Repo.list_adherents()
        existing = Repo.list_helloasso_links()
        links = competition_matching.auto_link_items(summarized, competitions, adherents, existing)
        Repo.replace_auto_links(links)

        applied = Repo.apply_links_to_participants()
        unlinked = Repo.list_unlinked_items()

        return {
            "status": "success",
            "stats": {
                "nb_items": len(items),
                "nb_auto": len([lk for lk in (links or {}).values() if lk]),
                "nb_manual": len([e for e in existing.values() if e.get("source") == "manuel"]),
                "nb_applied": applied,
                "nb_unlinked": len(unlinked),
            }
        }
    except Exception as e:
        return {"status": "error", "message": internal_error(e, "sync_helloasso_api")}


# --------------------------------------------------------------------------
# Batch quotidien de récupération des résultats MyCompet FFME & Notifications
# --------------------------------------------------------------------------
@app.post("/api/competitions/cron/fetch-results")
async def api_cron_fetch_competition_results(
    force: bool = False,
    email: Optional[str] = None
):
    """
    Exécute le batch de récupération des résultats MyCompet FFME pour les compétitions passées
    et envoie un e-mail de synthèse si des résultats sont découverts.
    Conçu pour être appelé par Google Cloud Scheduler (ex: tous les jours à 07h00) ou manuellement.
    """
    from infrastructure.competition_results_batch_service import CompetitionResultsBatchService
    res = await run_in_threadpool(CompetitionResultsBatchService.run_daily_batch, force=force, to_email=email)
    return res


@app.post("/api/competitions/{comp_id}/fetch-results")
async def api_fetch_competition_results(comp_id: str, payload: Dict[str, Any] = Body(default={})):
    """
    Récupère les résultats officiels depuis MyCompet FFME pour une compétition donnée,
    extrait les compétiteurs de l'Amicale Laïque de Jonage et met à jour leurs classements.
    """
    from mycompet_scraper import fetch_and_parse_mycompet_results, normalize_result_url, find_mycompet_result_url
    from infrastructure.firestore_client import FirestoreClient

    url = (payload.get("url") or payload.get("result_id") or "").strip()

    comp_doc = None
    try:
        comp_doc = FirestoreClient.get_document("competitions", comp_id)
    except Exception as e:
        print(f"⚠️ [MYCOMPET] Impossible de lire la compétition {comp_id} sur Firestore : {e}")

    if not url and comp_doc:
        url = comp_doc.get("url_resultats") or comp_doc.get("id_resultat_ffme") or ""

    # Détection automatique transparente si aucune URL n'est renseignée
    if not url and comp_doc:
        nom = comp_doc.get("nom") or ""
        date = comp_doc.get("date_competition") or ""
        lieu = comp_doc.get("lieu") or ""
        id_ffme = comp_doc.get("id_ffme") or ""
        auto_url = await run_in_threadpool(find_mycompet_result_url, nom, date, lieu, str(id_ffme))
        if auto_url:
            url = auto_url

    if not url:
        return JSONResponse({
            "status": "needs_url",
            "message": "Résultats introuvables automatiquement sur MyCompet. Veuillez renseigner l'URL ou le numéro de résultat (ex: https://mycompet.ffme.fr/resultat/resultat_13660 ou 13660)."
        }, status_code=404)

    try:
        club_kw = payload.get("club") or "JONAGE"
        scraped_results = await run_in_threadpool(fetch_and_parse_mycompet_results, url, club_kw)
    except Exception as e:
        print(f"❌ [MYCOMPET] Erreur scraping MyCompet ({url}) : {e}")
        return JSONResponse({
            "status": "error",
            "message": f"Erreur lors de la récupération des résultats MyCompet : {e}"
        }, status_code=502)

    matched_count = 0
    participants = list((comp_doc.get("participants") if comp_doc else None) or [])

    now_iso = datetime.datetime.now().isoformat()
    canonical_url = normalize_result_url(url)

    by_licence = {}
    by_name = {}
    for r in scraped_results:
        lic = str(r.get("licence") or "").strip()
        if lic:
            by_licence[lic] = r
        full = f"{r.get('nom', '')} {r.get('prenom', '')}".strip().lower()
        if full:
            by_name[full] = r

    for p in participants:
        p_lic = str(p.get("num_licence") or "").strip()
        p_name = f"{p.get('nom', '')} {p.get('prenom', '')}".strip().lower()

        match = by_licence.get(p_lic) or by_name.get(p_name)
        if match:
            matched_count += 1
            cl = str(match.get("classement") or "").strip()
            tot = int(match.get("total_categorie") or 0)
            p["classement"] = cl
            p["total_categorie"] = tot
            suffix = f" / {tot}" if tot > 0 else "e"
            p["resultat_ffme"] = f"{cl}{suffix}" if cl else ""
            p["categorie_ffme"] = match.get("categorie") or ""
            p["performance_ffme"] = match.get("performance") or ""
            p["resultat_synced_at"] = now_iso

    if comp_doc:
        try:
            FirestoreClient.update_fields("competitions", comp_id, {
                "participants": participants,
                "url_resultats": canonical_url,
                "resultats_synced_at": now_iso
            })
        except Exception as e:
            print(f"⚠️ [MYCOMPET] Erreur mise à jour Firestore : {e}")

    # Sauvegarde miroir dans la base SQLite locale si disponible
    try:
        from infrastructure.competition_repository import CompetitionRepository
        if os.path.exists(CompetitionRepository.get_db_path()):
            CompetitionRepository.setup_database()
            conn = CompetitionRepository.get_connection()
            try:
                conn.execute(
                    "UPDATE competitions SET url_resultats = ?, resultats_synced_at = ? WHERE id = ? OR id_ffme = ?",
                    (canonical_url, now_iso, comp_id, comp_id)
                )
                for p in participants:
                    aid = p.get("adherent_id")
                    if aid:
                        conn.execute(
                            """UPDATE participants SET classement = ?, total_categorie = ?, resultat_ffme = ?,
                               categorie_ffme = ?, performance_ffme = ?, resultat_synced_at = ?
                               WHERE (competition_id = ? OR competition_id = (SELECT id FROM competitions WHERE id_ffme = ?))
                               AND adherent_id = ?""",
                            (p.get("classement") or "", int(p.get("total_categorie") or 0), p.get("resultat_ffme") or "",
                             p.get("categorie_ffme") or "", p.get("performance_ffme") or "",
                             now_iso, comp_id, comp_id, aid)
                        )
                conn.commit()
            finally:
                conn.close()
    except Exception as e:
        print(f"⚠️ [SQLITE] Erreur sauvegarde locale des résultats : {e}")

    return {
        "status": "success",
        "url": canonical_url,
        "total_scraped": len(scraped_results),
        "matched_count": matched_count,
        "results": scraped_results,
        "participants": participants
    }


@app.get("/api/settings/competitions-results")
def get_competitions_results_settings_api():
    """Retourne la configuration et l'état du batch quotidien de résultats."""
    from infrastructure.competition_results_batch_service import CompetitionResultsBatchService
    return {
        "status": "success",
        **CompetitionResultsBatchService.get_batch_status()
    }


@app.post("/api/settings/competitions-results")
def update_competitions_results_settings_api(data: Dict[str, Any] = Body(...)):
    """Met à jour l'adresse e-mail de notification des résultats."""
    from infrastructure.competition_results_batch_service import CompetitionResultsBatchService
    email = str(data.get("notification_email") or "").strip()
    if not email or "@" not in email or "." not in email:
        raise HTTPException(status_code=400, detail="Adresse e-mail de notification invalide.")

    ok = CompetitionResultsBatchService.set_notification_email(email)
    return {
        "status": "success",
        "notification_email": CompetitionResultsBatchService.get_notification_email(),
        "saved": ok
    }


# --------------------------------------------------------------------------
# Attestations de paiement PDF (un adhérent à la fois, admin uniquement)
# --------------------------------------------------------------------------
@app.post("/api/attestations/preview")
def preview_attestation_api(data: Dict[str, Any] = Body(...)):
    """Génère l'aperçu PDF d'une attestation de paiement (retourne application/pdf)."""
    try:
        from domain.attestation import build_attestation, render_attestation_pdf, get_safe_pdf_filename
        member = data.get("member") or {}
        season = data.get("season")
        date_jour = data.get("date_jour")

        html = build_attestation(member, season=season, date_jour=date_jour)
        pdf_bytes = render_attestation_pdf(html)

        last_name = member.get("last_name") or member.get("user_last_name") or "ADHERENT"
        first_name = member.get("first_name") or member.get("user_first_name") or ""
        order_ref = member.get("order_ref")
        filename = get_safe_pdf_filename(last_name, first_name, order_ref)

        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'inline; filename="{filename}"'}
        )
    except Exception as e:
        return JSONResponse(status_code=400, content={"status": "error", "message": client_error(e, "preview_attestation_api")})


@app.post("/api/attestations/send")
def send_attestation_api(data: Dict[str, Any] = Body(...)):
    """Génère une attestation PDF en mémoire, l'envoie par e-mail et met à jour la date d'envoi."""
    try:
        from domain.attestation import build_attestation, render_attestation_pdf, get_safe_pdf_filename
        from domain.utils import apply_template_variables
        from infrastructure.email_repository import EmailRepository

        member = data.get("member") or {}
        season = data.get("season")
        to_email = (data.get("to_email") or member.get("email_primary") or "").strip()
        if not to_email or "@" not in to_email:
            return JSONResponse(status_code=400, content={"status": "error", "message": "Adresse e-mail du destinataire invalide ou manquante."})

        html = build_attestation(member, season=season)
        pdf_bytes = render_attestation_pdf(html)

        last_name = member.get("last_name") or member.get("user_last_name") or "ADHERENT"
        first_name = member.get("first_name") or member.get("user_first_name") or ""
        order_ref = member.get("order_ref")
        filename_pdf = get_safe_pdf_filename(last_name, first_name, order_ref)

        template_name = (data.get("template_name") or "Attestation échéance").strip()
        from infrastructure.email_dispatch_service import EmailDispatchService
        tmpl = EmailDispatchService.get_template_by_name(template_name)

        raw_subject = data.get("subject") or (tmpl.get("subject") if tmpl else None) or "Attestation de paiement et d'échéance - Amicale Laïque de Jonage"
        raw_body = data.get("body") or (tmpl.get("body") if tmpl else None) or (
            "Bonjour {first_name},\n\n"
            "Nous avons le plaisir de vous transmettre en pièce jointe l'attestation de paiement pour votre adhésion ou celle de votre enfant à la section escalade de l'Amicale Laïque de Jonage.\n\n"
            "Sportivement,\n"
            "L'équipe ALJ Escalade"
        )
        subject = apply_template_variables(raw_subject, member)
        body = apply_template_variables(raw_body, member)

        sender_email = data.get("sender_email") or (tmpl.get("sender_email") if tmpl else None) or "inscription@alj-escalade.fr"
        if not EmailDispatchService.is_allowed_sender(sender_email):
            return JSONResponse(status_code=403, content={
                "status": "error", "message": f"Adresse d'expédition non autorisée : {sender_email}"})
        sender_name = data.get("sender_name") or (tmpl.get("sender_name") if tmpl else None) or "Amicale Laïque Jonage - Inscriptions"

        add_signature = data.get("add_signature", True)
        from email_html import build_email_html, build_signature_plain, get_inline_images
        # HTML built from the template, then personalised with escaped values
        html_body = apply_template_variables(
            build_email_html(raw_body, add_signature=True, image_src_mode="cid"), member, escape_html=True
        ) if add_signature else None
        plain_body = body + ("\n\n" + build_signature_plain() if add_signature else "")
        inline_images = get_inline_images() if add_signature else []

        ok = EmailRepository.send_email(
            to_email=to_email,
            subject=subject,
            body=plain_body,
            html_body=html_body,
            attachment_bytes=pdf_bytes,
            attachment_filename=filename_pdf,
            inline_images=inline_images,
            from_email=sender_email,
            from_name=sender_name
        )
        if not ok:
            return JSONResponse(status_code=500, content={"status": "error", "message": "Échec d'envoi de l'e-mail."})

        # Enregistrement de la date d'envoi de l'attestation dans SQLite
        # (CloudDatabase.after_write synchronisera automatiquement la modification vers Firestore)
        now_str = datetime.datetime.now().strftime("%d/%m/%Y")
        try:
            from infrastructure.sqlite_repository import SqliteRepository
            pid = member.get("purchase_id")
            SqliteRepository.update_email_sent_date(
                order_ref=str(order_ref or "").strip(),
                last_name=str(last_name or "").strip(),
                first_name=str(first_name or "").strip(),
                date_str=now_str,
                purchase_id=int(pid) if pid is not None else None
            )
        except Exception as db_err:
            print(f"⚠️ [ATTESTATION] Erreur enregistrement date d'envoi dans SQLite : {db_err}")

        return {
            "status": "success",
            "message": f"Attestation envoyée avec succès à {to_email}.",
            "email_sent_date": now_str,
            "filename": filename_pdf
        }
    except Exception as e:
        return JSONResponse(status_code=400, content={"status": "error", "message": client_error(e, "send_attestation_api")})


# --------------------------------------------------------------------------
# Fiches de Présence Excel (Téléchargement direct dans le navigateur)
# --------------------------------------------------------------------------
@app.get("/api/presence/config")
def get_presence_config():
    """Renvoie les groupes disponibles (autonomes et cours) et leurs statistiques pour l'IHM."""
    try:
        import datetime
        from infrastructure.sqlite_repository import SqliteRepository
        from domain.planning_groups import is_autonome_creneau
        from domain.constants import get_active_season
        from presence_sheet_generator import SEASON_COURSE_START, SEASON_COURSE_END

        season = get_active_season()
        creneaux = SqliteRepository.load_creneaux_groups()
        raw_data = SqliteRepository.load_direct_data(season_filter=season)

        # 1. Groupes autonomes
        aut_creneaux = [c for c in creneaux if is_autonome_creneau(c)]
        aut_tarifs = set()
        for c in aut_creneaux:
            for t in (c.get("tarifs") or []):
                aut_tarifs.add(str(t).strip())

        today = datetime.date.today()
        def _dob_of(p):
            s = str(p.get("birth_date") or p.get("champ_Date de naissance de l'adhérent") or "").strip()
            for fmt, sliced in (("%Y-%m-%d", True), ("%d/%m/%Y", False)):
                try:
                    return datetime.datetime.strptime(s[:10] if sliced else s, fmt).date()
                except ValueError:
                    continue
            return None

        # Comptage autonome
        aut_adultes = 0
        aut_mineurs = 0
        counted_keys = set()
        for p in raw_data:
            tarif = str(p.get("tarif_name") or "").strip()
            if tarif not in aut_tarifs or "annul" in str(p.get("status") or "").lower():
                continue
            dob = _dob_of(p)
            ikey = (str(p.get("first_name") or "").strip().lower(), str(p.get("last_name") or "").strip().lower(), dob.isoformat() if dob else "")
            if ikey in counted_keys:
                continue
            counted_keys.add(ikey)
            if dob:
                age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
                if age < 18:
                    aut_mineurs += 1
                else:
                    aut_adultes += 1
            else:
                aut_adultes += 1

        # Mineurs autorisés ajoutés d'autres groupes
        added_minors = 0
        added_seen = set()
        for p in raw_data:
            if "annul" in str(p.get("status") or "").lower():
                continue
            if not (str(p.get("parental_auth_autonomous") or "").strip() == "Oui" or str(p.get("parental_auth_family") or "").strip() == "Oui"):
                continue
            dob = _dob_of(p)
            ikey = (str(p.get("first_name") or "").strip().lower(), str(p.get("last_name") or "").strip().lower(), dob.isoformat() if dob else "")
            if ikey in counted_keys or ikey in added_seen:
                continue
            if dob:
                age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
                if age >= 18:
                    continue
            added_seen.add(ikey)
            added_minors += 1

        # 2. Groupes de cours
        cours_creneaux = [c for c in creneaux if not is_autonome_creneau(c)]
        cours_list = []
        for c in cours_creneaux:
            c_tarifs = set(str(t).strip() for t in (c.get("tarifs") or []))
            count = 0
            c_seen = set()
            for p in raw_data:
                if "annul" in str(p.get("status") or "").lower():
                    continue
                if str(p.get("tarif_name") or "").strip() in c_tarifs:
                    dob = _dob_of(p)
                    ikey = (str(p.get("first_name") or "").strip().lower(), str(p.get("last_name") or "").strip().lower(), dob.isoformat() if dob else "")
                    if ikey not in c_seen:
                        c_seen.add(ikey)
                        count += 1
            slots_str = " · ".join(f"{j} {h}".strip() for j, h in c["slots"] if j or h)
            cours_list.append({
                "groupe": c["groupe"],
                "slots": slots_str,
                "tarifs": c["tarifs"],
                "count": count,
            })

        return {
            "status": "success",
            "season": season,
            "default_dates": {
                "start": SEASON_COURSE_START.strftime("%d/%m/%Y"),
                "end": SEASON_COURSE_END.strftime("%d/%m/%Y")
            },
            "autonome": {
                "adultes": aut_adultes,
                "mineurs": aut_mineurs,
                "mineurs_autorises": added_minors,
                "total": aut_adultes + aut_mineurs + added_minors,
                "groups": [c["groupe"] for c in aut_creneaux],
            },
            "cours": cours_list
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": f"Erreur chargement config présence : {e}"})


@app.post("/api/presence/export")
def export_presence_api(data: Dict[str, Any] = Body(...)):
    """Génère les fiches de présence au format Excel et les renvoie directement en téléchargement."""
    import os
    import shutil
    import tempfile
    import zipfile
    from presence_sheet_generator import generate_presence_sheets
    from infrastructure.sqlite_repository import SqliteRepository
    from domain.planning_groups import is_autonome_creneau
    from domain.constants import get_active_season

    try:
        season = data.get("season") or get_active_season()
        raw_data = SqliteRepository.load_direct_data(season_filter=season)
        creneaux = SqliteRepository.load_creneaux_groups()

        variant = (data.get("variant") or "cours").strip().lower()
        start_date = (data.get("start_date") or "").strip() or None
        end_date = (data.get("end_date") or "").strip() or None
        show_health_col = bool(data.get("show_health_col", False))

        if variant == "autonome":
            aut_creneaux = [c for c in creneaux if is_autonome_creneau(c)]
            selected_groups = [c["groupe"] for c in aut_creneaux]
            group_tarifs_map = {c["groupe"]: c["tarifs"] for c in aut_creneaux}
            merge_groups = True
            auth_only = True
            hide_badge_cols = False
            same_sheet = False
        else:
            cours_creneaux = [c for c in creneaux if not is_autonome_creneau(c)]
            user_groups = data.get("selected_groups") or []
            if user_groups:
                selected_groups = [c["groupe"] for c in cours_creneaux if c["groupe"] in user_groups]
            else:
                selected_groups = [c["groupe"] for c in cours_creneaux]
            group_tarifs_map = {c["groupe"]: c["tarifs"] for c in cours_creneaux if c["groupe"] in selected_groups}
            merge_groups = False
            auth_only = False
            hide_badge_cols = True
            same_sheet = bool(data.get("same_sheet", True))

        if not selected_groups:
            return JSONResponse(status_code=400, content={"status": "error", "message": "Aucun groupe sélectionné pour l'export."})

        tmp_dir = tempfile.mkdtemp(prefix="alj_presence_")
        try:
            ok, files = generate_presence_sheets(
                selected_groups=selected_groups,
                participants_data=raw_data,
                start_date_str=start_date,
                end_date_str=end_date,
                merge_groups=merge_groups,
                auth_only=auth_only,
                hide_badge_cols=hide_badge_cols,
                same_sheet=same_sheet,
                group_tarifs_map=group_tarifs_map,
                show_health_col=show_health_col,
                output_dir=tmp_dir,
            )
            if not ok or not files:
                return JSONResponse(status_code=400, content={"status": "error", "message": f"Erreur de génération : {files}"})

            if len(files) == 1:
                filename = files[0]
                file_path = os.path.join(tmp_dir, filename)
                with open(file_path, "rb") as f:
                    content_bytes = f.read()
                return Response(
                    content=content_bytes,
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={
                        "Content-Disposition": f'attachment; filename="{filename}"',
                        "Access-Control-Expose-Headers": "Content-Disposition"
                    }
                )
            else:
                zip_filename = f"Fiches_Presence_{variant.capitalize()}_{season}.zip"
                zip_path = os.path.join(tmp_dir, zip_filename)
                with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                    for fname in files:
                        fpath = os.path.join(tmp_dir, fname)
                        if os.path.exists(fpath):
                            zf.write(fpath, arcname=fname)
                with open(zip_path, "rb") as f:
                    zip_bytes = f.read()
                return Response(
                    content=zip_bytes,
                    media_type="application/zip",
                    headers={
                        "Content-Disposition": f'attachment; filename="{zip_filename}"',
                        "Access-Control-Expose-Headers": "Content-Disposition"
                    }
                )
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": f"Erreur serveur lors de la génération : {e}"})


# --------------------------------------------------------------------------
# Export Fédéral FFME (CSV)
# --------------------------------------------------------------------------
@app.get("/api/ffme/stats")
def get_ffme_stats_api(season: Optional[str] = None):
    """Calcule et renvoie les statistiques de l'export fédéral FFME."""
    try:
        import datetime
        from infrastructure.sqlite_repository import SqliteRepository
        from domain.constants import get_active_season
        from create_excel import parse_date_to_datetime, clean_digits_only

        target_season = season or get_active_season()
        participants = SqliteRepository.load_direct_data(season_filter=target_season)

        produced_count = 0
        ignored_count = 0
        termine_count = 0
        renewals_count = 0
        new_licences_count = 0
        ignored_details = []

        now = datetime.datetime.now()

        for p in participants:
            tarif_name = str(p.get("tarif_name") or "").lower()
            amount = p.get("amount", 0.0)
            status = str(p.get("status") or "").lower()
            commentaires = str(p.get("commentaires_correctif") or "").lower()
            is_manual = "ajout manuel" in commentaires

            # 1. Ignoré (liste d'attente, montant nul non manuel, annulé)
            if "attente" in tarif_name or (amount == 0.0 and not is_manual) or "annul" in status or "cancel" in status:
                ignored_count += 1
                continue

            # 2. Date de naissance manquante ou invalide
            dob_val = p.get("birth_date") or p.get("champ_Date de naissance de l'adhérent") or ""
            dob_date = None
            if isinstance(dob_val, (datetime.datetime, datetime.date)):
                dob_date = dob_val
            else:
                parsed_dt = parse_date_to_datetime(str(dob_val).strip())
                if isinstance(parsed_dt, (datetime.datetime, datetime.date)):
                    dob_date = parsed_dt

            if not dob_date or dob_date >= now:
                ignored_count += 1
                nom = str(p.get("last_name") or "Inconnu").strip().upper()
                prenom = str(p.get("first_name") or "Inconnu").strip()
                ignored_details.append(f"{nom} {prenom} (date de naissance manquante/invalide)")
                continue

            # 3. Terminé ou à produire
            lic = clean_digits_only(p.get("licence_ffme") or "")
            is_renewal = 5 <= len(lic) <= 10

            if "termin" in status:
                termine_count += 1
            else:
                produced_count += 1

            if is_renewal:
                renewals_count += 1
            else:
                new_licences_count += 1

        return {
            "status": "success",
            "season": target_season,
            "produced_count": produced_count,
            "termine_count": termine_count,
            "ignored_count": ignored_count,
            "estimated_total": produced_count + termine_count,
            "renewals_count": renewals_count,
            "new_licences_count": new_licences_count,
            "ignored_details": ignored_details[:20]
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": internal_error(e, "get_ffme_stats_api")})


@app.get("/api/ffme/export")
def export_ffme_api(season: Optional[str] = None, include_termine: bool = Query(True)):
    """Génère le fichier CSV d'import FFME et le renvoie directement en téléchargement."""
    import os
    import tempfile
    import datetime
    from infrastructure.sqlite_repository import SqliteRepository
    from domain.constants import get_active_season
    from create_excel import generate_ffme_csv

    try:
        target_season = season or get_active_season()
        raw_data = SqliteRepository.load_direct_data(season_filter=target_season)

        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"import_ffme_{timestamp}.csv"
        
        tmp_dir = tempfile.mkdtemp(prefix="alj_ffme_export_")
        tmp_csv = os.path.join(tmp_dir, filename)

        try:
            ignored = generate_ffme_csv(raw_data, output_path=tmp_csv, include_termine=include_termine)
            with open(tmp_csv, "rb") as f:
                content_bytes = f.read()

            return Response(
                content=content_bytes,
                media_type="text/csv; charset=utf-8",
                headers={
                    "Content-Disposition": f'attachment; filename="{filename}"',
                    "Access-Control-Expose-Headers": "Content-Disposition"
                }
            )
        finally:
            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": internal_error(e, "export_ffme_api")})


# --------------------------------------------------------------------------
# Importation & Rapprochement Fédéral FFME (Excel)
# --------------------------------------------------------------------------
@app.post("/api/ffme/preview")
def preview_ffme_import_api(data: Dict[str, Any] = Body(...)):
    """Analyse un fichier Excel FFME et prépare le rapprochement sans modifier la base."""
    import base64
    import tempfile
    import os
    from infrastructure.sqlite_repository import SqliteRepository

    try:
        content_b64 = data.get("content_base64") or ""
        filename = str(data.get("filename") or "licencies_ffme.xlsx").strip()

        if not content_b64:
            return JSONResponse(status_code=400, content={"status": "error", "message": "Fichier Excel manquant (content_base64 obligatoire)."})

        file_bytes = base64.b64decode(content_b64)
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name

        try:
            prep = SqliteRepository.prepare_ffme_licensees(tmp_path)
            stats = prep.get("stats", {})
            if stats.get("errors") and not prep.get("updates"):
                return JSONResponse(status_code=400, content={"status": "error", "message": stats["errors"][0], "errors": stats["errors"]})

            return {
                "status": "success",
                "filename": filename,
                "stats": stats,
                "matched_count": len(prep.get("updates", [])),
                "unmatched_count": len(prep.get("unmatched", [])),
                "updates": prep.get("updates", []),
                "unmatched": prep.get("unmatched", []),
                "users": prep.get("users", [])
            }
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": internal_error(e, "preview_ffme_import_api")})


@app.post("/api/ffme/import")
def apply_ffme_import_api(data: Dict[str, Any] = Body(...)):
    """Applique l'importation FFME en BDD (mises à jour automatiques + associations manuelles)."""
    import base64
    import os
    import tempfile
    from infrastructure.sqlite_repository import SqliteRepository
    from domain.constants import get_active_season
    from paths import ROOT_DIR

    try:
        season = str(data.get("season") or get_active_season()).strip()
        updates = list(data.get("updates") or [])
        manual_matches = list(data.get("manual_matches") or [])
        content_b64 = data.get("content_base64")
        filename = str(data.get("filename") or "import_ffme.xlsx").strip()

        # Si pas d'updates fournis mais content_b64 fourni : préparer automatiquement
        stats = {
            "total_processed": 0,
            "matched_by_licence": 0,
            "matched_by_name": 0,
            "matched_manually": 0,
            "errors": []
        }

        if not updates and content_b64:
            file_bytes = base64.b64decode(content_b64)
            with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
                tmp.write(file_bytes)
                tmp_path = tmp.name
            try:
                prep = SqliteRepository.prepare_ffme_licensees(tmp_path)
                updates = prep.get("updates", [])
                stats = prep.get("stats", {})
            finally:
                if os.path.exists(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except Exception:
                        pass
        elif data.get("stats"):
            stats = dict(data.get("stats"))

        # Ajouter les associations manuelles
        matched_manually = 0
        for m in manual_matches:
            uid = m.get("user_id")
            if uid:
                updates.append((
                    "Terminé",
                    str(m.get("licence") or "").strip(),
                    str(m.get("passeports") or "").strip(),
                    str(m.get("diplomes") or "").strip(),
                    str(m.get("document_sante") or "").strip(),
                    int(uid)
                ))
                matched_manually += 1

        stats["matched_manually"] = matched_manually

        if not updates:
            return JSONResponse(
                status_code=400,
                content={"status": "error", "message": "Aucune mise à jour à appliquer (aucun rapprochement trouvé)."}
            )

        ok = SqliteRepository.apply_ffme_matches(updates, season_name=season)
        if not ok:
            return JSONResponse(status_code=500, content={"status": "error", "message": "Échec de l'écriture des associations en base de données."})

        # Sauvegarde éventuelle d'une copie dans import/ffme/
        if content_b64:
            try:
                dest_dir = os.path.join(ROOT_DIR, "import", "ffme")
                os.makedirs(dest_dir, exist_ok=True)
                dest_path = os.path.join(dest_dir, filename)
                file_bytes = base64.b64decode(content_b64)
                with open(dest_path, "wb") as f:
                    f.write(file_bytes)
            except Exception as se:
                print(f"[FFME IMPORT] Copie locale du fichier non critique : {se}")

        from infrastructure.cloud_database import CloudDatabase
        if CloudDatabase.is_enabled():
            CloudDatabase.after_write()

        return {
            "status": "success",
            "message": f"Importation FFME validée : {len(updates)} adhérents mis à jour.",
            "updated_count": len(updates),
            "matched_manually": matched_manually,
            "season": season,
            "stats": stats
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": internal_error(e, "apply_ffme_import_api")})


@app.get("/api/season-tarifs")
def get_season_tarifs_api(season: Optional[str] = None):
    """Retourne la liste des tarifs HelloAsso (groupes disponibles) d'une saison pour l'édition de créneau."""
    try:
        from infrastructure.sqlite_repository import SqliteRepository
        from domain.constants import get_active_season
        target_season = season or get_active_season()
        tarifs = SqliteRepository.get_season_tarifs(target_season)
        return {"status": "success", "season": target_season, "tarifs": tarifs}
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": internal_error(e, "get_season_tarifs_api")})


@app.post("/api/members/update")
def update_member_api(data: Dict[str, Any] = Body(...)):
    """Met à jour les informations d'un adhérent (badge rouge, autonomie bloc, créneau/tarif, e-mails, téléphone)."""
    try:
        from infrastructure.sqlite_repository import SqliteRepository
        user_id = data.get("user_id")
        purchase_id = data.get("purchase_id")
        order_ref = data.get("order_ref")
        fields = data.get("fields") or {}

        if not user_id and not purchase_id and not order_ref:
            return JSONResponse(
                status_code=400,
                content={"status": "error", "message": "Identifiant d'adhérent manquant (user_id, purchase_id ou order_ref)."}
            )

        success, err = SqliteRepository.update_member_fields(
            user_id=int(user_id) if user_id is not None else None,
            fields=fields,
            purchase_id=int(purchase_id) if purchase_id is not None else None,
            order_ref=str(order_ref).strip() if order_ref else None
        )

        if not success:
            return JSONResponse(status_code=400, content={"status": "error", "message": err})

        return {
            "status": "success",
            "message": "Fiche adhérent mise à jour avec succès.",
            "user_id": user_id,
            "fields": fields
        }
    except Exception as e:
        return JSONResponse(status_code=400, content={"status": "error", "message": internal_error(e, "update_member_api")})


@app.post("/api/members/create")
@app.post("/api/members/add")
def add_member_api(data: Dict[str, Any] = Body(...)):
    """Ajoute manuellement un adhérent dans la base (saison active ou saison spécifiée)."""
    try:
        from infrastructure.sqlite_repository import SqliteRepository
        from domain.constants import get_active_season

        fields = data.get("fields") or data
        season = str(data.get("season") or fields.get("season") or get_active_season()).strip()

        last_name = str(fields.get("last_name") or "").strip()
        first_name = str(fields.get("first_name") or "").strip()
        birth_date = str(fields.get("birth_date") or "").strip()
        tarif_name = str(fields.get("tarif_name") or "").strip()

        if not last_name or not first_name:
            return JSONResponse(
                status_code=400,
                content={"status": "error", "message": "Le nom et le prénom de l'adhérent sont obligatoires."}
            )
        if not birth_date:
            return JSONResponse(
                status_code=400,
                content={"status": "error", "message": "La date de naissance est obligatoire."}
            )
        if not tarif_name:
            return JSONResponse(
                status_code=400,
                content={"status": "error", "message": "Le groupe (tarif) est obligatoire."}
            )

        success, res = SqliteRepository.add_manual_member(fields, season_name=season)
        if not success:
            return JSONResponse(status_code=400, content={"status": "error", "message": res})

        from infrastructure.cloud_database import CloudDatabase
        if CloudDatabase.is_enabled():
            CloudDatabase.after_write()

        return {
            "status": "success",
            "message": f"Adhérent {first_name} {last_name} ajouté avec succès.",
            "order_ref": res,
            "season": season
        }
    except Exception as e:
        return JSONResponse(status_code=400, content={"status": "error", "message": internal_error(e, "add_member_api")})


# --------------------------------------------------------------------------
# Renouvellement et Gestion OAuth2 Google (Gmail API, Drive & Firestore)
# --------------------------------------------------------------------------
@app.get("/api/auth/google/status")
def get_google_auth_status():
    """Vérifie l'état de la connexion Google OAuth2 et la validité du jeton d'accès pour la BDD et Gmail."""
    from infrastructure.google_drive_client import GoogleDriveClient
    from infrastructure.cloud_database import CloudDatabase
    
    client_id, client_secret = GoogleDriveClient.get_client_credentials()
    refresh_token = SecretStore.get_secret("GMAIL_REFRESH_TOKEN")
    user_email = SecretStore.get_secret("GMAIL_USER_EMAIL")
    backend = (SecretStore.get_secret("MEMBER_BACKEND") or "firestore").strip().lower()

    configured = bool(client_id and refresh_token)
    valid = False
    error_msg = ""
    
    if configured:
        try:
            tok = GoogleDriveClient.get_access_token()
            valid = bool(tok)
        except Exception as e:
            valid = False
            error_msg = str(e)
            
    db_ready = CloudDatabase.cache_ready() if CloudDatabase.is_enabled() else False

    status = "connected" if valid else ("expired" if refresh_token else "disconnected")

    return {
        "status": status,
        "valid": valid,
        "configured": configured,
        "client_id_configured": bool(client_id),
        "refresh_token_present": bool(refresh_token),
        "user_email": user_email,
        "backend": backend,
        "db_accessible": db_ready or valid,
        "error": error_msg,
    }


@app.get("/api/auth/google/login")
def google_auth_login(request: Request, return_to: Optional[str] = "/bureau/parametres", redirect_uri: Optional[str] = None):
    """Initie le flux d'autorisation OAuth2 Google pour renouveler le refresh token."""
    import base64
    import urllib.parse
    from infrastructure.google_drive_client import GoogleDriveClient
    
    client_id, _ = GoogleDriveClient.get_client_credentials(prefer_web=True)
    if not client_id:
        return HTMLResponse(
            "<h2>❌ Erreur de configuration Google OAuth2</h2>"
            "<p>Aucun identifiant client Google (GMAIL_CLIENT_ID ou client_secret_*.json) n'a été trouvé sur le serveur.</p>"
            "<p><a href='/bureau/parametres'>Retour aux paramètres</a></p>",
            status_code=500
        )

    # Détecter dynamiquement la redirect_uri
    if not redirect_uri:
        proto = request.headers.get("x-forwarded-proto") or request.url.scheme
        if "," in proto:
            proto = proto.split(",")[0].strip()
        host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
        if "," in host:
            host = host.split(",")[0].strip()
        redirect_uri = f"{proto}://{host}/api/auth/google/callback"

    # Construire le state
    state_payload = {
        "redirect_uri": redirect_uri,
        "return_to": return_to or "/bureau/parametres",
        "ts": time.time(),
    }
    state = base64.urlsafe_b64encode(json.dumps(state_payload).encode("utf-8")).decode("utf-8")

    scopes = [
        "https://www.googleapis.com/auth/gmail.send",
        "https://mail.google.com/",
        "https://www.googleapis.com/auth/userinfo.email",
        "https://www.googleapis.com/auth/drive",
        "https://www.googleapis.com/auth/contacts",
        "https://www.googleapis.com/auth/datastore",
    ]
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(scopes),
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    auth_url = f"https://accounts.google.com/o/oauth2/auth?{urllib.parse.urlencode(params)}"
    return RedirectResponse(auth_url, status_code=302)


@app.get("/api/auth/google/callback", response_class=HTMLResponse)
def google_auth_callback(
    request: Request,
    code: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    error: Optional[str] = Query(None)
):
    """Réceptionne le code d'autorisation OAuth2 de Google, échange contre le refresh_token et enregistre les identifiants."""
    import base64
    import requests
    from infrastructure.google_drive_client import GoogleDriveClient
    from infrastructure.cloud_database import CloudDatabase

    def _render_page(title: str, body_html: str, return_url: str = "/bureau/parametres", auto_redirect: bool = False):
        redirect_script = f"<script>setTimeout(function() {{ window.location.href = '{return_url}'; }}, 3500);</script>" if auto_redirect else ""
        return f"""<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{title} — ALJ Escalade</title>
    <style>
        body {{
            margin: 0; padding: 20px; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: #F1F5F9; color: #1E293B; display: flex; align-items: center; justify-content: center; min-height: 90vh;
        }}
        .card {{
            background: #fff; border-radius: 14px; box-shadow: 0 4px 15px rgba(15,23,42,0.1);
            max-width: 520px; width: 100%; padding: 32px 28px; text-align: center; border: 1px solid #E2E8F0;
        }}
        h2 {{ margin-top: 0; color: #0F172A; font-size: 20px; }}
        p {{ color: #475569; font-size: 14.5px; line-height: 1.5; }}
        .badge {{
            display: inline-block; padding: 6px 14px; border-radius: 999px; font-weight: 700; font-size: 13px; margin: 12px 0 16px;
        }}
        .badge-success {{ background: #DCFCE7; color: #166534; }}
        .badge-error {{ background: #FEE2E2; color: #991B1B; }}
        .btn {{
            display: inline-block; padding: 10px 22px; border-radius: 9px; font-size: 14px; font-weight: 700;
            text-decoration: none; color: #fff; background: #2563EB; border: none; cursor: pointer; margin-top: 15px;
        }}
        .btn:hover {{ background: #1D4ED8; }}
        .details {{ text-align: left; background: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 8px; padding: 12px; margin: 15px 0; font-size: 12px; }}
    </style>
    {redirect_script}
</head>
<body>
    <div class="card">
        {body_html}
    </div>
</body>
</html>"""

    if error:
        return _render_page(
            "Connexion refusée",
            f"""<h2>❌ Autorisation Google refusée</h2>
            <div class="badge badge-error">Erreur : {error}</div>
            <p>La connexion au compte Google a été annulée ou refusée.</p>
            <p><a href="/bureau/parametres" class="btn">Retour aux paramètres</a></p>"""
        )

    if not code:
        return _render_page(
            "Code manquant",
            """<h2>❌ Code d'autorisation manquant</h2>
            <div class="badge badge-error">Requête incomplète</div>
            <p>Google n'a pas transmis de code de validation.</p>
            <p><a href="/bureau/parametres" class="btn">Retour aux paramètres</a></p>"""
        )

    # Récupérer return_to et redirect_uri depuis le state
    return_to = "/bureau/parametres"
    redirect_uri = ""
    if state:
        try:
            raw_state = base64.urlsafe_b64decode(state.encode("utf-8")).decode("utf-8")
            state_data = json.loads(raw_state)
            return_to = state_data.get("return_to", "/bureau/parametres")
            redirect_uri = state_data.get("redirect_uri", "")
        except Exception:
            pass

    if not redirect_uri:
        proto = request.headers.get("x-forwarded-proto") or request.url.scheme
        if "," in proto:
            proto = proto.split(",")[0].strip()
        host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
        if "," in host:
            host = host.split(",")[0].strip()
        redirect_uri = f"{proto}://{host}/api/auth/google/callback"

    client_id, client_secret = GoogleDriveClient.get_client_credentials(prefer_web=True)
    if not client_id or not client_secret:
        return _render_page(
            "Configuration incomplète",
            """<h2>❌ Identifiants Google manquants</h2>
            <div class="badge badge-error">GMAIL_CLIENT_ID ou SECRET introuvable</div>
            <p>Impossible d'échanger le code : le client_secret est manquant sur le serveur.</p>
            <p><a href="/bureau/parametres" class="btn">Retour aux paramètres</a></p>"""
        )

    token_url = "https://oauth2.googleapis.com/token"
    token_params = {
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }
    
    try:
        token_resp = requests.post(token_url, data=token_params, timeout=15)
    except Exception as e:
        return _render_page(
            "Erreur réseau",
            f"""<h2>❌ Échec de la communication avec Google</h2>
            <div class="badge badge-error">Erreur de connexion</div>
            <p>{str(e)}</p>
            <p><a href="/bureau/outils" class="btn">Retour au bureau</a></p>"""
        )

    if token_resp.status_code != 200:
        err_detail = token_resp.text
        return _render_page(
            "Échec d'échange de jeton",
            f"""<h2>❌ Échange de jeton échoué</h2>
            <div class="badge badge-error">HTTP {token_resp.status_code}</div>
            <p>Google a refusé l'échange du code d'autorisation :</p>
            <div class="details"><pre style="margin:0; white-space:pre-wrap;">{err_detail}</pre></div>
            <p><b>Vérification conseillée :</b> assurez-vous que l'URI de redirection suivante est bien autorisée dans votre Google Cloud Console :<br>
            <code>{redirect_uri}</code></p>
            <p><a href="/bureau/outils" class="btn">Retour au bureau</a></p>"""
        )

    tokens = token_resp.json()
    refresh_token = tokens.get("refresh_token")
    access_token = tokens.get("access_token")

    if not refresh_token:
        refresh_token = SecretStore.get_secret("GMAIL_REFRESH_TOKEN")

    if not refresh_token:
        return _render_page(
            "Refresh Token absent",
            """<h2>⚠️ Google n'a pas renvoyé de Refresh Token</h2>
            <div class="badge badge-error">Consentement incomplet</div>
            <p>Pour forcer Google à générer un nouveau refresh token, révoquez l'accès de l'application dans votre compte Google puis relancez la connexion.</p>
            <p><a href="/bureau/outils" class="btn">Retour au bureau</a></p>"""
        )

    # Récupérer l'adresse e-mail
    user_email = ""
    if access_token:
        try:
            userinfo_resp = requests.get(
                "https://www.googleapis.com/oauth2/v3/userinfo",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=10
            )
            if userinfo_resp.status_code == 200:
                user_email = userinfo_resp.json().get("email", "")
        except Exception:
            pass

    # Sauvegarder dans SecretStore
    SecretStore.set_secret("GMAIL_CLIENT_ID", client_id)
    SecretStore.set_secret("GMAIL_CLIENT_SECRET", client_secret)
    SecretStore.set_secret("GMAIL_REFRESH_TOKEN", refresh_token)
    if user_email:
        SecretStore.set_secret("GMAIL_USER_EMAIL", user_email)

    # Déclencher la synchronisation immédiate de la BDD
    sync_ok = True
    sync_err = ""
    if CloudDatabase.is_enabled():
        try:
            CloudDatabase.sync()
        except Exception as se:
            sync_ok = False
            sync_err = str(se)

    email_display = f"Compte connecté : <b>{user_email}</b>" if user_email else "Compte Google connecté"
    sync_display = "✅ Base de données synchronisée avec succès." if sync_ok else f"⚠️ Connexion rétablie, mais synchro en attente : {sync_err}"

    return _render_page(
        "Connexion Réussie",
        f"""<h2>🎉 Connexion Google Réussie !</h2>
        <div class="badge badge-success">Accès BDD & Gmail rétabli</div>
        <p>{email_display}</p>
        <p>{sync_display}</p>
        <details style="margin:16px 0; text-align:left; font-size:12px; background:#F8FAFC; border:1px solid #CBD5E1; border-radius:8px; padding:10px 12px;">
            <summary style="cursor:pointer; font-weight:600; color:#334155;">🔑 Nouveau Refresh Token (pour Cloud Run)</summary>
            <p style="margin:6px 0 4px; color:#64748B; font-size:11.5px;">Le jeton a été synchronisé. Vous pouvez également copier cette valeur dans Cloud Run (GMAIL_REFRESH_TOKEN) :</p>
            <input type="text" readonly value="{refresh_token}" style="width:100%; box-sizing:border-box; padding:6px 8px; font-family:monospace; font-size:11px; background:#FFF; border:1px solid #CBD5E1; border-radius:4px;" onclick="this.select();">
        </details>
        <p style="font-size:13px; color:#64748B;">Redirection automatique vers le bureau dans quelques secondes…</p>
        <p><a href="{return_to}" class="btn">Retourner au bureau immédiatement</a></p>""",
        return_url=return_to,
        auto_redirect=True
    )


@app.post("/api/auth/google/test")
def test_google_auth():
    """Diagnostique en direct la connexion Google OAuth2, l'accès BDD et l'API Gmail."""
    import requests
    from infrastructure.google_drive_client import GoogleDriveClient
    from infrastructure.cloud_database import CloudDatabase
    
    results = {
        "oauth_token": {"ok": False, "message": ""},
        "database": {"ok": False, "message": ""},
        "gmail": {"ok": False, "message": ""},
    }
    
    # 1. Test Obtention Access Token
    try:
        tok = GoogleDriveClient.get_access_token()
        if tok:
            results["oauth_token"]["ok"] = True
            results["oauth_token"]["message"] = "Jeton d'accès obtenu avec succès auprès de Google OAuth2."
        else:
            results["oauth_token"]["message"] = "Le jeton d'accès retourné est vide."
    except Exception as e:
        results["oauth_token"]["message"] = f"Échec de renouvellement OAuth2 : {e}"
        results["database"]["message"] = "Test BDD ignoré en raison de l'échec OAuth2."
        results["gmail"]["message"] = "Test Gmail ignoré en raison de l'échec OAuth2."
        return {"status": "error", "all_ok": False, "results": results}

    # 2. Test Accès BDD (Firestore ou Drive)
    backend = (SecretStore.get_secret("MEMBER_BACKEND") or "firestore").strip().lower()
    try:
        if backend == "drive":
            db_id = SecretStore.get_secret("GOOGLE_DRIVE_DB_ID")
            if not db_id:
                results["database"]["ok"] = False
                results["database"]["message"] = "GOOGLE_DRIVE_DB_ID non configuré."
            else:
                name = GoogleDriveClient.get_file_name(db_id)
                results["database"]["ok"] = True
                results["database"]["message"] = f"Fichier Drive '{name}' accessible."
        else:
            if CloudDatabase.is_enabled():
                CloudDatabase.ensure_fresh(max_age=10)
                results["database"]["ok"] = True
                results["database"]["message"] = "Base Firestore synchronisée et opérationnelle."
            else:
                results["database"]["ok"] = True
                results["database"]["message"] = "Base locale opérationnelle."
    except Exception as e:
        results["database"]["ok"] = False
        results["database"]["message"] = f"Erreur d'accès à la BDD : {e}"

    # 3. Test API Gmail
    gmail_user = SecretStore.get_secret("GMAIL_USER_EMAIL")
    try:
        url = "https://gmail.googleapis.com/gmail/v1/users/me/profile"
        resp = requests.get(url, headers={"Authorization": f"Bearer {tok}"}, timeout=10)
        if resp.status_code == 200:
            p_data = resp.json()
            email_address = p_data.get("emailAddress", gmail_user or "ok")
            results["gmail"]["ok"] = True
            results["gmail"]["message"] = f"API Gmail active pour l'adresse : {email_address}."
        else:
            results["gmail"]["ok"] = False
            results["gmail"]["message"] = f"API Gmail HTTP {resp.status_code} : {resp.text}"
    except Exception as e:
        results["gmail"]["ok"] = False
        results["gmail"]["message"] = f"Erreur lors du test Gmail : {e}"

    all_ok = all(r["ok"] for r in results.values())
    return {
        "status": "success" if all_ok else "warning",
        "all_ok": all_ok,
        "results": results
    }


@app.post("/api/auth/google/update-token")
def update_google_token(data: Dict[str, Any] = Body(...)):
    """Permet à un administrateur de renseigner ou forcer un refresh token manuellement."""
    import requests
    from infrastructure.google_drive_client import GoogleDriveClient
    from infrastructure.cloud_database import CloudDatabase
    
    refresh_token = str(data.get("refresh_token") or "").strip()
    client_id = str(data.get("client_id") or "").strip()
    client_secret = str(data.get("client_secret") or "").strip()
    user_email = str(data.get("user_email") or "").strip()

    if not refresh_token:
        return JSONResponse(status_code=400, content={"status": "error", "message": "Le refresh token est requis."})

    cid_exist, sec_exist = GoogleDriveClient.get_client_credentials()
    final_cid = client_id or cid_exist
    final_sec = client_secret or sec_exist

    if not final_cid or not final_sec:
        return JSONResponse(status_code=400, content={"status": "error", "message": "Client ID ou Client Secret manquant."})

    test_data = {
        "client_id": final_cid,
        "client_secret": final_sec,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token"
    }
    try:
        r = requests.post("https://oauth2.googleapis.com/token", data=test_data, timeout=15)
        if r.status_code != 200:
            return JSONResponse(
                status_code=400,
                content={"status": "error", "message": f"Google a rejeté ce jeton : {r.text}"}
            )
        access_tok = r.json().get("access_token")
    except Exception as e:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": f"Impossible de joindre Google : {e}"}
        )

    if not user_email and access_tok:
        try:
            u_resp = requests.get(
                "https://www.googleapis.com/oauth2/v3/userinfo",
                headers={"Authorization": f"Bearer {access_tok}"},
                timeout=10
            )
            if u_resp.status_code == 200:
                user_email = u_resp.json().get("email", "")
        except Exception:
            pass

    SecretStore.set_secret("GMAIL_CLIENT_ID", final_cid)
    SecretStore.set_secret("GMAIL_CLIENT_SECRET", final_sec)
    SecretStore.set_secret("GMAIL_REFRESH_TOKEN", refresh_token)
    if user_email:
        SecretStore.set_secret("GMAIL_USER_EMAIL", user_email)

    if CloudDatabase.is_enabled():
        try:
            CloudDatabase.sync()
        except Exception:
            pass

    return {
        "status": "success",
        "message": "Jeton Google mis à jour et validé avec succès.",
        "user_email": user_email
    }


@app.get("/api/cloud-db/status")
def get_cloud_db_status_api():
    """Retourne l'état détaillé du cache local SQLite et de sa synchronisation Firestore."""
    try:
        from infrastructure.cloud_database import CloudDatabase
        from infrastructure.sqlite_repository import SqliteRepository
        enabled = CloudDatabase.is_enabled()
        st = CloudDatabase.status() if enabled else {}
        db_path = SqliteRepository.get_db_path()
        db_exists = os.path.exists(db_path)
        db_size_kb = round(os.path.getsize(db_path) / 1024, 1) if db_exists else 0

        member_count = 0
        if db_exists:
            try:
                conn = SqliteRepository.get_connection()
                row = conn.execute("SELECT COUNT(*) FROM users").fetchone()
                member_count = row[0] if row else 0
                conn.close()
            except Exception:
                pass

        return {
            "status": "success",
            "enabled": enabled,
            "db_exists": db_exists,
            "db_filename": os.path.basename(db_path),
            "db_size_kb": db_size_kb,
            "member_count": member_count,
            "pending": st.get("pending", 0),
            "last_error": st.get("last_error", ""),
            "last_sync": st.get("last_sync"),
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": internal_error(e, "get_cloud_db_status_api")})


@app.post("/api/cloud-db/sync")
def sync_cloud_db_api(force: bool = Query(False)):
    """Force la synchronisation bilatérale entre Firestore et la base SQLite locale."""
    try:
        from infrastructure.cloud_database import CloudDatabase
        if not CloudDatabase.is_enabled():
            return {"status": "skipped", "message": "Mode Firestore non activé (MEMBER_BACKEND != firestore)."}

        result = CloudDatabase.sync(full=force, force_pull_all=force)
        errors = result.get("errors") if isinstance(result, dict) else []
        if errors:
            return JSONResponse(status_code=500, content={"status": "error", "message": f"Erreur de synchronisation : {'; '.join(errors)}", "result": result})

        return {
            "status": "success",
            "message": "Base de données SQLite synchronisée avec succès avec Firestore.",
            "result": result
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": internal_error(e, "sync_cloud_db_api")})


if __name__ == "__main__":
    import uvicorn
    # Support de la variable d'environnement PORT (Cloud Run injecte PORT=8080)
    port = int(os.environ.get("PORT", 8000))
    host = os.environ.get("HOST", "0.0.0.0" if os.environ.get("PORT") else "127.0.0.1")
    uvicorn.run("server:app", host=host, port=port, reload=(port == 8000))
