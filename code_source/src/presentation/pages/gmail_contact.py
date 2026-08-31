import os
import glob
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QPushButton, QHBoxLayout, 
    QFrame, QProgressBar, QTextEdit, QMessageBox, QComboBox, QLineEdit,
    QAbstractItemView
)
from PySide6.QtCore import Qt
from presentation.workers import SyncGmailContactsWorker
from paths import ROOT_DIR

class GmailContactPage(QWidget):
    """
    Page de synchronisation des adhérents avec l'annuaire Google Contacts (API People).
    Permet d'organiser les membres par groupes de contacts Gmail (ex: Loisir Collège 2027).
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()
        self.load_available_groups()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(20)

        # En-tête
        title = QLabel("📧 Synchronisation Google Contacts")
        title.setStyleSheet("font-size: 24px; font-weight: bold; color: #1E293B;")
        layout.addWidget(title)

        # Description
        desc_lbl = QLabel(
            "Créez ou mettez à jour des groupes de contacts dans votre messagerie Gmail. "
            "Le système vérifie si les contacts existent déjà dans votre annuaire Google par adresse e-mail. "
            "S'ils sont absents, ils sont créés automatiquement, puis rattachés au groupe ciblé."
        )
        desc_lbl.setStyleSheet("color: #64748B; font-size: 13px; margin-bottom: 5px;")
        layout.addWidget(desc_lbl)

        # ----------------- SECTION CONFIGURATION DU GROUPE -----------------
        form_frame = QFrame()
        form_frame.setStyleSheet("""
            QFrame {
                background-color: #FFFFFF;
                border: 1px solid #E2E8F0;
                border-radius: 8px;
                padding: 20px;
            }
        """)
        form_layout = QVBoxLayout(form_frame)
        form_layout.setSpacing(15)

        form_title = QLabel("👥 Configurer la liste de contacts")
        form_title.setStyleSheet("font-size: 14px; font-weight: bold; color: #1E293B; margin-bottom: 5px;")
        form_layout.addWidget(form_title)

        # Sélection du groupe HelloAsso (Désormais Multi-Sélection !)
        combo_layout = QVBoxLayout()
        combo_lbl = QLabel("Sélectionner les groupes d'adhérents à fusionner :")
        combo_lbl.setStyleSheet("font-size: 13px; font-weight: 500; color: #334155;")
        combo_layout.addWidget(combo_lbl)
        
        from PySide6.QtWidgets import QListWidget, QListWidgetItem
        self.group_list = QListWidget()
        self.group_list.setSelectionMode(QAbstractItemView.MultiSelection)
        self.group_list.setStyleSheet("""
            QListWidget {
                border: 1px solid #CBD5E1;
                border-radius: 6px;
                padding: 6px;
                font-size: 13px;
                background-color: #FFFFFF;
                color: #1E293B;
                min-width: 250px;
                max-height: 120px;
            }
            QListWidget::item:selected {
                background-color: #E0E7FF;
                color: #1D4ED8;
                font-weight: bold;
                border-radius: 4px;
            }
        """)
        self.group_list.itemSelectionChanged.connect(self.update_group_name_preview)
        combo_layout.addWidget(self.group_list)
        form_layout.addLayout(combo_layout)

        # Prévisualisation du nom du groupe dans Google Contacts
        preview_layout = QHBoxLayout()
        preview_lbl = QLabel("Nom de la liste créée/mise à jour dans Google Contacts :")
        preview_lbl.setStyleSheet("font-size: 13px; font-weight: 500; color: #334155;")
        preview_layout.addWidget(preview_lbl)

        self.group_name_preview = QLineEdit()
        self.group_name_preview.setReadOnly(True)
        self.group_name_preview.setPlaceholderText("Les noms des groupes Google Contacts apparaîtront ici...")
        self.group_name_preview.setStyleSheet("""
            QLineEdit {
                border: 1px solid #E2E8F0;
                border-radius: 6px;
                padding: 6px 12px;
                font-size: 13px;
                background-color: #F8FAFC;
                color: #2563EB;
                font-weight: bold;
                min-width: 250px;
            }
        """)
        preview_layout.addWidget(self.group_name_preview)
        preview_layout.addStretch()
        form_layout.addLayout(preview_layout)

        # Options des destinataires (Choix des e-mails à synchroniser)
        from PySide6.QtWidgets import QGroupBox, QCheckBox
        dest_group = QGroupBox("📩 Choix des adresses e-mails à ajouter aux contacts")
        dest_group.setStyleSheet("""
            QGroupBox {
                color: #1E293B;
                font-weight: bold;
                font-size: 12px;
                border: 1px solid #E2E8F0;
                border-radius: 6px;
                margin-top: 15px;
                padding-top: 15px;
            }
        """)
        dest_layout = QVBoxLayout(dest_group)
        dest_layout.setSpacing(5)
        
        self.use_primary_email_cb = QCheckBox("Synchroniser l'E-mail Principal (Fiche Adhérent)")
        self.use_primary_email_cb.setChecked(True)
        self.use_primary_email_cb.setStyleSheet("color: #475569; font-size: 12px; font-weight: 500;")
        dest_layout.addWidget(self.use_primary_email_cb)

        self.use_secondary_email_cb = QCheckBox("Synchroniser le Deuxième E-mail (Fiche Adhérent)")
        self.use_secondary_email_cb.setChecked(True)
        self.use_secondary_email_cb.setStyleSheet("color: #475569; font-size: 12px; font-weight: 500;")
        dest_layout.addWidget(self.use_secondary_email_cb)

        self.use_payer_email_cb = QCheckBox("Synchroniser l'E-mail du Payeur (Acheteur HelloAsso)")
        self.use_payer_email_cb.setChecked(False)
        self.use_payer_email_cb.setStyleSheet("color: #475569; font-size: 12px; font-weight: 500;")
        dest_layout.addWidget(self.use_payer_email_cb)
        
        form_layout.addWidget(dest_group)

        # Bouton d'action principal
        action_layout = QHBoxLayout()
        self.sync_btn = QPushButton("⚡ Synchroniser avec Google Contacts")
        self.sync_btn.setCursor(Qt.PointingHandCursor)
        self.sync_btn.setStyleSheet("""
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
        self.sync_btn.clicked.connect(self.start_sync_workflow)
        action_layout.addWidget(self.sync_btn)
        action_layout.addStretch()
        form_layout.addLayout(action_layout)

        layout.addWidget(form_frame)

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

        # ----------------- CONSOLE DE LOGS -----------------
        log_title = QLabel("📝 Console de suivi de synchronisation")
        log_title.setStyleSheet("font-size: 13px; font-weight: bold; color: #334155;")
        layout.addWidget(log_title)

        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setPlaceholderText("Les journaux d'exportation de contacts s'afficheront ici en temps réel...")
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

    def load_available_groups(self):
        """Récupère dynamiquement tous les tarifs uniques de la base locale pour la saison active (2026-2027)."""
        try:
            from infrastructure.sqlite_repository import SqliteRepository
            SqliteRepository.setup_database()
            all_members = SqliteRepository.load_direct_data(season_filter="2026-2027")
            tarifs = sorted(list(set([str(m.get("tarif_name", "")).strip() for m in all_members if m.get("tarif_name")])))
            
            # Ajouter les groupes virtuels récapitulatifs au début de la liste
            virtual_groups = ["Adhérent", "Compétition", "Payeur"]
            # Éviter de dupliquer si un groupe de base s'appelle déjà comme un groupe virtuel
            tarifs = [t for t in tarifs if t not in virtual_groups]
            final_groups = virtual_groups + tarifs
            
            self.group_list.blockSignals(True)
            self.group_list.clear()
            self.group_list.addItems(final_groups)
            self.group_list.blockSignals(False)
            
            self.update_group_name_preview()
        except Exception as e:
            self.log_area.append(f"❌ [ERREUR] Impossible de charger les groupes depuis SQLite : {e}")

    def update_group_name_preview(self):
        """Met à jour le champ de texte prévisualisant le nom de la liste dans Gmail."""
        selected_items = self.group_list.selectedItems()
        if not selected_items:
            self.group_name_preview.setText("")
            return
            
        from domain.constants import get_active_season
        season = get_active_season()
        year = season.split("-")[1] if "-" in season else "2027"
        
        if len(selected_items) == 1:
            # S'il n'y a qu'un groupe sélectionné, on prend son nom
            self.group_name_preview.setText(f"{year} {selected_items[0].text().strip()}")
        else:
            # S'il y a plusieurs groupes sélectionnés, on propose un nom générique modifiable
            self.group_name_preview.setText(f"{year} Sélection Multiple")

    def set_ui_enabled(self, enabled: bool):
        """Active ou désactive les composants graphiques."""
        self.group_list.setEnabled(enabled)
        self.group_name_preview.setEnabled(enabled)
        self.sync_btn.setEnabled(enabled)

    def start_sync_workflow(self):
        """Déclenche le worker asynchrone pour synchroniser la liste."""
        # Récupérer tous les tarifs sélectionnés
        selected_items = self.group_list.selectedItems()
        if not selected_items:
            QMessageBox.warning(
                self,
                "Aucun groupe sélectionné",
                "Veuillez sélectionner au moins un groupe d'adhérents à exporter avant de lancer le traitement."
            )
            return
            
        selected_tariffs = [item.text().strip() for item in selected_items]

        # Demander confirmation
        tarifs_str = "\n- ".join(selected_tariffs)
        reply = QMessageBox.question(
            self,
            "Synchronisation Google Contacts",
            f"Voulez-vous synchroniser les adhérents des groupes suivants :\n\n- {tarifs_str}\n\n"
            f"L'application va traiter chaque groupe un par un et créer les listes correspondantes "
            f"dans votre compte Gmail.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes
        )
        if reply == QMessageBox.No:
            return

        self.set_ui_enabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.log_area.clear()

        self.log_area.append("🚀 Lancement de la synchronisation des contacts Gmail...")

        # Lancer le worker asynchrone
        self.worker = SyncGmailContactsWorker(
            selected_tariffs=selected_tariffs,
            use_primary_email=self.use_primary_email_cb.isChecked(),
            use_secondary_email=self.use_secondary_email_cb.isChecked(),
            use_payer_email=self.use_payer_email_cb.isChecked()
        )
        self.worker.progress.connect(self.on_progress)
        self.worker.finished.connect(self.on_finished)
        self.worker.start()

    def on_progress(self, message: str, percent: int):
        """Met à jour la barre de progression et le journal."""
        self.progress_bar.setValue(percent)
        self.log_area.append(message)

    def on_finished(self, success: bool, stats: dict):
        """Affiche le récapitulatif de fin de traitement."""
        self.set_ui_enabled(True)
        self.progress_bar.setVisible(False)

        if success:
            groups_str = ", ".join(stats.get('groups_processed', []))
            self.log_area.append(f"\n🎉 [SUCCÈS] Synchronisation terminée avec succès pour les groupes : {groups_str}")
            self.log_area.append(f"   • Total adhérents analysés : {stats['total_members']}")
            self.log_area.append(f"   • Contacts existants trouvés : {stats['contacts_found']}")
            self.log_area.append(f"   • Nouveaux contacts créés : {stats['contacts_created']}")
            self.log_area.append(f"   • Contacts associés dans les groupes : {stats['added_to_group']}")
            
            QMessageBox.information(
                self,
                "Synchronisation Contacts",
                f"L'exportation vers Google Contacts est terminée !\n\n"
                f"Groupes synchronisés :\n{groups_str}\n\n"
                f"- Contacts analysés : {stats['total_members']}\n"
                f"- Contacts existants : {stats['contacts_found']}\n"
                f"- Nouveaux contacts créés : {stats['contacts_created']}\n"
                f"- Liaisons aux groupes : {stats['added_to_group']}"
            )
        else:
            errors = "\n".join(stats.get("errors", ["Une erreur inconnue est survenue."]))
            self.log_area.append(f"\n❌ [ERREUR] Échec de la synchronisation :\n{errors}")
            QMessageBox.critical(
                self,
                "Échec de Synchronisation",
                f"La synchronisation des contacts avec Google a échoué :\n\n{errors}"
            )
