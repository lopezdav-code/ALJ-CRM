from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QLineEdit, QPushButton, QFrame, QHBoxLayout, QMessageBox
from PySide6.QtCore import Qt
from infrastructure.secret_store import SecretStore

class SettingsPage(QWidget):
    """
    Page des paramètres généraux de l'application ALJ Escalade.
    Permet de lire et de sauvegarder de manière sécurisée les clés d'API (Lot 2 & 5).
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.filename_labels = {}
        self.init_ui()
        self.load_settings()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(20)

        # En-tête
        title = QLabel("Paramètres de l'Application")
        title.setStyleSheet("font-size: 24px; font-weight: bold; color: #1E293B;")
        layout.addWidget(title)

        # Conteneur des configurations
        form_frame = QFrame()
        form_frame.setStyleSheet("""
            QFrame {
                background-color: #FFFFFF;
                border: 1px solid #E2E8F0;
                border-radius: 8px;
                padding: 20px;
            }
        """)
        self.form_layout = QVBoxLayout(form_frame)
        self.form_layout.setSpacing(15)

        # Liste des paramètres
        self.inputs = {}
        settings_fields = [
            ("Saison active (ex: 2026-2027) :", "ACTIVE_SEASON", "2026-2027"),
            ("HelloAsso Client ID :", "HELLOASSO_CLIENT_ID", ""),
            ("Google Drive SQLite DB ID (Base d'adhérents) :", "GOOGLE_DRIVE_DB_ID", ""),
            ("Google Cloud Client ID :", "GMAIL_CLIENT_ID", ""),
            ("Adresse Expéditeur Gmail :", "GMAIL_USER_EMAIL", "")
        ]

        for label_text, key, placeholder in settings_fields:
            self.form_layout.addWidget(QLabel(label_text))
            
            # Layout horizontal pour aligner le champ d'écriture et d'éventuels boutons d'actions rapides
            field_layout = QHBoxLayout()
            field_layout.setSpacing(8)

            line_edit = QLineEdit()
            line_edit.setPlaceholderText(placeholder)
            line_edit.setStyleSheet("""
                QLineEdit {
                    background-color: #FFFFFF;
                    border: 1px solid #CBD5E1;
                    border-radius: 6px;
                    padding: 8px;
                    color: #1E293B;
                }
            """)
            # Masquer le Client ID pour la sécurité
            if "CLIENT_ID" in key:
                line_edit.setEchoMode(QLineEdit.Password)
                
            field_layout.addWidget(line_edit)
            self.inputs[key] = line_edit

            # Ajouter le bouton "🌐 Ouvrir sur le Web" pour le champ Google Drive BDD
            if key == "GOOGLE_DRIVE_DB_ID":
                open_btn = QPushButton("🌐 Ouvrir sur le Web")
                open_btn.setCursor(Qt.PointingHandCursor)
                open_btn.setStyleSheet("""
                    QPushButton {
                        background-color: #2563EB;
                        color: #FFFFFF;
                        border: none;
                        border-radius: 6px;
                        padding: 8px 15px;
                        font-weight: bold;
                        font-size: 12px;
                    }
                    QPushButton:hover {
                        background-color: #1D4ED8;
                    }
                """)
                open_btn.clicked.connect(lambda checked=False, k=key: self.open_drive_file_in_browser(k))
                field_layout.addWidget(open_btn)

            self.form_layout.addLayout(field_layout)

            # Label d'information sur le nom du fichier Google Drive BDD
            if key == "GOOGLE_DRIVE_DB_ID":
                name_lbl = QLabel("📂 Nom du fichier sur Google Drive : (ID vide ou non chargé)")
                name_lbl.setStyleSheet("font-size: 11px; font-style: italic; color: #64748B; margin-bottom: 5px;")
                self.filename_labels[key] = name_lbl
                self.form_layout.addWidget(name_lbl)

        # Layout horizontal pour les boutons d'actions en bas de formulaire (évite l'étirement excessif)
        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(12)
        buttons_layout.setAlignment(Qt.AlignLeft)

        # Bouton Enregistrer
        self.save_btn = QPushButton("💾 Enregistrer les paramètres")
        self.save_btn.setCursor(Qt.PointingHandCursor)
        self.save_btn.setStyleSheet("""
            QPushButton {
                background-color: #10B981;
                color: #FFFFFF;
                border: none;
                border-radius: 6px;
                padding: 10px 22px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #059669;
            }
        """)
        self.save_btn.clicked.connect(self.save_settings)
        buttons_layout.addWidget(self.save_btn)

        # Bouton Connexion Google OAuth2
        self.google_btn = QPushButton("🔑 Connexion Google (OAuth2)")
        self.google_btn.setCursor(Qt.PointingHandCursor)
        self.google_btn.setStyleSheet("""
            QPushButton {
                background-color: #3B82F6;
                color: #FFFFFF;
                border: none;
                border-radius: 6px;
                padding: 10px 22px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #2563EB;
            }
        """)
        self.google_btn.clicked.connect(self.authenticate_google)
        buttons_layout.addWidget(self.google_btn)

        # Bouton Déconnexion Google
        self.google_logout_btn = QPushButton("🔌 Déconnexion Google")
        self.google_logout_btn.setCursor(Qt.PointingHandCursor)
        self.google_logout_btn.setStyleSheet("""
            QPushButton {
                background-color: #EF4444;
                color: #FFFFFF;
                border: none;
                border-radius: 6px;
                padding: 10px 22px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #DC2626;
            }
        """)
        self.google_logout_btn.clicked.connect(self.disconnect_google)
        buttons_layout.addWidget(self.google_logout_btn)

        # Bouton Tester Connexion Google
        self.google_test_btn = QPushButton("🔍 Tester Connexion Google")
        self.google_test_btn.setCursor(Qt.PointingHandCursor)
        self.google_test_btn.setStyleSheet("""
            QPushButton {
                background-color: #10B981;
                color: #FFFFFF;
                border: none;
                border-radius: 6px;
                padding: 10px 22px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #059669;
            }
        """)
        self.google_test_btn.clicked.connect(self.test_google_services)
        buttons_layout.addWidget(self.google_test_btn)

        # Bouton Envoyer la base de données SQLite locale sur le Google Drive
        self.upload_db_btn = QPushButton("📤 Envoyer BDD locale sur Drive")
        self.upload_db_btn.setCursor(Qt.PointingHandCursor)
        self.upload_db_btn.setStyleSheet("""
            QPushButton {
                background-color: #F59E0B;
                color: #FFFFFF;
                border: none;
                border-radius: 6px;
                padding: 10px 22px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #D97706;
            }
        """)
        self.upload_db_btn.clicked.connect(self.upload_db_to_drive)
        buttons_layout.addWidget(self.upload_db_btn)

        self.form_layout.addLayout(buttons_layout)

        layout.addWidget(form_frame)

        # Conteneur pour l'état des fichiers locaux
        status_frame = QFrame()
        status_frame.setStyleSheet("""
            QFrame {
                background-color: #FFFFFF;
                border: 1px solid #E2E8F0;
                border-radius: 8px;
                padding: 15px 20px;
                margin-top: 15px;
            }
        """)
        status_layout = QVBoxLayout(status_frame)
        status_layout.setSpacing(10)

        status_title = QLabel("📊 Disponibilité & Lisibilité des Fichiers Locaux")
        status_title.setStyleSheet("font-size: 14px; font-weight: bold; color: #1E293B;")
        status_layout.addWidget(status_title)

        # Label base SQLite
        self.db_status_lbl = QLabel("📁 database.db : (Analyse en cours...)")
        self.db_status_lbl.setStyleSheet("font-size: 13px; font-weight: bold; color: #64748B;")
        status_layout.addWidget(self.db_status_lbl)

        # Label Excel Adhésions
        self.excel_status_lbl = QLabel("📊 Fichier Excel : (Analyse en cours...)")
        self.excel_status_lbl.setStyleSheet("font-size: 13px; font-weight: bold; color: #64748B;")
        status_layout.addWidget(self.excel_status_lbl)

        # Bouton de rafraîchissement
        refresh_status_btn = QPushButton("🔄 Rafraîchir l'état des fichiers")
        refresh_status_btn.setCursor(Qt.PointingHandCursor)
        refresh_status_btn.setStyleSheet("""
            QPushButton {
                background-color: #F8FAFC;
                color: #334155;
                border: 1px solid #CBD5E1;
                border-radius: 6px;
                padding: 8px 15px;
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #E2E8F0;
            }
        """)
        refresh_status_btn.clicked.connect(self.check_local_files_status)
        status_layout.addWidget(refresh_status_btn)

        layout.addWidget(status_frame)
        layout.addStretch()

    def upload_db_to_drive(self):
        """Téléverse la base de données locale vers Google Drive (mise à jour ou création)."""
        from infrastructure.sqlite_repository import SqliteRepository
        from infrastructure.google_drive_client import GoogleDriveClient
        import os
        
        db_local_path = SqliteRepository.get_db_path()
        if not os.path.exists(db_local_path):
            QMessageBox.critical(
                self,
                "Erreur",
                "Le fichier de base de données locale 'database.db' est introuvable."
            )
            return

        db_drive_id = SecretStore.get_secret("GOOGLE_DRIVE_DB_ID")
        
        if db_drive_id:
            # Demander s'il souhaite écraser le fichier existant ou en créer un nouveau
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("Envoi vers Google Drive")
            msg_box.setText("Une base de données SQLite existe déjà sur votre Google Drive.")
            msg_box.setInformativeText("Que souhaitez-vous faire ?")
            
            btn_overwrite = msg_box.addButton("Écraser la base existante sur le Drive", QMessageBox.AcceptRole)
            btn_create_new = msg_box.addButton("Créer un nouveau fichier sur le Drive", QMessageBox.ActionRole)
            btn_cancel = msg_box.addButton("Annuler", QMessageBox.RejectRole)
            
            msg_box.exec()
            clicked = msg_box.clickedButton()
            
            if clicked == btn_cancel:
                return
            elif clicked == btn_overwrite:
                self.upload_db_btn.setEnabled(False)
                self.upload_db_btn.setText("🔄 Téléversement...")
                
                success = GoogleDriveClient.upload_file(db_drive_id, db_local_path)
                
                self.upload_db_btn.setEnabled(True)
                self.upload_db_btn.setText("📤 Envoyer BDD locale sur Drive")
                
                if success:
                    QMessageBox.information(self, "Succès", "La base de données existante sur Google Drive a été mise à jour avec succès !")
                else:
                    QMessageBox.critical(self, "Échec", "Le téléversement de mise à jour vers Google Drive a échoué.")
                return
            
        # Création d'un nouveau fichier (ou si pas de db_drive_id présent)
        self.upload_db_btn.setEnabled(False)
        self.upload_db_btn.setText("🔄 Création du fichier...")
        
        new_id = GoogleDriveClient.create_file("database.db", db_local_path)
        
        self.upload_db_btn.setEnabled(True)
        self.upload_db_btn.setText("📤 Envoyer BDD locale sur Drive")
        
        if new_id:
            SecretStore.set_secret("GOOGLE_DRIVE_DB_ID", new_id)
            self.load_settings() # Recharger l'affichage
            QMessageBox.information(
                self,
                "Succès",
                f"Un nouveau fichier de base de données 'database.db' a été créé sur votre Google Drive !\n\n"
                f"ID unique généré : {new_id}\n\n"
                "Le fichier de configuration .env/Keyring a été automatiquement mis à jour."
            )
        else:
            QMessageBox.critical(self, "Échec", "La création du nouveau fichier SQLite sur Google Drive a échoué.")

    def authenticate_google(self):
        """Lance l'assistant d'authentification Google dans un thread d'arrière-plan."""
        import threading
        import glob
        import json
        import os
        from paths import CODE_ROOT

        # Charger les informations directement depuis le fichier client_secret JSON
        json_files = glob.glob(os.path.join(CODE_ROOT, "client_secret_*.json"))
        if not json_files:
            QMessageBox.critical(
                self,
                "Fichier Credentials Manquant",
                "Aucun fichier 'client_secret_*.json' trouvé dans le dossier 'code_source/'.\n\n"
                "Veuillez y déposer le fichier de clés JSON téléchargé depuis votre console Google Cloud."
            )
            return

        secret_file = json_files[0]
        try:
            with open(secret_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            config_type = "installed" if "installed" in data else "web"
            project_id = data[config_type].get("project_id", "Inconnu")
            client_id = data[config_type].get("client_id", "Inconnu")
        except Exception as e:
            QMessageBox.critical(
                self,
                "Erreur de lecture",
                f"Impossible de lire le fichier client_secret :\n{e}"
            )
            return

        # Afficher les informations du projet Google Cloud avant de se connecter
        QMessageBox.information(
            self,
            "Connexion Google Cloud",
            f"L'application va lancer l'authentification auprès de Google Cloud avec les paramètres suivants :\n\n"
            f"📁 Fichier utilisé : {os.path.basename(secret_file)}\n"
            f"🆔 Projet Google : {project_id}\n"
            f"🔑 Client ID : {client_id[:35]}...\n\n"
            f"🌐 Un onglet va s'ouvrir dans votre navigateur Internet pour vous authentifier.\n\n"
            f"⚠️ Veuillez vous connecter avec le compte e-mail configuré comme 'Utilisateur de test' "
            f"dans ce projet GCP (ex: amicalelaique.jonage@gmail.com)."
        )

        def auth_thread():
            try:
                import gmail_auth_helper
                gmail_auth_helper.run_helper()
                # Recharger les paramètres pour afficher l'adresse e-mail mise à jour
                self.load_settings()
            except Exception as e:
                print(f"❌ Erreur lors de la connexion Google : {e}")

        threading.Thread(target=auth_thread, daemon=True).start()

    def disconnect_google(self):
        """Déconnecte le compte Google en effaçant le refresh token et l'adresse e-mail dans le trousseau et le .env."""
        reply = QMessageBox.question(
            self,
            "Déconnexion Google",
            "Êtes-vous sûr de vouloir déconnecter votre compte Google ?\n\n"
            "Cela effacera les jetons de sécurité d'envoi d'e-mails Gmail, "
            "et vous devrez vous reconnecter pour envoyer des attestations.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            # Effacer les secrets d'authentification utilisateur
            SecretStore.set_secret("GMAIL_REFRESH_TOKEN", "")
            SecretStore.set_secret("GMAIL_USER_EMAIL", "")
            
            # Mettre à jour l'affichage de l'IHM
            self.load_settings()
            
            QMessageBox.information(
                self,
                "Déconnexion réussie",
                "Votre compte Google a été déconnecté avec succès."
            )

    def test_google_services(self):
        """Teste la validité des autorisations pour Gmail, Google Drive et Google Contacts."""
        # 1. Vérifier si un token existe
        refresh_token = SecretStore.get_secret("GMAIL_REFRESH_TOKEN")
        if not refresh_token:
            QMessageBox.critical(
                self,
                "Test de Connexion",
                "❌ Aucun compte Google n'est actuellement connecté. Veuillez d'abord cliquer sur 'Connexion Google (OAuth2)'."
            )
            return
            
        self.log_msg = ["🕵️ <b>Lancement du diagnostic des services Google...</b><br>"]
        
        # Loader pour patienter
        from infrastructure.google_drive_client import GoogleDriveClient
        import requests
        
        try:
            # Tester l'obtention de l'Access Token (OAuth2)
            token = GoogleDriveClient.get_access_token()
            if token:
                self.log_msg.append("🔑 <b>Jeton d'accès OAuth2 :</b> OK (Actif)")
            else:
                self.log_msg.append("🔑 <b>Jeton d'accès OAuth2 :</b> ❌ Échec (Veuillez vous reconnecter)")
                raise Exception("Token manquant")
                
            headers = {"Authorization": f"Bearer {token}"}
            
            # A. Tester Gmail API (userinfo)
            res_gmail = requests.get("https://www.googleapis.com/oauth2/v3/userinfo", headers=headers, timeout=5)
            if res_gmail.status_code == 200:
                email = res_gmail.json().get("email", "Inconnu")
                self.log_msg.append(f"📧 <b>Gmail API :</b> 🟢 OK (Compte associé : {email})")
            else:
                self.log_msg.append(f"📧 <b>Gmail API :</b> ❌ Droits insuffisants ou expirés (Status {res_gmail.status_code})")
                
            # B. Tester Google Drive API
            res_drive = requests.get("https://www.googleapis.com/drive/v3/about?fields=user", headers=headers, timeout=5)
            if res_drive.status_code == 200:
                self.log_msg.append("💾 <b>Google Drive API :</b> 🟢 OK (Accès complet activé)")
            else:
                self.log_msg.append(f"💾 <b>Google Drive API :</b> ❌ Accès refusé ou API non activée (Status {res_drive.status_code})")
                
            # C. Tester Google Contacts (People API)
            res_contacts = requests.get("https://people.googleapis.com/v1/contactGroups?pageSize=1", headers=headers, timeout=5)
            if res_contacts.status_code == 200:
                self.log_msg.append("🧗 <b>Google Contacts (People API) :</b> 🟢 OK (Lecture/Écriture activée)")
            else:
                err_msg = res_contacts.json().get("error", {}).get("message", "Accès refusé")
                self.log_msg.append(
                    f"🧗 <b>Google Contacts :</b> ❌ Échec ({res_contacts.status_code})<br>"
                    f"   <i>Détail : {err_msg}</i><br><br>"
                    f"💡 <b>Solutions possibles :</b><br>"
                    f"1. Assurez-vous d'avoir bien <b>activé la 'People API'</b> sur votre console Google Cloud (https://console.cloud.google.com).<br>"
                    f"2. Déconnectez le compte puis cliquez sur <b>'Connexion Google'</b> pour accorder la nouvelle autorisation de Contacts."
                )

        except Exception as e:
            self.log_msg.append(f"❌ <b>Erreur de connexion Drive/Gmail :</b> {e}")
            
        # Afficher le bilan complet dans un QMessageBox formaté HTML
        box = QMessageBox(self)
        box.setWindowTitle("Bilan de Diagnostic Google Services")
        box.setTextFormat(Qt.TextFormat.RichText)
        box.setText("<br>".join(self.log_msg))
        box.exec()

    def load_settings(self):
        """Lit les clés stockées de façon sécurisée (Keyring / .env) et charge les noms de fichiers."""
        for key, line_edit in self.inputs.items():
            secret_value = SecretStore.get_secret(key)
            line_edit.setText(secret_value)
            
        # Charger également les noms des fichiers sur Google Drive
        self.load_drive_filenames()
        # Rafraîchir l'état de disponibilité et de lisibilité des fichiers locaux
        self.check_local_files_status()

    def check_local_files_status(self):
        """Vérifie la disponibilité et la lisibilité des fichiers SQLite et Excel locaux."""
        import os
        import sqlite3
        from openpyxl import load_workbook
        from paths import CODE_ROOT
        from domain.constants import get_drive_temp_filename
        from infrastructure.sqlite_repository import SqliteRepository
        
        # 1. Vérifier la base SQLite locale (Utilise le chemin persistant officiel)
        db_path = SqliteRepository.get_db_path()
        db_status = "🔴 Introuvable"
        db_color = "#EF4444"
        if os.path.exists(db_path):
            try:
                # Tester la lisibilité en ouvrant une connexion rapide
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
                cursor.close()
                conn.close()
                db_status = "🟢 Disponible et lisible"
                db_color = "#10B981"
            except Exception as e:
                db_status = f"⚠️ Corrompu ou illisible ({str(e)[:30]})"
                db_color = "#F59E0B"
        
        # 2. Vérifier l'Excel local de référence
        excel_name = get_drive_temp_filename()
        excel_path = os.path.join(CODE_ROOT, excel_name)
        excel_status = "🔴 Introuvable"
        excel_color = "#EF4444"
        if os.path.exists(excel_path):
            try:
                # Tester la lisibilité rapide en mode read_only
                wb = load_workbook(excel_path, read_only=True)
                wb.close()
                excel_status = "🟢 Disponible et lisible"
                excel_color = "#10B981"
            except Exception as e:
                excel_status = f"⚠️ Corrompu ou illisible ({str(e)[:30]})"
                excel_color = "#F59E0B"
                
        # Mettre à jour l'IHM
        self.db_status_lbl.setText(f"📁 database.db : {db_status}")
        self.db_status_lbl.setStyleSheet(f"font-size: 13px; font-weight: bold; color: {db_color};")
        
        self.excel_status_lbl.setText(f"📊 {excel_name} : {excel_status}")
        self.excel_status_lbl.setStyleSheet(f"font-size: 13px; font-weight: bold; color: {excel_color};")

    def load_drive_filenames(self):
        """Récupère en arrière-plan le nom de la base SQLite sur Google Drive."""
        import threading
        from infrastructure.google_drive_client import GoogleDriveClient
        
        db_id = SecretStore.get_secret("GOOGLE_DRIVE_DB_ID")
        
        # Réinitialiser les affichages
        if "GOOGLE_DRIVE_DB_ID" in self.filename_labels:
            if db_id:
                self.filename_labels["GOOGLE_DRIVE_DB_ID"].setText("📂 Nom du fichier sur Google Drive : (Chargement en cours...)")
            else:
                self.filename_labels["GOOGLE_DRIVE_DB_ID"].setText("📂 Nom du fichier sur Google Drive : (Aucun ID configuré)")
                
        if not db_id:
            return

        def fetch_names():
            if db_id:
                try:
                    db_name = GoogleDriveClient.get_file_name(db_id)
                    if db_name:
                        self.filename_labels["GOOGLE_DRIVE_DB_ID"].setText(f"📂 Nom du fichier sur Google Drive : {db_name}")
                    else:
                        self.filename_labels["GOOGLE_DRIVE_DB_ID"].setText("📂 Nom du fichier sur Google Drive : (Fichier introuvable ou non partagé)")
                except Exception:
                    self.filename_labels["GOOGLE_DRIVE_DB_ID"].setText("📂 Nom du fichier sur Google Drive : (Erreur lors de la récupération)")

        # Lancer dans un thread séparé pour ne pas figer l'IHM
        threading.Thread(target=fetch_names, daemon=True).start()

    def save_settings(self):
        """Écrit de manière chiffrée les secrets d'API."""
        success = True
        for key, line_edit in self.inputs.items():
            val = line_edit.text().strip()
            # Enregistrer via le SecretStore (trousseau d'accès keyring Windows)
            if not SecretStore.set_secret(key, val):
                success = False

        if success:
            QMessageBox.information(
                self, 
                "Succès", 
                "Les paramètres ont été enregistrés de manière chiffrée et sécurisée !"
            )
            # Recharger pour mettre à jour les noms des fichiers sur le Drive avec les nouveaux IDs
            self.load_settings()
        else:
            QMessageBox.warning(
                self, 
                "Avertissement", 
                "Certains paramètres n'ont pas pu être chiffrés, repli sur le .env local."
            )

    def open_drive_file_in_browser(self, key="GOOGLE_DRIVE_DB_ID"):
        """Ouvre le fichier Google Drive directement dans le navigateur."""
        drive_file_id = self.inputs[key].text().strip()
        if not drive_file_id:
            QMessageBox.warning(
                self, 
                "Avertissement", 
                f"Veuillez d'abord renseigner ou enregistrer un Google Drive ID pour '{key}'."
            )
            return

        url = f"https://drive.google.com/file/d/{drive_file_id}/view"
        import webbrowser
        try:
            webbrowser.open(url)
        except Exception as e:
            QMessageBox.warning(
                self, 
                "Erreur d'IHM", 
                f"Impossible d'ouvrir automatiquement votre navigateur web : {e}"
            )
