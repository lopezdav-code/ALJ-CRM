from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, 
    QPushButton, QStackedWidget, QFrame, QLabel, QMessageBox
)
from PySide6.QtCore import Qt

from presentation.pages.members import MembersPage
from presentation.pages.documents import DocumentsPage
from presentation.pages.communications import CommunicationsPage
from presentation.pages.exports import ExportsPage
from presentation.pages.ffme import ImportDataPage
from presentation.pages.gmail_contact import GmailContactPage
from presentation.pages.groups import GroupsPage
from presentation.pages.reports import ReportsPage
from presentation.pages.settings import SettingsPage
from presentation.pages.help import HelpPage
from presentation.pages.logs import LogsPage
from presentation.workers import SyncHelloAssoWorker, DownloadDriveFileWorker
from infrastructure.secret_store import SecretStore
from domain.constants import get_active_season, APP_VERSION

class MainWindow(QMainWindow):
    """
    Fenêtre principale de l'application ALJ Escalade moderne (PySide6).
    """
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ALJ Escalade - Gestion Administrative")
        self.resize(1150, 700)
        self.setMinimumSize(950, 600)
        
        # Charger le style général
        self.setStyleSheet("""
            QMainWindow {
                background-color: #F8FAFC;
            }
        """)

        self.init_ui()

        # Lancer le chargement asynchrone des données locales au démarrage après 100 ms de délai
        # pour laisser la fenêtre s'afficher instantanément à l'écran.
        from PySide6.QtCore import QTimer
        QTimer.singleShot(100, self.load_initial_data_async)

    def init_ui(self):
        # Widget central principal
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 1. BARRE LATÉRALE (Sidebar) de navigation
        sidebar = QFrame()
        sidebar.setStyleSheet("""
            QFrame {
                background-color: #163A5F;
                border: none;
                min-width: 220px;
                max-width: 220px;
            }
        """)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(10, 25, 10, 25)
        sidebar_layout.setSpacing(8)

        # Titre du Club dans la barre latérale
        club_title = QLabel("ALJ ESCALADE")
        club_title.setAlignment(Qt.AlignCenter)
        club_title.setStyleSheet("""
            QLabel {
                color: #FFFFFF;
                font-size: 18px;
                font-weight: bold;
                letter-spacing: 1px;
                margin-bottom: 25px;
            }
        """)
        sidebar_layout.addWidget(club_title)

        # Navigation Buttons (Onglets ALJ Escalade Manager)
        self.nav_buttons = []
        nav_items = [
            ("👥  Adhérents", 0),
            ("📄  Attestations", 1),
            ("✉️  Communications", 2),
            ("📦  Exports", 3),
            ("📥  Import Data", 4),
            ("🧗  Créneaux", 5),
            ("📧  Gmail Contact", 6),
            ("🔧  Outils", 7),
            ("⚙️  Paramètres", 8),
            ("❓  Aide", 9),
            ("📋  Logs", 10)
        ]

        for text, index in nav_items:
            btn = QPushButton(text)
            btn.setCheckable(True)
            btn.setAutoExclusive(True)
            btn.setStyleSheet(self.get_sidebar_button_style())
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda checked=False, idx=index: self.on_nav_changed(idx))
            sidebar_layout.addWidget(btn)
            self.nav_buttons.append(btn)

        # Sélectionner la première page (Accueil) par défaut
        self.nav_buttons[0].setChecked(True)

        sidebar_layout.addStretch()
        
        # Bouton Quitter
        quit_btn = QPushButton("🚪  Quitter")
        quit_btn.setCursor(Qt.PointingHandCursor)
        quit_btn.setStyleSheet("""
            QPushButton {
                color: #CBD5E1;
                background-color: transparent;
                border: none;
                border-radius: 6px;
                padding: 10px 15px;
                font-size: 13px;
                text-align: left;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: #EF4444;
                color: #FFFFFF;
                font-weight: bold;
            }
        """)
        quit_btn.clicked.connect(self.close)
        sidebar_layout.addWidget(quit_btn)
        
        # Pied de page de la barre latérale avec numéro de version
        version_lbl = QLabel(f"v{APP_VERSION}")
        version_lbl.setAlignment(Qt.AlignCenter)
        version_lbl.setStyleSheet("""
            QLabel {
                color: #94A3B8;
                font-size: 11px;
                font-weight: 500;
                margin-top: 10px;
            }
        """)
        sidebar_layout.addWidget(version_lbl)
        
        main_layout.addWidget(sidebar)

        # 2. CONTENU PRINCIPAL (Right Area)
        right_panel = QFrame()
        right_panel.setStyleSheet("QFrame { background-color: #F8FAFC; border: none; }")
        right_panel_layout = QVBoxLayout(right_panel)
        right_panel_layout.setContentsMargins(0, 0, 0, 0)
        right_panel_layout.setSpacing(0)

        # En-tête de l'application (Header)
        header = QFrame()
        header.setStyleSheet("""
            QFrame {
                background-color: #FFFFFF;
                border-bottom: 1px solid #E2E8F0;
                min-height: 60px;
                max-height: 60px;
            }
        """)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(25, 0, 25, 0)

        app_title = QLabel(f"ALJ Escalade Manager — Saison {get_active_season()}")
        app_title.setStyleSheet("font-size: 14px; font-weight: 600; color: #1E293B;")
        header_layout.addWidget(app_title)

        header_layout.addStretch()

        # Statuts de connexion en pastilles discrètes
        gmail_user = SecretStore.get_secret("GMAIL_USER_EMAIL")
        status_text = "🟢 Drive Connecté"
        if gmail_user:
            status_text += f" ({gmail_user.strip()})"
        self.drive_status = QLabel(status_text)
        self.drive_status.setStyleSheet("color: #16A34A; font-size: 12px; font-weight: 500; margin-right: 15px;")
        header_layout.addWidget(self.drive_status)

        # Action 1 : Bouton "update BDD" (Bleu Ciel) - Nouveau !
        self.drive_sync_btn = QPushButton("update BDD")
        self.drive_sync_btn.setCursor(Qt.PointingHandCursor)
        self.drive_sync_btn.setStyleSheet("""
            QPushButton {
                background-color: #0EA5E9;
                color: #FFFFFF;
                border: none;
                border-radius: 6px;
                padding: 6px 15px;
                font-weight: bold;
                font-size: 12px;
                margin-right: 8px;
            }
            QPushButton:hover {
                background-color: #0284C7;
            }
            QPushButton:disabled {
                background-color: #94A3B8;
            }
        """)
        self.drive_sync_btn.clicked.connect(self.start_drive_sync_workflow)
        header_layout.addWidget(self.drive_sync_btn)

        # Action 1.5 : Bouton "Sauvegarder sur Drive" (Orange) - Nouveau !
        self.drive_upload_btn = QPushButton("Sauvegarder sur Drive")
        self.drive_upload_btn.setCursor(Qt.PointingHandCursor)
        self.drive_upload_btn.setStyleSheet("""
            QPushButton {
                background-color: #F59E0B;
                color: #FFFFFF;
                border: none;
                border-radius: 6px;
                padding: 6px 15px;
                font-weight: bold;
                font-size: 12px;
                margin-right: 8px;
            }
            QPushButton:hover {
                background-color: #D97706;
            }
            QPushButton:disabled {
                background-color: #94A3B8;
            }
        """)
        self.drive_upload_btn.clicked.connect(self.start_drive_upload_workflow)
        header_layout.addWidget(self.drive_upload_btn)

        # Action 2 : Bouton "Synchroniser et merger avec HelloAsso" (Bleu Action) - Renommé !
        self.sync_btn = QPushButton("Synchroniser et merger avec HelloAsso")
        self.sync_btn.setCursor(Qt.PointingHandCursor)
        self.sync_btn.setStyleSheet("""
            QPushButton {
                background-color: #2563EB;
                color: #FFFFFF;
                border: none;
                border-radius: 6px;
                padding: 6px 15px;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #1D4ED8;
            }
            QPushButton:disabled {
                background-color: #94A3B8;
            }
        """)
        self.sync_btn.clicked.connect(self.start_sync_workflow)
        header_layout.addWidget(self.sync_btn)

        right_panel_layout.addWidget(header)

        # Pages superposées (Stacked Widget)
        self.stacked_widget = QStackedWidget()
        self.stacked_widget.addWidget(MembersPage())         # Index 0
        self.stacked_widget.addWidget(DocumentsPage())       # Index 1
        self.stacked_widget.addWidget(CommunicationsPage())  # Index 2
        self.stacked_widget.addWidget(ExportsPage())         # Index 3
        self.stacked_widget.addWidget(ImportDataPage())      # Index 4
        self.stacked_widget.addWidget(GroupsPage())          # Index 5
        self.stacked_widget.addWidget(GmailContactPage())     # Index 6
        self.stacked_widget.addWidget(ReportsPage())         # Index 7 (La page Outils d'Analyses !)
        self.stacked_widget.addWidget(SettingsPage())        # Index 8
        self.stacked_widget.addWidget(HelpPage())            # Index 9
        self.stacked_widget.addWidget(LogsPage())            # Index 10

        right_panel_layout.addWidget(self.stacked_widget)

        # Raccourci « enveloppe » : bouton ✉️ de la fiche adhérent vers Communication filtrée (Nouveau !)
        self.members_page = self.stacked_widget.widget(0)
        self.members_page.email_requested.connect(self.open_communications_for_member)

        # Pied de page unifié pour tout le site (Nouveau !)
        footer = QFrame()
        footer.setStyleSheet("""
            QFrame {
                background-color: #FFFFFF;
                border-top: 1px solid #E2E8F0;
                min-height: 35px;
                max-height: 35px;
            }
        """)
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(25, 0, 25, 0)
        
        footer_text = QLabel(f"ALJ Escalade — Section Escalade Amicale Laïque de Jonage | Version {APP_VERSION}")
        footer_text.setStyleSheet("font-size: 11px; color: #64748B; font-weight: 500;")
        footer_layout.addWidget(footer_text)
        
        footer_layout.addStretch()
        
        # Afficher la date de dernière sauvegarde de la BDD sur Google Drive !
        self.last_sync_lbl = QLabel()
        self.last_sync_lbl.setStyleSheet("font-size: 11px; color: #059669; font-weight: 600;")
        self.update_last_sync_footer_label() # Mettre à jour le texte
        footer_layout.addWidget(self.last_sync_lbl)
        
        right_panel_layout.addWidget(footer)

        main_layout.addWidget(right_panel)

    def on_nav_changed(self, index: int, force_reload=False):
        """Met à jour l'affichage de la page active et rafraîchit les données si nécessaire."""
        self.stacked_widget.setCurrentIndex(index)
        page = self.stacked_widget.currentWidget()
        
        # Mettre à jour dynamiquement l'adresse e-mail de connexion affichée dans l'en-tête
        gmail_user = SecretStore.get_secret("GMAIL_USER_EMAIL")
        status_text = "🟢 Drive Connecté"
        if gmail_user:
            status_text += f" ({gmail_user.strip()})"
        self.drive_status.setText(status_text)

        # Actualiser les stats et listes si l'on revient sur l'accueil, adhérents ou logs
        if index == 7 and hasattr(page, "load_and_calculate_stats"):
            page.load_and_calculate_stats(force_reload=force_reload)
        elif index == 0 and hasattr(page, "load_members_from_repository"):
            page.load_members_from_repository(force_reload=force_reload)
        elif index == 10 and hasattr(page, "load_logs"):
            page.load_logs()

    def open_communications_for_member(self, member):
        """Bouton ✉️ de la fiche adhérent : bascule sur la page Communication avec la
        recherche préremplie sur ce membre (même saison que l'onglet Adhérents)."""
        members_page = self.stacked_widget.widget(0)
        communications_page = self.stacked_widget.widget(2)

        # Aligner la saison de Communication sur celle de l'onglet Adhérents
        if hasattr(members_page, "season_filter") and hasattr(communications_page, "season_filter"):
            if communications_page.season_filter.currentIndex() != members_page.season_filter.currentIndex():
                communications_page.season_filter.setCurrentIndex(members_page.season_filter.currentIndex())

        if hasattr(communications_page, "focus_on_member"):
            communications_page.focus_on_member(member)

        # Basculer l'affichage sur la page Communication (+ bouton de navigation coché)
        self.nav_buttons[2].setChecked(True)
        self.on_nav_changed(2)

    def start_drive_sync_workflow(self):
        """Déclenche le téléchargement du tableur de référence depuis Google Drive en tâche de fond."""
        self.drive_sync_btn.setEnabled(False)
        self.drive_sync_btn.setText("🔄 update BDD...")
        self.sync_btn.setEnabled(False)

        drive_db_id = SecretStore.get_secret("GOOGLE_DRIVE_DB_ID")
        
        print("🔄 [MAIN] Lancement du worker de téléchargement seul depuis Google Drive...")
        self.drive_worker = DownloadDriveFileWorker(drive_db_id)
        self.drive_worker.progress.connect(self.on_drive_sync_progress)
        self.drive_worker.finished.connect(self.on_drive_sync_finished)
        self.drive_worker.start()

    def on_drive_sync_progress(self, message: str, percent: int):
        print(f"🔄 [DRIVE_SYNC] {percent}% - {message}")

    def on_drive_sync_finished(self, success: bool, result_message: str):
        self.drive_sync_btn.setEnabled(True)
        self.drive_sync_btn.setText("update BDD")
        self.sync_btn.setEnabled(True)

        if success:
            import datetime
            now_str = datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S")
            SecretStore.set_secret("LAST_GOOGLE_DRIVE_IMPORT", now_str)
            self.update_last_sync_footer_label()

            QMessageBox.information(
                self,
                "Téléchargement Google Drive",
                "Le fichier d'adhérents le plus récent a été récupéré avec succès depuis Google Drive !"
            )
            self.on_nav_changed(self.stacked_widget.currentIndex(), force_reload=True)
        else:
            QMessageBox.critical(
                self,
                "Échec Google Drive",
                f"Le téléchargement Google Drive a échoué :\n\n{result_message}"
            )

    def start_drive_upload_workflow(self):
        """Déclenche le téléversement de la base SQLite locale vers Google Drive en arrière-plan."""
        self.drive_upload_btn.setEnabled(False)
        self.drive_upload_btn.setText("🔄 Envoi...")
        self.drive_sync_btn.setEnabled(False)
        self.sync_btn.setEnabled(False)

        print("📤 [MAIN] Lancement du worker de sauvegarde SQLite vers Google Drive...")
        from presentation.workers import UploadDriveFileWorker
        self.upload_worker = UploadDriveFileWorker()
        self.upload_worker.progress.connect(self.on_drive_upload_progress)
        self.upload_worker.finished.connect(self.on_drive_upload_finished)
        self.upload_worker.start()

    def on_drive_upload_progress(self, message: str, percent: int):
        print(f"📤 [DRIVE_UPLOAD] {percent}% - {message}")

    def on_drive_upload_finished(self, success: bool, result_message: str):
        self.drive_upload_btn.setEnabled(True)
        self.drive_upload_btn.setText("Sauvegarder sur Drive")
        self.drive_sync_btn.setEnabled(True)
        self.sync_btn.setEnabled(True)

        if success:
            import datetime
            now_str = datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S")
            SecretStore.set_secret("LAST_GOOGLE_DRIVE_SYNC", now_str)
            self.update_last_sync_footer_label()

            QMessageBox.information(
                self,
                "Sauvegarde Google Drive",
                "Votre base de données SQLite locale a été téléversée et sauvegardée avec succès sur Google Drive !"
            )
        else:
            QMessageBox.critical(
                self,
                "Échec de Sauvegarde",
                f"La sauvegarde sur Google Drive a échoué :\n\n{result_message}"
            )

    def start_sync_workflow(self):
        """Déclenche la synchronisation HelloAsso & Google Drive en arrière-plan."""
        self.sync_btn.setEnabled(False)
        self.sync_btn.setText("🔄 Synchro...")
        self.drive_sync_btn.setEnabled(False)
        
        drive_file_id = SecretStore.get_secret("GOOGLE_DRIVE_FILE_ID")
        campaign_slug = SecretStore.get_secret("CAMPAIGN_SLUG") or f"adhesion-escalade-{get_active_season()}-amicale-laique-escalade"
        
        print("🔄 [MAIN] Lancement du worker de synchronisation HelloAsso...")
        
        self.sync_worker = SyncHelloAssoWorker(drive_file_id, campaign_slug)
        self.sync_worker.progress.connect(self.on_sync_progress)
        self.sync_worker.finished.connect(self.on_sync_finished)
        self.sync_worker.start()

    def on_sync_progress(self, message: str, percent: int):
        print(f"🔄 [SYNC] {percent}% - {message}")

    @staticmethod
    def _apply_sync_dialog_size(box: QMessageBox, has_tables: bool):
        """Élargit la fenêtre de résultat de la synchronisation quand elle affiche des
        tableaux (nouveaux membres / conflits d'âge) : sans cela, le QMessageBox se
        réduit à son minimum et les colonnes se tassent sur quelques caractères.
        La poignée de redimensionnement est activée pour laisser la main à l'utilisateur."""
        if not has_tables:
            return
        from PySide6.QtGui import QGuiApplication
        screen_geo = QGuiApplication.primaryScreen().availableGeometry()
        box.setMinimumWidth(min(980, int(screen_geo.width() * 0.80)))
        box.setSizeGripEnabled(True)

    def on_sync_finished(self, success: bool, result_message: str):
        self.sync_btn.setEnabled(True)
        self.sync_btn.setText("Synchroniser et merger avec HelloAsso")
        self.drive_sync_btn.setEnabled(True)
        
        if success:
            import datetime
            now_str = datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S")
            SecretStore.set_secret("LAST_HELLOASSO_SYNC", now_str)
            SecretStore.set_secret("LAST_GOOGLE_DRIVE_SYNC", now_str) # Car HelloAsso sync téléverse aussi vers Drive !

            import json
            # Vérifier s'il y a des données de nouveaux adhérents + conflits d'âge
            new_members = []
            age_conflicts = []
            if result_message.startswith("SUCCESS_DATA:"):
                try:
                    data_str = result_message.split("SUCCESS_DATA:", 1)[1]
                    payload = json.loads(data_str)
                    if isinstance(payload, dict):
                        new_members = payload.get("new_members", [])
                        age_conflicts = payload.get("age_conflicts", [])
                    elif isinstance(payload, list):
                        new_members = payload
                except Exception:
                    pass
            
            # Formater l'affichage du pop-up de confirmation sous forme de tableau HTML
            total_added = len(new_members)
            if total_added > 0:
                html_msg = (
                    f"<h3><b>🎉 Synchronisation Réussie !</b></h3>"
                    f"<p>La base d'adhérents a été actualisée de manière transparente.</p>"
                    f"<p><b>📊 {total_added} nouveau(x) membre(s) ajouté(s) dans l'Excel :</b></p>"
                    f"<table border='1' cellpadding='6' cellspacing='0' style='border-collapse: collapse; border: 1px solid #CBD5E1; font-family: Segoe UI; font-size: 11px;'>"
                    f"<tr bgcolor='#163A5F' style='color: white; font-weight: bold;'>"
                    f"  <th>Nom</th>"
                    f"  <th>Prénom</th>"
                    f"  <th>Date d'inscription</th>"
                    f"  <th>Alerte</th>"
                    f"</tr>"
                )
                for m in new_members:
                    warning_txt = str(m.get('warning') or '').strip()
                    if warning_txt:
                        alerte_cell = (
                            f"<td align='center' bgcolor='#FEF3C7' style='color: #B45309;' title=\"{warning_txt}\">"
                            f"⚠️ {warning_txt}</td>"
                        )
                    else:
                        alerte_cell = "<td align='center'>—</td>"
                    html_msg += (
                        f"<tr>"
                        f"  <td><b>{m.get('last_name', '')}</b></td>"
                        f"  <td>{m.get('first_name', '')}</td>"
                        f"  <td align='center'>{m.get('order_date', '')}</td>"
                        f"  {alerte_cell}"
                        f"</tr>"
                    )
                html_msg += "</table>"
            else:
                html_msg = (
                    "<h3><b>✔️ Synchronisation Réussie !</b></h3>"
                    "<p>La base d'adhérents est déjà entièrement à jour.</p>"
                    "<p><b>📊 0 nouvelle ligne ajoutée.</b></p>"
            )
            
            # Bloc d'avertissement en cas de conflit d'âge sur les nouvelles inscriptions
            # (adulte dans un groupe enfants/collège/lycée ou année de naissance hors bornes)
            if age_conflicts:
                html_msg += (
                    f"<h3 style='color: #B45309; margin-top: 15px;'><b>⚠️ Conflits d'âge détectés ({len(age_conflicts)})</b></h3>"
                    f"<p>Ces nouvelles inscriptions ne respectent pas les bornes de date de naissance du groupe "
                    f"(par exemple : un adulte au 01/09 de la saison inscrit dans un groupe enfants / collège / lycée). "
                    f"Merci de vérifier ces dossiers dans l'onglet <b>Adhérents</b>.</p>"
                    f"<table border='1' cellpadding='6' cellspacing='0' style='border-collapse: collapse; border: 1px solid #D97706; font-family: Segoe UI; font-size: 11px;'>"
                    f"<tr bgcolor='#D97706' style='color: white; font-weight: bold;'>"
                    f"  <th>Nom</th>"
                    f"  <th>Prénom</th>"
                    f"  <th>Tarif</th>"
                    f"  <th>Problème détecté</th>"
                    f"</tr>"
                )
                for c in age_conflicts:
                    problems = "<br>".join(f"• {msg}" for msg in c.get("messages", []))
                    html_msg += (
                        f"<tr bgcolor='#FEF3C7'>"
                        f"  <td><b>{c.get('last_name', '')}</b></td>"
                        f"  <td>{c.get('first_name', '')}</td>"
                        f"  <td>{c.get('tarif_name', '')}</td>"
                        f"  <td style='color: #B45309;'>{problems}</td>"
                        f"</tr>"
                    )
                html_msg += "</table>"
                
            # Créer un QMessageBox personnalisé pour intégrer le bouton d'ouverture web Google Drive
            box = QMessageBox(self)
            box.setWindowTitle("Synchronisation ALJ Escalade")
            box.setText(html_msg)
            box.setTextFormat(Qt.TextFormat.RichText)
            # Fenêtre élargie quand des tableaux sont affichés : les colonnes
            # « Date d'inscription » et « Alerte » restent lisibles sans se tasser.
            self._apply_sync_dialog_size(box, bool(new_members or age_conflicts))
            if age_conflicts:
                box.setIcon(QMessageBox.Icon.Warning)
            
            ok_btn = box.addButton("OK", QMessageBox.ButtonRole.AcceptRole)
            
            drive_file_id = SecretStore.get_secret("GOOGLE_DRIVE_FILE_ID")
            open_btn = None
            if drive_file_id:
                open_btn = box.addButton("🌐 Ouvrir sur Google Drive", QMessageBox.ButtonRole.ActionRole)
                
            box.exec()
            
            if open_btn and box.clickedButton() == open_btn:
                url = f"https://drive.google.com/file/d/{drive_file_id}/view"
                import webbrowser
                try:
                    webbrowser.open(url)
                except Exception:
                    pass
                    
            # Actualiser la page active pour refléter les nouvelles données immédiatement en vidant le cache
            self.on_nav_changed(self.stacked_widget.currentIndex(), force_reload=True)
        else:
            QMessageBox.critical(
                self, 
                "Échec de Synchronisation", 
                f"La synchronisation a échoué :\n\n{result_message}"
            )

    def load_initial_data_async(self):
        """Lance le chargement asynchrone des données locales au démarrage pour accélérer l'ouverture de l'application."""
        # Désactiver temporairement les boutons de navigation
        for btn in self.nav_buttons:
            btn.setEnabled(False)
        self.sync_btn.setEnabled(False)
        self.drive_sync_btn.setEnabled(False)
        self.drive_upload_btn.setEnabled(False)
        
        # Créer un dialogue de chargement propre et moderne
        self.loading_dialog = QMessageBox(self)
        self.loading_dialog.setWindowTitle("Initialisation")
        self.loading_dialog.setText("🚀 <b>ALJ Escalade Manager</b><br><br>Chargement en cours...")
        self.loading_dialog.setIcon(QMessageBox.Information)
        self.loading_dialog.setStandardButtons(QMessageBox.Ok)
        
        # Désactiver le bouton OK pour empêcher la fermeture prématurée pendant le chargement
        ok_btn = self.loading_dialog.button(QMessageBox.Ok)
        if ok_btn:
            ok_btn.setEnabled(False)
        
        # Lancer le worker de chargement
        from presentation.workers import LocalDataLoaderWorker
        self.loader_worker = LocalDataLoaderWorker()
        self.loader_worker.progress.connect(self.on_loader_progress)
        self.loader_worker.finished.connect(self.on_loader_finished)
        self.loader_worker.start()
        
        # Afficher le dialogue de manière non-bloquante
        self.loading_dialog.show()

    def on_loader_progress(self, message: str, percent: int):
        # Afficher la progression dans la console, mais ne pas modifier le texte du dialogue
        # pour éviter d'avoir du texte entre "chargement en cours" et "chargement terminé"
        print(f"⏳ [STARTUP PROGRESS] {percent}% - {message}")

    def on_loader_finished(self, success: bool, members_list: list, error_msg: str):
        # Réactiver les boutons
        for btn in self.nav_buttons:
            btn.setEnabled(True)
        self.sync_btn.setEnabled(True)
        self.drive_sync_btn.setEnabled(True)
        self.drive_upload_btn.setEnabled(True)
        
        if success and members_list:
            # Distribuer les données aux pages de l'application
            members_page = self.stacked_widget.widget(0) # Index 0 (Adhérents)
            documents_page = self.stacked_widget.widget(1) # Index 1 (Attestations)
            communications_page = self.stacked_widget.widget(2) # Index 2 (Communications)
            reports_page = self.stacked_widget.widget(7) # Index 7 (Outils)
            
            # Injecter la liste de membres préchargée
            members_page.members_list = members_list
            reports_page.members_list = members_list
            documents_page.load_members(members_list)
            communications_page.load_members(members_list)
            
            # Actualiser la vue d'accueil / outils (statistiques ou bannière)
            if hasattr(reports_page, "calculate_and_display_stats"):
                reports_page.calculate_and_display_stats()
            elif hasattr(reports_page, "load_and_calculate_stats"):
                reports_page.load_and_calculate_stats()
            
            # Mettre à jour la table des adhérents
            members_page.base_model.update_data(members_list)
            members_page.update_counter(len(members_list))
            
            # Actualiser les filtres (tarifs + statuts dynamiques) sur la page des membres
            members_page.notify_members_reloaded()
            
            print(f"✅ [SYSTEM] {len(members_list)} adhérents chargés de façon asynchrone au démarrage.")
            
            # Mettre à jour le texte du dialogue de chargement et ACTIVER le bouton OK pour fermer !
            if hasattr(self, 'loading_dialog'):
                self.loading_dialog.setText("🚀 <b>ALJ Escalade Manager</b><br><br>✅ Chargement terminé !")
                ok_btn = self.loading_dialog.button(QMessageBox.Ok)
                if ok_btn:
                    ok_btn.setEnabled(True)
        else:
            # Fermer le dialogue d'attente s'il y a une erreur
            if hasattr(self, 'loading_dialog'):
                self.loading_dialog.close()
                
            # S'il n'y a pas de fichier ou en cas d'erreur
            QMessageBox.warning(
                self,
                "Données locales absentes",
                f"Aucun fichier d'adhérents local n'a pu être chargé au démarrage : {error_msg}\n\n"
                "Veuillez cliquer sur le bouton 'update BDD' pour récupérer la base d'adhérents."
            )

    def update_last_sync_footer_label(self):
        """Met à jour l'étiquette de dernière sauvegarde et de dernier import de la BDD SQLite sur le Google Drive dans le pied de page."""
        last_sync = SecretStore.get_secret("LAST_GOOGLE_DRIVE_SYNC")
        last_import = SecretStore.get_secret("LAST_GOOGLE_DRIVE_IMPORT")
        
        sync_text = f"☁️ Dernière sauvegarde Drive : {last_sync.strip()}" if last_sync else "☁️ Aucune sauvegarde Drive"
        import_text = f"📥 Dernier import BDD : {last_import.strip()}" if last_import else "📥 Aucun import Drive"
        
        self.last_sync_lbl.setText(f"{import_text}  |  {sync_text}")

    @staticmethod
    def get_sidebar_button_style() -> str:
        return """
            QPushButton {
                color: #CBD5E1;
                background-color: transparent;
                border: none;
                border-radius: 6px;
                padding: 10px 15px;
                font-size: 13px;
                text-align: left;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: #1E293B;
                color: #FFFFFF;
            }
            QPushButton:checked {
                background-color: #2563EB;
                color: #FFFFFF;
                font-weight: bold;
            }
        """

    def closeEvent(self, event):
        """Déclenché lors de la fermeture de l'application pour archiver et synchroniser vers le Drive."""
        from PySide6.QtWidgets import QProgressDialog
        from PySide6.QtCore import QCoreApplication
        import os
        
        # Créer un indicateur d'attente
        progress = QProgressDialog("Sauvegarde locale et synchronisation Google Drive en cours...", None, 0, 0, self)
        progress.setWindowTitle("Fermeture de l'application")
        progress.setWindowModality(Qt.WindowModal)
        progress.setCancelButton(None) # Pas de bouton d'annulation
        progress.setMinimumDuration(0)
        progress.show()
        QCoreApplication.processEvents() # Forcer l'IHM à s'afficher
        
        try:
            from infrastructure.sqlite_repository import SqliteRepository
            from infrastructure.google_drive_client import GoogleDriveClient
            from infrastructure.secret_store import SecretStore
            import datetime
            
            print("\n================================================================================")
            print("🚪 [FERMETURE] Début de la procédure d'archivage et de synchronisation finale...")
            print("================================================================================")
            
            # Étape 1 : Créer une archive locale saine
            progress.setLabelText("Étape 1/2 : Création de la sauvegarde locale...")
            QCoreApplication.processEvents()
            backup_file = SqliteRepository.create_db_backup()
            if backup_file:
                print(f"✅ [FERMETURE] Point de restauration local créé : {backup_file}")
            
            # Étape 2 : Sauvegarder la BDD sur Google Drive
            db_drive_id = SecretStore.get_secret("GOOGLE_DRIVE_DB_ID")
            db_local_path = SqliteRepository.get_db_path()
            
            if db_drive_id and os.path.exists(db_local_path):
                current_hash = SqliteRepository.get_file_hash()
                startup_hash = getattr(SqliteRepository, "_startup_db_hash", None)
                
                if startup_hash and current_hash == startup_hash:
                    print("ℹ️ [FERMETURE] Aucun changement détecté dans la base SQLite locale. Téléversement Google Drive ignoré.")
                    progress.setLabelText("Étape 2/2 : Téléversement Google Drive non requis (base inchangée).")
                    QCoreApplication.processEvents()
                else:
                    progress.setLabelText("Étape 2/2 : Téléversement de la base de données vers Google Drive...")
                    QCoreApplication.processEvents()
                    
                    print(f"📤 [FERMETURE] Envoi du fichier database.db vers Google Drive (ID : {db_drive_id})...")
                    success = GoogleDriveClient.upload_file(db_drive_id, db_local_path)
                    if success:
                        now_str = datetime.datetime.now().strftime("%d/%m/%Y %H:%M")
                        SecretStore.set_secret("LAST_GOOGLE_DRIVE_SYNC", now_str)
                        print(f"✅ [FERMETURE] Base SQLite sauvegardée avec succès sur Google Drive à {now_str}.")
                    else:
                        print("⚠️ [FERMETURE] Échec de la sauvegarde sur Google Drive lors de la fermeture.")
            else:
                print("⚠️ [FERMETURE] Aucun ID de BDD Drive configuré ou base locale absente. Pas d'envoi vers le Drive.")
                
            print("================================================================================\n")
            
        except Exception as e:
            print(f"❌ [FERMETURE] Erreur lors de la procédure de sauvegarde finale : {e}")
        finally:
            progress.close()
            event.accept()
