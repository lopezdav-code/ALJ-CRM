import os
import datetime
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QTableView, QHeaderView, QSplitter, QComboBox,
    QDateEdit, QCheckBox, QPushButton, QDialog, QScrollArea,
    QFrame, QDialogButtonBox, QRadioButton, QMessageBox
)
from PySide6.QtCore import Qt, QSortFilterProxyModel, QDate, Signal

from paths import ROOT_DIR
from domain.models import Member
from infrastructure.sqlite_repository import SqliteRepository
from infrastructure.schema_v2 import normalize_status
from presentation.components.member_table_model import MemberTableModel
from presentation.components.member_detail_panel import MemberDetailPanel

# Tarif isolé dans son propre sous-groupe de la pop-up de sélection, désélectionné par défaut
WAITING_LIST_TARIF = "Liste d'attente cours"

# Statut désélectionné par défaut dans la pop-up des statuts (onglet Communications)
# pour ne jamais envoyer d'e-mail aux personnes ayant annulé leur inscription.
CANCELLED_STATUS = "Annulé"

class TarifEditDialog(QDialog):
    """
    Pop-up de changement de groupe (tarif HelloAsso) d'un adhérent :
    liste à boutons radio des tarifs disponibles pour la saison active.
    Le tarif actuel de l'adhérent est présélectionné.
    """
    def __init__(self, member, tarifs: list, parent=None):
        super().__init__(parent)
        self.member = member
        self.tarifs = tarifs or []
        self.selected_tarif = None
        self.radio_buttons = []
        self.setWindowTitle("Changer de groupe (Tarif)")
        self.setMinimumWidth(440)
        self.setMinimumHeight(480)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(12)

        # Rappel de l'adhérent et de son tarif actuel
        current = str(self.member.tarif_name or "").strip()
        info_lbl = QLabel(
            f"<b>{str(self.member.user_last_name or '').upper()} {str(self.member.user_first_name or '')}</b><br>"
            f"Tarif actuel : <b>{current or 'Aucun'}</b>"
        )
        info_lbl.setStyleSheet("font-size: 12px; color: #1E293B;")
        layout.addWidget(info_lbl)

        desc_lbl = QLabel("Sélectionnez le nouveau groupe (tarif) pour la saison active :")
        desc_lbl.setWordWrap(True)
        desc_lbl.setStyleSheet("font-size: 11px; color: #64748B;")
        layout.addWidget(desc_lbl)

        # Zone défilante avec un bouton radio par tarif disponible
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(4, 4, 4, 4)
        container_layout.setSpacing(5)

        for tarif in self.tarifs:
            rb = QRadioButton(tarif)
            rb.setCursor(Qt.PointingHandCursor)
            rb.setStyleSheet("""
                QRadioButton {
                    color: #1E293B;
                    font-size: 12px;
                    spacing: 6px;
                }
                QRadioButton::indicator {
                    width: 14px;
                    height: 14px;
                }
            """)
            if current and tarif.strip().lower() == current.lower():
                rb.setChecked(True)
            container_layout.addWidget(rb)
            self.radio_buttons.append(rb)

        if not self.radio_buttons:
            empty_lbl = QLabel("Aucun tarif disponible pour la saison active.")
            empty_lbl.setStyleSheet("color: #64748B; font-style: italic; font-size: 11px;")
            container_layout.addWidget(empty_lbl)

        container_layout.addStretch(1)
        scroll.setWidget(container)
        layout.addWidget(scroll, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Valider")
        buttons.button(QDialogButtonBox.Cancel).setText("Annuler")
        buttons.setStyleSheet("""
            QPushButton {
                background-color: #2563EB;
                color: #FFFFFF;
                border: none;
                border-radius: 6px;
                padding: 6px 14px;
                font-size: 11px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #1D4ED8;
            }
        """)
        buttons.accepted.connect(self.accept_selection)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def accept_selection(self):
        """Valide la sélection radio (refuse si aucun tarif choisi ou inchangé)."""
        for rb in self.radio_buttons:
            if rb.isChecked():
                self.selected_tarif = rb.text().strip()
                break
        if not self.selected_tarif:
            QMessageBox.warning(self, "Aucune sélection", "Veuillez sélectionner un tarif dans la liste.")
            return
        if self.selected_tarif.lower() == str(self.member.tarif_name or "").strip().lower():
            # Aucun changement réel : fermer sans enregistrer
            self.reject()
            return
        self.accept()

    def get_selected_tarif(self) -> str:
        """Retourne le tarif sélectionné (ou None)."""
        return self.selected_tarif


class SubCategoryDialog(QDialog):
    """
    Pop-up de sélection multi-catégories : une case à cocher par sous-catégorie,
    regroupées par type (Séance autonome, Cours, Compétition...),
    avec boutons "Tout sélectionner" / "Tout désélectionner".
    La sélection est appliquée en direct (la set `selected` est mutée par référence).
    """
    def __init__(self, groups, selected: set, on_change=None, parent=None,
                 title="Sélection des sous-catégories"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(360)
        self.selected = selected  # Set muté en direct par le dialogue
        self.on_change = on_change

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 12)
        layout.setSpacing(10)

        self.checkboxes = []

        # Zone défilante contenant les groupes de cases à cocher
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(4)

        for group_name, tarifs in groups:
            group_label = QLabel(group_name)
            group_label.setStyleSheet(
                "color: #1E293B; font-size: 12px; font-weight: bold;"
                "margin-top: 8px; border-bottom: 1px solid #E2E8F0;"
            )
            container_layout.addWidget(group_label)
            for tarif in tarifs:
                cb = QCheckBox(tarif)
                cb.setChecked(tarif in self.selected)
                cb.setStyleSheet("color: #475569; font-size: 11px;")
                cb.stateChanged.connect(lambda _, box=cb: self._on_checkbox_changed(box))
                container_layout.addWidget(cb)
                self.checkboxes.append(cb)

        container_layout.addStretch(1)
        scroll.setWidget(container)
        layout.addWidget(scroll, 1)

        # Boutons Tout sélectionner / Tout désélectionner
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self.select_all_btn = QPushButton("Tout sélectionner")
        self.deselect_all_btn = QPushButton("Tout désélectionner")
        for btn in (self.select_all_btn, self.deselect_all_btn):
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #F1F5F9;
                    border: 1px solid #CBD5E1;
                    border-radius: 6px;
                    padding: 6px 10px;
                    font-size: 11px;
                    color: #475569;
                }
                QPushButton:hover {
                    background-color: #E2E8F0;
                }
            """)
        self.select_all_btn.clicked.connect(self.select_all)
        self.deselect_all_btn.clicked.connect(self.deselect_all)
        btn_row.addWidget(self.select_all_btn)
        btn_row.addWidget(self.deselect_all_btn)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        # Bouton Fermer
        close_box = QDialogButtonBox(QDialogButtonBox.Close)
        close_box.setStyleSheet("""
            QPushButton {
                background-color: #3B82F6;
                color: #FFFFFF;
                border: none;
                border-radius: 6px;
                padding: 6px 14px;
                font-size: 11px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #2563EB;
            }
        """)
        close_box.rejected.connect(self.reject)
        layout.addWidget(close_box)

    def _on_checkbox_changed(self, box: QCheckBox):
        if box.isChecked():
            self.selected.add(box.text())
        else:
            self.selected.discard(box.text())
        if self.on_change:
            self.on_change()

    def select_all(self):
        for cb in self.checkboxes:
            cb.blockSignals(True)
            cb.setChecked(True)
            cb.blockSignals(False)
            self.selected.add(cb.text())
        if self.on_change:
            self.on_change()

    def deselect_all(self):
        for cb in self.checkboxes:
            cb.blockSignals(True)
            cb.setChecked(False)
            cb.blockSignals(False)
        self.selected.clear()
        if self.on_change:
            self.on_change()


# ============================================================================
# Fonctions réutilisables de construction des filtres (onglets Adhérents
# et Communications) : regroupement des tarifs par type et liste des statuts.
# ============================================================================

def get_tariff_category(tarif_name: str) -> str:
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

def build_tarif_groups(members_list):
    """Retourne les tarifs disponibles regroupés par catégorie, dans un ordre logique.
    'Liste d'attente cours' est isolé dans son propre sous-groupe, placé en premier."""
    unique_tarifs = sorted(set(m.tarif_name for m in members_list if m.tarif_name))
    groups = {}
    waiting = []
    for t in unique_tarifs:
        if t == WAITING_LIST_TARIF:
            waiting.append(t)
        else:
            groups.setdefault(get_tariff_category(t), []).append(t)

    order = ["Séance autonome", "Cours", "Compétition", "Autre"]
    ordered_groups = [(g, groups[g]) for g in order if g in groups] + \
                     [(g, groups[g]) for g in groups if g not in order]

    # Sous-groupe distinct et seul pour la liste d'attente, en tête de la pop-up
    if waiting:
        ordered_groups.insert(0, ("Liste d'attente", waiting))
    return ordered_groups

def build_default_tarif_selection(members_list):
    """Sélection par défaut des sous-catégories : toutes sauf la liste d'attente."""
    return set(
        m.tarif_name for m in members_list
        if m.tarif_name and m.tarif_name != WAITING_LIST_TARIF
    )

def build_status_list(members_list):
    """Liste des statuts présents chez les adhérents (normalisés, cf. schema_v2),
    dans l'ordre canonique puis alphabétique."""
    statuses = set(
        normalize_status(m.status)
        for m in members_list
        if m.status and str(m.status).strip()
    )
    statuses.discard("")
    statuses.discard("None")
    canonical = ["Validé", "Traité", "Terminé", "En cours", "Annulé"]
    return [s for s in canonical if s in statuses] + sorted(statuses - set(canonical))

def parse_order_date(value):
    """Parse une date d'inscription et retourne une date sans heure ni fuseau horaire
    (formats gérés : ISO avec heure/fuseau '2026-08-12T09:27:29+02:00', ISO simple
    '2025-09-01', 'JJ/MM/AAAA'). Retourne None si illisible."""
    date_raw = str(value or "").strip()
    if not date_raw:
        return None
    try:
        return datetime.datetime.strptime(date_raw[:10], "%Y-%m-%d").date()
    except ValueError:
        pass
    try:
        import pandas as pd
        parsed = pd.to_datetime(date_raw, utc=True, errors="coerce", dayfirst=True)
        if pd.isna(parsed):
            return None
        return parsed.date()
    except Exception:
        return None


class MembersPage(QWidget):
    """
    Page de gestion des Adhérents avec table hautes performances, filtres croisés et fiche détaillée.
    """
    # Émis depuis la fiche adhérent (bouton ✉️) : demande à la fenêtre principale
    # d'ouvrir la page Communication avec la recherche filtrée sur ce membre.
    email_requested = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.members_list = []
        self.selected_sub_tarifs = set()  # Sous-catégories de tarif cochées dans la pop-up
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

        # Barre des Filtres (Saison, Statuts, Tarifs, Email envoyé, Attestation générée)
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

        # 1. Filtre par statut de commande (dynamique : peuplé depuis les adhérents chargés,
        #    cf. schema_v2.STATUS_NORMALIZATION)
        self.status_filter = QComboBox()
        self.status_filter.addItems(["Tous les statuts"])
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

        # 2b. Filtre de sous-catégorie (pop-up de sélection multi-critères, regroupée par type)
        self.tarif_sub_filter = QPushButton("Toutes les sous-catégories ▾")
        self.tarif_sub_filter.setCursor(Qt.PointingHandCursor)
        self.tarif_sub_filter.setStyleSheet("""
            QPushButton {
                background-color: #FFFFFF;
                border: 1px solid #CBD5E1;
                border-radius: 6px;
                padding: 5px 8px;
                font-size: 11px;
                color: #475569;
                min-width: 110px;
                text-align: left;
            }
            QPushButton:hover {
                background-color: #F8FAFC;
            }
        """)
        self.tarif_sub_filter.clicked.connect(self.open_sub_category_popup)
        filters_layout.addWidget(self.tarif_sub_filter)

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
        self.table_view.setEditTriggers(QTableView.NoEditTriggers)  # Édition du tarif via pop-up uniquement
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

        # Double-clic sur la colonne Tarif : pop-up de changement de groupe (Nouveau !)
        self.table_view.doubleClicked.connect(self.on_table_double_clicked)

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
        self.detail_panel.email_requested.connect(self.on_email_requested) # Bouton ✉️ (Nouveau !)
        self.detail_panel.setVisible(False)
        self.splitter.addWidget(self.detail_panel)

        self.splitter.setStretchFactor(0, 4)
        self.splitter.setStretchFactor(1, 1)

        layout.addWidget(self.splitter)

    def get_tariff_category(self, tarif_name: str) -> str:
        """Retourne la catégorie principale associée à un nom de tarif."""
        return get_tariff_category(tarif_name)

    def get_tarif_groups(self):
        """Retourne les tarifs disponibles regroupés par catégorie (pop-up de sélection)."""
        return build_tarif_groups(self.members_list)

    def get_default_sub_selection(self):
        """Sélection par défaut des sous-catégories : toutes sauf la liste d'attente."""
        return build_default_tarif_selection(self.members_list)

    def update_sub_filter_button(self):
        """Met à jour le libellé du bouton filtre de sous-catégories selon la sélection."""
        count = len(self.selected_sub_tarifs)
        if count == 0 or self.selected_sub_tarifs == self.get_default_sub_selection() | {WAITING_LIST_TARIF}:
            self.tarif_sub_filter.setText("Toutes les sous-catégories ▾")
        elif self.selected_sub_tarifs == self.get_default_sub_selection():
            self.tarif_sub_filter.setText("Toutes sauf liste d'attente ▾")
        else:
            self.tarif_sub_filter.setText(f"Sous-catégories ({count}) ▾")

    def open_sub_category_popup(self):
        """Ouvre la pop-up de sélection des sous-catégories, regroupées par type."""
        dialog = SubCategoryDialog(
            self.get_tarif_groups(),
            self.selected_sub_tarifs,
            on_change=self.on_sub_selection_changed,
            parent=self
        )
        dialog.exec()
        self.on_filters_changed()

    def on_sub_selection_changed(self):
        """Déclenché à chaque changement de case à cocher dans la pop-up (filtrage en direct)."""
        self.update_sub_filter_button()
        self.on_filters_changed()

    def on_tarif_type_changed(self):
        """Déclenché lorsque la catégorie de tarif principale change."""
        type_sel = self.tarif_type_filter.currentText()

        # Retirer les sous-catégories sélectionnées qui n'appartiennent plus au type choisi
        if type_sel != "Tous les types":
            self.selected_sub_tarifs = {
                t for t in self.selected_sub_tarifs
                if self.get_tariff_category(t) == type_sel
            }
            self.update_sub_filter_button()

        # Déclencher le filtrage global
        self.on_filters_changed()

    def refresh_status_filter(self):
        """Peuple dynamiquement le filtre de statuts : seuls les statuts possédant
        au moins un adhérent dans la liste chargée sont affichés."""
        self.status_filter.blockSignals(True)
        previous = self.status_filter.currentText()
        self.status_filter.clear()
        self.status_filter.addItem("Tous les statuts")

        ordered = build_status_list(self.members_list)
        self.status_filter.addItems(ordered)

        # Restaurer la sélection précédente si toujours disponible
        idx = self.status_filter.findText(previous)
        if idx > 0:
            self.status_filter.setCurrentIndex(idx)
        self.status_filter.blockSignals(False)

    def notify_members_reloaded(self):
        """À appeler après une injection/mise à jour de self.members_list (chargement
        synchrone ou asynchrone) : réinitialise les filtres de tarifs (sélection par
        défaut = tout sauf la liste d'attente), repeuple le filtre des statuts
        et applique le tri par défaut sur la date d'inscription (la plus récente en premier)."""
        self.tarif_type_filter.blockSignals(True)
        self.tarif_type_filter.setCurrentIndex(0)
        self.tarif_type_filter.blockSignals(False)
        self.selected_sub_tarifs = self.get_default_sub_selection()
        self.update_sub_filter_button()
        self.refresh_status_filter()
        self.on_filters_changed()

        # Tri par défaut du tableau : date d'inscription décroissante (la plus récente en haut)
        date_col = next(
            i for i, c in enumerate(MemberTableModel.COLUMNS) if c[1] == "order_date"
        )
        self.table_view.sortByColumn(date_col, Qt.DescendingOrder)

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
            
            # Réinitialiser les filtres de tarifs et peupler le filtre des statuts
            self.notify_members_reloaded()
            
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
        sub_selection = self.selected_sub_tarifs
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

            # 2. Filtre de statut de commande (comparaison sur statut normalisé : insensible
            #    à la casse/accents, gère les variantes Processed/Canceled/Validated...)
            if status_sel != "Tous les statuts" and normalize_status(m.status) != normalize_status(status_sel):
                continue

            # 3. Filtre de tarif (catégorie principale et sous-catégories via la pop-up)
            if type_sel != "Tous les types":
                m_cat = self.get_tariff_category(m.tarif_name)
                if m_cat != type_sel:
                    continue
            
            if sub_selection and m.tarif_name not in sub_selection:
                continue

            # 4. Filtre email envoyé
            is_sent = bool(m.email_sent_date)
            if sent_sel == "Envoyés" and not is_sent:
                continue
            if sent_sel == "Non envoyés" and is_sent:
                continue

            # 5. Filtre attestation générée
            from attestation_generator import get_safe_filename
            filename = get_safe_filename(m.user_last_name, m.user_first_name, m.order_ref)
            pdf_path = os.path.join(ROOT_DIR, "exports", "attestation", filename.replace(".docx", ".pdf"))
            has_pdf = os.path.exists(pdf_path)
            
            if att_sel == "Générées (.pdf)" and not has_pdf:
                continue
            if att_sel == "Non générées" and has_pdf:
                continue

            # 6. Filtre d'inscription après la date sélectionnée
            #    (comparaison de DATES sans heure/fuseau : les horodatages HelloAsso
            #    avec fuseau '+02:00' étaient exclus à tort par une TypeError)
            if self.date_checkbox.isChecked():
                filter_qdate = self.date_edit.date()
                filter_date = datetime.date(filter_qdate.year(), filter_qdate.month(), filter_qdate.day())
                m_date = parse_order_date(m.order_date)
                if m_date is None or m_date < filter_date:
                    continue

            # 7. Filtre Nouveau membre (déjà adhérent == Non)
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

    def on_table_double_clicked(self, proxy_index):
        """Double-clic sur la colonne Tarif : ouvre la pop-up de changement de groupe."""
        source_idx = self.proxy_model.mapToSource(proxy_index)
        if not source_idx.isValid():
            return

        tarif_col = next(
            (i for i, c in enumerate(MemberTableModel.COLUMNS) if c[1] == "tarif_name"), None
        )
        if tarif_col is None or source_idx.column() != tarif_col:
            return

        if source_idx.row() >= len(self.base_model.members):
            return
        member = self.base_model.members[source_idx.row()]
        self.open_tarif_editor(member)

    def open_tarif_editor(self, member):
        """Ouvre la pop-up des tarifs de la saison active et enregistre le changement de groupe."""
        from domain.constants import get_active_season

        tarifs = SqliteRepository.get_season_tarifs(get_active_season())
        dialog = TarifEditDialog(member, tarifs, parent=self)
        if dialog.exec() != QDialog.Accepted:
            return

        new_tarif = dialog.get_selected_tarif()
        ok, err = SqliteRepository.update_member_tarif(
            member.order_ref, member.user_last_name, member.user_first_name, new_tarif
        )
        if not ok:
            QMessageBox.critical(
                self, "Échec du changement de groupe",
                f"Impossible de changer le tarif :\n\n{err}"
            )
            return

        QMessageBox.information(
            self, "Changement enregistré",
            f"Le groupe de {member.user_first_name} {str(member.user_last_name).upper()} est désormais :\n\n{new_tarif}"
        )
        # Recharger la base pour actualiser le tableau (contrôle d'âge, filtres, exports...)
        self.load_members_from_repository(force_reload=True)

    def hide_detail_panel(self):
        self.table_view.clearSelection()
        self.detail_panel.setVisible(False)

    def on_email_requested(self, member):
        """Bouton ✉️ de la fiche adhérent : remonte la demande à la fenêtre principale."""
        self.email_requested.emit(member)

    def on_member_updated(self):
        """Déclenché après qu'un adhérent a été édité et sauvegardé avec succès dans l'Excel."""
        # Forcer le rechargement depuis l'Excel local (pour actualiser le modèle de table !)
        self.load_members_from_repository(force_reload=True)
