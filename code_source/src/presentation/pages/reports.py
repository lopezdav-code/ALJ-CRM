import os
import socket
import sqlite3
import webbrowser
import threading
import time
import datetime
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, 
    QPushButton, QMessageBox, QGridLayout, QTableWidget, QTableWidgetItem,
    QHeaderView, QSizePolicy
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QPixmap

from paths import CODE_ROOT, ROOT_DIR

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

    # ------------------------------------------------------------------
    # Styles QSS centralises de la page (maintenance facilitee)
    # ------------------------------------------------------------------
    QSS_CARD = "QFrame { background-color: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 10px; }"
    QSS_ICON = "QLabel {{ background-color: {bg}; border-radius: 10px; font-size: 22px; }}"
    QSS_PILL_OK = "QLabel { background-color: #DCFCE7; color: #166534; border: 1px solid #86EFAC; border-radius: 10px; padding: 4px 12px; font-size: 12px; font-weight: bold; }"
    QSS_PILL_WARN = "QLabel { background-color: #FEF3C7; color: #92400E; border: 1px solid #FCD34D; border-radius: 10px; padding: 4px 12px; font-size: 12px; font-weight: bold; }"
    QSS_PILL_NEUTRAL = "QLabel { background-color: #F1F5F9; color: #475569; border: 1px solid #E2E8F0; border-radius: 10px; padding: 4px 12px; font-size: 12px; font-weight: bold; }"
    QSS_BTN_PRIMARY = """
        QPushButton {
            background-color: #2563EB; color: #FFFFFF; border: none;
            border-radius: 6px; padding: 9px 16px; font-weight: bold; font-size: 12px;
        }
        QPushButton:hover { background-color: #1D4ED8; }
        QPushButton:disabled { background-color: #94A3B8; }
    """
    QSS_BTN_SECONDARY = """
        QPushButton {
            background-color: #FFFFFF; color: #334155; border: 1px solid #CBD5E1;
            border-radius: 6px; padding: 9px 16px; font-weight: bold; font-size: 12px;
        }
        QPushButton:hover { background-color: #F8FAFC; border-color: #94A3B8; }
    """

    def _make_card_title(self, icon_text, icon_bg, title_text, subtitle_text=None):
        """En-tete de carte : pastille icone + titre (et sous-titre facultatif)."""
        head = QHBoxLayout()
        head.setSpacing(12)
        icon_lbl = QLabel(icon_text)
        icon_lbl.setFixedSize(46, 46)
        icon_lbl.setAlignment(Qt.AlignCenter)
        icon_lbl.setStyleSheet(self.QSS_ICON.format(bg=icon_bg))
        head.addWidget(icon_lbl)

        col = QVBoxLayout()
        col.setSpacing(2)
        t = QLabel(title_text)
        t.setStyleSheet("font-size: 16px; font-weight: bold; color: #1E293B; background: transparent; border: none;")
        col.addWidget(t)
        if subtitle_text:
            s = QLabel(subtitle_text)
            s.setStyleSheet("font-size: 11px; color: #64748B; background: transparent; border: none;")
            col.addWidget(s)
        head.addLayout(col)
        head.addStretch()
        return head

    def _vline(self):
        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setStyleSheet("color: #BFDBFE; max-height: 20px;")
        return sep

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 25, 30, 25)
        layout.setSpacing(14)

        # 1. TITRE DE PAGE (gabarit commun a tous les onglets)
        title = QLabel("🔧 Boîte à Outils d'Administration & Analyses")
        title.setStyleSheet("font-size: 24px; font-weight: bold; color: #1E293B;")
        title.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        layout.addWidget(title)

        subtitle = QLabel("Accédez aux outils d'analyse et de cartographie, et gérez la qualité des données ainsi que la supervision du serveur.")
        subtitle.setStyleSheet("color: #64748B; font-size: 13px;")
        subtitle.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        layout.addWidget(subtitle)

        # 2. BARRE D'ETAT GENERAL (outils disponibles / anomalies / API)
        self.status_bar = QFrame()
        self.status_bar.setObjectName("StatusBar")
        self.status_bar.setStyleSheet("""
            QFrame#StatusBar {
                background-color: #EFF6FF;
                border: 1px solid #DBEAFE;
                border-radius: 8px;
            }
            QLabel { background: transparent; border: none; }
        """)
        status_layout = QHBoxLayout(self.status_bar)
        status_layout.setContentsMargins(16, 14, 16, 14)
        status_layout.setSpacing(12)

        lbl_tools = QLabel("🧩 3 outils disponibles")
        lbl_tools.setStyleSheet("color: #1E293B; font-size: 13px; font-weight: bold;")
        lbl_tools.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        lbl_tools.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        status_layout.addWidget(lbl_tools, 1)

        self.status_anomalies_lbl = QLabel("✅ 0 anomalie d'adresse")
        self.status_anomalies_lbl.setStyleSheet("color: #16A34A; font-size: 13px; font-weight: bold;")
        self.status_anomalies_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.status_anomalies_lbl.setAlignment(Qt.AlignVCenter | Qt.AlignHCenter)
        status_layout.addWidget(self.status_anomalies_lbl, 1)
        status_layout.addWidget(self._vline())

        self.status_api_lbl = QLabel("🟢 API opérationnelle")
        self.status_api_lbl.setStyleSheet("color: #16A34A; font-size: 13px; font-weight: bold;")
        self.status_api_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.status_api_lbl.setAlignment(Qt.AlignVCenter | Qt.AlignRight)
        status_layout.addWidget(self.status_api_lbl, 1)
        layout.addWidget(self.status_bar)

        # 3. ZONE 1 - OUTILS PRINCIPAUX (2 cartes cote a cote)
        tools_grid = QGridLayout()
        tools_grid.setSpacing(14)
        tools_grid.setColumnStretch(0, 1)
        tools_grid.setColumnStretch(1, 1)

        # --- Carte 1 : Cartographie interactive ---
        card_map = QFrame()
        card_map.setStyleSheet(self.QSS_CARD)
        card_map.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        map_outer = QHBoxLayout(card_map)
        map_outer.setContentsMargins(18, 16, 18, 16)
        map_outer.setSpacing(16)
        lay_map = QVBoxLayout()
        lay_map.setSpacing(10)
        map_outer.addLayout(lay_map, 1)
        lay_map.addLayout(self._make_card_title("🗺️", "#DBEAFE", "Cartographie interactive"))
        desc_map = QLabel(
            "Visualisez la répartition géographique des adhérents sur une carte de France interactive. "
            "Analysez la densité d'effectifs par commune, département ou région."
        )
        desc_map.setWordWrap(True)
        desc_map.setStyleSheet("font-size: 12px; color: #475569; background: transparent; border: none;")
        lay_map.addWidget(desc_map)
        lay_map.addStretch()
        btn_open_map = QPushButton("🗺️  Ouvrir la carte interactive")
        btn_open_map.setCursor(Qt.PointingHandCursor)
        btn_open_map.setStyleSheet(self.QSS_BTN_PRIMARY)
        btn_open_map.clicked.connect(self.open_interactive_map)
        lay_map.addWidget(btn_open_map, Qt.AlignLeft)
        map_preview = self._load_doc_image("maps.png", height=170)
        if map_preview is not None:
            map_outer.addWidget(map_preview)
        tools_grid.addWidget(card_map, 0, 0)

        # --- Carte 2 : Analyse des effectifs (TCD) ---
        card_tcd = QFrame()
        card_tcd.setStyleSheet(self.QSS_CARD)
        card_tcd.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        tcd_outer = QHBoxLayout(card_tcd)
        tcd_outer.setContentsMargins(18, 16, 18, 16)
        tcd_outer.setSpacing(16)
        lay_tcd = QVBoxLayout()
        lay_tcd.setSpacing(10)
        tcd_outer.addLayout(lay_tcd, 1)
        lay_tcd.addLayout(self._make_card_title("📊", "#EDE9FE", "Analyse des effectifs (TCD)"))
        desc_tcd = QLabel(
            "Explorez et croisez vos données d'inscription à l'aide d'une grille de reporting dynamique. "
            "Filtrez, regroupez et analysez vos adhérents en quelques clics."
        )
        desc_tcd.setWordWrap(True)
        desc_tcd.setStyleSheet("font-size: 12px; color: #475569; background: transparent; border: none;")
        lay_tcd.addWidget(desc_tcd)
        lay_tcd.addStretch()
        btn_open_tcd = QPushButton("📊  Ouvrir le tableau croisé dynamique")
        btn_open_tcd.setCursor(Qt.PointingHandCursor)
        btn_open_tcd.setStyleSheet(self.QSS_BTN_PRIMARY)
        btn_open_tcd.clicked.connect(self.open_interactive_pivot)
        lay_tcd.addWidget(btn_open_tcd, Qt.AlignLeft)
        tcd_preview = self._load_doc_image("TDC.png", height=170)
        if tcd_preview is not None:
            tcd_outer.addWidget(tcd_preview)
        tools_grid.addWidget(card_tcd, 0, 1)

        layout.addLayout(tools_grid)

        # 4. ZONE 2/3 - QUALITE DES ADRESSES (large) + SERVEUR API LOCAL (compact)
        bottom_grid = QGridLayout()
        bottom_grid.setSpacing(14)
        bottom_grid.setColumnStretch(0, 1)
        bottom_grid.setColumnStretch(1, 1)

        # --- Carte Qualite des adresses ---
        card_quality = QFrame()
        card_quality.setStyleSheet(self.QSS_CARD)
        card_quality.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        quality_layout = QVBoxLayout(card_quality)
        quality_layout.setContentsMargins(18, 16, 18, 16)
        quality_layout.setSpacing(12)

        q_head = QHBoxLayout()
        q_head.setSpacing(12)
        q_icon = QLabel("📍")
        q_icon.setFixedSize(46, 46)
        q_icon.setAlignment(Qt.AlignCenter)
        q_icon.setStyleSheet(self.QSS_ICON.format(bg="#DBEAFE"))
        q_head.addWidget(q_icon)
        q_col = QVBoxLayout()
        q_col.setSpacing(2)
        q_title = QLabel("Qualité des adresses")
        q_title.setStyleSheet("font-size: 16px; font-weight: bold; color: #1E293B; background: transparent; border: none;")
        q_col.addWidget(q_title)
        q_sub = QLabel("Vérification et correction des adresses des adhérents.")
        q_sub.setStyleSheet("font-size: 11px; color: #64748B; background: transparent; border: none;")
        q_col.addWidget(q_sub)
        q_head.addLayout(q_col)
        q_head.addStretch()
        self.quality_badge = QLabel("Aucune anomalie détectée")
        self.quality_badge.setStyleSheet(self.QSS_PILL_OK)
        q_head.addWidget(self.quality_badge, Qt.AlignTop)
        quality_layout.addLayout(q_head)

        # Etat OK : encart vert compact (empty state)
        self.quality_ok_widget = QFrame()
        self.quality_ok_widget.setStyleSheet("""
            QFrame {
                background-color: #F0FDF4;
                border: 1px solid #BBF7D0;
                border-radius: 8px;
            }
            QLabel { background: transparent; border: none; }
        """)
        # Compact : l'encart ne doit jamais s'etirer verticalement (empty state)
        self.quality_ok_widget.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.quality_ok_widget.setMaximumHeight(210)
        ok_layout = QVBoxLayout(self.quality_ok_widget)
        ok_layout.setContentsMargins(16, 14, 16, 14)
        ok_layout.setSpacing(6)
        ok_layout.setAlignment(Qt.AlignHCenter)
        ok_circle = QLabel("✓")
        ok_circle.setFixedSize(52, 52)
        ok_circle.setAlignment(Qt.AlignCenter)
        ok_circle.setStyleSheet("""
            QLabel {
                background-color: #16A34A; color: #FFFFFF;
                border-radius: 26px; font-size: 26px; font-weight: bold;
            }
        """)
        ok_layout.addWidget(ok_circle, Qt.AlignHCenter)
        ok_t1 = QLabel("Toutes les adresses sont reconnues")
        ok_t1.setStyleSheet("font-size: 15px; font-weight: bold; color: #14532D;")
        ok_layout.addWidget(ok_t1, Qt.AlignHCenter)
        ok_t2 = QLabel("✓ 0 anomalie")
        ok_t2.setStyleSheet("font-size: 12px; font-weight: bold; color: #16A34A;")
        ok_layout.addWidget(ok_t2, Qt.AlignHCenter)
        ok_t3 = QLabel("Aucune adresse n'a besoin d'être corrigée ou géocodée.")
        ok_t3.setStyleSheet("font-size: 12px; color: #475569;")
        ok_layout.addWidget(ok_t3, Qt.AlignHCenter)
        quality_layout.addWidget(self.quality_ok_widget)

        # Etat anomalies : actions + tableau d'audit
        self.quality_error_widget = QWidget()
        error_layout = QVBoxLayout(self.quality_error_widget)
        error_layout.setContentsMargins(0, 0, 0, 0)
        error_layout.setSpacing(10)

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
        error_layout.addLayout(geocode_action_layout)

        self.unrec_table = QTableWidget()
        self.unrec_table.setMinimumHeight(180)
        self.unrec_table.setMaximumHeight(320)
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
        error_layout.addWidget(self.unrec_table)
        self.quality_error_widget.setVisible(False)
        quality_layout.addWidget(self.quality_error_widget)

        bottom_grid.addWidget(card_quality, 0, 0)

        # --- Carte Serveur API local (zone technique, secondaire et compacte) ---
        card_server = QFrame()
        card_server.setStyleSheet(self.QSS_CARD)
        card_server.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        server_layout = QVBoxLayout(card_server)
        server_layout.setContentsMargins(18, 16, 18, 16)
        server_layout.setSpacing(10)
        server_layout.addLayout(self._make_card_title(
            "🖥️", "#F1F5F9", "Serveur API local", "API locale • FastAPI / Uvicorn"))

        self.server_status_pill = QLabel("● Vérification en cours...")
        self.server_status_pill.setStyleSheet(self.QSS_PILL_NEUTRAL)
        self.server_status_pill.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        server_layout.addWidget(self.server_status_pill, Qt.AlignLeft)

        info_frame = QFrame()
        info_frame.setStyleSheet("""
            QFrame {
                background-color: #F8FAFC;
                border: 1px solid #E2E8F0;
                border-radius: 6px;
            }
            QLabel { background: transparent; border: none; }
        """)
        info_grid = QGridLayout(info_frame)
        info_grid.setContentsMargins(12, 10, 12, 10)
        info_grid.setVerticalSpacing(6)
        info_grid.setHorizontalSpacing(12)

        def info_row(row, label_text, value_widget):
            k = QLabel(label_text)
            k.setStyleSheet("color: #64748B; font-size: 11px;")
            info_grid.addWidget(k, row, 0)
            info_grid.addWidget(value_widget, row, 1)

        self.server_url_lbl = QLabel("http://127.0.0.1:8000")
        self.server_url_lbl.setStyleSheet("color: #1E293B; font-size: 11px; font-weight: bold;")
        info_row(0, "URL locale", self.server_url_lbl)
        self.server_check_lbl = QLabel("—")
        self.server_check_lbl.setStyleSheet("color: #1E293B; font-size: 11px;")
        info_row(1, "Dernière vérification", self.server_check_lbl)
        self.server_ms_lbl = QLabel("—")
        self.server_ms_lbl.setStyleSheet("color: #1E293B; font-size: 11px;")
        info_row(2, "Temps de réponse", self.server_ms_lbl)
        info_grid.setColumnStretch(1, 1)
        server_layout.addWidget(info_frame)

        srv_btn_layout = QHBoxLayout()
        srv_btn_layout.setSpacing(10)
        btn_test_srv = QPushButton("↻  Tester la connexion")
        btn_test_srv.setCursor(Qt.PointingHandCursor)
        btn_test_srv.setStyleSheet(self.QSS_BTN_SECONDARY)
        btn_test_srv.clicked.connect(self.test_server_connection)
        srv_btn_layout.addWidget(btn_test_srv)

        btn_restart_srv = QPushButton("▶  Relancer le serveur")
        btn_restart_srv.setCursor(Qt.PointingHandCursor)
        btn_restart_srv.setStyleSheet(self.QSS_BTN_PRIMARY)
        btn_restart_srv.clicked.connect(self.restart_map_server)
        srv_btn_layout.addWidget(btn_restart_srv)
        srv_btn_layout.addStretch()
        server_layout.addLayout(srv_btn_layout)
        server_layout.addStretch()

        bottom_grid.addWidget(card_server, 0, 1)
        layout.addLayout(bottom_grid)

        # 5. ZONE SYNCHRONISATION (2 cartes côte à côte : BDD Drive + HelloAsso)
        sync_section = QLabel("🌐 Synchronisation")
        sync_section.setStyleSheet("""
            QLabel {
                background-color: #F8FAFC;
                border: 1px solid #E2E8F0;
                border-radius: 6px;
                padding: 8px 14px;
                color: #1E293B;
                font-size: 13px;
                font-weight: bold;
            }
        """)
        sync_section.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        layout.addWidget(sync_section)

        sync_grid = QGridLayout()
        sync_grid.setSpacing(14)
        sync_grid.setColumnStretch(0, 1)
        sync_grid.setColumnStretch(1, 1)

        # --- Carte 1 : Télécharger la BDD (Google Drive) ---
        card_db = QFrame()
        card_db.setStyleSheet(self.QSS_CARD)
        card_db.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        db_layout = QVBoxLayout(card_db)
        db_layout.setContentsMargins(18, 16, 18, 16)
        db_layout.setSpacing(10)
        db_layout.addLayout(self._make_card_title(
            "☁️", "#DBEAFE", "Télécharger la BDD", "Base de données • Google Drive"))

        # Informations : dates de dernier import / fichier Drive
        db_info_frame = QFrame()
        db_info_frame.setStyleSheet("""
            QFrame {
                background-color: #F8FAFC;
                border: 1px solid #E2E8F0;
                border-radius: 6px;
            }
            QLabel { background: transparent; border: none; }
        """)
        db_info_grid = QGridLayout(db_info_frame)
        db_info_grid.setContentsMargins(12, 10, 12, 10)
        db_info_grid.setVerticalSpacing(6)
        db_info_grid.setHorizontalSpacing(12)

        k1 = QLabel("📥 Date du dernier import")
        k1.setStyleSheet("color: #64748B; font-size: 11px;")
        self.drive_sync_lbl = QLabel("Inconnue")
        self.drive_sync_lbl.setStyleSheet("color: #1E293B; font-size: 11px; font-weight: bold;")
        db_info_grid.addWidget(k1, 0, 0)
        db_info_grid.addWidget(self.drive_sync_lbl, 0, 1)

        k2 = QLabel("☁️ Date du fichier Drive (database.db)")
        k2.setStyleSheet("color: #64748B; font-size: 11px;")
        self.drive_db_date_lbl = QLabel("—")
        self.drive_db_date_lbl.setStyleSheet("color: #1E293B; font-size: 11px; font-weight: bold;")
        db_info_grid.addWidget(k2, 1, 0)
        db_info_grid.addWidget(self.drive_db_date_lbl, 1, 1)
        db_info_grid.setColumnStretch(1, 1)
        db_layout.addWidget(db_info_frame)

        # Rappel de fonctionnement
        db_recall = QLabel(
            "💡 La BDD est sauvegardée sur Google Drive (envoi automatique à la fermeture du logiciel). "
            "Un cache local est en place : faites la mise à jour si plusieurs personnes travaillent sur la BDD."
        )
        db_recall.setWordWrap(True)
        db_recall.setStyleSheet("color: #94A3B8; font-size: 11px; font-style: italic; background: transparent; border: none;")
        db_layout.addWidget(db_recall)

        # Actions : telecharger depuis Drive / envoyer sur Drive
        db_btn_layout = QHBoxLayout()
        db_btn_layout.setSpacing(10)
        btn_download_db = QPushButton("⬇️  Télécharger depuis Drive")
        btn_download_db.setCursor(Qt.PointingHandCursor)
        btn_download_db.setStyleSheet(self.QSS_BTN_SECONDARY)
        btn_download_db.clicked.connect(self.start_drive_sync_workflow)
        db_btn_layout.addWidget(btn_download_db)

        btn_upload_db = QPushButton("⬆️  Envoyer la BDD sur Drive")
        btn_upload_db.setCursor(Qt.PointingHandCursor)
        btn_upload_db.setStyleSheet(self.QSS_BTN_PRIMARY)
        btn_upload_db.clicked.connect(self.start_drive_upload_workflow)
        db_btn_layout.addWidget(btn_upload_db)
        db_btn_layout.addStretch()
        db_layout.addLayout(db_btn_layout)

        sync_grid.addWidget(card_db, 0, 0)

        # --- Carte 2 : Synchro avec HelloAsso ---
        card_ha = QFrame()
        card_ha.setStyleSheet(self.QSS_CARD)
        card_ha.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        ha_layout = QVBoxLayout(card_ha)
        ha_layout.setContentsMargins(18, 16, 18, 16)
        ha_layout.setSpacing(10)
        ha_layout.addLayout(self._make_card_title(
            "🔄", "#DCFCE7", "Synchro avec HelloAsso", "Inscriptions • Fusion automatique"))

        ha_info_frame = QFrame()
        ha_info_frame.setStyleSheet("""
            QFrame {
                background-color: #F8FAFC;
                border: 1px solid #E2E8F0;
                border-radius: 6px;
            }
            QLabel { background: transparent; border: none; }
        """)
        ha_info_grid = QGridLayout(ha_info_frame)
        ha_info_grid.setContentsMargins(12, 10, 12, 10)
        ha_info_grid.setVerticalSpacing(6)
        ha_info_grid.setHorizontalSpacing(12)

        k3 = QLabel("🔄 Date de la dernière synchronisation")
        k3.setStyleSheet("color: #64748B; font-size: 11px;")
        self.hello_sync_lbl = QLabel("Inconnue")
        self.hello_sync_lbl.setStyleSheet("color: #1E293B; font-size: 11px; font-weight: bold;")
        ha_info_grid.addWidget(k3, 0, 0)
        ha_info_grid.addWidget(self.hello_sync_lbl, 0, 1)
        ha_info_grid.setColumnStretch(1, 1)
        ha_layout.addWidget(ha_info_frame)

        ha_recall = QLabel(
            "💡 Récupère les nouvelles inscriptions HelloAsso de la saison et les fusionne "
            "automatiquement avec la base locale, puis sauvegarde sur Google Drive."
        )
        ha_recall.setWordWrap(True)
        ha_recall.setStyleSheet("color: #94A3B8; font-size: 11px; font-style: italic; background: transparent; border: none;")
        ha_layout.addWidget(ha_recall)

        ha_btn_layout = QHBoxLayout()
        btn_hello_sync = QPushButton("🔄  Mettre à jour depuis HelloAsso")
        btn_hello_sync.setCursor(Qt.PointingHandCursor)
        btn_hello_sync.setStyleSheet(self.QSS_BTN_PRIMARY)
        btn_hello_sync.clicked.connect(self.start_helloasso_sync_workflow)
        ha_btn_layout.addWidget(btn_hello_sync)
        ha_btn_layout.addStretch()
        ha_layout.addLayout(ha_btn_layout)

        sync_grid.addWidget(card_ha, 0, 1)

        layout.addLayout(sync_grid)

        # Espace libre en bas de page (les cartes restent compactes)
        layout.addStretch(1)

        # Mettre a jour les labels de date, le tableau d'audit et l'etat serveur au demarrage
        self.update_sync_dates_on_banner()
        self.populate_unrecognized_table()
        self.refresh_server_status()

    def _load_doc_image(self, filename: str, height: int = 170):
        """Charge une image d'illustration depuis le dossier doc (apercu des outils).
        Retourne un QLabel prete a afficher, ou None si le fichier est absent/illisible."""
        path = None
        for base in (CODE_ROOT, ROOT_DIR):
            candidate = os.path.join(base, "doc", filename)
            if os.path.exists(candidate):
                path = candidate
                break
        if not path:
            return None
        try:
            pixmap = QPixmap(path)
            if pixmap.isNull():
                return None
            scaled = pixmap.scaledToHeight(height, Qt.SmoothTransformation)
            lbl = QLabel()
            lbl.setPixmap(scaled)
            lbl.setStyleSheet("border: 1px solid #E2E8F0; background-color: #FFFFFF;")
            lbl.setAlignment(Qt.AlignCenter)
            return lbl
        except Exception:
            return None

    def _probe_server(self, timeout=0.4):
        """Teste la disponibilite du serveur local. Retourne (actif, temps_de_reponse_ms)."""
        port = int(os.environ.get("FASTAPI_PORT", "8000"))
        start = time.time()
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(timeout)
                s.connect(('127.0.0.1', port))
            return True, max(1, int((time.time() - start) * 1000))
        except Exception:
            return False, None

    def _apply_server_status(self, alive, ms=None):
        """Met a jour la pastille serveur et l'indicateur de la barre d'etat."""
        if alive is True:
            self.server_status_pill.setText("●  Serveur opérationnel")
            self.server_status_pill.setStyleSheet(self.QSS_PILL_OK)
            self.server_ms_lbl.setText(f"{ms} ms" if ms else "—")
            self.status_api_lbl.setText("🟢 API opérationnelle")
            self.status_api_lbl.setStyleSheet("color: #16A34A; font-size: 12px; font-weight: bold;")
        elif alive is False:
            self.server_status_pill.setText("●  Serveur indisponible")
            self.server_status_pill.setStyleSheet(self.QSS_PILL_WARN)
            self.server_ms_lbl.setText("—")
            self.status_api_lbl.setText("🔴 API indisponible")
            self.status_api_lbl.setStyleSheet("color: #DC2626; font-size: 12px; font-weight: bold;")
        else:
            self.server_status_pill.setText("●  Vérification en cours...")
            self.server_status_pill.setStyleSheet(self.QSS_PILL_NEUTRAL)

    def refresh_server_status(self):
        """Actualise la carte serveur (URL, date, temps de reponse) et la barre d'etat."""
        alive, ms = self._probe_server()
        port = os.environ.get("FASTAPI_PORT", "8000")
        self.server_url_lbl.setText(f"http://127.0.0.1:{port}")
        self.server_check_lbl.setText(datetime.datetime.now().strftime("%d/%m/%Y %H:%M"))
        self._apply_server_status(alive, ms)

    def _update_quality_state(self, count):
        """Bascule l'affichage Qualite des adresses entre etat vide (0 anomalie)
        et etat anomalies (actions + tableau), et met a jour la barre d'etat."""
        has_errors = count > 0
        self.quality_error_widget.setVisible(has_errors)
        self.quality_ok_widget.setVisible(not has_errors)
        if has_errors:
            self.quality_badge.setText(f"⚠️ {count} adresse(s) à corriger")
            self.quality_badge.setStyleSheet(self.QSS_PILL_WARN)
            self.status_anomalies_lbl.setText(f"⚠️ {count} anomalie(s) d'adresse")
            self.status_anomalies_lbl.setStyleSheet("color: #B45309; font-size: 12px; font-weight: bold;")
        else:
            self.quality_badge.setText("Aucune anomalie détectée")
            self.quality_badge.setStyleSheet(self.QSS_PILL_OK)
            self.status_anomalies_lbl.setText("✅ 0 anomalie d'adresse")
            self.status_anomalies_lbl.setStyleSheet("color: #16A34A; font-size: 12px; font-weight: bold;")


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
                    
                addr = row.get("address") or ""
                city = row.get("city") or ""
                zip_code = row.get("zip_code") or ""
                
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
                        "name": f"{row.get('first_name', '').strip().title()} {row.get('last_name', '').strip().upper()}",
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

        # Etat visuel : encart compact (0 anomalie) ou liste d'actions + tableau
        self._update_quality_state(len(unresolved))

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
                    
                addr = row.get("address") or ""
                city = row.get("city") or ""
                zip_code = row.get("zip_code") or ""
                
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
        """Récupère et actualise les dates de synchronisation sur les cartes."""
        drive_sync = SecretStore.get_secret("LAST_GOOGLE_DRIVE_IMPORT") or SecretStore.get_secret("LAST_GOOGLE_DRIVE_SYNC") or "Inconnue"
        hello_sync = SecretStore.get_secret("LAST_HELLOASSO_SYNC") or "Inconnue"

        self.drive_sync_lbl.setText(drive_sync)
        self.hello_sync_lbl.setText(hello_sync)
        self._refresh_drive_db_date()

    def _refresh_drive_db_date(self):
        """Interroge Google Drive en arrière-plan pour afficher la date de dernière
        modification du fichier database.db hébergé sur Drive."""
        from infrastructure.google_drive_client import GoogleDriveClient
        file_id = SecretStore.get_secret("GOOGLE_DRIVE_DB_ID")
        if not file_id:
            self.drive_db_date_lbl.setText("Aucun ID Drive configuré")
            return

        self.drive_db_date_lbl.setText("Interrogation en cours...")

        class _DriveDateWorker(QThread):
            date_ready = Signal(str)

            def __init__(self, fid, parent=None):
                super().__init__(parent)
                self.fid = fid

            def run(self):
                try:
                    self.date_ready.emit(GoogleDriveClient.get_file_modified_time(self.fid))
                except Exception:
                    self.date_ready.emit("")

        self._drive_date_worker = _DriveDateWorker(file_id)
        self._drive_date_worker.date_ready.connect(self._on_drive_db_date_ready)
        self._drive_date_worker.start()

    def _on_drive_db_date_ready(self, date_str: str):
        self.drive_db_date_lbl.setText(date_str if date_str else "Indisponible")

    # ------------------------------------------------------------------
    # Actions de synchronisation : délégation aux workflows de la fenêtre
    # principale (mêmes workers et boîtes de dialogue que l'Import Data)
    # ------------------------------------------------------------------
    def start_drive_sync_workflow(self):
        """Télécharge la BDD la plus récente depuis Google Drive (workflow principal)."""
        main_win = self.window()
        if main_win and hasattr(main_win, "start_drive_sync_workflow"):
            main_win.start_drive_sync_workflow()
            self.drive_sync_lbl.setText("Téléchargement en cours...")
        else:
            QMessageBox.warning(self, "Indisponible", "Action disponible uniquement depuis la fenêtre principale.")

    def start_drive_upload_workflow(self):
        """Envoie la BDD locale sur Google Drive (workflow principal)."""
        main_win = self.window()
        if main_win and hasattr(main_win, "start_drive_upload_workflow"):
            main_win.start_drive_upload_workflow()
        else:
            QMessageBox.warning(self, "Indisponible", "Action disponible uniquement depuis la fenêtre principale.")

    def start_helloasso_sync_workflow(self):
        """Lance la synchronisation et fusion HelloAsso (workflow principal)."""
        main_win = self.window()
        if main_win and hasattr(main_win, "start_sync_workflow"):
            main_win.start_sync_workflow()
            self.hello_sync_lbl.setText("Synchronisation en cours...")
        else:
            QMessageBox.warning(self, "Indisponible", "Action disponible uniquement depuis la fenêtre principale.")

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
        alive, ms = self._probe_server(timeout=1.0)
        port = int(os.environ.get("FASTAPI_PORT", "8000"))
        self.server_check_lbl.setText(datetime.datetime.now().strftime("%d/%m/%Y %H:%M"))
        self._apply_server_status(alive, ms)
        if alive:
            QMessageBox.information(
                self,
                "Serveur Opérationnel",
                f"⚡ Connexion réseau réussie ! Le serveur local d'API répond parfaitement et de manière instantanée sur le port {port}."
            )
        else:
            QMessageBox.critical(
                self,
                "Serveur Hors-ligne",
                f"❌ Échec de la connexion réseau : Le serveur local d'API ne répond pas sur le port {port}.\n\n"
                f"Veuillez cliquer sur 'Relancer le Serveur' pour régénérer le canal local.\n\nDétails : connexion refusée"
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
        # Mise a jour visuelle de la carte serveur (probe apres demarrage d'Uvicorn)
        self.server_url_lbl.setText(f"http://127.0.0.1:{new_port}")
        self.server_check_lbl.setText(datetime.datetime.now().strftime("%d/%m/%Y %H:%M"))
        self._apply_server_status(None)
        QTimer.singleShot(2000, self.refresh_server_status)
        self.update_sync_dates_on_banner()

    def load_and_calculate_stats(self, force_reload=False):
        """Rétro-compatibilité pour l'IHM globale sans ralentissement."""
        self.update_sync_dates_on_banner()
        self.populate_unrecognized_table()
        self.refresh_server_status()
