from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QFrame, QScrollArea

class HelpPage(QWidget):
    """
    Page d'aide et de documentation décrivant les 3 fichiers d'entrée gérés par l'application.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()

    def init_ui(self):
        # Utilisation d'un Scroll Area pour s'assurer que le contenu s'adapte à toutes les résolutions d'écran
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background-color: #F8FAFC; }")
        
        scroll_content = QWidget()
        scroll_content.setObjectName("ScrollContent")
        scroll_content.setStyleSheet("#ScrollContent { background-color: #F8FAFC; }")
        
        layout = QVBoxLayout(scroll_content)
        layout.setContentsMargins(30, 25, 30, 30)
        layout.setSpacing(15)

        # En-tête de la page d'aide
        title = QLabel("❓ Centre d'Aide & Documentation")
        title.setStyleSheet("font-size: 24px; font-weight: bold; color: #163A5F;")
        layout.addWidget(title)

        subtitle = QLabel("Guide de référence concernant les 3 fichiers d'entrée majeurs gérés par ALJ Escalade Manager.")
        subtitle.setStyleSheet("font-size: 13px; color: #64748B; margin-bottom: 10px;")
        layout.addWidget(subtitle)

        # CARD PRINCIPALE : Les 3 fichiers d'entrée
        card = QFrame()
        card.setStyleSheet("""
            QFrame {
                background-color: #FFFFFF;
                border: 1px solid #E2E8F0;
                border-radius: 8px;
                padding: 20px;
            }
        """)
        card_layout = QVBoxLayout(card)
        card_layout.setSpacing(20)

        card_title = QLabel("📋 Les 3 Fichiers d'Entrée Gérés par le Système")
        card_title.setStyleSheet("font-size: 16px; font-weight: bold; color: #1E293B; border-bottom: 2px solid #CBD5E1; padding-bottom: 8px;")
        card_layout.addWidget(card_title)

        # 1. Fichier FFME
        f1_layout = QVBoxLayout()
        f1_layout.setSpacing(4)
        f1_title = QLabel("📁 1. Fichier National des Licenciés FFME")
        f1_title.setStyleSheet("font-size: 14px; font-weight: bold; color: #2563EB;")
        f1_desc = QLabel(
            "<b>Format :</b> <code>Export_Licencies_david_lopez_*.xlsx</code><br>"
            "<b>Provenance :</b> Téléchargé depuis l'espace club de l'intranet fédéral FFME.<br>"
            "<b>Rôle :</b> Ce fichier est lu par l'application pour extraire de façon automatisée les informations fédérales "
            "officielles des adhérents : <i>numéros de licence, couleurs de passeports d'escalade (niveaux), et diplômes d'encadrement</i>."
        )
        f1_desc.setWordWrap(True)
        f1_desc.setStyleSheet("font-size: 12px; color: #475569; line-height: 1.5;")
        f1_layout.addWidget(f1_title)
        f1_layout.addWidget(f1_desc)
        card_layout.addLayout(f1_layout)

        # Séparateur pointillé
        sep1 = QFrame()
        sep1.setFrameShape(QFrame.HLine)
        sep1.setStyleSheet("color: #E2E8F0; background-color: #E2E8F0; max-height: 1px; border: none;")
        card_layout.addWidget(sep1)

        # 2. Fichier Autonomes
        f2_layout = QVBoxLayout()
        f2_layout.setSpacing(4)
        f2_title = QLabel("📁 2. Fichier de Suivi des Grimpeurs Autonomes")
        f2_title.setStyleSheet("font-size: 14px; font-weight: bold; color: #2563EB;")
        f2_desc = QLabel(
            "<b>Format :</b> <code>Autonomes_*.xlsx</code> (ex : <code>Autonomes_2026-06-30.xlsx</code>)<br>"
            "<b>Provenance :</b> Registre de suivi interne rédigé par les initiateurs et le bureau de l'ALJ Escalade.<br>"
            "<b>Rôle :</b> Lu par le module d'import pour associer à chaque adhérent ses validations d'autonomie interne "
            "au club : <i>l'Autonomie en Bloc</i> ainsi que l'obtention du précieux <i>Badge rouge de Difficulté (grimpe en tête)</i>."
        )
        f2_desc.setWordWrap(True)
        f2_desc.setStyleSheet("font-size: 12px; color: #475569; line-height: 1.5;")
        f2_layout.addWidget(f2_title)
        f2_layout.addWidget(f2_desc)
        card_layout.addLayout(f2_layout)

        # Séparateur pointillé
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.HLine)
        sep2.setStyleSheet("color: #E2E8F0; background-color: #E2E8F0; max-height: 1px; border: none;")
        card_layout.addWidget(sep2)

        # 3. Base d'Adhérents Maîtresse (HelloAsso / Drive)
        f3_layout = QVBoxLayout()
        f3_layout.setSpacing(4)
        f3_title = QLabel("📁 3. Base de Référence des Adhésions du Club")
        f3_title.setStyleSheet("font-size: 14px; font-weight: bold; color: #2563EB;")
        f3_desc = QLabel(
            "<b>Format :</b> <code>Adhésions escalade-{saison}-amicale-laique-de-jonage-DRIVE_TEMP.xlsx</code> ou <code>HelloAsso_Admin_*.xlsx</code><br>"
            "<b>Provenance :</b> Téléchargé automatiquement depuis l'API HelloAsso ou récupéré de façon partagée sur Google Drive.<br>"
            "<b>Rôle :</b> C'est le fichier pivot central (base de données de l'application). Il recense l'intégralité des "
            "<i>coordonnées des adhérents, tarifs réglés, justificatifs de paiement et statuts de commandes</i>. Il est synchronisé "
            "en temps réel avec HelloAsso et sauvegardé sur Google Drive."
        )
        f3_desc.setWordWrap(True)
        f3_desc.setStyleSheet("font-size: 12px; color: #475569; line-height: 1.5;")
        f3_layout.addWidget(f3_title)
        f3_layout.addWidget(f3_desc)
        card_layout.addLayout(f3_layout)

        layout.addWidget(card)

        # BLOC 2 : Fonctionnement du Pipeline
        pipeline_card = QFrame()
        pipeline_card.setStyleSheet("""
            QFrame {
                background-color: #F0FDF4;
                border: 1px solid #BBF7D0;
                border-radius: 8px;
                padding: 15px;
            }
        """)
        pipeline_layout = QVBoxLayout(pipeline_card)
        pipeline_layout.setSpacing(10)

        pip_title = QLabel("💡 Rappel du Cycle de Synchronisation")
        pip_title.setStyleSheet("font-size: 14px; font-weight: bold; color: #166534;")
        pipeline_layout.addWidget(pip_title)

        pip_desc = QLabel(
            "<b>1. Chargement initial :</b> Au démarrage, l'application lit de façon asynchrone le fichier n°3 de référence local.<br>"
            "<b>2. Rapprochement Web :</b> L'action de synchronisation HelloAsso rapatrie automatiquement les nouvelles inscriptions et les fusionne sans perte avec les correctifs manuels du club.<br>"
            "<b>3. Sauvegarde automatique :</b> Le fichier consolidé est réimporté sur Google Drive de façon sécurisée.<br>"
            "<b>4. Exploitation :</b> Vous pouvez ensuite générer les fiches de cours (Excel), les fiches d'urgences, les attestations de paiement PDF, ou mener vos campagnes de communication par courriel."
        )
        pip_desc.setWordWrap(True)
        pip_desc.setStyleSheet("font-size: 12px; color: #14532D; line-height: 1.6;")
        pipeline_layout.addWidget(pip_desc)

        layout.addWidget(pipeline_card)
        layout.addStretch()

        scroll.setWidget(scroll_content)
        main_layout.addWidget(scroll)
