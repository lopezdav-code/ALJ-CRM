import os
import glob
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QPushButton, QHBoxLayout,
    QFrame, QProgressBar, QTextEdit, QFileDialog, QMessageBox, QLineEdit, QTabWidget, QComboBox,
    QDialog, QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView
)
from PySide6.QtCore import Qt
from presentation.workers import FFMEMergeWorker, AutonomesMergeWorker, SaisonMergeWorker
from paths import ROOT_DIR


class ManualMatchDialog(QDialog):
    """
    Fenêtre modale proposant la sélection manuelle d'un adhérent de la base
    pour un licencié FFME qui n'a pas été trouvé automatiquement.
    Recherche tolérante par tokens : "BOURDAUD HUI Marine" retrouve "BOURDAUD Marine".
    """
    def __init__(self, person: dict, users: list, parent=None):
        super().__init__(parent)
        self.person = person
        self.users = users
        self.selected_user_id = None
        self.setWindowTitle("Association manuelle FFME")
        self.setModal(True)
        self.resize(560, 520)
        self.init_ui()
        self.populate_table()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Cadre récapitulatif du licencié FFME introuvable
        info_frame = QFrame()
        info_frame.setStyleSheet("""
            QFrame {
                background-color: #FEF2F2;
                border: 1px solid #FECACA;
                border-radius: 6px;
            }
        """)
        info_layout = QVBoxLayout(info_frame)
        info_layout.setContentsMargins(12, 10, 12, 10)
        info_title = QLabel("⚠️ Licencié FFME non trouvé automatiquement dans la base :")
        info_title.setStyleSheet("font-size: 12px; font-weight: bold; color: #B91C1C;")
        info_layout.addWidget(info_title)
        p = self.person
        details = f"👤 {p.get('nom', '')} {p.get('prenom', '')}"
        if p.get("licence"):
            details += f"   |   🪪 N° licence : {p['licence']}"
        if p.get("birth_date"):
            details += f"   |   🎂 Né(e) le : {p['birth_date']}"
        info_lbl = QLabel(details)
        info_lbl.setStyleSheet("font-size: 13px; color: #1E293B; font-weight: bold;")
        info_lbl.setWordWrap(True)
        info_layout.addWidget(info_lbl)
        help_lbl = QLabel(
            "Sélectionnez l'adhérent correspondant dans la liste ci-dessous "
            "(recherche par nom/prénom possible), ou ignorez cette ligne."
        )
        help_lbl.setStyleSheet("font-size: 11px; color: #64748B;")
        help_lbl.setWordWrap(True)
        info_layout.addWidget(help_lbl)
        layout.addWidget(info_frame)

        # Recherche
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("🔍 Filtrer les adhérents (nom, prénom...)")
        self.search_input.setStyleSheet("""
            QLineEdit {
                border: 1px solid #CBD5E1;
                border-radius: 6px;
                padding: 8px 12px;
                font-size: 13px;
            }
        """)
        self.search_input.textChanged.connect(self.populate_table)
        layout.addWidget(self.search_input)

        # Table des adhérents de la base
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Nom", "Prénom", "N° Licence", "Naissance"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.verticalHeader().setDefaultSectionSize(26)
        self.table.setStyleSheet("""
            QTableWidget {
                border: 1px solid #E2E8F0;
                border-radius: 6px;
                gridline-color: #F1F5F9;
                font-size: 12px;
            }
            QHeaderView::section {
                background-color: #F8FAFC;
                color: #64748B;
                padding: 6px;
                font-weight: bold;
                border: none;
                border-bottom: 1px solid #E2E8F0;
            }
        """)
        self.table.itemDoubleClicked.connect(lambda _: self.accept_selection())
        self.table.itemSelectionChanged.connect(self.on_selection_changed)
        layout.addWidget(self.table)

        # Boutons
        btn_layout = QHBoxLayout()
        self.associate_btn = QPushButton("🔗 Associer cet adhérent")
        self.associate_btn.setCursor(Qt.PointingHandCursor)
        self.associate_btn.setEnabled(False)
        self.associate_btn.setStyleSheet("""
            QPushButton {
                background-color: #10B981;
                color: #FFFFFF;
                border: none;
                border-radius: 6px;
                padding: 8px 18px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #059669; }
            QPushButton:disabled { background-color: #94A3B8; }
        """)
        self.associate_btn.clicked.connect(self.accept_selection)

        skip_btn = QPushButton("⏭️ Ignorer (laisser non trouvé)")
        skip_btn.setCursor(Qt.PointingHandCursor)
        skip_btn.setStyleSheet("""
            QPushButton {
                background-color: #F1F5F9;
                color: #475569;
                border: 1px solid #CBD5E1;
                border-radius: 6px;
                padding: 8px 18px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #E2E8F0; }
        """)
        skip_btn.clicked.connect(self.reject)

        btn_layout.addWidget(self.associate_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(skip_btn)
        layout.addLayout(btn_layout)

    def _user_tokens(self, user: dict) -> set:
        from domain.utils import normalize_name
        return set(normalize_name(f"{user.get('last_name', '')} {user.get('first_name', '')}").split())

    def populate_table(self):
        """Remplit la table avec les adhérents filtrés, triés par pertinence."""
        from domain.utils import normalize_name
        search_tokens = set(normalize_name(self.search_input.text()).split())
        person_tokens = set(normalize_name(
            f"{self.person.get('nom', '')} {self.person.get('prenom', '')}"
        ).split())

        candidates = []
        for u in self.users:
            u_tokens = self._user_tokens(u)
            if search_tokens:
                # Au moins un token de recherche présent dans le nom de l'adhérent
                if not (search_tokens & u_tokens):
                    continue
                score = len(search_tokens & u_tokens)
            else:
                # Pas de recherche : tri par pertinence par rapport au licencié FFME
                score = len(person_tokens & u_tokens)
            candidates.append((score, u))

        # Tri : pertinence décroissante puis nom/prénom alphabétique
        candidates.sort(key=lambda t: (-t[0], str(t[1].get("last_name", "")).lower(),
                                       str(t[1].get("first_name", "")).lower()))

        self.table.setRowCount(len(candidates))
        for r, (_, u) in enumerate(candidates):
            birth = str(u.get("birth_date") or "").split(" ")[0]
            lic = str(u.get("licence_ffme") or "").replace(".0", "")
            for c, val in enumerate([u.get("last_name", ""), u.get("first_name", ""), lic, birth]):
                item = QTableWidgetItem(str(val))
                item.setData(Qt.UserRole, u.get("id"))
                self.table.setItem(r, c, item)

        # Pré-remplir la recherche avec le nom FFME (une seule fois, si vide)
        if not self.search_input.text() and self.person.get("nom"):
            self.search_input.setText(self.person["nom"])

        self.table.clearSelection()
        self.associate_btn.setEnabled(False)

    def on_selection_changed(self):
        self.associate_btn.setEnabled(bool(self.table.selectedItems()))

    def accept_selection(self):
        selected = self.table.selectedItems()
        if not selected:
            return
        row = selected[0].row()
        self.selected_user_id = self.table.item(row, 0).data(Qt.UserRole)
        self.accept()

class ImportDataPage(QWidget):
    """
    Page d'importation globale de données.
    Permet de gérer l'importation FFME et l'importation des Badges Rouges / Autonomie via un système d'onglets.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # En-tête principal
        title = QLabel("📥 Importation de Données")
        title.setStyleSheet("font-size: 24px; font-weight: bold; color: #1E293B;")
        layout.addWidget(title)

        # QTabWidget pour les deux imports
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #CBD5E1;
                border-radius: 8px;
                background-color: #FFFFFF;
                padding: 10px;
            }
            QTabBar::tab {
                background-color: #F1F5F9;
                color: #475569;
                padding: 8px 16px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                font-weight: bold;
                font-size: 13px;
                margin-right: 4px;
            }
            QTabBar::tab:selected {
                background-color: #FFFFFF;
                color: #2563EB;
                border-bottom: 2px solid #2563EB;
            }
            QTabBar::tab:hover {
                background-color: #E2E8F0;
            }
        """)

        # Création des trois sous-onglets (Nouveau !)
        self.ffme_tab = FFMEImportWidget(self)
        self.autonomes_tab = AutonomesImportWidget(self)
        self.saison_tab = SaisonImportWidget(self)

        self.tabs.addTab(self.ffme_tab, "🧗 Validation FFME")
        self.tabs.addTab(self.autonomes_tab, "🔴 Badges d'Autonomie")
        self.tabs.addTab(self.saison_tab, "📅 Importer Ancienne Saison")

        layout.addWidget(self.tabs)


class FFMEImportWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()
        self.pre_detect_ffme_file()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(15)

        # Description
        desc_lbl = QLabel(
            "Importez la liste Excel des licenciés fournie par le portail FFME. "
            "Le système synchronisera automatiquement les numéros de licence manquants et basculera le statut "
            "des adhérents associés en 'Terminé'."
        )
        desc_lbl.setWordWrap(True)
        desc_lbl.setStyleSheet("color: #64748B; font-size: 13px; margin-bottom: 5px;")
        layout.addWidget(desc_lbl)

        # ----------------- SECTION SELECTION DE FICHIER -----------------
        select_frame = QFrame()
        select_frame.setStyleSheet("""
            QFrame {
                background-color: #FFFFFF;
                border: 1px solid #E2E8F0;
                border-radius: 8px;
                padding: 15px;
            }
        """)
        select_layout = QVBoxLayout(select_frame)
        select_layout.setSpacing(12)

        select_title = QLabel("📂 Sélectionner la liste d'export FFME (.xlsx)")
        select_title.setStyleSheet("font-size: 14px; font-weight: bold; color: #1E293B;")
        select_layout.addWidget(select_title)

        file_selection_layout = QHBoxLayout()
        self.file_path_input = QLineEdit()
        self.file_path_input.setReadOnly(True)
        self.file_path_input.setPlaceholderText("Aucun fichier sélectionné...")
        self.file_path_input.setStyleSheet("""
            QLineEdit {
                border: 1px solid #CBD5E1;
                border-radius: 6px;
                padding: 8px 12px;
                font-size: 13px;
                background-color: #F8FAFC;
                color: #334155;
            }
        """)
        file_selection_layout.addWidget(self.file_path_input)

        self.browse_btn = QPushButton("📁 Choisir un fichier...")
        self.browse_btn.setCursor(Qt.PointingHandCursor)
        self.browse_btn.setStyleSheet("""
            QPushButton {
                background-color: #F1F5F9;
                color: #334155;
                border: 1px solid #CBD5E1;
                border-radius: 6px;
                padding: 8px 16px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #E2E8F0;
            }
        """)
        self.browse_btn.clicked.connect(self.browse_file)
        file_selection_layout.addWidget(self.browse_btn)
        select_layout.addLayout(file_selection_layout)

        # Bouton d'action principal de fusion
        action_layout = QHBoxLayout()
        self.merge_btn = QPushButton("⚡ Lancer l'importation & la fusion")
        self.merge_btn.setCursor(Qt.PointingHandCursor)
        self.merge_btn.setStyleSheet("""
            QPushButton {
                background-color: #2563EB;
                color: #FFFFFF;
                border: none;
                border-radius: 6px;
                padding: 10px 24px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #1D4ED8;
            }
            QPushButton:disabled {
                background-color: #94A3B8;
            }
        """)
        self.merge_btn.clicked.connect(self.start_merge_workflow)
        action_layout.addWidget(self.merge_btn)
        action_layout.addStretch()
        select_layout.addLayout(action_layout)

        layout.addWidget(select_frame)

        # ----------------- BARRE DE PROGRESSION -----------------
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #E2E8F0;
                border-radius: 6px;
                background-color: #FFFFFF;
                text-align: center;
                color: #1E293B;
                font-weight: bold;
            }
            QProgressBar::chunk {
                background-color: #10B981;
                border-radius: 5px;
            }
        """)
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        # ----------------- SECTION RESULTATS & STATISTIQUES -----------------
        self.stats_frame = QFrame()
        self.stats_frame.setStyleSheet("""
            QFrame {
                background-color: #FFFFFF;
                border: 1px solid #E2E8F0;
                border-radius: 8px;
                padding: 15px;
            }
        """)
        self.stats_frame.setVisible(False)
        stats_layout = QVBoxLayout(self.stats_frame)
        stats_layout.setSpacing(8)

        stats_title = QLabel("📊 Résumé de la fusion FFME")
        stats_title.setStyleSheet("font-size: 14px; font-weight: bold; color: #1E293B; margin-bottom: 5px;")
        stats_layout.addWidget(stats_title)

        self.lbl_stat_total = QLabel("📋 Lignes traitées : -")
        self.lbl_stat_total.setStyleSheet("font-size: 13px; color: #334155;")
        stats_layout.addWidget(self.lbl_stat_total)

        self.lbl_stat_licence = QLabel("🟢 Associés par N° de licence (Statut Terminé) : -")
        self.lbl_stat_licence.setStyleSheet("font-size: 13px; color: #16A34A; font-weight: bold;")
        stats_layout.addWidget(self.lbl_stat_licence)

        self.lbl_stat_name = QLabel("🔑 Associés par Nom/Prénom (Nouveau N° enregistré & Statut Terminé) : -")
        self.lbl_stat_name.setStyleSheet("font-size: 13px; color: #2563EB; font-weight: bold;")
        stats_layout.addWidget(self.lbl_stat_name)

        self.lbl_stat_notfound = QLabel("🔴 Licenciés FFME non trouvés en base locale : -")
        self.lbl_stat_notfound.setStyleSheet("font-size: 13px; color: #DC2626;")
        stats_layout.addWidget(self.lbl_stat_notfound)

        layout.addWidget(self.stats_frame)

        # ----------------- TRACE / LOG AREA -----------------
        log_title = QLabel("📝 Console de suivi d'importation FFME")
        log_title.setStyleSheet("font-size: 13px; font-weight: bold; color: #334155;")
        layout.addWidget(log_title)

        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setPlaceholderText("Les journaux d'importation s'afficheront ici en temps réel...")
        self.log_area.setStyleSheet("""
            QTextEdit {
                background-color: #1E293B;
                color: #F8FAFC;
                border: 1px solid #0F172A;
                border-radius: 8px;
                padding: 10px;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 12px;
            }
        """)
        layout.addWidget(self.log_area)

    def pre_detect_ffme_file(self):
        import_dir = os.path.join(ROOT_DIR, "import", "ffme")
        if os.path.exists(import_dir):
            files = glob.glob(os.path.join(import_dir, "Export_Licencies_*.xlsx"))
            if files:
                files.sort(key=os.path.getmtime, reverse=True)
                latest_file = files[0]
                self.file_path_input.setText(latest_file)
                self.log_area.append(f"🔍 [SYSTEM] Fichier FFME détecté automatiquement : {os.path.basename(latest_file)}")

    def browse_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Sélectionner la liste des licenciés FFME",
            ROOT_DIR,
            "Fichiers Excel (*.xlsx *.xls)"
        )
        if file_path:
            self.file_path_input.setText(file_path)
            self.log_area.append(f"📁 [FILE] Fichier sélectionné : {file_path}")

    def set_ui_enabled(self, enabled: bool):
        self.browse_btn.setEnabled(enabled)
        self.merge_btn.setEnabled(enabled)
        self.file_path_input.setEnabled(enabled)

    def start_merge_workflow(self):
        file_path = self.file_path_input.text().strip()
        if not file_path or not os.path.exists(file_path):
            QMessageBox.warning(
                self,
                "Fichier manquant",
                "Veuillez d'abord sélectionner un fichier Excel FFME valide pour lancer l'importation."
            )
            return

        self.set_ui_enabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.log_area.clear()
        self.stats_frame.setVisible(False)

        self.log_area.append("🚀 Démarrage du traitement d'importation FFME...")

        self.worker = FFMEMergeWorker(file_path)
        self.worker.progress.connect(self.on_progress)
        # Connexion bloquante : le worker se met en pause pendant l'affichage de la fenêtre
        self.worker.manual_match_requested.connect(self.on_manual_match_requested, Qt.BlockingQueuedConnection)
        self.worker.finished.connect(self.on_finished)
        self.worker.start()

    def on_manual_match_requested(self, payload: dict):
        """Affiche la fenêtre de sélection manuelle pour un licencié non trouvé.
        Le worker (thread d'import) est bloqué en attendant la réponse."""
        person = payload.get("person", {})
        dialog = ManualMatchDialog(person, payload.get("users", []), self)
        dialog.exec()
        # La réponse passe par l'attribut partagé du worker (le payload est copié par Qt)
        self.worker.manual_result["user_id"] = dialog.selected_user_id

        who = f"{person.get('nom', '')} {person.get('prenom', '')}".strip()
        if dialog.selected_user_id:
            self.log_area.append(f"🤝 [MANUEL] {who} associé manuellement à un adhérent de la base.")
        else:
            self.log_area.append(f"⏭️ [MANUEL] {who} ignoré (restera non trouvé).")

    def on_progress(self, message: str, percent: int):
        self.progress_bar.setValue(percent)
        self.log_area.append(message)

    def on_finished(self, success: bool, stats: dict):
        self.set_ui_enabled(True)
        self.progress_bar.setVisible(False)

        if success:
            self.log_area.append("\n🎉 [SUCCÈS] Traitement d'importation et de fusion FFME accompli !")
            
            self.lbl_stat_total.setText(f"📋 Lignes traitées : {stats['total_processed']}")
            self.lbl_stat_licence.setText(f"🟢 Associés par N° de licence (Statut Terminé) : {stats['matched_by_licence']}")
            self.lbl_stat_name.setText(f"🔑 Associés par Nom/Prénom (Nouveau N° enregistré & Statut Terminé) : {stats['matched_by_name']}")
            matched_manually = stats.get("matched_manually", 0)
            not_found = stats.get("not_found", 0)
            self.lbl_stat_notfound.setText(
                f"🔴 Licenciés FFME non trouvés en base locale : {not_found}"
                + (f"  (dont {matched_manually} associé(s) manuellement)" if matched_manually else "")
            )
            self.stats_frame.setVisible(True)

            try:
                parent_window = self.window()
                if hasattr(parent_window, "load_initial_data_async"):
                    parent_window.load_initial_data_async()
            except Exception:
                pass

            QMessageBox.information(
                self,
                "Importation réussie",
                f"Fusion terminée avec succès !\n\n"
                f"- Lignes traitées : {stats['total_processed']}\n"
                f"- Associés par licence : {stats['matched_by_licence']}\n"
                f"- Associés par nom/prénom : {stats['matched_by_name']}\n"
                f"- Associés manuellement : {stats.get('matched_manually', 0)}\n"
                f"- Non trouvés : {stats.get('not_found', 0)}"
            )
        else:
            errors = "\n".join(stats.get("errors", ["Une erreur inconnue est survenue."]))
            self.log_area.append(f"\n❌ [ERREUR] Le traitement a échoué :\n{errors}")
            QMessageBox.critical(
                self,
                "Échec de l'importation",
                f"Une erreur est survenue lors de l'importation :\n\n{errors}"
            )


class AutonomesImportWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()
        self.pre_detect_autonomes_file()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(15)

        # Description
        desc_lbl = QLabel(
            "Importez la liste Excel de suivi d'autonomie (Autonomes_*.xlsx). "
            "Le système mettra à jour pour chaque adhérent ses validations d'Autonomie Bloc et d'obtention "
            "du précieux Badge Rouge de Difficulté (grimpe en tête)."
        )
        desc_lbl.setWordWrap(True)
        desc_lbl.setStyleSheet("color: #64748B; font-size: 13px; margin-bottom: 5px;")
        layout.addWidget(desc_lbl)

        # ----------------- SECTION SELECTION DE FICHIER -----------------
        select_frame = QFrame()
        select_frame.setStyleSheet("""
            QFrame {
                background-color: #FFFFFF;
                border: 1px solid #E2E8F0;
                border-radius: 8px;
                padding: 15px;
            }
        """)
        select_layout = QVBoxLayout(select_frame)
        select_layout.setSpacing(12)

        select_title = QLabel("📂 Sélectionner la liste d'autonomie (Autonomes_*.xlsx)")
        select_title.setStyleSheet("font-size: 14px; font-weight: bold; color: #1E293B;")
        select_layout.addWidget(select_title)

        file_selection_layout = QHBoxLayout()
        self.file_path_input = QLineEdit()
        self.file_path_input.setReadOnly(True)
        self.file_path_input.setPlaceholderText("Aucun fichier sélectionné...")
        self.file_path_input.setStyleSheet("""
            QLineEdit {
                border: 1px solid #CBD5E1;
                border-radius: 6px;
                padding: 8px 12px;
                font-size: 13px;
                background-color: #F8FAFC;
                color: #334155;
            }
        """)
        file_selection_layout.addWidget(self.file_path_input)

        self.browse_btn = QPushButton("📁 Choisir un fichier...")
        self.browse_btn.setCursor(Qt.PointingHandCursor)
        self.browse_btn.setStyleSheet("""
            QPushButton {
                background-color: #F1F5F9;
                color: #334155;
                border: 1px solid #CBD5E1;
                border-radius: 6px;
                padding: 8px 16px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #E2E8F0;
            }
        """)
        self.browse_btn.clicked.connect(self.browse_file)
        file_selection_layout.addWidget(self.browse_btn)
        select_layout.addLayout(file_selection_layout)

        # Bouton d'action principal de fusion
        action_layout = QHBoxLayout()
        self.merge_btn = QPushButton("⚡ Lancer l'importation de l'Autonomie")
        self.merge_btn.setCursor(Qt.PointingHandCursor)
        self.merge_btn.setStyleSheet("""
            QPushButton {
                background-color: #EF4444;
                color: #FFFFFF;
                border: none;
                border-radius: 6px;
                padding: 10px 24px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #DC2626;
            }
            QPushButton:disabled {
                background-color: #94A3B8;
            }
        """)
        self.merge_btn.clicked.connect(self.start_merge_workflow)
        action_layout.addWidget(self.merge_btn)
        action_layout.addStretch()
        select_layout.addLayout(action_layout)

        layout.addWidget(select_frame)

        # ----------------- BARRE DE PROGRESSION -----------------
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #E2E8F0;
                border-radius: 6px;
                background-color: #FFFFFF;
                text-align: center;
                color: #1E293B;
                font-weight: bold;
            }
            QProgressBar::chunk {
                background-color: #EF4444;
                border-radius: 5px;
            }
        """)
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        # ----------------- SECTION RESULTATS & STATISTIQUES -----------------
        self.stats_frame = QFrame()
        self.stats_frame.setStyleSheet("""
            QFrame {
                background-color: #FFFFFF;
                border: 1px solid #E2E8F0;
                border-radius: 8px;
                padding: 15px;
            }
        """)
        self.stats_frame.setVisible(False)
        stats_layout = QVBoxLayout(self.stats_frame)
        stats_layout.setSpacing(8)

        stats_title = QLabel("📊 Résumé de l'import autonomie")
        stats_title.setStyleSheet("font-size: 14px; font-weight: bold; color: #1E293B; margin-bottom: 5px;")
        stats_layout.addWidget(stats_title)

        self.lbl_stat_total = QLabel("📋 Lignes traitées : -")
        self.lbl_stat_total.setStyleSheet("font-size: 13px; color: #334155;")
        stats_layout.addWidget(self.lbl_stat_total)

        self.lbl_stat_matched = QLabel("🟢 Grimpeurs mis à jour (Licence trouvée) : -")
        self.lbl_stat_matched.setStyleSheet("font-size: 13px; color: #16A34A; font-weight: bold;")
        stats_layout.addWidget(self.lbl_stat_matched)

        self.lbl_stat_notfound = QLabel("🔴 Licences introuvables ou invalides : -")
        self.lbl_stat_notfound.setStyleSheet("font-size: 13px; color: #DC2626;")
        stats_layout.addWidget(self.lbl_stat_notfound)

        # Statistiques supplémentaires demandées par l'utilisateur
        self.lbl_stat_file_badge_rouge = QLabel("🔴 Badges rouges trouvés dans le fichier : -")
        self.lbl_stat_file_badge_rouge.setStyleSheet("font-size: 13px; color: #E11D48;")
        stats_layout.addWidget(self.lbl_stat_file_badge_rouge)

        self.lbl_stat_db_total_badge_rouge = QLabel("🎯 Total de badges rouges enregistrés en BDD : -")
        self.lbl_stat_db_total_badge_rouge.setStyleSheet("font-size: 13px; color: #BE123C; font-weight: bold;")
        stats_layout.addWidget(self.lbl_stat_db_total_badge_rouge)

        self.lbl_stat_db_autonomes_without_badge = QLabel("🧗 Grimpeurs autonomes sans badge rouge : -")
        self.lbl_stat_db_autonomes_without_badge.setStyleSheet("font-size: 13px; color: #475569;")
        stats_layout.addWidget(self.lbl_stat_db_autonomes_without_badge)

        layout.addWidget(self.stats_frame)

        # ----------------- TRACE / LOG AREA -----------------
        log_title = QLabel("📝 Console de suivi d'importation Autonomie")
        log_title.setStyleSheet("font-size: 13px; font-weight: bold; color: #334155;")
        layout.addWidget(log_title)

        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setPlaceholderText("Les journaux d'importation s'afficheront ici en temps réel...")
        self.log_area.setStyleSheet("""
            QTextEdit {
                background-color: #1E293B;
                color: #F8FAFC;
                border: 1px solid #0F172A;
                border-radius: 8px;
                padding: 10px;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 12px;
            }
        """)
        layout.addWidget(self.log_area)

    def pre_detect_autonomes_file(self):
        # Chercher d'abord dans 'import/badge rouge'
        import_dir = os.path.join(ROOT_DIR, "import", "badge rouge")
        latest_file = None
        if os.path.exists(import_dir):
            files = glob.glob(os.path.join(import_dir, "Autonomes_*.xlsx"))
            if files:
                files.sort(key=os.path.getmtime, reverse=True)
                latest_file = files[0]
        
        # Fallback : Chercher directement à la racine ROOT_DIR
        if not latest_file:
            files = glob.glob(os.path.join(ROOT_DIR, "Autonomes_*.xlsx"))
            if files:
                files.sort(key=os.path.getmtime, reverse=True)
                latest_file = files[0]

        if latest_file:
            self.file_path_input.setText(latest_file)
            self.log_area.append(f"🔍 [SYSTEM] Fichier d'autonomie détecté automatiquement : {os.path.basename(latest_file)}")

    def browse_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Sélectionner la liste d'autonomie (Autonomes_*.xlsx)",
            ROOT_DIR,
            "Fichiers Excel (*.xlsx *.xls)"
        )
        if file_path:
            self.file_path_input.setText(file_path)
            self.log_area.append(f"📁 [FILE] Fichier sélectionné : {file_path}")

    def set_ui_enabled(self, enabled: bool):
        self.browse_btn.setEnabled(enabled)
        self.merge_btn.setEnabled(enabled)
        self.file_path_input.setEnabled(enabled)

    def start_merge_workflow(self):
        file_path = self.file_path_input.text().strip()
        if not file_path or not os.path.exists(file_path):
            QMessageBox.warning(
                self,
                "Fichier manquant",
                "Veuillez d'abord sélectionner un fichier Excel Autonomes valide pour lancer l'importation."
            )
            return

        self.set_ui_enabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.log_area.clear()
        self.stats_frame.setVisible(False)

        self.log_area.append("🚀 Démarrage du traitement d'importation d'autonomie...")

        self.worker = AutonomesMergeWorker(file_path)
        self.worker.progress.connect(self.on_progress)
        self.worker.finished.connect(self.on_finished)
        self.worker.start()

    def on_progress(self, message: str, percent: int):
        self.progress_bar.setValue(percent)
        self.log_area.append(message)

    def on_finished(self, success: bool, stats: dict):
        self.set_ui_enabled(True)
        self.progress_bar.setVisible(False)

        if success:
            self.log_area.append("\n🎉 [SUCCÈS] Traitement d'importation et de fusion Autonomie accompli !")
            
            # Logs supplémentaires demandés par l'utilisateur
            self.log_area.append("\n📊 [STATISTIQUES DE TRAITEMENT] :")
            self.log_area.append(f"  • Nombre d'adhérents avec badge rouge trouvés dans le fichier : {stats.get('file_badge_rouge_count', 0)}")
            self.log_area.append(f"  • Nombre d'adhérents qui ont le badge rouge en base de données : {stats.get('db_total_badge_rouge', 0)}")
            self.log_area.append(f"  • Nombre d'adhérents du groupe autonome sans badge rouge : {stats.get('db_autonomes_without_badge_rouge', 0)}")
            
            self.lbl_stat_total.setText(f"📋 Lignes traitées : {stats['total_processed']}")
            self.lbl_stat_matched.setText(f"🟢 Grimpeurs mis à jour (Licence trouvée) : {stats['matched']}")
            self.lbl_stat_notfound.setText(f"🔴 Licences introuvables ou invalides : {stats['not_found']}")
            self.lbl_stat_file_badge_rouge.setText(f"🔴 Badges rouges trouvés dans le fichier : {stats.get('file_badge_rouge_count', 0)}")
            self.lbl_stat_db_total_badge_rouge.setText(f"🎯 Total de badges rouges enregistrés en BDD : {stats.get('db_total_badge_rouge', 0)}")
            self.lbl_stat_db_autonomes_without_badge.setText(f"🧗 Grimpeurs autonomes sans badge rouge : {stats.get('db_autonomes_without_badge_rouge', 0)}")
            self.stats_frame.setVisible(True)

            try:
                parent_window = self.window()
                if hasattr(parent_window, "load_initial_data_async"):
                    parent_window.load_initial_data_async()
            except Exception:
                pass

            QMessageBox.information(
                self,
                "Importation réussie",
                f"Importation de l'autonomie terminée avec succès !\n\n"
                f"- Lignes traitées : {stats['total_processed']}\n"
                f"- Mis à jour (licence trouvée) : {stats['matched']}\n"
                f"- Licences introuvables : {stats['not_found']}\n\n"
                f"📊 Statistiques d'autonomie :\n"
                f"- Badges rouges dans le fichier : {stats.get('file_badge_rouge_count', 0)}\n"
                f"- Total de badges rouges en BDD : {stats.get('db_total_badge_rouge', 0)}\n"
                f"- Autonomes sans badge rouge : {stats.get('db_autonomes_without_badge_rouge', 0)}"
            )
        else:
            errors = "\n".join(stats.get("errors", ["Une erreur inconnue est survenue."]))
            self.log_area.append(f"\n❌ [ERREUR] Le traitement a échoué :\n{errors}")
            QMessageBox.critical(
                self,
                "Échec de l'importation",
                f"Une erreur est survenue lors de l'importation :\n\n{errors}"
            )


class SaisonImportWidget(QWidget):
    """
    Widget pour importer les données historiques d'anciennes saisons (FFME export format).
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()
        self.pre_detect_saison_file()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(15)

        # Description
        desc_lbl = QLabel(
            "Importez un fichier Excel d'export de licenciés FFME d'une ancienne saison (ex: Saison 2025-2026). "
            "Le système créera automatiquement les adhérents qui ne sont pas présents dans la base "
            "et les rattachera tous de façon persistante à la saison spécifiée."
        )
        desc_lbl.setWordWrap(True)
        desc_lbl.setStyleSheet("font-size: 12px; color: #475569; line-height: 1.5;")
        layout.addWidget(desc_lbl)

        # Cadre de configuration et sélection
        select_frame = QFrame()
        select_frame.setStyleSheet("""
            QFrame {
                background-color: #FFFFFF;
                border: 1px solid #E2E8F0;
                border-radius: 8px;
                padding: 15px;
            }
        """)
        select_layout = QVBoxLayout(select_frame)
        select_layout.setSpacing(12)

        # 1. Sélection de la saison
        season_config_layout = QHBoxLayout()
        season_lbl = QLabel("🎯 Sélectionner la saison cible de l'import :")
        season_lbl.setStyleSheet("font-size: 13px; font-weight: bold; color: #1E293B;")
        season_config_layout.addWidget(season_lbl)

        self.season_combo = QComboBox()
        self.season_combo.addItems(["2025-2026", "2026-2027"])
        self.season_combo.setCurrentText("2025-2026")
        self.season_combo.setStyleSheet("""
            QComboBox {
                border: 1px solid #CBD5E1;
                border-radius: 6px;
                padding: 5px 12px;
                font-size: 12px;
                font-weight: bold;
                color: #1E293B;
                min-width: 120px;
            }
        """)
        season_config_layout.addWidget(self.season_combo)
        season_config_layout.addStretch()
        select_layout.addLayout(season_config_layout)

        # Separator line
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setFrameShadow(QFrame.Sunken)
        sep.setStyleSheet("color: #E2E8F0;")
        select_layout.addWidget(sep)

        # 2. Sélection du fichier
        select_title = QLabel("📂 Sélectionner le fichier FFME de l'ancienne saison (.xlsx)")
        select_title.setStyleSheet("font-size: 13px; font-weight: bold; color: #1E293B;")
        select_layout.addWidget(select_title)

        file_selection_layout = QHBoxLayout()
        self.file_path_input = QLineEdit()
        self.file_path_input.setReadOnly(True)
        self.file_path_input.setPlaceholderText("Aucun fichier sélectionné...")
        self.file_path_input.setStyleSheet("""
            QLineEdit {
                border: 1px solid #CBD5E1;
                border-radius: 6px;
                padding: 8px 12px;
                font-size: 13px;
                background-color: #F8FAFC;
                color: #334155;
            }
        """)
        file_selection_layout.addWidget(self.file_path_input)

        self.browse_btn = QPushButton("📁 Choisir un fichier...")
        self.browse_btn.setCursor(Qt.PointingHandCursor)
        self.browse_btn.setStyleSheet("""
            QPushButton {
                background-color: #F1F5F9;
                color: #334155;
                border: 1px solid #CBD5E1;
                border-radius: 6px;
                padding: 8px 16px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #E2E8F0;
            }
        """)
        self.browse_btn.clicked.connect(self.browse_file)
        file_selection_layout.addWidget(self.browse_btn)
        select_layout.addLayout(file_selection_layout)

        # Bouton d'action principal de fusion
        action_layout = QHBoxLayout()
        self.merge_btn = QPushButton("⚡ Lancer l'importation de la saison")
        self.merge_btn.setCursor(Qt.PointingHandCursor)
        self.merge_btn.setStyleSheet("""
            QPushButton {
                background-color: #2563EB;
                color: #FFFFFF;
                border: none;
                border-radius: 6px;
                padding: 10px 24px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #1D4ED8;
            }
            QPushButton:disabled {
                background-color: #94A3B8;
            }
        """)
        self.merge_btn.clicked.connect(self.start_merge_workflow)
        action_layout.addWidget(self.merge_btn)
        action_layout.addStretch()
        select_layout.addLayout(action_layout)

        layout.addWidget(select_frame)

        # ----------------- BARRE DE PROGRESSION -----------------
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #E2E8F0;
                border-radius: 6px;
                background-color: #FFFFFF;
                text-align: center;
                color: #1E293B;
                font-weight: bold;
            }
            QProgressBar::chunk {
                background-color: #10B981;
                border-radius: 5px;
            }
        """)
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        # ----------------- SECTION RESULTATS & STATISTIQUES -----------------
        self.stats_frame = QFrame()
        self.stats_frame.setStyleSheet("""
            QFrame {
                background-color: #FFFFFF;
                border: 1px solid #E2E8F0;
                border-radius: 8px;
                padding: 15px;
            }
        """)
        self.stats_frame.setVisible(False)
        stats_layout = QVBoxLayout(self.stats_frame)
        stats_layout.setSpacing(8)

        stats_title = QLabel("📊 Statistiques de l'import de saison :")
        stats_title.setStyleSheet("font-size: 14px; font-weight: bold; color: #1E293B;")
        stats_layout.addWidget(stats_title)

        self.lbl_stat_processed = QLabel("• Licenciés traités : 0")
        self.lbl_stat_processed.setStyleSheet("font-size: 12px; color: #475569; font-weight: 500;")
        stats_layout.addWidget(self.lbl_stat_processed)

        self.lbl_stat_created = QLabel("• Nouveaux adhérents créés en base : 0")
        self.lbl_stat_created.setStyleSheet("font-size: 12px; color: #16A34A; font-weight: 500;")
        stats_layout.addWidget(self.lbl_stat_created)

        self.lbl_stat_linked = QLabel("• Adhérents rattachés à la saison : 0")
        self.lbl_stat_linked.setStyleSheet("font-size: 12px; color: #2563EB; font-weight: 500;")
        stats_layout.addWidget(self.lbl_stat_linked)

        layout.addWidget(self.stats_frame)

        # Console de Logs locale
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setPlaceholderText("Les logs du traitement de saison s'afficheront ici en direct...")
        self.log_area.setStyleSheet("""
            QTextEdit {
                background-color: #1E293B;
                color: #38BDF8;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 11px;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 10px;
                min-height: 120px;
            }
        """)
        layout.addWidget(self.log_area)

    def pre_detect_saison_file(self):
        """Tente de pré-détecter automatiquement le fichier d'ancienne saison de référence."""
        search_pattern = os.path.join(ROOT_DIR, "import", "ffme", "*Saison 2025-2026*.xlsx")
        files = glob.glob(search_pattern)
        if files:
            files.sort(key=os.path.getmtime, reverse=True)
            self.file_path_input.setText(files[0])
            self.log_area.append(f"🔍 [AUTO-DETECT] Fichier historique détecté : {os.path.basename(files[0])}")

    def browse_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Sélectionner la liste d'export FFME de saison",
            ROOT_DIR,
            "Fichiers Excel (*.xlsx *.xls)"
        )
        if file_path:
            self.file_path_input.setText(file_path)
            self.log_area.append(f"📂 Fichier sélectionné manuellement : {os.path.basename(file_path)}")

    def start_merge_workflow(self):
        file_path = self.file_path_input.text().strip()
        season_name = self.season_combo.currentText()
        if not file_path or not os.path.exists(file_path):
            QMessageBox.warning(self, "Fichier manquant", "Veuillez d'abord sélectionner un fichier Excel valide.")
            return

        self.merge_btn.setEnabled(False)
        self.browse_btn.setEnabled(False)
        self.season_combo.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(10)
        self.stats_frame.setVisible(False)
        self.log_area.clear()

        # Instancier et lancer le SaisonMergeWorker de manière non-bloquante !
        self.worker = SaisonMergeWorker(file_path, season_name)
        self.worker.progress.connect(self.on_progress)
        self.worker.finished.connect(self.on_finished)
        self.worker.start()

    def on_progress(self, message: str, percent: int):
        self.progress_bar.setValue(percent)
        self.log_area.append(message)

    def on_finished(self, success: bool, stats: dict):
        self.merge_btn.setEnabled(True)
        self.browse_btn.setEnabled(True)
        self.season_combo.setEnabled(True)
        self.progress_bar.setVisible(False)

        if success:
            self.log_area.append("\n==============================================")
            self.log_area.append("🎉 [SUCCÈS] Importation d'ancienne saison terminée !")
            self.log_area.append(f"- Total traités dans l'Excel : {stats['total_processed']}")
            self.log_area.append(f"- Nouveaux adhérents créés : {stats['created']}")
            self.log_area.append(f"- Liés à la saison {self.season_name} : {stats['linked']}")
            self.log_area.append("==============================================")

            self.lbl_stat_processed.setText(f"• Licenciés traités : {stats['total_processed']}")
            self.lbl_stat_created.setText(f"• Nouveaux adhérents créés en base : {stats['created']}")
            self.lbl_stat_linked.setText(f"• Adhérents rattachés à la saison : {stats['linked']}")
            self.stats_frame.setVisible(True)

            try:
                parent_window = self.window()
                if hasattr(parent_window, "load_initial_data_async"):
                    parent_window.load_initial_data_async()
            except Exception:
                pass

            QMessageBox.information(
                self,
                "Importation réussie",
                f"Importation de l'saison {self.season_name} terminée avec succès !\n\n"
                f"- Lignes traitées : {stats['total_processed']}\n"
                f"- Nouveaux adhérents créés : {stats['created']}\n"
                f"- Adhérents rattachés à la saison : {stats['linked']}"
            )
        else:
            errors = "\n".join(stats.get("errors", ["Une erreur inconnue est survenue."]))
            self.log_area.append(f"\n❌ [ERREUR] L'importation a échoué :\n{errors}")
            QMessageBox.critical(
                self,
                "Échec de l'importation",
                f"Une erreur est survenue lors de l'importation :\n\n{errors}"
            )
