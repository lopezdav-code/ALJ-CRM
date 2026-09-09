import datetime
from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
    QScrollArea, QWidget, QLineEdit, QMessageBox
)
from PySide6.QtCore import Qt, Signal
from domain.models import Member

class MemberDetailPanel(QFrame):
    """
    Panneau latéral d'affichage détaillé pour un adhérent unique.
    Permet également d'éditer, de comparer et de sauvegarder les modifications directement dans Excel (v1.0.8).
    """
    closed = Signal()
    member_updated = Signal() # Émis après une sauvegarde réussie pour actualiser le tableau parent !
    email_requested = Signal(object) # Émis via le bouton ✉️ : ouvrir la Communication filtrée sur cet adhérent

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_member = None
        self.is_editing = False
        self.edit_widgets = {}

        self.setStyleSheet("""
            MemberDetailPanel {
                background-color: #FFFFFF;
                border-left: 1px solid #E2E8F0;
            }
            QLabel {
                color: #1E293B;
            }
        """)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(15)

        # En-tête du panneau avec bouton fermer, éditer, et titre
        header_layout = QHBoxLayout()
        self.title_label = QLabel("Fiche Adhérent")
        self.title_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #1E293B;")
        header_layout.addWidget(self.title_label)

        header_layout.addStretch()

        # Bouton d'édition (Nouveau !)
        self.edit_btn = QPushButton("✏️ Éditer")
        self.edit_btn.setCursor(Qt.PointingHandCursor)
        self.edit_btn.setStyleSheet("""
            QPushButton {
                background-color: #F1F5F9;
                border: 1px solid #CBD5E1;
                border-radius: 4px;
                padding: 4px 10px;
                font-size: 11px;
                font-weight: bold;
                color: #475569;
            }
            QPushButton:hover {
                background-color: #E2E8F0;
                color: #1E293B;
            }
        """)
        self.edit_btn.clicked.connect(self.toggle_edit_mode)
        header_layout.addWidget(self.edit_btn)

        # Bouton enveloppe : bascule vers la page Communication filtrée sur cet adhérent (Nouveau !)
        self.email_btn = QPushButton("✉️ E-mail")
        self.email_btn.setCursor(Qt.PointingHandCursor)
        self.email_btn.setToolTip("Ouvrir la page Communication avec la recherche filtrée sur cet adhérent")
        self.email_btn.setStyleSheet("""
            QPushButton {
                background-color: #F1F5F9;
                border: 1px solid #CBD5E1;
                border-radius: 4px;
                padding: 4px 10px;
                font-size: 11px;
                font-weight: bold;
                color: #475569;
            }
            QPushButton:hover {
                background-color: #EFF6FF;
                border-color: #BFDBFE;
                color: #2563EB;
            }
        """)
        self.email_btn.clicked.connect(self._on_email_requested)
        header_layout.addWidget(self.email_btn)

        close_btn = QPushButton("✖")
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.setFixedSize(24, 24)
        close_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                border: none;
                font-size: 14px;
                color: #64748B;
            }
            QPushButton:hover {
                color: #EF4444;
            }
        """)
        close_btn.clicked.connect(self.closed.emit)
        header_layout.addWidget(close_btn)
        layout.addLayout(header_layout)

        # Zone défilante (Scroll Area) pour contenir les sections
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea { background-color: transparent; }")

        scroll_content = QWidget()
        scroll_content.setStyleSheet("background-color: transparent;")
        self.scroll_layout = QVBoxLayout(scroll_content)
        self.scroll_layout.setContentsMargins(0, 0, 10, 0)
        self.scroll_layout.setSpacing(15)

        # Les différentes sections d'informations
        self.sec_identity = self.create_section("👤 IDENTITÉ")
        self.sec_payment = self.create_section("💳 ADHÉSION & PAIEMENT")
        self.sec_contact = self.create_section("📞 COORDONNÉES")
        self.sec_emergency = self.create_section("🚨 CONTACTS D'URGENCE")
        self.sec_insurance = self.create_section("🛡️ ASSURANCES & DROITS")
        self.sec_ffme = self.create_section("🏅 PASSEPORTS & DIPLÔMES FFME")
        self.sec_comment = self.create_section("✍️ COMMENTAIRES / CORRECTIFS")

        scroll.setWidget(scroll_content)
        layout.addWidget(scroll)

    def create_section(self, title: str) -> QVBoxLayout:
        """Crée un conteneur vertical stylisé pour une section d'informations."""
        title_lbl = QLabel(title)
        title_lbl.setStyleSheet("font-size: 11px; font-weight: bold; color: #64748B; letter-spacing: 0.5px; margin-top: 5px;")
        self.scroll_layout.addWidget(title_lbl)

        section_frame = QFrame()
        section_frame.setStyleSheet("""
            QFrame {
                background-color: #F8FAFC;
                border: 1px solid #E2E8F0;
                border-radius: 6px;
            }
        """)
        section_layout = QVBoxLayout(section_frame)
        section_layout.setContentsMargins(12, 12, 12, 12)
        section_layout.setSpacing(8)
        
        self.scroll_layout.addWidget(section_frame)
        return section_layout

    def clear_layout(self, layout: QVBoxLayout):
        """Vide l'ensemble des widgets d'une section."""
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

    def add_info_row(self, layout: QVBoxLayout, label: str, value: str):
        """Ajoute une ligne clé/valeur simple dans une section."""
        row_widget = QWidget()
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(5)

        lbl = QLabel(label)
        lbl.setStyleSheet("font-weight: 500; color: #64748B; font-size: 11px;")
        val = QLabel(str(value or ""))
        val.setStyleSheet("color: #1E293B; font-size: 11px;")
        val.setWordWrap(True)
        val.setAlignment(Qt.AlignRight)

        row_layout.addWidget(lbl)
        row_layout.addWidget(val)
        layout.addWidget(row_widget)

    def add_editable_row(self, layout: QVBoxLayout, label: str, field_key: str, value: str):
        """Ajoute une ligne clé/valeur éditable (QLineEdit) dans une section."""
        row_widget = QWidget()
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(5)

        lbl = QLabel(label)
        lbl.setStyleSheet("font-weight: 500; color: #64748B; font-size: 11px;")
        
        edit = QLineEdit(str(value or ""))
        edit.setStyleSheet("""
            QLineEdit {
                background-color: #FFFFFF;
                border: 1px solid #CBD5E1;
                border-radius: 4px;
                padding: 2px 6px;
                font-size: 11px;
                color: #1E293B;
                max-width: 180px;
            }
            QLineEdit:focus {
                border-color: #2563EB;
            }
        """)
        
        row_layout.addWidget(lbl)
        row_layout.addWidget(edit)
        layout.addWidget(row_widget)
        
        self.edit_widgets[field_key] = edit

    def add_combobox_row(self, layout: QVBoxLayout, label: str, field_key: str, value: str, options: list):
        """Ajoute une ligne clé/valeur éditable avec un QComboBox dans une section."""
        from PySide6.QtWidgets import QComboBox
        row_widget = QWidget()
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(5)

        lbl = QLabel(label)
        lbl.setStyleSheet("font-weight: 500; color: #64748B; font-size: 11px;")
        
        combo = QComboBox()
        combo.addItems(options)
        
        # Sélectionner la valeur actuelle
        idx = combo.findText(value)
        if idx >= 0:
            combo.setCurrentIndex(idx)
        else:
            # Essayer insensible à la casse
            for i in range(combo.count()):
                if combo.itemText(i).strip().lower() == str(value).strip().lower():
                    combo.setCurrentIndex(i)
                    break
                    
        combo.setStyleSheet("""
            QComboBox {
                background-color: #FFFFFF;
                border: 1px solid #CBD5E1;
                border-radius: 4px;
                padding: 2px 6px;
                font-size: 11px;
                color: #1E293B;
                max-width: 180px;
            }
            QComboBox:focus {
                border-color: #2563EB;
            }
        """)
        
        row_layout.addWidget(lbl)
        row_layout.addWidget(combo)
        layout.addWidget(row_widget)
        
        self.edit_widgets[field_key] = combo

    def toggle_edit_mode(self):
        """Bascule entre le mode consultation et édition."""
        if not self.is_editing:
            self.is_editing = True
            self.render_member_details()
        else:
            self.save_modifications()

    def set_member(self, member: Member):
        """Peuple le panneau latéral et se positionne d'abord en consultation."""
        self.current_member = member
        self.is_editing = False
        self.render_member_details()

    def _on_email_requested(self):
        """Bouton ✉️ : demande à la fenêtre principale d'ouvrir la page Communication
        avec la recherche filtrée sur l'adhérent courant."""
        if self.current_member is not None:
            self.email_requested.emit(self.current_member)

    def render_member_details(self):
        """Dessine dynamiquement le détail en consultation ou édition."""
        member = self.current_member
        if not member:
            return

        self.title_label.setText(f"{member.user_last_name} {member.user_first_name}")

        # Vider les layouts existants
        self.edit_widgets = {}
        self.clear_layout(self.sec_identity)
        self.clear_layout(self.sec_payment)
        self.clear_layout(self.sec_contact)
        self.clear_layout(self.sec_emergency)
        self.clear_layout(self.sec_insurance)
        self.clear_layout(self.sec_ffme)
        self.clear_layout(self.sec_comment)

        if not self.is_editing:
            # Mode lecture seule (Bouton gris classique)
            self.edit_btn.setText("✏️ Éditer")
            self.edit_btn.setStyleSheet("""
                QPushButton {
                    background-color: #F1F5F9;
                    border: 1px solid #CBD5E1;
                    border-radius: 4px;
                    padding: 4px 10px;
                    font-size: 11px;
                    font-weight: bold;
                    color: #475569;
                }
                QPushButton:hover {
                    background-color: #E2E8F0;
                }
            """)

            # Section 1 : Identité
            self.add_info_row(self.sec_identity, "Nom :", member.user_last_name)
            self.add_info_row(self.sec_identity, "Prénom :", member.user_first_name)
            self.add_info_row(self.sec_identity, "Date de naissance :", str(member.birth_date).split(" ")[0] if member.birth_date else "")
            self.add_info_row(self.sec_identity, "Sexe :", member.gender)
            self.add_info_row(self.sec_identity, "Nationalité :", member.nationality)
            self.add_info_row(self.sec_identity, "Licence FFME :", member.licence_ffme or "Aucune")

            # Section 2 : Adhésion & Paiement
            self.add_info_row(self.sec_payment, "Commande HelloAsso :", member.order_ref)
            self.add_info_row(self.sec_payment, "Date d'achat :", str(member.order_date).split(" ")[0] if member.order_date else "")
            self.add_info_row(self.sec_payment, "Tarif :", member.tarif_name)
            self.add_info_row(self.sec_payment, "Montant payé :", f"{member.amount:.2f} €")
            self.add_info_row(self.sec_payment, "E-mail utilisé pour le paiement :", member.payer_email or "Non renseigné")
            self.add_info_row(self.sec_payment, "Statut :", member.status)

            # Section 3 : Coordonnées
            self.add_info_row(self.sec_contact, "E-mail Principal :", member.primary_email)
            if member.secondary_email:
                self.add_info_row(self.sec_contact, "E-mail Secondaire :", member.secondary_email)
            self.add_info_row(self.sec_contact, "Téléphone :", member.phone or "Non renseigné")
            self.add_info_row(self.sec_contact, "Adresse :", f"{member.address}\n{member.zip_code} {member.city}")

            # Section 4 : Contacts d'urgence
            self.add_info_row(self.sec_emergency, "Contact 1 :", member.emergency_contact_name_1 or "Non spécifié")
            self.add_info_row(self.sec_emergency, "Téléphone 1 :", member.emergency_contact_phone_1 or "Non spécifié")
            if member.emergency_contact_name_2:
                self.add_info_row(self.sec_emergency, "Contact 2 :", member.emergency_contact_name_2)
                self.add_info_row(self.sec_emergency, "Téléphone 2 :", member.emergency_contact_phone_2)

            # Section 5 : Assurances & Droits
            ins_txt = "Base" if member.insurance.has_base else ("Base +" if member.insurance.has_base_plus else ("Base ++" if member.insurance.has_base_plus_plus else "Aucune"))
            self.add_info_row(self.sec_insurance, "Assurance principale :", ins_txt)
            self.add_info_row(self.sec_insurance, "Option Ski :", "Oui" if member.insurance.has_ski else "Non")
            self.add_info_row(self.sec_insurance, "Option VTT :", "Oui" if member.insurance.has_vtt else "Non")
            self.add_info_row(self.sec_insurance, "Option Trail :", "Oui" if member.insurance.has_trail else "Non")
            self.add_info_row(self.sec_insurance, "Droit à l'image :", member.photo_auth or "Non spécifié")
            self.add_info_row(self.sec_insurance, "Engagement Médical :", member.health_q_auth or "Non spécifié")

            # Section 5.5 : Passeports & Diplômes FFME
            self.add_info_row(self.sec_ffme, "🔴 Badge rouge diff :", member.badge_rouge or "Non")
            self.add_info_row(self.sec_ffme, "🟩 Autonomie Bloc :", member.autonomie_bloc or "Non")
            self.add_info_row(self.sec_ffme, "🚸 Autorisation Parentale Autonomes :", member.parental_auth_autonomous or "Non") # Nouveau !
            self.add_info_row(self.sec_ffme, "🚸 Autorisation Parentale Famille :", member.parental_auth_family or "Non")      # Nouveau !
            self.add_info_row(self.sec_ffme, "🎓 Passeports obtenus :", member.raw_passports or "Aucun passeport enregistré")
            self.add_info_row(self.sec_ffme, "📜 Diplômes FFME :", member.raw_diplomas or "Aucun diplôme enregistré")

            # Section 6 : Commentaires
            lbl_comm = QLabel(member.commentaires_correctif or "Aucun correctif ou commentaire saisi.")
            lbl_comm.setStyleSheet("font-size: 11px; color: #475569; font-style: italic;")
            lbl_comm.setWordWrap(True)
            self.sec_comment.addWidget(lbl_comm)

        else:
            # Mode Édition (QLineEdit pour les champs modifiables, Bouton vert)
            self.edit_btn.setText("💾 Sauvegarder")
            self.edit_btn.setStyleSheet("""
                QPushButton {
                    background-color: #10B981;
                    border: none;
                    border-radius: 4px;
                    padding: 4px 10px;
                    font-size: 11px;
                    font-weight: bold;
                    color: #FFFFFF;
                }
                QPushButton:hover {
                    background-color: #059669;
                }
            """)

            # Section 1 : Identité (Champs d'écriture !)
            self.add_editable_row(self.sec_identity, "Nom :", "user_last_name", member.user_last_name)
            self.add_editable_row(self.sec_identity, "Prénom :", "user_first_name", member.user_first_name)
            self.add_editable_row(self.sec_identity, "Date de naissance :", "birth_date", str(member.birth_date).split(" ")[0] if member.birth_date else "")
            self.add_info_row(self.sec_identity, "Sexe :", member.gender)
            self.add_info_row(self.sec_identity, "Nationalité :", member.nationality)
            self.add_editable_row(self.sec_identity, "Licence FFME :", "licence_ffme", member.licence_ffme)

            # Section 2 : Adhésion (lecture seule ou combobox éditable !)
            self.add_info_row(self.sec_payment, "Commande HelloAsso :", member.order_ref)
            self.add_info_row(self.sec_payment, "Date d'achat :", str(member.order_date).split(" ")[0] if member.order_date else "")
            self.add_info_row(self.sec_payment, "Tarif :", member.tarif_name)
            self.add_info_row(self.sec_payment, "Montant payé :", f"{member.amount:.2f} €")
            self.add_info_row(self.sec_payment, "E-mail utilisé pour le paiement :", member.payer_email or "Non renseigné")
            # Statuts normalisés (+ statut brut courant pour ne pas créer un faux changement)
            status_opts = ["Validé", "Traité", "Terminé", "En cours", "Annulé"]
            if member.status and member.status not in status_opts:
                status_opts.append(member.status)
            self.add_combobox_row(self.sec_payment, "Statut :", "status", member.status, status_opts)

            # Section 3 : Coordonnées (Champs d'écriture !)
            self.add_editable_row(self.sec_contact, "E-mail Principal :", "primary_email", member.primary_email or member.payer_email)
            self.add_editable_row(self.sec_contact, "Deuxième E-mail :", "secondary_email", member.secondary_email)
            self.add_editable_row(self.sec_contact, "Téléphone :", "phone", member.phone)
            self.add_editable_row(self.sec_contact, "Ville :", "city", member.city)
            self.add_info_row(self.sec_contact, "Adresse :", f"{member.address}\n{member.zip_code}")

            # Section 4 : Contacts d'urgence (Champs d'écriture !)
            self.add_editable_row(self.sec_emergency, "Contact 1 :", "emergency_contact_name_1", member.emergency_contact_name_1)
            self.add_editable_row(self.sec_emergency, "Téléphone 1 :", "emergency_contact_phone_1", member.emergency_contact_phone_1)

            # Section 5 : Assurances & Droits (Édition !)
            ins_txt = "Base" if member.insurance.has_base else ("Base +" if member.insurance.has_base_plus else ("Base ++" if member.insurance.has_base_plus_plus else "Aucune"))
            self.add_combobox_row(self.sec_insurance, "Assurance principale :", "assurance_level", ins_txt, ["Aucune", "Base", "Base +", "Base ++"])
            self.add_combobox_row(self.sec_insurance, "Option Ski :", "opt_assurance_ski", "Oui" if member.insurance.has_ski else "Non", ["Non", "Oui"])
            self.add_combobox_row(self.sec_insurance, "Option VTT :", "opt_assurance_vtt", "Oui" if member.insurance.has_vtt else "Non", ["Non", "Oui"])
            self.add_combobox_row(self.sec_insurance, "Option Trail :", "opt_assurance_trail", "Oui" if member.insurance.has_trail else "Non", ["Non", "Oui"])
            self.add_editable_row(self.sec_insurance, "Droit à l'image :", "photo_auth", member.photo_auth)
            self.add_editable_row(self.sec_insurance, "Engagement Médical :", "health_q_auth", member.health_q_auth)

            # Section 5.5 : Passeports & Diplômes FFME (Édition !)
            self.add_combobox_row(self.sec_ffme, "🔴 Badge rouge diff :", "badge_rouge", member.badge_rouge or "Non", ["Non", "Oui"])
            self.add_combobox_row(self.sec_ffme, "🟩 Autonomie Bloc :", "autonomie_bloc", member.autonomie_bloc or "Non", ["Non", "Oui"])
            self.add_combobox_row(self.sec_ffme, "🚸 Autoris. Parentale Autonomes :", "parental_auth_autonomous", member.parental_auth_autonomous or "Non", ["Non", "Oui"]) # Nouveau !
            self.add_combobox_row(self.sec_ffme, "🚸 Autoris. Parentale Famille :", "parental_auth_family", member.parental_auth_family or "Non", ["Non", "Oui"])      # Nouveau !
            self.add_editable_row(self.sec_ffme, "🎓 Passeports obtenus :", "raw_passports", member.raw_passports)
            self.add_editable_row(self.sec_ffme, "📜 Diplômes FFME :", "raw_diplomas", member.raw_diplomas)

            # Section 6 : Note d'explication
            lbl_comm = QLabel("⚠️ Les modifications seront directement enregistrées dans la base de données SQLite locale et partagées sur Google Drive.")
            lbl_comm.setStyleSheet("font-size: 11px; color: #1E293B; font-weight: 500; font-style: italic;")
            lbl_comm.setWordWrap(True)
            self.sec_comment.addWidget(lbl_comm)

    def save_modifications(self):
        """Calcule les modifications apportées et les écrit de façon sécurisée dans la BDD."""
        member = self.current_member
        if not member:
            return

        changes = []
        updated_fields = {}

        # 1. Rapprochement de l'assurance principale pour l'écrire sous forme de colonnes séparées
        if "assurance_level" in self.edit_widgets:
            new_level = self.edit_widgets["assurance_level"].currentText().strip()
            # Valeurs d'origine
            orig_base = "Oui" if member.insurance.has_base else "Non"
            orig_plus = "Oui" if member.insurance.has_base_plus else "Non"
            orig_plus_plus = "Oui" if member.insurance.has_base_plus_plus else "Non"
            
            # Nouvelles valeurs cibles
            new_base = "Oui" if new_level == "Base" else "Non"
            new_plus = "Oui" if new_level == "Base +" else "Non"
            new_plus_plus = "Oui" if new_level == "Base ++" else "Non"
            
            if new_base != orig_base:
                updated_fields["opt_assurance_base"] = new_base
                changes.append(f"• <b>Assurance Base</b> : {orig_base} ➔ <b>{new_base}</b>")
            if new_plus != orig_plus:
                updated_fields["opt_assurance_base_plus"] = new_plus
                changes.append(f"• <b>Assurance Base +</b> : {orig_plus} ➔ <b>{new_plus}</b>")
            if new_plus_plus != orig_plus_plus:
                updated_fields["opt_assurance_base_plus_plus"] = new_plus_plus
                changes.append(f"• <b>Assurance Base ++</b> : {orig_plus_plus} ➔ <b>{new_plus_plus}</b>")

        # Mappages sémantiques champ à champ
        mappings = {
            "user_last_name": ("Nom", member.user_last_name),
            "user_first_name": ("Prénom", member.user_first_name),
            "birth_date": ("Date de naissance", member.birth_date),
            "licence_ffme": ("N° Licence FFME", member.licence_ffme),
            "status": ("Statut", member.status),
            "primary_email": ("E-mail Principal", member.primary_email),
            "secondary_email": ("Deuxième E-mail", member.secondary_email),
            "phone": ("Téléphone", member.phone),
            "city": ("Ville", member.city),
            "emergency_contact_name_1": ("Contact Urgence", member.emergency_contact_name_1),
            "emergency_contact_phone_1": ("Tél Urgence", member.emergency_contact_phone_1),
            "opt_assurance_ski": ("Option Ski", "Oui" if member.insurance.has_ski else "Non"),
            "opt_assurance_vtt": ("Option VTT", "Oui" if member.insurance.has_vtt else "Non"),
            "opt_assurance_trail": ("Option Trail", "Oui" if member.insurance.has_trail else "Non"),
            "photo_auth": ("Droit à l'image", member.photo_auth),
            "health_q_auth": ("Engagement Médical", member.health_q_auth),
            "badge_rouge": ("Badge rouge", member.badge_rouge),
            "autonomie_bloc": ("Autonomie Bloc", member.autonomie_bloc),
            "raw_passports": ("Passeports FFME", member.raw_passports),
            "raw_diplomas": ("Diplômes FFME", member.raw_diplomas),
            "parental_auth_autonomous": ("Autoris. Parentale Autonomes", member.parental_auth_autonomous),
            "parental_auth_family": ("Autoris. Parentale Famille", member.parental_auth_family)
        }

        for field_key, (label, orig_val) in mappings.items():
            if field_key in self.edit_widgets:
                widget = self.edit_widgets[field_key]
                from PySide6.QtWidgets import QComboBox
                if isinstance(widget, QComboBox):
                    new_val = widget.currentText().strip()
                else:
                    new_val = widget.text().strip()
                    
                if field_key == "licence_ffme":
                    # Supprimer absolument tous les espaces pour la licence FFME !
                    new_val = new_val.replace(" ", "")
                orig_clean = str(orig_val or "").strip()
                if new_val != orig_clean:
                    changes.append(f"• <b>{label}</b> : {orig_clean or 'vide'} ➔ <b>{new_val or 'vide'}</b>")
                    updated_fields[field_key] = new_val

        if not changes:
            # Pas de changements réels, simplement repasser en lecture seule
            self.is_editing = False
            self.render_member_details()
            return

        # Afficher la boîte de dialogue récapitulative des modifications avant sauvegarde
        box = QMessageBox(self)
        box.setWindowTitle("Confirmer les modifications")
        box.setTextFormat(Qt.TextFormat.RichText)
        
        html_msg = (
            f"<h3><b>📝 Valider les modifications ?</b></h3>"
            f"<p>Les modifications suivantes ont été détectées pour <b>{member.user_last_name} {member.user_first_name}</b> :</p>"
            f"<div style='background-color: #F8FAFC; border: 1px solid #E2E8F0; padding: 10px; border-radius: 6px; font-size: 11px;'>"
            f"  {'<br>'.join(changes)}"
            f"</div>"
            f"<p><i>Cela va enregistrer définitivement les modifications dans votre base de données locale.</i></p>"
        )
        box.setText(html_msg)
        
        yes_btn = box.addButton("💾 Enregistrer les modifications", QMessageBox.ButtonRole.YesRole)
        no_btn = box.addButton("Annuler", QMessageBox.ButtonRole.NoRole)
        box.exec()
        
        if box.clickedButton() == yes_btn:
            # Afficher une belle en-tête d'action dans les logs avant d'enregistrer (Nouveau !)
            print("\n================================================================================")
            print(f"📝 [MODIFICATION] Enregistrement des modifications pour {member.user_last_name.upper()} {member.user_first_name}...")
            print("================================================================================")
            
            # 1. Composer le texte classique du changement (sans préfixe inutile)
            now_str = datetime.datetime.now().strftime("%d/%m/%Y")
            changes_brief = ", ".join([c.replace("• ", "").replace("<b>", "").replace("</b>", "") for c in changes])
            comment_text = f"{now_str} {changes_brief}"

            # 3. Écrire chirurgicalement les modifications dans la BDD SQLite
            from infrastructure.sqlite_repository import SqliteRepository
            success, error_msg = SqliteRepository.update_member_in_db(
                original_order_ref=member.order_ref,
                original_last_name=member.user_last_name,
                original_first_name=member.user_first_name,
                updated_fields=updated_fields,
                comment_text=comment_text
            )

            if success:
                # Désactivation du téléversement individuel sur Google Drive (car cela ralentit trop l'IHM) (Nouveau !)
                # L'archivage et le téléversement complet seront exécutés à la fermeture de l'application.
                print(f"✅ [MODIFICATION] Modifications de {member.user_last_name.upper()} {member.user_first_name} enregistrées localement.")
                print("================================================================================\n")
                
                msg_text = (
                    "Les modifications ont été enregistrées avec succès dans la base de données locale !\n\n"
                    "⚡ Pour maximiser la rapidité de l'application, le téléversement vers Google Drive est mis en attente. "
                    "Il sera exécuté automatiquement lors de la fermeture de l'application."
                )

                QMessageBox.information(
                    self,
                    "Sauvegarde réussie localement",
                    msg_text
                )
                
                # 4. Actualiser l'objet courant en mémoire pour le mode lecture seule
                for k, val in updated_fields.items():
                    if k == "opt_assurance_base":
                        member.insurance.has_base = (val == "Oui")
                    elif k == "opt_assurance_base_plus":
                        member.insurance.has_base_plus = (val == "Oui")
                    elif k == "opt_assurance_base_plus_plus":
                        member.insurance.has_base_plus_plus = (val == "Oui")
                    elif k == "opt_assurance_ski":
                        member.insurance.has_ski = (val == "Oui")
                    elif k == "opt_assurance_vtt":
                        member.insurance.has_vtt = (val == "Oui")
                    elif k == "opt_assurance_trail":
                        member.insurance.has_trail = (val == "Oui")
                    else:
                        setattr(member, k, val)
                
                # Également forcer les champs dérivés si email/coordonnées ont été modifiés
                if "primary_email" in updated_fields:
                    member.primary_email = updated_fields["primary_email"]
                
                # Ajouter au commentaire de modifications visible
                new_comm = f"[{now_str}] {changes_brief}"
                if member.commentaires_correctif:
                    member.commentaires_correctif += f"\n{new_comm}"
                else:
                    member.commentaires_correctif = new_comm

                self.is_editing = False
                self.render_member_details()

                # 5. Émettre le signal pour recharger immédiatement le tableau parent !
                self.member_updated.emit()
            else:
                QMessageBox.critical(
                    self,
                    "Échec de la sauvegarde",
                    f"Une erreur est survenue lors de l'enregistrement de l'adhérent.\n\nDétails : {error_msg}\n\nVeuillez également vérifier que le fichier d'adhésions n'est pas déjà ouvert dans Microsoft Excel !"
                )
