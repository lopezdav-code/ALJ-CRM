import os
import json
import requests
import webbrowser
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QPushButton, QHBoxLayout, 
    QFrame, QTableWidget, QTableWidgetItem, QMessageBox, QDialog,
    QLineEdit, QComboBox, QFormLayout, QAbstractItemView, QHeaderView,
    QListWidget, QListWidgetItem, QGroupBox
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from paths import ROOT_DIR

class GroupsPage(QWidget):
    """
    Page de configuration des créneaux et des groupes du club.
    Gère une structure relationnelle Groupe -> Créneaux multiples avec encadrants BDD,
    ainsi qu'une matrice de correspondance configurable avec les tarifs HelloAsso.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.planning_path = os.path.join(ROOT_DIR, "planning.json")
        self.planning_data = [] # Données brutes de planning.json
        self.groups_dict = {}   # Données groupées en mémoire
        self.all_helloasso_tarifs = []
        self.load_all_helloasso_tarifs()
        self.init_ui()
        self.load_planning()

    def load_all_helloasso_tarifs(self):
        """Récupère tous les tarifs HelloAsso uniques présents dans la table d'adhérents de la BDD SQLite."""
        try:
            from infrastructure.sqlite_repository import SqliteRepository
            conn = SqliteRepository.get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT tarif_name FROM adherents WHERE tarif_name IS NOT NULL AND tarif_name != '' ORDER BY tarif_name ASC")
            rows = cursor.fetchall()
            self.all_helloasso_tarifs = [row["tarif_name"].strip() for row in rows]
            conn.close()
        except Exception as e:
            print(f"⚠️ [MAPPING_TARIF] Impossible de précharger les tarifs : {e}")
            self.all_helloasso_tarifs = []

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(20)

        # En-tête
        title = QLabel("🧗 Configuration des Créneaux & Groupes")
        title.setStyleSheet("font-size: 24px; font-weight: bold; color: #1E293B;")
        layout.addWidget(title)

        # Description
        desc_lbl = QLabel(
            "Gérez les groupes d'activités. Sélectionnez un groupe dans le tableau ci-dessous, puis "
            "cliquez sur '✏️ Modifier le groupe' pour configurer ses créneaux horaires, associer des animateurs "
            "et mapper les tarifs HelloAsso correspondants."
        )
        desc_lbl.setStyleSheet("color: #64748B; font-size: 13px; margin-bottom: 5px;")
        layout.addWidget(desc_lbl)

        # Layout horizontal principal séparant le tableau (gauche) et l'infographie du planning (droite)
        main_content_layout = QHBoxLayout()
        main_content_layout.setSpacing(25)

        # ----------------- PARTIE GAUCHE (Tableau & Actions) -----------------
        left_layout = QVBoxLayout()
        left_layout.setSpacing(15)

        # Filtrage / Recherche
        search_layout = QHBoxLayout()
        search_lbl = QLabel("🔍 Rechercher :")
        search_lbl.setStyleSheet("font-size: 13px; font-weight: bold; color: #475569;")
        search_layout.addWidget(search_lbl)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Filtrer par nom du groupe, type...")
        self.search_input.setStyleSheet("""
            QLineEdit {
                background-color: #FFFFFF;
                border: 1px solid #CBD5E1;
                border-radius: 6px;
                padding: 8px 12px;
                font-size: 13px;
                color: #1E293B;
            }
        """)
        self.search_input.textChanged.connect(self.filter_table)
        search_layout.addWidget(self.search_input)
        left_layout.addLayout(search_layout)

        # Tableau des groupes uniques
        table_frame = QFrame()
        table_frame.setStyleSheet("""
            QFrame {
                background-color: #FFFFFF;
                border: 1px solid #E2E8F0;
                border-radius: 8px;
            }
        """)
        table_layout = QVBoxLayout(table_frame)
        table_layout.setContentsMargins(10, 10, 10, 10)

        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels([
            "Nom du groupe", "Type de groupe", "Créneaux associés", "Tarifs HelloAsso connectés", "WhatsApp 📱"
        ])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSortingEnabled(True)
        self.table.setStyleSheet("""
            QTableWidget {
                border: none;
                gridline-color: #F1F5F9;
                background-color: #FFFFFF;
                color: #1E293B;
                font-size: 13px;
            }
            QHeaderView::section {
                background-color: #F8FAFC;
                border: none;
                border-bottom: 2px solid #E2E8F0;
                padding: 8px;
                font-weight: bold;
                color: #475569;
            }
        """)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        table_layout.addWidget(self.table)
        left_layout.addWidget(table_frame)

        # Boutons d'actions principaux sous la table
        actions_btn_layout = QHBoxLayout()
        actions_btn_layout.setSpacing(10)

        self.add_btn = QPushButton("➕ Ajouter groupe")
        self.add_btn.setCursor(Qt.PointingHandCursor)
        self.add_btn.setStyleSheet("""
            QPushButton {
                background-color: #10B981;
                color: #FFFFFF;
                border: none;
                border-radius: 6px;
                padding: 8px 15px;
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #059669;
            }
        """)
        self.add_btn.clicked.connect(self.add_group)
        actions_btn_layout.addWidget(self.add_btn)

        self.edit_btn = QPushButton("✏️ Modifier groupe")
        self.edit_btn.setCursor(Qt.PointingHandCursor)
        self.edit_btn.setStyleSheet("""
            QPushButton {
                background-color: #2563EB;
                color: #FFFFFF;
                border: none;
                border-radius: 6px;
                padding: 8px 15px;
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #1D4ED8;
            }
        """)
        self.edit_btn.clicked.connect(self.edit_group)
        actions_btn_layout.addWidget(self.edit_btn)

        self.qr_btn = QPushButton("📱 Générer QRCode")
        self.qr_btn.setCursor(Qt.PointingHandCursor)
        self.qr_btn.setStyleSheet("""
            QPushButton {
                background-color: #0EA5E9;
                color: #FFFFFF;
                border: none;
                border-radius: 6px;
                padding: 8px 15px;
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #0284C7;
            }
        """)
        self.qr_btn.clicked.connect(self.generate_qr_code)
        actions_btn_layout.addWidget(self.qr_btn)

        self.delete_btn = QPushButton("❌ Supprimer")
        self.delete_btn.setCursor(Qt.PointingHandCursor)
        self.delete_btn.setStyleSheet("""
            QPushButton {
                background-color: #EF4444;
                color: #FFFFFF;
                border: none;
                border-radius: 6px;
                padding: 8px 15px;
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #DC2626;
            }
        """)
        self.delete_btn.clicked.connect(self.delete_group)
        actions_btn_layout.addWidget(self.delete_btn)

        actions_btn_layout.addStretch()

        self.save_btn = QPushButton("💾 Enregistrer")
        self.save_btn.setCursor(Qt.PointingHandCursor)
        self.save_btn.setStyleSheet("""
            QPushButton {
                background-color: #4F46E5;
                color: #FFFFFF;
                border: none;
                border-radius: 6px;
                padding: 8px 18px;
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #4338CA;
            }
        """)
        self.save_btn.clicked.connect(self.save_planning)
        actions_btn_layout.addWidget(self.save_btn)

        left_layout.addLayout(actions_btn_layout)
        main_content_layout.addLayout(left_layout, stretch=3)

        # ----------------- PARTIE DROITE (Infographie Planning) -----------------
        right_frame = QFrame()
        right_frame.setStyleSheet("""
            QFrame {
                background-color: #FFFFFF;
                border: 1px solid #E2E8F0;
                border-radius: 8px;
                padding: 15px;
                min-width: 320px;
                max-width: 350px;
            }
        """)
        right_layout = QVBoxLayout(right_frame)
        right_layout.setSpacing(12)
        right_layout.setAlignment(Qt.AlignTop | Qt.AlignHCenter)

        right_title = QLabel("📅 Infographie du Planning")
        right_title.setStyleSheet("font-size: 14px; font-weight: bold; color: #1E293B;")
        right_title.setAlignment(Qt.AlignCenter)
        right_layout.addWidget(right_title)

        # Label d'image cliquable
        self.img_lbl = QLabel()
        self.img_lbl.setCursor(Qt.PointingHandCursor)
        self.img_lbl.setAlignment(Qt.AlignCenter)

        # Tenter de charger l'infographie
        img_path = os.path.join(ROOT_DIR, "doc", "Planning-2026-2027-ALJ-1-2048x1448.png")
        if os.path.exists(img_path):
            pixmap = QPixmap(img_path)
            # Redimensionner pour tenir à droite
            self.img_lbl.setPixmap(pixmap.scaled(300, 212, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            self.img_lbl.setText("🖼️ Image du planning introuvable dans doc/")
            self.img_lbl.setStyleSheet("color: #64748B; font-size: 11px; font-style: italic;")

        self.img_lbl.mousePressEvent = self.on_image_clicked
        right_layout.addWidget(self.img_lbl)

        # Lien cliquable direct
        help_link_lbl = QLabel('<a href="https://alj-escalade.fr/creneaux/" style="color: #2563EB; font-weight: bold; text-decoration: none;">🔗 Visiter alj-escalade.fr/creneaux/</a>')
        help_link_lbl.setOpenExternalLinks(True)
        help_link_lbl.setAlignment(Qt.AlignCenter)
        help_link_lbl.setStyleSheet("font-size: 12px;")
        right_layout.addWidget(help_link_lbl)

        # Description
        info_desc_lbl = QLabel("Cliquez sur l'image ou sur le lien pour ouvrir la page officielle des créneaux de la section.")
        info_desc_lbl.setStyleSheet("font-size: 11px; color: #64748B; font-style: italic; line-height: 14px;")
        info_desc_lbl.setAlignment(Qt.AlignCenter)
        info_desc_lbl.setWordWrap(True)
        right_layout.addWidget(info_desc_lbl)

        main_content_layout.addWidget(right_frame, stretch=2)
        layout.addLayout(main_content_layout)

    def on_image_clicked(self, event):
        """Ouvre le site officiel des créneaux dans le navigateur web par défaut."""
        webbrowser.open("https://alj-escalade.fr/creneaux/")

    def load_planning(self):
        """Charge le planning de créneaux depuis la BDD SQLite."""
        try:
            from infrastructure.sqlite_repository import SqliteRepository
            self.planning_data = SqliteRepository.load_planning_data()
            
            self.group_planning_data()
            self.refresh_table()
        except Exception as e:
            QMessageBox.critical(
                self, "Erreur de chargement",
                f"Impossible de charger le planning depuis la BDD SQLite :\n{e}"
            )

    def group_planning_data(self):
        """Groupe l'ensemble des données plates de planning.json par Nom de Groupe unique."""
        self.groups_dict = {}
        for item in self.planning_data:
            g_name = str(item.get("groupe", "")).strip()
            if not g_name:
                continue
                
            if g_name not in self.groups_dict:
                self.groups_dict[g_name] = {
                    "groupe": g_name,
                    "type": item.get("type", "cours"),
                    "whatsapp_link": item.get("whatsapp_link", ""),
                    "categorie_age": item.get("categorie_age", ""),
                    "helloasso_tarifs": item.get("helloasso_tarifs", []), # Nouveau !
                    "slots": []
                }
                
            self.groups_dict[g_name]["slots"].append({
                "id": item.get("id"),
                "jour": item.get("jour", "Lundi"),
                "horaires": item.get("horaires", ""),
                "encadrants": item.get("encadrants", [])
            })

    def flatten_groups_data(self):
        """Aplatit notre dictionnaire de groupes en une liste plate conforme au format planning.json."""
        flat_list = []
        for g_name, group in self.groups_dict.items():
            for slot in group.get("slots", []):
                flat_list.append({
                    "id": slot.get("id"),
                    "groupe": group.get("groupe", g_name),
                    "type": group.get("type", "cours"),
                    "categorie_age": group.get("categorie_age", ""),
                    "whatsapp_link": group.get("whatsapp_link", ""),
                    "helloasso_tarifs": group.get("helloasso_tarifs", []),
                    "jour": slot.get("jour", "Lundi"),
                    "horaires": slot.get("horaires", ""),
                    "encadrants": slot.get("encadrants", [])
                })
        self.planning_data = flat_list

    def refresh_table(self):
        """Actualise l'affichage graphique du tableau à partir des données groupées."""
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(self.groups_dict))
        
        for row_idx, (g_name, group) in enumerate(self.groups_dict.items()):
            # Créer l'item principal et y attacher la clé du dictionnaire de groupe
            group_item = QTableWidgetItem(g_name)
            group_item.setData(Qt.UserRole, g_name)
            self.table.setItem(row_idx, 0, group_item)
            
            self.table.setItem(row_idx, 1, QTableWidgetItem(str(group.get("type", ""))))
            
            # Formater le résumé des créneaux associés (avec indication claire du nombre !)
            num_slots = len(group["slots"])
            if num_slots == 0:
                slots_text = "❌ Aucun créneau"
            elif num_slots == 1:
                slots_text = f"1 créneau : {group['slots'][0]['jour']} ({group['slots'][0]['horaires']})"
            else:
                slots_summary = []
                for s in group["slots"]:
                    slots_summary.append(f"{s['jour']} ({s['horaires']})")
                slots_text = f"{num_slots} créneaux : {', '.join(slots_summary)}"
            self.table.setItem(row_idx, 2, QTableWidgetItem(slots_text))
            
            # Formater les tarifs HelloAsso associés
            tarifs_summary = ", ".join(group.get("helloasso_tarifs", []))
            self.table.setItem(row_idx, 3, QTableWidgetItem(tarifs_summary or "Non configuré ⚠️"))
            
            # Statut WhatsApp (Pictogramme coloré !)
            wa_link = str(group.get("whatsapp_link", "")).strip()
            wa_item = QTableWidgetItem()
            if wa_link and wa_link.startswith("http"):
                wa_item.setText("🟢 Enregistré")
                wa_item.setToolTip(wa_link)
                wa_item.setForeground(Qt.darkGreen)
            else:
                wa_item.setText("🔴 Aucun")
                wa_item.setToolTip("Aucun lien WhatsApp n'a été configuré pour ce groupe.")
                wa_item.setForeground(Qt.red)
            self.table.setItem(row_idx, 4, wa_item)

        self.table.setSortingEnabled(True)
        self.table.resizeColumnsToContents()
        self.filter_table()

    def get_selected_group(self) -> tuple:
        """Détermine le groupe sélectionné en base en fonction du nom stocké dans le QTableWidgetItem."""
        selected_row = self.table.currentRow()
        if selected_row < 0:
            return None
            
        group_item = self.table.item(selected_row, 0)
        if not group_item:
            return None
            
        group_name = group_item.data(Qt.UserRole)
        return self.groups_dict.get(group_name)

    def filter_table(self):
        """Filtre les lignes du tableau en temps réel selon la saisie."""
        search_text = self.search_input.text().strip().lower()
        for row_idx in range(self.table.rowCount()):
            match = False
            for col_idx in range(self.table.columnCount()):
                item = self.table.item(row_idx, col_idx)
                if item and search_text in item.text().lower():
                    match = True
                    break
            self.table.setRowHidden(row_idx, not match)

    def add_group(self):
        """Ajoute un groupe entièrement vide en mémoire."""
        dialog = GroupEditDialog(self)
        if dialog.exec() == QDialog.Accepted:
            new_data = dialog.get_data()
            g_name = new_data["groupe"]
            
            if g_name in self.groups_dict:
                QMessageBox.warning(self, "Doublon", f"Un groupe nommé '{g_name}' existe déjà.")
                return
                
            self.groups_dict[g_name] = {
                "groupe": g_name,
                "type": new_data["type"],
                "whatsapp_link": new_data["whatsapp_link"],
                "categorie_age": "",
                "helloasso_tarifs": new_data["helloasso_tarifs"],
                "slots": new_data["slots"]
            }
            self.refresh_table()

    def edit_group(self):
        """Modifie le groupe sélectionné (ouvre le grand dialogue d'édition des créneaux & animateurs)."""
        selected_group = self.get_selected_group()
        if not selected_group:
            QMessageBox.warning(
                self, "Aucune sélection",
                "Veuillez sélectionner le groupe à modifier dans le tableau."
            )
            return

        dialog = GroupEditDialog(self, selected_group)
        if dialog.exec() == QDialog.Accepted:
            # Récupérer les modifications
            updated_data = dialog.get_data()
            old_name = selected_group["groupe"]
            new_name = updated_data["groupe"]
            
            # Gérer le changement de nom
            if old_name != new_name:
                if new_name in self.groups_dict:
                    QMessageBox.critical(self, "Erreur", f"Un groupe nommé '{new_name}' existe déjà.")
                    return
                # Supprimer l'ancienne clé
                self.groups_dict.pop(old_name)
                
            self.groups_dict[new_name] = {
                "groupe": new_name,
                "type": updated_data["type"],
                "whatsapp_link": updated_data["whatsapp_link"],
                "categorie_age": selected_group.get("categorie_age", ""),
                "helloasso_tarifs": updated_data["helloasso_tarifs"],
                "slots": updated_data["slots"]
            }
            
            self.refresh_table()

    def delete_group(self):
        """Supprime définitivement le groupe sélectionné et tous ses créneaux associés."""
        selected_group = self.get_selected_group()
        if not selected_group:
            QMessageBox.warning(
                self, "Aucune sélection",
                "Veuillez sélectionner le groupe à supprimer dans le tableau."
            )
            return

        group_name = selected_group["groupe"]
        reply = QMessageBox.question(
            self, "Supprimer le groupe",
            f"Êtes-vous sûr de vouloir supprimer définitivement le groupe '{group_name}' "
            f"ainsi que ses {len(selected_group['slots'])} créneau(x) associés ?\n\n"
            f"Cela retirera toutes ces lignes du planning.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            self.groups_dict.pop(group_name)
            self.refresh_table()

    def generate_qr_code(self):
        """Génère le QRCode du lien WhatsApp pour le groupe sélectionné."""
        selected_group = self.get_selected_group()
        if not selected_group:
            QMessageBox.warning(
                self, "Aucune sélection",
                "Veuillez sélectionner le groupe pour lequel vous souhaitez générer le QRCode."
            )
            return

        whatsapp_link = selected_group.get("whatsapp_link", "").strip()
        group_name = selected_group.get("groupe", "Groupe")
        
        if not whatsapp_link:
            QMessageBox.warning(
                self, "Lien manquant",
                f"Aucun lien WhatsApp n'est configuré pour le groupe '{group_name}'.\n\n"
                f"Veuillez modifier le groupe pour lui associer un lien d'invitation."
            )
            return

        # Dossier d'export pour les QRCodes
        qrcodes_dir = os.path.join(ROOT_DIR, "exports", "qrcodes")
        os.makedirs(qrcodes_dir, exist_ok=True)
        
        # Télécharger l'image depuis l'API libre qrserver.com
        api_url = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={whatsapp_link}"
        
        try:
            res = requests.get(api_url, timeout=10)
            if res.status_code == 200:
                safe_group_name = "".join([c for c in group_name if c.isalnum() or c in (" ", "-", "_")]).strip()
                file_path = os.path.join(qrcodes_dir, f"QRCode_WhatsApp_{safe_group_name}.png")
                
                with open(file_path, "wb") as f:
                    f.write(res.content)
                    
                # Afficher la boîte de dialogue avec le QPixmap
                dialog = QRCodeDisplayDialog(self, file_path, group_name, whatsapp_link)
                dialog.exec()
            else:
                QMessageBox.critical(
                    self, "Erreur API",
                    f"Impossible de générer le QRCode (Code HTTP {res.status_code})"
                )
        except Exception as e:
            QMessageBox.critical(
                self, "Erreur réseau",
                f"Impossible de se connecter au service de génération de QRCode. "
                f"Veuillez vérifier votre connexion Internet.\n\nDétail : {e}"
            )

    def save_planning(self):
        """Enregistre le planning actuel au format relationnel dans SQLite et l'exporte en JSON pour compatibilité."""
        self.flatten_groups_data()
        
        # 1. Vérifier la couverture des correspondances tarifaires avec alerte si manquant
        self.load_all_helloasso_tarifs() # Actualiser en direct
        
        all_mapped_tarifs = set()
        for g in self.groups_dict.values():
            for t in g.get("helloasso_tarifs", []):
                all_mapped_tarifs.add(t)
                
        unmapped = []
        for t in self.all_helloasso_tarifs:
            if t not in all_mapped_tarifs:
                unmapped.append(t)
                
        if unmapped:
            tarifs_list_str = "\n".join([f"• {t}" for t in unmapped])
            QMessageBox.warning(
                self, "⚠️ Groupes HelloAsso non connectés !",
                f"Attention : Certains groupes/tarifs HelloAsso présents dans votre base d'adhérents "
                f"ne sont associés à AUCUN créneau d'activité :\n\n{tarifs_list_str}\n\n"
                f"Veuillez modifier vos créneaux pour les connecter. Sans cela, ces adhérents ne pourront pas "
                f"être positionnés sur les fiches de présence ou d'envois WhatsApp."
            )
            
        # Afficher une belle en-tête d'action dans les logs avant d'enregistrer (Nouveau !)
        print("\n================================================================================")
        print("🧗 [PLANNING] Enregistrement des modifications du planning...")
        print("================================================================================")
        try:
            from infrastructure.sqlite_repository import SqliteRepository
            SqliteRepository.save_planning_data(self.planning_data)
            
            # Désactivation du téléversement individuel sur Google Drive (car cela ralentit trop l'IHM) (Nouveau !)
            # L'archivage et le téléversement complet seront exécutés à la fermeture de l'application.
            print("✅ [PLANNING] Planning enregistré localement dans SQLite.")
            print("================================================================================\n")
            
            msg_text = (
                "Le planning (créneaux, animateurs et correspondances HelloAsso) a été enregistré avec succès !\n\n"
                "⚡ Pour maximiser la rapidité de l'application, le téléversement vers Google Drive est mis en attente. "
                "Il sera exécuté automatiquement lors de la fermeture de l'application."
            )
            
            QMessageBox.information(
                self, "Sauvegarde réussie localement",
                msg_text
            )
        except Exception as e:
            QMessageBox.critical(
                self, "Échec de sauvegarde",
                f"Impossible d'enregistrer le planning dans SQLite :\n{e}"
            )


class GroupEditDialog(QDialog):
    """
    Dialogue de modification d'un groupe.
    Affiche la configuration générale du groupe, la liaison des tarifs HelloAsso,
    et la table d'édition de ses créneaux (jours, heures, animateurs).
    """
    def __init__(self, parent=None, group_item=None):
        super().__init__(parent)
        self.group_item = group_item
        self.slots = list(group_item.get("slots", [])) if group_item else []
        self.setWindowTitle("Ajouter un groupe" if not group_item else f"Modifier le groupe - {group_item['groupe']}")
        self.setMinimumWidth(800) # Élargi pour supporter les deux colonnes (Tarifs + Créneaux)
        self.all_helloasso_tarifs = []
        self.load_all_helloasso_tarifs()
        self.init_ui()

    def load_all_helloasso_tarifs(self):
        """Récupère l'intégralité des tarifs HelloAsso existants dans la BDD."""
        try:
            from infrastructure.sqlite_repository import SqliteRepository
            conn = SqliteRepository.get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT tarif_name FROM adherents WHERE tarif_name IS NOT NULL AND tarif_name != '' ORDER BY tarif_name ASC")
            rows = cursor.fetchall()
            self.all_helloasso_tarifs = [row["tarif_name"].strip() for row in rows]
            conn.close()
        except Exception as e:
            print(f"⚠️ [MAPPING_TARIF] Impossible de charger les tarifs : {e}")
            self.all_helloasso_tarifs = []

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # Corps principal horizontal à deux colonnes
        main_columns_layout = QHBoxLayout()
        main_columns_layout.setSpacing(20)

        # --- COLONNE DE GAUCHE : Configuration & Liaisons Tarifs ---
        left_panel = QVBoxLayout()
        left_panel.setSpacing(12)

        # Formulaire général
        form_layout = QFormLayout()
        form_layout.setSpacing(8)

        self.group_input = QLineEdit()
        self.group_input.setPlaceholderText("ex: Loisir Collège")
        if self.group_item:
            self.group_input.setText(self.group_item.get("groupe", ""))
        form_layout.addRow("Nom du groupe :", self.group_input)

        self.type_combo = QComboBox()
        self.type_combo.addItems(["autonome", "cours", "compétition", "perfectionnement"])
        if self.group_item:
            stored_type = str(self.group_item.get("type", "")).strip().lower()
            if "autonome" in stored_type:
                self.type_combo.setCurrentText("autonome")
            elif "compétition" in stored_type or "compet" in stored_type:
                self.type_combo.setCurrentText("compétition")
            elif "perfectionnement" in stored_type or "perf" in stored_type:
                self.type_combo.setCurrentText("perfectionnement")
            else:
                self.type_combo.setCurrentText("cours")
        form_layout.addRow("Type de groupe :", self.type_combo)

        self.whatsapp_input = QLineEdit()
        self.whatsapp_input.setPlaceholderText("ex: https://chat.whatsapp.com/...")
        if self.group_item:
            self.whatsapp_input.setText(self.group_item.get("whatsapp_link", ""))
        form_layout.addRow("Lien WhatsApp :", self.whatsapp_input)

        left_panel.addLayout(form_layout)

        # Panneau des tarifs HelloAsso associables
        tarifs_group = QGroupBox("🔗 Groupes HelloAsso connectés à ce créneau")
        tarifs_group_layout = QVBoxLayout(tarifs_group)
        tarifs_group_layout.setSpacing(8)

        tarifs_desc = QLabel("Cochez les catégories HelloAsso qui se rattachent à ce cours :")
        tarifs_desc.setWordWrap(True)
        tarifs_desc.setStyleSheet("font-size: 11px; color: #64748B; font-style: italic; line-height: 14px;")
        tarifs_group_layout.addWidget(tarifs_desc)

        # List Widget contenant des QListWidgetItem cochables
        self.tarif_list_widget = QListWidget()
        self.tarif_list_widget.setStyleSheet("QListWidget { font-size: 11px; }")
        
        # Remplir la liste des tarifs HelloAsso
        linked_tarifs = self.group_item.get("helloasso_tarifs", []) if self.group_item else []
        for t in self.all_helloasso_tarifs:
            item = QListWidgetItem(t)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            if t in linked_tarifs:
                item.setCheckState(Qt.Checked)
            else:
                item.setCheckState(Qt.Unchecked)
            self.tarif_list_widget.addItem(item)
            
        tarifs_group_layout.addWidget(self.tarif_list_widget)
        left_panel.addWidget(tarifs_group)

        main_columns_layout.addLayout(left_panel, stretch=2)

        # --- COLONNE DE DROITE : Créneaux horaires ---
        right_panel = QVBoxLayout()
        right_panel.setSpacing(10)

        box_slots = QGroupBox("📅 Créneaux horaires & Animateurs affectés")
        box_layout = QVBoxLayout(box_slots)
        box_layout.setSpacing(10)

        # Tableau des créneaux du groupe
        self.slots_table = QTableWidget()
        self.slots_table.setColumnCount(3)
        self.slots_table.setHorizontalHeaderLabels(["Jour", "Heure", "Animateurs (Encadrants)"])
        self.slots_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.slots_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.slots_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.slots_table.setStyleSheet("QTableWidget { font-size: 12px; }")
        self.slots_table.horizontalHeader().setStretchLastSection(True)
        box_layout.addWidget(self.slots_table)

        # Boutons d'édition des créneaux
        slots_btn_layout = QHBoxLayout()
        slots_btn_layout.setSpacing(8)

        self.add_slot_btn = QPushButton("➕ Ajouter un créneau")
        self.add_slot_btn.setCursor(Qt.PointingHandCursor)
        self.add_slot_btn.setStyleSheet("QPushButton { background-color: #10B981; color: white; padding: 4px 10px; font-weight: bold; font-size: 11px; }")
        self.add_slot_btn.clicked.connect(self.add_slot)
        slots_btn_layout.addWidget(self.add_slot_btn)

        self.edit_slot_btn = QPushButton("✏️ Modifier")
        self.edit_slot_btn.setCursor(Qt.PointingHandCursor)
        self.edit_slot_btn.setStyleSheet("QPushButton { background-color: #2563EB; color: white; padding: 4px 10px; font-weight: bold; font-size: 11px; }")
        self.edit_slot_btn.clicked.connect(self.edit_slot)
        slots_btn_layout.addWidget(self.edit_slot_btn)

        self.delete_slot_btn = QPushButton("❌ Retirer")
        self.delete_slot_btn.setCursor(Qt.PointingHandCursor)
        self.delete_slot_btn.setStyleSheet("QPushButton { background-color: #EF4444; color: white; padding: 4px 10px; font-weight: bold; font-size: 11px; }")
        self.delete_slot_btn.clicked.connect(self.delete_slot)
        slots_btn_layout.addWidget(self.delete_slot_btn)

        box_layout.addLayout(slots_btn_layout)
        right_panel.addWidget(box_slots)

        main_columns_layout.addLayout(right_panel, stretch=3)
        layout.addLayout(main_columns_layout)

        # Remplir le tableau des créneaux
        self.refresh_slots_table()

        # Boutons de validation globaux de la boîte de dialogue
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        self.save_btn = QPushButton("Valider le groupe")
        self.save_btn.setStyleSheet("QPushButton { background-color: #4F46E5; color: white; padding: 6px 16px; font-weight: bold; }")
        self.save_btn.clicked.connect(self.accept_data)
        button_layout.addWidget(self.save_btn)

        self.cancel_btn = QPushButton("Annuler")
        self.cancel_btn.setStyleSheet("QPushButton { background-color: #F1F5F9; color: #334155; border: 1px solid #CBD5E1; padding: 6px 16px; }")
        self.cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_btn)

        layout.addLayout(button_layout)

    def refresh_slots_table(self):
        """Actualise le tableau interne affichant les différents créneaux du groupe."""
        self.slots_table.setRowCount(len(self.slots))
        for row_idx, slot in enumerate(self.slots):
            self.slots_table.setItem(row_idx, 0, QTableWidgetItem(str(slot.get("jour", "Lundi"))))
            self.slots_table.setItem(row_idx, 1, QTableWidgetItem(str(slot.get("horaires", ""))))
            encadrants_str = ", ".join(slot.get("encadrants", []))
            self.slots_table.setItem(row_idx, 2, QTableWidgetItem(encadrants_str or "Aucun animateur"))
        self.slots_table.resizeColumnsToContents()

    def add_slot(self):
        """Ouvre la sous-boîte de dialogue pour ajouter un nouveau créneau horaire."""
        dialog = SlotEditDialog(self)
        if dialog.exec() == QDialog.Accepted:
            new_slot_data = dialog.get_data()
            
            # Génération robuste de l'ID temporaire
            import time
            new_slot_data["id"] = int(time.time() * 1000) # Assure un ID toujours unique pour SQLite !
            
            self.slots.append(new_slot_data)
            self.refresh_slots_table()

    def edit_slot(self):
        """Ouvre la sous-boîte de dialogue pour modifier le créneau horaire sélectionné."""
        selected_row = self.slots_table.currentRow()
        if selected_row < 0:
            QMessageBox.warning(self, "Sélection", "Veuillez d'abord sélectionner le créneau à modifier.")
            return

        current_slot = self.slots[selected_row]
        dialog = SlotEditDialog(self, current_slot)
        if dialog.exec() == QDialog.Accepted:
            updated_slot_data = dialog.get_data()
            
            current_slot["jour"] = updated_slot_data["jour"]
            current_slot["horaires"] = updated_slot_data["horaires"]
            current_slot["encadrants"] = updated_slot_data["encadrants"]
            
            self.refresh_slots_table()

    def delete_slot(self):
        """Retire le créneau sélectionné."""
        selected_row = self.slots_table.currentRow()
        if selected_row < 0:
            QMessageBox.warning(self, "Sélection", "Veuillez d'abord sélectionner le créneau à retirer.")
            return
            
        self.slots.pop(selected_row)
        self.refresh_slots_table()

    def accept_data(self):
        """Valide et accepte les modifications globales du groupe."""
        if not self.group_input.text().strip():
            QMessageBox.warning(self, "Nom manquant", "Le nom du groupe est obligatoire.")
            return
        self.accept()

    def get_data(self) -> dict:
        """Retourne les valeurs du formulaire."""
        # Récupérer les tarifs HelloAsso cochés
        linked_tarifs = []
        for r in range(self.tarif_list_widget.count()):
            item = self.tarif_list_widget.item(r)
            if item.checkState() == Qt.Checked:
                linked_tarifs.append(item.text().strip())

        # Créer une copie profonde de la liste de slots pour être sûr que l'affectation à groups_dict ne passe pas à côté !
        import copy
        current_slots = copy.deepcopy(self.slots)

        return {
            "groupe": self.group_input.text().strip(),
            "type": self.type_combo.currentText(),
            "whatsapp_link": self.whatsapp_input.text().strip(),
            "helloasso_tarifs": linked_tarifs,
            "slots": current_slots
        }


class SlotEditDialog(QDialog):
    """
    Boîte de dialogue modale d'édition d'un créneau horaire (Jour, Heure).
    Comprend une zone de recherche/ajout dynamique des animateurs directement issus de la BDD d'adhérents !
    """
    def __init__(self, parent=None, slot_item=None):
        super().__init__(parent)
        self.slot_item = slot_item
        self.encadrants = list(slot_item.get("encadrants", [])) if slot_item else []
        self.setWindowTitle("Ajouter un créneau" if not slot_item else "Modifier le créneau")
        self.setMinimumWidth(450)
        self.init_ui()
        self.load_members_as_animators()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        form_layout = QFormLayout()
        form_layout.setSpacing(8)

        # 1. Jour
        self.day_combo = QComboBox()
        self.day_combo.addItems(["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"])
        if self.slot_item:
            self.day_combo.setCurrentText(self.slot_item.get("jour", "Lundi"))
        form_layout.addRow("Jour du cours :", self.day_combo)

        # 2. Horaires
        self.time_input = QLineEdit()
        self.time_input.setPlaceholderText("ex: 18:30 - 20:00")
        if self.slot_item:
            self.time_input.setText(self.slot_item.get("horaires", ""))
        form_layout.addRow("Heure du cours :", self.time_input)

        layout.addLayout(form_layout)

        # ----------------- RECHERCHE & GESTION DES ANIMATEURS BDD -----------------
        anim_box = QGroupBox("👥 Affectation des Animateurs (Encadrants)")
        anim_layout = QVBoxLayout(anim_box)
        anim_layout.setSpacing(10)

        # Liste graphique des animateurs affectés actuellement
        self.anim_list_widget = QListWidget()
        self.anim_list_widget.addItems(self.encadrants)
        self.anim_list_widget.setStyleSheet("QListWidget { font-size: 12px; max-height: 80px; }")
        anim_layout.addWidget(self.anim_list_widget)

        # Barre de recherche et ajout de l'animateur
        search_add_layout = QHBoxLayout()
        self.anim_combo = QComboBox()
        self.anim_combo.setEditable(True) # Rendre éditable pour permettre la saisie et l'autocomplétion
        self.anim_combo.setInsertPolicy(QComboBox.NoInsert)
        self.anim_combo.completer().setFilterMode(Qt.MatchContains) # Recherche par ressemblance de sous-chaîne !
        self.anim_combo.setStyleSheet("""
            QComboBox {
                border: 1px solid #CBD5E1;
                border-radius: 4px;
                padding: 4px;
                font-size: 12px;
                background-color: #FFFFFF;
                min-width: 230px;
            }
        """)
        search_add_layout.addWidget(self.anim_combo)

        # Bouton Ajouter l'Animateur
        add_anim_btn = QPushButton("➕ Affecter")
        add_anim_btn.setCursor(Qt.PointingHandCursor)
        add_anim_btn.setStyleSheet("QPushButton { background-color: #10B981; color: white; padding: 4px 10px; font-weight: bold; font-size: 11px; }")
        add_anim_btn.clicked.connect(self.add_animator)
        search_add_layout.addWidget(add_anim_btn)

        # Bouton Retirer l'Animateur
        remove_anim_btn = QPushButton("❌ Retirer")
        remove_anim_btn.setCursor(Qt.PointingHandCursor)
        remove_anim_btn.setStyleSheet("QPushButton { background-color: #EF4444; color: white; padding: 4px 10px; font-weight: bold; font-size: 11px; }")
        remove_anim_btn.clicked.connect(self.remove_animator)
        search_add_layout.addWidget(remove_anim_btn)

        anim_layout.addLayout(search_add_layout)
        layout.addWidget(anim_box)

        # Boutons de validation de la boîte de dialogue créneau
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        self.save_btn = QPushButton("Valider")
        self.save_btn.setStyleSheet("QPushButton { background-color: #10B981; color: white; padding: 6px 16px; font-weight: bold; }")
        self.save_btn.clicked.connect(self.accept)
        button_layout.addWidget(self.save_btn)

        self.cancel_btn = QPushButton("Annuler")
        self.cancel_btn.setStyleSheet("QPushButton { background-color: #F1F5F9; color: #334155; border: 1px solid #CBD5E1; padding: 6px 16px; }")
        self.cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_btn)

        layout.addLayout(button_layout)

    def load_members_as_animators(self):
        """Charge l'intégralité des adhérents de la base SQLite active pour alimenter le menu de recherche pour la saison active (2026-2027)."""
        try:
            from infrastructure.sqlite_repository import SqliteRepository
            SqliteRepository.setup_database()
            all_members = SqliteRepository.load_direct_data(season_filter="2026-2027")
            
            # Formater en liste de strings de type "NOM Prénom"
            anim_names = sorted(list(set([
                f"{str(m.get('user_lastName', '')).strip().upper()} {str(m.get('user_firstName', '')).strip().capitalize()}"
                for m in all_members if m.get("user_lastName")
            ])))
            
            self.anim_combo.blockSignals(True)
            self.anim_combo.clear()
            self.anim_combo.addItems(anim_names)
            self.anim_combo.blockSignals(False)
        except Exception as e:
            print(f"⚠️ [CONTACTS_SEARCH] Impossible de précharger les adhérents pour recherche : {e}")

    def add_animator(self):
        """Ajoute l'animateur sélectionné dans la boîte de recherche à la liste du créneau."""
        selected_name = self.anim_combo.currentText().strip()
        if not selected_name:
            return
            
        if selected_name in self.encadrants:
            QMessageBox.warning(self, "Déjà affecté", f"L'animateur '{selected_name}' est déjà rattaché à ce créneau.")
            return
            
        self.encadrants.append(selected_name)
        self.anim_list_widget.addItem(selected_name)

    def remove_animator(self):
        """Retire l'animateur sélectionné de la liste du créneau."""
        selected_row = self.anim_list_widget.currentRow()
        if selected_row < 0:
            QMessageBox.warning(self, "Sélection", "Veuillez sélectionner l'animateur à retirer dans la liste ci-dessus.")
            return
            
        self.encadrants.pop(selected_row)
        self.anim_list_widget.takeItem(selected_row)

    def get_data(self) -> dict:
        """Retourne le dictionnaire du créneau configuré."""
        return {
            "jour": self.day_combo.currentText(),
            "horaires": self.time_input.text().strip(),
            "encadrants": self.encadrants
        }


class QRCodeDisplayDialog(QDialog):
    """
    Dialogue modal affichant le QRCode généré avec options d'ouverture et fermeture.
    """
    def __init__(self, parent=None, image_path=None, group_name="", whatsapp_link=""):
        super().__init__(parent)
        self.image_path = image_path
        self.group_name = group_name
        self.whatsapp_link = whatsapp_link
        self.setWindowTitle(f"QRCode WhatsApp - {group_name}")
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(25, 25, 25, 25)
        layout.setSpacing(15)

        # Titre
        title_lbl = QLabel(f"📱 QRCode pour {self.group_name}")
        title_lbl.setStyleSheet("font-size: 16px; font-weight: bold; color: #1E293B;")
        title_lbl.setAlignment(Qt.AlignCenter)
        layout.addWidget(title_lbl)

        # Image du QRCode
        from PySide6.QtGui import QPixmap
        self.img_label = QLabel()
        self.img_label.setAlignment(Qt.AlignCenter)
        
        pixmap = QPixmap(self.image_path)
        self.img_label.setPixmap(pixmap.scaled(250, 250, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        layout.addWidget(self.img_label)

        # Lien textuel cliquable
        link_lbl = QLabel(f'<a href="{self.whatsapp_link}" style="color: #2563EB; font-weight: bold; text-decoration: none;">🔗 Cliquer pour rejoindre le groupe WhatsApp</a>')
        link_lbl.setOpenExternalLinks(True)
        link_lbl.setAlignment(Qt.AlignCenter)
        link_lbl.setStyleSheet("font-size: 13px;")
        layout.addWidget(link_lbl)

        # Description
        info_lbl = QLabel("Scannez ce code avec un smartphone pour rejoindre instantanément le groupe de discussion.")
        info_lbl.setStyleSheet("font-size: 11px; color: #64748B; font-style: italic;")
        info_lbl.setAlignment(Qt.AlignCenter)
        info_lbl.setWordWrap(True)
        layout.addWidget(info_lbl)

        # Boutons d'action en bas
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)
        btn_layout.addStretch()

        # Bouton ouvrir dossier
        open_folder_btn = QPushButton("📂 Ouvrir le dossier")
        open_folder_btn.setCursor(Qt.PointingHandCursor)
        open_folder_btn.setStyleSheet("""
            QPushButton {
                background-color: #F1F5F9;
                color: #334155;
                border: 1px solid #CBD5E1;
                border-radius: 4px;
                padding: 6px 16px;
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #E2E8F0;
            }
        """)
        open_folder_btn.clicked.connect(self.open_folder)
        btn_layout.addWidget(open_folder_btn)

        # Bouton fermer
        close_btn = QPushButton("Fermer")
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.setStyleSheet("""
            QPushButton {
                background-color: #1E293B;
                color: #FFFFFF;
                border: none;
                border-radius: 4px;
                padding: 6px 16px;
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #0F172A;
            }
        """)
        close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(close_btn)

        layout.addLayout(btn_layout)

    def open_folder(self):
        """Ouvre l'explorateur Windows dans le dossier contenant le QRCode."""
        import os
        dir_path = os.path.dirname(self.image_path)
        os.startfile(dir_path)
