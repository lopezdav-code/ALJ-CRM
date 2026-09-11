from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QPushButton, QHBoxLayout,
    QFrame, QProgressBar, QTextEdit, QMessageBox, QGroupBox,
    QCheckBox, QListWidget, QListWidgetItem
)
from PySide6.QtCore import Qt
from presentation.workers import SyncGmailContactsWorker

CHIP_STYLE = (
    'background-color:#EFF6FF;color:#1D4ED8;border-radius:10px;'
    'padding:3px 12px;font-weight:bold;font-size:12px;'
)


class GmailContactPage(QWidget):
    """
    Page de synchronisation des adhérents avec l'annuaire Google Contacts (API People).
    Les groupes proposés proviennent du planning des créneaux (BDD) : un groupe de
    créneau peut regrouper plusieurs tarifs HelloAsso. Des groupes virtuels
    (Adhérent, Compétition, Payeur) complètent la liste.
    """
    VIRTUAL_GROUPS = ["Adhérent", "Compétition", "Payeur"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.group_tarifs_map = {}  # Nom de groupe de créneau -> tarifs HelloAsso associés
        self.init_ui()
        self.load_available_groups()

    # ------------------------------------------------------------------
    # Construction de l'interface
    # ------------------------------------------------------------------
    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(16)

        # En-tête
        title = QLabel("📧 Synchronisation Google Contacts")
        title.setStyleSheet("font-size: 24px; font-weight: bold; color: #1E293B;")
        layout.addWidget(title)

        desc_lbl = QLabel(
            "Créez ou mettez à jour des listes de contacts dans votre messagerie Gmail. "
            "Les groupes proposés proviennent du planning des créneaux du club (un créneau peut "
            "regrouper plusieurs tarifs HelloAsso). Les contacts absents de votre annuaire Google "
            "sont créés automatiquement, puis rattachés aux listes cochées."
        )
        desc_lbl.setWordWrap(True)
        desc_lbl.setStyleSheet("color: #64748B; font-size: 13px;")
        layout.addWidget(desc_lbl)

        # ----------------- CARTE PRINCIPALE (2 colonnes) -----------------
        card = QFrame()
        card.setStyleSheet("""
            QFrame#cardGmail {
                background-color: #FFFFFF;
                border: 1px solid #E2E8F0;
                border-radius: 8px;
            }
        """)
        card.setObjectName("cardGmail")
        card_layout = QHBoxLayout(card)
        card_layout.setContentsMargins(20, 20, 20, 20)
        card_layout.setSpacing(24)

        card_layout.addLayout(self._build_left_column(), stretch=3)
        card_layout.addLayout(self._build_right_column(), stretch=2)

        layout.addWidget(card)

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
                max-height: 20px;
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
        self.log_area.setMinimumHeight(170)
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
        layout.addWidget(self.log_area, stretch=1)

    def _build_left_column(self):
        """Colonne gauche : sélection des groupes de créneaux (cases à cocher + compteurs)."""
        left_col = QVBoxLayout()
        left_col.setSpacing(10)

        header_row = QHBoxLayout()
        form_title = QLabel("👥 Groupes à exporter")
        form_title.setStyleSheet("font-size: 14px; font-weight: bold; color: #1E293B;")
        header_row.addWidget(form_title)
        header_row.addStretch()

        self.select_all_btn = QPushButton("Tout cocher")
        self.select_all_btn.setCursor(Qt.PointingHandCursor)
        self.select_none_btn = QPushButton("Tout décocher")
        self.select_none_btn.setCursor(Qt.PointingHandCursor)
        mini_btn_style = """
            QPushButton {
                background-color: #F1F5F9;
                color: #334155;
                border: 1px solid #E2E8F0;
                border-radius: 6px;
                padding: 4px 10px;
                font-size: 11px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #E2E8F0;
            }
        """
        self.select_all_btn.setStyleSheet(mini_btn_style)
        self.select_none_btn.setStyleSheet(mini_btn_style)
        self.select_all_btn.clicked.connect(self.check_all_groups)
        self.select_none_btn.clicked.connect(self.uncheck_all_groups)
        header_row.addWidget(self.select_all_btn)
        header_row.addWidget(self.select_none_btn)
        left_col.addLayout(header_row)

        self.group_list = QListWidget()
        self.group_list.setStyleSheet("""
            QListWidget {
                border: 1px solid #CBD5E1;
                border-radius: 6px;
                padding: 6px;
                font-size: 13px;
                background-color: #FFFFFF;
                color: #1E293B;
            }
            QListWidget::item {
                padding: 6px 4px;
            }
            QListWidget::item:hover {
                background-color: #F8FAFC;
            }
            QListWidget::item:checked {
                color: #1D4ED8;
                font-weight: bold;
            }
            QListWidget::indicator {
                width: 15px;
                height: 15px;
                border: 1px solid #CBD5E1;
                border-radius: 4px;
                background-color: #FFFFFF;
            }
            QListWidget::indicator:checked {
                background-color: #2563EB;
                border-color: #2563EB;
                image: url(none);
            }
        """)
        self.group_list.itemClicked.connect(self._on_item_clicked)
        self.group_list.itemChanged.connect(lambda _: self.update_preview())
        left_col.addWidget(self.group_list, stretch=1)

        hint_lbl = QLabel("Un groupe de créneau peut regrouper plusieurs tarifs HelloAsso.\nSurvolez un groupe pour voir ses créneaux et tarifs associés.")
        hint_lbl.setStyleSheet("color: #94A3B8; font-size: 11px; font-style: italic;")
        left_col.addWidget(hint_lbl)
        return left_col

    def _build_right_column(self):
        """Colonne droite : options des e-mails, prévisualisation des listes, bouton d'action."""
        right_col = QVBoxLayout()
        right_col.setSpacing(14)

        # Options des destinataires (Choix des e-mails à synchroniser)
        dest_group = QGroupBox("📩 Choix des adresses e-mails à ajouter aux contacts")
        dest_group.setStyleSheet("""
            QGroupBox {
                color: #1E293B;
                font-weight: bold;
                font-size: 12px;
                border: 1px solid #E2E8F0;
                border-radius: 6px;
                margin-top: 12px;
                padding: 12px 12px 8px 12px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
            }
        """)
        dest_layout = QVBoxLayout(dest_group)
        dest_layout.setSpacing(6)

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

        right_col.addWidget(dest_group)

        # Prévisualisation des listes Google qui seront créées / mises à jour
        preview_frame = QFrame()
        preview_frame.setStyleSheet("""
            QFrame {
                background-color: #F8FAFC;
                border: 1px solid #E2E8F0;
                border-radius: 6px;
            }
        """)
        preview_layout = QVBoxLayout(preview_frame)
        preview_layout.setContentsMargins(14, 10, 14, 12)
        preview_layout.setSpacing(8)

        preview_title = QLabel("🏷️ Listes Google Contacts concernées")
        preview_title.setStyleSheet("font-size: 12px; font-weight: bold; color: #334155; border: none;")
        preview_layout.addWidget(preview_title)

        self.preview_area = QLabel()
        self.preview_area.setWordWrap(True)
        self.preview_area.setTextFormat(Qt.RichText)
        self.preview_area.setStyleSheet("border: none; background: transparent;")
        preview_layout.addWidget(self.preview_area)

        right_col.addWidget(preview_frame)

        # Bouton d'action principal
        self.sync_btn = QPushButton("⚡  Synchroniser avec Google Contacts")
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
        right_col.addWidget(self.sync_btn)

        right_col.addStretch()
        return right_col

    # ------------------------------------------------------------------
    # Chargement des données (planning + compteurs)
    # ------------------------------------------------------------------
    def load_available_groups(self):
        """Charge les groupes de créneaux depuis la table planning de la BDD,
        avec compteurs d'adhérents calculés depuis les tarifs HelloAsso mappés."""
        try:
            from infrastructure.sqlite_repository import SqliteRepository
            from domain.constants import get_active_season
            SqliteRepository.setup_database()
            members = SqliteRepository.load_direct_data(season_filter=get_active_season())
            planning = SqliteRepository.load_planning_data(log_debug=False)

            # Agrégation des créneaux par nom de groupe unique (un groupe peut
            # posséder plusieurs créneaux horaires et plusieurs tarifs HelloAsso)
            creneaux = {}
            order = []
            for item in planning:
                g_name = str(item.get("groupe") or "").strip()
                if not g_name:
                    continue
                if g_name not in creneaux:
                    creneaux[g_name] = {"tarifs": [], "slots": []}
                    order.append(g_name)
                for t in item.get("helloasso_tarifs") or []:
                    t_str = str(t).strip()
                    if t_str and t_str not in creneaux[g_name]["tarifs"]:
                        creneaux[g_name]["tarifs"].append(t_str)
                creneaux[g_name]["slots"].append((
                    str(item.get("jour") or "").strip(),
                    str(item.get("horaires") or "").strip()
                ))

            self.group_tarifs_map = {g: c["tarifs"] for g, c in creneaux.items()}

            def tarif_of(m):
                return str(m.get("tarif_name") or "").strip().lower()

            n_total = len(members)
            n_comp = sum(1 for m in members if "compétition" in tarif_of(m))

            rows = [
                ("Adhérent", n_total, "Tous les adhérents de la saison active."),
                ("Compétition", n_comp, "Adhérents dont le tarif contient « Compétition »."),
                ("Payeur", n_total, "Tous les adhérents (utile pour ajouter les e-mails payeurs)."),
            ]
            for g_name in order:
                info = creneaux[g_name]
                targets = {t.strip().lower() for t in info["tarifs"]}
                count = sum(1 for m in members if tarif_of(m) in targets) if targets else 0
                slots_txt = " · ".join(f"{j} {h}".strip() for j, h in info["slots"] if j or h)
                tarifs_txt = ", ".join(info["tarifs"]) or "Aucun tarif HelloAsso configuré ⚠️"
                tooltip = g_name
                if slots_txt:
                    tooltip += f"\nCréneau(x) : {slots_txt}"
                tooltip += f"\nTarifs HelloAsso : {tarifs_txt}"
                rows.append((g_name, count, tooltip))

            self.group_list.blockSignals(True)
            self.group_list.clear()
            for name, count, tooltip in rows:
                item = QListWidgetItem(f"{name}   ({count})")
                item.setData(Qt.UserRole, name)
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Unchecked)
                item.setToolTip(tooltip)
                self.group_list.addItem(item)
            self.group_list.blockSignals(False)

            self.update_preview()
        except Exception as e:
            self.log_area.append(f"❌ [ERREUR] Impossible de charger les groupes depuis SQLite : {e}")

    # ------------------------------------------------------------------
    # Interactions UI
    # ------------------------------------------------------------------
    def _on_item_clicked(self, item):
        """Un simple clic sur la ligne bascule la case à cocher (UX multi-sélection)."""
        item.setCheckState(Qt.Unchecked if item.checkState() == Qt.Checked else Qt.Checked)

    def get_checked_groups(self):
        """Retourne les noms de groupes cochés."""
        return [
            self.group_list.item(i).data(Qt.UserRole)
            for i in range(self.group_list.count())
            if self.group_list.item(i).checkState() == Qt.Checked
        ]

    def check_all_groups(self):
        self.group_list.blockSignals(True)
        for i in range(self.group_list.count()):
            self.group_list.item(i).setCheckState(Qt.Checked)
        self.group_list.blockSignals(False)
        self.update_preview()

    def uncheck_all_groups(self):
        self.group_list.blockSignals(True)
        for i in range(self.group_list.count()):
            self.group_list.item(i).setCheckState(Qt.Unchecked)
        self.group_list.blockSignals(False)
        self.update_preview()

    def update_preview(self):
        """Affiche les badges des listes Google qui seront créées/mises à jour."""
        from domain.constants import get_active_season
        season = get_active_season()
        year = season.split("-")[1] if "-" in season else "2027"

        checked = self.get_checked_groups()
        if not checked:
            self.preview_area.setText(
                '<span style="color:#94A3B8;font-size:12px;font-style:italic;">'
                "Cochez des groupes pour prévisualiser les listes qui seront créées dans Google Contacts…"
                "</span>"
            )
            return

        chips = "<br>".join(
            f'<span style="{CHIP_STYLE}">&nbsp;{year} {g}&nbsp;</span>'
            for g in checked
        )
        self.preview_area.setText(chips)

    def set_ui_enabled(self, enabled: bool):
        """Active ou désactive les composants graphiques."""
        self.group_list.setEnabled(enabled)
        self.select_all_btn.setEnabled(enabled)
        self.select_none_btn.setEnabled(enabled)
        self.use_primary_email_cb.setEnabled(enabled)
        self.use_secondary_email_cb.setEnabled(enabled)
        self.use_payer_email_cb.setEnabled(enabled)
        self.sync_btn.setEnabled(enabled)

    # ------------------------------------------------------------------
    # Workflow de synchronisation
    # ------------------------------------------------------------------
    def start_sync_workflow(self):
        """Déclenche le worker asynchrone pour synchroniser les listes cochées."""
        checked_groups = self.get_checked_groups()
        if not checked_groups:
            QMessageBox.warning(
                self,
                "Aucun groupe sélectionné",
                "Veuillez cocher au moins un groupe d'adhérents à exporter avant de lancer le traitement."
            )
            return

        tarifs_str = "\n- ".join(checked_groups)
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

        self.worker = SyncGmailContactsWorker(
            selected_tariffs=checked_groups,
            use_primary_email=self.use_primary_email_cb.isChecked(),
            use_secondary_email=self.use_secondary_email_cb.isChecked(),
            use_payer_email=self.use_payer_email_cb.isChecked(),
            group_tarifs_map=dict(self.group_tarifs_map)
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
