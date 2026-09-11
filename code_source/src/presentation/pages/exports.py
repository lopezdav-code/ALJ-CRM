import os
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QPushButton, QHBoxLayout, 
    QFrame, QProgressBar, QTextEdit, QDialog, QMessageBox,
    QListWidget, QListWidgetItem, QDateEdit, QCheckBox, QApplication
)
from PySide6.QtCore import Qt, QDate
from PySide6.QtGui import QColor, QFont
from presentation.workers import ExportWorker
from paths import CODE_ROOT

class ExportsPage(QWidget):
    """
    Page d'exports administratifs asynchrones (FFME, listes de présence, listes d'urgence) (Lot 5).
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(20)

        # En-tête
        title = QLabel("Exports Administratifs")
        title.setStyleSheet("font-size: 24px; font-weight: bold; color: #1E293B;")
        layout.addWidget(title)

        # Description
        desc_lbl = QLabel("Générez et compilez les différents livrables administratifs du club en arrière-plan.")
        desc_lbl.setStyleSheet("color: #64748B; font-size: 13px; margin-bottom: 10px;")
        layout.addWidget(desc_lbl)

        # Conteneur des boutons d'exports
        buttons_frame = QFrame()
        buttons_frame.setStyleSheet("""
            QFrame {
                background-color: #FFFFFF;
                border: 1px solid #E2E8F0;
                border-radius: 8px;
                padding: 15px;
            }
        """)
        buttons_layout = QVBoxLayout(buttons_frame)
        buttons_layout.setSpacing(12)

        # 1. Export FFME CSV
        ffme_layout = QHBoxLayout()
        self.ffme_btn = QPushButton("📊 Exporter le fichier FFME (CSV)")
        self.style_button(self.ffme_btn, "#2563EB", "#1D4ED8")
        self.ffme_btn.clicked.connect(lambda: self.run_export("ffme"))
        ffme_layout.addWidget(self.ffme_btn)
        
        # Lien externe vers le portail fédéral FFME (Nouveau !)
        ffme_link = QLabel('<a href="https://myffme.fr/federal/gestion-des-licences/saisir-les-licences-via-csv/2027" style="color: #2563EB; font-weight: bold; text-decoration: underline;">🌐 Aller sur le portail d\'import FFME</a>')
        ffme_link.setOpenExternalLinks(True)
        ffme_link.setCursor(Qt.PointingHandCursor)
        ffme_link.setStyleSheet("font-size: 12px; margin-left: 15px;")
        ffme_layout.addWidget(ffme_link)
        
        ffme_layout.addStretch()
        buttons_layout.addLayout(ffme_layout)

        # Sous-label pour afficher les statistiques détaillées de l'export FFME (CSV)
        self.ffme_stats_lbl = QLabel("Chargement des statistiques de l'export FFME...")
        self.ffme_stats_lbl.setWordWrap(True)
        self.ffme_stats_lbl.setStyleSheet("""
            QLabel {
                color: #475569;
                font-size: 11px;
                margin-left: 10px;
                margin-top: -4px;
                margin-bottom: 8px;
                background-color: #F8FAFC;
                padding: 8px 12px;
                border: 1px solid #E2E8F0;
                border-radius: 4px;
            }
        """)
        buttons_layout.addWidget(self.ffme_stats_lbl)

        # 2. Fiches de présence (2 exports distincts, options préconfigurées)
        presence_layout = QHBoxLayout()
        self.presence_autonome_btn = QPushButton("🧗 Fiche présence autonome")
        self.style_button(self.presence_autonome_btn, "#0EA5E9", "#0284C7")
        self.presence_autonome_btn.clicked.connect(lambda: self.run_presence_export("autonome"))
        presence_layout.addWidget(self.presence_autonome_btn)

        self.presence_cours_btn = QPushButton("📚 Fiche présence des cours")
        self.style_button(self.presence_cours_btn, "#6366F1", "#4F46E5")
        self.presence_cours_btn.clicked.connect(lambda: self.run_presence_export("cours"))
        presence_layout.addWidget(self.presence_cours_btn)
        presence_layout.addStretch()
        buttons_layout.addLayout(presence_layout)

        # 3. Contacts d'urgence
        urgency_layout = QHBoxLayout()
        self.urgency_btn = QPushButton("📞 Générer le cahier des contacts d'urgence (A4)")
        self.style_button(self.urgency_btn, "#EA580C", "#C2410C")
        self.urgency_btn.clicked.connect(lambda: self.run_export("urgency"))
        urgency_layout.addWidget(self.urgency_btn)
        urgency_layout.addStretch()
        buttons_layout.addLayout(urgency_layout)

        # 4. Ouverture du dossier de modèles
        template_layout = QHBoxLayout()
        self.template_folder_btn = QPushButton("📂 Ouvrir dossier Modèles")
        self.style_secondary_button(self.template_folder_btn, "#475569", "#334155")
        self.template_folder_btn.clicked.connect(self.open_template_folder)
        template_layout.addWidget(self.template_folder_btn)
        template_layout.addStretch()
        buttons_layout.addLayout(template_layout)

        # 5. Export Anciens Adhérents non réinscrits (Nouveau !)
        anciens_layout = QHBoxLayout()
        self.anciens_btn = QPushButton("📥 Exporter les anciens adhérents non réinscrits (Excel)")
        self.style_button(self.anciens_btn, "#8B5CF6", "#7C3AED") # Jolie couleur violette pour le CRM
        self.anciens_btn.clicked.connect(lambda: self.run_export("anciens"))
        anciens_layout.addWidget(self.anciens_btn)
        anciens_layout.addStretch()
        buttons_layout.addLayout(anciens_layout)

        # 6. Import/Export MyCompet (Nouveau !)
        mycompet_layout = QHBoxLayout()
        self.mycompet_btn = QPushButton("🏆 Récupérer les classements MyCompet (Excel)")
        self.style_button(self.mycompet_btn, "#D97706", "#B45309") # Belle couleur ambre/dorée pour la compétition
        self.mycompet_btn.clicked.connect(lambda: self.run_export("mycompet"))
        mycompet_layout.addWidget(self.mycompet_btn)
        mycompet_layout.addStretch()
        buttons_layout.addLayout(mycompet_layout)

        layout.addWidget(buttons_frame)

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
        layout.addWidget(self.progress_bar)

        # Console de logs
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setPlaceholderText("Les traces d'exécution de vos exports s'afficheront ici en direct...")
        self.log_area.setStyleSheet("""
            QTextEdit {
                background-color: #1E293B;
                color: #FBBF24;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 12px;
                border-radius: 8px;
                padding: 10px;
            }
        """)
        layout.addWidget(self.log_area)

    def style_button(self, btn: QPushButton, bg_color: str, hover_color: str):
        """Applique une charte visuelle standardisée et dynamique sur les boutons d'exports (avec largeur fixe contrôlée)."""
        btn.setCursor(Qt.PointingHandCursor)
        btn.setFixedWidth(380) # Largeur fixe pour éviter l'étirement horizontal !
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {bg_color};
                color: #FFFFFF;
                border: none;
                border-radius: 6px;
                padding: 10px 20px;
                font-size: 13px;
                font-weight: bold;
                text-align: left;
            }}
            QPushButton:hover {{
                background-color: {hover_color};
            }}
            QPushButton:disabled {{
                background-color: #94A3B8;
            }}
        """)

    def style_secondary_button(self, btn: QPushButton, bg_color: str, hover_color: str):
        """Applique une charte visuelle standardisée pour un bouton secondaire d'export (plus compact)."""
        btn.setCursor(Qt.PointingHandCursor)
        btn.setFixedWidth(200) # Largeur fixe plus petite que le bouton principal
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {bg_color};
                color: #FFFFFF;
                border: none;
                border-radius: 6px;
                padding: 10px 15px;
                font-size: 13px;
                font-weight: bold;
                text-align: center;
            }}
            QPushButton:hover {{
                background-color: {hover_color};
            }}
            QPushButton:disabled {{
                background-color: #CBD5E1;
            }}
        """)

    def set_buttons_enabled(self, enabled: bool):
        """Active ou désactive l'ensemble des boutons d'exports pour prévenir des concurrences."""
        self.ffme_btn.setEnabled(enabled)
        self.presence_autonome_btn.setEnabled(enabled)
        self.presence_cours_btn.setEnabled(enabled)
        self.urgency_btn.setEnabled(enabled)
        self.template_folder_btn.setEnabled(enabled)
        self.anciens_btn.setEnabled(enabled)  # Nouveau !
        self.mycompet_btn.setEnabled(enabled)  # Nouveau !

    def showEvent(self, event):
        """Rafraîchit les statistiques d'export FFME automatiquement lorsque l'onglet est affiché."""
        super().showEvent(event)
        self.update_ffme_stats()

    def update_ffme_stats(self):
        """Calcule et affiche les statistiques de l'export FFME CSV (Lot 5)."""
        try:
            from infrastructure.sqlite_repository import SqliteRepository
            import datetime
            from create_excel import parse_date_to_datetime
            
            participants = SqliteRepository.load_direct_data(season_filter="2026-2027")
            
            produced_count = 0
            ignored_count = 0
            termine_count = 0
            
            for p in participants:
                tarif_name = str(p.get("tarif_name") or "").lower()
                amount = p.get("amount", 0.0)
                status = str(p.get("status") or "").lower()
                commentaires = str(p.get("commentaires_correctif") or "").lower()
                is_manual = "ajout manuel" in commentaires
                
                # 1. Ignoré (liste d'attente, montant nul (sauf les ajouts manuels), annulé/Canceled)
                if "attente" in tarif_name or (amount == 0.0 and not is_manual) or "annul" in status or "cancel" in status:
                    ignored_count += 1
                    continue
                    
                # 2. Terminé
                if "termin" in status:
                    termine_count += 1
                    continue
                    
                # 3. Date de naissance invalide
                dob_val = p.get("champ_Date de naissance de l'adhérent") or ""
                dob_date = None
                if isinstance(dob_val, (datetime.datetime, datetime.date)):
                    dob_date = dob_val
                else:
                    dob_str = str(dob_val).strip()
                    parsed_dt = parse_date_to_datetime(dob_str)
                    if isinstance(parsed_dt, (datetime.datetime, datetime.date)):
                        dob_date = parsed_dt
                
                if not dob_date or (isinstance(dob_date, (datetime.datetime, datetime.date)) and dob_date >= datetime.datetime.now()):
                    ignored_count += 1
                    continue
                    
                produced_count += 1
                
            estimated_total = produced_count + termine_count
            
            stats_text = (
                f"📋 <b>Statistiques de l'export FFME :</b> "
                f"Lignes à produire : <span style='color: #10B981; font-weight: bold;'>{produced_count}</span> | "
                f"Lignes ignorées (attente/annulées/0€) : <span style='color: #EA580C; font-weight: bold;'>{ignored_count}</span> | "
                f"Membres déjà 'Terminé' : <span style='color: #2563EB; font-weight: bold;'>{termine_count}</span> | "
                f"Adhérents estimés (avec 'Terminé') : <span style='color: #8B5CF6; font-weight: bold;'>{estimated_total}</span>"
            )
            self.ffme_stats_lbl.setText(stats_text)
        except Exception as e:
            self.ffme_stats_lbl.setText(f"⚠️ Impossible de charger les statistiques de l'export FFME : {e}")

    def open_template_folder(self):
        """Ouvre le dossier contenant les modèles de documents dans l'explorateur Windows."""
        import os
        template_dir = os.path.join(CODE_ROOT, "doc", "template")
        if os.path.exists(template_dir):
            try:
                os.startfile(template_dir)
            except Exception as e:
                self.log_area.append(f"❌ [ERREUR] Impossible d'ouvrir le dossier du template : {e}")
        else:
            self.log_area.append(f"❌ [ERREUR] Le dossier du template n'existe pas : {template_dir}")

    def _load_presence_creneaux(self):
        """Charge les groupes de créneaux depuis la table planning de la BDD.
        Chaque créneau regroupe un ou plusieurs tarifs HelloAsso. Retourne une liste
        de dicts {groupe, tarifs, slots} triée par nom de groupe."""
        from infrastructure.sqlite_repository import SqliteRepository
        SqliteRepository.setup_database()
        planning = SqliteRepository.load_planning_data(log_debug=False)

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

        return [
            {"groupe": g, "tarifs": creneaux[g]["tarifs"], "slots": creneaux[g]["slots"]}
            for g in sorted(order)
        ]

    def _build_cours_hierarchy(self, creneaux):
        """Organise les créneaux de cours en rubriques hiérarchiques pour le dialogue :
        Collège, Enfants (sous-rubriques par tranche d'âge 2016-2018 / 2019-2020),
        Perfectionnement, Compétition. Les créneaux hors rubrique restent en liste plate.
        Les libellés affichés sont raccourcis (le nom de la rubrique, redondant, est retiré).
        Retourne une liste de (kind, libellé, nom_brut) où kind ∈ {'section', 'sub-section', 'group'}."""
        import re
        from domain.utils import normalize_string

        def accent_class_pattern(word):
            """Motif regex insensible aux accents (é/è/ê, à, î...) pour découper les libellés."""
            tr = str.maketrans({
                "e": "[eèéêë]", "a": "[aàâä]", "i": "[iîï]", "o": "[oôö]",
                "u": "[uùûü]", "c": "[cç]", "y": "[yÿ]",
            })
            return word.translate(tr)

        def shorten(name, keyword, drop_patterns=()):
            """Retire du libellé le nom de rubrique (et autres motifs) devenus redondants."""
            parts = re.split(accent_class_pattern(keyword), name, flags=re.IGNORECASE)
            rest = max(parts, key=len) if len(parts) > 1 else name
            for dp in drop_patterns:
                rest = re.sub(dp, "", rest, flags=re.IGNORECASE)
            rest = re.sub(r"\s{2,}", " ", rest).strip(" \t-–—")
            if rest.startswith("(") and rest.endswith(")"):
                rest = rest[1:-1].strip()
            return rest if rest else name

        buckets = {"Collège": [], "Enfants": {}, "Perfectionnement": [], "Compétition": []}
        others = []
        for c in creneaux:
            name = c["groupe"]
            n = normalize_string(name)
            if "competition" in n:
                buckets["Compétition"].append((name, shorten(name, "competition")))
            elif "college" in n:
                buckets["Collège"].append((name, shorten(name, "college")))
            elif "enfants" in n:
                m = re.search(r"20\d\d\s*-\s*20\d\d", n)
                sub = m.group(0).replace(" ", "") if m else "Autres tranches"
                short = shorten(name, "enfants", (r"20\d\d\s*-\s*20\d\d",))
                buckets["Enfants"].setdefault(sub, []).append((name, short))
            elif "perfectionnement" in n:
                buckets["Perfectionnement"].append((name, shorten(name, "perfectionnement")))
            else:
                others.append((name, name))

        items = []
        # Les créneaux hors rubrique (ex : Loisir - Adultes débutants, Loisir - Lycée)
        # sont listés en premier, sans titre de rubrique (libellé complet conservé).
        items.extend(("group", short, name) for name, short in sorted(others))
        for section in ("Collège", "Enfants", "Perfectionnement", "Compétition"):
            entries = buckets.get(section)
            if not entries:
                continue
            items.append(("section", section))
            if isinstance(entries, dict):
                for sub in sorted(entries):
                    items.append(("sub-section", sub))
                    items.extend(("group", short, name) for name, short in sorted(entries[sub]))
            else:
                items.extend(("group", short, name) for name, short in sorted(entries))
        return items

    def run_presence_export(self, variant: str):
        """Lance les fiches de présence (variante 'autonome' ou 'cours') à partir des
        groupes de créneaux du planning (un créneau peut regrouper plusieurs tarifs).
        Les options techniques sont préconfigurées selon la variante : seul le choix
        des groupes (pour les cours) et la période restent à la charge de l'utilisateur.
        Le code de génération (ExportWorker / presence_sheet_generator) reste identique."""
        try:
            creneaux = self._load_presence_creneaux()
            if not creneaux:
                QMessageBox.warning(self, "Aucun groupe", "Aucun groupe de créneaux trouvé dans le planning (BDD).")
                return

            from domain.utils import normalize_string

            def is_autonome(c):
                if "autonome" in normalize_string(c["groupe"]):
                    return True
                return any("autonome" in normalize_string(t) for t in c["tarifs"])

            tooltips = {}
            for c in creneaux:
                slots_txt = " · ".join(f"{j} {h}".strip() for j, h in c["slots"] if j or h)
                tarifs_txt = ", ".join(c["tarifs"]) or "Aucun tarif HelloAsso configuré ⚠️"
                tooltip = c["groupe"]
                if slots_txt:
                    tooltip += f"\nCréneau(x) : {slots_txt}"
                tooltips[c["groupe"]] = f"{tooltip}\nTarifs HelloAsso : {tarifs_txt}"

            if variant == "autonome":
                # Fusionne les créneaux autonomes + jeunes avec autorisation parentale
                selected_creneaux = [c for c in creneaux if is_autonome(c)]
                if not selected_creneaux:
                    QMessageBox.warning(
                        self, "Aucun groupe autonome",
                        "Aucun créneau autonome n'a été trouvé dans le planning de la BDD."
                    )
                    return
                selected_groups = [c["groupe"] for c in selected_creneaux]
                dialog = PresenceSelectionDialog(
                    selected_groups,
                    title="🧗 Fiche de Présence Autonome",
                    description=(
                        "Les créneaux autonomes ci-dessous seront fusionnés en UN SEUL tableau, "
                        "en ajoutant les jeunes avec autorisation parentale (Autonomes / Famille) "
                        "répartis dans les autres groupes."
                    ),
                    fixed_selection=True,
                    tooltips=tooltips,
                    parent=self,
                )
                preset = {"merge_groups": True, "auth_only": True, "hide_badge_cols": False, "same_sheet": False}
            else:
                # Export des cours : sélection manuelle, badges masqués, tableaux empilés dans la même feuille
                cours_creneaux = [c for c in creneaux if not is_autonome(c)]
                if not cours_creneaux:
                    QMessageBox.warning(self, "Aucun cours", "Aucun créneau de cours trouvé dans le planning (BDD).")
                    return
                selected_groups = [c["groupe"] for c in cours_creneaux]
                dialog = PresenceSelectionDialog(
                    selected_groups,
                    title="📚 Fiches de Présence des Cours",
                    description=(
                        "Les colonnes Badge rouge / Bloc / Passeport Orange seront masquées et tous les "
                        "tableaux seront générés dans la même feuille Excel (empilés, espace QRCode réservé)."
                    ),
                    fixed_selection=False,
                    tooltips=tooltips,
                    group_items=self._build_cours_hierarchy(cours_creneaux),
                    parent=self,
                )
                preset = {"merge_groups": False, "auth_only": False, "hide_badge_cols": True, "same_sheet": True}

            if dialog.exec() != QDialog.Accepted:
                return

            self.set_buttons_enabled(False)
            self.progress_bar.setValue(0)
            self.progress_bar.setVisible(True)
            self.log_area.clear()

            self.log_area.append(f"ℹ️ [INFO] Lancement du compilateur d'export 'PRESENCE ({variant.upper()})'...")

            # Mapping créneau -> tarifs HelloAsso pour les groupes sélectionnés uniquement
            group_tarifs_map = {
                c["groupe"]: c["tarifs"] for c in creneaux if c["groupe"] in dialog.selected_groups
            }

            self.worker = ExportWorker(
                export_type="presence",
                selected_groups=dialog.selected_groups,
                start_date_str=dialog.start_date_str,
                end_date_str=dialog.end_date_str,
                merge_groups=preset["merge_groups"],
                auth_only=preset["auth_only"],
                hide_badge_cols=preset["hide_badge_cols"],
                same_sheet=preset["same_sheet"],
                group_tarifs_map=group_tarifs_map
            )
            self.worker.progress.connect(self.on_progress)
            self.worker.finished.connect(self.on_finished)
            self.worker.start()
        except Exception as e:
            QMessageBox.critical(self, "Erreur d'initialisation", f"Impossible de préparer l'export des fiches de présence : {e}")

    def run_export(self, export_type: str):
        """Déclenche la tâche d'export sélectionnée en tâche de fond (asynchrone)."""
        selected_groups = None
        start_date_str = None
        end_date_str = None
        merge_groups = False
        auth_only = False
        hide_badge_cols = False
        same_sheet = False

        self.set_buttons_enabled(False)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)
        self.log_area.clear()

        self.log_area.append(f"ℹ️ [INFO] Lancement du compilateur d'export '{export_type.upper()}'...")
        
        self.worker = ExportWorker(
            export_type=export_type, 
            selected_groups=selected_groups,
            start_date_str=start_date_str,
            end_date_str=end_date_str,
            merge_groups=merge_groups,
            auth_only=auth_only,
            hide_badge_cols=hide_badge_cols,  # Nouveau !
            same_sheet=same_sheet  # Nouveau !
        )
        self.worker.progress.connect(self.on_progress)
        self.worker.finished.connect(self.on_finished)
        self.worker.start()

    def on_progress(self, message: str, percent: int):
        self.progress_bar.setValue(percent)
        self.log_area.append(message)

    def on_finished(self, success: bool, message: str, file_path: str = ""):
        self.set_buttons_enabled(True)
        self.log_area.append("\n==============================================")
        
        is_cours_summary = message.startswith("COURS_SUMMARY:")
        clean_msg = message.split("COURS_SUMMARY:", 1)[1] if is_cours_summary else message
        
        if success:
            if is_cours_summary:
                self.log_area.append("✅ [SUCCÈS] Remplissage du fichier Cours.xlsx complété avec succès !")
                # Lire et afficher le rapport détaillé de remplissage dans la console de logs !
                try:
                    from paths import ROOT_DIR
                    report_path = os.path.join(ROOT_DIR, "exports", "liste adhérent", "Rapport_Remplissage_Cours.md")
                    if os.path.exists(report_path):
                        with open(report_path, "r", encoding="utf-8") as rf:
                            report_content = rf.read()
                        self.log_area.append("\n" + "="*60)
                        self.log_area.append("📝 RAPPORT DÉTAILLÉ DE REMPLISSAGE DES COURS (MARKDOWN) :")
                        self.log_area.append("="*60)
                        self.log_area.append(report_content)
                        self.log_area.append("="*60 + "\n")
                except Exception as rex:
                    self.log_area.append(f"⚠️ Impossible de charger le rapport détaillé dans la console : {rex}")
            else:
                self.log_area.append(f"✅ [SUCCÈS] {clean_msg}")
            if file_path:
                self.log_area.append(f"📁 Emplacement : {file_path}")
        else:
            self.log_area.append(f"❌ [ERREUR] Échec de l'export : {clean_msg}")
        self.log_area.append("==============================================")

        # Proposer l'ouverture du fichier ou dossier généré (uniquement en cas de succès sous Windows)
        if success and file_path and os.path.exists(file_path):
            from PySide6.QtWidgets import QMessageBox
            
            is_dir = os.path.isdir(file_path)
            export_type = getattr(self.worker, "export_type", "") if getattr(self, "worker", None) else ""
            
            if is_cours_summary:
                # Créer un pop-up QMessageBox HTML personnalisé pour afficher le résumé de remplissage Cours.xlsx !
                box = QMessageBox(self)
                box.setWindowTitle("Rapport d'export Cours.xlsx")
                box.setText(clean_msg + "<p><b>Voulez-vous ouvrir le fichier Cours.xlsx maintenant ?</b></p>")
                box.setTextFormat(Qt.TextFormat.RichText)
                yes_btn = box.addButton("🚀 Oui, ouvrir", QMessageBox.ButtonRole.YesRole)
                no_btn = box.addButton("Non, fermer", QMessageBox.ButtonRole.NoRole)
                box.exec()
                
                if box.clickedButton() == yes_btn:
                    try:
                        os.startfile(file_path)
                    except Exception as err:
                        self.log_area.append(f"⚠️ Impossible d'ouvrir le fichier automatiquement : {err}")
            elif export_type == "ffme":
                # Pop-up de validation FFME : ouvrir le dossier généré + portail fédéral
                box = QMessageBox(self)
                box.setWindowTitle("Export FFME terminé")
                box.setTextFormat(Qt.TextFormat.RichText)
                box.setText(
                    "✅ <b>Le fichier d'import FFME a été généré avec succès !</b><br><br>"
                    f"<code>{os.path.basename(file_path)}</code><br><br>"
                    "Que souhaitez-vous faire ?"
                )
                folder_btn = box.addButton("📂 Ouvrir le dossier", QMessageBox.ButtonRole.ActionRole)
                ffme_btn = box.addButton("🌐 FFME", QMessageBox.ButtonRole.ActionRole)
                box.addButton("Fermer", QMessageBox.ButtonRole.RejectRole)
                box.exec()
                
                if box.clickedButton() == folder_btn:
                    self.open_export_folder(file_path)
                elif box.clickedButton() == ffme_btn:
                    self.open_ffme_portal()
            else:
                # Pop-up classique pour les autres types d'exports
                title = "Ouverture de l'export"
                question = (
                    f"L'export a été généré avec succès !\n\n"
                    f"Voulez-vous ouvrir le {'dossier' if is_dir else 'fichier'} maintenant ?\n"
                    f"({os.path.basename(file_path)})"
                )
                
                reply = QMessageBox.question(
                    self, 
                    title, 
                    question, 
                    QMessageBox.Yes | QMessageBox.No, 
                    QMessageBox.Yes
                )
                
                if reply == QMessageBox.Yes:
                    try:
                        os.startfile(file_path)
                    except Exception as e:
                        self.log_area.append(f"❌ [ERREUR] Impossible d'ouvrir automatiquement l'export : {e}")

        # Actualiser les statistiques FFME après chaque fin d'exportation
        self.update_ffme_stats()

    def open_export_folder(self, file_path: str):
        """Ouvre le dossier contenant le fichier généré (fichier sélectionné dans l'Explorateur)."""
        try:
            import subprocess
            subprocess.Popen(f'explorer /select,"{os.path.abspath(file_path)}"')
        except Exception:
            try:
                os.startfile(os.path.dirname(os.path.abspath(file_path)))
            except Exception as err:
                self.log_area.append(f"❌ [ERREUR] Impossible d'ouvrir le dossier : {err}")

    def open_ffme_portal(self):
        """Ouvre la page de saisie des licences via CSV sur le portail fédéral (Chrome si disponible)."""
        url = "https://myffme.fr/federal/gestion-des-licences/saisir-les-licences-via-csv/2027"
        chrome_candidates = [
            os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
        ]
        for chrome_path in chrome_candidates:
            if os.path.exists(chrome_path):
                try:
                    import subprocess
                    subprocess.Popen([chrome_path, "--new-window", url])
                    return
                except Exception:
                    continue
        # Repli : navigateur par défaut du système
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception as err:
            self.log_area.append(f"❌ [ERREUR] Impossible d'ouvrir le portail FFME : {err}")


class PresenceSelectionDialog(QDialog):
    """Dialogue modal des fiches de présence : sélection des cours (export « cours »)
    ou liste fixe en lecture seule (export « autonome »), plus la période de présence.
    Les options techniques (fusion, autorisation, badge, même feuille) sont préconfigurées
    par type d'export côté ExportsPage et ne sont plus exposées à l'utilisateur."""
    def __init__(self, groups, title, description, fixed_selection=False, tooltips=None, group_items=None, parent=None):
        super().__init__(parent)
        self.groups = sorted(groups)
        self.fixed_selection = fixed_selection
        self.tooltips = tooltips or {}
        # Structure hiérarchique optionnelle : liste de (kind, label) où
        # kind ∈ {'section', 'sub-section', 'group'}. Sinon liste plate.
        self.group_items = group_items if group_items is not None else [("group", g) for g in self.groups]
        self.selected_groups = []
        self.start_date_str = None
        self.end_date_str = None
        self.init_ui(title, description)

    def init_ui(self, title, description):
        self.setWindowTitle(title)
        self.setMinimumWidth(520)
        self.setStyleSheet("""
            QDialog {
                background-color: #F8FAFC;
            }
            QLabel {
                color: #1E293B;
                font-weight: bold;
                font-size: 13px;
            }
            QListWidget {
                border: 1px solid #CBD5E1;
                border-radius: 6px;
                background-color: #FFFFFF;
                font-size: 11px;
                padding: 5px;
            }
            QListWidget::item {
                padding: 6px;
                border-bottom: 1px solid #F1F5F9;
                color: #334155;
            }
            QListWidget::item:hover {
                background-color: #F1F5F9;
                color: #0F172A;
            }
            QListWidget::item:selected {
                background-color: #DBEAFE;
                color: #1E3A8A;
                font-weight: bold;
            }
            QListWidget::indicator {
                border: 1px solid #94A3B8;
                background-color: #F1F5F9;
                border-radius: 3px;
                width: 14px;
                height: 14px;
            }
            QListWidget::indicator:checked {
                background-color: #2563EB;
                border: 1px solid #1D4ED8;
            }
            QCheckBox {
                color: #1E293B;
                font-size: 11px;
                font-weight: bold;
            }
            QCheckBox::indicator {
                border: 1px solid #CBD5E1;
                border-radius: 3px;
                background: #FFFFFF;
                width: 14px;
                height: 14px;
            }
            QCheckBox::indicator:checked {
                background-color: #2563EB;
                border-color: #1D4ED8;
            }
            QPushButton {
                font-weight: bold;
                font-size: 11px;
                border-radius: 4px;
                padding: 6px 12px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # Récapitulatif des options préconfigurées pour cet export
        desc_lbl = QLabel(description)
        desc_lbl.setWordWrap(True)
        desc_lbl.setStyleSheet("color: #475569; font-weight: 500; font-size: 11px;")
        layout.addWidget(desc_lbl)

        lbl = QLabel(
            "Groupes inclus (sélection figée) :"
            if self.fixed_selection else
            "Sélectionnez les cours / groupes d'activités à générer :"
        )
        layout.addWidget(lbl)

        # Liste des groupes : cases à cocher (export « cours ») ou lecture seule (export « autonome »)
        # Les rubriques (sections / sous-sections) sont des lignes de titre non sélectionnables.
        self.list_widget = QListWidget()
        section_font = QFont()
        section_font.setBold(True)
        sub_font = QFont()
        sub_font.setBold(True)
        sub_font.setItalic(True)

        indent = 0
        for entry in self.group_items:
            kind, label = entry[0], entry[1]
            raw_name = entry[2] if len(entry) > 2 else label  # Nom brut du groupe (sans indentation)
            if kind == "section":
                indent = 1
                item = QListWidgetItem(f"📁 {label}")
                item.setFlags(Qt.NoItemFlags)
                item.setFont(section_font)
                item.setForeground(QColor("#1E3A8A"))
                item.setBackground(QColor("#DBEAFE"))
            elif kind == "sub-section":
                indent = 2
                item = QListWidgetItem("\u00A0\u00A0\u00A0📂 " + label)
                item.setFlags(Qt.NoItemFlags)
                item.setFont(sub_font)
                item.setForeground(QColor("#1D4ED8"))
                item.setBackground(QColor("#EFF6FF"))
            else:
                item = QListWidgetItem("\u00A0" * (4 * indent) + label)
                if self.fixed_selection:
                    item.setFlags(item.flags() & ~Qt.ItemIsUserCheckable)
                    item.setCheckState(Qt.Checked)
                else:
                    item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                    item.setCheckState(Qt.Checked) # Coché par défaut !
                if raw_name in self.tooltips:
                    item.setToolTip(self.tooltips[raw_name])
            item.setData(Qt.UserRole, kind)
            item.setData(Qt.UserRole + 1, raw_name)  # Nom brut envoyé au générateur
            self.list_widget.addItem(item)
        layout.addWidget(self.list_widget)

        # Dimensionner la fenêtre pour afficher la liste complète sans défilement
        screen = QApplication.primaryScreen().availableGeometry()
        rows = self.list_widget.count()
        row_h = self.list_widget.sizeHintForRow(0)
        if row_h <= 0:
            row_h = 30
        list_h = min(row_h * rows + 16, int(screen.height() * 0.55))
        self.list_widget.setMinimumHeight(list_h)
        self.setMinimumHeight(min(400 + list_h, screen.height() - 40))

        # Boutons de sélection de masse (uniquement pour la sélection des cours)
        if not self.fixed_selection:
            sel_layout = QHBoxLayout()
            sel_layout.setSpacing(10)

            btn_select_all = QPushButton("Tout Sélectionner")
            btn_select_all.setCursor(Qt.PointingHandCursor)
            btn_select_all.setStyleSheet("""
                QPushButton {
                    background-color: #F1F5F9;
                    color: #475569;
                    border: 1px solid #CBD5E1;
                }
                QPushButton:hover {
                    background-color: #E2E8F0;
                }
            """)
            btn_select_all.clicked.connect(self.select_all)
            sel_layout.addWidget(btn_select_all)

            btn_deselect_all = QPushButton("Tout Décocher")
            btn_deselect_all.setCursor(Qt.PointingHandCursor)
            btn_deselect_all.setStyleSheet("""
                QPushButton {
                    background-color: #F1F5F9;
                    color: #475569;
                    border: 1px solid #CBD5E1;
                }
                QPushButton:hover {
                    background-color: #E2E8F0;
                }
            """)
            btn_deselect_all.clicked.connect(self.deselect_all)
            sel_layout.addWidget(btn_deselect_all)

            layout.addLayout(sel_layout)

        # 📅 Section Période de Présence à Générer
        date_title = QLabel("📅 Période de Présence :")
        layout.addWidget(date_title)

        date_group = QFrame()
        date_group.setStyleSheet("""
            QFrame {
                border: 1px solid #E2E8F0;
                border-radius: 6px;
                background-color: #F8FAFC;
                padding: 10px;
            }
            QLabel {
                font-size: 11px;
                color: #475569;
                font-weight: bold;
            }
            QDateEdit {
                border: 1px solid #CBD5E1;
                border-radius: 4px;
                background-color: #FFFFFF;
                padding: 4px;
                font-size: 11px;
                color: #334155;
            }
        """)
        date_layout = QHBoxLayout(date_group)
        date_layout.setSpacing(10)

        lbl_start = QLabel("Du :")
        self.start_date_edit = QDateEdit()
        self.start_date_edit.setCalendarPopup(True)
        
        lbl_end = QLabel("Au :")
        self.end_date_edit = QDateEdit()
        self.end_date_edit.setCalendarPopup(True)
        
        # Déterminer les années par rapport à la saison active
        try:
            from domain.constants import get_active_season
            season = get_active_season()
            y_start = int(season.split("-")[0])
            y_end = int(season.split("-")[1])
        except Exception:
            y_start, y_end = 2026, 2027
            
        self.start_date_edit.setDate(QDate(y_start, 9, 1)) # Par défaut : 1er Septembre
        self.end_date_edit.setDate(QDate(y_end, 6, 30)) # Par défaut : 30 Juin

        date_layout.addWidget(lbl_start)
        date_layout.addWidget(self.start_date_edit)
        date_layout.addWidget(lbl_end)
        date_layout.addWidget(self.end_date_edit)
        layout.addWidget(date_group)

        # Boutons OK / Annuler
        ok_layout = QHBoxLayout()
        ok_layout.setSpacing(10)
        ok_layout.addStretch()

        btn_cancel = QPushButton("Annuler")
        btn_cancel.setCursor(Qt.PointingHandCursor)
        btn_cancel.setStyleSheet("""
            QPushButton {
                background-color: #64748B;
                color: #FFFFFF;
                border: none;
            }
            QPushButton:hover {
                background-color: #475569;
            }
        """)
        btn_cancel.clicked.connect(self.reject)
        ok_layout.addWidget(btn_cancel)

        btn_ok = QPushButton("💾 Générer Sélection")
        btn_ok.setCursor(Qt.PointingHandCursor)
        btn_ok.setStyleSheet("""
            QPushButton {
                background-color: #2563EB;
                color: #FFFFFF;
                border: none;
            }
            QPushButton:hover {
                background-color: #1D4ED8;
            }
        """)
        btn_ok.clicked.connect(self.accept_selection)
        ok_layout.addWidget(btn_ok)

        layout.addLayout(ok_layout)

    def select_all(self):
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.data(Qt.UserRole) == "group":
                item.setCheckState(Qt.Checked)

    def deselect_all(self):
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.data(Qt.UserRole) == "group":
                item.setCheckState(Qt.Unchecked)

    def accept_selection(self):
        self.selected_groups = []
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.data(Qt.UserRole) == "group" and item.checkState() == Qt.Checked:
                self.selected_groups.append(item.data(Qt.UserRole + 1))
                
        if not self.selected_groups:
            QMessageBox.warning(self, "Aucune sélection", "Veuillez cocher au moins un cours pour lancer l'export.")
            return
            
        # Récupérer et formater les dates sélectionnées
        self.start_date_str = self.start_date_edit.date().toString("dd/MM/yyyy")
        self.end_date_str = self.end_date_edit.date().toString("dd/MM/yyyy")
        self.accept()
