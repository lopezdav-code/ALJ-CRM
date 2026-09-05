import os
import datetime
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
    QLineEdit, QTextEdit, QProgressBar, QFrame, QListWidget, 
    QListWidgetItem, QSplitter, QComboBox, QCheckBox, QMessageBox,
    QRadioButton, QDialog, QGroupBox, QDateEdit
)
from PySide6.QtCore import Qt, QDate
from PIL import Image, ImageDraw

from paths import CODE_ROOT
from domain.models import Member
from infrastructure.sqlite_repository import SqliteRepository
from infrastructure.schema_v2 import normalize_status
from presentation.workers import SendEmailCampaignWorker
from presentation.pages.members import (
    SubCategoryDialog, CANCELLED_STATUS,
    build_tarif_groups, build_default_tarif_selection, build_status_list,
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
        """Met à jour le libellé du bouton tarifs selon la sélection courante."""
        all_tarifs = set(m.tarif_name for m in self.members_list if m.tarif_name)
        default_tarifs = build_default_tarif_selection(self.members_list)
        if not self.selected_tarifs or self.selected_tarifs == all_tarifs:
            self.tarif_filter.setText("Tous les tarifs ▾")
        elif self.selected_tarifs == default_tarifs:
            self.tarif_filter.setText("Tous sauf liste d'attente ▾")
        else:
            self.tarif_filter.setText(f"Tarifs ({len(self.selected_tarifs)}) ▾")

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
        """Ouvre la pop-up de sélection des tarifs, regroupés par type (comme l'onglet Adhérents)."""
        dialog = SubCategoryDialog(
            build_tarif_groups(self.members_list),
            self.selected_tarifs,
            on_change=self.on_popup_selection_changed,
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

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 15, 20, 20)
        layout.setSpacing(12)

        # Séparateur mobile horizontal (Splitter) pour séparer les Destinataires à gauche et la Composition à droite
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setStyleSheet("""
            QSplitter::handle {
                background-color: #E2E8F0;
                width: 1px;
            }
        """)

        # ----------------------------------------------------
        # CÔTÉ GAUCHE : SÉLECTION DES DESTINATAIRES
        # ----------------------------------------------------
        left_container = QWidget()
        left_layout = QVBoxLayout(left_container)
        left_layout.setContentsMargins(0, 0, 10, 0)
        left_layout.setSpacing(10)

        self.dest_title = QLabel("🎯 Sélection des Destinataires (0)")
        self.dest_title.setStyleSheet("font-size: 13px; font-weight: bold; color: #1E293B;")
        left_layout.addWidget(self.dest_title)

        # Barre de recherche de destinataire
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("🔍 Filtrer par nom, prénom ou e-mail...")
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

        # Barre de filtres avancés (Tarifs et e-mail envoyé)
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

        # 1. Filtre par Tarif (pop-up de sélection multi-critères, identique à l'onglet Adhérents)
        self.tarif_filter = QPushButton("Tous les tarifs ▾")
        self.tarif_filter.setCursor(Qt.PointingHandCursor)
        self.tarif_filter.setStyleSheet(self.get_filter_button_style())
        self.tarif_filter.clicked.connect(self.open_tarif_popup)
        filters_bar.addWidget(self.tarif_filter)

        # 1b. Filtre par Statut (pop-up à cases à cocher ; "Annulé" décoché par défaut)
        self.status_filter = QPushButton("Tous sauf annulés ▾")
        self.status_filter.setCursor(Qt.PointingHandCursor)
        self.status_filter.setStyleSheet(self.get_filter_button_style())
        self.status_filter.clicked.connect(self.open_status_popup)
        filters_bar.addWidget(self.status_filter)

        # 2. Filtre E-mail envoyé
        self.sent_filter = QComboBox()
        self.sent_filter.addItems(["Tous les envois", "Non envoyés", "Envoyés"])
        self.sent_filter.setStyleSheet(self.get_combobox_style())
        self.sent_filter.currentIndexChanged.connect(self.on_filters_changed)
        filters_bar.addWidget(self.sent_filter)

        # 3. Filtre Calendrier : Inscrit après le (QCheckBox + QDateEdit)
        self.date_checkbox = QCheckBox("Inscrit après le :")
        self.date_checkbox.setStyleSheet("color: #475569; font-size: 11px; font-weight: 500;")
        self.date_checkbox.stateChanged.connect(self.on_filters_changed)
        filters_bar.addWidget(self.date_checkbox)

        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True) # Affiche un calendrier pop-up visuel !
        self.date_edit.setDate(QDate(2026, 7, 1)) # Par défaut au début de la saison
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
        filters_bar.addWidget(self.date_edit)

        left_layout.addLayout(filters_bar)

        # Boutons de sélection de masse pour la sélection filtrée
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

        # List Widget contenant les checkboxes d'adhérents (avec style de checkbox VERT !)
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
        # CÔTÉ DROIT : COMPOSITION DE L'EMAIL & ENVOI
        # ----------------------------------------------------
        right_container = QWidget()
        right_layout = QVBoxLayout(right_container)
        right_layout.setContentsMargins(10, 0, 0, 0)
        right_layout.setSpacing(15)

        form_frame = QFrame()
        form_frame.setStyleSheet("""
            QFrame {
                background-color: #FFFFFF;
                border: 1px solid #E2E8F0;
                border-radius: 8px;
                padding: 15px;
            }
        """)
        form_layout = QVBoxLayout(form_frame)
        form_layout.setSpacing(10)

        # Section de Gestion des modèles d'e-mails (Nouveau !)
        form_layout.addWidget(QLabel("Modèle d'e-mail :"))
        template_bar = QHBoxLayout()
        template_bar.setSpacing(6)
        
        self.template_selector = QComboBox()
        self.template_selector.setStyleSheet("""
            QComboBox {
                background-color: #FFFFFF;
                border: 1px solid #CBD5E1;
                border-radius: 6px;
                padding: 6px;
                color: #1E293B;
                min-width: 180px;
            }
        """)
        self.template_selector.currentIndexChanged.connect(self.on_template_selected)
        template_bar.addWidget(self.template_selector)
        
        self.btn_save_template = QPushButton("💾 Enregistrer")
        self.btn_save_template.setStyleSheet("""
            QPushButton {
                background-color: #10B981;
                color: #FFFFFF;
                border: none;
                border-radius: 6px;
                padding: 6px 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #059669;
            }
        """)
        self.btn_save_template.clicked.connect(self.on_save_template_clicked)
        template_bar.addWidget(self.btn_save_template)
        
        self.btn_new_template = QPushButton("➕ Nouveau")
        self.btn_new_template.setStyleSheet("""
            QPushButton {
                background-color: #3B82F6;
                color: #FFFFFF;
                border: none;
                border-radius: 6px;
                padding: 6px 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #2563EB;
            }
        """)
        self.btn_new_template.clicked.connect(self.on_new_template_clicked)
        template_bar.addWidget(self.btn_new_template)
        
        self.btn_delete_template = QPushButton("🗑️ Supprimer")
        self.btn_delete_template.setStyleSheet("""
            QPushButton {
                background-color: #EF4444;
                color: #FFFFFF;
                border: none;
                border-radius: 6px;
                padding: 6px 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #DC2626;
            }
        """)
        self.btn_delete_template.clicked.connect(self.on_delete_template_clicked)
        template_bar.addWidget(self.btn_delete_template)
        
        form_layout.addLayout(template_bar)

        # Objet du mail
        form_layout.addWidget(QLabel("Objet du courriel :"))
        self.subject_input = QLineEdit()
        self.subject_input.setPlaceholderText("Entrez le sujet de l'email...")
        self.subject_input.setText("Attestation de paiement escalade - Amicale Laïque de Jonage")
        self.subject_input.setStyleSheet("""
            QLineEdit {
                background-color: #FFFFFF;
                border: 1px solid #CBD5E1;
                border-radius: 6px;
                padding: 8px;
                color: #1E293B;
            }
        """)
        form_layout.addWidget(self.subject_input)

        # Corps du mail
        form_layout.addWidget(QLabel("Corps du message (Texte brut) :"))
        self.body_input = QTextEdit()
        self.body_input.setPlaceholderText("Saisissez le texte d'accompagnement...")
        self.body_input.setPlainText(
            "Bonjour {Prénom},\n\n"
            "Veuillez trouver ci-joint l'attestation de paiement relative à votre adhésion au club d'escalade "
            "pour la saison active.\n\n"
            "Sportivement,\n"
            "L'équipe ALJ Escalade"
        )
        self.body_input.setStyleSheet("""
            QTextEdit {
                background-color: #FFFFFF;
                border: 1px solid #CBD5E1;
                border-radius: 6px;
                padding: 8px;
                color: #1E293B;
                min-height: 120px;
            }
        """)
        form_layout.addWidget(self.body_input)

        # Option d'attestation PDF (Nouveau !)
        self.attach_pdf_checkbox = QCheckBox("Joindre l'attestation de paiement (PDF)")
        self.attach_pdf_checkbox.setChecked(True)
        self.attach_pdf_checkbox.setStyleSheet("""
            QCheckBox {
                color: #475569;
                font-size: 12px;
                font-weight: 500;
                margin-top: 5px;
                margin-bottom: 2px;
            }
        """)
        form_layout.addWidget(self.attach_pdf_checkbox)

        # Option WhatsApp (Nouveau !)
        self.attach_whatsapp_checkbox = QCheckBox("Joindre l'invitation & le QRCode WhatsApp du créneau")
        self.attach_whatsapp_checkbox.setChecked(True)
        self.attach_whatsapp_checkbox.setStyleSheet("""
            QCheckBox {
                color: #475569;
                font-size: 12px;
                font-weight: 500;
                margin-top: 2px;
                margin-bottom: 5px;
            }
        """)
        form_layout.addWidget(self.attach_whatsapp_checkbox)

        # Conteneur pour le gabarit WhatsApp personnalisé (Nouveau !)
        self.whatsapp_template_widget = QWidget()
        whatsapp_temp_layout = QVBoxLayout(self.whatsapp_template_widget)
        whatsapp_temp_layout.setContentsMargins(0, 5, 0, 5)
        whatsapp_temp_layout.setSpacing(5)
        
        lbl_bar_wt = QHBoxLayout()
        lbl_bar_wt.setSpacing(6)
        lbl_wt = QLabel("📝 Texte d'invitation WhatsApp joint au mail (supporte {group_name} et {whatsapp_link}) :")
        lbl_wt.setStyleSheet("color: #475569; font-size: 11px; font-weight: bold;")
        lbl_bar_wt.addWidget(lbl_wt)
        lbl_bar_wt.addStretch()

        self.btn_save_whatsapp_template = QPushButton("💾 Enregistrer")
        self.btn_save_whatsapp_template.setToolTip("Enregistre ce texte WhatsApp en base de données pour tous les prochains envois.")
        self.btn_save_whatsapp_template.setStyleSheet("""
            QPushButton {
                background-color: #10B981;
                color: #FFFFFF;
                border: none;
                border-radius: 6px;
                padding: 3px 10px;
                font-weight: bold;
                font-size: 10px;
            }
            QPushButton:hover {
                background-color: #059669;
            }
        """)
        self.btn_save_whatsapp_template.clicked.connect(self.on_save_whatsapp_template_clicked)
        lbl_bar_wt.addWidget(self.btn_save_whatsapp_template)
        whatsapp_temp_layout.addLayout(lbl_bar_wt)
        
        self.whatsapp_template_input = QTextEdit()
        saved_wt = SqliteRepository.get_whatsapp_template()
        self.whatsapp_template_input.setPlainText(saved_wt if saved_wt else DEFAULT_WHATSAPP_TEMPLATE)
        self.whatsapp_template_input.setStyleSheet("""
            QTextEdit {
                border: 1px solid #CBD5E1;
                border-radius: 6px;
                padding: 6px;
                color: #1E293B;
                min-height: 80px;
                max-height: 100px;
                font-size: 11px;
            }
        """)
        whatsapp_temp_layout.addWidget(self.whatsapp_template_input)
        form_layout.addWidget(self.whatsapp_template_widget)

        # Gérer la visibilité dynamique du texte d'invitation
        self.attach_whatsapp_checkbox.toggled.connect(self.whatsapp_template_widget.setVisible)

        # Option Signature du club (radio boutons : avec / sans signature en fin d'e-mail)
        sig_group = QGroupBox("✍️ Signature du club")
        sig_group.setStyleSheet("""
            QGroupBox {
                color: #1E293B;
                font-weight: bold;
                font-size: 12px;
                border: 1px solid #E2E8F0;
                border-radius: 6px;
                margin-top: 10px;
                padding-top: 15px;
            }
        """)
        sig_layout = QHBoxLayout(sig_group)
        sig_layout.setSpacing(12)

        self.signature_yes_radio = QRadioButton("Ajouter la signature du club (logos Instagram & Facebook)")
        self.signature_yes_radio.setChecked(True)
        self.signature_yes_radio.setStyleSheet("color: #475569; font-size: 12px; font-weight: 500;")
        sig_layout.addWidget(self.signature_yes_radio)

        self.signature_no_radio = QRadioButton("Sans signature")
        self.signature_no_radio.setStyleSheet("color: #475569; font-size: 12px; font-weight: 500;")
        sig_layout.addWidget(self.signature_no_radio)
        sig_layout.addStretch()

        form_layout.addWidget(sig_group)

        # Options des destinataires (Choix des e-mails)
        dest_group = QGroupBox("📩 Choix des adresses de destination")
        dest_group.setStyleSheet("""
            QGroupBox {
                color: #1E293B;
                font-weight: bold;
                font-size: 12px;
                border: 1px solid #E2E8F0;
                border-radius: 6px;
                margin-top: 10px;
                padding-top: 15px;
            }
        """)
        dest_layout = QVBoxLayout(dest_group)
        dest_layout.setSpacing(5)
        
        self.use_primary_email_cb = QCheckBox("Envoyer à l'E-mail Principal (Fiche Adhérent)")
        self.use_primary_email_cb.setChecked(True)
        self.use_primary_email_cb.setStyleSheet("color: #475569; font-size: 12px; font-weight: 500;")
        dest_layout.addWidget(self.use_primary_email_cb)

        self.use_secondary_email_cb = QCheckBox("Envoyer au Deuxième E-mail (Fiche Adhérent)")
        self.use_secondary_email_cb.setChecked(True)
        self.use_secondary_email_cb.setStyleSheet("color: #475569; font-size: 12px; font-weight: 500;")
        dest_layout.addWidget(self.use_secondary_email_cb)

        self.use_payer_email_cb = QCheckBox("Envoyer à l'E-mail du Payeur (Acheteur HelloAsso)")
        self.use_payer_email_cb.setChecked(False)
        self.use_payer_email_cb.setStyleSheet("color: #475569; font-size: 12px; font-weight: 500;")
        dest_layout.addWidget(self.use_payer_email_cb)
        
        form_layout.addWidget(dest_group)

        # Bouton d'aperçu du code HTML + Bouton Envoi
        send_row = QHBoxLayout()
        send_row.setSpacing(8)

        self.btn_preview_email = QPushButton("🔍 Prévisualiser l'email")
        self.btn_preview_email.setCursor(Qt.PointingHandCursor)
        self.btn_preview_email.setStyleSheet("""
            QPushButton {
                background-color: #FFFFFF;
                border: 1px solid #CBD5E1;
                border-radius: 6px;
                padding: 10px 14px;
                font-size: 12px;
                font-weight: 500;
                color: #059669;
            }
            QPushButton:hover {
                background-color: #ECFDF5;
                border-color: #A7F3D0;
            }
        """)
        self.btn_preview_email.clicked.connect(self.on_preview_email_clicked)
        send_row.addWidget(self.btn_preview_email)

        self.btn_view_html = QPushButton("👁️ Voir le code HTML du mail")
        self.btn_view_html.setCursor(Qt.PointingHandCursor)
        self.btn_view_html.setStyleSheet("""
            QPushButton {
                background-color: #FFFFFF;
                border: 1px solid #CBD5E1;
                border-radius: 6px;
                padding: 10px 14px;
                font-size: 12px;
                font-weight: 500;
                color: #2563EB;
            }
            QPushButton:hover {
                background-color: #EFF6FF;
                border-color: #BFDBFE;
            }
        """)
        self.btn_view_html.clicked.connect(self.on_view_html_clicked)
        send_row.addWidget(self.btn_view_html)
        send_row.addStretch()

        self.send_btn = QPushButton("🚀 Lancer l'envoi de la campagne de courriels")
        self.send_btn.setCursor(Qt.PointingHandCursor)
        self.send_btn.setStyleSheet("""
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
        self.send_btn.clicked.connect(self.start_email_campaign)
        send_row.addWidget(self.send_btn)

        form_layout.addLayout(send_row)

        right_layout.addWidget(form_frame)

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
                background-color: #3B82F6;
                border-radius: 5px;
            }
        """)
        self.progress_bar.setVisible(False)
        right_layout.addWidget(self.progress_bar)

        # Zone d'affichage des logs
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setPlaceholderText("Les comptes-rendus d'envois SMTP / Gmail REST s'afficheront ici...")
        self.log_area.setStyleSheet("""
            QTextEdit {
                background-color: #1E293B;
                color: #A7F3D0;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 12px;
                border-radius: 8px;
                padding: 10px;
                min-height: 100px;
            }
        """)
        right_layout.addWidget(self.log_area)

        self.splitter.addWidget(right_container)
        
        # Ratios d'expansion
        self.splitter.setStretchFactor(0, 1) # Liste destinataires
        self.splitter.setStretchFactor(1, 2) # Formulaire d'édition

        layout.addWidget(self.splitter)
        
        # Charger les templates d'email initiaux (Nouveau !)
        self.load_email_templates()

    def on_season_changed(self):
        """Déclenché lorsque l'utilisateur change de saison dans la liste déroulante."""
        self.load_members(members_list=None)

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
            
            for m in self.members_list:
                email_dest = m.primary_email or m.payer_email
                if email_dest:
                    item = QListWidgetItem(f"{m.user_last_name} {m.user_first_name} <{email_dest}>")
                    item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                    item.setCheckState(Qt.Unchecked) # Décoché par défaut
                    item.setData(Qt.UserRole, m) # Stocker le membre complet
                    self.list_widget.addItem(item)
            
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

    def on_search_changed(self, text: str):
        """Filtrage textuel à la volée."""
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

            # Masquer l'item s'il ne valide pas les critères
            item.setHidden(not (match_search and match_tarif and match_status and match_sent and match_date))
            
        self.list_widget.blockSignals(False)
        self.update_selection_count()

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

    def update_selection_count(self):
        """Calcule et affiche le nombre de destinataires sélectionnés."""
        checked_count = 0
        for i in range(self.list_widget.count()):
            if self.list_widget.item(i).checkState() == Qt.Checked:
                checked_count += 1
        
        self.dest_title.setText(f"🎯 Sélection des Destinataires ({checked_count})")
        self.send_btn.setEnabled(checked_count > 0)

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

        subject = self.subject_input.text().strip()
        body = self.body_input.toPlainText()

        self.log_area.append(f"ℹ️ [INFO] Lancement de la campagne d'envoi pour {len(selected_members)} destinataires...")
        
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
            add_signature=self.signature_yes_radio.isChecked()
        )
        self.worker.progress.connect(self.on_progress)
        self.worker.finished.connect(self.on_finished)
        self.worker.start()

    def on_progress(self, message: str, percent: int):
        self.progress_bar.setValue(percent)
        self.log_area.append(message)

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

        # 3. Personnalisation des variables (identique à SendEmailCampaignWorker)
        msg_body = body
        msg_body = msg_body.replace("{Prénom}", first_member.user_first_name.strip().title())
        msg_body = msg_body.replace("{Nom}", first_member.user_last_name.strip().upper())
        msg_body = msg_body.replace("{first_name}", first_member.user_first_name.strip().title())
        msg_body = msg_body.replace("{last_name}", first_member.user_last_name.strip().upper())

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
        subject_lbl = QLabel(f"<b>Objet :</b> {subject or '(vide)'}")
        subject_lbl.setTextFormat(Qt.TextFormat.RichText)
        subject_lbl.setWordWrap(True)
        header_layout.addWidget(to_lbl)
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

    def on_save_template_clicked(self):
        """Enregistre les modifications apportées au template sélectionné."""
        current_name = self.template_selector.currentText().strip()
        if not current_name:
            QMessageBox.warning(self, "Pas de modèle", "Veuillez sélectionner ou créer un modèle avant d'enregistrer.")
            return
            
        subject = self.subject_input.text().strip()
        body = self.body_input.toPlainText()
        
        from infrastructure.sqlite_repository import SqliteRepository
        success = SqliteRepository.save_email_template(current_name, subject, body)
        if success:
            self.log_area.append(f"💾 [MODÈLE] Modèle d'e-mail '{current_name}' enregistré avec succès en BDD.")
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
        from PySide6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "Nouveau Modèle d'E-mail", "Entrez le nom de votre nouveau modèle d'e-mail :")
        if not ok or not name.strip():
            return
            
        name = name.strip()
        subject = "Sujet du nouveau courriel"
        body = "Bonjour {first_name},\n\nSaisissez votre texte ici."
        
        from infrastructure.sqlite_repository import SqliteRepository
        # Vérifier si existe déjà
        templates = SqliteRepository.get_email_templates()
        if any(t["name"].lower() == name.lower() for t in templates):
            QMessageBox.warning(self, "Modèle Existant", f"Un modèle nommé '{name}' existe déjà.")
            return
            
        success = SqliteRepository.save_email_template(name, subject, body)
        if success:
            self.log_area.append(f"➕ [MODÈLE] Nouveau modèle '{name}' créé avec succès.")
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
