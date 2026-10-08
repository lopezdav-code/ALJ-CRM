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

from fastapi import FastAPI, Body, BackgroundTasks, Query
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

# Importer les fonctions de notre script existant
from helloasso_api import get_campaigns, get_items
from infrastructure.sqlite_repository import SqliteRepository

from dotenv import load_dotenv
load_dotenv()

from domain.constants import get_active_season, APP_VERSION
from infrastructure.secret_store import SecretStore


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

# Contrôle d'accès (jeton Firebase + rôles de firestore.rules) : actif sur Cloud Run
# et dans l'image Docker (ALJ_API_AUTH=required), désactivé pour le serveur local
# de l'application de bureau. Enregistré AVANT le CORS pour que les pré-vols
# OPTIONS soient traités par le middleware CORS (le plus externe).
from infrastructure.cloud_database import CloudDatabase
from starlette.concurrency import run_in_threadpool


async def cloud_db_middleware(request, call_next):
    """Base principale dans Firestore : le cache SQLite du serveur est mis à jour
    avant les routes de données, et les écritures sont envoyées juste après.
    Enregistré avant le contrôle d'accès : il ne s'exécute qu'après lui."""
    path = request.url.path
    relevant = path.startswith("/api/") or path in ("/map", "/pivot")
    if relevant and os.environ.get("K_SERVICE") and CloudDatabase.is_enabled():
        await run_in_threadpool(CloudDatabase.ensure_fresh, 30)
    response = await call_next(request)
    if relevant and request.method not in ("GET", "HEAD", "OPTIONS") and CloudDatabase.is_enabled():
        await run_in_threadpool(CloudDatabase.after_write)
    return response


app.middleware("http")(cloud_db_middleware)

from infrastructure.api_auth import auth_middleware
app.middleware("http")(auth_middleware)

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

# Autoriser le frontend local à communiquer avec l'API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
    map_points_json = json.dumps(map_points, ensure_ascii=False)

    html_content = """<!DOCTYPE html>
<html>
<head>
    <title>ALJ Escalade - Cartographie des Adhérents</title>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    
    <!-- CDN Leaflet -->
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=" crossorigin="" />
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" crossorigin=""></script>
    
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
            label.innerHTML = `<input type="checkbox" class="group-checkbox" value="${group}" checked onchange="applyFilter(event)"> ${group}`;
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

        // Ajouter les tuiles OpenStreetMap
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            maxZoom: 19,
            attribution: '© OpenStreetMap contributors'
        }).addTo(map);

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
                        <div class="popup-address">📍 ${point.address}</div>
                        <ul class="popup-members-list">
                            ${membersToDisplay.map(name => `<li>${name}</li>`).join('')}
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
def get_pivot_table(season: str = "Toutes les saisons"):
    """Renvoie la page du Tableau Croisé Dynamique interactif via PivotTable.js."""
    try:
        from infrastructure.sqlite_repository import SqliteRepository
        raw_data = SqliteRepository.load_direct_data(season)
        
        # Préparer un tableau de données plat et épuré pour le TCD
        pivot_records = []
        for row in raw_data:
            # 1. Normaliser et fusionner les statuts HelloAsso (Processed, Validated -> Validé)
            status_raw = str(row.get("status", "Validé")).strip()
            if status_raw.lower() in ("processed", "validated", "validé"):
                status_clean = "Validé"
            else:
                status_clean = status_raw.title()
                
            # 2. Normaliser les noms de villes pour fusionner "Saint-Maurice..." et "Saint Maurice..."
            from domain.utils import clean_city_name
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
            
            pivot_records.append({
                "Nom": (row.get("last_name") or "").strip().upper(),
                "Pr\u00e9nom": (row.get("first_name") or "").strip().title(),
                "Sexe": (row.get("gender") or "Inconnu").strip().title() or "Inconnu",
                "Ville": city_clean,
                "Groupe / Tarif": str(row.get("tarif_name") or "").strip() or "Aucun",
                "Statut": status_clean,
                "Saison": season_name,
                "Type d'Adhésion": inscription_type,
                "Date d'Inscription": date_iso or "Inconnue",
                "Mois d'Inscription": month_iso or "Inconnue",
            })
            
        pivot_data_json = json.dumps(pivot_records, ensure_ascii=False)
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
        <p>Glissez et déposez les étiquettes ci-dessous pour filtrer et croiser à volonté les adhérents (par Jour de cours, Ville, Sexe, Statut, Date d'inscription, etc.)</p>
    </div>

    <div class="container">
        <div id="output"></div>
    </div>

    <script type="text/javascript">
        $(function(){
            const pivotData = {PIVOT_DATA_JSON};
            
            $("#output").pivotUI(pivotData, {
                rows: ["Groupe / Tarif"],
                cols: ["Statut"],
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
        return SqliteRepository.load_planning_data()
    except Exception as e:
        return {"error": str(e)}

# Annuaire mobile (page web en lecture seule : télécharge database.db depuis
# Google Drive après connexion Google, cache navigateur, filtres par créneaux).
# Nécessaire pour l'authentification Google OAuth (origine http://localhost:8000).
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
_web_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")
if os.path.isdir(_web_dir):
    app.mount("/annuaire", StaticFiles(directory=_web_dir, html=True), name="annuaire")

_competitions_page_path = os.path.join(_web_dir, "competitions.html")

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
        "annuaire_url": "/annuaire"
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
        return {"error": str(e)}


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
        return {"status": "error", "message": str(e)}


@app.get("/api/email-templates")
def get_email_templates():
    """Retourne la liste des modèles d'e-mails configurés."""
    try:
        return {"status": "success", "templates": EmailDispatchService.list_templates()}
    except Exception as e:
        return {"status": "error", "message": str(e)}


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
        return {"status": "error", "message": str(e)}


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
def send_email_api(data: Dict[str, Any] = Body(...)):
    """Déclenche l'envoi d'e-mails sécurisé via Gmail API ou SMTP avec injection de variables."""
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
        return {"status": "error", "message": str(e)}


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
        return {"status": "error", "message": str(e)}


if __name__ == "__main__":
    import uvicorn
    # Support de la variable d'environnement PORT (Cloud Run injecte PORT=8080)
    port = int(os.environ.get("PORT", 8000))
    host = os.environ.get("HOST", "0.0.0.0" if os.environ.get("PORT") else "127.0.0.1")
    uvicorn.run("server:app", host=host, port=port, reload=(port == 8000))
