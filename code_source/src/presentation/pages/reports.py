import os
import socket
import sqlite3
import webbrowser
import threading
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, 
    QPushButton, QMessageBox, QGridLayout, QTableWidget, QTableWidgetItem,
    QHeaderView
)
from PySide6.QtCore import Qt, QThread, Signal

from infrastructure.secret_store import SecretStore

class GeocodeWorker(QThread):
    """
    Worker asynchrone pour géocoder de manière autonome et sécurisée les adresses en attente (Nouveau !).
    """
    progress = Signal(str, int)  # (message, pourcentage)
    finished = Signal(bool, int, int) # (succès, réussis, échecs)

    def __init__(self, addresses: list, parent=None):
        super().__init__(parent)
        self.addresses = addresses

    def run(self):
        try:
            total = len(self.addresses)
            if total == 0:
                self.finished.emit(True, 0, 0)
                return
                
            from geopy.geocoders import Nominatim
            from infrastructure.sqlite_repository import SqliteRepository
            import time
            
            geolocator = Nominatim(user_agent="alj_escalade_manager_manual_geocode")
            success_count = 0
            fail_count = 0
            
            print("\n================================================================================")
            print(f"🌍 [GEOCODING] Début du géocodage manuel de {total} adresses...")
            print("================================================================================")
            
            for idx, addr in enumerate(self.addresses):
                percent = int((idx / total) * 100)
                self.progress.emit(f"🌍 Géocodage ({idx+1}/{total}) : {addr}...", percent)
                print(f"🌍 [GEOCODING] ({idx+1}/{total}) Recherche de l'adresse : {addr}")
                
                try:
                    location = geolocator.geocode(addr, timeout=10)
                    if location:
                        lat, lon = location.latitude, location.longitude
                        SqliteRepository.save_geocode(addr, lat, lon)
                        success_count += 1
                        print(f"✅ [GEOCODING] Résolution : {lat}, {lon}")
                    else:
                        SqliteRepository.save_geocode(addr, None, None)
                        fail_count += 1
                        print("⚠️ [GEOCODING] Adresse introuvable ou non localisée.")
                except Exception as err:
                    print(f"❌ [GEOCODING] Erreur technique pour '{addr}' : {err}")
                    fail_count += 1
                    
                # Respect du délai d'une seconde pour l'API Nominatim
                time.sleep(1.0)
                
            print("================================================================================\n")
            self.finished.emit(True, success_count, fail_count)
        except Exception as e:
            print(f"❌ [GEOCODING] Erreur critique du worker : {e}")
            self.finished.emit(False, 0, 0)

class ReportsPage(QWidget):
    """
    Page 'Outils' d'Administration & Analyses.
    Permet d'ouvrir la carte interactive Leaflet, le TCD interactif Drag-and-Drop,
    de tester la connexion réseau, de relancer le serveur d'API FastAPI local,
    et d'auditer/corriger les adresses postales non reconnues à l'aide de l'API de l'État (BAN).
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()

    def init_ui(self):
        # Utiliser un layout vertical principal avec défilement si nécessaire
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 25, 30, 25)
        layout.setSpacing(15)

        # 1. EN-TÊTE PRINCIPAL DE LA PAGE
        header_frame = QFrame()
        header_frame.setStyleSheet("""
            QFrame {
                background-color: #1E3A8A;
                border-radius: 8px;
                padding: 20px;
            }
        """)
        header_layout = QVBoxLayout(header_frame)
        header_layout.setSpacing(5)

        title = QLabel("🔧 Boîte à Outils d'Administration & Analyses")
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: #FFFFFF;")
        header_layout.addWidget(title)

        subtitle = QLabel("Gérez le serveur local de l'application, accédez aux analyses cartographiques et supervisez la cohérence des adresses.")
        subtitle.setStyleSheet("font-size: 12px; color: #BFDBFE;")
        header_layout.addWidget(subtitle)

        layout.addWidget(header_frame)

        # 2. GRILLE D'OUTILS ET DE MODULES (2 Colonnes)
        grid = QGridLayout()
        grid.setSpacing(20)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        # --- OUTIL 1 : CARTOGRAPHIE INTERACTIVE ---
        card_map = QFrame()
        card_map.setStyleSheet("QFrame { background-color: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 8px; padding: 20px; }")
        lay_map = QVBoxLayout(card_map)
        lay_map.setSpacing(12)

        lbl_map_title = QLabel("📍 Cartographie Interactive")
        lbl_map_title.setStyleSheet("font-size: 14px; font-weight: bold; color: #1E293B; border-bottom: 1px solid #F1F5F9; padding-bottom: 6px;")
        lay_map.addWidget(lbl_map_title)

        lbl_map_desc = QLabel(
            "Visualisez la répartition géographique de vos adhérents sur une carte de France interactive. "
            "Permet d'analyser la densité d'élèves par code postal et par commune pour adapter vos créneaux."
        )
        lbl_map_desc.setWordWrap(True)
        lbl_map_desc.setStyleSheet("font-size: 12px; color: #475569; line-height: 1.4;")
        lay_map.addWidget(lbl_map_desc)
        lay_map.addStretch()

        btn_open_map = QPushButton("🗺️ Ouvrir la carte interactive")
        btn_open_map.setCursor(Qt.PointingHandCursor)
        btn_open_map.setStyleSheet("""
            QPushButton {
                background-color: #0EA5E9;
                color: #FFFFFF;
                border: none;
                border-radius: 6px;
                padding: 10px 15px;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #0284C7;
            }
        """)
        btn_open_map.clicked.connect(self.open_interactive_map)
        lay_map.addWidget(btn_open_map)
        grid.addWidget(card_map, 0, 0)

        # --- OUTIL 2 : TABLEAU CROISÉ DYNAMIQUE ---
        card_tcd = QFrame()
        card_tcd.setStyleSheet("QFrame { background-color: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 8px; padding: 20px; }")
        lay_tcd = QVBoxLayout(card_tcd)
        lay_tcd.setSpacing(12)

        lbl_tcd_title = QLabel("📊 Tableau Croisé Dynamique (TCD)")
        lbl_tcd_title.setStyleSheet("font-size: 14px; font-weight: bold; color: #1E293B; border-bottom: 1px solid #F1F5F9; padding-bottom: 6px;")
        lay_tcd.addWidget(lbl_tcd_title)

        lbl_tcd_desc = QLabel(
            "Explorez, filtrez et croisez vos dossiers d'inscriptions à l'aide d'une grille de reporting dynamique. "
            "Glissez-déposez simplement les étiquettes (Cours, Sexe, Villes, Statut) pour construire vos analyses en temps réel."
        )
        lbl_tcd_desc.setWordWrap(True)
        lbl_tcd_desc.setStyleSheet("font-size: 12px; color: #475569; line-height: 1.4;")
        lay_tcd.addWidget(lbl_tcd_desc)
        lay_tcd.addStretch()

        btn_open_tcd = QPushButton("📊 Ouvrir le TCD Interactif")
        btn_open_tcd.setCursor(Qt.PointingHandCursor)
        btn_open_tcd.setStyleSheet("""
            QPushButton {
                background-color: #2563EB;
                color: #FFFFFF;
                border: none;
                border-radius: 6px;
                padding: 10px 15px;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #1D4ED8;
            }
        """)
        btn_open_tcd.clicked.connect(self.open_interactive_pivot)
        lay_tcd.addWidget(btn_open_tcd)
        grid.addWidget(card_tcd, 0, 1)

        # --- OUTIL 3 : CONTRÔLE & API SERVEUR LOCAL ---
        card_srv = QFrame()
        card_srv.setStyleSheet("QFrame { background-color: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 8px; padding: 20px; }")
        lay_srv = QVBoxLayout(card_srv)
        lay_srv.setSpacing(12)

        lbl_srv_title = QLabel("⚙️ Supervision du Serveur API Local")
        lbl_srv_title.setStyleSheet("font-size: 14px; font-weight: bold; color: #1E293B; border-bottom: 1px solid #F1F5F9; padding-bottom: 6px;")
        lay_srv.addWidget(lbl_srv_title)

        lbl_srv_desc = QLabel(
            "Supervisez et pilotez le serveur web local d'arrière-plan (FastAPI / Uvicorn). "
            "Il traite en temps réel les calculs cartographiques et structure l'analyse dynamique des effectifs."
        )
        lbl_srv_desc.setWordWrap(True)
        lbl_srv_desc.setStyleSheet("font-size: 12px; color: #475569; line-height: 1.4;")
        lay_srv.addWidget(lbl_srv_desc)
        lay_srv.addStretch()

        # Ligne de boutons d'administration
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        btn_test_srv = QPushButton("⚡ Tester la Connexion")
        btn_test_srv.setCursor(Qt.PointingHandCursor)
        btn_test_srv.setStyleSheet("""
            QPushButton {
                background-color: #10B981;
                color: #FFFFFF;
                border: none;
                border-radius: 6px;
                padding: 10px 15px;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #059669;
            }
        """)
        btn_test_srv.clicked.connect(self.test_server_connection)
        btn_layout.addWidget(btn_test_srv)

        btn_restart_srv = QPushButton("🔄 Relancer le Serveur")
        btn_restart_srv.setCursor(Qt.PointingHandCursor)
        btn_restart_srv.setStyleSheet("""
            QPushButton {
                background-color: #64748B;
                color: #FFFFFF;
                border: none;
                border-radius: 6px;
                padding: 10px 15px;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #475569;
            }
        """)
        btn_restart_srv.clicked.connect(self.restart_map_server)
        btn_layout.addWidget(btn_restart_srv)

        lay_srv.addLayout(btn_layout)
        grid.addWidget(card_srv, 1, 0, 1, 2) # Occupe toute la largeur sous la carte et le TCD

        # --- OUTIL 4 : AUDIT DES ADRESSES POSTALES NON RECONNUES ---
        card_unrec = QFrame()
        card_unrec.setStyleSheet("QFrame { background-color: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 8px; padding: 20px; }")
        lay_unrec = QVBoxLayout(card_unrec)
        lay_unrec.setSpacing(10)

        lbl_unrec_title = QLabel("⚠️ Adresses Non Reconnues ou Invalides (Audit Cartographie)")
        lbl_unrec_title.setStyleSheet("font-size: 14px; font-weight: bold; color: #DC2626; border-bottom: 1px solid #FEE2E2; padding-bottom: 6px;")
        lay_unrec.addWidget(lbl_unrec_title)

        lbl_unrec_desc = QLabel(
            "Voici la liste des adhérents dont l'adresse postale comporte une anomalie ou n'a pas pu être localisée. "
            "Vous pouvez utiliser le bouton '🪄 Corriger' pour appeler l'API de l'État (BAN) et corriger automatiquement l'adresse après votre validation."
        )
        lbl_unrec_desc.setWordWrap(True)
        lbl_unrec_desc.setStyleSheet("font-size: 11px; color: #475569; line-height: 1.4;")
        lay_unrec.addWidget(lbl_unrec_desc)

        # Ligne d'action pour le géocodage manuel (Nouveau !)
        geocode_action_layout = QHBoxLayout()
        geocode_action_layout.setSpacing(15)
        
        self.btn_geocode = QPushButton("🌍 Récupérer / Géocoder les adresses en attente")
        self.btn_geocode.setCursor(Qt.PointingHandCursor)
        self.btn_geocode.setStyleSheet("""
            QPushButton {
                background-color: #F0FDF4;
                border: 1px solid #BBF7D0;
                border-radius: 6px;
                padding: 6px 14px;
                font-size: 11px;
                font-weight: bold;
                color: #16A34A;
            }
            QPushButton:hover {
                background-color: #DCFCE7;
                border-color: #86EFAC;
            }
            QPushButton:disabled {
                background-color: #F1F5F9;
                border-color: #E2E8F0;
                color: #94A3B8;
            }
        """)
        self.btn_geocode.clicked.connect(self.start_manual_geocoding)
        geocode_action_layout.addWidget(self.btn_geocode)
        
        self.geocode_status_lbl = QLabel("")
        self.geocode_status_lbl.setStyleSheet("color: #475569; font-size: 11px; font-weight: 500;")
        geocode_action_layout.addWidget(self.geocode_status_lbl)
        
        geocode_action_layout.addStretch()
        lay_unrec.addLayout(geocode_action_layout)

        self.unrec_table = QTableWidget()
        self.unrec_table.setMinimumHeight(220)
        self.unrec_table.setMaximumHeight(350)
        self.unrec_table.setStyleSheet("""
            QTableWidget {
                border: 1px solid #E2E8F0;
                gridline-color: #E2E8F0;
                font-size: 11px;
                background-color: #FFFFFF;
            }
            QHeaderView::section {
                background-color: #FEF2F2;
                color: #991B1B;
                font-weight: bold;
                border: 1px solid #FEE2E2;
                padding: 6px;
                font-size: 10px;
            }
        """)
        lay_unrec.addWidget(self.unrec_table)
        grid.addWidget(card_unrec, 2, 0, 1, 2) # Occupe toute la largeur sous la supervision

        layout.addLayout(grid)

        # 3. BANNIÈRE D'INFORMATION DE SYNCHRONISATION
        self.sync_banner = QFrame()
        self.sync_banner.setStyleSheet("""
            QFrame {
                background-color: #F8FAFC;
                border: 1px solid #E2E8F0;
                border-radius: 6px;
                padding: 10px 15px;
                margin-top: 10px;
            }
        """)
        banner_layout = QHBoxLayout(self.sync_banner)
        self.drive_sync_lbl = QLabel("🌐 Dernière mise à jour Drive : Inconnue")
        self.drive_sync_lbl.setStyleSheet("color: #64748B; font-size: 11px; font-weight: 500;")
        banner_layout.addWidget(self.drive_sync_lbl)

        banner_layout.addStretch()

        self.hello_sync_lbl = QLabel("🔄 Dernière synchro HelloAsso : Inconnue")
        self.hello_sync_lbl.setStyleSheet("color: #64748B; font-size: 11px; font-weight: 500;")
        banner_layout.addWidget(self.hello_sync_lbl)

        layout.addWidget(self.sync_banner)
        
        # Mettre à jour les labels de date et peupler le tableau d'audit au démarrage
        self.update_sync_dates_on_banner()
        self.populate_unrecognized_table()

    def get_unrecognized_addresses(self):
        """Récupère la liste des adhérents dont l'adresse est invalide ou non résolue par la carte."""
        unresolved_list = []
        try:
            from infrastructure.sqlite_repository import SqliteRepository
            raw_data = SqliteRepository.load_direct_data()
            geocache = SqliteRepository.get_geocache()
            
            for row in raw_data:
                status = row.get("status", "Validé")
                if "annul" in str(status).lower():
                    continue
                    
                addr = row.get("champ_Adresse : numéro et nom de rue") or ""
                city = row.get("champ_Ville") or ""
                zip_code = row.get("champ_Code postal") or ""
                
                city_upper = str(city).strip().upper() if city else ""
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
                    
                # Vérifier si elle est résolue
                is_resolved = False
                in_cache = False
                if full_address in geocache:
                    in_cache = True
                    coords = geocache[full_address]
                    if coords[0] is not None and coords[1] is not None:
                        is_resolved = True
                        
                if not is_resolved:
                    unresolved_list.append({
                        "name": f"{row.get('user_firstName', '').strip().title()} {row.get('user_lastName', '').strip().upper()}",
                        "tarif": row.get("tarif_name") or "".strip() or "Aucun",
                        "address": f"{addr_clean}, {zip_clean} {city_upper}" if addr_clean else city_upper,
                        "status": "⚠️ Adresse non reconnue" if in_cache else "⏳ En attente de géocodage"
                    })
        except Exception as ex:
            print(f"⚠️ Erreur lors du calcul des adresses non reconnues : {ex}")
            
        return unresolved_list

    def populate_unrecognized_table(self):
        """Peuple le tableau des adresses non reconnues."""
        unresolved = self.get_unrecognized_addresses()
        self.unrec_table.clear()
        
        # 5 colonnes : Nom, Cours, Adresse, Statut, Action !
        self.unrec_table.setColumnCount(5)
        self.unrec_table.setHorizontalHeaderLabels(["Nom de l'Adhérent", "Cours / Tarif", "Adresse Saisie", "Statut Audit", "Action"])
        
        # Style des en-têtes
        self.unrec_table.horizontalHeader().setFixedHeight(28)
        self.unrec_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.unrec_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.unrec_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch) # Stretch pour l'adresse !
        self.unrec_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.unrec_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents) # Bouton Action
        self.unrec_table.horizontalHeader().setStretchLastSection(False)
        self.unrec_table.verticalHeader().setVisible(False)
        
        self.unrec_table.setRowCount(len(unresolved))
        
        from PySide6.QtGui import QFont, QColor, QBrush
        font_normal = QFont()
        font_bold = QFont()
        font_bold.setBold(True)
        
        red_text_brush = QBrush(QColor("#991B1B"))
        orange_text_brush = QBrush(QColor("#D97706"))
        gray_brush = QBrush(QColor("#334155"))
        bg_zebra = QBrush(QColor("#FFF5F5"))
        bg_white = QBrush(QColor("#FFFFFF"))
        
        for idx, item in enumerate(unresolved):
            is_zebra = (idx % 2 == 0)
            row_bg = bg_zebra if is_zebra else bg_white
            
            c_name = QTableWidgetItem(item["name"])
            c_name.setFont(font_bold)
            c_name.setForeground(gray_brush)
            c_name.setBackground(row_bg)
            
            c_tarif = QTableWidgetItem(item["tarif"])
            c_tarif.setFont(font_normal)
            c_tarif.setForeground(gray_brush)
            c_tarif.setBackground(row_bg)
            
            c_addr = QTableWidgetItem(item["address"])
            c_addr.setFont(font_normal)
            c_addr.setForeground(gray_brush)
            c_addr.setBackground(row_bg)
            
            c_status = QTableWidgetItem(item["status"])
            c_status.setFont(font_bold)
            if "attente" in item["status"].lower():
                c_status.setForeground(orange_text_brush)
            else:
                c_status.setForeground(red_text_brush)
            c_status.setBackground(row_bg)
            c_status.setTextAlignment(Qt.AlignCenter)
            
            # Bouton magique d'auto-correction via l'API de l'État (BAN)
            btn_correct = QPushButton("🪄 Corriger")
            btn_correct.setCursor(Qt.PointingHandCursor)
            btn_correct.setStyleSheet("""
                QPushButton {
                    background-color: #10B981;
                    color: #FFFFFF;
                    border: none;
                    border-radius: 4px;
                    padding: 4px 10px;
                    font-size: 10px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #059669;
                }
            """)
            btn_correct.clicked.connect(lambda checked=False, r_idx=idx: self.suggest_address_correction(r_idx))
            
            self.unrec_table.setItem(idx, 0, c_name)
            self.unrec_table.setItem(idx, 1, c_tarif)
            self.unrec_table.setItem(idx, 2, c_addr)
            self.unrec_table.setItem(idx, 3, c_status)
            self.unrec_table.setCellWidget(idx, 4, btn_correct)

    def suggest_address_correction(self, idx_row):
        """Appelle le service d'API public de la BAN pour suggérer et corriger l'adresse d'un adhérent."""
        try:
            unresolved = self.get_unrecognized_addresses()
            if idx_row >= len(unresolved):
                return
                
            item = unresolved[idx_row]
            orig_name = item["name"]
            orig_addr = item["address"]
            
            # Appeler l'API de la Base Adresse Nationale (BAN)
            import requests
            url = f"https://api-adresse.data.gouv.fr/search/?q={requests.utils.quote(orig_addr)}&limit=1"
            response = requests.get(url, timeout=3.0)
            
            if response.status_code != 200:
                QMessageBox.warning(self, "Erreur Service", "Impossible de joindre le service de normalisation Adresse.Data.Gouv.fr.")
                return
                
            data = response.json()
            features = data.get("features", [])
            if not features:
                QMessageBox.warning(self, "Aucune suggestion", f"Le service d'État n'a trouvé aucune suggestion pour l'adresse :\n'{orig_addr}'")
                return
                
            feat = features[0]
            props = feat.get("properties", {})
            geom = feat.get("geometry", {})
            coords = geom.get("coordinates", []) # [lon, lat]
            
            suggested_label = props.get("label") or ""
            s_name = props.get("name") or ""
            s_postcode = props.get("postcode") or ""
            s_city = props.get("city") or ""
            
            if not s_name or not s_city:
                QMessageBox.warning(self, "Suggestion incomplète", "La suggestion retournée par le service est incomplète.")
                return
                
            # Afficher la boîte de dialogue récapitulative pour validation de l'utilisateur
            box = QMessageBox(self)
            box.setWindowTitle("Correction d'Adresse Officielle")
            box.setTextFormat(Qt.RichText)
            
            html_msg = (
                f"<h3><b>🪄 Correction Suggérée par la BAN (Service Public)</b></h3>"
                f"<p>Voulez-vous corriger et écraser l'adresse de l'adhérent <b>{orig_name}</b> ?</p>"
                f"<table border='0' cellpadding='5' style='font-size: 11px; margin-top: 10px; border-collapse: collapse;'>"
                f"  <tr><td>❌ <b>Adresse d'Origine :</b></td><td><font color='#DC2626'>{orig_addr}</font></td></tr>"
                f"  <tr><td>✅ <b>Proposition Officielle :</b></td><td><font color='#16A34A'><b>{suggested_label}</b></font></td></tr>"
                f"</table>"
                f"<p><i>Après validation, l'adresse corrigée sera enregistrée en base de données et instantanément géocodée sur votre carte !</i></p>"
            )
            box.setText(html_msg)
            
            yes_btn = box.addButton("💾 Enregistrer la correction", QMessageBox.ButtonRole.YesRole)
            no_btn = box.addButton("Annuler", QMessageBox.ButtonRole.NoRole)
            box.exec()
            
            if box.clickedButton() == yes_btn:
                # Écrire directement la correction en base de données SQLite de manière pérenne !
                from infrastructure.sqlite_repository import SqliteRepository
                
                conn = sqlite3.connect(SqliteRepository.get_db_path())
                cursor = conn.cursor()
                
                # Retrouver l'adhérent exact par son nom/prénom
                parts = orig_name.split(" ", 1)
                first_name = parts[0].strip()
                last_name = parts[1].strip() if len(parts) > 1 else ""
                
                # Mettre à jour les colonnes d'adresse
                cursor.execute(
                    "UPDATE users SET "
                    "address = ?, zip_code = ?, city = ? "
                    "WHERE UPPER(TRIM(first_name)) = UPPER(TRIM(?)) "
                    "AND UPPER(TRIM(last_name)) = UPPER(TRIM(?))",
                    (s_name, s_postcode, s_city, first_name, last_name)
                )
                
                # Enregistrer également directement les coordonnées dans le geocache pour un affichage carte instantané !
                if len(coords) >= 2:
                    lon, lat = coords[0], coords[1]
                    city_upper = s_city.strip().upper()
                    full_address = f"{s_name.strip()}, {s_postcode.strip()}, {city_upper}, France"
                    full_address = " ".join(full_address.split())
                    
                    cursor.execute(
                        "INSERT OR REPLACE INTO geocache (address, lat, lon) VALUES (?, ?, ?)",
                        (full_address, lat, lon)
                    )
                
                conn.commit()
                conn.close()
                
                QMessageBox.information(self, "Adresse Corrigée", f"✅ L'adresse de {orig_name} a été corrigée et enregistrée en BDD avec succès !")
                
                # Rafraîchir l'IHM locale
                self.populate_unrecognized_table()
                
                # Signaler le rafraîchissement au reste de l'application
                main_win = self.window()
                if main_win and hasattr(main_win, "on_nav_changed"):
                    main_win.on_nav_changed(main_win.stacked_widget.currentIndex(), force_reload=True)
                    
        except Exception as e:
            QMessageBox.critical(self, "Erreur", f"Une erreur s'est produite lors de la correction : {e}")

    def start_manual_geocoding(self):
        """Récupère toutes les adresses en attente de géocodage et lance le worker asynchrone."""
        unresolved_addresses = []
        try:
            from infrastructure.sqlite_repository import SqliteRepository
            raw_data = SqliteRepository.load_direct_data()
            geocache = SqliteRepository.get_geocache()
            
            for row in raw_data:
                status = row.get("status", "Validé")
                if "annul" in str(status).lower():
                    continue
                    
                addr = row.get("champ_Adresse : numéro et nom de rue") or ""
                city = row.get("champ_Ville") or ""
                zip_code = row.get("champ_Code postal") or ""
                
                city_upper = str(city).strip().upper() if city else ""
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
                    
                # Si elle n'est pas dans le geocache, elle est en attente de géocodage !
                if full_address not in geocache:
                    if full_address not in unresolved_addresses:
                        unresolved_addresses.append(full_address)
        except Exception as e:
            QMessageBox.warning(self, "Erreur", f"Impossible de lister les adresses en attente : {e}")
            return
            
        if not unresolved_addresses:
            QMessageBox.information(
                self, "Aucune adresse en attente",
                "Toutes les adresses valides ont déjà été géocodées et enregistrées !"
            )
            return
            
        self.btn_geocode.setEnabled(False)
        self.geocode_status_lbl.setText(f"⏳ Préparation du géocodage pour {len(unresolved_addresses)} adresses...")
        
        # Lancer le worker QThread de manière non-bloquante !
        self.geocode_worker = GeocodeWorker(unresolved_addresses)
        self.geocode_worker.progress.connect(self.on_geocode_progress)
        self.geocode_worker.finished.connect(self.on_geocode_finished)
        self.geocode_worker.start()

    def on_geocode_progress(self, message: str, percent: int):
        self.geocode_status_lbl.setText(message)

    def on_geocode_finished(self, success: bool, resolved: int, failed: int):
        self.btn_geocode.setEnabled(True)
        if success:
            self.geocode_status_lbl.setText(f"✅ Géocodage terminé ! {resolved} adresses géolocalisées, {failed} échecs.")
            # Recharger le tableau d'audit des adresses
            self.populate_unrecognized_table()
            
            # Mettre à jour la carte s'il y a lieu
            main_win = self.window()
            if main_win and hasattr(main_win, "on_nav_changed"):
                main_win.on_nav_changed(main_win.stacked_widget.currentIndex(), force_reload=True)
        else:
            self.geocode_status_lbl.setText("❌ Échec lors du géocodage en tâche de fond.")

    def update_sync_dates_on_banner(self):
        """Récupère et actualise les dates de synchronisation sur la bannière."""
        drive_sync = SecretStore.get_secret("LAST_GOOGLE_DRIVE_SYNC") or "Inconnue"

        hello_sync = SecretStore.get_secret("LAST_HELLOASSO_SYNC") or "Inconnue"

        self.drive_sync_lbl.setText(f"🌐 Dernière mise à jour Drive : {drive_sync}")
        self.hello_sync_lbl.setText(f"🔄 Dernière synchro HelloAsso : {hello_sync}")

    def open_interactive_map(self):
        """Ouvre la carte interactive des adhérents dans le navigateur par défaut."""
        port = os.environ.get("FASTAPI_PORT", "8000")
        webbrowser.open(f"http://127.0.0.1:{port}/map")

    def open_interactive_pivot(self):
        """Ouvre le Tableau Croisé Dynamique interactif dans le navigateur par défaut."""
        port = os.environ.get("FASTAPI_PORT", "8000")
        webbrowser.open(f"http://127.0.0.1:{port}/pivot")

    def test_server_connection(self):
        """Tester de façon instantanée et sécuritaire si le serveur local d'API répond."""
        port = int(os.environ.get("FASTAPI_PORT", "8000"))
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(1.0)
                s.connect(('127.0.0.1', port))
            QMessageBox.information(
                self,
                "Serveur Opérationnel",
                f"⚡ Connexion réseau réussie ! Le serveur local d'API répond parfaitement et de manière instantanée sur le port {port}."
            )
        except Exception as e:
            QMessageBox.critical(
                self,
                "Serveur Hors-ligne",
                f"❌ Échec de la connexion réseau : Le serveur local d'API ne répond pas sur le port {port}.\n\n"
                f"Veuillez cliquer sur 'Relancer le Serveur' pour régénérer le canal local.\n\nDétails : {e}"
            )

    def restart_map_server(self):
        """Trouve un nouveau port libre et lance une nouvelle instance du serveur FastAPI en tâche de fond."""
        def find_free_port(start_port=8000, max_port=8099):
            for port in range(start_port, max_port + 1):
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    try:
                        s.bind(('127.0.0.1', port))
                        return port
                    except OSError:
                        continue
            return 8000
            
        def run_server(port):
            try:
                from server import app as fastapi_app
                import uvicorn
                uvicorn.run(fastapi_app, host="127.0.0.1", port=port, log_level="warning")
            except Exception as e:
                print(f"⚠️ [RESTART_SERVER] Erreur : {e}")

        new_port = find_free_port()
        os.environ["FASTAPI_PORT"] = str(new_port)
        
        # Lancer le nouveau serveur dans un Daemon Thread de façon non bloquante
        t = threading.Thread(target=run_server, args=(new_port,), daemon=True)
        t.start()
        
        QMessageBox.information(
            self,
            "Serveur Logiquement Relancé",
            f"Le serveur API d'arrière-plan a été ré-initialisé et relancé avec succès sur le port {new_port}.\n\n"
            "Vos raccourcis de cartes et de tableaux croisés s'ouvriront à présent sur ce nouveau port dynamique."
        )
        self.update_sync_dates_on_banner()

    def load_and_calculate_stats(self, force_reload=False):
        """Rétro-compatibilité pour l'IHM globale sans ralentissement."""
        self.update_sync_dates_on_banner()
        self.populate_unrecognized_table()
