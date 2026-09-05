import os
import json
import time
from fastapi import FastAPI, Body, BackgroundTasks
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Dict, Any

# Importer les fonctions de notre script existant
from helloasso_api import get_campaigns, get_items
from infrastructure.sqlite_repository import SqliteRepository

from dotenv import load_dotenv
load_dotenv()

from domain.constants import get_active_season
env_slug = os.getenv("CAMPAIGN_SLUG")
TARGET_SLUG = env_slug.strip() if env_slug and env_slug.strip() else f"adhesion-escalade-{get_active_season()}-amicale-laique-escalade"

app = FastAPI(title="Admin Escalade API")

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
    target_camp = next((c for c in campaigns if c.get('formSlug') == TARGET_SLUG), None)
    
    if not target_camp:
        return {"error": "Campagne introuvable"}
        
    c_type = target_camp.get('formType')
    items = get_items(c_type, TARGET_SLUG)
    
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

@app.post("/api/planning")
def update_planning(planning_data: List[Dict[str, Any]] = Body(...)):
    """Met à jour le planning dans la BDD SQLite."""
    try:
        SqliteRepository.save_planning_data(planning_data)
        return {"status": "success", "message": "Planning mis à jour"}
    except Exception as e:
        return {"error": str(e)}

if __name__ == "__main__":
    import uvicorn
    # Le serveur tourne sur le port 8000
    uvicorn.run("server:app", host="127.0.0.1", port=8000, reload=True)
