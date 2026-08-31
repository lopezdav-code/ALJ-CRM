import os
import glob
import datetime
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, 
    QTableView, QHeaderView, QFrame, QSplitter, QComboBox,
    QDateEdit, QCheckBox
)
from PySide6.QtCore import Qt, QSortFilterProxyModel, QDate

from paths import CODE_ROOT, ROOT_DIR
from domain.constants import get_corrective_files_pattern
from domain.models import Member
from infrastructure.sqlite_repository import SqliteRepository
from presentation.components.member_table_model import MemberTableModel
from presentation.components.member_detail_panel import MemberDetailPanel

class MembersPage(QWidget):
    """
    Page de gestion des Adhérents avec table hautes performances, filtres croisés et fiche détaillée.
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

        # Barre de recherche principale
        search_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("🔍 Rechercher un adhérent (Nom, prénom, commande...)")
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
        self.search_input.textChanged.connect(self.on_search_changed)
        search_layout.addWidget(self.search_input)
        layout.addLayout(search_layout)

        # Barre des Filtres (Saison, Email valide, Tarifs, Email envoyé, Attestation générée)
        filters_layout = QHBoxLayout()
        filters_layout.setSpacing(8)

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
        filters_layout.addWidget(self.season_filter)

        # 1. Filtre par statut de commande
        self.status_filter = QComboBox()
        self.status_filter.addItems(["Tous les statuts", "Validated", "Terminé", "En cours", "Annulé"])
        self.status_filter.setStyleSheet(self.get_combobox_style())
        self.status_filter.currentIndexChanged.connect(self.on_filters_changed)
        filters_layout.addWidget(self.status_filter)

        # 2. Découpe du filtre des tarifs en deux sous-filtres
        # 2a. Filtre de catégorie de tarif
        self.tarif_type_filter = QComboBox()
        self.tarif_type_filter.addItems(["Tous les types", "Séance autonome", "Cours", "Compétition"])
        self.tarif_type_filter.setStyleSheet(self.get_combobox_style())
        self.tarif_type_filter.currentIndexChanged.connect(self.on_tarif_type_changed)
        filters_layout.addWidget(self.tarif_type_filter)

        # 2b. Filtre de sous-catégorie (tarif spécifique)
        self.tarif_sub_filter = QComboBox()
        self.tarif_sub_filter.addItems(["Toutes les sous-catégories"])
        self.tarif_sub_filter.setStyleSheet(self.get_combobox_style())
        self.tarif_sub_filter.currentIndexChanged.connect(self.on_filters_changed)
        filters_layout.addWidget(self.tarif_sub_filter)

        # 3. Filtre Adresse mail valide
        self.email_filter = QComboBox()
        self.email_filter.addItems(["Tous les e-mails", "Avec e-mail", "Sans e-mail"])
        self.email_filter.setStyleSheet(self.get_combobox_style())
        self.email_filter.currentIndexChanged.connect(self.on_filters_changed)
        filters_layout.addWidget(self.email_filter)

        # 4. Filtre Email envoyé
        self.sent_filter = QComboBox()
        self.sent_filter.addItems(["Tous les envois", "Non envoyés", "Envoyés"])
        self.sent_filter.setStyleSheet(self.get_combobox_style())
        self.sent_filter.currentIndexChanged.connect(self.on_filters_changed)
        filters_layout.addWidget(self.sent_filter)

        # 5. Filtre Attestation générée (Masqué !)
        self.attestation_filter = QComboBox()
        self.attestation_filter.addItems(["Toutes les attestations", "Générées (.pdf)", "Non générées"])
        self.attestation_filter.setStyleSheet(self.get_combobox_style())
        self.attestation_filter.currentIndexChanged.connect(self.on_filters_changed)
        filters_layout.addWidget(self.attestation_filter)
        self.attestation_filter.setVisible(False) # Masquer le filtre visuellement

        # 5b. Case à cocher : Nouveau membre
        self.new_member_checkbox = QCheckBox("Nouveau membre")
        self.new_member_checkbox.setStyleSheet("color: #475569; font-size: 11px; font-weight: 500; margin-left: 8px;")
        self.new_member_checkbox.stateChanged.connect(self.on_filters_changed)
        filters_layout.addWidget(self.new_member_checkbox)

        # 6. Nouveau Filtre Calendrier : Inscrit après le (QDateEdit + QCheckBox) !
        date_filter_layout = QHBoxLayout()
        date_filter_layout.setSpacing(4)

        self.date_checkbox = QCheckBox("Inscrit après le :")
        self.date_checkbox.setStyleSheet("color: #475569; font-size: 11px; font-weight: 500;")
        self.date_checkbox.stateChanged.connect(self.on_filters_changed)
        date_filter_layout.addWidget(self.date_checkbox)

        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True) # Affiche un calendrier pop-up visuel !
        self.date_edit.setDate(QDate(2026, 7, 1)) # Par défaut au début de la saison d'été
        self.date_edit.setStyleSheet("""
            QDateEdit {
                background-color: #FFFFFF;
                border: 1px solid #CBD5E1;
                border-radius: 6px;
                padding: 4px 6px;
                font-size: 11px;
                color: #475569;
            }
        """)
        self.date_edit.dateChanged.connect(self.on_filters_changed)
        date_filter_layout.addWidget(self.date_edit)

        filters_layout.addLayout(date_filter_layout)
        layout.addLayout(filters_layout)

        # Séparateur mobile (Splitter) pour diviser la table et la fiche adhérent
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setStyleSheet("""
            QSplitter::handle {
                background-color: #E2E8F0;
                width: 1px;
            }
        """)

        # Côté gauche : Table View
        table_container = QWidget()
        table_layout = QVBoxLayout(table_container)
        table_layout.setContentsMargins(0, 0, 0, 0)

        self.table_view = QTableView()
        self.table_view.setSelectionBehavior(QTableView.SelectRows)
        self.table_view.setSelectionMode(QTableView.SingleSelection)
        self.table_view.setSortingEnabled(True)
        self.table_view.setStyleSheet("""
            QTableView {
                background-color: #FFFFFF;
                border: 1px solid #E2E8F0;
                border-radius: 6px;
                gridline-color: #F1F5F9;
            }
            QHeaderView::section {
                background-color: #F8FAFC;
                color: #64748B;
                padding: 8px;
                font-weight: bold;
                border: none;
                border-bottom: 1px solid #E2E8F0;
            }
        """)

        # Configuration des modèles
        self.base_model = MemberTableModel([])
        self.proxy_model = QSortFilterProxyModel()
        self.proxy_model.setSourceModel(self.base_model)
        self.proxy_model.setFilterKeyColumn(-1)
        self.proxy_model.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self.proxy_model.setSortRole(Qt.EditRole) # Trier par valeur brute (Dates, Montants, Licences...)
        
        self.table_view.setModel(self.proxy_model)
        self.table_view.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table_view.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents) # N° Licence
        self.table_view.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents) # Date Inscription
        self.table_view.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeToContents) # Diplômes / Autonomie
        
        # Connecter la sélection de la table
        self.table_view.selectionModel().selectionChanged.connect(self.on_selection_changed)

        table_layout.addWidget(self.table_view)
        
        # Ajouter le compteur de ligne dynamique
        self.counter_label = QLabel()
        self.counter_label.setStyleSheet("color: #64748B; font-size: 11px; font-weight: bold; margin-top: 4px; margin-left: 5px;")
        table_layout.addWidget(self.counter_label)
        
        self.splitter.addWidget(table_container)

        # Côté droit : Fiche Adhérent (cachée par défaut)
        self.detail_panel = MemberDetailPanel()
        self.detail_panel.closed.connect(self.hide_detail_panel)
        self.detail_panel.member_updated.connect(self.on_member_updated) # Nouveau !
        self.detail_panel.setVisible(False)
        self.splitter.addWidget(self.detail_panel)

        self.splitter.setStretchFactor(0, 4)
        self.splitter.setStretchFactor(1, 1)

        layout.addWidget(self.splitter)

    def get_tariff_category(self, tarif_name: str) -> str:
        """Retourne la catégorie principale associée à un nom de tarif."""
        if not tarif_name:
            return "Autre"
        t_lower = tarif_name.lower()
        if "autonome" in t_lower:
            return "Séance autonome"
        elif "compétition" in t_lower or "compet" in t_lower:
            return "Compétition"
        elif "cours" in t_lower or "loisir" in t_lower or "perfectionnement" in t_lower:
            return "Cours"
        return "Autre"

    def on_tarif_type_changed(self):
        """Déclenché lorsque la catégorie de tarif principale change."""
        type_sel = self.tarif_type_filter.currentText()
        
        # Bloquer temporairement les signaux pour éviter de déclencher on_filters_changed en boucle
        self.tarif_sub_filter.blockSignals(True)
        self.tarif_sub_filter.clear()
        self.tarif_sub_filter.addItem("Toutes les sous-catégories")
        
        # Filtrer les tarifs uniques selon la catégorie principale sélectionnée
        unique_tarifs = sorted(list(set([m.tarif_name for m in self.members_list if m.tarif_name])))
        
        filtered_sub = []
        for t in unique_tarifs:
            cat = self.get_tariff_category(t)
            if type_sel == "Tous les types" or cat == type_sel:
                filtered_sub.append(t)
                
        self.tarif_sub_filter.addItems(filtered_sub)
        self.tarif_sub_filter.blockSignals(False)
        
        # Déclencher le filtrage global
        self.on_filters_changed()

    def on_season_changed(self):
        """Déclenché lorsque l'utilisateur change de saison dans la liste déroulante."""
        self.load_members_from_repository(force_reload=True)

    def load_members_from_repository(self, force_reload=False):
        """Charge très rapidement les adhérents depuis SQLite avec mise en cache mémoire."""
        if self.members_list and not force_reload:
            return # Utiliser le cache en mémoire, chargement instantané !

        try:
            # Récupérer le filtre de saison de l'IHM (Nouveau !)
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
            
            self.members_list = []
            for idx, row in enumerate(raw_data):
                m = Member.from_dict(row)
                from domain.constants import get_active_season
                try:
                    season_yr = get_active_season().split("-")[0][-2:]
                except Exception:
                    season_yr = "26"
                m.member_id = f"ALJ-{season_yr}-{idx + 1:03d}"
                self.members_list.append(m)
            
            # Mettre à jour le modèle
            self.base_model.update_data(self.members_list)
            self.update_counter(len(self.members_list))
            
            # Mettre à jour les deux sous-filtres des tarifs
            # On réinitialise d'abord le type de tarif à "Tous les types" pour repeupler correctement
            self.tarif_type_filter.blockSignals(True)
            self.tarif_type_filter.setCurrentIndex(0)
            self.tarif_type_filter.blockSignals(False)
            
            # Repeupler le filtre des sous-catégories
            self.on_tarif_type_changed()
            
            print(f"✅ [MEMBERS] {len(self.members_list)} adhérents chargés dans l'IHM depuis SQLite.")
        except Exception as e:
            print(f"❌ [MEMBERS] Erreur lors du peuplement de la liste : {e}")

    def on_search_changed(self, text: str):
        self.on_filters_changed()

    def on_filters_changed(self):
        """Filtre la table en croisant toutes les options de filtres sélectionnées."""
        search_text = self.search_input.text().strip().lower()
        status_sel = self.status_filter.currentText()
        type_sel = self.tarif_type_filter.currentText()
        sub_sel = self.tarif_sub_filter.currentText()
        email_sel = self.email_filter.currentText()
        sent_sel = self.sent_filter.currentText()
        att_sel = self.attestation_filter.currentText()

        filtered = []
        for m in self.members_list:
            # 1. Recherche textuelle
            match_search = (
                not search_text or
                search_text in m.user_last_name.lower() or
                search_text in m.user_first_name.lower() or
                search_text in m.order_ref.lower()
            )
            if not match_search:
                continue

            # 2. Filtre de statut de commande
            if status_sel != "Tous les statuts" and m.status != status_sel:
                continue

            # 3. Filtre de tarif (catégorie principale et sous-catégorie)
            if type_sel != "Tous les types":
                m_cat = self.get_tariff_category(m.tarif_name)
                if m_cat != type_sel:
                    continue
            
            if sub_sel != "Toutes les sous-catégories" and m.tarif_name != sub_sel:
                continue

            # 4. Filtre avec ou sans email
            has_email = bool(m.primary_email or m.payer_email)
            if email_sel == "Avec e-mail" and not has_email:
                continue
            if email_sel == "Sans e-mail" and has_email:
                continue

            # 5. Filtre email envoyé
            is_sent = bool(m.email_sent_date)
            if sent_sel == "Envoyés" and not is_sent:
                continue
            if sent_sel == "Non envoyés" and is_sent:
                continue

            # 6. Filtre attestation générée
            from attestation_generator import get_safe_filename
            filename = get_safe_filename(m.user_last_name, m.user_first_name, m.order_ref)
            pdf_path = os.path.join(ROOT_DIR, "exports", "attestation", filename.replace(".docx", ".pdf"))
            has_pdf = os.path.exists(pdf_path)
            
            if att_sel == "Générées (.pdf)" and not has_pdf:
                continue
            if att_sel == "Non générées" and has_pdf:
                continue

            # 7. Nouveau Filtre d'inscription après la date sélectionnée (croisement ultra-robuste)
            if self.date_checkbox.isChecked():
                import pandas as pd
                filter_qdate = self.date_edit.date()
                # Créer un objet datetime comparable
                filter_dt = datetime.datetime(filter_qdate.year(), filter_qdate.month(), filter_qdate.day())
                
                try:
                    m_dt = pd.to_datetime(m.order_date)
                    if pd.isna(m_dt) or m_dt.to_pydatetime() < filter_dt:
                        continue
                except Exception:
                    continue

            # 8. Filtre Nouveau membre (déjà adhérent == Non)
            if self.new_member_checkbox.isChecked():
                if m.already_member != "Non":
                    continue

            filtered.append(m)

        self.base_model.update_data(filtered)
        self.update_counter(len(filtered))

    def update_counter(self, count: int):
        total = len(self.members_list)
        self.counter_label.setText(f"📋 {count} adhérent(s) affiché(s) sur {total} au total")

    def on_selection_changed(self, selected, deselected):
        indexes = self.table_view.selectionModel().selectedRows()
        if not indexes:
            self.hide_detail_panel()
            return

        proxy_idx = indexes[0]
        source_idx = self.proxy_model.mapToSource(proxy_idx)
        
        member = self.base_model.members[source_idx.row()]
        
        self.detail_panel.set_member(member)
        self.detail_panel.setVisible(True)

    def hide_detail_panel(self):
        self.table_view.clearSelection()
        self.detail_panel.setVisible(False)

    def on_member_updated(self):
        """Déclenché après qu'un adhérent a été édité et sauvegardé avec succès dans l'Excel."""
        # Forcer le rechargement depuis l'Excel local (pour actualiser le modèle de table !)
        self.load_members_from_repository(force_reload=True)
