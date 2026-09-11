import os
import glob
import datetime
from PySide6.QtCore import QThread, Signal

from domain.models import Member
from paths import ROOT_DIR
from infrastructure.google_drive_client import GoogleDriveClient
from infrastructure.email_repository import EmailRepository

class SyncHelloAssoWorker(QThread):
    """
    Worker asynchrone pour la synchronisation complète HelloAsso <=> Google Drive.
    """
    progress = Signal(str, int)  # (message, pourcentage)
    finished = Signal(bool, str) # (succès, message_résultat)

    def __init__(self, drive_file_id: str, campaign_slug: str, parent=None):
        super().__init__(parent)
        self.drive_file_id = drive_file_id
        self.campaign_slug = campaign_slug

    def run(self):
        try:
            self.progress.emit("Démarrage de la synchronisation HelloAsso...", 10)
            self.progress.emit("Téléchargement du Drive et intégration en arrière-plan...", 50)
            
            from create_excel import update_membership_excel
            success, new_participants, result = update_membership_excel()
            
            if success:
                self.progress.emit("Sauvegarde et téléversement terminés !", 90)
                
                # Formater le résumé des ajouts
                import json
                
                def format_date_to_french_day_month(val):
                    import datetime
                    dt = None
                    if isinstance(val, (datetime.datetime, datetime.date)):
                        dt = val
                    elif isinstance(val, str):
                        for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%d/%m/%Y %H:%M:%S"):
                            try:
                                dt = datetime.datetime.strptime(val.strip(), fmt)
                                break
                            except Exception:
                                pass
                    if dt:
                        FRENCH_MONTHS = {
                            1: "janvier", 2: "février", 3: "mars", 4: "avril", 5: "mai", 6: "juin",
                            7: "juillet", 8: "août", 9: "septembre", 10: "octobre", 11: "novembre", 12: "décembre"
                        }
                        return f"{dt.day:02d} {FRENCH_MONTHS[dt.month]}"
                    return str(val)

                # Contrôle d'âge des nouvelles inscriptions : un adulte (18 ans révolus au 01/09
                # de la saison) ne peut pas souscrire à un groupe enfants/collège/lycée, et
                # l'année de naissance doit correspondre aux bornes du groupe (tarif HelloAsso).
                age_conflicts = []
                planning_data = []
                age_rules_ok = True
                try:
                    from infrastructure.sqlite_repository import SqliteRepository
                    from domain.age_rules import check_age_conflict, find_planning_item_for_tarif
                    planning_data = SqliteRepository.load_planning_data(log_debug=False)
                except Exception as ac_err:
                    print(f"⚠️ [SYNC_WORKER] Contrôle d'âge impossible : {ac_err}")
                    age_rules_ok = False

                new_members_list = []
                for p in new_participants:
                    raw_date = p.get("order_date") or ""
                    date_str = format_date_to_french_day_month(raw_date)
                    last_name = str(p.get("user_lastName") or "").upper().strip()
                    first_name = str(p.get("user_firstName") or "").capitalize().strip()
                    tarif = str(p.get("tarif_name") or "").strip()

                    warning_msg = ""
                    if age_rules_ok:
                        birth_raw = str(p.get("champ_Date de naissance de l'adhérent") or "").strip()
                        planning_item = find_planning_item_for_tarif(tarif, planning_data)
                        messages = check_age_conflict(birth_raw, tarif, planning_item)
                        if messages:
                            warning_msg = " | ".join(messages)
                            age_conflicts.append({
                                "last_name": last_name,
                                "first_name": first_name,
                                "tarif_name": tarif,
                                "birth_date": birth_raw,
                                "messages": messages
                            })
                            print(f"⚠️ [SYNC_WORKER] Conflit d'âge : {last_name} {first_name} ({tarif}) : {warning_msg}")

                    new_members_list.append({
                        "last_name": last_name,
                        "first_name": first_name,
                        "order_date": date_str,
                        "warning": warning_msg
                    })
                
                new_members_json = json.dumps(
                    {"new_members": new_members_list, "age_conflicts": age_conflicts},
                    ensure_ascii=False
                )
                self.progress.emit("Synchronisation HelloAsso terminée avec succès !", 100)
                self.finished.emit(True, f"SUCCESS_DATA:{new_members_json}")
            else:
                self.finished.emit(False, f"Échec lors de la synchronisation : {result}")
                
        except Exception as e:
            self.finished.emit(False, str(e))


class GenerateAttestationsWorker(QThread):
    """
    Worker asynchrone pour la génération des attestations de paiement au format Word et PDF.
    """
    progress = Signal(str, int)  # (message, pourcentage)
    finished = Signal(int, int, int) # (générés, ignorés, erreurs)
    # Demande de génération déléguée au thread principal (QtWebEngine/Chromium n'est pas
    # thread-safe). L'IHM doit connecter ce signal avec Qt.BlockingQueuedConnection.
    pdf_generation_requested = Signal(dict)

    def __init__(self, output_format: str = "pdf", test_mode: bool = False, members: list = None, parent=None):
        super().__init__(parent)
        self.output_format = output_format
        self.test_mode = test_mode
        self.members = members
        self.pdf_result = {"success": False, "error": ""}

    def run(self):
        try:
            self.progress.emit("Initialisation du générateur d'attestations...", 10)
            
            if self.members is not None:
                raw_data = self.members
            else:
                self.progress.emit("Chargement des adhérents depuis la base SQLite...", 30)
                from infrastructure.sqlite_repository import SqliteRepository
                raw_data = SqliteRepository.load_direct_data()
            
            self.progress.emit("Lancement de la fusion Word et conversion PDF en arrière-plan...", 50)
            # IMPORTANT : le rendu PDF s'appuie sur QtWebEngine (Chromium) qui n'est pas
            # thread-safe. On délègue la génération au thread principal via une connexion
            # bloquante, sinon l'application plante nativement dès la 2ème génération.
            self.pdf_result = {"success": False, "error": ""}
            self.pdf_generation_requested.emit({
                "participants": raw_data,
                "output_format": self.output_format,
                "test_mode": self.test_mode
            })
            # Connexion bloquante : on reprend ici une fois la génération terminée sur le thread principal
            if not self.pdf_result.get("success"):
                raise RuntimeError(self.pdf_result.get("error") or "Échec de la génération des attestations.")
            
            self.progress.emit("Génération des attestations terminée !", 100)
            # Renvoyer des statistiques fictives ou calculées
            self.finished.emit(len(raw_data), 0, 0)
            
        except Exception as e:
            print(f"❌ [WORKER_ATTESTATION] Erreur : {e}")
            self.progress.emit(f"Erreur : {e}", 100)
            self.finished.emit(0, 0, 1)


class SendEmailCampaignWorker(QThread):
    """
    Worker asynchrone pour l'envoi d'e-mails par lots avec ou sans attestations jointes.
    """
    progress = Signal(str, int)  # (message, pourcentage)
    finished = Signal(int, int)  # (succès, échecs)
    # Demande de génération d'attestation déléguée au thread principal (QtWebEngine/Chromium
    # n'est pas thread-safe). L'IHM doit connecter ce signal avec Qt.BlockingQueuedConnection.
    pdf_generation_requested = Signal(dict)

    def __init__(self, subject: str, body: str, members: list, attach_pdf: bool = True, attach_whatsapp: bool = True, use_primary_email: bool = True, use_secondary_email: bool = True, use_payer_email: bool = False, whatsapp_template: str = None, add_signature: bool = False, sender_email: str = None, sender_name: str = None, parent=None):
        super().__init__(parent)
        self.subject = subject
        self.body = body
        self.members = members
        self.attach_pdf = attach_pdf
        self.attach_whatsapp = attach_whatsapp
        self.use_primary_email = use_primary_email
        self.use_secondary_email = use_secondary_email
        self.use_payer_email = use_payer_email
        self.whatsapp_template = whatsapp_template
        self.add_signature = add_signature
        self.sender_email = (sender_email or "").strip() or None
        self.sender_name = (sender_name or "").strip() or None
        self.pdf_result = {"success": False, "error": ""}

    def run(self):
        success_count = 0
        error_count = 0
        total = len(self.members)
        
        if total == 0:
            self.progress.emit("Aucun destinataire sélectionné.", 100)
            self.finished.emit(0, 0)
            return

        # 1. Charger le planning depuis SQLite pour récupérer les liens WhatsApp associés aux créneaux
        planning_data = []
        try:
            from infrastructure.sqlite_repository import SqliteRepository
            planning_data = SqliteRepository.load_planning_data()
        except Exception as pe:
            print(f"⚠️ [EMAIL_WORKER] Impossible de charger le planning depuis SQLite : {pe}")

        for idx, m in enumerate(self.members):
            percent = int((idx / total) * 100)
            
            # Recueillir les adresses e-mail valides selon les critères choisis par l'utilisateur
            emails = []
            candidates = []
            if self.use_primary_email:
                candidates.append(m.primary_email)
            if self.use_secondary_email:
                candidates.append(m.secondary_email)
            if self.use_payer_email:
                candidates.append(m.payer_email)
                
            for em in candidates:
                if em:
                    em_strip = str(em).strip()
                    if em_strip and "@" in em_strip and em_strip.lower() not in [x.lower() for x in emails]:
                        emails.append(em_strip)
            
            if not emails:
                error_count += 1
                self.progress.emit(f"⏩ Ignoré : {m.user_last_name} {m.user_first_name} (Aucune adresse e-mail valide selon vos critères)", percent)
                continue
                
            email_dest = ", ".join(emails)
                
            pdf_path = None
            if self.attach_pdf:
                # 1. Vérifier si l'attestation PDF existe
                from attestation_generator import get_safe_filename
                filename_docx = get_safe_filename(m.user_last_name, m.user_first_name, m.order_ref)
                filename_pdf = filename_docx.replace(".docx", ".pdf")
                pdf_path = os.path.join(ROOT_DIR, "exports", "attestation", filename_pdf)
                
                if not os.path.exists(pdf_path):
                    self.progress.emit(f"⚙️ Génération de l'attestation manquante pour {m.user_last_name} {m.user_first_name}...", percent)
                    try:
                        # Générer uniquement pour ce membre au format PDF.
                        # IMPORTANT : QtWebEngine (Chromium) n'est pas thread-safe, la génération
                        # est déléguée au thread principal via une connexion bloquante
                        # (sinon crash natif de l'application).
                        self.pdf_result = {"success": False, "error": ""}
                        self.pdf_generation_requested.emit({
                            "participants": [m.to_dict()],
                            "output_format": "pdf"
                        })
                        # Connexion bloquante : on reprend ici une fois la génération terminée
                        if not self.pdf_result.get("success"):
                            print(f"❌ [EMAIL_WORKER] Impossible de générer l'attestation : {self.pdf_result.get('error')}")
                    except Exception as gen_err:
                        print(f"❌ [EMAIL_WORKER] Impossible de générer l'attestation : {gen_err}")
                
                # Vérifier à nouveau après tentative de génération
                if not os.path.exists(pdf_path):
                    error_count += 1
                    self.progress.emit(f"❌ Échec d'envoi : L'attestation PDF pour {m.user_last_name} {m.user_first_name} est introuvable ou n'a pas pu être générée.", percent)
                    continue

            # 2. Détection dynamique du groupe WhatsApp et récupération du lien/QRCode
            msg_body = self.body
            
            # Personnaliser le corps du message avec le Prénom et le Nom de l'adhérent (Nouveau !)
            # Support des deux syntaxes : {Prénom}/{Nom} (IHM) et {first_name}/{last_name} (modèles BDD)
            msg_body = msg_body.replace("{Prénom}", m.user_first_name.strip().title())
            msg_body = msg_body.replace("{Nom}", m.user_last_name.strip().upper())
            msg_body = msg_body.replace("{first_name}", m.user_first_name.strip().title())
            msg_body = msg_body.replace("{last_name}", m.user_last_name.strip().upper())
            qr_path = None
            qr_status_msg = "⚠️ QRCode non joint (Option désactivée)" if not self.attach_whatsapp else "⚠️ QRCode non joint (Aucun créneau correspondant)"
            
            if self.attach_whatsapp and planning_data and m.tarif_name:
                try:
                    # 2.1 Tenter d'abord de trouver une correspondance exacte configurée via l'IHM (helloasso_tarifs)
                    found_item = None
                    for item in planning_data:
                        linked_tarifs = item.get("helloasso_tarifs", [])
                        if any(str(t).strip().lower() == m.tarif_name.strip().lower() for t in linked_tarifs):
                            found_item = item
                            break
                            
                    # 2.2 Si aucune correspondance configurée, utiliser le rapprochement sémantique d'origine
                    if not found_item:
                        from presence_sheet_generator import find_planning_match_dynamically
                        match_info = find_planning_match_dynamically(m.tarif_name, planning_data)
                        if match_info:
                            # Retrouver le créneau réel du planning qui correspond au groupe trouvé par l'algorithme sémantique
                            target_group_name = match_info.get("groupe_planning")
                            for item in planning_data:
                                if str(item.get("groupe")).strip().lower() == str(target_group_name).strip().lower():
                                    found_item = item
                                    break
                                    
                    if found_item:
                        whatsapp_link = found_item.get("whatsapp_link") or "".strip()
                        group_name = found_item.get("groupe") or "".strip()
                        if whatsapp_link and group_name:
                            # Enrichir le corps de l'e-mail sous forme de signature officielle de créneau
                            template = self.whatsapp_template
                            if not template or not template.strip():
                                template = (
                                    "\n\n---\n"
                                    "🧗 <b>Créneau : {group_name}</b>\n"
                                    "💬 Rejoindre le groupe WhatsApp : {whatsapp_link}\n"
                                    "📱 Le QRCode d'invitation est également joint en pièce jointe à cet e-mail."
                                )
                            
                            # Formater le gabarit avec les variables réelles de manière robuste
                            try:
                                formatted_text = template.format(group_name=group_name, whatsapp_link=whatsapp_link)
                            except Exception as fmt_err:
                                print(f"⚠️ [EMAIL_WORKER] Erreur de formatage du texte WhatsApp : {fmt_err}")
                                # Repli automatique sur le texte standard en cas d'erreur de saisie de l'utilisateur
                                formatted_text = (
                                    f"\n\n---\n"
                                    f"🧗 <b>Créneau : {group_name}</b>\n"
                                    f"💬 Rejoindre le groupe WhatsApp : {whatsapp_link}\n"
                                    f"📱 Le QRCode d'invitation est également joint en pièce jointe à cet e-mail."
                                )
                            
                            msg_body += formatted_text
                            
                            # Télécharger / Générer le QRCode du groupe WhatsApp si absent
                            import urllib.parse
                            safe_group = "".join([c for c in group_name if c.isalnum() or c in (" ", "-", "_")]).strip()
                            qrcodes_dir = os.path.join(ROOT_DIR, "exports", "qrcodes")
                            os.makedirs(qrcodes_dir, exist_ok=True)
                            qr_path = os.path.join(qrcodes_dir, f"QRCode_WhatsApp_{safe_group}.png")
                            
                            if not os.path.exists(qr_path):
                                try:
                                    import requests
                                    api_url = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={urllib.parse.quote(whatsapp_link)}"
                                    res = requests.get(api_url, timeout=10)
                                    if res.status_code == 200:
                                        with open(qr_path, "wb") as f:
                                            f.write(res.content)
                                        qr_status_msg = f"🟢 QRCode joint avec succès ({group_name})"
                                    else:
                                        qr_status_msg = f"❌ QRCode non joint ({group_name} : Échec API, code HTTP {res.status_code})"
                                        qr_path = None
                                except Exception:
                                    qr_status_msg = f"❌ QRCode non joint ({group_name} : Erreur de téléchargement)"
                                    qr_path = None
                            else:
                                qr_status_msg = f"🟢 QRCode joint avec succès ({group_name})"
                        else:
                            group_desc = group_name or m.tarif_name
                            qr_status_msg = f"⚠️ QRCode non joint (Lien WhatsApp absent pour le groupe '{group_desc}')"
                    else:
                        qr_status_msg = f"⚠️ QRCode non joint (Aucun cours trouvé pour le tarif '{m.tarif_name}')"
                except Exception:
                    qr_status_msg = "❌ QRCode non joint (Erreur de matching de cours)"
                
            self.progress.emit(f"✉️ Envoi de l'e-mail à {m.user_last_name} {m.user_first_name} ({email_dest})...\n   └─ {qr_status_msg}", percent)
            
            try:
                # 3. Construire la liste des pièces jointes à transmettre
                attachments = []
                if pdf_path:
                    attachments.append(pdf_path)
                if qr_path and os.path.exists(qr_path):
                    attachments.append(qr_path)

                # 4. Préparer les versions texte brut et HTML (avec signature du club optionnelle)
                from email_html import build_email_html, build_signature_plain, get_inline_images
                plain_body = msg_body
                html_body = build_email_html(msg_body, add_signature=self.add_signature, image_src_mode="cid")
                inline_imgs = None
                if self.add_signature:
                    plain_body = msg_body + "\n\n" + build_signature_plain()
                    inline_imgs = get_inline_images()

                # Appel du repository d'email découplé et robuste en joignant les pièces jointes !
                # L'adresse et le nom d'expédition choisis dans l'IHM (template de mail) sont transmis ici.
                EmailRepository.send_email(
                    to_email=email_dest,
                    subject=self.subject,
                    body=plain_body,
                    attachment_path=attachments,
                    html_body=html_body,
                    inline_images=inline_imgs,
                    from_email=self.sender_email,
                    from_name=self.sender_name
                )
                
                # Enregistrer la date d'envoi d'e-mail directement dans SQLite
                try:
                    now_str = datetime.datetime.now().strftime("%d/%m/%Y")
                    from infrastructure.sqlite_repository import SqliteRepository
                    SqliteRepository.update_email_sent_date(
                        order_ref=m.order_ref,
                        last_name=m.user_last_name,
                        first_name=m.user_first_name,
                        date_str=now_str
                    )
                except Exception as b_err:
                    print(f"⚠️ [EMAIL_WORKER] Erreur lors de l'enregistrement de la date d'envoi d'e-mail dans la base SQLite : {b_err}")
                    
                success_count += 1
            except Exception as e:
                error_count += 1
                print(f"❌ [EMAIL_WORKER] Échec d'envoi à {email_dest} : {e}")
                
        self.progress.emit(f"Campagne d'envoi terminée ! {success_count} envoyés, {error_count} échecs.", 100)
        self.finished.emit(success_count, error_count)


class ExportWorker(QThread):
    """
    Worker asynchrone pour la génération d'exports administratifs (FFME, Présence, Urgence, Anciens).
    """
    progress = Signal(str, int)  # (message, pourcentage)
    finished = Signal(bool, str, str) # (succès, message_résultat, chemin_fichier)

    def __init__(self, export_type: str, selected_groups: list = None, start_date_str: str = None, end_date_str: str = None, merge_groups: bool = False, auth_only: bool = False, cours_pdf: bool = False, hide_badge_cols: bool = False, same_sheet: bool = False, group_tarifs_map: dict = None, parent=None):
        super().__init__(parent)
        self.export_type = export_type
        self.selected_groups = selected_groups
        self.start_date_str = start_date_str
        self.end_date_str = end_date_str
        self.merge_groups = merge_groups
        self.auth_only = auth_only
        self.cours_pdf = cours_pdf
        self.hide_badge_cols = hide_badge_cols
        self.same_sheet = same_sheet
        self.group_tarifs_map = group_tarifs_map or {}

    def convert_excel_to_pdf(self, excel_path: str, pdf_path: str) -> bool:
        """
        Convertit un fichier Excel au format PDF en utilisant l'automatisation COM Excel (Windows uniquement).
        Force la mise en page en A3 Paysage et ajustement des pages.
        """
        import win32com.client
        import pythoncom
        import os
        
        self.progress.emit("Initialisation de Microsoft Excel pour la conversion PDF (A3)...", 85)
        pythoncom.CoInitialize()
        excel_app = win32com.client.Dispatch("Excel.Application")
        excel_app.Visible = False
        excel_app.DisplayAlerts = False
        
        try:
            wb = excel_app.Workbooks.Open(os.path.abspath(excel_path))
            ws = wb.ActiveSheet
            
            self.progress.emit("Configuration de la mise en page A3 Paysage...", 90)
            # S'assurer de la mise en page A3, Paysage et ajustement des colonnes à une seule page
            ws.PageSetup.PaperSize = 8  # xlPaperA3 (8)
            ws.PageSetup.Orientation = 2  # xlLandscape (2)
            ws.PageSetup.Zoom = False
            ws.PageSetup.FitToPagesWide = 1
            ws.PageSetup.FitToPagesTall = 1
            
            # Détecter la zone d'impression réelle pour éliminer les pages blanches (votre demande !)
            self.progress.emit("Analyse de la zone d'impression réelle (filtrage des pages blanches)...", 92)
            try:
                # Rechercher la dernière cellule contenant du texte réel (ignore les cellules vides ayant de simples bordures)
                last_row = ws.Cells.Find("*", SearchOrder=1, SearchDirection=2).Row
                last_col = ws.Cells.Find("*", SearchOrder=1, SearchDirection=2).Column
                if last_row > 0 and last_col > 0:
                    ws.PageSetup.PrintArea = ws.Range(ws.Cells(1, 1), ws.Cells(last_row, last_col)).Address
                    print(f"[SQLITE] Zone d'impression optimisée pour exclure le vide : {ws.PageSetup.PrintArea}")
            except Exception as fe:
                print(f"⚠️ [PDF_CONVERT] Impossible d'optimiser la zone d'impression (repli par défaut) : {fe}")
            
            self.progress.emit("Exportation du fichier PDF au format A3...", 95)
            # Exporter uniquement la feuille active (ws) au format PDF (Type 0 = xlTypePDF) pour exclure les autres onglets vides ! (votre demande !)
            ws.ExportAsFixedFormat(0, os.path.abspath(pdf_path))
            wb.Close(False)
            print(f"✅ Conversion Excel -> PDF A3 réussie : {pdf_path}")
            return True
        except Exception as e:
            print(f"❌ Erreur lors de la conversion Excel -> PDF A3 : {e}")
            self.progress.emit(f"⚠️ Erreur de conversion PDF : {e}", 95)
            return False
        finally:
            try:
                excel_app.Quit()
            except Exception:
                pass
            pythoncom.CoUninitialize()

    def run(self):
        try:
            self.progress.emit("Initialisation de l'export...", 10)
            
            # Ne pas brider les autres types d'exports s'ils ont besoin d'autres saisons, mais par défaut on prend raw_data
            self.progress.emit("Chargement des adhérents depuis la base SQLite...", 30)
            from infrastructure.sqlite_repository import SqliteRepository
            raw_data = SqliteRepository.load_direct_data(season_filter="2026-2027")
            
            if self.export_type == "ffme":
                self.progress.emit("Génération du fichier CSV d'import FFME...", 60)
                from create_excel import generate_ffme_csv
                ignored_members = generate_ffme_csv(raw_data)
                
                # S'il y a des ignorés, les afficher de manière très visible dans les logs de la console
                if ignored_members:
                    self.progress.emit(f"\n⚠️  [ALERTE] {len(ignored_members)} adhérent(s) ont été ignoré(s) de l'export FFME car ils ont des données obligatoires manquantes :", 80)
                    for msg in ignored_members:
                        self.progress.emit(msg, 80)
                    self.progress.emit("\n👉 Veuillez compléter leurs fiches dans l'onglet 'Adhérents' ou modifier le fichier HelloAsso pour les inclure.\n", 80)
                
                # Retrouver le fichier CSV nouvellement généré
                csv_files = glob.glob(os.path.join(ROOT_DIR, "exports", "ffme", "import_ffme_*.csv"))
                csv_files.sort(key=os.path.getmtime, reverse=True)
                new_file_path = csv_files[0] if csv_files else ""
                
                self.progress.emit("Fichier d'import FFME généré avec succès !", 100)
                self.finished.emit(True, "Le fichier d'import FFME CSV a été généré.", new_file_path)
                
            elif self.export_type == "presence":
                self.progress.emit("Génération des fiches de présence d'activité...", 50)
                from presence_sheet_generator import generate_presence_sheets
                
                # Utiliser les groupes sélectionnés par l'utilisateur ou charger tous les groupes par défaut
                groups_to_gen = self.selected_groups
                if not groups_to_gen:
                    groups_to_gen = list(set([str(p.get("tarif_name") or "").strip() for p in raw_data if p.get("tarif_name")]))
                    
                if not groups_to_gen:
                    self.finished.emit(False, "Aucun groupe ou tarif sélectionné pour générer les fiches de présence.", "")
                    return
                    
                success, result = generate_presence_sheets(
                    groups_to_gen, 
                    raw_data, 
                    start_date_str=self.start_date_str, 
                    end_date_str=self.end_date_str,
                    merge_groups=self.merge_groups,
                    auth_only=self.auth_only,
                    hide_badge_cols=self.hide_badge_cols,
                    same_sheet=self.same_sheet,
                    group_tarifs_map=self.group_tarifs_map
                )
                if success:
                    dest_dir = os.path.join(ROOT_DIR, "exports", "fiches_presence")
                    self.progress.emit("Fiches de présence générées avec succès !", 100)
                    if self.same_sheet:
                        self.finished.emit(True, f"{len(groups_to_gen)} tableau(x) de présence empilé(s) dans un seul fichier Excel créé dans le dossier 'exports/fiches_presence'.", dest_dir)
                    else:
                        self.finished.emit(True, f"{len(result)} feuilles Excel créées dans le dossier 'exports/fiches_presence'.", dest_dir)
                else:
                    self.finished.emit(False, f"Erreur de génération : {result}", "")
                    
            elif self.export_type == "anciens":
                self.progress.emit("Extraction des anciens adhérents non réinscrits...", 50)
                
                # Charger spécifiquement les anciens non réinscrits (Présents en 2025-2026 mais absents en 2026-2027)
                anciens_raw = SqliteRepository.load_direct_data(season_filter="Non réinscrits")
                if not anciens_raw:
                    self.finished.emit(False, "Aucun ancien adhérent non réinscrit trouvé en base.", "")
                    return
                    
                excel_rows = []
                for p in anciens_raw:
                    email_val = str(p.get("email_primary") or p.get("payer_email") or "").strip()
                    excel_rows.append({
                        "Nom": str(p.get("last_name") or "").strip().upper(),
                        "Pr\u00e9nom": str(p.get("first_name") or "").strip().capitalize(),
                        "Email": email_val,
                        "Tarif (Saison précédente 2025-2026)": str(p.get("tarif_name") or "").strip()
                    })
                    
                import pandas as pd
                df = pd.DataFrame(excel_rows)
                df = df.sort_values(by=["Nom", "Prénom"])
                
                dest_file = os.path.join(ROOT_DIR, "exports", "Anciens_Adherents_Non_Reinscrits.xlsx")
                os.makedirs(os.path.dirname(dest_file), exist_ok=True)
                df.to_excel(dest_file, index=False)
                
                self.progress.emit("Liste des anciens adhérents exportée avec succès !", 100)
                self.finished.emit(True, f"La liste des {len(excel_rows)} anciens adhérents non réinscrits a été générée.", dest_file)
                    
            elif self.export_type == "urgency":
                self.progress.emit("Génération du cahier des contacts d'urgence (A4)...", 60)
                from urgency_contact_generator import generate_urgency_contacts_sheet
                success, filename = generate_urgency_contacts_sheet(raw_data)
                if success:
                    file_path = os.path.join(ROOT_DIR, "exports", filename)
                    self.progress.emit("Cahier des contacts d'urgence finalisé avec succès !", 100)
                    self.finished.emit(True, f"Fichier '{filename}' créé dans le dossier 'exports'.", file_path)
                else:
                    self.finished.emit(False, "Échec lors de la génération de la fiche d'urgence.", "")
                    
            elif self.export_type == "mycompet":
                self.progress.emit("Lancement du scraper de résultats MyCompet...", 40)
                from mycompet_scraper import scrape_mycompet
                try:
                    excel_path = scrape_mycompet(progress_callback=self.progress.emit)
                    self.progress.emit("Résultats de compétition MyCompet exportés avec succès !", 100)
                    self.finished.emit(True, "Les classements de compétitions (Bloc, Vitesse, Difficulté) ont été importés.", excel_path)
                except Exception as ex:
                    self.finished.emit(False, f"Erreur lors du scraping MyCompet : {ex}", "")
                    
            elif self.export_type == "cours":
                self.progress.emit("Alimentation et rapprochement automatique du tableur Cours.xlsx...", 50)
                from fill_presence_cours import main as fill_cours_main
                stats = fill_cours_main()
                
                # Compiler le résumé statistique
                total_sections = len(stats) if stats else 19
                filled_sections = [s for s in stats if s["count"] > 0] if stats else []
                unfilled_sections = [s for s in stats if s["count"] == 0] if stats else []
                
                num_filled = len(filled_sections)
                num_unfilled = len(unfilled_sections)
                has_unfilled = "Oui" if num_unfilled > 0 else "Non"
                total_rows = sum(s["count"] for s in stats) if stats else 0
                
                # Composer un résumé sémantique détaillé
                detail_rows = []
                if stats:
                    for s in stats:
                        if s["count"] > 0:
                            detail_rows.append(f"• 📅 <b>{s['title']}</b> : <b>{s['count']}</b> ligne(s)")
                        else:
                            detail_rows.append(f"• ⚠️ <i><b>{s['title']}</b> : <b>Non rempli</b> (0 inscrit)</i>")
                detail_text = "<br>".join(detail_rows) if detail_rows else "Aucun tableau rempli."
                
                summary_msg = (
                    f"COURS_SUMMARY:<h3><b>📊 Remplissage du fichier de présence terminé !</b></h3>"
                    f"<p>Le tableur général basé sur votre modèle d'origine a été créé et rempli avec succès.</p>"
                    f"<p><b>📈 Résumé des tableaux :</b></p>"
                    f"<ul>"
                    f"  <li><b>Nombre total de lignes saisies au total</b> : <b>{total_rows}</b></li>"
                    f"  <li><b>Nombre de tableaux remplis</b> : <b>{num_filled} / {total_sections}</b></li>"
                    f"  <li><b>Existe-t-il un tableau non rempli ?</b> : <b>{has_unfilled}</b> ({num_unfilled} vide(s))</li>"
                    f"</ul>"
                    f"<p><b>📝 Lignes par tableau :</b></p>"
                    f"<div style='background-color: #F8FAFC; border: 1px solid #E2E8F0; padding: 10px; border-radius: 6px; font-size: 11px; max-height: 150px; overflow-y: auto;'>"
                    f"{detail_text}"
                    f"</div>"
                )
                
                # Retrouver dynamiquement le fichier Cours-*.xlsx qui a été nouvellement généré dans 'exports/liste adhérent'
                cours_files = glob.glob(os.path.join(ROOT_DIR, "exports", "liste adhérent", "Cours-*.xlsx"))
                cours_files.sort(key=os.path.getmtime, reverse=True)
                file_path = cours_files[0] if cours_files else os.path.join(ROOT_DIR, "exports", "liste adhérent", "Cours.xlsx")
                
                if self.cours_pdf:
                    pdf_path = file_path.replace(".xlsx", ".pdf")
                    pdf_success = self.convert_excel_to_pdf(file_path, pdf_path)
                    if pdf_success:
                        self.progress.emit("Remplissage et conversion PDF A3 terminés avec succès !", 100)
                        self.finished.emit(True, summary_msg, pdf_path)
                        return
                
                self.progress.emit("Remplissage du fichier terminé avec succès !", 100)
                self.finished.emit(True, summary_msg, file_path)
                    
        except Exception as e:
            self.finished.emit(False, str(e), "")


class DownloadDriveFileWorker(QThread):
    """
    Worker asynchrone pour télécharger la base SQLite (ou l'Excel de référence) depuis Google Drive.
    """
    progress = Signal(str, int)  # (message, pourcentage)
    finished = Signal(bool, str) # (succès, message_résultat)

    def __init__(self, drive_file_id: str, parent=None):
        super().__init__(parent)
        self.drive_file_id = drive_file_id

    def run(self):
        try:
            from infrastructure.secret_store import SecretStore
            from infrastructure.sqlite_repository import SqliteRepository
            from infrastructure.google_drive_client import GoogleDriveClient
            
            self.progress.emit("Connexion à Google Drive...", 20)
            
            db_drive_id = SecretStore.get_secret("GOOGLE_DRIVE_DB_ID")
            excel_drive_id = SecretStore.get_secret("GOOGLE_DRIVE_FILE_ID") or self.drive_file_id
            db_local_path = SqliteRepository.get_db_path()
            
            # Migration automatique si pas de base de données configurée sur le Drive
            if not db_drive_id and excel_drive_id:
                self.progress.emit("Première utilisation : Migration automatique de l'Excel vers SQLite...", 40)
                try:
                    from migrate_excel_to_db import run_migration
                    run_migration()
                    db_drive_id = SecretStore.get_secret("GOOGLE_DRIVE_DB_ID")
                except Exception as me:
                    print(f"⚠️ Échec de la migration automatique dans le worker : {me}")
            
            if db_drive_id:
                self.progress.emit("Téléchargement de la base de données SQLite...", 60)
                success = GoogleDriveClient.download_file(db_drive_id, db_local_path)
                if success:
                    self.progress.emit("Initialisation de la base de données...", 80)
                    SqliteRepository.setup_database()
                    self.progress.emit("Téléchargement et synchronisation réussis !", 100)
                    self.finished.emit(True, "La base de données SQLite a été téléchargée et synchronisée depuis Google Drive.")
                else:
                    self.finished.emit(False, "Le téléchargement de la base SQLite depuis Google Drive a échoué.")
            else:
                self.finished.emit(False, "Aucun identifiant Google Drive (DB ID) n'est configuré dans vos Paramètres.")
        except Exception as e:
            self.finished.emit(False, str(e))


class LocalDataLoaderWorker(QThread):
    """
    Worker asynchrone pour charger les données adhérents locales au démarrage sans bloquer l'IHM.
    """
    progress = Signal(str, int)  # (message, pourcentage)
    finished = Signal(bool, list, str) # (succès, members_list, message_erreur)

    def run(self):
        try:
            from infrastructure.secret_store import SecretStore
            from infrastructure.sqlite_repository import SqliteRepository
            from infrastructure.google_drive_client import GoogleDriveClient
            import os
            
            self.progress.emit("Initialisation de la base SQLite...", 10)
            
            db_drive_id = SecretStore.get_secret("GOOGLE_DRIVE_DB_ID")
            excel_drive_id = SecretStore.get_secret("GOOGLE_DRIVE_FILE_ID")
            db_local_path = SqliteRepository.get_db_path()
            
            # Vérifier si la base SQLite locale existe déjà
            db_exists = os.path.exists(db_local_path)
            
            # 1. Si la BDD locale n'existe pas encore, la télécharger depuis Drive à la première utilisation
            if not db_exists:
                if db_drive_id:
                    self.progress.emit("Première utilisation : Téléchargement de la base SQLite depuis Google Drive...", 25)
                    try:
                        success = GoogleDriveClient.download_file(db_drive_id, db_local_path)
                        if success:
                            self.progress.emit("Base de données SQLite synchronisée !", 45)
                        else:
                            self.progress.emit("⚠️ Impossible de télécharger, création d'une nouvelle base...", 45)
                    except Exception as e:
                        self.progress.emit(f"⚠️ Connexion Drive indisponible ({e})", 45)
                elif excel_drive_id:
                    self.progress.emit("Base vide détectée, migration de l'Excel de référence vers SQLite...", 25)
                    try:
                        from migrate_excel_to_db import run_migration
                        run_migration()
                        db_drive_id = SecretStore.get_secret("GOOGLE_DRIVE_DB_ID")
                        if db_drive_id:
                            GoogleDriveClient.download_file(db_drive_id, db_local_path)
                    except Exception as me:
                        print(f"⚠️ Échec de la migration initiale : {me}")
            else:
                self.progress.emit("Chargement de la base de données en cache local (Démarrage ultra-rapide)...", 30)
            
            # Initialiser le schéma de la base SQLite locale
            SqliteRepository.setup_database()
            
            # Créer un point de restauration préventif au lancement de l'application (Nouveau !)
            self.progress.emit("Création d'une sauvegarde locale au lancement...", 45)
            try:
                SqliteRepository.create_db_backup()
            except Exception as be:
                print(f"⚠️ [STARTUP] Impossible de créer la sauvegarde de démarrage : {be}")
            
            self.progress.emit("Lecture des données de la base de données...", 60)
            raw_data = SqliteRepository.load_direct_data()
            
            self.progress.emit("Indexation des adhérents et modélisation...", 80)
            members_list = []
            for idx, row in enumerate(raw_data):
                m = Member.from_dict(row)
                from domain.constants import get_active_season
                try:
                    season_yr = get_active_season().split("-")[0][-2:]
                except Exception:
                    season_yr = "26"
                m.member_id = f"ALJ-{season_yr}-{idx + 1:03d}"
                members_list.append(m)
                
            self.progress.emit("Chargement terminé avec succès !", 100)
            self.finished.emit(True, members_list, "")
            
        except Exception as e:
            self.finished.emit(False, [], str(e))


class FFMEMergeWorker(QThread):
    """
    Worker asynchrone pour l'importation et la fusion de la liste des licenciés FFME.
    Pour chaque licencié non trouvé automatiquement, un signal `manual_match_requested`
    est émis (connexion bloquante) afin que l'IHM propose une fenêtre de sélection
    manuelle d'un adhérent de la base.
    """
    progress = Signal(str, int)  # (message, pourcentage)
    finished = Signal(bool, dict) # (succès, statistiques)
    # Payload : {"person": {...}, "users": [...]}
    # NB : PySide6 copie les arguments lors d'une livraison queued — la réponse
    # de l'IHM est donc écrite dans self.manual_result (objet partagé par référence).
    manual_match_requested = Signal(dict)

    def __init__(self, file_path: str, parent=None):
        super().__init__(parent)
        self.file_path = file_path
        self.manual_result = {"user_id": None}

    def run(self):
        try:
            self.progress.emit("Initialisation de l'importation FFME...", 10)
            
            import shutil
            from paths import ROOT_DIR
            
            # Définir le dossier de destination relative au ROOT_DIR
            dest_dir = os.path.join(ROOT_DIR, "import", "ffme")
            os.makedirs(dest_dir, exist_ok=True)
            
            filename = os.path.basename(self.file_path)
            dest_path = os.path.join(dest_dir, filename)
            
            self.progress.emit(f"Sauvegarde du fichier dans {os.path.join('import', 'ffme')}...", 30)
            
            # Copier si c'est un fichier externe différent
            if os.path.abspath(self.file_path) != os.path.abspath(dest_path):
                shutil.copy2(self.file_path, dest_path)
            
            self.progress.emit("Rapprochement automatique avec la base de données locale...", 60)
            
            from infrastructure.sqlite_repository import SqliteRepository
            prep = SqliteRepository.prepare_ffme_licensees(dest_path)
            stats = prep["stats"]

            if stats["errors"] and not prep["updates"]:
                self.progress.emit(f"❌ Échec du rapprochement : {stats['errors'][0]}", 100)
                self.finished.emit(False, stats)
                return

            stats.setdefault("matched_manually", 0)
            stats.setdefault("not_found", 0)

            # Association manuelle des licenciés non trouvés (fenêtre IHM, connexion bloquante)
            if prep["unmatched"]:
                self.progress.emit(
                    f"🤝 {len(prep['unmatched'])} licencié(s) FFME non trouvé(s) : association manuelle requise...", 70
                )
            for person in prep["unmatched"]:
                self.manual_result = {"user_id": None}
                self.manual_match_requested.emit({"person": person, "users": prep["users"]})
                # Connexion bloquante : on reprend ici après fermeture de la fenêtre
                user_id = self.manual_result.get("user_id")
                if user_id:
                    prep["updates"].append((
                        "Terminé", person["licence"], person.get("passeports", ""),
                        person.get("diplomes", ""), user_id
                    ))
                    stats["matched_manually"] += 1
                else:
                    stats["not_found"] = stats.get("not_found", 0) + 1

            if prep["updates"]:
                self.progress.emit("Écriture des associations dans la base de données...", 80)
                if not SqliteRepository.apply_ffme_matches(prep["updates"]):
                    stats["errors"].append("Erreur lors de l'écriture des associations en BDD.")

            if stats.get("errors"):
                self.progress.emit(f"❌ Échec de la fusion : {stats['errors'][0]}", 100)
                self.finished.emit(False, stats)
            else:
                # Téléverser automatiquement la base SQLite mise à jour vers le Google Drive
                from infrastructure.secret_store import SecretStore
                db_drive_id = SecretStore.get_secret("GOOGLE_DRIVE_DB_ID")
                if db_drive_id:
                    self.progress.emit("Synchronisation de la base SQLite sur Google Drive...", 85)
                    db_local_path = SqliteRepository.get_db_path()
                    GoogleDriveClient.upload_file(db_drive_id, db_local_path)
                    
                self.progress.emit("Fusion et mise à jour terminées !", 100)
                self.finished.emit(True, stats)
            
        except Exception as e:
            self.progress.emit(f"❌ Erreur lors de l'importation : {e}", 100)
            self.finished.emit(False, {"errors": [str(e)]})


class AutonomesMergeWorker(QThread):
    """
    Worker asynchrone pour l'importation et la fusion de la liste d'autonomie (Badge rouge / Autonomie bloc).
    """
    progress = Signal(str, int)  # (message, pourcentage)
    finished = Signal(bool, dict) # (succès, statistiques)

    def __init__(self, file_path: str, parent=None):
        super().__init__(parent)
        self.file_path = file_path

    def run(self):
        try:
            self.progress.emit("Initialisation de l'importation d'autonomie...", 10)

            import shutil
            from paths import ROOT_DIR
            from infrastructure.google_drive_client import GoogleDriveClient

            # Définir le dossier de destination relative au ROOT_DIR
            dest_dir = os.path.join(ROOT_DIR, "import", "badge rouge")
            os.makedirs(dest_dir, exist_ok=True)

            filename = os.path.basename(self.file_path)
            dest_path = os.path.join(dest_dir, filename)

            self.progress.emit(f"Sauvegarde du fichier dans {os.path.join('import', 'badge rouge')}...", 30)

            # Copier si c'est un fichier externe différent
            if os.path.abspath(self.file_path) != os.path.abspath(dest_path):
                shutil.copy2(self.file_path, dest_path)

            self.progress.emit("Lancement de la fusion avec la base de données locale...", 60)

            from infrastructure.sqlite_repository import SqliteRepository
            stats = SqliteRepository.merge_autonomes_data(dest_path)

            if stats.get("errors"):
                self.progress.emit(f"❌ Échec de la fusion : {stats['errors'][0]}", 100)
                self.finished.emit(False, stats)
            else:
                # Téléverser automatiquement la base SQLite mise à jour vers le Google Drive
                from infrastructure.secret_store import SecretStore
                db_drive_id = SecretStore.get_secret("GOOGLE_DRIVE_DB_ID")
                if db_drive_id:
                    self.progress.emit("Synchronisation de la base SQLite sur Google Drive...", 85)
                    db_local_path = SqliteRepository.get_db_path()
                    GoogleDriveClient.upload_file(db_drive_id, db_local_path)

                self.progress.emit("Fusion et mise à jour terminées !", 100)
                self.finished.emit(True, stats)

        except Exception as e:
            self.progress.emit(f"❌ Erreur lors de l'importation : {e}", 100)
            self.finished.emit(False, {"errors": [str(e)]})


class UploadDriveFileWorker(QThread):
    """
    Worker asynchrone pour téléverser la base de données SQLite locale vers Google Drive.
    """
    progress = Signal(str, int)  # (message, pourcentage)
    finished = Signal(bool, str) # (succès, message)

    def run(self):
        try:
            from infrastructure.secret_store import SecretStore
            from infrastructure.sqlite_repository import SqliteRepository
            from infrastructure.google_drive_client import GoogleDriveClient
            import os
            
            self.progress.emit("Connexion à Google Drive...", 20)
            
            db_drive_id = SecretStore.get_secret("GOOGLE_DRIVE_DB_ID")
            db_local_path = SqliteRepository.get_db_path()
            
            if not os.path.exists(db_local_path):
                self.finished.emit(False, "Fichier database.db local introuvable.")
                return
                
            if db_drive_id:
                self.progress.emit("Téléversement et mise à jour de la base sur Google Drive...", 60)
                success = GoogleDriveClient.upload_file(db_drive_id, db_local_path)
                if success:
                    self.progress.emit("Téléversement terminé avec succès !", 100)
                    self.finished.emit(True, "La base de données SQLite locale a été sauvegardée sur Google Drive.")
                else:
                    self.finished.emit(False, "Le téléversement de la base de données SQLite a échoué.")
            else:
                self.finished.emit(False, "Aucun identifiant Google Drive (DB ID) n'est configuré dans vos Paramètres.")
        except Exception as e:
            self.finished.emit(False, str(e))


class SyncGmailContactsWorker(QThread):
    """
    Worker asynchrone pour créer et synchroniser plusieurs groupes de contacts de façon individuelle dans Google Contacts.
    Chaque élément de `selected_tariffs` est soit un groupe virtuel (Adhérent, Compétition, Payeur),
    soit un groupe de créneau du planning. Dans ce dernier cas, `group_tarifs_map` fournit
    la liste des tarifs HelloAsso rattachés au créneau (un créneau peut regrouper plusieurs tarifs).
    """
    progress = Signal(str, int)  # (message, pourcentage)
    finished = Signal(bool, dict) # (succès, statistiques)

    def __init__(self, selected_tariffs: list, use_primary_email: bool = True, use_secondary_email: bool = True, use_payer_email: bool = False, group_tarifs_map: dict = None, parent=None):
        super().__init__(parent)
        self.selected_tariffs = selected_tariffs
        self.use_primary_email = use_primary_email
        self.use_secondary_email = use_secondary_email
        self.use_payer_email = use_payer_email
        self.group_tarifs_map = group_tarifs_map or {}

    def run(self):
        try:
            self.progress.emit("Initialisation de la synchronisation des contacts...", 10)
            
            from infrastructure.sqlite_repository import SqliteRepository
            from infrastructure.google_contacts_client import GoogleContactsClient
            from domain.constants import get_active_season
            
            season = get_active_season()
            year = season.split("-")[1] if "-" in season else "2027"
            
            SqliteRepository.setup_database()
            all_members = SqliteRepository.load_direct_data()
            
            global_stats = {
                "groups_processed": [],
                "total_members": 0,
                "contacts_found": 0,
                "contacts_created": 0,
                "added_to_group": 0,
                "errors": []
            }
            
            total_tariffs = len(self.selected_tariffs)
            
            for t_idx, tariff in enumerate(self.selected_tariffs):
                group_name = f"{year} {tariff.strip()}"
                base_percent = int((t_idx / total_tariffs) * 100)
                
                self.progress.emit("\n======================================", base_percent)
                self.progress.emit(f"==> Traitement du groupe [{t_idx+1}/{total_tariffs}] : '{group_name}'", base_percent)
                self.progress.emit("======================================", base_percent)
                
                selected_clean = tariff.strip().lower()
                
                # Fetch members for this specific group
                mapped_tarifs = self.group_tarifs_map.get(tariff)
                if selected_clean in ("adhérent", "payeur"):
                    group_members = all_members
                elif selected_clean == "compétition":
                    group_members = [m for m in all_members if "compétition" in str(m.get("tarif_name") or "").strip().lower()]
                elif mapped_tarifs:
                    target_set = {str(t).strip().lower() for t in mapped_tarifs}
                    group_members = [m for m in all_members if str(m.get("tarif_name") or "").strip().lower() in target_set]
                else:
                    group_members = [m for m in all_members if str(m.get("tarif_name") or "").strip().lower() == selected_clean]
                
                if not group_members:
                    self.progress.emit(f"⚠️ Aucun adhérent trouvé pour '{tariff}'. Le groupe est ignoré.", base_percent)
                    continue

                self.progress.emit(f"📋 {len(group_members)} adhérents trouvés pour ce groupe.", base_percent + 2)
                
                # Création/récupération du groupe Google
                self.progress.emit(f"🔑 Récupération/Création du groupe '{group_name}' sur votre Google Contacts...", base_percent + 5)
                group_resource = GoogleContactsClient.get_or_create_group(group_name)
                if not group_resource:
                    err_msg = f"Impossible d'obtenir/créer le groupe de contacts Google '{group_name}'."
                    self.progress.emit(f"❌ {err_msg}", base_percent + 5)
                    global_stats["errors"].append(err_msg)
                    continue

                contact_resources = []
                self.progress.emit("🔍 Analyse et synchronisation des membres dans votre annuaire Google...", base_percent + 10)
                
                for m_idx, m in enumerate(group_members):
                    first_name = (m.get("first_name") or "").strip()
                    last_name = (m.get("last_name") or "").strip().upper()
                    phone = (m.get("phone") or "").strip()
                    
                    emails_to_process = []
                    emails_added = set()
                    
                    def add_email(em, suffix):
                        em_lower = em.lower()
                        if em_lower and "@" in em_lower and em_lower not in emails_added:
                            emails_added.add(em_lower)
                            emails_to_process.append((em, suffix))
                    
                    if self.use_primary_email:
                        email1 = (m.get("email_primary") or "").strip()
                        add_email(email1, "")
                        
                    if self.use_secondary_email:
                        email2 = (m.get("email_secondary") or "").strip()
                        add_email(email2, " (2)")
                        
                    if self.use_payer_email:
                        payer = m.get("payer_email") or "".strip()
                        suffix = " (Payeur)" if len(emails_to_process) > 0 else ""
                        add_email(payer, suffix)
                    
                    if not emails_to_process:
                        continue
                    
                    for email, suffix in emails_to_process:
                        c_first_name = f"{first_name}{suffix}" if suffix else first_name
                        
                        contact_res = GoogleContactsClient.find_contact_by_email(email)
                        if contact_res:
                            global_stats["contacts_found"] += 1
                        else:
                            self.progress.emit(f"   ➕ Contact absent. Création de {c_first_name} {last_name}...", base_percent + 15)
                            contact_res = GoogleContactsClient.create_contact(c_first_name, last_name, email, phone)
                            if contact_res:
                                global_stats["contacts_created"] += 1
                                
                        if contact_res:
                            contact_resources.append(contact_res)
                
                global_stats["total_members"] += len(group_members)
                
                if contact_resources:
                    self.progress.emit(f"⚡ Liaison de {len(contact_resources)} contacts au groupe '{group_name}'...", base_percent + (80 // total_tariffs))
                    assoc_success = GoogleContactsClient.add_members_to_group(group_resource, contact_resources)
                    if assoc_success:
                        global_stats["added_to_group"] += len(contact_resources)
                        global_stats["groups_processed"].append(group_name)
                    else:
                        global_stats["errors"].append(f"Échec liaison des contacts pour {group_name}")
                else:
                    self.progress.emit(f"⚠️ Aucun contact valide final à associer au groupe '{group_name}'.", base_percent + (80 // total_tariffs))

            self.progress.emit("🎉 Synchronisation totale terminée !", 100)
            self.finished.emit(True, global_stats)
            
        except Exception as e:
            self.progress.emit(f"❌ Erreur lors de la synchronisation : {e}", 100)
            self.finished.emit(False, {"errors": [str(e)]})

class SaisonMergeWorker(QThread):
    """
    Worker asynchrone pour l'importation de fichiers d'export FFME d'anciennes saisons (Nouveau !).
    """
    progress = Signal(str, int)  # (message, pourcentage)
    finished = Signal(bool, dict) # (succès, statistiques)

    def __init__(self, file_path: str, season_name: str, parent=None):
        super().__init__(parent)
        self.file_path = file_path
        self.season_name = season_name

    def run(self):
        try:
            self.progress.emit(f"Initialisation de l'importation de la saison {self.season_name}...", 10)

            import shutil
            from paths import ROOT_DIR

            # Définir le dossier de destination
            dest_dir = os.path.join(ROOT_DIR, "import", "ffme")
            os.makedirs(dest_dir, exist_ok=True)

            filename = os.path.basename(self.file_path)
            dest_path = os.path.join(dest_dir, filename)

            self.progress.emit(f"Sauvegarde du fichier dans {os.path.join('import', 'ffme')}...", 30)

            # Copier si c'est un fichier externe différent
            if os.path.abspath(self.file_path) != os.path.abspath(dest_path):
                shutil.copy2(self.file_path, dest_path)

            self.progress.emit(f"Lancement de l'importateur multi-saisons SQLite pour la saison {self.season_name}...", 60)

            from infrastructure.sqlite_repository import SqliteRepository
            stats = SqliteRepository.import_old_season_ffme(dest_path, self.season_name)

            if stats.get("errors"):
                self.progress.emit(f"❌ Échec de l'importation : {stats['errors'][0]}", 100)
                self.finished.emit(False, stats)
            else:
                # Téléverser automatiquement la base SQLite mise à jour vers le Google Drive
                from infrastructure.secret_store import SecretStore
                from infrastructure.google_drive_client import GoogleDriveClient
                db_drive_id = SecretStore.get_secret("GOOGLE_DRIVE_DB_ID")
                if db_drive_id:
                    self.progress.emit("Synchronisation de la base SQLite sur Google Drive...", 85)
                    db_local_path = SqliteRepository.get_db_path()
                    GoogleDriveClient.upload_file(db_drive_id, db_local_path)

                self.progress.emit(f"Importation de la saison {self.season_name} terminée avec succès !", 100)
                self.finished.emit(True, stats)

        except Exception as e:
            self.progress.emit(f"❌ Erreur lors de l'importation : {e}", 100)
            self.finished.emit(False, {"errors": [str(e)]})
