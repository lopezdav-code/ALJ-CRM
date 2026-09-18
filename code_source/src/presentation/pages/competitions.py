"""
Page « Compétitions » : gestion des épreuves de la saison (base dédiée database_Competition.db).

Structure à deux niveaux :
- Onglets GLOBAUX (indépendants des épreuves) : « 🔄 HelloAsso » (campagne annuelle
  unique + miroir local + rattachements persistants) et « 📊 Bilan de saison » ;
- Onglet « 🏆 Épreuves » : liste des épreuves + détail d'une compétition avec ses
  onglets propres (« 📋 Détails », « 👥 Compétiteurs »).

Workflow (cahier des charges) :
1. Création / édition d'une compétition (ID FFME, nom, date, tarif, statut) ;
2. Sélection des compétiteurs (groupe « Compétition » + ajouts ponctuels) ;
3. Invitations / relances via l'onglet Communication (bouton ✉️) ;
4. Synchronisation HelloAsso de la campagne annuelle (miroir + liens) ;
5. Bilan de fin d'année (tableau croisé élèves × compétitions, export CSV).
"""
import os
import csv
import datetime

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit, QComboBox,
    QDateEdit, QDoubleSpinBox, QListWidget, QListWidgetItem, QSplitter, QFrame,
    QTableWidget, QTableWidgetItem, QHeaderView, QTabWidget, QCheckBox, QDialog, QProgressDialog, QMessageBox, QAbstractItemView,
)
from PySide6.QtCore import Qt, Signal, QThread
from PySide6.QtGui import QColor

from paths import ROOT_DIR
from domain.constants import COLOR_ACTION, COLOR_SUCCESS, COLOR_WARNING, COLOR_ERROR
from domain.competition_models import (
    Competition,
    LIBELLES_STATUT_COMPETITION,
    LIBELLES_STATUT_PAIEMENT,
    LIBELLE_VERS_STATUT_PAIEMENT,
    PAIEMENT_NON_INVITE,
)
from infrastructure.competition_repository import CompetitionRepository
from infrastructure import competition_drive_sync
from domain import competition_matching
from domain.planning_groups import group_for_tarif
from domain.utils import normalize_string

# Catégorie « hors groupe » : compétiteurs dont le tarif ne correspond à aucun
# créneau du planning (tarif vide, modifié ou non mappé).
NON_IDENTIFIES = "Non identifiés"

# Clé app_settings : campagne annuelle HelloAsso (un seul formulaire pour la saison)
ANNUAL_CAMPAIGN_KEY = "HELLOASSO_ANNUAL_CAMPAIGN"


# ----------------------------------------------------------------------
# Workers asynchrones (réseau / BDD lourde)
# ----------------------------------------------------------------------
class CompetitionDriveWorker(QThread):
    """Téléchargement ou téléversement de database_Competition.db sur Google Drive."""
    progress = Signal(str, int)
    finished_sig = Signal(bool, str)

    def __init__(self, mode: str, parent=None):
        super().__init__(parent)
        self.mode = mode

    def run(self):
        try:
            self.progress.emit("Connexion à Google Drive...", 20)
            if self.mode == "download":
                self.progress.emit("Téléchargement de database_Competition.db...", 60)
                ok, msg = competition_drive_sync.download_competition_db()
            else:
                self.progress.emit("Téléversement de database_Competition.db...", 60)
                ok, msg = competition_drive_sync.upload_competition_db()
            self.progress.emit("Terminé.", 100)
            self.finished_sig.emit(bool(ok), str(msg))
        except Exception as e:
            # Sans cet except, un crash du thread laisserait la fenêtre de
            # progression ouverte (jamais de finished_sig -> jamais de reset()).
            self.progress.emit("Terminé.", 100)
            self.finished_sig.emit(False, f"Erreur lors de la synchronisation Drive : {e}")


class AnnualHelloAssoSyncWorker(QThread):
    """Synchronise la campagne annuelle HelloAsso : miroir local + liens auto.

    - le miroir (helloasso_items) est réécrasé à chaque passage ;
    - les liens automatiques (item_links source='auto') sont recalculés ;
    - les liens 'manuel' (vos corrections) sont préservés ;
    - les participants (statut Payé, montant) sont reportés depuis les liens.
    """
    progress = Signal(str, int)
    finished_sig = Signal(bool, dict)

    def run(self):
        result = {"stats": {}, "unlinked": [], "errors": []}
        try:
            slug = CompetitionRepository.get_app_setting(ANNUAL_CAMPAIGN_KEY)
            if not (slug or "").strip():
                result["errors"].append(
                    "Aucune campagne annuelle configurée : renseignez le slug ou l'URL "
                    "du formulaire HelloAsso puis enregistrez."
                )
                self.finished_sig.emit(False, result)
                return

            self.progress.emit(f"Analyse de la campagne annuelle : {slug}", 10)
            try:
                ident = competition_matching.parse_campaign_identifier(slug)
            except ValueError as ve:
                result["errors"].append(str(ve))
                self.finished_sig.emit(False, result)
                return

            self.progress.emit("Connexion à l'API HelloAsso...", 30)
            from helloasso_api import get_items
            items = get_items(ident["form_type"], ident["slug"]) or []
            summarized = competition_matching.summarize_items(items)

            self.progress.emit(f"{len(items)} article(s) récupéré(s) : mise à jour du miroir…", 50)
            CompetitionRepository.sync_helloasso_mirror(summarized, items, ident["slug"])

            self.progress.emit("Rapprochement automatique…", 70)
            competitions = [{"id": c.id, "id_ffme": c.id_ffme, "nom": c.nom}
                            for c in CompetitionRepository.list_competitions()]
            adherents = CompetitionRepository.list_adherents()
            existing = CompetitionRepository.list_helloasso_links()
            links = competition_matching.auto_link_items(summarized, competitions, adherents, existing)
            CompetitionRepository.replace_auto_links(links)

            self.progress.emit("Report des paiements sur les compétiteurs…", 85)
            applied = CompetitionRepository.apply_links_to_participants()

            unlinked = CompetitionRepository.list_unlinked_items()
            result["stats"] = {
                "nb_items": len(items),
                "nb_auto": len(links),
                "nb_manual": sum(1 for lk in existing.values() if lk["source"] == "manuel"),
                "nb_applied": applied,
                "nb_unlinked": len(unlinked),
            }
            result["unlinked"] = unlinked
            self.progress.emit("Synchronisation terminée.", 100)
            self.finished_sig.emit(True, result)
        except Exception as e:
            result["errors"].append(str(e))
            self.finished_sig.emit(False, result)


# ----------------------------------------------------------------------
# Boîtes de dialogue
# ----------------------------------------------------------------------
class AddAdherentsDialog(QDialog):
    """Recherche étendue : ajoute des adhérents hors groupe « Compétition »."""

    def __init__(self, competition_id: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Ajouter des adhérents (recherche étendue)")
        self.resize(480, 520)
        self.competition_id = competition_id
        self.added = 0

        layout = QVBoxLayout(self)
        lbl = QLabel("Recherchez dans l'ensemble des adhérents de la base (nom, prénom, licence) :")
        lbl.setWordWrap(True)
        layout.addWidget(lbl)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("🔍 Nom, prénom ou n° de licence…")
        self.search_input.textChanged.connect(self.refresh_list)
        layout.addWidget(self.search_input)

        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        layout.addWidget(self.list_widget, 1)

        btns = QHBoxLayout()
        self.btn_add = QPushButton("➕ Ajouter la sélection")
        self.btn_add.clicked.connect(self.add_selected)
        btns.addWidget(self.btn_add)
        btn_close = QPushButton("Fermer")
        btn_close.clicked.connect(self.reject)
        btns.addWidget(btn_close)
        layout.addLayout(btns)
        self.refresh_list()

    def refresh_list(self):
        self.list_widget.clear()
        existing = {p.adherent_id for p in CompetitionRepository.list_participants(self.competition_id)}
        for a in CompetitionRepository.list_adherents(search=self.search_input.text().strip()):
            if a["id"] in existing:
                continue
            licence = a.get("num_licence") or "sans licence"
            item = QListWidgetItem(f"{a['nom']} {a['prenom']}  ·  {licence}  ·  {a.get('tarif') or '—'}")
            item.setData(Qt.UserRole, a["id"])
            self.list_widget.addItem(item)

    def add_selected(self):
        for item in self.list_widget.selectedItems():
            CompetitionRepository.add_participant(self.competition_id, item.data(Qt.UserRole))
            self.added += 1
        if self.added:
            self.accept()


class ManualCorrectionDialog(QDialog):
    """Correction / rattachement manuel des paiements HelloAsso.

    Chaque ligne affiche la valeur du champ « Compétition concernée » saisie sur
    HelloAsso et permet de choisir la compétition cible (par défaut l'épreuve en
    cours si fournie), puis le compétiteur à créditer parmi tous les adhérents du
    club (rattaché à la compétition cible si besoin) — ou d'ignorer la ligne.
    Les lignes peuvent porter un `id_item` (miroir HelloAsso) : la correction est
    alors mémorisée comme lien durable dans item_links.
    """

    def __init__(self, manual_review: list, current_competition=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Correction manuelle — n° de compétition HelloAsso")
        self.resize(1060, 560)
        # corrections : [(id_item|None, competition_id, adherent_id, montant)]
        self.corrections = []
        self._review = manual_review
        self.current_competition = current_competition
        self._comp_combos = []
        self._part_combos = []

        layout = QVBoxLayout(self)
        head = QLabel(
            f"⚠️ {len(manual_review)} paiement(s) n'affichent pas le n° de cette compétition dans le champ "
            "« Compétition concernée » du formulaire HelloAsso.\n"
            "Choisissez la compétition concernée puis le compétiteur à créditer (marqué « Payé »), "
            "ou laissez « — Ignorer — ».\n"
            "Le compétiteur est présélectionné automatiquement : n° de licence, sinon nom + prénom du payeur."
        )
        head.setWordWrap(True)
        head.setStyleSheet("font-size: 13px; font-weight: bold; color: #1E293B;")
        layout.addWidget(head)

        table = QTableWidget(len(manual_review), 6)
        table.setHorizontalHeaderLabels([
            "Payeur", "Montant", "Commande",
            "« Compétition concernée » (saisi sur HelloAsso)", "Compétition", "Compétiteur à créditer",
        ])
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Interactive)
        table.setColumnWidth(4, 250)
        table.setColumnWidth(5, 220)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

        competitions = CompetitionRepository.list_competitions()
        for r, rev in enumerate(manual_review):
            table.setItem(r, 0, QTableWidgetItem(str(rev.get("payer") or "")))
            montant = QTableWidgetItem(f"{float(rev.get('montant') or 0):.2f} €")
            montant.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            table.setItem(r, 1, montant)
            table.setItem(r, 2, QTableWidgetItem(str(rev.get("order_ref") or "")))
            valeur = QTableWidgetItem(str(rev.get("valeur_champ") or "— non renseigné —"))
            if not (rev.get("valeur_champ") or "").strip():
                valeur.setForeground(QColor(COLOR_WARNING))
            table.setItem(r, 3, valeur)

            # Colonne « Compétition » : toutes les épreuves enregistrées,
            # pré-sélection = épreuve en cours (si contexte de compétition).
            combo_comp = QComboBox()
            combo_comp.addItem("— Ignorer —", None)
            for c in competitions:
                date_txt = ""
                if c.date_competition:
                    try:
                        date_txt = f" ({datetime.date.fromisoformat(c.date_competition).strftime('%d/%m/%Y')})"
                    except ValueError:
                        date_txt = ""
                combo_comp.addItem(f"{c.nom}{date_txt}", c.id)
            if current_competition is not None:
                idx = combo_comp.findData(current_competition.id)
                if idx > 0:
                    combo_comp.setCurrentIndex(idx)
            combo_part = QComboBox()
            self._fill_participant_combo(combo_part, combo_comp.currentData(),
                                         rev.get("adherent_id"), rev.get("payer") or "")
            combo_comp.currentIndexChanged.connect(
                lambda _i, row=r, cpt=combo_part: self._on_target_changed(row, cpt)
            )
            table.setCellWidget(r, 4, combo_comp)
            table.setCellWidget(r, 5, combo_part)
            self._comp_combos.append(combo_comp)
            self._part_combos.append(combo_part)
            table.setRowHeight(r, 36)
        self._table = table
        layout.addWidget(table, 1)

        btns = QHBoxLayout()
        btn_apply = QPushButton("✔  Appliquer les corrections")
        btn_apply.setCursor(Qt.PointingHandCursor)
        btn_apply.setStyleSheet(
            "QPushButton { background-color: #10B981; color: #FFFFFF; border: none; "
            "border-radius: 6px; padding: 8px 14px; font-size: 12px; font-weight: bold; }"
        )
        btn_apply.clicked.connect(self.apply)
        btns.addWidget(btn_apply)
        btn_close = QPushButton("Fermer")
        btn_close.clicked.connect(self.reject)
        btns.addWidget(btn_close)
        btns.addStretch()
        layout.addLayout(btns)

    def _adherents(self) -> list:
        """Instantané des adhérents du club (mis en cache) : tout membre peut être crédité,
        même s'il n'est pas encore rattaché à la compétition cible."""
        if not hasattr(self, "_adherents_cache"):
            self._adherents_cache = CompetitionRepository.list_adherents()
        return self._adherents_cache

    def _match_adherent_by_name(self, payer: str):
        """Retrouve un adhérent par nom + prénom (normalisés, ordre inversé accepté)."""
        from domain.competition_matching import match_adherent_by_name
        return match_adherent_by_name(payer, self._adherents())

    def _fill_participant_combo(self, combo, competition_id, preferred_adherent_id=None,
                                payer: str = ""):
        """(Re)remplit le choix du compétiteur (tous les adhérents du club) et
        pré-sélectionne le meilleur candidat : n° de licence, sinon nom + prénom
        du payeur saisi sur HelloAsso."""
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("— Choisir —", None)
        if competition_id is not None:
            for a in self._adherents():
                lic = a.get("num_licence") or "sans licence"
                combo.addItem(f"{a.get('nom')} {a.get('prenom')}  ·  {lic}", a.get("id"))
            candidat = None
            if preferred_adherent_id is not None and combo.findData(preferred_adherent_id) > 0:
                candidat = preferred_adherent_id
            elif payer:
                candidat = self._match_adherent_by_name(payer)
            if candidat is not None:
                idx = combo.findData(candidat)
                if idx > 0:
                    combo.setCurrentIndex(idx)
        combo.setEnabled(competition_id is not None)
        combo.blockSignals(False)

    def _on_target_changed(self, row: int, combo_part: QComboBox):
        rev = self._review[row] if row < len(self._review) else {}
        self._fill_participant_combo(combo_part, self._comp_combos[row].currentData(),
                                     rev.get("adherent_id"), rev.get("payer") or "")

    def apply(self):
        for r, rev in enumerate(self._review):
            comp_id = self._comp_combos[r].currentData()
            adherent_id = self._part_combos[r].currentData() if comp_id is not None else None
            if comp_id is not None and adherent_id is not None:
                self.corrections.append((rev.get("id_item"), int(comp_id),
                                         int(adherent_id), float(rev.get("montant") or 0.0)))
        self.accept()


# ----------------------------------------------------------------------
# Page principale
# ----------------------------------------------------------------------
class CompetitionsPage(QWidget):
    """Onglet de gestion des compétitions de la section."""

    # (competition_id, nom) : demande d'ouverture de Communication ciblée
    email_requested = Signal(int, str)

    def __init__(self):
        super().__init__()
        self.current_competition = None
        self.sync_worker = None
        self.drive_worker = None
        self._loading = False
        self._group_header_rows = []   # [(ligne en-tête, [lignes compétiteurs])]
        self.init_ui()

    # ------------------------------------------------------------------
    # Construction de l'interface
    # ------------------------------------------------------------------
    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 15, 20, 20)
        layout.setSpacing(8)

        title = QLabel("🏆 Compétitions")
        title.setStyleSheet("font-size: 24px; font-weight: bold; color: #1E293B;")
        layout.addWidget(title)

        subtitle = QLabel(
            "Gestion des épreuves : sélection des compétiteurs, invitations, paiements HelloAsso et bilan de saison."
        )
        subtitle.setStyleSheet("color: #64748B; font-size: 13px;")
        layout.addWidget(subtitle)

        # Barre de synchronisation Drive (même mécanisme que la base principale)
        drive_bar = QFrame()
        drive_bar.setStyleSheet("QFrame { background: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 8px; }")
        drive_layout = QHBoxLayout(drive_bar)
        drive_layout.setContentsMargins(12, 8, 12, 8)

        lbl_drive = QLabel("🗄️ Base dédiée : database_Competition.db (cache local + Google Drive)")
        lbl_drive.setStyleSheet("color: #334155; font-size: 12px; border: none;")
        drive_layout.addWidget(lbl_drive)
        drive_layout.addStretch()

        self.btn_drive_download = QPushButton("⬇️  Charger depuis Drive")
        self.btn_drive_download.setCursor(Qt.PointingHandCursor)
        self.btn_drive_download.setStyleSheet(self._btn_style("#2563EB"))
        self.btn_drive_download.clicked.connect(lambda: self._start_drive_worker("download"))
        drive_layout.addWidget(self.btn_drive_download)

        self.btn_drive_upload = QPushButton("💾  Sauvegarder en BDD (Drive)")
        self.btn_drive_upload.setCursor(Qt.PointingHandCursor)
        self.btn_drive_upload.setToolTip("Envoie la base des compétitions vers Google Drive.")
        self.btn_drive_upload.setStyleSheet(self._btn_style("#10B981"))
        self.btn_drive_upload.clicked.connect(lambda: self._start_drive_worker("upload"))
        drive_layout.addWidget(self.btn_drive_upload)

        self.drive_status_lbl = QLabel("")
        self.drive_status_lbl.setStyleSheet("color: #64748B; font-size: 11px; border: none;")
        drive_layout.addWidget(self.drive_status_lbl)
        layout.addWidget(drive_bar)

        # Fenêtre de progression créée paresseusement (_ensure_progress) : ne PAS
        # l'instancier au démarrage — QProgressDialog arme un minuteur interne
        # (setMinimumDuration) qui peut la rendre visible seule à l'ouverture.
        self.progress = None

        # Deux niveaux : les onglets GLOBAUX (HelloAsso, bilan) sont indépendants
        # des épreuves ; le détail d'une compétition ne contient que ses onglets
        # propres (Détails, Compétiteurs).
        self.global_tabs = QTabWidget()
        self.global_tabs.addTab(self._build_epreuves_tab(), "🏆 Épreuves")
        self.global_tabs.addTab(self._build_helloasso_tab(), "🔄 HelloAsso")
        self.global_tabs.addTab(self._build_bilan_tab(), "📊 Bilan de saison")
        self.global_tabs.currentChanged.connect(self._on_global_tab_changed)
        layout.addWidget(self.global_tabs, 1)

        self.refresh_page()

    def _build_epreuves_tab(self) -> QWidget:
        """Onglet des épreuves : liste (gauche) + détail de la compétition (droite)."""
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._build_left_panel())

        self.comp_tabs = QTabWidget()
        self.comp_tabs.addTab(self._build_details_tab(), "📋 Détails")
        self.comp_tabs.addTab(self._build_participants_tab(), "👥 Compétiteurs")
        splitter.addWidget(self.comp_tabs)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([320, 800])
        return splitter

    def _btn_style(self, color: str) -> str:
        return f"""
            QPushButton {{
                background-color: {color}; color: #FFFFFF; border: none;
                border-radius: 6px; padding: 8px 14px; font-size: 12px; font-weight: bold;
            }}
            QPushButton:hover {{ background-color: {color}; }}
            QPushButton:disabled {{ background-color: #94A3B8; }}
        """

    def _build_left_panel(self) -> QWidget:
        container = QFrame()
        container.setStyleSheet("QFrame { background: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 8px; }")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        head = QHBoxLayout()
        lbl = QLabel("Épreuves de la saison")
        lbl.setStyleSheet("font-size: 14px; font-weight: bold; color: #1E293B; border: none;")
        head.addWidget(lbl)
        head.addStretch()
        btn_add = QPushButton("➕")
        btn_add.setToolTip("Nouvelle compétition")
        btn_add.setCursor(Qt.PointingHandCursor)
        btn_add.setStyleSheet(self._btn_style(COLOR_ACTION))
        btn_add.clicked.connect(self.on_new_competition)
        head.addWidget(btn_add)
        layout.addLayout(head)

        self.competitions_list = QListWidget()
        self.competitions_list.currentRowChanged.connect(self.on_competition_selected)
        layout.addWidget(self.competitions_list, 1)

        self.adherents_status_lbl = QLabel("")
        self.adherents_status_lbl.setStyleSheet("color: #64748B; font-size: 11px; border: none;")
        self.adherents_status_lbl.setWordWrap(True)
        layout.addWidget(self.adherents_status_lbl)

        btn_refresh = QPushButton("🔄  Rafraîchir / resynchroniser les adhérents")
        btn_refresh.setToolTip("Recopie la table des adhérents depuis la base principale database.db.")
        btn_refresh.setCursor(Qt.PointingHandCursor)
        btn_refresh.setStyleSheet(self._btn_style("#475569"))
        btn_refresh.clicked.connect(self.on_sync_adherents)
        layout.addWidget(btn_refresh)
        return container

    def _build_details_tab(self) -> QWidget:
        form_frame = QFrame()
        form_frame.setStyleSheet("QFrame { background: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 8px; }")
        form = QVBoxLayout(form_frame)
        form.setContentsMargins(16, 16, 16, 16)
        form.setSpacing(10)

        def field_label(text):
            lbl = QLabel(text)
            lbl.setStyleSheet("color: #334155; font-size: 12px; font-weight: bold; border: none;")
            return lbl

        def line_edit(placeholder=""):
            e = QLineEdit()
            e.setPlaceholderText(placeholder)
            e.setStyleSheet("QLineEdit { border: 1px solid #CBD5E1; border-radius: 6px; padding: 7px; }")
            return e

        form.addWidget(field_label("Nom de l'épreuve *"))
        self.input_nom = line_edit("Ex : Championnat départemental U13")
        form.addWidget(self.input_nom)

        row1 = QHBoxLayout()
        col1 = QVBoxLayout()
        col1.addWidget(field_label("Identifiant FFME (id_ffme)"))
        self.input_id_ffme = line_edit("Ex : EVT-2026-001")
        col1.addWidget(self.input_id_ffme)
        row1.addLayout(col1, 1)
        col2 = QVBoxLayout()
        col2.addWidget(field_label("Date de la compétition"))
        self.input_date = QDateEdit()
        self.input_date.setCalendarPopup(True)
        self.input_date.setDisplayFormat("dd/MM/yyyy")
        self.input_date.setStyleSheet("QDateEdit { border: 1px solid #CBD5E1; border-radius: 6px; padding: 6px; }")
        col2.addWidget(self.input_date)
        row1.addLayout(col2, 1)
        col3 = QVBoxLayout()
        col3.addWidget(field_label("Tarif d'inscription (€)"))
        self.input_prix = QDoubleSpinBox()
        self.input_prix.setRange(0.0, 500.0)
        self.input_prix.setDecimals(2)
        self.input_prix.setSuffix(" €")
        self.input_prix.setStyleSheet("QDoubleSpinBox { border: 1px solid #CBD5E1; border-radius: 6px; padding: 6px; }")
        col3.addWidget(self.input_prix)
        row1.addLayout(col3, 1)
        form.addLayout(row1)

        row2 = QHBoxLayout()
        col4 = QVBoxLayout()
        col4.addWidget(field_label("Statut"))
        self.input_statut = QComboBox()
        for lib in LIBELLES_STATUT_COMPETITION.values():
            self.input_statut.addItem(lib)
        self.input_statut.setStyleSheet("QComboBox { border: 1px solid #CBD5E1; border-radius: 6px; padding: 7px; }")
        col4.addWidget(self.input_statut)
        row2.addLayout(col4, 1)
        form.addLayout(row2)

        form.addStretch()

        btns = QHBoxLayout()
        self.btn_save = QPushButton("💾  Enregistrer")
        self.btn_save.setCursor(Qt.PointingHandCursor)
        self.btn_save.setStyleSheet(self._btn_style(COLOR_SUCCESS))
        self.btn_save.clicked.connect(self.on_save_competition)
        btns.addWidget(self.btn_save)

        self.btn_delete = QPushButton("🗑  Supprimer")
        self.btn_delete.setCursor(Qt.PointingHandCursor)
        self.btn_delete.setStyleSheet(self._btn_style(COLOR_ERROR))
        self.btn_delete.clicked.connect(self.on_delete_competition)
        btns.addWidget(self.btn_delete)
        btns.addStretch()
        form.addLayout(btns)

        self.details_hint = QLabel("Sélectionnez une épreuve à gauche ou créez-en une nouvelle.")
        self.details_hint.setStyleSheet("color: #94A3B8; font-size: 12px; font-style: italic; border: none;")
        form.addWidget(self.details_hint)
        return form_frame

    def _build_participants_tab(self) -> QWidget:
        frame = QFrame()
        frame.setStyleSheet("QFrame { background: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 8px; }")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)

        btns = QHBoxLayout()
        self.btn_load_group = QPushButton("🧗  Charger le groupe « Compétition »")
        self.btn_load_group.setToolTip("Ajoute (bascule Oui) tous les adhérents du groupe Compétition de la base principale.")
        self.btn_load_group.setCursor(Qt.PointingHandCursor)
        self.btn_load_group.setStyleSheet(self._btn_style(COLOR_ACTION))
        self.btn_load_group.clicked.connect(self.on_load_competition_group)
        btns.addWidget(self.btn_load_group)

        self.btn_add_extended = QPushButton("➕  Ajouter via recherche étendue")
        self.btn_add_extended.setCursor(Qt.PointingHandCursor)
        self.btn_add_extended.setStyleSheet(self._btn_style("#475569"))
        self.btn_add_extended.clicked.connect(self.on_add_extended)
        btns.addWidget(self.btn_add_extended)

        self.btn_invite = QPushButton("✉️  Préparer les invitations")
        self.btn_invite.setToolTip("Ouvre l'onglet Communication filtré sur les compétiteurs sélectionnés.")
        self.btn_invite.setCursor(Qt.PointingHandCursor)
        self.btn_invite.setStyleSheet(self._btn_style("#7C3AED"))
        self.btn_invite.clicked.connect(self.on_prepare_invitations)
        btns.addWidget(self.btn_invite)
        btns.addStretch()

        self.participants_count_lbl = QLabel("0 compétiteur sélectionné")
        self.participants_count_lbl.setStyleSheet("color: #334155; font-size: 12px; font-weight: bold; border: none;")
        btns.addWidget(self.participants_count_lbl)
        layout.addLayout(btns)

        self.participants_search = QLineEdit()
        self.participants_search.setPlaceholderText("🔍 Filtrer les compétiteurs affichés…")
        self.participants_search.setStyleSheet("QLineEdit { border: 1px solid #CBD5E1; border-radius: 6px; padding: 7px; }")
        self.participants_search.textChanged.connect(self.filter_participants_rows)
        layout.addWidget(self.participants_search)

        self.participants_table = QTableWidget(0, 8)
        self.participants_table.setHorizontalHeaderLabels(
            ["Participe", "Nom", "Prénom", "Licence FFME", "N° de commande",
             "Paiement", "Synchro HelloAsso", ""]
        )
        header = self.participants_table.horizontalHeader()
        # Nom et Prénom : même traitement (largeur adaptée au contenu) pour rester
        # cohérents ; la colonne Synchro HelloAsso absorbe l'espace restant.
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(7, QHeaderView.ResizeMode.Fixed)
        self.participants_table.setColumnWidth(0, 70)
        self.participants_table.setColumnWidth(5, 120)
        self.participants_table.setColumnWidth(7, 60)
        self.participants_table.verticalHeader().setVisible(False)
        self.participants_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        layout.addWidget(self.participants_table, 1)
        return frame

    def _build_helloasso_tab(self) -> QWidget:
        frame = QFrame()
        frame.setStyleSheet("QFrame { background: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 8px; }")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)

        hint = QLabel(
            "Campagne annuelle : un seul formulaire HelloAsso pour toutes les compétitions.\n"
            "La synchro remplit le miroir local, rattache automatiquement les articles "
            "(n° de compétition saisi, puis licence, puis nom) et reporte les paiements.\n"
            "Vos corrections manuelles sont conservées d'une synchro à l'autre ; les articles\n"
            "sans rattachement complet vous sont proposés à la fin de chaque synchro."
        )
        hint.setStyleSheet("color: #64748B; font-size: 12px; border: none;")
        layout.addWidget(hint)

        # --- Campagne annuelle (un seul formulaire pour la saison) ---
        annual_row = QHBoxLayout()
        lbl_annual = QLabel("Campagne annuelle :")
        lbl_annual.setStyleSheet("color: #334155; font-size: 12px; font-weight: bold; border: none;")
        annual_row.addWidget(lbl_annual)
        self.annual_campaign_input = QLineEdit()
        self.annual_campaign_input.setPlaceholderText(
            "competition-saison-2026 ou https://www.helloasso.com/associations/…"
        )
        self.annual_campaign_input.setStyleSheet("QLineEdit { border: 1px solid #CBD5E1; border-radius: 6px; padding: 6px; }")
        annual_row.addWidget(self.annual_campaign_input, 1)
        self.btn_save_annual = QPushButton("💾  Enregistrer")
        self.btn_save_annual.setCursor(Qt.PointingHandCursor)
        self.btn_save_annual.setStyleSheet(self._btn_style("#475569"))
        self.btn_save_annual.clicked.connect(self.on_save_annual_campaign)
        annual_row.addWidget(self.btn_save_annual)
        self.btn_sync_annual = QPushButton("🔄  Synchroniser la campagne")
        self.btn_sync_annual.setCursor(Qt.PointingHandCursor)
        self.btn_sync_annual.setStyleSheet(self._btn_style(COLOR_SUCCESS))
        self.btn_sync_annual.clicked.connect(self.on_sync_annual)
        annual_row.addWidget(self.btn_sync_annual)
        layout.addLayout(annual_row)

        self.sync_result_lbl = QLabel("")
        self.sync_result_lbl.setStyleSheet("color: #1E293B; font-size: 12px; border: none;")
        self.sync_result_lbl.setWordWrap(True)
        layout.addWidget(self.sync_result_lbl)

        # --- Miroir HelloAsso (copie locale + rattachements) ---
        items_row = QHBoxLayout()
        items_lbl = QLabel("Articles HelloAsso (miroir local) :")
        items_lbl.setStyleSheet("color: #334155; font-size: 12px; font-weight: bold; border: none;")
        items_row.addWidget(items_lbl)
        items_row.addStretch()
        self.btn_attach_items = QPushButton("🔗  Rattacher les paiements en attente")
        self.btn_attach_items.setCursor(Qt.PointingHandCursor)
        self.btn_attach_items.setStyleSheet(self._btn_style(COLOR_ACTION))
        self.btn_attach_items.clicked.connect(self.on_attach_items)
        items_row.addWidget(self.btn_attach_items)
        layout.addLayout(items_row)

        self.items_table = QTableWidget(0, 10)
        self.items_table.setHorizontalHeaderLabels([
            "Payeur", "Montant", "N° de commande", "N° de licence",
            "« Compétition concernée »", "Numéro de la compétition",
            "Compétition rattachée", "Adhérent rattaché", "Source", "État",
        ])
        items_header = self.items_table.horizontalHeader()
        items_header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        items_header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        items_header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        items_header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        items_header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        items_header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        items_header.setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        items_header.setSectionResizeMode(7, QHeaderView.ResizeMode.ResizeToContents)
        items_header.setSectionResizeMode(8, QHeaderView.ResizeMode.ResizeToContents)
        items_header.setSectionResizeMode(9, QHeaderView.ResizeMode.ResizeToContents)
        self.items_table.verticalHeader().setVisible(False)
        self.items_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        layout.addWidget(self.items_table, 1)
        return frame

    def _build_bilan_tab(self) -> QWidget:
        frame = QFrame()
        frame.setStyleSheet("QFrame { background: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 8px; }")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)

        row = QHBoxLayout()
        lbl = QLabel("Saison :")
        lbl.setStyleSheet("color: #334155; font-size: 12px; font-weight: bold; border: none;")
        row.addWidget(lbl)
        self.bilan_season_combo = QComboBox()
        self.bilan_season_combo.setMinimumWidth(160)
        self.bilan_season_combo.currentIndexChanged.connect(lambda _i: self.render_bilan())
        row.addWidget(self.bilan_season_combo)
        row.addStretch()
        self.btn_export_bilan = QPushButton("📄  Exporter en CSV")
        self.btn_export_bilan.setCursor(Qt.PointingHandCursor)
        self.btn_export_bilan.setStyleSheet(self._btn_style(COLOR_ACTION))
        self.btn_export_bilan.clicked.connect(self.on_export_bilan)
        row.addWidget(self.btn_export_bilan)
        self.btn_refresh_bilan = QPushButton("🔄  Actualiser")
        self.btn_refresh_bilan.setCursor(Qt.PointingHandCursor)
        self.btn_refresh_bilan.setStyleSheet(self._btn_style("#475569"))
        self.btn_refresh_bilan.clicked.connect(self.render_bilan)
        row.addWidget(self.btn_refresh_bilan)
        layout.addLayout(row)

        self.bilan_hint = QLabel(
            "Tableau croisé élèves × compétitions : chaque cellule indique l'état du paiement pour la saison choisie."
        )
        self.bilan_hint.setStyleSheet("color: #64748B; font-size: 12px; border: none;")
        layout.addWidget(self.bilan_hint)

        self.bilan_table = QTableWidget(0, 0)
        self.bilan_table.verticalHeader().setVisible(False)
        self.bilan_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        layout.addWidget(self.bilan_table, 1)
        return frame

    # ------------------------------------------------------------------
    # Chargement des données
    # ------------------------------------------------------------------
    def refresh_page(self):
        """(Re)charge les compétitions et vérifie l'instantané des adhérents."""
        if self._loading:
            return
        self._loading = True
        try:
            CompetitionRepository.setup_database()
            count = CompetitionRepository.count_adherents()
            if count == 0:
                report = CompetitionRepository.sync_adherents_from_main()
                if report["errors"]:
                    self.adherents_status_lbl.setText(
                        "⚠️ Instantané des adhérents non initialisé : " + " ; ".join(report["errors"])
                    )
                else:
                    count = CompetitionRepository.count_adherents()
                    self.adherents_status_lbl.setText(
                        f"✅ Instantané des adhérents initialisé depuis database.db ({count} adhérents)."
                    )
            elif count:
                self.adherents_status_lbl.setText(f"👥 {count} adhérents dans l'instantané local.")

            self.reload_competitions_list()
            self._refresh_bilan_seasons()
        finally:
            self._loading = False

    def reload_competitions_list(self):
        self.competitions_list.blockSignals(True)
        self.competitions_list.clear()
        comps = CompetitionRepository.list_competitions()
        for c in comps:
            lib_statut = LIBELLES_STATUT_COMPETITION.get(c.statut, c.statut)
            date_txt = datetime.date.fromisoformat(c.date_competition).strftime("%d/%m/%Y") if c.date_competition else "sans date"
            item = QListWidgetItem(f"🏆 {c.nom}\n📅 {date_txt}   ·   {lib_statut}")
            item.setData(Qt.UserRole, c.id)
            self.competitions_list.addItem(item)
        self.competitions_list.blockSignals(False)

        if not comps:
            self.current_competition = None
            self._clear_form()
            self._update_participants_view()
            self._update_helloasso_view()
            self.details_hint.setText("Aucune compétition : cliquez sur ➕ pour créer la première épreuve.")
        elif self.current_competition:
            for i in range(self.competitions_list.count()):
                if self.competitions_list.item(i).data(Qt.UserRole) == self.current_competition.id:
                    self.competitions_list.setCurrentRow(i)
                    break
        else:
            self.competitions_list.setCurrentRow(0)

    def on_competition_selected(self, row: int):
        item = self.competitions_list.item(row)
        if not item:
            return
        comp_id = item.data(Qt.UserRole)
        self.current_competition = CompetitionRepository.get_competition(comp_id)
        self._fill_form()
        self._update_participants_view()
        self._update_helloasso_view()

    def _fill_form(self):
        c = self.current_competition
        if not c:
            self._clear_form()
            return
        self.input_nom.setText(c.nom)
        self.input_id_ffme.setText(c.id_ffme)
        if c.date_competition:
            d = datetime.date.fromisoformat(c.date_competition)
            from PySide6.QtCore import QDate
            self.input_date.setDate(QDate(d.year, d.month, d.day))
        self.input_prix.setValue(c.prix)
        self.input_statut.setCurrentIndex(
            list(LIBELLES_STATUT_COMPETITION.keys()).index(c.statut)
            if c.statut in LIBELLES_STATUT_COMPETITION else 0
        )
        self.details_hint.setText(f"Édition de « {c.nom} » (ID interne #{c.id}).")

    def _clear_form(self):
        self.input_nom.clear()
        self.input_id_ffme.clear()
        self.input_prix.setValue(0.0)
        self.input_statut.setCurrentIndex(0)
        self.details_hint.setText("Sélectionnez une épreuve à gauche ou créez-en une nouvelle.")

    # ------------------------------------------------------------------
    # CRUD compétition
    # ------------------------------------------------------------------
    def on_new_competition(self):
        self.current_competition = None
        self._clear_form()
        self.input_nom.setFocus()
        self.comp_tabs.setCurrentIndex(0)
        self.details_hint.setText("Saisissez le nom, la date, le tarif et l'ID FFME puis enregistrez.")

    def on_save_competition(self):
        nom = self.input_nom.text().strip()
        if not nom:
            QMessageBox.warning(self, "Champ requis", "Le nom de l'épreuve est obligatoire.")
            return
        d = self.input_date.date()
        comp = self.current_competition or Competition()
        comp.nom = nom
        comp.id_ffme = self.input_id_ffme.text().strip()
        comp.date_competition = f"{d.year():04d}-{d.month():02d}-{d.day():02d}"
        comp.prix = round(self.input_prix.value(), 2)
        comp.statut = list(LIBELLES_STATUT_COMPETITION.keys())[self.input_statut.currentIndex()]
        # NB : helloasso_ref n'est plus éditable ici — la campagne HelloAsso est
        # désormais annuelle et se configure dans l'onglet global « HelloAsso ».
        comp_id = CompetitionRepository.save_competition(comp)
        self.current_competition = CompetitionRepository.get_competition(comp_id)
        self.reload_competitions_list()
        self._update_participants_view()
        self._update_helloasso_view()
        QMessageBox.information(self, "Enregistré", f"La compétition « {comp.nom} » a été enregistrée.")

    def on_delete_competition(self):
        if not self.current_competition:
            return
        reply = QMessageBox.question(
            self, "Confirmation",
            f"Supprimer la compétition « {self.current_competition.nom} » et sa liste de participants ?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        CompetitionRepository.delete_competition(self.current_competition.id)
        self.current_competition = None
        self.reload_competitions_list()
        self._update_participants_view()
        self._update_helloasso_view()

    def on_sync_adherents(self):
        progress = self._ensure_progress()
        progress.setLabelText("Resynchronisation des adhérents depuis database.db…")
        progress.setValue(40)
        progress.show()
        report = CompetitionRepository.sync_adherents_from_main()
        progress.reset()
        if report["errors"]:
            QMessageBox.critical(self, "Erreur", "\n".join(report["errors"]))
        else:
            count = CompetitionRepository.count_adherents()
            self.adherents_status_lbl.setText(f"👥 {count} adhérents dans l'instantané local (mise à jour réussie).")
            QMessageBox.information(
                self, "Synchronisation adhérents",
                f"{report['imported']} ajouté(s), {report['updated']} mis à jour.\nTotal : {count} adhérents."
            )

    # ------------------------------------------------------------------
    # Participants
    # ------------------------------------------------------------------
    def _update_participants_view(self):
        table = self.participants_table
        table.setRowCount(0)
        table.clearSpans()
        self._group_header_rows = []
        if not self.current_competition:
            self.participants_count_lbl.setText("0 compétiteur sélectionné")
            return
        participants = CompetitionRepository.list_participants(self.current_competition.id)
        selected = sum(1 for p in participants if p.selectionne)

        # Regroupement par groupe de créneau du planning (Autonome, Compétition
        # U11-U13…) ; les tarifs non rapprochés vont dans la catégorie « Non identifiés ».
        planning = []
        try:
            from infrastructure.sqlite_repository import SqliteRepository
            planning = SqliteRepository.load_planning_data(log_debug=False)
        except Exception as e:
            print(f"⚠️ [COMPETITIONS] Planning indisponible pour le regroupement : {e}")
        groups = {}
        for p in participants:
            label = group_for_tarif(p.tarif, planning) or NON_IDENTIFIES
            groups.setdefault(label, []).append(p)

        paiement_styles = {
            "paye": QColor(COLOR_SUCCESS),
            "en_attente": QColor(COLOR_WARNING),
            "non_invite": QColor("#94A3B8"),
        }
        table.setRowCount(len(participants) + len(groups))
        row = 0
        ordered = sorted(
            groups.items(),
            key=lambda kv: (kv[0] == NON_IDENTIFIES, normalize_string(kv[0])),
        )
        for label, members in ordered:
            # Ligne d'en-tête du groupe (fusionnée sur toute la largeur)
            header_item = QTableWidgetItem(f"{label}  ·  {len(members)} compétiteur(s)")
            header_item.setFlags(header_item.flags() & ~Qt.ItemIsEditable)
            header_item.setFont(self._group_header_font())
            header_item.setBackground(QColor("#EFF6FF"))
            header_item.setForeground(QColor("#1D4ED8"))
            table.setItem(row, 0, header_item)
            table.setSpan(row, 0, 1, table.columnCount())
            table.setRowHeight(row, 30)
            header_row = row
            row += 1

            member_rows = []
            for p in members:
                cb = QCheckBox()
                cb.setChecked(p.selectionne)
                cb.setStyleSheet("QCheckBox { margin-left: 12px; }")
                cb.toggled.connect(lambda checked, cid=self.current_competition.id, aid=p.adherent_id:
                                   self._on_selection_toggled(cid, aid, checked))
                table.setCellWidget(row, 0, cb)

                for col, val in ((1, p.nom), (2, p.prenom), (3, p.num_licence or ""),
                                 (4, p.commande_helloasso or "")):
                    it = QTableWidgetItem(val)
                    it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                    table.setItem(row, col, it)

                combo = QComboBox()
                for lib in LIBELLES_STATUT_PAIEMENT.values():
                    combo.addItem(lib)
                combo.setCurrentText(LIBELLES_STATUT_PAIEMENT.get(p.statut_paiement, "Non invité"))
                combo.currentTextChanged.connect(
                    lambda lib, cid=self.current_competition.id, aid=p.adherent_id:
                    self._on_paiement_changed(cid, aid, lib)
                )
                table.setCellWidget(row, 5, combo)

                synchro = QTableWidgetItem(
                    datetime.datetime.fromisoformat(p.date_synchro_helloasso).strftime("%d/%m/%Y %H:%M")
                    if p.date_synchro_helloasso else ""
                )
                synchro.setFlags(synchro.flags() & ~Qt.ItemIsEditable)
                synchro.setForeground(QColor(paiement_styles.get(p.statut_paiement, "#94A3B8")))
                table.setItem(row, 6, synchro)

                btn_del = QPushButton("🗑")
                btn_del.setToolTip(f"Retirer {p.nom} {p.prenom} de cette compétition")
                btn_del.setCursor(Qt.PointingHandCursor)
                btn_del.setStyleSheet(
                    "QPushButton { border: none; background: transparent; font-size: 14px; }"
                    "QPushButton:hover { color: #DC2626; }"
                )
                btn_del.clicked.connect(
                    lambda _c, cid=self.current_competition.id, aid=p.adherent_id,
                           nom=f"{p.nom} {p.prenom}": self._on_delete_participant(cid, aid, nom)
                )
                table.setCellWidget(row, 7, btn_del)
                member_rows.append(row)
                row += 1

            self._group_header_rows.append((header_row, member_rows))

        self.participants_count_lbl.setText(
            f"{selected} compétiteur{'s' if selected > 1 else ''} sélectionné{'s' if selected > 1 else ''} "
            f"sur {len(participants)}"
        )
        self.filter_participants_rows()

    def _group_header_font(self):
        from PySide6.QtGui import QFont
        f = QFont()
        f.setBold(True)
        return f

    def _on_selection_toggled(self, competition_id: int, adherent_id: int, checked: bool):
        CompetitionRepository.set_selection(competition_id, adherent_id, checked)
        self._refresh_count_only()

    def _on_delete_participant(self, competition_id: int, adherent_id: int, nom_complet: str):
        """Retire un compétiteur de l'épreuve (confirmation avant suppression)."""
        reply = QMessageBox.question(
            self, "Supprimer le compétiteur",
            f"Retirer « {nom_complet} » de cette compétition ?\n"
            "(L'adhérent reste dans la base ; seul le rattachement à l'épreuve est supprimé.)",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        CompetitionRepository.remove_participant(competition_id, adherent_id)
        self._update_participants_view()

    def _on_paiement_changed(self, competition_id: int, adherent_id: int, libelle: str):
        statut = LIBELLE_VERS_STATUT_PAIEMENT.get(libelle, PAIEMENT_NON_INVITE)
        CompetitionRepository.set_payment_status(competition_id, adherent_id, statut)

    def _refresh_count_only(self):
        if not self.current_competition:
            return
        participants = CompetitionRepository.list_participants(self.current_competition.id)
        selected = sum(1 for p in participants if p.selectionne)
        self.participants_count_lbl.setText(
            f"{selected} compétiteur{'s' if selected > 1 else ''} sélectionné{'s' if selected > 1 else ''} "
            f"sur {len(participants)}"
        )

    def filter_participants_rows(self):
        from domain.utils import normalize_string
        q = normalize_string(self.participants_search.text())
        table = self.participants_table
        header_map = getattr(self, "_group_header_rows", []) or []
        header_rows = {h for h, _rows in header_map}
        for r in range(table.rowCount()):
            if r in header_rows:
                continue  # visibilité pilotée par le groupe en dessous
            hay = " ".join(
                table.item(r, c).text() if table.item(r, c) else ""
                for c in (1, 2, 3, 4)
            )
            table.setRowHidden(r, bool(q) and q not in normalize_string(hay))
        # Un en-tête de groupe reste visible uniquement si au moins une de ses
        # lignes de compétiteurs est visible après filtrage.
        for header_row, member_rows in header_map:
            table.setRowHidden(header_row, all(table.isRowHidden(r) for r in member_rows))

    def on_load_competition_group(self):
        if not self.current_competition:
            QMessageBox.information(self, "Aucune compétition", "Créez ou sélectionnez d'abord une compétition.")
            return
        n = CompetitionRepository.load_competition_group_into(self.current_competition.id)
        self._update_participants_view()
        QMessageBox.information(
            self, "Groupe « Compétition »",
            f"{n} compétiteur(s) du groupe « Compétition » sont maintenant rattaché(s) à cette épreuve.",
        )

    def on_add_extended(self):
        if not self.current_competition:
            QMessageBox.information(self, "Aucune compétition", "Créez ou sélectionnez d'abord une compétition.")
            return
        dlg = AddAdherentsDialog(self.current_competition.id, self)
        if dlg.exec():
            self._update_participants_view()
            QMessageBox.information(self, "Ajout réussi", f"{dlg.added} adhérent(s) ajouté(s) à la compétition.")

    def on_prepare_invitations(self):
        if not self.current_competition:
            return
        selected = [p for p in CompetitionRepository.list_participants(self.current_competition.id) if p.selectionne]
        if not selected:
            QMessageBox.warning(
                self, "Aucun compétiteur",
                "Aucun compétiteur sélectionné : basculez au moins un adhérent sur « Oui »."
            )
            return
        self.email_requested.emit(self.current_competition.id, self.current_competition.nom)

    # ------------------------------------------------------------------
    # HelloAsso
    # ------------------------------------------------------------------
    def _update_helloasso_view(self):
        """Onglet global HelloAsso : campagne annuelle + miroir (indépendant des épreuves)."""
        self.annual_campaign_input.setText(
            CompetitionRepository.get_app_setting(ANNUAL_CAMPAIGN_KEY)
        )
        self._refresh_mirror_table()

    def _refresh_mirror_table(self):
        """Affiche le miroir HelloAsso + rattachements (compétition, adhérent, source)."""
        import json
        rows = CompetitionRepository.list_mirror_items()
        table = self.items_table
        table.setRowCount(len(rows))
        nb_attente = 0
        for r, it in enumerate(rows):
            linked_comp = it.get("competition_id") is not None
            linked_adh = it.get("adherent_id") is not None
            if not linked_comp or not linked_adh:
                nb_attente += 1
            table.setItem(r, 0, QTableWidgetItem(f"{it.get('payer_nom') or ''} {it.get('payer_prenom') or ''}".strip()))
            montant = QTableWidgetItem(f"{float(it.get('montant') or 0):.2f} €")
            montant.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            table.setItem(r, 1, montant)
            table.setItem(r, 2, QTableWidgetItem(str(it.get("order_id") or "")))
            table.setItem(r, 3, QTableWidgetItem(str(it.get("licence_saisie") or "")))
            table.setItem(r, 4, QTableWidgetItem(str(it.get("competition_saisie") or "")))
            
            # Extraction dynamique du numéro de compétition depuis le JSON brut
            comp_num = ""
            raw_json_str = it.get("raw_json")
            if raw_json_str:
                try:
                    raw_data = json.loads(raw_json_str)
                    for field in raw_data.get("customFields", []):
                        name = str(field.get("name") or "").strip().lower()
                        if "numero" in name and "competition" in name:
                            comp_num = str(field.get("answer") or field.get("value") or "").strip()
                            break
                except Exception:
                    pass
            table.setItem(r, 5, QTableWidgetItem(comp_num))
            
            table.setItem(r, 6, QTableWidgetItem(str(it.get("competition_nom") or "")))
            table.setItem(r, 7, QTableWidgetItem(
                f"{it.get('adherent_nom') or ''} {it.get('adherent_prenom') or ''}".strip()))
            source = QTableWidgetItem(str(it.get("source") or "—"))
            if str(it.get("source")) == "manuel":
                source.setForeground(QColor(COLOR_SUCCESS))
            table.setItem(r, 8, source)
            etat = QTableWidgetItem(str(it.get("etat") or "").capitalize())
            etat.setForeground(QColor("#64748B"))
            table.setItem(r, 9, etat)
            table.setRowHeight(r, 26)
        self.btn_attach_items.setText(
            f"🔗  Rattacher les paiements en attente ({nb_attente})"
        )

    def on_save_annual_campaign(self):
        slug = self.annual_campaign_input.text().strip()
        if slug:
            try:
                competition_matching.parse_campaign_identifier(slug)
            except ValueError as ve:
                QMessageBox.warning(self, "Campagne invalide", str(ve))
                return
        CompetitionRepository.save_app_setting(ANNUAL_CAMPAIGN_KEY, slug)
        QMessageBox.information(
            self, "Campagne annuelle enregistrée",
            "La campagne annuelle HelloAsso a été enregistrée." if slug
            else "La campagne annuelle a été effacée.",
        )

    def on_sync_annual(self):
        if not (CompetitionRepository.get_app_setting(ANNUAL_CAMPAIGN_KEY) or "").strip():
            QMessageBox.warning(
                self, "Campagne manquante",
                "Renseignez d'abord la campagne annuelle (slug ou URL) puis enregistrez-la."
            )
            return
        self.btn_sync_annual.setEnabled(False)
        progress = self._ensure_progress()
        progress.setLabelText("Connexion à HelloAsso…")
        progress.setValue(5)
        progress.show()
        self.sync_worker = AnnualHelloAssoSyncWorker()
        self.sync_worker.progress.connect(self._on_sync_progress)
        self.sync_worker.finished_sig.connect(self._on_annual_sync_finished)
        self.sync_worker.start()

    def _on_annual_sync_finished(self, success: bool, result: dict):
        if self.progress is not None:
            self.progress.reset()
        self.btn_sync_annual.setEnabled(True)
        errors = result.get("errors") or []
        if errors:
            QMessageBox.critical(self, "Échec de la synchronisation", "\n".join(errors))
            return
        stats = result.get("stats") or {}
        self.sync_result_lbl.setText(
            f"✅ {stats.get('nb_items', 0)} article(s) dans le miroir · "
            f"{stats.get('nb_auto', 0)} rattachement(s) automatique(s) · "
            f"{stats.get('nb_manual', 0)} correction(s) manuelle(s) conservée(s) · "
            f"{stats.get('nb_applied', 0)} paiement(s) reporté(s) · "
            f"{stats.get('nb_unlinked', 0)} à rattacher."
        )
        self._refresh_mirror_table()
        self._update_participants_view()
        self._refresh_bilan_seasons()
        unlinked = result.get("unlinked") or []
        if unlinked:
            self._run_manual_corrections(unlinked, current_competition=None)

    def on_attach_items(self):
        """Ouvre la boîte de rattachement des paiements en attente (miroir)."""
        unlinked = CompetitionRepository.list_unlinked_items()
        if not unlinked:
            QMessageBox.information(
                self, "Rien à rattacher",
                "Tous les paiements de la campagne sont rattachés à une compétition et un compétiteur."
            )
            return
        self._run_manual_corrections(unlinked, current_competition=None)

    def _on_sync_progress(self, message: str, percent: int):
        progress = self._ensure_progress()
        progress.setLabelText(message)
        progress.setValue(percent)

    def _run_manual_corrections(self, manual_review: list, current_competition=None):
        """Propose la correction manuelle des paiements sans rattachement complet.

        Chaque correction (ligne du miroir) crée un lien durable
        (item_links, source='manuel'), conservé lors des synchronisations suivantes,
        puis est reportée sur les participants.
        """
        dlg = ManualCorrectionDialog(manual_review, current_competition, self)
        if not dlg.exec() or not dlg.corrections:
            return
        for id_item, comp_id, adherent_id, _montant in dlg.corrections:
            CompetitionRepository.set_item_link(id_item, comp_id, adherent_id, source="manuel")
        # Report de TOUS les liens (y compris les corrections qui viennent d'être saisies)
        reported = CompetitionRepository.apply_links_to_participants()
        self._refresh_mirror_table()
        self._update_participants_view()
        QMessageBox.information(
            self, "Corrections appliquées",
            f"{reported} rattachement(s) enregistré(s) dans le miroir (persistants) · "
            f"paiements reportés sur les compétiteurs.",
        )

    # ------------------------------------------------------------------
    # Bilan de saison
    # ------------------------------------------------------------------
    def _on_global_tab_changed(self, index: int):
        text = self.global_tabs.tabText(index)
        if text.startswith("📊"):
            self.render_bilan()
        elif text.startswith("🔄"):
            self._update_helloasso_view()

    def _refresh_bilan_seasons(self):
        bilan = CompetitionRepository.get_bilan()
        seasons = bilan["seasons"]
        self.bilan_season_combo.blockSignals(True)
        self.bilan_season_combo.clear()
        if seasons:
            for s in seasons:
                self.bilan_season_combo.addItem(s)
        else:
            self.bilan_season_combo.addItem("")
        self.bilan_season_combo.blockSignals(False)

    def render_bilan(self):
        season = self.bilan_season_combo.currentText() if self.bilan_season_combo.count() else ""
        if not season:
            self.bilan_table.clear()
            self.bilan_table.setRowCount(1)
            self.bilan_table.setColumnCount(1)
            self.bilan_table.setHorizontalHeaderLabels(["Aucune compétition enregistrée pour le moment"])
            self.bilan_table.setItem(0, 0, QTableWidgetItem("—"))
            return

        bilan = CompetitionRepository.get_bilan(season)
        comps = bilan["competitions"]
        students = bilan["students"]
        parts = bilan["participations"]

        headers = ["Élève", "Licence FFME"] + [
            f"{c.nom}\n({datetime.date.fromisoformat(c.date_competition).strftime('%d/%m/%Y') if c.date_competition else '?'})"
            for c in comps
        ]
        self.bilan_table.clear()
        self.bilan_table.setColumnCount(len(headers))
        self.bilan_table.setHorizontalHeaderLabels(headers)
        self.bilan_table.setRowCount(len(students) + 1)

        cell_colors = {
            "paye": QColor(COLOR_SUCCESS), "en_attente": QColor(COLOR_WARNING),
        }
        row = 0
        for adherent_id, stu in students.items():
            nom_it = QTableWidgetItem(f"{stu['nom']} {stu['prenom']}")
            nom_it.setFlags(nom_it.flags() & ~Qt.ItemIsEditable)
            self.bilan_table.setItem(row, 0, nom_it)
            lic_it = QTableWidgetItem(stu.get("num_licence") or "—")
            lic_it.setFlags(lic_it.flags() & ~Qt.ItemIsEditable)
            self.bilan_table.setItem(row, 1, lic_it)
            for ci, c in enumerate(comps, start=2):
                statut = parts.get((adherent_id, c.id))
                if statut:
                    it = QTableWidgetItem(LIBELLES_STATUT_PAIEMENT.get(statut, statut))
                    color = cell_colors.get(statut)
                    if color:
                        it.setForeground(color)
                else:
                    it = QTableWidgetItem("")
                self.bilan_table.setItem(row, ci, it)
            row += 1

        # Ligne de totaux : nb de payés par compétition
        total_it = QTableWidgetItem("Total payés")
        total_it.setForeground(QColor("#1E293B"))
        self.bilan_table.setItem(row, 0, total_it)
        self.bilan_table.setItem(row, 1, QTableWidgetItem(""))
        for ci, c in enumerate(comps, start=2):
            nb = sum(1 for (aid, cid), st in parts.items() if cid == c.id and st == "paye")
            it = QTableWidgetItem(str(nb))
            it.setForeground(QColor(COLOR_SUCCESS))
            self.bilan_table.setItem(row, ci, it)
        self.bilan_table.resizeColumnsToContents()
        self.bilan_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)

    def on_export_bilan(self):
        season = self.bilan_season_combo.currentText() if self.bilan_season_combo.count() else ""
        if not season:
            QMessageBox.information(self, "Aucune donnée", "Rien à exporter : aucune compétition enregistrée.")
            return
        bilan = CompetitionRepository.get_bilan(season)
        comps, students, parts = bilan["competitions"], bilan["students"], bilan["participations"]

        out_dir = os.path.join(ROOT_DIR, "exports")
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, f"bilan_competitions_{season}.csv")
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f, separator=";")
            writer.writerow(["Bilan des compétitions - Saison", season])
            writer.writerow([])
            writer.writerow(["Nom", "Prénom", "Licence FFME", "Tarif"] +
                            [f"{c.nom} ({c.date_competition})" for c in comps])
            for adherent_id, stu in students.items():
                row = [stu.get("nom", ""), stu.get("prenom", ""),
                       stu.get("num_licence", ""), stu.get("tarif", "")]
                row += [LIBELLES_STATUT_PAIEMENT.get(parts.get((adherent_id, c.id), ""), "") for c in comps]
                writer.writerow(row)
        QMessageBox.information(self, "Export réussi", f"Bilan exporté :\n{path}")

    # ------------------------------------------------------------------
    # Google Drive
    # ------------------------------------------------------------------
    def _ensure_progress(self) -> QProgressDialog:
        """Crée la fenêtre de progression à la demande (titre et label définis :
        jamais de fenêtre vide intitulée « python » ni de ré-affichage spontané)."""
        if self.progress is None:
            self.progress = QProgressDialog(self)
            self.progress.setWindowTitle("Compétitions — opération en cours")
            self.progress.setLabelText("Opération en cours…")
            self.progress.setWindowModality(Qt.WindowModality.WindowModal)
            self.progress.setCancelButton(None)
            self.progress.setRange(0, 100)
            self.progress.hide()
        return self.progress

    def _start_drive_worker(self, mode: str):
        self.btn_drive_download.setEnabled(False)
        self.btn_drive_upload.setEnabled(False)
        progress = self._ensure_progress()
        progress.setLabelText("Connexion à Google Drive…")
        progress.setValue(10)
        progress.show()
        self.drive_worker = CompetitionDriveWorker(mode)
        self.drive_worker.progress.connect(self._on_drive_progress)
        self.drive_worker.finished_sig.connect(lambda ok, msg, m=mode: self._on_drive_finished(ok, msg, m))
        self.drive_worker.start()

    def _on_drive_progress(self, message: str, percent: int):
        progress = self._ensure_progress()
        progress.setLabelText(message)
        progress.setValue(percent)

    def _on_drive_finished(self, ok: bool, message: str, mode: str):
        if self.progress is not None:
            self.progress.reset()
        self.btn_drive_download.setEnabled(True)
        self.btn_drive_upload.setEnabled(True)
        self.drive_status_lbl.setText(message)
        if ok:
            # La base locale vient d'être remplacée (ou envoyée) : recharger tout l'état
            self.current_competition = None
            self._refresh_bilan_seasons()
            self.reload_competitions_list()
            QMessageBox.information(self, "Google Drive", message)
        else:
            QMessageBox.critical(self, "Échec Google Drive", message)
