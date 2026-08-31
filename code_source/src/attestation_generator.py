import os
from paths import CODE_ROOT, ROOT_DIR
import re
import datetime
import docx
import glob

def get_french_date():
    """Retourne la date du jour formatée en français (ex: '14 juillet 2026')."""
    months = {
        1: "janvier", 2: "février", 3: "mars", 4: "avril",
        5: "mai", 6: "juin", 7: "juillet", 8: "août",
        9: "septembre", 10: "octobre", 11: "novembre", 12: "décembre"
    }
    now = datetime.datetime.now()
    return f"{now.day} {months[now.month]} {now.year}"

def extract_season_from_filename(filename, default_season=None):
    """Extrait la saison (ex: 2026-2027) du nom de fichier Excel."""
    match = re.search(r"(\d{4}-\d{4})", filename)
    if match:
        return match.group(1)
    if default_season is None:
        from domain.constants import get_active_season
        return get_active_season()
    return default_season

def get_safe_filename(last_name, first_name, order_id=None):
    """Génère un nom de fichier propre et sécurisé pour l'attestation (avec ou sans identifiant unique)."""
    ln = str(last_name).strip().upper()
    fn = str(first_name).strip().capitalize()
    
    # Conserver uniquement les caractères alphanumériques, espaces, tirets et underscores
    safe_ln = "".join(c for c in ln if c.isalnum() or c in (" ", "-", "_"))
    safe_fn = "".join(c for c in fn if c.isalnum() or c in (" ", "-", "_"))
    
    # Remplacer les espaces par des underscores
    safe_ln = safe_ln.replace(" ", "_")
    safe_fn = safe_fn.replace(" ", "_")
    
    if order_id:
        clean_order = "".join(c for c in str(order_id).strip() if c.isalnum() or c in ("-", "_"))
        return f"Attestation_{safe_ln}_{safe_fn}_{clean_order}.docx"
        
    return f"Attestation_{safe_ln}_{safe_fn}.docx"

def generate_all_attestations(test_mode=False, output_format="pdf", participants_list=None):
    """
    Génère les attestations de paiement pour tous les adhérents du fichier Excel.
    
    Arguments :
    - test_mode : si True, limite la génération aux 10 premiers adhérents.
    - output_format : "pdf" (PDF uniquement), "docx" (Word uniquement), "both" (les deux).
    - participants_list : si fourni, utilise cette liste spécifique de dictionnaires d'adhérents.
    """
    print("\n--- DÉBUT DE LA GÉNÉRATION DES ATTESTATIONS ---")
    print(f"Format demandé : {output_format.upper()}")
    
    # 1. Récupération des données d'adhésion via ExcelRepository ou la liste fournie
    if participants_list is not None:
        participants = participants_list
        print(f"Génération d'attestations pour un lot de {len(participants)} adhérents sélectionnés.")
    else:
        try:
            from infrastructure.excel_repository import ExcelRepository
            from domain.constants import get_corrective_files_pattern
            
            pattern = os.path.join(CODE_ROOT, get_corrective_files_pattern())
            files = glob.glob(pattern)
            if not files:
                raise FileNotFoundError(f"Aucun fichier d'adhésion correspondant au motif {get_corrective_files_pattern()} n'a été trouvé.")
            
            files.sort(key=os.path.getmtime, reverse=True)
            latest_file = files[0]
            print(f"Chargement des données d'adhésion depuis : {os.path.basename(latest_file)}")
            participants = ExcelRepository.load_direct_data(latest_file)
        except Exception as e:
            print(f"[ERREUR] Impossible de charger les données du fichier d'adhésion : {e}")
            return
        
    if not participants:
        print("[ERREUR] Aucun adhérent trouvé dans le fichier Excel d'adhésions.")
        return
        
    # 2. Détermination de la saison à partir du fichier Excel d'adhésions actuel
    from domain.constants import get_corrective_files_pattern
    root_dir = ROOT_DIR
    corrective_files = glob.glob(os.path.join(CODE_ROOT, get_corrective_files_pattern()))
    excel_filename = os.path.basename(corrective_files[0]) if corrective_files else ""
    season = extract_season_from_filename(excel_filename)
    print(f"Saison détectée : {season}")
    
    # 3. Création du dossier /attestation s'il n'existe pas dans la racine
    output_dir = os.path.join(root_dir, "exports", "attestation")
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        print(f"Dossier de destination créé : {output_dir}")
    else:
        print(f"Dossier de destination utilisé : {output_dir}")
        
    # 4. Vérification des chemins de modèles
    template_path_docx = os.path.join(root_dir, "doc", "ATTESTATION DE PAIEMENT_adulte.docx")
    template_path_html = os.path.join(root_dir, "doc", "ATTESTATION_TEMPLATE.html")
    
    if output_format in ("docx", "both") and not os.path.exists(template_path_docx):
        print(f"[ERREUR] Modèle Word d'attestation introuvable : {template_path_docx}")
        return
    if output_format in ("pdf", "both") and not os.path.exists(template_path_html):
        print(f"[ERREUR] Modèle HTML d'attestation introuvable : {template_path_html}")
        return
        
    # 5. Initialisation du moteur de rendu PDF Chromium si applicable
    web_page = None
    if output_format in ("pdf", "both"):
        try:
            print("Démarrage du moteur de rendu PDF Chromium (PySide6) en arrière-plan...")
            from PySide6.QtWidgets import QApplication
            from PySide6.QtWebEngineCore import QWebEnginePage
            
            # S'assurer qu'une QApplication existe (obligatoire pour Qt)
            app = QApplication.instance() or QApplication([])
            web_page = QWebEnginePage()
        except Exception as e:
            print(f"[ERREUR] Impossible de charger le moteur PDF PySide6 : {e}")
            print("⚠️ Repli sur la génération Word (.docx) uniquement.")
            output_format = "docx"
            
    try:
        # 6. Filtrage des données si mode test
        if test_mode:
            print("⚠️ Mode Test activé : génération limitée aux 10 premiers adhérents.")
            participants_to_process = participants[:10]
        else:
            participants_to_process = participants
            
        total_to_process = len(participants_to_process)
        generated_count = 0
        skipped_count = 0
        error_count = 0
        
        date_jour_fr = get_french_date()
        
        for idx, member in enumerate(participants_to_process, 1):
            try:
                # Récupérer les informations de l'adhérent
                user_last = member.get("user_lastName") or "".strip()
                user_first = member.get("user_firstName") or "".strip()
                
                # S'il n'y a pas d'adhérent valide (nom et prénom vides), on passe
                if not user_last and not user_first:
                    continue
                    
                # Infos payeur (par défaut l'adhérent s'il n'y a pas d'infos payeur distinctes)
                payer_last = member.get("payer_lastName") or "".strip() or user_last
                payer_first = member.get("payer_firstName") or "".strip() or user_first
                
                # Montant payé et filtrage si 0 €
                amount = member.get("amount", 0.0)
                try:
                    amount_val = float(amount)
                except (ValueError, TypeError):
                    amount_val = 0.0
                    
                if amount_val == 0.0:
                    print(f"[{idx}/{total_to_process}] ⏭️ Passé (Montant de 0 €) : {user_last.upper()} {user_first.capitalize()}")
                    skipped_count += 1
                    continue
                    
                status = str(member.get("status") or "").lower()
                if "annul" in status:
                    print(f"[{idx}/{total_to_process}] ⏭️ Passé (Commande annulée) : {user_last.upper()} {user_first.capitalize()}")
                    skipped_count += 1
                    continue
                    
                if isinstance(amount, float) and amount.is_integer():
                    amount_str = str(int(amount))
                else:
                    amount_str = f"{amount:.2f}".replace(".00", "")
                    
                # Formater les noms
                user_last_format = user_last.upper()
                user_first_format = user_first.capitalize()
                payer_last_format = payer_last.upper()
                payer_first_format = payer_first.capitalize()
                
                # Nom de fichier de l'attestation avec identifiant de commande pour l'unicité
                order_ref = member.get("order_ref") or ""
                filename_docx = get_safe_filename(user_last_format, user_first_format, order_ref)
                filename_pdf = filename_docx.replace(".docx", ".pdf")
                
                file_path_docx = os.path.join(output_dir, filename_docx)
                file_path_pdf = os.path.join(output_dir, filename_pdf)
                
                # Vérifier si les fichiers correspondants existent déjà
                skip = False
                if participants_list is None:
                    if output_format == "docx" and os.path.exists(file_path_docx):
                        skip = True
                    elif output_format == "pdf" and os.path.exists(file_path_pdf):
                        skip = True
                    elif output_format == "both" and os.path.exists(file_path_docx) and os.path.exists(file_path_pdf):
                        skip = True
                    
                if skip:
                    print(f"[{idx}/{total_to_process}] ⏭️ Passé (existe déjà) : {filename_pdf if output_format == 'pdf' else filename_docx}")
                    skipped_count += 1
                    continue
                    
                # Étape 1 : Sauvegarde du fichier DOCX s'il est demandé
                if output_format in ("docx", "both"):
                    doc = docx.Document(template_path_docx)
                    
                    # Remplacement des variables dans tous les paragraphes du document
                    for p in doc.paragraphs:
                        if "{" in p.text:
                            orig_size = None
                            orig_name = None
                            for r in p.runs:
                                if r.font.size:
                                    orig_size = r.font.size
                                if r.font.name:
                                    orig_name = r.font.name
                                    
                            p_text = p.text
                            p_text = p_text.replace("{Date du jour}", date_jour_fr)
                            p_text = p_text.replace("{Nom payeur}", payer_last_format)
                            p_text = p_text.replace("{prénom payeur}", payer_first_format)
                            p_text = p_text.replace("{Nom adhérent}", user_last_format)
                            p_text = p_text.replace("{Prénom adhérent}", user_first_format)
                            p_text = p_text.replace("{Montant}", amount_str)
                            p_text = p_text.replace("{Saison}", season)
                            p.text = p_text
                            
                            final_size = orig_size or docx.shared.Pt(12)
                            for r in p.runs:
                                r.font.size = final_size
                                if orig_name:
                                    r.font.name = orig_name
                            
                    doc.save(file_path_docx)
                
                # Étape 2 : Conversion en PDF s'il est demandé (via rendu Chromium)
                if output_format in ("pdf", "both") and web_page:
                    with open(template_path_html, "r", encoding="utf-8") as f:
                        html_content = f.read()
                        
                    html_content = html_content.replace("{Date du jour}", date_jour_fr)
                    html_content = html_content.replace("{Nom payeur}", payer_last_format)
                    html_content = html_content.replace("{prénom payeur}", payer_first_format)
                    html_content = html_content.replace("{Nom adhérent}", user_last_format)
                    html_content = html_content.replace("{Prénom adhérent}", user_first_format)
                    html_content = html_content.replace("{Montant}", amount_str)
                    html_content = html_content.replace("{Saison}", season)
                    
                    # Event loop pour l'asynchronisme de QtWebEngine
                    from PySide6.QtCore import QEventLoop, QUrl, QMarginsF
                    from PySide6.QtGui import QPageLayout, QPageSize
                    
                    # Base URL pour résoudre logo.png à la racine
                    base_url = QUrl.fromLocalFile(os.path.join(root_dir, "logo.png"))
                    
                    loop = QEventLoop()
                    web_page.loadFinished.connect(lambda ok: loop.quit())
                    web_page.setHtml(html_content, base_url)
                    loop.exec()
                    
                    pdf_loop = QEventLoop()
                    pdf_success = False
                    
                    def handle_pdf_finished(path, success):
                        nonlocal pdf_success
                        pdf_success = success
                        pdf_loop.quit()
                        
                    conn = web_page.pdfPrintingFinished.connect(handle_pdf_finished)
                    
                    layout = QPageLayout(
                        QPageSize(QPageSize.PageSizeId.A4),
                        QPageLayout.Orientation.Portrait,
                        QMarginsF(0, 0, 0, 0),  # L'HTML gère les marges de façon native via le padding du body
                        QPageLayout.Unit.Millimeter
                    )
                    
                    web_page.printToPdf(file_path_pdf, layout)
                    pdf_loop.exec()
                    
                    web_page.pdfPrintingFinished.disconnect(conn)
                    
                    if not pdf_success:
                        raise Exception("Échec de l'impression PDF via Chromium.")
                            
                # Log de succès
                if output_format == "both":
                    print(f"[{idx}/{total_to_process}] ✅ Généré (Word & PDF) : {filename_docx[:-5]}")
                elif output_format == "pdf":
                    print(f"[{idx}/{total_to_process}] ✅ Généré (PDF uniquement) : {filename_pdf}")
                else:
                    print(f"[{idx}/{total_to_process}] ✅ Généré (Word uniquement) : {filename_docx}")
                    
                generated_count += 1
                
            except Exception as member_err:
                print(f"[ERREUR] Échec de la génération pour {member.get('user_lastName')} {member.get('user_firstName')} : {member_err}")
                error_count += 1
                
    finally:
        # Libération des ressources de rendu
        if web_page:
            try:
                web_page.deleteLater()
            except Exception:
                pass
            
    print("\n--- BILAN DE LA GÉNÉRATION ---")
    print(f"Adhérents traités : {total_to_process}")
    print(f"Attestations générées avec succès : {generated_count}")
    print(f"Attestations ignorées (déjà existantes) : {skipped_count}")
    if error_count > 0:
        print(f"Attestations en échec : {error_count}")
    print("------------------------------------------\n")
