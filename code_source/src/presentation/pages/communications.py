import os
import json
import datetime
from PySide6.QtCore import Qt, QDate, QSize, QEvent
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QTextEdit, QProgressBar, QFrame, QListWidget,
    QListWidgetItem, QSplitter, QComboBox, QCheckBox, QMessageBox,
    QRadioButton, QDialog, QDateEdit, QScrollArea, QSizePolicy,
    QGridLayout, QInputDialog
)
from PySide6.QtGui import QColor, QTextCursor
from PIL import Image, ImageDraw

from paths import CODE_ROOT
from domain.models import Member
from infrastructure.sqlite_repository import SqliteRepository, DEFAULT_SENDER_EMAIL, DEFAULT_SENDER_NAME
from infrastructure.competition_repository import CompetitionRepository
from domain.competition_models import LIBELLES_STATUT_PAIEMENT, LIBELLE_VERS_STATUT_PAIEMENT, PAIEMENT_NON_INVITE
from domain.utils import normalize_name
from infrastructure.schema_v2 import normalize_status
from presentation.workers import SendEmailCampaignWorker
from presentation.pages.members import (
    SubCategoryDialog, CANCELLED_STATUS, WAITING_LIST_TARIF,
    build_creneau_filter_blocks, build_default_tarif_selection, build_status_list,
    parse_order_date
)

# Texte d'invitation WhatsApp par défaut (utilisé si aucun texte n'a été sauvegardé en BDD)
DEFAULT_WHATSAPP_TEMPLATE = (
    "\n\n---\n"
    "🧗 Votre Groupe : {group_name}\n"
    "💬 Rejoins ton groupe WhatsApp pour ne rater aucune info : {whatsapp_link}\n"
    "📱 Le QRCode d'invitation est également joint en pièce jointe à cet e-mail."
)

def generate_check_icon() -> str:
    """Génère une icône de coche blanche transparente pour le style personnalisé des checkboxes."""
    icon_path = os.path.join(CODE_ROOT, "check_icon.png")
    if not os.path.exists(icon_path):
        try:
            # Créer un canvas transparent 16x16
            img = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)
            # Dessiner la coche en blanc
            draw.line([(3, 8), (7, 12)], fill=(255, 255, 255, 255), width=2)
            draw.line([(7, 12), (13, 4)], fill=(255, 255, 255, 255), width=2)
            img.save(icon_path, "PNG")
        except Exception:
            pass
    return icon_path.replace("\\", "/")

class CommunicationsPage(QWidget):
    """
    Page d'envoi d'e-mails et de suivi des communications asynchrone (Lot 5).
    Permet de filtrer et sélectionner individuellement les destinataires avec filtres avancés.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.members_list = []
        self.selected_tarifs = set()    # Tarifs cochés dans la pop-up (vide = tous)
        self.selected_statuses = set()  # Statuts cochés dans la pop-up (vide = tous)
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
                min-width: 100px;
            }
            QComboBox::drop-down {
                border: none;
            }
        """

    def get_filter_button_style(self) -> str:
        """Style commun des boutons ouvrant les pop-up de sélection (tarifs/statuts)."""
        return """
            QPushButton {
                background-color: #FFFFFF;
                border: 1px solid #CBD5E1;
                border-radius: 6px;
                padding: 5px 8px;
                font-size: 11px;
                color: #475569;
                min-width: 100px;
                text-align: left;
            }
            QPushButton:hover {
                background-color: #F8FAFC;
            }
        """

    def update_tarif_button(self):
        """Met à jour le libellé du bouton de sous-catégories (libellés identiques à l'onglet Adhérents)."""
        default_tarifs = build_default_tarif_selection(self.members_list)
        count = len(self.selected_tarifs)
        if count == 0 or self.selected_tarifs == default_tarifs | {WAITING_LIST_TARIF}:
            self.tarif_filter.setText("Toutes les sous-catégories ▾")
        elif self.selected_tarifs == default_tarifs:
            self.tarif_filter.setText("Toutes sauf liste d'attente ▾")
        else:
            self.tarif_filter.setText(f"Sous-catégories ({count}) ▾")

    def update_status_button(self):
        """Met à jour le libellé du bouton statuts selon la sélection courante."""
        all_statuses = set(build_status_list(self.members_list))
        if not self.selected_statuses or self.selected_statuses == all_statuses:
            self.status_filter.setText("Tous les statuts ▾")
        elif self.selected_statuses == all_statuses - {CANCELLED_STATUS}:
            self.status_filter.setText("Tous sauf annulés ▾")
        else:
            self.status_filter.setText(f"Statuts ({len(self.selected_statuses)}) ▾")

    def open_tarif_popup(self):
        """Ouvre la pop-up de sélection des sous-catégories (identique à l'onglet Adhérents :
        rubriques de créneaux du planning, une case cochée sélectionne tous les tarifs
        rattachés au créneau)."""
        dialog = SubCategoryDialog(
            [],
            self.selected_tarifs,
            on_change=self.on_popup_selection_changed,
            hierarchy=build_creneau_filter_blocks(self.members_list),
            parent=self
        )
        dialog.exec()
        self.on_filters_changed()

    def open_status_popup(self):
        """Ouvre la pop-up de sélection des statuts (cases à cocher)."""
        dialog = SubCategoryDialog(
            [("Statuts", build_status_list(self.members_list))],
            self.selected_statuses,
            on_change=self.on_popup_selection_changed,
            parent=self,
            title="Sélection des statuts"
        )
        dialog.exec()
        self.on_filters_changed()

    def on_popup_selection_changed(self):
        """Déclenché à chaque changement de case à cocher dans une pop-up (filtrage en direct)."""
        self.update_tarif_button()
        self.update_status_button()
        self.on_filters_changed()

    # ------------------------------------------------------------------
    # Styles QSS centralises de la page Communications
    # ------------------------------------------------------------------
    QSS_CARD = "QFrame { background-color: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 10px; } QLabel { background: transparent; border: none; }"
    QSS_INNER = "QFrame { background-color: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 8px; } QLabel { background: transparent; border: none; }"
    QSS_BAR = "QFrame { background-color: #EFF6FF; border: 1px solid #DBEAFE; border-radius: 8px; } QLabel { background: transparent; border: none; }"
    QSS_BTN_PRIMARY = """
        QPushButton {
            background-color: #2563EB; color: #FFFFFF; border: none;
            border-radius: 6px; padding: 8px 14px; font-size: 12px; font-weight: bold;
        }
        QPushButton:hover { background-color: #1D4ED8; }
        QPushButton:disabled { background-color: #94A3B8; }
    """
    QSS_BTN_SECONDARY = """
        QPushButton {
            background-color: #FFFFFF; color: #334155; border: 1px solid #CBD5E1;
            border-radius: 6px; padding: 7px 12px; font-size: 12px; font-weight: 600;
        }
        QPushButton:hover { background-color: #F8FAFC; border-color: #94A3B8; }
    """
    QSS_BTN_DANGER = """
        QPushButton {
            background-color: #FFFFFF; color: #B91C1C; border: 1px solid #FCA5A5;
            border-radius: 6px; padding: 7px 12px; font-size: 12px; font-weight: 600;
        }
        QPushButton:hover { background-color: #FEF2F2; border-color: #DC2626; }
    """
    QSS_PILL = "QLabel { background-color: #DBEAFE; color: #1D4ED8; border-radius: 9px; padding: 3px 10px; font-size: 11px; font-weight: bold; }"
    QSS_CARD_TITLE = "font-size: 14px; font-weight: bold; color: #1E293B; background: transparent; border: none;"
    QSS_FIELD_LABEL = "color: #475569; font-size: 11px; font-weight: 600; background: transparent; border: none;"

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 15, 20, 20)
        layout.setSpacing(8)

        # 1. TITRE + SOUS-TITRE (gabarit commun de l application)
        title = QLabel("\u2709 Communications")
        title.setStyleSheet("font-size: 24px; font-weight: bold; color: #1E293B;")
        title.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        layout.addWidget(title)

        subtitle = QLabel("Envoyez un message personnalis\u00e9 aux adh\u00e9rents")
        subtitle.setStyleSheet("color: #64748B; font-size: 13px;")
        subtitle.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        layout.addWidget(subtitle)

        # 2. INDICATEUR DE WORKFLOW (purement visuel)
        self.wf_bar = QFrame()
        self.wf_bar.setObjectName("WorkflowBar")
        self.wf_bar.setStyleSheet(self.QSS_BAR)
        wf_layout = QHBoxLayout(self.wf_bar)
        wf_layout.setContentsMargins(16, 8, 16, 8)
        wf_layout.setSpacing(10)

        def _wf_step(badge_text, active, title_text, detail_label):
            badge = QLabel(badge_text)
            badge.setFixedSize(26, 26)
            badge.setAlignment(Qt.AlignCenter)
            color = "#2563EB" if active else "#94A3B8"
            badge.setStyleSheet(f"QLabel {{ background-color: {color}; color: #FFFFFF; border-radius: 13px; font-size: 12px; font-weight: bold; }}")
            wf_layout.addWidget(badge)
            col = QVBoxLayout()
            col.setSpacing(0)
            t = QLabel(title_text)
            t.setStyleSheet("font-size: 12px; font-weight: bold; color: #1E293B; background: transparent;")
            col.addWidget(t)
            detail_label.setStyleSheet("font-size: 11px; color: #64748B; background: transparent;")
            col.addWidget(detail_label)
            wf_layout.addLayout(col)

        self.wf_step1_lbl = QLabel("0 s\u00e9lectionn\u00e9")
        _wf_step("\u2460", True, "Destinataires", self.wf_step1_lbl)
        wf_layout.addStretch()
        wf_layout.addWidget(self._vsep())
        wf_layout.addStretch()
        self.wf_step2_lbl = QLabel("\u2014")
        _wf_step("\u2461", True, "Message", self.wf_step2_lbl)
        wf_layout.addStretch()
        wf_layout.addWidget(self._vsep())
        wf_layout.addStretch()
        self.wf_step3_lbl = QLabel("Aucun destinataire")
        _wf_step("\u2462", False, "V\u00e9rification", self.wf_step3_lbl)
        wf_layout.addStretch()
        wf_layout.addWidget(self._vsep())
        wf_layout.addStretch()
        self.wf_step4_lbl = QLabel("\u2014")
        _wf_step("\u2463", False, "Envoi", self.wf_step4_lbl)
        layout.addWidget(self.wf_bar)

        # 3. SPLITTER : DESTINATAIRES (gauche) / MESSAGE (droite, un peu plus large)
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setStyleSheet("""
            QSplitter::handle {
                background-color: #E2E8F0;
                width: 1px;
            }
        """)
        # ------------------ COTE GAUCHE : DESTINATAIRES ------------------
        left_container = QWidget()
        left_layout = QVBoxLayout(left_container)
        left_layout.setContentsMargins(0, 0, 8, 0)
        left_layout.setSpacing(8)

        dest_card = QFrame()
        dest_card.setStyleSheet(self.QSS_CARD)
        dest_layout = QVBoxLayout(dest_card)
        dest_layout.setContentsMargins(14, 12, 14, 12)
        dest_layout.setSpacing(8)

        dest_head = QHBoxLayout()
        lbl_dest = QLabel("\U0001F465 Destinataires")
        lbl_dest.setStyleSheet(self.QSS_CARD_TITLE)
        dest_head.addWidget(lbl_dest)
        dest_head.addStretch()
        self.dest_title = QLabel("0 s\u00e9lectionn\u00e9s")
        self.dest_title.setStyleSheet(self.QSS_PILL)
        dest_head.addWidget(self.dest_title)
        dest_layout.addLayout(dest_head)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("\U0001F50E Rechercher un adh\u00e9rent (nom, pr\u00e9nom, e-mail)...")
        self.search_input.setStyleSheet("""
            QLineEdit {
                background-color: #FFFFFF;
                border: 1px solid #CBD5E1;
                border-radius: 6px;
                padding: 7px 10px;
                font-size: 12px;
                color: #1E293B;
            }
        """)
        self.search_input.textChanged.connect(self.on_search_changed)
        dest_layout.addWidget(self.search_input)

        # Carte Filtres
        filters_frame = QFrame()
        filters_frame.setStyleSheet(self.QSS_INNER)
        filters_layout = QVBoxLayout(filters_frame)
        filters_layout.setContentsMargins(10, 8, 10, 10)
        filters_layout.setSpacing(6)

        f_head = QHBoxLayout()
        lbl_filters = QLabel("\u2699 Filtres")
        lbl_filters.setStyleSheet("color: #334155; font-size: 12px; font-weight: bold; background: transparent; border: none;")
        f_head.addWidget(lbl_filters)
        f_head.addStretch()
        self.btn_reset_filters = QPushButton("\u21ba R\u00e9initialiser")
        self.btn_reset_filters.setCursor(Qt.PointingHandCursor)
        self.btn_reset_filters.setToolTip("Remet tous les filtres \u00e0 z\u00e9ro (saison, statut, cr\u00e9neau, sant\u00e9, dipl\u00f4me, recherche).")
        self.btn_reset_filters.setStyleSheet("""
            QPushButton {
                background-color: transparent; color: #2563EB; border: none;
                padding: 2px 6px; font-size: 11px; font-weight: 600;
            }
            QPushButton:hover { text-decoration: underline; }
        """)
        self.btn_reset_filters.clicked.connect(self.reset_filters)
        f_head.addWidget(self.btn_reset_filters)
        filters_layout.addLayout(f_head)

        f_grid = QGridLayout()
        f_grid.setHorizontalSpacing(10)
        f_grid.setVerticalSpacing(4)
        lbl_season = QLabel("Saison")
        lbl_season.setStyleSheet(self.QSS_FIELD_LABEL)
        self.season_filter = QComboBox()
        self.season_filter.addItems([
            "Saison 2026-2027 (Active)",
            "Saison 2025-2026",
            "Toutes les saisons confondues",
            "Anciens non r\u00e9inscrits (Pr\u00e9sents en 25/26 mais pas en 26/27)"
        ])
        self.season_filter.setStyleSheet(self.get_combobox_style())
        self.season_filter.currentIndexChanged.connect(self.on_season_changed)
        lbl_status = QLabel("Statut")
        lbl_status.setStyleSheet(self.QSS_FIELD_LABEL)
        self.status_filter = QPushButton("Tous les statuts \u25be")
        self.status_filter.setCursor(Qt.PointingHandCursor)
        self.status_filter.setStyleSheet(self.get_filter_button_style())
        self.status_filter.clicked.connect(self.open_status_popup)
        lbl_tarif = QLabel("Cr\u00e9neau")
        lbl_tarif.setStyleSheet(self.QSS_FIELD_LABEL)
        self.tarif_filter = QPushButton("Toutes les sous-cat\u00e9gories \u25be")
        self.tarif_filter.setCursor(Qt.PointingHandCursor)
        self.tarif_filter.setStyleSheet(self.get_filter_button_style())
        self.tarif_filter.clicked.connect(self.open_tarif_popup)
        for col_idx, w in enumerate((lbl_season, lbl_status, lbl_tarif)):
            f_grid.addWidget(w, 0, col_idx)
        for col_idx, w in enumerate((self.season_filter, self.status_filter, self.tarif_filter)):
            f_grid.addWidget(w, 1, col_idx)
        filters_layout.addLayout(f_grid)

        checks_row = QHBoxLayout()
        checks_row.setSpacing(14)
        self.health_filter_checkbox = QCheckBox("\u26a0 Sant\u00e9 en attente")
        self.health_filter_checkbox.setToolTip(
            "N'affiche que les adh\u00e9rents dont le Document de sant\u00e9 FFME est \u00ab ATTENTE \u00bb."
        )
        self.health_filter_checkbox.setStyleSheet("color: #475569; font-size: 11px; font-weight: 500; background: transparent;")
        self.health_filter_checkbox.stateChanged.connect(self.on_filters_changed)
        checks_row.addWidget(self.health_filter_checkbox)
        self.diploma_filter_checkbox = QCheckBox("\U0001F393 Sans dipl\u00f4me")
        self.diploma_filter_checkbox.setToolTip(
            "N'affiche que les adh\u00e9rents qui n'ont ni le Badge Rouge ni le Passeport Orange "
            "(utile pour relancer l'obtention des dipl\u00f4mes FFME)."
        )
        self.diploma_filter_checkbox.setStyleSheet("color: #475569; font-size: 11px; font-weight: 500; background: transparent;")
        self.diploma_filter_checkbox.stateChanged.connect(self.on_filters_changed)
        checks_row.addWidget(self.diploma_filter_checkbox)
        checks_row.addStretch()
        filters_layout.addLayout(checks_row)

        adv_row = QHBoxLayout()
        adv_row.setSpacing(6)
        self.sent_filter = QComboBox()
        self.sent_filter.addItems(["Tous les envois", "Non envoy\u00e9s", "Envoy\u00e9s"])
        self.sent_filter.setStyleSheet(self.get_combobox_style())
        self.sent_filter.currentIndexChanged.connect(self.on_filters_changed)
        adv_row.addWidget(self.sent_filter)
        self.date_checkbox = QCheckBox("Inscrit apr\u00e8s le :")
        self.date_checkbox.setStyleSheet("color: #475569; font-size: 11px; font-weight: 500; background: transparent;")
        self.date_checkbox.stateChanged.connect(self.on_filters_changed)
        adv_row.addWidget(self.date_checkbox)
        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDate(QDate(2026, 7, 1))
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
        adv_row.addWidget(self.date_edit)
        adv_row.addStretch()
        filters_layout.addLayout(adv_row)

        # Filtre « Compétition » (Nouveau !) : cible les compétiteurs sélectionnés d'une
        # épreuve de database_Competition.db ; le filtre de paiement permet les relances.
        comp_row = QHBoxLayout()
        comp_row.setSpacing(6)
        lbl_comp = QLabel("🏆 Compétition")
        lbl_comp.setStyleSheet("color: #475569; font-size: 11px; font-weight: 500; background: transparent;")
        comp_row.addWidget(lbl_comp)
        self.competition_filter = QComboBox()
        self.competition_filter.setStyleSheet(self.get_combobox_style())
        self.competition_filter.currentIndexChanged.connect(self.on_competition_filter_changed)
        comp_row.addWidget(self.competition_filter, 1)
        self.competition_paiement_filter = QComboBox()
        self.competition_paiement_filter.addItems(["Tous les paiements"] + list(LIBELLES_STATUT_PAIEMENT.values()))
        self.competition_paiement_filter.setEnabled(False)
        self.competition_paiement_filter.setStyleSheet(self.get_combobox_style())
        self.competition_paiement_filter.currentIndexChanged.connect(self.on_filters_changed)
        comp_row.addWidget(self.competition_paiement_filter)
        filters_layout.addLayout(comp_row)
        self.load_competition_filters()
        dest_layout.addWidget(filters_frame)
        # Boutons de selection compacts
        sel_btns = QHBoxLayout()
        sel_btns.setSpacing(6)
        self.btn_select_all = QPushButton("\u2611  Tout s\u00e9lectionner (0)")
        self.btn_select_all.setCursor(Qt.PointingHandCursor)
        self.btn_select_all.setStyleSheet(self.QSS_BTN_PRIMARY)
        self.btn_select_all.clicked.connect(self.select_visible)
        sel_btns.addWidget(self.btn_select_all)

        self.btn_deselect_filtered = QPushButton("\u2610  D\u00e9cocher le filtre")
        self.btn_deselect_filtered.setCursor(Qt.PointingHandCursor)
        self.btn_deselect_filtered.setStyleSheet(self.QSS_BTN_SECONDARY)
        self.btn_deselect_filtered.clicked.connect(self.deselect_visible)
        sel_btns.addWidget(self.btn_deselect_filtered)

        self.btn_clear_selection = QPushButton("\U0001F5D1  Tout d\u00e9s\u00e9lectionner")
        self.btn_clear_selection.setCursor(Qt.PointingHandCursor)
        self.btn_clear_selection.setToolTip("D\u00e9coche tous les destinataires, y compris ceux masqu\u00e9s par les filtres.")
        self.btn_clear_selection.setStyleSheet(self.QSS_BTN_DANGER)
        self.btn_clear_selection.clicked.connect(self.deselect_all_members)
        sel_btns.addWidget(self.btn_clear_selection)
        sel_btns.addStretch()
        dest_layout.addLayout(sel_btns)

        # Encart repliable des personnes selectionnees
        self.selected_panel_btn = QPushButton("\u2713 Personnes s\u00e9lectionn\u00e9es (0) \u25b8")
        self.selected_panel_btn.setCursor(Qt.PointingHandCursor)
        self.selected_panel_btn.setStyleSheet("""
            QPushButton {
                background-color: #FFFFFF;
                border: 1px solid #CBD5E1;
                border-radius: 6px;
                padding: 5px 10px;
                font-size: 11px;
                font-weight: 500;
                color: #059669;
                text-align: left;
            }
            QPushButton:hover {
                background-color: #ECFDF5;
                border-color: #A7F3D0;
            }
        """)
        self.selected_panel_btn.clicked.connect(self.toggle_selected_panel)
        dest_layout.addWidget(self.selected_panel_btn)

        self.selected_panel = QListWidget()
        self.selected_panel.setVisible(False)
        self._selected_panel_open = False
        self.selected_panel.setFixedHeight(150)
        self.selected_panel.setToolTip("Destinataires coch\u00e9s, m\u00eame s'ils sont masqu\u00e9s par les filtres.")
        self.selected_panel.setStyleSheet("""
            QListWidget {
                background-color: #F8FAFC;
                border: 1px solid #A7F3D0;
                border-radius: 6px;
                padding: 4px;
                font-size: 11px;
                color: #1E293B;
            }
            QListWidget::item {
                padding: 2px 6px;
                border-bottom: 1px solid #D1FAE5;
            }
        """)
        dest_layout.addWidget(self.selected_panel)

        # Liste des destinataires (items riches)
        icon_url = generate_check_icon()
        self.list_widget = QListWidget()
        self.list_widget.setStyleSheet(f"""
            QListWidget {{
                background-color: #FFFFFF;
                border: none;
                padding: 5px;
            }}
            QListWidget::item {{
                padding: 4px;
                border: none;
            }}
            QListWidget::item:hover {{
                background-color: #F8FAFC;
            }}
            QListWidget::item:selected {{
                background-color: #EFF6FF;
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
        self.list_widget.setSpacing(2)
        dest_layout.addWidget(self.list_widget, 1)

        dest_footer = QHBoxLayout()
        self.footer_lbl = QLabel("\U0001F465 0 destinataire s\u00e9lectionn\u00e9")
        self.footer_lbl.setStyleSheet("color: #64748B; font-size: 11px; font-weight: 600; background: transparent;")
        dest_footer.addWidget(self.footer_lbl)
        dest_footer.addStretch()
        self.btn_show_all = QPushButton("Tout afficher")
        self.btn_show_all.setCursor(Qt.PointingHandCursor)
        self.btn_show_all.setToolTip("Efface la recherche pour r\u00e9afficher tous les destinataires.")
        self.btn_show_all.setStyleSheet("""
            QPushButton {
                background-color: transparent; color: #2563EB; border: none;
                padding: 2px 6px; font-size: 11px; font-weight: 600;
            }
            QPushButton:hover { text-decoration: underline; }
        """)
        self.btn_show_all.clicked.connect(self.show_all_recipients)
        dest_footer.addWidget(self.btn_show_all)
        dest_layout.addLayout(dest_footer)

        left_layout.addWidget(dest_card, 1)
        self.splitter.addWidget(left_container)
        # ------------------ COTE DROIT : MESSAGE ------------------
        right_container = QWidget()
        right_layout = QVBoxLayout(right_container)
        right_layout.setContentsMargins(8, 0, 0, 0)
        right_layout.setSpacing(8)

        form_widget = QWidget()
        form_layout = QVBoxLayout(form_widget)
        form_layout.setContentsMargins(0, 0, 0, 0)
        form_layout.setSpacing(10)
        self.form_frame = form_widget  # compatibilite du nom historique

        # Carte Modele d e-mail
        template_card = QFrame()
        template_card.setStyleSheet(self.QSS_CARD)
        tc_layout = QVBoxLayout(template_card)
        tc_layout.setContentsMargins(14, 12, 14, 12)
        tc_layout.setSpacing(8)
        lbl_tpl = QLabel("\U0001F4C4 Mod\u00e8le d e-mail")
        lbl_tpl.setStyleSheet(self.QSS_CARD_TITLE)
        tc_layout.addWidget(lbl_tpl)
        tpl_row = QHBoxLayout()
        tpl_row.setSpacing(6)
        self.template_selector = QComboBox()
        self.template_selector.setStyleSheet("""
            QComboBox {
                background-color: #FFFFFF;
                border: 1px solid #CBD5E1;
                border-radius: 6px;
                padding: 6px;
                color: #1E293B;
            }
        """)
        self.template_selector.currentIndexChanged.connect(self.on_template_selected)
        tpl_row.addWidget(self.template_selector, 1)

        self.btn_save_template = QPushButton("\U0001F4BE Enregistrer")
        self.btn_save_template.setStyleSheet(self.QSS_BTN_PRIMARY)
        self.btn_save_template.clicked.connect(self.on_save_template_clicked)
        tpl_row.addWidget(self.btn_save_template)

        self.btn_new_template = QPushButton("\u2795 Nouveau")
        self.btn_new_template.setStyleSheet(self.QSS_BTN_SECONDARY)
        self.btn_new_template.clicked.connect(self.on_new_template_clicked)
        tpl_row.addWidget(self.btn_new_template)

        self.btn_delete_template = QPushButton("\U0001F5D1 Supprimer")
        self.btn_delete_template.setStyleSheet(self.QSS_BTN_DANGER)
        self.btn_delete_template.clicked.connect(self.on_delete_template_clicked)
        tpl_row.addWidget(self.btn_delete_template)
        tc_layout.addLayout(tpl_row)
        form_layout.addWidget(template_card)

        # Carte Message
        message_card = QFrame()
        message_card.setStyleSheet(self.QSS_CARD)
        mc_layout = QVBoxLayout(message_card)
        mc_layout.setContentsMargins(14, 12, 14, 12)
        mc_layout.setSpacing(6)
        lbl_msg = QLabel("\u2709 Message")
        lbl_msg.setStyleSheet(self.QSS_CARD_TITLE)
        mc_layout.addWidget(lbl_msg)

        sender_row = QHBoxLayout()
        sender_row.setSpacing(8)
        sender_col = QVBoxLayout()
        sender_col.setSpacing(2)
        lbl_sender = QLabel("Exp\u00e9diteur")
        lbl_sender.setStyleSheet(self.QSS_FIELD_LABEL)
        sender_col.addWidget(lbl_sender)
        sender_email_row = QHBoxLayout()
        sender_email_row.setSpacing(4)
        self.sender_email_combo = QComboBox()
        self.sender_email_combo.setEditable(True)
        self.sender_email_combo.setToolTip(
            "Adresse utilis\u00e9e comme exp\u00e9diteur (De) des e-mails.\n"
            "Elle est enregistr\u00e9e avec le mod\u00e8le d e-mail et r\u00e9utilis\u00e9e \u00e0 chaque envoi."
        )
        self.sender_email_combo.setStyleSheet("""
            QComboBox {
                background-color: #FFFFFF;
                border: 1px solid #CBD5E1;
                border-radius: 6px;
                padding: 6px;
                color: #1E293B;
            }
            QComboBox::drop-down {
                border: none;
            }
            QComboBox QAbstractItemView {
                background-color: #FFFFFF;
                selection-background-color: #EFF6FF;
                selection-color: #1E293B;
            }
            QComboBox QLineEdit {
                border: none;
                background: transparent;
                color: #1E293B;
            }
        """)
        sender_email_row.addWidget(self.sender_email_combo, 1)
        self.btn_save_sender = QPushButton("\U0001F4BE")
        self.btn_save_sender.setFixedSize(30, 30)
        self.btn_save_sender.setToolTip(
            "Enregistre cette adresse comme exp\u00e9diteur par d\u00e9faut de la Communication "
            "(elle est aussi m\u00e9moris\u00e9e dans la liste d\u00e9roulante)."
        )
        self.btn_save_sender.setStyleSheet(self.QSS_BTN_SECONDARY)
        self.btn_save_sender.clicked.connect(self.on_save_sender_clicked)
        sender_email_row.addWidget(self.btn_save_sender)
        sender_col.addLayout(sender_email_row)
        sender_row.addLayout(sender_col, 2)

        name_col = QVBoxLayout()
        name_col.setSpacing(2)
        lbl_name = QLabel("Nom affich\u00e9")
        lbl_name.setStyleSheet(self.QSS_FIELD_LABEL)
        name_col.addWidget(lbl_name)
        self.sender_name_input = QLineEdit()
        self.sender_name_input.setPlaceholderText(DEFAULT_SENDER_NAME)
        self.sender_name_input.setToolTip(
            "Nom affich\u00e9 dans la colonne \u00ab De \u00bb des messageries (ex : Amicale La\u00efque Jonage - Inscriptions).\n"
            "Il est enregistr\u00e9 avec le mod\u00e8le d e-mail et r\u00e9utilis\u00e9 \u00e0 chaque envoi."
        )
        self.sender_name_input.setStyleSheet("""
            QLineEdit {
                background-color: #FFFFFF;
                border: 1px solid #CBD5E1;
                border-radius: 6px;
                padding: 6px;
                color: #1E293B;
            }
        """)
        name_col.addWidget(self.sender_name_input)
        sender_row.addLayout(name_col, 1)
        mc_layout.addLayout(sender_row)

        lbl_subject = QLabel("Objet")
        lbl_subject.setStyleSheet(self.QSS_FIELD_LABEL)
        mc_layout.addWidget(lbl_subject)
        self.subject_input = QLineEdit()
        self.subject_input.setPlaceholderText("Entrez le sujet de l email...")
        self.subject_input.setText("[ALJ] Attestation de paiement relative \u00e0 votre adh\u00e9sion \u00e0 l Amicale La\u00efque de Jonage")
        self.subject_input.setStyleSheet("""
            QLineEdit {
                background-color: #FFFFFF;
                border: 1px solid #CBD5E1;
                border-radius: 6px;
                padding: 7px;
                color: #1E293B;
            }
        """)
        mc_layout.addWidget(self.subject_input)

        body_head = QHBoxLayout()
        lbl_body = QLabel("Corps du message")
        lbl_body.setStyleSheet(self.QSS_FIELD_LABEL)
        body_head.addWidget(lbl_body)
        body_head.addStretch()
        self.btn_variables = QPushButton("{ }  Variables")
        self.btn_variables.setCursor(Qt.PointingHandCursor)
        self.btn_variables.setToolTip("Affiche les variables personnalis\u00e9es utilisables dans le message.")
        self.btn_variables.setStyleSheet(self.QSS_BTN_SECONDARY)
        self.btn_variables.clicked.connect(self.show_variables_hint)
        body_head.addWidget(self.btn_variables)
        mc_layout.addLayout(body_head)

        # Barre d'outils de mise en forme (insère des balises dans le texte brut) :
        # Gras <b>, Italique <i>, Souligné <u>, Lien externe <a href>.
        fmt_row = QHBoxLayout()
        fmt_row.setSpacing(6)
        fmt_lbl = QLabel("Mise en forme :")
        fmt_lbl.setStyleSheet("color: #64748B; font-size: 12px;")
        fmt_row.addWidget(fmt_lbl)
        for label, tag, tip in (
            ("<b>G</b>", "b", "Gras : entoure la sélection avec <b>…</b>"),
            ("<i>I</i>", "i", "Italique : entoure la sélection avec <i>…</i>"),
            ("<u>S</u>", "u", "Souligné : entoure la sélection avec <u>…</u>"),
        ):
            btn = QPushButton(label)
            btn.setFixedSize(30, 26)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setToolTip(tip)
            btn.setStyleSheet(self.QSS_BTN_SECONDARY)
            btn.clicked.connect(lambda _c, tg=tag: self._wrap_body_tag(tg))
            fmt_row.addWidget(btn)
        self.btn_body_link = QPushButton("🔗 Lien externe")
        self.btn_body_link.setCursor(Qt.PointingHandCursor)
        self.btn_body_link.setToolTip("Insère un lien cliquable vers un site externe (<a href=\"…\">…) à la position du curseur.")
        self.btn_body_link.setStyleSheet(self.QSS_BTN_SECONDARY)
        self.btn_body_link.clicked.connect(self._insert_body_link)
        fmt_row.addWidget(self.btn_body_link)
        fmt_row.addStretch()
        mc_layout.addLayout(fmt_row)

        self.body_input = QTextEdit()
        self.body_input.setPlaceholderText("Saisissez le texte d accompagnement...")
        self.body_input.setAcceptRichText(False)  # corps = texte brut + balises autorisées (<b>, <i>, <a>…)
        self.body_input.setPlainText(
            "Bonjour {first_name},\n\n"
            "Veuillez trouver ci-joint l attestation de paiement relative \u00e0 votre adh\u00e9sion au club d escalade "
            "pour la saison active.\n\n"
            "Sportivement,\n"
            "L \u00e9quipe ALJ Escalade"
        )
        self.body_input.setMinimumHeight(200)
        self.body_input.setStyleSheet("""
            QTextEdit {
                background-color: #FFFFFF;
                border: 1px solid #CBD5E1;
                border-radius: 6px;
                padding: 6px;
                color: #1E293B;
            }
        """)
        mc_layout.addWidget(self.body_input, 1)
        form_layout.addWidget(message_card, 1)
        # Carte Options d envoi
        options_card = QFrame()
        options_card.setStyleSheet(self.QSS_CARD)
        opt_layout = QVBoxLayout(options_card)
        opt_layout.setContentsMargins(14, 12, 14, 12)
        opt_layout.setSpacing(6)
        lbl_opt = QLabel("\u2699 Options d envoi")
        lbl_opt.setStyleSheet(self.QSS_CARD_TITLE)
        opt_layout.addWidget(lbl_opt)

        self.attach_pdf_checkbox = QCheckBox("Joindre l attestation de paiement (PDF)")
        self.attach_pdf_checkbox.setChecked(False)
        self.attach_pdf_checkbox.setStyleSheet("color: #475569; font-size: 12px; font-weight: 500; background: transparent;")
        opt_layout.addWidget(self.attach_pdf_checkbox)

        self.attach_whatsapp_checkbox = QCheckBox("Joindre l invitation & le QRCode WhatsApp du cr\u00e9neau")
        self.attach_whatsapp_checkbox.setChecked(False)
        self.attach_whatsapp_checkbox.setStyleSheet("color: #475569; font-size: 12px; font-weight: 500; background: transparent;")
        opt_layout.addWidget(self.attach_whatsapp_checkbox)

        # Gabarit WhatsApp (conditionne par la case ci-dessus)
        self.whatsapp_template_widget = QWidget()
        wtmp_layout = QVBoxLayout(self.whatsapp_template_widget)
        wtmp_layout.setContentsMargins(18, 2, 0, 4)
        wtmp_layout.setSpacing(4)
        wtmp_head = QHBoxLayout()
        lbl_wt = QLabel("\U0001F4DD Texte d invitation WhatsApp (supporte {group_name} et {whatsapp_link}) :")
        lbl_wt.setStyleSheet("color: #475569; font-size: 11px; font-weight: bold; background: transparent;")
        wtmp_head.addWidget(lbl_wt)
        wtmp_head.addStretch()
        self.btn_save_whatsapp_template = QPushButton("\U0001F4BE Enregistrer")
        self.btn_save_whatsapp_template.setToolTip("Enregistre ce texte WhatsApp en base de donn\u00e9es pour tous les prochains envois.")
        self.btn_save_whatsapp_template.setStyleSheet(self.QSS_BTN_SECONDARY)
        self.btn_save_whatsapp_template.clicked.connect(self.on_save_whatsapp_template_clicked)
        wtmp_head.addWidget(self.btn_save_whatsapp_template)
        wtmp_layout.addLayout(wtmp_head)
        self.whatsapp_template_input = QTextEdit()
        saved_wt = SqliteRepository.get_whatsapp_template()
        self.whatsapp_template_input.setPlainText(saved_wt if saved_wt else DEFAULT_WHATSAPP_TEMPLATE)
        self.whatsapp_template_input.setStyleSheet("""
            QTextEdit {
                border: 1px solid #CBD5E1;
                border-radius: 6px;
                padding: 5px;
                color: #1E293B;
                min-height: 60px;
                max-height: 90px;
                font-size: 11px;
            }
        """)
        wtmp_layout.addWidget(self.whatsapp_template_input)
        opt_layout.addWidget(self.whatsapp_template_widget)
        # Le texte d invitation WhatsApp n est visible que si la case d envoi est cochée
        self.attach_whatsapp_checkbox.toggled.connect(self.whatsapp_template_widget.setVisible)
        self.whatsapp_template_widget.setVisible(self.attach_whatsapp_checkbox.isChecked())

        # Signature du club
        lbl_sig = QLabel("Signature du club")
        lbl_sig.setStyleSheet(self.QSS_FIELD_LABEL)
        opt_layout.addWidget(lbl_sig)
        sig_row = QHBoxLayout()
        sig_row.setSpacing(16)
        self.signature_yes_radio = QRadioButton("\u2713 Ajouter la signature du club (logos Instagram & Facebook)")
        self.signature_yes_radio.setChecked(True)
        self.signature_yes_radio.setStyleSheet("color: #475569; font-size: 12px; font-weight: 500; background: transparent;")
        sig_row.addWidget(self.signature_yes_radio)
        self.signature_no_radio = QRadioButton("Sans signature")
        self.signature_no_radio.setStyleSheet("color: #475569; font-size: 12px; font-weight: 500; background: transparent;")
        sig_row.addWidget(self.signature_no_radio)
        sig_row.addStretch()
        opt_layout.addLayout(sig_row)

        # Repli : options avancees (adresses de destination + dedoublonnage)
        self.btn_advanced = QCheckBox("\u25b8 Options avanc\u00e9es (adresses de destination & d\u00e9doublonnage)")
        self.btn_advanced.setStyleSheet("""
            QCheckBox {
                color: #2563EB; font-size: 12px; font-weight: 600;
                background: transparent; border: none; padding: 2px 0;
            }
            QCheckBox:hover { text-decoration: underline; }
        """)
        opt_layout.addWidget(self.btn_advanced)

        self.advanced_widget = QWidget()
        adv_layout = QVBoxLayout(self.advanced_widget)
        adv_layout.setContentsMargins(18, 2, 0, 2)
        adv_layout.setSpacing(4)
        lbl_dest_choice = QLabel("Choix des adresses de destination")
        lbl_dest_choice.setStyleSheet(self.QSS_FIELD_LABEL)
        adv_layout.addWidget(lbl_dest_choice)

        self.use_primary_email_cb = QCheckBox("Envoyer \u00e0 l E-mail Principal (Fiche Adh\u00e9rent)")
        self.use_primary_email_cb.setChecked(True)
        self.use_primary_email_cb.setStyleSheet("color: #475569; font-size: 12px; font-weight: 500; background: transparent;")
        adv_layout.addWidget(self.use_primary_email_cb)

        self.use_secondary_email_cb = QCheckBox("Envoyer au Deuxi\u00e8me E-mail (Fiche Adh\u00e9rent)")
        self.use_secondary_email_cb.setChecked(True)
        self.use_secondary_email_cb.setStyleSheet("color: #475569; font-size: 12px; font-weight: 500; background: transparent;")
        adv_layout.addWidget(self.use_secondary_email_cb)

        self.use_payer_email_cb = QCheckBox("Envoyer \u00e0 l E-mail du Payeur (Acheteur HelloAsso)")
        self.use_payer_email_cb.setChecked(False)
        self.use_payer_email_cb.setStyleSheet("color: #475569; font-size: 12px; font-weight: 500; background: transparent;")
        adv_layout.addWidget(self.use_payer_email_cb)

        self.btn_remove_duplicates = QPushButton("\U0001F9F9 Supprimer les doublons de la s\u00e9lection")
        self.btn_remove_duplicates.setCursor(Qt.PointingHandCursor)
        self.btn_remove_duplicates.setToolTip(
            "D\u00e9coche les destinataires dont toutes les adresses e-mail s\u00e9lectionn\u00e9es "
            "(principal, deuxi\u00e8me, payeur) sont d\u00e9j\u00e0 couvertes par un autre destinataire,\n"
            "pour \u00e9viter d envoyer plusieurs fois le m\u00eame e-mail \u00e0 la m\u00eame adresse."
        )
        self.btn_remove_duplicates.setStyleSheet(self.QSS_BTN_SECONDARY)
        self.btn_remove_duplicates.clicked.connect(self.remove_duplicate_recipients)
        adv_layout.addWidget(self.btn_remove_duplicates)
        self.advanced_widget.setVisible(False)
        self.btn_advanced.toggled.connect(self.advanced_widget.setVisible)
        opt_layout.addWidget(self.advanced_widget)
        form_layout.addWidget(options_card)

        # Barre d action en bas du formulaire
        self.action_bar = QFrame()
        self.action_bar.setStyleSheet(self.QSS_BAR)
        action_layout = QHBoxLayout(self.action_bar)
        action_layout.setContentsMargins(14, 10, 14, 10)
        action_layout.setSpacing(10)
        self.action_count_lbl = QLabel("0 destinataire")
        self.action_count_lbl.setStyleSheet("color: #1E293B; font-size: 13px; font-weight: bold; background: transparent;")
        action_layout.addWidget(self.action_count_lbl)
        self.action_ready_lbl = QLabel("Aucun destinataire s\u00e9lectionn\u00e9")
        self.action_ready_lbl.setStyleSheet("color: #94A3B8; font-size: 12px; font-weight: 500; background: transparent;")
        action_layout.addWidget(self.action_ready_lbl)
        action_layout.addStretch()

        self.btn_view_html = QPushButton("\U0001F441 Voir le code HTML du mail")
        self.btn_view_html.setCursor(Qt.PointingHandCursor)
        self.btn_view_html.setStyleSheet(self.QSS_BTN_SECONDARY)
        self.btn_view_html.clicked.connect(self.on_view_html_clicked)
        action_layout.addWidget(self.btn_view_html)

        self.btn_preview_email = QPushButton("\U0001F441 Aper\u00e7u complet")
        self.btn_preview_email.setCursor(Qt.PointingHandCursor)
        self.btn_preview_email.setStyleSheet(self.QSS_BTN_SECONDARY)
        self.btn_preview_email.clicked.connect(self.on_preview_email_clicked)
        action_layout.addWidget(self.btn_preview_email)

        self.send_btn = QPushButton("\u2709  Envoyer \u00e0 0 personne(s)")
        self.send_btn.setCursor(Qt.PointingHandCursor)
        self.send_btn.setStyleSheet(self.QSS_BTN_PRIMARY)
        self.send_btn.clicked.connect(self.start_email_campaign)
        action_layout.addWidget(self.send_btn)
        form_layout.addWidget(self.action_bar)
        # Zone de formulaire defilable (presentation conservee)
        form_widget.setMinimumWidth(480)
        self.form_scroll = QScrollArea()
        self.form_scroll.setWidgetResizable(True)
        self.form_scroll.setFrameShape(QFrame.NoFrame)
        self.form_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.form_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.form_scroll.setStyleSheet("""
            QScrollArea {
                background-color: transparent;
                border: none;
            }
            QScrollArea > QWidget {
                background-color: transparent;
            }
            QScrollBar:vertical {
                background: #F1F5F9;
                width: 10px;
                border-radius: 5px;
                margin: 0;
            }
            QScrollBar::handle:vertical {
                background: #CBD5E1;
                border-radius: 5px;
                min-height: 30px;
            }
            QScrollBar::handle:vertical:hover {
                background: #94A3B8;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QScrollBar:horizontal {
                background: #F1F5F9;
                height: 10px;
                border-radius: 5px;
                margin: 0;
            }
            QScrollBar::handle:horizontal {
                background: #CBD5E1;
                border-radius: 5px;
                min-width: 30px;
            }
            QScrollBar::handle:horizontal:hover {
                background: #94A3B8;
            }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                width: 0px;
            }
        """)
        self.form_scroll.setWidget(form_widget)
        right_layout.addWidget(self.form_scroll, 1)
        self.splitter.addWidget(right_container)

        # Ratios d expansion : la colonne Message un peu plus large
        self.splitter.setStretchFactor(0, 2)
        self.splitter.setStretchFactor(1, 3)
        layout.addWidget(self.splitter, 1)

        # 4. JOURNAL DES ENVOIS (repliable, compact)
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
                max-height: 18px;
            }
            QProgressBar::chunk {
                background-color: #3B82F6;
                border-radius: 5px;
            }
        """)
        self.progress_bar.setVisible(False)

        self.log_toggle_btn = QPushButton("\u25b8  Journal des envois")
        self.log_toggle_btn.setCheckable(True)
        self.log_toggle_btn.setCursor(Qt.PointingHandCursor)
        self.log_toggle_btn.setStyleSheet("""
            QPushButton {
                background-color: #FFFFFF; color: #334155; border: 1px solid #CBD5E1;
                border-radius: 6px; padding: 7px 12px; font-size: 12px; font-weight: 600;
                text-align: left;
            }
            QPushButton:hover { background-color: #F8FAFC; border-color: #94A3B8; }
            QPushButton:checked { background-color: #F1F5F9; }
        """)
        self.log_container = QWidget()
        log_layout = QVBoxLayout(self.log_container)
        log_layout.setContentsMargins(0, 0, 0, 0)
        log_layout.setSpacing(6)
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setMinimumHeight(120)
        self.log_area.setPlaceholderText("Les comptes-rendus d envois SMTP / Gmail REST s afficheront ici...")
        self.log_area.setStyleSheet("""
            QTextEdit {
                background-color: #1E293B;
                color: #A7F3D0;
                font-family: Consolas, Courier New, monospace;
                font-size: 12px;
                border-radius: 8px;
                padding: 10px;
            }
        """)
        log_layout.addWidget(self.log_area)
        self.log_container.setVisible(False)
        self.log_toggle_btn.toggled.connect(self.log_container.setVisible)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.log_toggle_btn)
        layout.addWidget(self.log_container)

        # Initialiser la liste des adresses d expedition disponibles
        self.init_sender_combo()

        # Charger les templates d email initiaux
        self.load_email_templates()

    def _vsep(self):
        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setStyleSheet("color: #BFDBFE; max-height: 22px;")
        return sep

    def show_all_recipients(self):
        """Efface la recherche pour reafficher tous les destinataires (presentation)."""
        self.search_input.clear()

    def show_variables_hint(self):
        """Rappel des variables personnalisees utilisees par le mecanisme d envoi existant."""
        QMessageBox.information(
            self,
            "Variables disponibles",
            "Variables remplacees pour chaque destinataire lors de l envoi :\n\n"
            "- {Pr\u00e9nom} ou {first_name} : prenom de l adherent\n"
            "- {Nom} ou {last_name} : nom de l adherent\n"
            "- {num_licence} : numero de licence FFME de l adherent\n\n"
            "Variables disponibles lorsqu un filtre Compet est actif (onglet Competitions) :\n\n"
            "- {no_competition} : identifiant FFME de la competition selectionnee\n"
            "- {name_competition} : nom de la competition selectionnee\n"
            "- {montant_competition} : tarif d inscription de la competition\n\n"
            "Variables du texte d invitation WhatsApp (lorsque l invitation est jointe) :\n\n"
            "- {group_name} : nom du groupe de creneau\n"
            "- {whatsapp_link} : lien d invitation WhatsApp du creneau"
        )

    def _wrap_body_tag(self, tag: str):
        """Entoure la sélection (ou insère une paire vide) avec la balise <tag>…</tag>.

        Le corps reste du texte brut : les balises saisies (<b>, <i>, <u>, <a href>…)
        sont rendues à l'envoi par text_to_html (email_html.py).
        """
        cursor = self.body_input.textCursor()
        open_tag, close_tag = f"<{tag}>", f"</{tag}>"
        if cursor.hasSelection():
            selected = cursor.selectedText()
            cursor.insertText(f"{open_tag}{selected}{close_tag}")
        else:
            cursor.insertText(f"{open_tag}{close_tag}")
            cursor.movePosition(QTextCursor.MoveOperation.Left, QTextCursor.MoveMode.MoveAnchor,
                                len(close_tag))
            self.body_input.setTextCursor(cursor)
        self.body_input.setFocus()

    def _insert_body_link(self):
        """Insère un lien cliquable <a href="…">…</a> vers un site externe.

        Le texte du lien = la sélection courante si elle existe, sinon l'URL saisie.
        """
        cursor = self.body_input.textCursor()
        selected = cursor.selectedText().strip()
        url, ok = QInputDialog.getText(
            self, "🔗 Lien vers un site externe",
            "Adresse du lien (https://… ou mailto:) :",
            text="https://"
        )
        if not ok:
            return
        url = url.strip()
        if not url:
            QMessageBox.warning(self, "Lien vide", "Veuillez saisir une adresse (ex. https://www.exemple.fr).")
            return
        if not url.lower().startswith(("http://", "https://", "mailto:")):
            url = "https://" + url
        link_text = selected or url
        cursor.insertText(f'<a href="{url}">{link_text}</a>')
        self.body_input.setFocus()

    def reset_filters(self):
        """Remet tous les filtres de destinataires a zero (reutilise les mecanismes existants)."""
        self.search_input.clear()
        self.season_filter.blockSignals(True)
        self.season_filter.setCurrentIndex(0)
        self.season_filter.blockSignals(False)
        self.sent_filter.blockSignals(True)
        self.sent_filter.setCurrentIndex(0)
        self.sent_filter.blockSignals(False)
        self.date_checkbox.blockSignals(True)
        self.date_checkbox.setChecked(False)
        self.date_checkbox.blockSignals(False)
        self.health_filter_checkbox.blockSignals(True)
        self.health_filter_checkbox.setChecked(False)
        self.health_filter_checkbox.blockSignals(False)
        self.diploma_filter_checkbox.blockSignals(True)
        self.diploma_filter_checkbox.setChecked(False)
        self.diploma_filter_checkbox.blockSignals(False)
        self.competition_filter.blockSignals(True)
        self.competition_filter.setCurrentIndex(0)
        self.competition_filter.blockSignals(False)
        self.competition_paiement_filter.blockSignals(True)
        self.competition_paiement_filter.setCurrentIndex(0)
        self.competition_paiement_filter.setEnabled(False)
        self.competition_paiement_filter.blockSignals(False)
        self._competition_map_cache = None
        self.selected_tarifs = build_default_tarif_selection(self.members_list)
        self.selected_statuses = set(build_status_list(self.members_list)) - {CANCELLED_STATUS}
        self.update_tarif_button()
        self.update_status_button()
        self.on_filters_changed()
    def get_saved_sender_emails(self) -> list:
        """Retourne la liste des adresses d'expédition mémorisées en BDD."""
        raw = SqliteRepository.get_app_setting("sender_emails", "") or ""
        try:
            items = json.loads(raw)
            if not isinstance(items, list):
                items = []
        except Exception:
            items = [e.strip() for e in raw.split(",") if e.strip()]
        return [str(e).strip() for e in items if str(e).strip() and "@" in str(e)]

    def init_sender_combo(self):
        """Pré-remplit la liste déroulante des adresses d'expédition :
        adresse par défaut du club + adresses mémorisées + dernière adresse utilisée."""
        default_saved = (SqliteRepository.get_app_setting("default_sender_email", "") or "").strip()
        first = default_saved or DEFAULT_SENDER_EMAIL

        emails = [first]
        for em in [DEFAULT_SENDER_EMAIL] + self.get_saved_sender_emails():
            if em.lower() not in [x.lower() for x in emails]:
                emails.append(em)

        self.sender_email_combo.blockSignals(True)
        self.sender_email_combo.clear()
        self.sender_email_combo.addItems(emails)
        self.sender_email_combo.setCurrentText(first)
        self.sender_email_combo.blockSignals(False)

        # Nom d'affichage de l'expédition mémorisé (Nouveau !)
        saved_name = (SqliteRepository.get_app_setting("default_sender_name", "") or "").strip()
        self.sender_name_input.setText(saved_name or DEFAULT_SENDER_NAME)

    def remember_sender_email(self, email: str, name: str = None):
        """Mémorise une adresse d'expédition : ajout à la liste déroulante + définition par défaut."""
        email = (email or "").strip()
        if not email or "@" not in email:
            return
        saved = self.get_saved_sender_emails()
        if email.lower() not in [x.lower() for x in saved]:
            saved.append(email)
            SqliteRepository.save_app_setting("sender_emails", json.dumps(saved, ensure_ascii=False))
        SqliteRepository.save_app_setting("default_sender_email", email)
        if name is not None:
            SqliteRepository.save_app_setting("default_sender_name", (name or "").strip() or DEFAULT_SENDER_NAME)

    def get_current_sender_email(self) -> str:
        """Retourne l'adresse d'expédition courante (saisie ou sélectionnée dans l'IHM)."""
        return self.sender_email_combo.currentText().strip()

    def get_current_sender_name(self) -> str:
        """Retourne le nom d'affichage de l'expéditeur courant (saisi dans l'IHM)."""
        return self.sender_name_input.text().strip() or DEFAULT_SENDER_NAME

    def on_save_sender_clicked(self):
        """Enregistre l'adresse et le nom d'affichage courants comme expéditeur par défaut."""
        email = self.get_current_sender_email()
        if not email or "@" not in email:
            QMessageBox.warning(
                self, "Adresse invalide",
                "Veuillez saisir une adresse e-mail d'expédition valide (contenant un '@')."
            )
            return
        name = self.get_current_sender_name()
        self.remember_sender_email(email, name)
        self.init_sender_combo()
        self.log_area.append(f"💾 [EXPÉDITION] Expéditeur par défaut enregistré : {name} <{email}>")
        QMessageBox.information(
            self, "Expéditeur enregistré",
            f"L'expéditeur par défaut a été enregistré :\n\n{name} <{email}>\n\n"
            "Il sera proposé automatiquement à chaque ouverture de l'onglet Communication."
        )

    def on_season_changed(self):
        """Déclenché lorsque l'utilisateur change de saison dans la liste déroulante."""
        self.load_members(members_list=None)

    def _build_tarif_group_labels(self) -> dict:
        """Associe chaque tarif HelloAsso au nom du groupe issu du planning de la
        BDD, pour afficher le groupe de la personne entre parenthèses dans la
        liste des destinataires."""
        try:
            from infrastructure.sqlite_repository import SqliteRepository
            creneaux = SqliteRepository.load_creneaux_groups()
        except Exception:
            return {}
        labels = {}
        for c in creneaux:
            g_name = c["groupe"]
            for t in c["tarifs"]:
                labels.setdefault(str(t).strip(), g_name)
        return labels

    def load_members(self, members_list=None):
        """Récupère la liste des d'adhérents et peuple le widget de liste avec des cases à cocher (compatible multi-saisons)."""
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
                self.send_btn.setEnabled(False)
                return

        try:
            # Bloquer les signaux temporairement pour éviter des surcoûts d'évaluation
            self.list_widget.blockSignals(True)
            self.list_widget.clear()

            tarif_group_labels = self._build_tarif_group_labels()
            for m in self.members_list:
                email_dest = m.primary_email or m.payer_email
                if email_dest:
                    group_lbl = tarif_group_labels.get(m.tarif_name, "")
                    item_text = f"{m.user_last_name} {m.user_first_name} <{email_dest}>"
                    if group_lbl:
                        item_text += f" ({group_lbl})"
                    item = QListWidgetItem(item_text)
                    item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                    item.setCheckState(Qt.Unchecked) # Décoché par défaut
                    item.setData(Qt.UserRole, m) # Stocker le membre complet
                    self.list_widget.addItem(item)
                    self._decorate_recipient_item(item, m, email_dest, group_lbl)
            
            # Réinitialiser les sélections des pop-up tarifs / statuts :
            # - Tarifs : tout sauf la liste d'attente (comme l'onglet Adhérents)
            # - Statuts : tous sauf "Annulé" (pas d'e-mail aux inscriptions annulées)
            self.selected_tarifs = build_default_tarif_selection(self.members_list)
            self.selected_statuses = set(build_status_list(self.members_list)) - {CANCELLED_STATUS}
            self.update_tarif_button()
            self.update_status_button()

            self.list_widget.blockSignals(False)
            self.update_selection_count()
            
        except Exception as e:
            self.dest_title.setText(f"❌ Erreur lors du chargement : {e}")
            self.send_btn.setEnabled(False)

    def _decorate_recipient_item(self, item, m, email_dest, group_label):
        """Habille un destinataire d une ligne riche (nom, e-mail, creneau, badge)
        tout en conservant le comportement natif de l item (case, donnees, filtres)."""
        widget = QWidget()
        row = QHBoxLayout(widget)
        row.setContentsMargins(4, 3, 6, 3)
        row.setSpacing(8)
        col = QVBoxLayout()
        col.setSpacing(1)
        lbl_name = QLabel(f"{m.user_last_name} {m.user_first_name}")
        lbl_name.setStyleSheet("font-size: 14px; font-weight: bold; color: #1E293B; background: transparent;")
        lbl_meta = QLabel("  \u00b7  ".join(x for x in [email_dest, group_label] if x))
        lbl_meta.setStyleSheet("font-size: 12px; color: #64748B; background: transparent;")
        col.addWidget(lbl_name)
        col.addWidget(lbl_meta)
        row.addLayout(col, 1)
        # Masquer le texte natif de l item (dessine derriere le widget transparent)
        # tout en le conservant pour les journaux et la liste des envois reussis.
        item.setForeground(QColor(0, 0, 0, 0))
        badge_text, badge_qss = self._category_badge(m.tarif_name)
        if badge_text:
            lbl_badge = QLabel(badge_text)
            lbl_badge.setStyleSheet(badge_qss)
            row.addWidget(lbl_badge, 0, Qt.AlignTop)
        # Les labels enfants laissent passer la souris ; le conteneur capte le clic
        # (n importe ou sur la ligne) et inverse la case via eventFilter.
        widget.setCursor(Qt.PointingHandCursor)
        widget.installEventFilter(self)
        for child in widget.findChildren(QWidget):
            child.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        item.setSizeHint(QSize(0, widget.sizeHint().height() + 6))
        self.list_widget.setItemWidget(item, widget)

    def eventFilter(self, obj, event):
        """Clic n importe ou sur une ligne de destinataire : inverse sa case a cocher."""
        if event.type() == QEvent.MouseButtonRelease and obj.parent() is self.list_widget.viewport():
            for i in range(self.list_widget.count()):
                it = self.list_widget.item(i)
                if self.list_widget.itemWidget(it) is obj:
                    it.setCheckState(Qt.Unchecked if it.checkState() == Qt.Checked else Qt.Checked)
                    return True
        return super().eventFilter(obj, event)

    def _category_badge(self, tarif_name: str):
        """Pastille de categorie (presentation) derivee du libelle du tarif."""
        t = str(tarif_name or "").lower()
        badge_qss = "QLabel { background-color: %bg%; color: %fg%; border-radius: 8px; padding: 2px 8px; font-size: 12px; font-weight: bold; }"
        if "autonome" in t:
            return "Autonome", badge_qss.replace("%bg%", "#EFF6FF").replace("%fg%", "#1D4ED8")
        if "perfectionnement" in t:
            return "Perf.", badge_qss.replace("%bg%", "#EDE9FE").replace("%fg%", "#6D28D9")
        if "compétition" in t:
            return "Compét.", badge_qss.replace("%bg%", "#FEF3C7").replace("%fg%", "#B45309")
        if "lycée" in t or "collège" in t or "enfants" in t or "cours" in t:
            return "Loisir", badge_qss.replace("%bg%", "#ECFDF5").replace("%fg%", "#047857")
        return "", ""

    def _update_select_all_label(self):
        """Presentational : affiche le nombre de destinataires visibles dans le bouton Tout selectionner."""
        visible = sum(
            1 for i in range(self.list_widget.count())
            if not self.list_widget.item(i).isHidden()
        )
        self.btn_select_all.setText(f"☑  Tout sélectionner ({visible})")

    def on_search_changed(self, text: str):
        """Filtrage textuel à la volée."""
        self.on_filters_changed()

    # ------------------------------------------------------------------
    # Filtre de destination « Compétition » (Nouveau !)
    # ------------------------------------------------------------------
    def load_competition_filters(self):
        """Peuple la liste déroulante des compétitions depuis database_Competition.db."""
        self.competition_filter.blockSignals(True)
        self.competition_filter.clear()
        self.competition_filter.addItem("(Aucun filtre compétition)", 0)
        try:
            for comp in CompetitionRepository.list_competitions():
                date_txt = comp.date_competition[:10] if comp.date_competition else "sans date"
                self.competition_filter.addItem(f"🏆 {comp.nom} ({date_txt})", comp.id)
        except Exception as e:
            print(f"⚠️ [COMMUNICATION] Chargement des compétitions impossible : {e}")
        self.competition_filter.blockSignals(False)

    def _selected_competition_id(self) -> int:
        return self.competition_filter.currentData() or 0

    def _competition_participants_map(self, competition_id: int) -> dict:
        """Index des participants d'une compétition, par n° de licence puis par nom
        normalisé (clés « L:123456 » / « N:dupont jean »), avec cache invalidé à chaque
        changement de compétition."""
        cache = getattr(self, "_competition_map_cache", None)
        if cache and cache.get("competition_id") == competition_id:
            return cache["map"]
        mapping = {}
        try:
            for p in CompetitionRepository.list_participants(competition_id, selected_only=False):
                entry = {
                    "selectionne": p.selectionne,
                    "statut_paiement": p.statut_paiement,
                    "num_licence": p.num_licence,
                }
                lic = "".join(ch for ch in str(p.num_licence or "") if ch.isdigit())
                if lic:
                    mapping[f"L:{lic}"] = entry
                nkey = normalize_name(f"{p.nom} {p.prenom}")
                if nkey:
                    mapping.setdefault(f"N:{nkey}", entry)
        except Exception as e:
            print(f"⚠️ [COMMUNICATION] Lecture des participants impossible : {e}")
        self._competition_map_cache = {"competition_id": competition_id, "map": mapping}
        return mapping

    def _member_competition_entry(self, member, mapping: dict):
        """Retrouve l'entrée participant d'un adhérent : par licence (prioritaire)
        puis par nom normalisé (fallback pour les non licenciés)."""
        lic = "".join(ch for ch in str(getattr(member, "licence_ffme", "") or "") if ch.isdigit())
        if lic and f"L:{lic}" in mapping:
            return mapping[f"L:{lic}"]
        nkey = normalize_name(f"{member.user_last_name} {member.user_first_name}")
        return mapping.get(f"N:{nkey}")

    def on_competition_filter_changed(self):
        """Active/désactive le filtre de paiement et invalide le cache participants."""
        self._competition_map_cache = None
        self.competition_paiement_filter.setEnabled(self._selected_competition_id() > 0)
        self.on_filters_changed()

    def apply_competition_filter(self, competition_id: int, competition_name: str = ""):
        """Ouverture depuis la page Compétitions (bouton ✉️) : recharge la liste des
        épreuves, sélectionne la compétition demandée et coche ses compétiteurs."""
        self.load_competition_filters()
        index = self.competition_filter.findData(int(competition_id))
        if index < 0:
            QMessageBox.warning(
                self, "Compétition introuvable",
                f"L'épreuve « {competition_name or competition_id} » n'existe plus dans la base des compétitions."
            )
            return
        self.competition_filter.setCurrentIndex(index)  # déclenche on_filters_changed
        # Pré-cocher les compétiteurs sélectionnés de l'épreuve (invitation / relance)
        mapping = self._competition_participants_map(int(competition_id))
        checked = 0
        self.list_widget.blockSignals(True)
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            m = item.data(Qt.UserRole)
            entry = self._member_competition_entry(m, mapping)
            if entry and entry["selectionne"]:
                item.setCheckState(Qt.Checked)
                item.setHidden(False)
                checked += 1
        self.list_widget.blockSignals(False)
        self.update_selection_count()
        self.log_area.append(
            f"🏆 [COMPÉTITION] Filtre actif : {competition_name or competition_id} — "
            f"{checked} compétiteur(s) pré-coché(s)."
        )

    def _current_competition_context(self):
        """Contexte de variables dynamiques du filtre compétition actif :
        {no_competition}, {name_competition}, {montant_competition}."""
        comp_id = self._selected_competition_id()
        if not comp_id:
            return None
        try:
            comp = CompetitionRepository.get_competition(comp_id)
        except Exception:
            comp = None
        if not comp:
            return None
        from domain.utils import format_montant
        return {
            "competition_id": comp.id,
            "nom": comp.nom,
            "no_competition": comp.id_ffme,
            "name_competition": comp.nom,
            "montant_competition": format_montant(comp.prix),
        }

    def focus_on_member(self, member):
        """Préfiltre la liste des destinataires sur l'adhérent choisi dans l'onglet
        Adhérents (bouton ✉️ de la fiche) : la recherche est remplie avec son nom."""
        # S'assurer que la liste des destinataires est chargée (accès direct)
        if not self.members_list:
            self.load_members()
        last_name = str(getattr(member, "user_last_name", "") or "").strip()
        # La recherche compare le texte saisi à chaque champ (nom OU prénom) :
        # on filtre donc sur le nom de famille uniquement pour retrouver la personne.
        self.search_input.setText(last_name)
        self.on_filters_changed()

    def on_filters_changed(self):
        """Filtre l'affichage de la liste des destinataires en combinant la recherche,
        les tarifs (pop-up), les statuts (pop-up), l'état d'envoi et la date d'inscription."""
        search_text = self.search_input.text().strip().lower()
        sent_sel = self.sent_filter.currentText()

        # Filtre de date d'inscription (comparaison de DATES sans heure/fuseau)
        filter_date = None
        if self.date_checkbox.isChecked():
            filter_qdate = self.date_edit.date()
            filter_date = datetime.date(filter_qdate.year(), filter_qdate.month(), filter_qdate.day())

        self.list_widget.blockSignals(True)
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            m = item.data(Qt.UserRole)
            
            # 1. Recherche textuelle
            match_search = (
                not search_text or
                search_text in m.user_last_name.lower() or
                search_text in m.user_first_name.lower() or
                search_text in (m.primary_email or m.payer_email).lower()
            )
            
            # 2. Filtre de tarifs (sélection multi via la pop-up ; vide = tous)
            match_tarif = (
                not self.selected_tarifs
                or m.tarif_name in self.selected_tarifs
            )

            # 3. Filtre de statuts (sélection multi via la pop-up ; comparaison sur
            #    statut normalisé, "Annulé" décoché par défaut)
            match_status = (
                not self.selected_statuses
                or normalize_status(m.status) in self.selected_statuses
            )

            # 3b. Filtre Santé (Nouveau !) : Document de santé FFME « ATTENTE » uniquement
            match_health = (
                not self.health_filter_checkbox.isChecked()
                or str(getattr(m, "document_sante", "") or "").strip().upper() == "ATTENTE"
            )

            # 3c. Filtre Sans diplôme (Nouveau !) : ni Badge Rouge ni Passeport Orange
            match_diploma = True
            if self.diploma_filter_checkbox.isChecked():
                has_badge = str(getattr(m, "badge_rouge", "") or "").strip() == "Oui"
                has_orange = "orange" in str(getattr(m, "raw_passports", "") or "").lower()
                match_diploma = not (has_badge or has_orange)

            # 4. Filtre d'envoi
            is_sent = bool(m.email_sent_date)
            match_sent = True
            if sent_sel == "Envoyés" and not is_sent:
                match_sent = False
            elif sent_sel == "Non envoyés" and is_sent:
                match_sent = False

            # 5. Filtre de date d'inscription (inscrit après la date choisie)
            match_date = True
            if filter_date is not None:
                m_date = parse_order_date(m.order_date)
                match_date = m_date is not None and m_date >= filter_date

            # 6. Filtre « Compétition » (Nouveau !) : participants de l'épreuve choisie,
            #    éventuellement restreints à un statut de paiement (relances « en attente »).
            match_competition = True
            comp_id = self._selected_competition_id()
            if comp_id:
                mapping = self._competition_participants_map(comp_id)
                entry = self._member_competition_entry(m, mapping)
                match_competition = bool(entry and entry["selectionne"])
                if match_competition:
                    sel_lib = self.competition_paiement_filter.currentText()
                    wanted = LIBELLE_VERS_STATUT_PAIEMENT.get(sel_lib)
                    if wanted and wanted != PAIEMENT_NON_INVITE:
                        match_competition = entry["statut_paiement"] == wanted

            # Masquer l'item s'il ne valide pas les critères
            item.setHidden(not (match_search and match_tarif and match_status and match_health
                                and match_diploma and match_sent and match_date
                                and match_competition))
            
        self.list_widget.blockSignals(False)
        self.update_selection_count()
        self._update_select_all_label()

    def select_visible(self):
        """Coche uniquement les destinataires visibles (ceux qui passent le filtre actif)."""
        self.list_widget.blockSignals(True)
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if not item.isHidden():
                item.setCheckState(Qt.Checked)
        self.list_widget.blockSignals(False)
        self.update_selection_count()

    def deselect_visible(self):
        """Décoche uniquement les destinataires visibles (ceux qui passent le filtre actif)."""
        self.list_widget.blockSignals(True)
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if not item.isHidden():
                item.setCheckState(Qt.Unchecked)
        self.list_widget.blockSignals(False)
        self.update_selection_count()

    def deselect_all_members(self):
        """Décoche TOUS les destinataires, y compris ceux masqués par les filtres actifs."""
        self.list_widget.blockSignals(True)
        for i in range(self.list_widget.count()):
            self.list_widget.item(i).setCheckState(Qt.Unchecked)
        self.list_widget.blockSignals(False)
        self.update_selection_count()

    def _resolved_emails_for_member(self, member) -> list:
        """Adresses e-mail valides d'un membre selon les cases « Choix des adresses »
        cochées (principal / deuxième / payeur), sans doublon et insensibles à la casse."""
        candidates = []
        if self.use_primary_email_cb.isChecked() and member.primary_email:
            candidates.append(str(member.primary_email).strip())
        if self.use_secondary_email_cb.isChecked() and member.secondary_email:
            candidates.append(str(member.secondary_email).strip())
        if self.use_payer_email_cb.isChecked() and member.payer_email:
            candidates.append(str(member.payer_email).strip())
        emails = []
        for em in candidates:
            if em and "@" in em and em.lower() not in [x.lower() for x in emails]:
                emails.append(em)
        return emails

    def remove_duplicate_recipients(self):
        """Décoche les destinataires dont toutes les adresses e-mail (selon les cases
        « Choix des adresses de destination ») sont déjà couvertes par un autre
        destinataire déjà sélectionné, afin d'éviter les envois en double."""
        seen = set()  # adresses e-mail normalisées (minuscules) déjà couvertes
        removed = []
        self.list_widget.blockSignals(True)
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.checkState() != Qt.Checked:
                continue
            member = item.data(Qt.UserRole)
            emails = self._resolved_emails_for_member(member)
            if not emails:
                # Aucune adresse valide selon les critères : sera ignoré à l'envoi,
                # on ne le compte donc ni comme doublon ni comme couverture.
                continue
            if all(em.lower() in seen for em in emails):
                item.setCheckState(Qt.Unchecked)
                removed.append(item.text())
            else:
                for em in emails:
                    seen.add(em.lower())
        self.list_widget.blockSignals(False)

        if removed:
            self.update_selection_count()
            detail = "\n".join(f"• {name}" for name in removed[:15])
            if len(removed) > 15:
                detail += f"\n• … et {len(removed) - 15} autre(s)"
            QMessageBox.information(
                self,
                "Doublons supprimés",
                f"{len(removed)} destinataire(s) décoché(s) car toutes leurs adresses "
                f"e-mail sélectionnées étaient déjà couvertes par un autre destinataire :\n\n{detail}"
            )
        else:
            QMessageBox.information(
                self,
                "Aucun doublon",
                "Aucun doublon détecté : chaque destinataire sélectionné apporte "
                "au moins une adresse e-mail unique."
            )

    def update_selection_count(self):
        """Calcule et affiche le nombre de destinataires sélectionnés, alerte sur les
        cochés masqués par les filtres, et resynchronise l'encart « Personnes sélectionnées »."""
        checked_count = 0
        hidden_checked = 0
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.checkState() == Qt.Checked:
                checked_count += 1
                if item.isHidden():
                    hidden_checked += 1

        suffix = f"  ·  ⚠ {hidden_checked} masqué(s) par le filtre" if hidden_checked else ""
        self.dest_title.setText(f"{checked_count} sélectionnés{suffix}")
        self.footer_lbl.setText(f"👥 {checked_count} destinataire(s) sélectionné(s)")
        self.action_count_lbl.setText(f"{checked_count} destinataire(s)")
        self.action_ready_lbl.setText("✓ Message complet" if checked_count else "Aucun destinataire sélectionné")
        self.action_ready_lbl.setStyleSheet(
            "color: #16A34A; font-size: 12px; font-weight: 500; background: transparent;"
            if checked_count else
            "color: #94A3B8; font-size: 12px; font-weight: 500; background: transparent;"
        )
        self.wf_step1_lbl.setText(f"{checked_count} sélectionné(s)")
        self.wf_step3_lbl.setText("Prêt à envoyer" if checked_count else "Aucun destinataire")
        self.send_btn.setEnabled(checked_count > 0)
        self.send_btn.setText(f"✉  Envoyer à {checked_count} personne(s)")
        self.refresh_selected_panel()

    # ------------------------------------------------------------------
    # Encart « Personnes sélectionnées » (Nouveau !)
    # ------------------------------------------------------------------
    def _count_checked(self) -> int:
        """Nombre de destinataires cochés dans la liste principale."""
        return sum(
            1 for i in range(self.list_widget.count())
            if self.list_widget.item(i).checkState() == Qt.Checked
        )

    def toggle_selected_panel(self):
        """Affiche / masque l'encart listant les destinataires cochés."""
        self._selected_panel_open = not self._selected_panel_open
        self.selected_panel.setVisible(self._selected_panel_open)
        self.refresh_selected_panel()

    def refresh_selected_panel(self):
        """Resynchronise l'encart avec les destinataires cochés — y compris ceux
        masqués par les filtres (recherche, tarifs, statuts...) — pour ne pas les oublier."""
        count = self._count_checked()
        arrow = "▾" if getattr(self, "_selected_panel_open", False) else "▸"
        self.selected_panel_btn.setText(f"✅ Personnes sélectionnées ({count}) {arrow}")

        self.selected_panel.clear()
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.checkState() == Qt.Checked:
                self.selected_panel.addItem(QListWidgetItem(item.text()))

    def start_email_campaign(self):
        """Démarre l'envoi de masse asynchrone pour les seuls adhérents sélectionnés."""
        # Récupérer uniquement les membres cochés
        selected_members = []
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.checkState() == Qt.Checked:
                selected_members.append(item.data(Qt.UserRole))

        count = len(selected_members)
        if count == 0:
            return

        # Boîte de dialogue de confirmation de sécurité avant envoi
        from PySide6.QtWidgets import QMessageBox
        reply = QMessageBox.question(
            self, 
            "Confirmation d'envoi", 
            f"Vous êtes sur le point de lancer l'expédition de courriels d'attestations.\n\n"
            f"Voulez-vous envoyer cet e-mail aux {count} adhérent(s) sélectionné(s) ?",
            QMessageBox.Yes | QMessageBox.No, 
            QMessageBox.No
        )
        
        if reply == QMessageBox.No:
            return

        self.send_btn.setEnabled(False)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)
        self.log_area.clear()
        # Presentational : ouvre le journal repliable pour suivre l envoi
        self.log_toggle_btn.setChecked(True)
        self.log_container.setVisible(True)

        subject = self.subject_input.text().strip()
        body = self.body_input.toPlainText()

        self.log_area.append(f"ℹ️ [INFO] Lancement de la campagne d'envoi pour {len(selected_members)} destinataires...")
        self.log_area.append(f"📤 [EXPÉDITION] Expéditeur utilisé : {self.get_current_sender_name()} <{self.get_current_sender_email() or DEFAULT_SENDER_EMAIL}>")
        
        self.worker = SendEmailCampaignWorker(
            subject=subject,
            body=body,
            members=selected_members,
            attach_pdf=self.attach_pdf_checkbox.isChecked(),
            attach_whatsapp=self.attach_whatsapp_checkbox.isChecked(),
            use_primary_email=self.use_primary_email_cb.isChecked(),
            use_secondary_email=self.use_secondary_email_cb.isChecked(),
            use_payer_email=self.use_payer_email_cb.isChecked(),
            whatsapp_template=self.whatsapp_template_input.toPlainText(), # Nouveau !
            add_signature=self.signature_yes_radio.isChecked(),
            sender_email=self.get_current_sender_email(), # Adresse d'expédition (De) choisie (Nouveau !)
            sender_name=self.get_current_sender_name(),   # Nom d'affichage de l'expéditeur (Nouveau !)
            competition_context=self._current_competition_context()  # Variables {no_competition}… (Nouveau !)
        )
        self.worker.progress.connect(self.on_progress)
        self.worker.finished.connect(self.on_finished)
        # La génération d'attestations PDF s'appuie sur QtWebEngine (Chromium) qui n'est pas
        # thread-safe : délégation au thread principal via une connexion bloquante.
        self.worker.pdf_generation_requested.connect(self.on_pdf_generation_requested, Qt.BlockingQueuedConnection)
        self.worker.start()

    def on_progress(self, message: str, percent: int):
        self.progress_bar.setValue(percent)
        self.log_area.append(message)

    def on_pdf_generation_requested(self, payload):
        """Slot exécuté sur le thread principal (connexion bloquante) : QtWebEngine (Chromium)
        n'est pas thread-safe, toute génération d'attestation PDF doit passer par ici."""
        from presentation.pdf_render_service import get_pdf_render_service
        result = get_pdf_render_service().render_attestations(
            payload.get("participants"),
            output_format=payload.get("output_format", "pdf"),
            test_mode=payload.get("test_mode", False)
        )
        if self.worker is not None:
            self.worker.pdf_result = result

    def on_view_html_clicked(self):
        """Ouvre une fenêtre affichant le code HTML exact du courriel qui sera envoyé."""
        try:
            from email_html import build_email_html
            html_code = build_email_html(
                self.body_input.toPlainText(),
                add_signature=self.signature_yes_radio.isChecked(),
                image_src_mode="preview"
            )
        except Exception as e:
            QMessageBox.critical(self, "Erreur", f"Impossible de générer le code HTML : {e}")
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("👁️ Code HTML du courriel")
        dlg.resize(720, 540)
        dlg_layout = QVBoxLayout(dlg)
        dlg_layout.setContentsMargins(12, 12, 12, 12)

        info_lbl = QLabel(
            "Voici le code HTML tel qu'il sera envoyé (version riche affichée par les messageries). "
            "Les logos sont intégrés automatiquement à l'envoi."
        )
        info_lbl.setWordWrap(True)
        info_lbl.setStyleSheet("color: #475569; font-size: 11px;")
        dlg_layout.addWidget(info_lbl)

        html_view = QTextEdit()
        html_view.setReadOnly(True)
        html_view.setPlainText(html_code)
        html_view.setStyleSheet("""
            QTextEdit {
                background-color: #1E293B;
                color: #A7F3D0;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 12px;
                border-radius: 8px;
                padding: 10px;
            }
        """)
        dlg_layout.addWidget(html_view, 1)

        close_btn = QPushButton("Fermer")
        close_btn.setStyleSheet("""
            QPushButton {
                background-color: #3B82F6;
                color: #FFFFFF;
                border: none;
                border-radius: 6px;
                padding: 6px 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #2563EB;
            }
        """)
        close_btn.clicked.connect(dlg.accept)
        dlg_layout.addWidget(close_btn, 0, Qt.AlignRight)

        dlg.exec()

    def on_preview_email_clicked(self):
        """Ouvre une pop-in montrant l'e-mail rendu avec les informations du premier
        destinataire coché (variables remplacées, bloc WhatsApp et signature selon
        les options cochées — même logique que l'envoi réel)."""
        # 1. Récupérer le premier destinataire coché
        first_member = None
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.checkState() == Qt.Checked:
                first_member = item.data(Qt.UserRole)
                break
        if first_member is None:
            QMessageBox.warning(
                self, "Aucun destinataire",
                "Veuillez d'abord cocher au moins un destinataire pour prévisualiser l'e-mail."
            )
            return

        subject = self.subject_input.text().strip()
        body = self.body_input.toPlainText()

        # 2. Destinataires calculés selon les cases cochées (même logique que l'envoi réel)
        candidates = []
        if self.use_primary_email_cb.isChecked():
            candidates.append(first_member.primary_email)
        if self.use_secondary_email_cb.isChecked():
            candidates.append(first_member.secondary_email)
        if self.use_payer_email_cb.isChecked():
            candidates.append(first_member.payer_email)
        emails = []
        for em in candidates:
            em_strip = str(em or "").strip()
            if em_strip and "@" in em_strip and em_strip.lower() not in [x.lower() for x in emails]:
                emails.append(em_strip)
        to_display = ", ".join(emails) if emails else "⚠️ Aucune adresse valide selon vos critères"

        # 3. Personnalisation des variables (identique à SendEmailCampaignWorker :
        #    {Prénom}/{Nom}/{first_name}/{last_name}, {num_licence} et variables
        #    compétition {no_competition}/{name_competition}/{montant_competition})
        from presentation.workers import apply_template_variables
        competition_context = self._current_competition_context()
        msg_body = apply_template_variables(body, first_member, competition_context)
        subject = apply_template_variables(subject, first_member, competition_context)

        # 4. Pièce jointe attestation + bloc WhatsApp / QRCode (identique à l'envoi réel)
        attachments_lines = []
        if self.attach_pdf_checkbox.isChecked():
            from attestation_generator import get_safe_filename
            filename_pdf = get_safe_filename(
                first_member.user_last_name, first_member.user_first_name, first_member.order_ref
            ).replace(".docx", ".pdf")
            attachments_lines.append(f"📄 Attestation de paiement : {filename_pdf}")

        if self.attach_whatsapp_checkbox.isChecked():
            planning_data = []
            try:
                from infrastructure.sqlite_repository import SqliteRepository
                planning_data = SqliteRepository.load_planning_data()
            except Exception:
                planning_data = []

            found_item = None
            if planning_data and first_member.tarif_name:
                for item in planning_data:
                    linked_tarifs = item.get("helloasso_tarifs", [])
                    if any(str(t).strip().lower() == first_member.tarif_name.strip().lower() for t in linked_tarifs):
                        found_item = item
                        break
                if not found_item:
                    from presence_sheet_generator import find_planning_match_dynamically
                    match_info = find_planning_match_dynamically(first_member.tarif_name, planning_data)
                    if match_info:
                        target_group_name = match_info.get("groupe_planning")
                        for item in planning_data:
                            if str(item.get("groupe")).strip().lower() == str(target_group_name).strip().lower():
                                found_item = item
                                break

            if found_item:
                whatsapp_link = (found_item.get("whatsapp_link") or "").strip()
                group_name = (found_item.get("groupe") or "").strip()
                if whatsapp_link and group_name:
                    template = self.whatsapp_template_input.toPlainText()
                    if not template or not template.strip():
                        template = (
                            "\n\n---\n"
                            "🧗 <b>Créneau : {group_name}</b>\n"
                            "💬 Rejoindre le groupe WhatsApp : {whatsapp_link}\n"
                            "📱 Le QRCode d'invitation est également joint en pièce jointe à cet e-mail."
                        )
                    try:
                        msg_body += template.format(group_name=group_name, whatsapp_link=whatsapp_link)
                    except Exception:
                        msg_body += (
                            f"\n\n---\n"
                            f"🧗 <b>Créneau : {group_name}</b>\n"
                            f"💬 Rejoindre le groupe WhatsApp : {whatsapp_link}\n"
                            f"📱 Le QRCode d'invitation est également joint en pièce jointe à cet e-mail."
                        )
                    attachments_lines.append(f"🟢 QRCode joint avec succès ({group_name})")
                else:
                    group_desc = group_name or first_member.tarif_name
                    attachments_lines.append(f"⚠️ QRCode non joint (Lien WhatsApp absent pour le groupe '{group_desc}')")
            else:
                attachments_lines.append(f"⚠️ QRCode non joint (Aucun cours trouvé pour le tarif '{first_member.tarif_name}')")

        # 5. Rendu HTML (signature selon le bouton radio choisi)
        try:
            from email_html import build_email_html
            html_body = build_email_html(
                msg_body,
                add_signature=self.signature_yes_radio.isChecked(),
                image_src_mode="preview"
            )
        except Exception as e:
            QMessageBox.critical(self, "Erreur", f"Impossible de générer l'aperçu : {e}")
            return

        # 6. Pop-in d'aperçu
        dlg = QDialog(self)
        dlg.setWindowTitle("🔍 Prévisualisation de l'e-mail")
        dlg.resize(760, 640)
        dlg_layout = QVBoxLayout(dlg)
        dlg_layout.setContentsMargins(14, 14, 14, 12)
        dlg_layout.setSpacing(8)

        info_lbl = QLabel(
            f"Aperçu généré avec les informations du premier destinataire coché : "
            f"<b>{first_member.user_last_name.upper()} {first_member.user_first_name}</b>. "
            "Chaque destinataire recevra son e-mail personnalisé de la même façon."
        )
        info_lbl.setWordWrap(True)
        info_lbl.setTextFormat(Qt.TextFormat.RichText)
        info_lbl.setStyleSheet("color: #475569; font-size: 11px;")
        dlg_layout.addWidget(info_lbl)

        header_frame = QFrame()
        header_frame.setStyleSheet("""
            QFrame {
                background-color: #F8FAFC;
                border: 1px solid #E2E8F0;
                border-radius: 6px;
            }
            QLabel { color: #334155; font-size: 12px; }
        """)
        header_layout = QVBoxLayout(header_frame)
        header_layout.setContentsMargins(10, 8, 10, 8)
        header_layout.setSpacing(3)
        to_lbl = QLabel(f"<b>À :</b> {to_display}")
        to_lbl.setTextFormat(Qt.TextFormat.RichText)
        to_lbl.setWordWrap(True)
        from_display = self.get_current_sender_email() or DEFAULT_SENDER_EMAIL
        from_name_display = self.get_current_sender_name()
        from_lbl = QLabel(f"<b>De :</b> {from_name_display} &lt;{from_display}&gt;")
        from_lbl.setTextFormat(Qt.TextFormat.RichText)
        from_lbl.setWordWrap(True)
        subject_lbl = QLabel(f"<b>Objet :</b> {subject or '(vide)'}")
        subject_lbl.setTextFormat(Qt.TextFormat.RichText)
        subject_lbl.setWordWrap(True)
        header_layout.addWidget(to_lbl)
        header_layout.addWidget(from_lbl)
        header_layout.addWidget(subject_lbl)
        dlg_layout.addWidget(header_frame)

        email_view = QTextEdit()
        email_view.setReadOnly(True)
        email_view.setHtml(html_body)
        email_view.setStyleSheet("""
            QTextEdit {
                background-color: #FFFFFF;
                border: 1px solid #E2E8F0;
                border-radius: 8px;
                padding: 14px;
            }
        """)
        dlg_layout.addWidget(email_view, 1)

        if attachments_lines:
            attach_lbl = QLabel("<b>Pièces jointes :</b><br>" + "<br>".join(attachments_lines))
            attach_lbl.setTextFormat(Qt.TextFormat.RichText)
            attach_lbl.setWordWrap(True)
            attach_lbl.setStyleSheet("color: #475569; font-size: 11px;")
            dlg_layout.addWidget(attach_lbl)

        close_btn = QPushButton("Fermer")
        close_btn.setStyleSheet("""
            QPushButton {
                background-color: #3B82F6;
                color: #FFFFFF;
                border: none;
                border-radius: 6px;
                padding: 6px 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #2563EB;
            }
        """)
        close_btn.clicked.connect(dlg.accept)
        dlg_layout.addWidget(close_btn, 0, Qt.AlignRight)

        dlg.exec()

    def on_finished(self, success_count: int, error_count: int):
        self.send_btn.setEnabled(True)
        self.log_area.append("\n==============================================")
        self.log_area.append("🎉 [FIN] Campagne d'envoi de courriels terminée !")
        self.log_area.append(f"✅ Messages envoyés avec succès : {success_count}")
        if error_count > 0:
            self.log_area.append(f"❌ Échecs d'envois : {error_count}")
            self.log_area.append("ℹ️ Consultez 'email_audit.log' à la racine pour examiner les traces d'erreurs.")
        self.log_area.append("==============================================")
        self.update_selection_count()

    def load_email_templates(self):
        """Charge la liste des templates d'emails depuis SQLite et peuple le sélecteur."""
        try:
            self.template_selector.blockSignals(True)
            self.template_selector.clear()
            
            # Récupérer les templates de BDD
            from infrastructure.sqlite_repository import SqliteRepository
            self.email_templates = SqliteRepository.get_email_templates()
            
            # Ajouter au sélecteur
            names = [t["name"] for t in self.email_templates]
            self.template_selector.addItems(names)
            
            self.template_selector.blockSignals(False)
            
            # Sélectionner le premier s'il y en a
            if self.email_templates:
                self.template_selector.setCurrentIndex(0)
                self.on_template_selected(0)
        except Exception as e:
            print(f"⚠️ Erreur lors du préchargement des templates : {e}")

    def on_template_selected(self, index: int):
        """Déclenché lorsque l'utilisateur change de template d'email."""
        if index < 0 or index >= len(self.email_templates):
            return
        tmpl = self.email_templates[index]
        self.subject_input.blockSignals(True)
        self.body_input.blockSignals(True)
        
        self.subject_input.setText(tmpl["subject"])
        self.body_input.setPlainText(tmpl["body"])
        
        self.subject_input.blockSignals(False)
        self.body_input.blockSignals(False)
        
        # Charger l'adresse et le nom d'expédition mémorisés pour ce modèle (Nouveau !)
        # Repli : expéditeur par défaut sauvegardé, puis valeurs du club
        sender = (tmpl.get("sender_email") or "").strip()
        if not sender:
            sender = (SqliteRepository.get_app_setting("default_sender_email", "") or "").strip()
        if not sender:
            sender = DEFAULT_SENDER_EMAIL
        self.sender_email_combo.setCurrentText(sender)

        sender_name = (tmpl.get("sender_name") or "").strip()
        if not sender_name:
            sender_name = (SqliteRepository.get_app_setting("default_sender_name", "") or "").strip()
        if not sender_name:
            sender_name = DEFAULT_SENDER_NAME
        self.sender_name_input.setText(sender_name)
        self.wf_step2_lbl.setText(tmpl.get("name") or "—")

    def on_save_template_clicked(self):
        """Enregistre les modifications apportées au template sélectionné (avec son expéditeur)."""
        current_name = self.template_selector.currentText().strip()
        if not current_name:
            QMessageBox.warning(self, "Pas de modèle", "Veuillez sélectionner ou créer un modèle avant d'enregistrer.")
            return
            
        subject = self.subject_input.text().strip()
        body = self.body_input.toPlainText()

        # Rappel : l'objet est encore celui par défaut d'un nouveau modèle
        if subject.lower() == "sujet du nouveau courriel":
            answer = QMessageBox.question(
                self,
                "Objet par défaut",
                "L'objet du courriel est encore « Sujet du nouveau courriel ».\n\n"
                "Pensez à le personnaliser avant d'enregistrer votre modèle.\n\n"
                "Voulez-vous l'enregistrer quand même ?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if answer != QMessageBox.Yes:
                return

        sender_email = self.get_current_sender_email()
        sender_name = self.get_current_sender_name()
        if not sender_email or "@" not in sender_email:
            QMessageBox.warning(
                self, "Adresse d'expédition invalide",
                "L'adresse d'expédition (De) doit être une adresse e-mail valide (contenant un '@').\n"
                "Exemple : inscription@alj-escalade.fr"
            )
            return
        
        from infrastructure.sqlite_repository import SqliteRepository
        success = SqliteRepository.save_email_template(current_name, subject, body, sender_email=sender_email, sender_name=sender_name)
        if success:
            self.remember_sender_email(sender_email, sender_name)
            self.log_area.append(f"💾 [MODÈLE] Modèle d'e-mail '{current_name}' enregistré avec succès en BDD (expédition : {sender_name} <{sender_email}>).")
            self.load_email_templates()
            self.template_selector.setCurrentText(current_name)
        else:
            QMessageBox.critical(self, "Erreur", f"Impossible d'enregistrer le modèle '{current_name}' en BDD.")

    def on_save_whatsapp_template_clicked(self):
        """Enregistre le texte d'invitation WhatsApp personnalisé en BDD pour les prochains envois."""
        text = self.whatsapp_template_input.toPlainText()
        if not text.strip():
            QMessageBox.warning(self, "Texte vide", "Le texte d'invitation WhatsApp ne peut pas être vide.")
            return
            
        success = SqliteRepository.save_whatsapp_template(text)
        if success:
            self.log_area.append("💾 [WHATSAPP] Texte d'invitation WhatsApp enregistré avec succès en BDD.")
        else:
            QMessageBox.critical(self, "Erreur", "Impossible d'enregistrer le texte d'invitation WhatsApp en BDD.")

    def on_new_template_clicked(self):
        """Demande un nom pour un nouveau template d'email, et l'enregistre."""
        name, ok = QInputDialog.getText(self, "Nouveau Modèle d'E-mail", "Entrez le nom de votre nouveau modèle d'e-mail :")
        if not ok or not name.strip():
            return
            
        name = name.strip()
        subject = "Sujet du nouveau courriel"
        body = "Bonjour {first_name},\n\nSaisissez votre texte ici."
        sender_email = self.get_current_sender_email()
        sender_name = self.get_current_sender_name()
        
        from infrastructure.sqlite_repository import SqliteRepository
        # Vérifier si existe déjà
        templates = SqliteRepository.get_email_templates()
        if any(t["name"].lower() == name.lower() for t in templates):
            QMessageBox.warning(self, "Modèle Existant", f"Un modèle nommé '{name}' existe déjà.")
            return
            
        success = SqliteRepository.save_email_template(name, subject, body, sender_email=sender_email, sender_name=sender_name)
        if success:
            self.remember_sender_email(sender_email, sender_name)
            self.log_area.append(f"➕ [MODÈLE] Nouveau modèle '{name}' créé avec succès (expédition : {sender_name} <{sender_email}>).")
            self.load_email_templates()
            self.template_selector.setCurrentText(name)
        else:
            QMessageBox.critical(self, "Erreur", f"Impossible de créer le modèle '{name}'.")

    def on_delete_template_clicked(self):
        """Supprime le template sélectionné de la BDD."""
        current_name = self.template_selector.currentText().strip()
        if not current_name:
            return
            
        # Demander confirmation
        reply = QMessageBox.question(
            self, 
            "Supprimer le Modèle ?", 
            f"Êtes-vous sûr de vouloir supprimer définitivement le modèle d'e-mail '{current_name}' ?",
            QMessageBox.Yes | QMessageBox.No, 
            QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return
            
        from infrastructure.sqlite_repository import SqliteRepository
        success = SqliteRepository.delete_email_template(current_name)
        if success:
            self.log_area.append(f"🗑️ [MODÈLE] Modèle d'e-mail '{current_name}' supprimé de la BDD.")
            self.load_email_templates()
        else:
            QMessageBox.critical(self, "Erreur", f"Impossible de supprimer le modèle '{current_name}'.")
