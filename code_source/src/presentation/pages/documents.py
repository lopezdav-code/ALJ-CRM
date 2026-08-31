import os
import glob
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
    QLineEdit, QTextEdit, QProgressBar, QFrame, QListWidget, 
    QListWidgetItem, QSplitter, QComboBox
)
from PySide6.QtCore import Qt
from PIL import Image, ImageDraw

from paths import CODE_ROOT, ROOT_DIR
from domain.constants import get_corrective_files_pattern
from domain.models import Member
from infrastructure.sqlite_repository import SqliteRepository
from presentation.workers import GenerateAttestationsWorker

def generate_check_icon() -> str:
    """Génère une icône de coche blanche transparente pour le style personnalisé des checkboxes (sert à la fois pour documents et emails)."""
    icon_path = os.path.join(CODE_ROOT, "check_icon.png")
    if not os.path.exists(icon_path):
        try:
            img = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)
            draw.line([(3, 8), (7, 12)], fill=(255, 255, 255, 255), width=2)
            draw.line([(7, 12), (13, 4)], fill=(255, 255, 255, 255), width=2)
            img.save(icon_path, "PNG")
        except Exception:
            pass
    return icon_path.replace("\\", "/")

class DocumentsPage(QWidget):
    """
    Page de génération d'attestations Word et PDF asynchrone (Lot 5).
    Permet de filtrer et sélectionner individuellement les adhérents (comme l'onglet Communications).
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.members_list = []
        self.init_ui()
        # Ne pas charger de manière synchrone au démarrage pour optimiser le temps de lancement !

    def get_combobox_style(self) -> str:
        return """
            QComboBox {
                background-color: #FFFFFF;
                border: 1px solid #CBD5E1;
                border-radius: 6px;
                padding: 5px 8px;
                font-size: 11px;
                color: #475569;
                min-width: 110px;
            }
            QComboBox::drop-down {
                border: none;
            }
        """

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 15, 20, 20)
        layout.setSpacing(12)

        # Séparateur mobile horizontal (Splitter) pour séparer les Adhérents à gauche et la Configuration à droite
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setStyleSheet("""
            QSplitter::handle {
                background-color: #E2E8F0;
                width: 1px;
            }
        """)

        # ----------------------------------------------------
        # CÔTÉ GAUCHE : SÉLECTION DES BÉNÉFICIAIRES
        # ----------------------------------------------------
        left_container = QWidget()
        left_layout = QVBoxLayout(left_container)
        left_layout.setContentsMargins(0, 0, 10, 0)
        left_layout.setSpacing(10)

        self.dest_title = QLabel("🎯 Sélection des Bénéficiaires (0)")
        self.dest_title.setStyleSheet("font-size: 13px; font-weight: bold; color: #1E293B;")
        left_layout.addWidget(self.dest_title)

        # Barre de recherche d'adhérent
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("🔍 Filtrer par nom ou prénom...")
        self.search_input.setStyleSheet("""
            QLineEdit {
                background-color: #FFFFFF;
                border: 1px solid #CBD5E1;
                border-radius: 6px;
                padding: 6px 10px;
                font-size: 12px;
                color: #1E293B;
            }
        """)
        self.search_input.textChanged.connect(self.on_search_changed)
        left_layout.addWidget(self.search_input)

        # Barre de filtres avancés (Tarifs et état de génération)
        filters_bar = QHBoxLayout()
        filters_bar.setSpacing(6)

        # 0. Filtre par Saison (Nouveau !)
        self.season_filter = QComboBox()
        self.season_filter.addItems([
            "Saison 2026-2027 (Active)", 
            "Saison 2025-2026", 
            "Toutes les saisons confondues", 
            "Anciens non réinscrits (Présents en 25/26 mais pas en 26/27)"
        ])
        self.season_filter.setStyleSheet(self.get_combobox_style())
        self.season_filter.currentIndexChanged.connect(self.on_season_changed)
        filters_bar.addWidget(self.season_filter)

        # 1. Filtre par Tarif
        self.tarif_filter = QComboBox()
        self.tarif_filter.addItems(["Tous les tarifs"])
        self.tarif_filter.setStyleSheet(self.get_combobox_style())
        self.tarif_filter.currentIndexChanged.connect(self.on_filters_changed)
        filters_bar.addWidget(self.tarif_filter)

        # 2. Filtre Attestation générée
        self.attestation_filter = QComboBox()
        self.attestation_filter.addItems(["Toutes attestations", "Générées (.pdf)", "Non générées"])
        self.attestation_filter.setStyleSheet(self.get_combobox_style())
        self.attestation_filter.currentIndexChanged.connect(self.on_filters_changed)
        filters_bar.addWidget(self.attestation_filter)

        left_layout.addLayout(filters_bar)

        # Boutons de sélection globale
        selection_btns = QHBoxLayout()
        selection_btns.setSpacing(6)

        check_all_btn = QPushButton("Cocher le filtre")
        check_all_btn.setCursor(Qt.PointingHandCursor)
        check_all_btn.setStyleSheet("""
            QPushButton {
                background-color: #FFFFFF;
                border: 1px solid #CBD5E1;
                border-radius: 4px;
                padding: 5px 10px;
                font-size: 11px;
                font-weight: 500;
                color: #2563EB;
            }
            QPushButton:hover {
                background-color: #EFF6FF;
                border-color: #BFDBFE;
            }
        """)
        check_all_btn.clicked.connect(self.select_visible)
        selection_btns.addWidget(check_all_btn)

        uncheck_all_btn = QPushButton("Décocher le filtre")
        uncheck_all_btn.setCursor(Qt.PointingHandCursor)
        uncheck_all_btn.setStyleSheet("""
            QPushButton {
                background-color: #FFFFFF;
                border: 1px solid #CBD5E1;
                border-radius: 4px;
                padding: 5px 10px;
                font-size: 11px;
                font-weight: 500;
                color: #EF4444;
            }
            QPushButton:hover {
                background-color: #FEF2F2;
                border-color: #FCA5A5;
            }
        """)
        uncheck_all_btn.clicked.connect(self.deselect_visible)
        selection_btns.addWidget(uncheck_all_btn)

        selection_btns.addStretch()
        left_layout.addLayout(selection_btns)

        # List Widget contenant les checkboxes d'adhérents (avec notre style Vert ALJ !)
        icon_url = generate_check_icon()
        self.list_widget = QListWidget()
        self.list_widget.setStyleSheet(f"""
            QListWidget {{
                background-color: #FFFFFF;
                border: 1px solid #E2E8F0;
                border-radius: 6px;
                padding: 5px;
            }}
            QListWidget::item {{
                padding: 8px 10px;
                border-bottom: 1px solid #F1F5F9;
                font-size: 12px;
                color: #1E293B;
            }}
            QListWidget::item:hover {{
                background-color: #F8FAFC;
            }}
            QListWidget::indicator {{
                width: 16px;
                height: 16px;
                border: 1.5px solid #CBD5E1;
                border-radius: 4px;
                background-color: #FFFFFF;
            }}
            QListWidget::indicator:hover {{
                border-color: #10B981;
            }}
            QListWidget::indicator:checked {{
                background-color: #10B981;
                border-color: #10B981;
                image: url({icon_url});
            }}
        """)
        self.list_widget.itemChanged.connect(self.update_selection_count)
        left_layout.addWidget(self.list_widget)

        self.splitter.addWidget(left_container)

        # ----------------------------------------------------
        # CÔTÉ DROIT : OPTIONS DE GÉNÉRATION & LOGS
        # ----------------------------------------------------
        right_container = QWidget()
        right_layout = QVBoxLayout(right_container)
        right_layout.setContentsMargins(10, 0, 0, 0)
        right_layout.setSpacing(15)

        config_frame = QFrame()
        config_frame.setStyleSheet("""
            QFrame {
                background-color: #FFFFFF;
                border: 1px solid #E2E8F0;
                border-radius: 8px;
                padding: 15px;
            }
        """)
        config_layout = QVBoxLayout(config_frame)
        config_layout.setSpacing(10)

        config_layout.addWidget(QLabel("Format d'export de l'attestation :"))
        self.format_combo = QComboBox()
        self.format_combo.addItems(["PDF uniquement (.pdf)", "Word uniquement (.docx)", "Les deux (Word + PDF)"])
        self.format_combo.setStyleSheet("""
            QComboBox {
                background-color: #FFFFFF;
                border: 1px solid #CBD5E1;
                border-radius: 6px;
                padding: 8px;
                color: #1E293B;
            }
            QComboBox::drop-down {
                border: none;
            }
        """)
        config_layout.addWidget(self.format_combo)

        # Bouton Lancer la génération
        self.generate_btn = QPushButton("🚀 Lancer la génération des attestations")
        self.generate_btn.setCursor(Qt.PointingHandCursor)
        self.generate_btn.setStyleSheet("""
            QPushButton {
                background-color: #2563EB;
                color: #FFFFFF;
                border: none;
                border-radius: 6px;
                padding: 10px 20px;
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
        self.generate_btn.clicked.connect(self.start_generation)
        config_layout.addWidget(self.generate_btn)

        # Bouton Ouvrir le dossier des attestations
        self.open_folder_btn = QPushButton("📁 Ouvrir le dossier des attestations")
        self.open_folder_btn.setCursor(Qt.PointingHandCursor)
        self.open_folder_btn.setStyleSheet("""
            QPushButton {
                background-color: #F8FAFC;
                color: #475569;
                border: 1px solid #CBD5E1;
                border-radius: 6px;
                padding: 10px 20px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #F1F5F9;
                color: #1E293B;
                border-color: #94A3B8;
            }
        """)
        self.open_folder_btn.clicked.connect(self.open_attestation_folder)
        config_layout.addWidget(self.open_folder_btn)

        right_layout.addWidget(config_frame)

        # Barre de progression
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
        right_layout.addWidget(self.progress_bar)

        # Zone de logs
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setPlaceholderText("Les traces de fusion et d'export s'afficheront ici...")
        self.log_area.setStyleSheet("""
            QTextEdit {
                background-color: #1E293B;
                color: #38BDF8;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 12px;
                border-radius: 8px;
                padding: 10px;
                min-height: 100px;
            }
        """)
        right_layout.addWidget(self.log_area)

        self.splitter.addWidget(right_container)

        self.splitter.setStretchFactor(0, 1) # Destinataires
        self.splitter.setStretchFactor(1, 2) # Formulaire

        layout.addWidget(self.splitter)

    def on_season_changed(self):
        """Déclenché lorsque l'utilisateur change de saison dans la liste déroulante."""
        self.load_members(members_list=None)

    def load_members(self, members_list=None):
        """Récupère et liste les adhérents disponibles pour la génération d'attestations (compatible multi-saisons)."""
        if members_list is not None:
            self.members_list = members_list
        else:
            try:
                # Récupérer la saison sélectionnée dans l'IHM (Nouveau !)
                season_text = self.season_filter.currentText()
                if "2026-2027" in season_text:
                    season_filter_val = "2026-2027"
                elif "2025-2026" in season_text:
                    season_filter_val = "2025-2026"
                elif "Anciens" in season_text:
                    season_filter_val = "Non réinscrits"
                else:
                    season_filter_val = "Tous"
                    
                raw_data = SqliteRepository.load_direct_data(season_filter=season_filter_val)
                self.members_list = [Member.from_dict(row) for row in raw_data]
            except Exception as e:
                self.dest_title.setText(f"❌ Erreur lors du chargement : {e}")
                self.generate_btn.setEnabled(False)
                return

        try:
            self.list_widget.blockSignals(True)
            self.list_widget.clear()
            
            for m in self.members_list:
                item = QListWidgetItem(f"{m.user_last_name} {m.user_first_name} — (Tarif : {m.tarif_name})")
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Unchecked) # Décoché par défaut
                item.setData(Qt.UserRole, m) # Stocker le membre
                self.list_widget.addItem(item)
            
            # Charger la liste des tarifs dans le ComboBox
            unique_tarifs = sorted(list(set([m.tarif_name for m in self.members_list if m.tarif_name])))
            self.tarif_filter.clear()
            self.tarif_filter.addItem("Tous les tarifs")
            self.tarif_filter.addItems(unique_tarifs)

            self.list_widget.blockSignals(False)
            self.update_selection_count()
            
        except Exception as e:
            self.dest_title.setText(f"❌ Erreur lors du chargement : {e}")
            self.generate_btn.setEnabled(False)

    def on_search_changed(self, text: str):
        self.on_filters_changed()

    def on_filters_changed(self):
        """Filtre l'affichage de la liste des bénéficiaires en combinant la recherche, le tarif et l'état d'attestation."""
        search_text = self.search_input.text().strip().lower()
        tarif_sel = self.tarif_filter.currentText()
        att_sel = self.attestation_filter.currentText()

        self.list_widget.blockSignals(True)
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            m = item.data(Qt.UserRole)
            
            # 1. Recherche textuelle
            match_search = (
                not search_text or
                search_text in m.user_last_name.lower() or
                search_text in m.user_first_name.lower()
            )
            
            # 2. Filtre de tarif
            match_tarif = (tarif_sel == "Tous les tarifs" or m.tarif_name == tarif_sel)
            
            # 3. Filtre d'attestation générée
            from attestation_generator import get_safe_filename
            filename = get_safe_filename(m.user_last_name, m.user_first_name, m.order_ref)
            pdf_path = os.path.join(ROOT_DIR, "exports", "attestation", filename.replace(".docx", ".pdf"))
            has_pdf = os.path.exists(pdf_path)
            
            match_att = True
            if att_sel == "Générées (.pdf)" and not has_pdf:
                match_att = False
            elif att_sel == "Non générées" and has_pdf:
                match_att = False
                
            # Cacher/Afficher l'item
            item.setHidden(not (match_search and match_tarif and match_att))
            
        self.list_widget.blockSignals(False)
        self.update_selection_count()

    def select_visible(self):
        """Coche uniquement les adhérents visibles (ceux qui passent le filtre actif)."""
        self.list_widget.blockSignals(True)
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if not item.isHidden():
                item.setCheckState(Qt.Checked)
        self.list_widget.blockSignals(False)
        self.update_selection_count()

    def deselect_visible(self):
        """Décoche uniquement les adhérents visibles (ceux qui passent le filtre actif)."""
        self.list_widget.blockSignals(True)
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if not item.isHidden():
                item.setCheckState(Qt.Unchecked)
        self.list_widget.blockSignals(False)
        self.update_selection_count()

    def update_selection_count(self):
        """Calcule et affiche le nombre de bénéficiaires sélectionnés."""
        checked_count = 0
        for i in range(self.list_widget.count()):
            if self.list_widget.item(i).checkState() == Qt.Checked:
                checked_count += 1
        
        self.dest_title.setText(f"🎯 Sélection des Bénéficiaires ({checked_count})")
        self.generate_btn.setEnabled(checked_count > 0)

    def open_attestation_folder(self):
        """Ouvre le dossier des attestations dans l'explorateur Windows."""
        folder_path = os.path.join(ROOT_DIR, "exports", "attestation")
        if not os.path.exists(folder_path):
            os.makedirs(folder_path)
        try:
            os.startfile(folder_path)
        except Exception as e:
            self.log_area.append(f"❌ Impossible d'ouvrir le dossier : {e}")

    def start_generation(self):
        """Déclenche la compilation des reçus fiscaux en tâche de fond pour les adhérents cochés (non bloquant)."""
        # Récupérer les données de membres cochés sous forme de dictionnaires bruts pour generate_all_attestations
        selected_raw_members = []
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.checkState() == Qt.Checked:
                selected_raw_members.append(item.data(Qt.UserRole).to_dict())

        if not selected_raw_members:
            return

        self.last_selected_members = selected_raw_members # Sauvegarder pour pouvoir ouvrir l'attestation si 1 seule générée

        self.generate_btn.setEnabled(False)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)
        self.log_area.clear()

        # Mapper le choix de format
        fmt_idx = self.format_combo.currentIndex()
        fmt_map = {0: "pdf", 1: "docx", 2: "both"}
        selected_format = fmt_map.get(fmt_idx, "pdf")

        self.log_area.append(f"ℹ️ [INFO] Initialisation de la génération pour {len(selected_raw_members)} adhérent(s) sélectionné(s)...")
        
        # Lancer le Worker en lui passant spécifiquement la liste sélectionnée !
        self.worker = GenerateAttestationsWorker(
            output_format=selected_format,
            members=selected_raw_members
        )
        self.worker.progress.connect(self.on_progress)
        self.worker.finished.connect(self.on_finished)
        self.worker.start()

    def on_progress(self, message: str, percent: int):
        self.progress_bar.setValue(percent)
        self.log_area.append(message)

    def on_finished(self, generated: int, skipped: int, errors: int):
        self.generate_btn.setEnabled(True)
        self.log_area.append("\n==============================================")
        self.log_area.append("🎉 [SUCCÈS] Génération documentaire terminée !")
        self.log_area.append(f"📄 Attestations générées avec succès : {generated}")
        if errors > 0:
            self.log_area.append(f"❌ Échecs de génération : {errors}")
        self.log_area.append("==============================================")
        self.update_selection_count()

        # Si une seule attestation a été générée (ou sautée car déjà existante), on l'ouvre directement
        if (generated == 1 or skipped == 1) and hasattr(self, 'last_selected_members') and len(self.last_selected_members) == 1:
            member = self.last_selected_members[0]
            user_last = member.get("user_lastName", "").strip()
            user_first = member.get("user_firstName", "").strip()
            order_ref = member.get("order_ref", "")
            
            from attestation_generator import get_safe_filename
            filename_docx = get_safe_filename(user_last.upper(), user_first.capitalize(), order_ref)
            
            fmt_idx = self.format_combo.currentIndex()
            output_dir = os.path.join(ROOT_DIR, "exports", "attestation")
            
            target_file = None
            if fmt_idx in (0, 2):  # pdf ou both
                target_file = os.path.join(output_dir, filename_docx.replace(".docx", ".pdf"))
            else:
                target_file = os.path.join(output_dir, filename_docx)
                
            if target_file and os.path.exists(target_file):
                try:
                    self.log_area.append(f"🗂️ Ouverture automatique de l'attestation : {os.path.basename(target_file)}")
                    os.startfile(target_file)
                except Exception as e:
                    self.log_area.append(f"❌ Impossible d'ouvrir l'attestation : {e}")
