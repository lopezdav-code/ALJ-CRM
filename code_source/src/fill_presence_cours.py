import os
import glob
import shutil
import datetime
import pandas as pd
import openpyxl
from openpyxl.styles import Border, Side, PatternFill, Font, Alignment

from paths import ROOT_DIR

# Configuration paths
COURS_PATH = os.path.join(ROOT_DIR, "liste adhérent", "Cours.xlsx")
BACKUP_PATH = os.path.join(ROOT_DIR, "liste adhérent", "Cours - Template-Vide.xlsx")
REPORT_PATH = os.path.join(ROOT_DIR, "liste adhérent", "Rapport_Remplissage_Cours.md")

# Weekday names mapping
DAYS_OF_WEEK = ['lundi', 'mardi', 'mercredi', 'jeudi', 'vendredi', 'samedi', 'dimanche']

# Tariff mapping dictionary for all 19 sections in Cours.xlsx
# The keys are normalized tuples of: (day, time, title)
# Values are lists of HelloAsso tariff names.
SECTION_TARIFFS_MAP = {
    # Lundi (Monday) [Columns A & B]
    ("lundi", "18h20h", "competitionu11u13"): [
        "Compétition U11 U13 - enfants nés en 2015, 2016, 2017, 2018"
    ],
    ("lundi", "18h20h30", "competitionu15u19"): [
        "Compétition U15 U17 U19- jeunes nés en 2009, 2010, 2011, 2012, 2013, 2014",
        "Compétition U15 U17 - jeunes nés en 2011, 2012, 2013, 2014"
    ],
    ("lundi", "17h3018h30", "enfant20192020"): [
        # Monday class has no registrations in database
    ],
    ("lundi", "18h3020h00", "collegiens"): [
        "Loisir collège - jeunes nés en 2012, 2013, 2014, 2015 - lundi 18h30"
    ],
    
    # Mardi (Tuesday) [Columns AO & AP]
    ("mardi", "18h3020h", "lyceens"): [
        "Loisir lycée - jeunes nés en 2009, 2010, 2011"
    ],
    ("mardi", "20h22h", "adulte"): [
        "Cours Adultes débutants"
    ],
    
    # Mercredi (Wednesday) [Columns CB & CC]
    ("mercredi", "16h18h", "competitionu11u13"): [
        "Compétition U11 U13 - enfants nés en 2015, 2016, 2017, 2018"
    ],
    ("mercredi", "18h20h", "competitionu11u13"): [ # Pour compatibilité avec l'ancienne typo du template
        "Compétition U15 U17 U19- jeunes nés en 2009, 2010, 2011, 2012, 2013, 2014",
        "Compétition U15 U17 - jeunes nés en 2011, 2012, 2013, 2014"
    ],
    ("mercredi", "18h20h", "competitionu15u19"): [ # Si corrigé en Compétition U15-U19
        "Compétition U15 U17 U19- jeunes nés en 2009, 2010, 2011, 2012, 2013, 2014",
        "Compétition U15 U17 - jeunes nés en 2011, 2012, 2013, 2014"
    ],
    ("mercredi", "18h20h", "competitionu15u17u19"): [ # Si corrigé en Compétition U15-U17-U19
        "Compétition U15 U17 U19- jeunes nés en 2009, 2010, 2011, 2012, 2013, 2014",
        "Compétition U15 U17 - jeunes nés en 2011, 2012, 2013, 2014"
    ],
    ("mercredi", "20h22h", "blocu19adulteperf"): [
        "Cours perfectionnement BLOC + Difficulté - U19 et adultes",
        "Cours perfectionnement BLOC - U19 et adultes"
    ],
    ("mercredi", "09h3010h30", "enfants20192020"): [
        "Loisir enfants nés en 2019, 2020 - mercredi 9h30"
    ],
    ("mercredi", "10h3012h", "enfants20162018"): [
        "Loisir enfants nés en 2016, 2017, 2018 - mercredi 10h30"
    ],
    ("mercredi", "13h14h30", "perfu11u13"): [
        "Perfectionnement U11 U13 (1)- enfants nés en 2016, 2017, 2018"
    ],
    ("mercredi", "16h17h", "enfants20192020"): [
        "Loisir enfants nés en 2019, 2020 - mercredi 16h"
    ],
    ("mercredi", "13h14h30", "collegiens"): [
        "Loisir collège - jeunes nés en 2012, 2013, 2014, 2015 - mercredi 13h"
    ],
    ("mercredi", "14h3016h", "enfants20162018"): [
        "Loisir enfants nés en 2016, 2017, 2018 - mercredi 14h30"
    ],
    ("mercredi", "14h3016h", "perfu13u17"): [
        "Perfectionnement U13(2) U15 U17 nés 2011, 2012, 2013, 2014, 2015"
    ],
    
    # Vendredi (Friday) [Columns DP & DQ]
    ("vendredi", "18h20h", "competitionu11u13"): [
        "Compétition U11 U13 - enfants nés en 2015, 2016, 2017, 2018"
    ],
    ("vendredi", "18h20h30", "competitionu15u19"): [
        "Compétition U15 U17 U19- jeunes nés en 2009, 2010, 2011, 2012, 2013, 2014",
        "Compétition U15 U17 - jeunes nés en 2011, 2012, 2013, 2014"
    ],
    ("vendredi", "20h22h", "diffu19adulteperf"): [
        "Cours perfectionnement BLOC + Difficulté - U19 et adultes",
        "Cours perfectionnement Difficulté - U19 et adultes"
    ]
}

from domain.utils import normalize_string, normalize_key_part

def find_latest_database():
    """Locate the latest HelloAsso_Admin_*.xlsx database file in the import/helloAsso directory."""
    import_dir = os.path.join(ROOT_DIR, "import", "helloAsso")
    excel_files = glob.glob(os.path.join(import_dir, "HelloAsso_Admin_*.xlsx"))
    if not excel_files:
        # Fallback to root just in case
        excel_files = glob.glob(os.path.join(ROOT_DIR, "HelloAsso_Admin_*.xlsx"))
        if not excel_files:
            return None
    return max(excel_files, key=os.path.getmtime)

def get_expected_tariffs(day, time, title):
    """Find matching HelloAsso tariffs in the map using normalized keys."""
    key = (normalize_key_part(day), normalize_key_part(time), normalize_key_part(title))
    return SECTION_TARIFFS_MAP.get(key, [])

def audit_prefilled_members(prefilled_sections, df_db):
    """
    Compare the prefilled names in the original template to the database.
    Return list of audits and discrepancies found.
    """
    audit_results = []
    
    # Pre-index database by normalized name for fast lookup
    db_by_name = {}
    for idx, row in df_db.iterrows():
        norm_key = (normalize_string(row['user_lastName']), normalize_string(row['user_firstName']))
        db_by_name[norm_key] = row
        
    for idx_sec, sec in enumerate(prefilled_sections, 1):
        sec_title = sec['title']
        sec_day = sec['day']
        sec_time = sec['time']
        
        expected_tariffs = get_expected_tariffs(sec_day, sec_time, sec_title)
        expected_tariffs_norm = [normalize_string(t) for t in expected_tariffs]
        
        for last_name, first_name, row_num in sec['names']:
            # Skip Excel formulas (e.g. =$A5, =$B5)
            if str(last_name).startswith("="):
                continue
                
            norm_key = (normalize_string(last_name), normalize_string(first_name))
            
            if norm_key in db_by_name:
                db_row = db_by_name[norm_key]
                db_status = str(db_row['status']).strip()
                db_tariff = str(db_row['tarif_name']).strip()
                
                # Check status
                status_ok = "annul" not in db_status.lower()
                
                # Check tariff match
                tariff_ok = False
                for t in expected_tariffs_norm:
                    if t in normalize_string(db_tariff):
                        tariff_ok = True
                        break
                        
                if not status_ok:
                    audit_results.append({
                        "type": "WARNING",
                        "section": f"{sec_day} {sec_time} - {sec_title}",
                        "name": f"{first_name} {last_name} (Ligne {row_num})",
                        "msg": f"Présent dans le template mais son inscription est '{db_status}' dans la base !"
                    })
                elif not tariff_ok and expected_tariffs:
                    audit_results.append({
                        "type": "WARNING",
                        "section": f"{sec_day} {sec_time} - {sec_title}",
                        "name": f"{first_name} {last_name} (Ligne {row_num})",
                        "msg": f"Présent dans le template mais enregistré sous le tarif '{db_tariff}' dans la base !"
                    })
                else:
                    audit_results.append({
                        "type": "OK",
                        "section": f"{sec_day} {sec_time} - {sec_title}",
                        "name": f"{first_name} {last_name}",
                        "msg": "Correspondance parfaite"
                    })
            else:
                audit_results.append({
                    "type": "ERROR",
                    "section": f"{sec_day} {sec_time} - {sec_title}",
                    "name": f"{first_name} {last_name} (Ligne {row_num})",
                    "msg": "Présent dans le template de test mais INTROUVABLE dans la base de données !"
                })
                
    return audit_results

def main():
    print("🚀 Démarrage du processus global de remplissage (Colonnes A à FC)...")
    
    # 1. Définir les chemins de template et de sortie dynamique
    template_path = BACKUP_PATH
    old_default_path = os.path.join(ROOT_DIR, "liste adhérent", "Cours.xlsx")
    
    print(f"📋 Modèle (Template) utilisé pour le remplissage : {template_path}")
    
    now_dt = datetime.datetime.now()
    date_str = now_dt.strftime("%Y%m%d")
    time_str = now_dt.strftime("%H%M%S")
    new_filename = f"Cours-{date_str}-{time_str}.xlsx"
    
    global COURS_PATH
    COURS_PATH = os.path.join(ROOT_DIR, "liste adhérent", new_filename)
    
    # 2. S'assurer de la présence du template d'origine
    if not os.path.exists(template_path):
        if os.path.exists(old_default_path):
            shutil.copy2(old_default_path, template_path)
            print(f"💾 Sauvegarde de sécurité créée sous : {template_path}")
            print("💾 Sauvegarde de sécurité créée sous : Cours_Original_Backup.xlsx")
        else:
            print(f"❌ [ERREUR] Le fichier template '{template_path}' est introuvable !")
            return None
            
    # 3. Déplacer l'ancien Cours.xlsx et les anciens Cours-*.xlsx dans le dossier d'archives
    archive_dir = os.path.join(ROOT_DIR, "liste adhérent", "archive")
    os.makedirs(archive_dir, exist_ok=True)
    
    if os.path.exists(old_default_path):
        try:
            mtime = os.path.getmtime(old_default_path)
            old_time_str = datetime.datetime.fromtimestamp(mtime).strftime("%Y%m%d_%H%M%S")
            shutil.move(old_default_path, os.path.join(archive_dir, f"Cours_Ancien_{old_time_str}.xlsx"))
            print("📦 Ancien fichier Cours.xlsx déplacé vers le dossier archive/ !")
        except Exception as e:
            print(f"⚠️ Impossible de déplacer l'ancien fichier de cours : {e}")
            
    for f in glob.glob(os.path.join(ROOT_DIR, "liste adhérent", "Cours-*.xlsx")):
        # Ne pas déplacer le fichier en cours d'écriture
        if f != COURS_PATH:
            try:
                shutil.move(f, os.path.join(archive_dir, os.path.basename(f)))
            except Exception:
                pass

    # 4. Copier le template propre pour notre nouvelle exécution
    shutil.copy2(template_path, COURS_PATH)
    print(f"📝 Nouveau fichier de cours créé : {new_filename}")
        
    # 4. Charger les adhérents directement depuis la base SQLite locale
    try:
        from infrastructure.sqlite_repository import SqliteRepository
        db_path = SqliteRepository.get_db_path()
        raw_data = SqliteRepository.load_direct_data(season_filter="2026-2027")
        df_db = pd.DataFrame(raw_data)
        
        # Filtrer pour ne garder que les inscriptions validées (exclure annulé)
        df_valid = df_db[~df_db["status"].astype(str).str.lower().str.contains("annul", na=False)].copy()
        print(f"👥 {len(df_valid)} adhésions validées chargées depuis la base SQLite.")
    except Exception as e:
        print(f"❌ [ERREUR] Impossible de charger la base de données SQLite : {e}")
        return None
        
    # Load workbook
    try:
        wb = openpyxl.load_workbook(COURS_PATH)
        ws = wb['Feuil1']
    except Exception as e:
        print(f"❌ [ERREUR] Impossible de charger le fichier {new_filename} : {e}")
        return None
        
    # Scan the spreadsheet to discover ALL 19 table headers
    table_headers = []
    for r in range(1, 225):
        for c in range(1, 165):
            val_a = ws.cell(row=r, column=c).value
            val_b = ws.cell(row=r, column=c+1).value
            if val_a == "Nom" and val_b == "Prénom":
                table_headers.append((r, c))
                
    print(f"🔍 {len(table_headers)} en-têtes 'Nom/Prénom' identifiés dans le document.")
    
    sections = []
    for r_hdr, c_hdr in table_headers:
        col_letter_nom = openpyxl.utils.get_column_letter(c_hdr)
        col_letter_prenom = openpyxl.utils.get_column_letter(c_hdr+1)
        
        # Scan upwards to find the section header (title, day, time, coach)
        title = None
        day = None
        time = None
        coach = None
        header_row = None
        
        for r_check in range(r_hdr - 1, max(0, r_hdr - 5), -1):
            for c_check in range(c_hdr, c_hdr + 25):
                cell_val = ws.cell(row=r_check, column=c_check).value
                if cell_val and str(cell_val).strip().lower() in DAYS_OF_WEEK:
                    day = str(cell_val).strip()
                    time = ws.cell(row=r_check+1, column=c_check).value
                    header_row = r_check
                    break
            if day:
                break
                
        if header_row:
            title = ws.cell(row=header_row, column=c_hdr + 4).value
            coach = ws.cell(row=header_row, column=c_hdr + 11).value
        else:
            header_row = r_hdr - 3 if r_hdr > 3 else r_hdr - 2
            title = ws.cell(row=header_row, column=c_hdr + 4).value
            
        # Collect prefilled names
        names = []
        r_data = r_hdr + 1
        while r_data < 225:
            if ws.cell(row=r_data, column=c_hdr).value == "Nom":
                break
            is_new_sec = False
            for c_check in range(c_hdr, c_hdr + 25):
                v_check = ws.cell(row=r_data, column=c_check).value
                if v_check and str(v_check).strip().lower() in DAYS_OF_WEEK:
                    is_new_sec = True
                    break
            if is_new_sec:
                break
                
            val_last = ws.cell(row=r_data, column=c_hdr).value
            val_first = ws.cell(row=r_data, column=c_hdr+1).value
            if val_last or val_first:
                names.append((val_last, val_first, r_data))
            else:
                consecutive_empty = 0
                for r_temp in range(r_data, min(r_data + 5, 225)):
                    if not ws.cell(row=r_temp, column=c_hdr).value and not ws.cell(row=r_temp, column=c_hdr+1).value:
                        consecutive_empty += 1
                    else:
                        break
                if consecutive_empty >= 5:
                    break
            r_data += 1
            
        sections.append({
            'title': title,
            'coach': coach,
            'day': day,
            'time': time,
            'col_start': c_hdr,
            'col_letter_nom': col_letter_nom,
            'col_letter_prenom': col_letter_prenom,
            'table_header_row': r_hdr,
            'data_start': r_hdr + 1,
            'names': names,
            'header_row': header_row or r_hdr
        })
        
    # 6. Run audit of prefilled names
    print("🔍 Exécution de l'audit de cohérence sur l'ensemble des 19 sections...")
    audit_results = audit_prefilled_members(sections, df_db)
    
    # 7. Modify Excel and write names
    print("✍️ Remplissage des cases par groupe tarifaire...")
    
    # Styles for Excel cells (matching template exactly)
    thin_gray = Side(style='thin', color='CCCCCC')
    border_cell_thin = Border(left=thin_gray, right=thin_gray, top=thin_gray, bottom=thin_gray)
    fill_zebra_light_gray = PatternFill(start_color="EAEAEA", end_color="EAEAEA", fill_type="solid")
    fill_white = PatternFill(start_color="FFFFFF", end_color="FFFFFF", fill_type="solid")
    font_student_name = Font(name="Segoe UI", size=9, bold=False, color="1F2937")
    align_left = Alignment(horizontal="left", vertical="center")
    align_center = Alignment(horizontal="center", vertical="center")
    
    missing_sections = []
    section_stats = []
    possible_errors = []
    active_ranges = []  # Liste pour stocker les plages d'impression des cours actifs (Nouveau !)
    
    for idx_sec, sec in enumerate(sections):
        title = sec['title']
        day = sec['day']
        time = sec['time']
        col_start = sec['col_start']
        data_start = sec['data_start']
        table_hdr = sec['table_header_row']
        
        # Calculate row limit for this section in its specific column block
        # Find other sections in the same column block situated below this one
        same_col_below = [s for s in sections if s['col_start'] == col_start and s['header_row'] > sec['header_row']]
        if same_col_below:
            limit_row = min(s['header_row'] for s in same_col_below) - 2
        else:
            limit_row = sec['header_row'] + 60 # Le cours situé tout en bas d'un bloc de jour peut s'étendre dynamiquement jusqu'à 60 lignes au besoin ! (Nouveau !)
            
        # Get expected tariffs for this section
        mapped_tariffs = get_expected_tariffs(day, time, title)
        
        # Filter DB members for this section
        section_members = []
        if mapped_tariffs:
            for tariff in mapped_tariffs:
                matches = df_valid[df_valid['tarif_name'].str.strip() == tariff]
                for _, row in matches.iterrows():
                    section_members.append({
                        "firstName": str(row['user_firstName']).strip(),
                        "lastName": str(row['user_lastName']).strip()
                    })
        else:
            if title not in ["Enfant 2019-2020"]: # Skip Enfant 2019-2020 on Monday since we know it has no tariff
                missing_sections.append(f"{day} {time} - {title}")
                
        # Sort members alphabetically by last name then first name
        section_members.sort(key=lambda m: (m['lastName'].lower(), m['firstName'].lower()))
        num_members = len(section_members)
        
        # Detect active date columns by scanning the table header row starting from col_start + 2
        date_cols = []
        col = col_start + 2
        while ws.cell(row=table_hdr, column=col).value is not None:
            date_cols.append(col)
            col += 1
            if col > 200: # Safeguard
                break
                
        # Determine capacity and formatted rows
        capacity = limit_row - data_start + 1
        num_formatted_rows = min(num_members + 3, capacity)
        
        # Clear values first in Column col_start and col_start+1 for all rows in this section's range
        for r in range(data_start, limit_row + 1):
            ws.cell(row=r, column=col_start).value = None
            ws.cell(row=r, column=col_start + 1).value = None
            
        # If section is Wednesday 18h-20h, flag the title typo
        if day == "Mercredi" and time == "18h-20h" and title == "Compétition U11-U13":
            possible_errors.append("La section Mercredi 18h-20h a un titre erroné dans Excel ('Compétition U11-U13' au lieu de 'U15-U19'). Les adhérents Compétition U15-U19 ont bien été importés dedans conformément au planning.")

        # Check for capacity overflow
        if num_members > capacity:
            msg = f"Capacité dépassée pour {day} {time} - {title} : {num_members} adhérents pour {capacity} places."
            print(f"🚨 [ERREUR] {msg}")
            possible_errors.append(msg)
            section_members = section_members[:capacity]
            num_members = len(section_members)
            num_formatted_rows = capacity
            
        # 1. Fill active member rows
        for i, member in enumerate(section_members):
            curr_row = data_start + i
            
            first_cap = member['firstName'].capitalize()
            last_up = member['lastName'].upper()
            
            cell_last = ws.cell(row=curr_row, column=col_start, value=last_up)
            cell_first = ws.cell(row=curr_row, column=col_start + 1, value=first_cap)
            
            is_zebra = (curr_row % 2 == 0)
            row_fill = fill_zebra_light_gray if is_zebra else fill_white
            
            # Style name columns
            for cell in (cell_last, cell_first):
                cell.font = font_student_name
                cell.fill = row_fill
                cell.alignment = align_left
                cell.border = border_cell_thin
                
            # Style date columns
            for col in date_cols:
                c_cell = ws.cell(row=curr_row, column=col)
                c_cell.fill = row_fill
                c_cell.border = border_cell_thin
                
        # 2. Add extra blank formatted rows for manual hand-writing
        for i in range(num_members, num_formatted_rows):
            curr_row = data_start + i
            is_zebra = (curr_row % 2 == 0)
            row_fill = fill_zebra_light_gray if is_zebra else fill_white
            
            for col_idx in (col_start, col_start + 1):
                cell = ws.cell(row=curr_row, column=col_idx)
                cell.value = None
                cell.font = font_student_name
                cell.fill = row_fill
                cell.alignment = align_left
                cell.border = border_cell_thin
                
            for col in date_cols:
                c_cell = ws.cell(row=curr_row, column=col)
                c_cell.fill = row_fill
                c_cell.border = border_cell_thin
                
        # 3. Clean formatting for completely unused rows below
        for curr_row in range(data_start + num_formatted_rows, limit_row + 1):
            for col_idx in range(col_start, (max(date_cols) + 1 if date_cols else col_start + 3)):
                cell = ws.cell(row=curr_row, column=col_idx)
                cell.value = None
                cell.border = Border()
                cell.fill = PatternFill(fill_type=None)
                
        section_stats.append({
            "title": f"{day} {time} - {title}",
            "day": day,
            "time": time,
            "course_title": title,
            "count": num_members,
            "capacity": capacity,
            "formatted_empty": num_formatted_rows - num_members
        })
        print(f"✅ Section {sec['col_letter_nom']} ({day} {time}) mise à jour : {num_members} adhérents (+{num_formatted_rows - num_members} lignes de réserve)")

        # Calculer la plage d'impression active utile pour cette section (Nouveau !)
        if num_members > 0:
            col_start_letter = openpyxl.utils.get_column_letter(col_start)
            col_end_letter = openpyxl.utils.get_column_letter(max(date_cols) if date_cols else col_start + 3)
            row_start = sec['header_row'] - 1
            row_end = data_start + num_formatted_rows - 1
            sec_range = f"{col_start_letter}{row_start}:{col_end_letter}{row_end}"
            active_ranges.append(sec_range)

    # 7.5 Supprimer l'onglet de résumé pour n'avoir que l'onglet principal Feuil1 (votre demande !)
    try:
        if "Résumé Effectifs" in wb.sheetnames:
            del wb["Résumé Effectifs"]
            print("💡 [SQLITE] Onglet 'Résumé Effectifs' supprimé du classeur Excel.")
    except Exception as e_del_res:
        print(f"⚠️ [SYSTEM] Impossible de supprimer l'onglet de résumé : {e_del_res}")

    # 7.5 Optimisation dynamique de la mise en page pour l'impression (Masquage des lignes vides) (Nouveau !)
    try:
        # Collecter toutes les colonnes de noms/prénoms des sections et les lignes d'en-tête
        student_cols = set()
        header_rows = set()
        for sec in sections:
            student_cols.add(sec['col_start'])
            student_cols.add(sec['col_start'] + 1)
            header_rows.add(sec['table_header_row'])
            header_rows.add(sec['header_row'])
            header_rows.add(sec['header_row'] - 1)
            header_rows.add(sec['header_row'] - 2)
            
        # Trouver la feuille d'origine
        ws_grid = wb['Feuil1']
        
        # Parcourir les lignes de données de la ligne 5 à 220
        for r in range(5, 221):
            # Si c'est une ligne d'en-tête ou de titre, on la garde visible
            if r in header_rows:
                continue
                
            # Vérifier si cette ligne contient un nom d'élève
            has_student_on_row = False
            for c in student_cols:
                val = ws_grid.cell(row=r, column=c).value
                if val is not None and str(val).strip() != "":
                    has_student_on_row = True
                    break
                    
            if has_student_on_row:
                continue
                
            # Si elle est vide, on vérifie si l'une des 3 lignes précédentes contenait un élève (pour garder 3 lignes de réserve)
            has_student_nearby = False
            for r_prev in range(max(5, r - 3), r):
                for c in student_cols:
                    val = ws_grid.cell(row=r_prev, column=c).value
                    if val is not None and str(val).strip() != "":
                        has_student_nearby = True
                        break
                if has_student_nearby:
                    break
                    
            if not has_student_nearby:
                # Masquer la ligne vide superflue !
                ws_grid.row_dimensions[r].hidden = True
                
        print("💡 [SQLITE] Les lignes vides superflues ont été masquées dynamiquement dans l'onglet Feuil1 pour éliminer les pages blanches.")
    except Exception as e_hide:
        print(f"⚠️ [SYSTEM] Impossible de masquer les lignes vides : {e_hide}")

    # Save Excel changes
    try:
        wb.save(COURS_PATH)
        print(f"🎉 Fichier Excel enregistré avec succès : {os.path.basename(COURS_PATH)}")
    except Exception as e:
        print(f"❌ [ERREUR] Impossible d'enregistrer le fichier Excel : {e}")
        possible_errors.append(f"Impossible de sauvegarder le fichier de sortie: {e}")
        return

    # 8. Generate markdown report
    generate_report(db_path, audit_results, section_stats, missing_sections, possible_errors)
    return section_stats

def generate_report(db_path, audit_results, section_stats, missing_sections, possible_errors):
    """Generate a structured Markdown report of the import process."""
    
    print("\n📝 Génération du rapport de remplissage global...")
    
    now_str = datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    cours_filename = os.path.basename(COURS_PATH)
    
    report_content = f"""# Rapport de Remplissage Global des Feuilles de Présence (Cours A3)

Généré le : **{now_str}**
Base de données source : `{os.path.basename(db_path)}`
Nouveau fichier de cours généré : `liste adhérent/{cours_filename}`
Fichier modèle de base utilisé : `liste adhérent/Cours - Template-Vide.xlsx`
Historique des anciennes feuilles archivé dans : `liste adhérent/archive/`

---

## 📊 Statistiques de Remplissage (19 sections)

| Section dans Excel | Nombre d'Adhérents Importés | Lignes Vides de Réserve | Capacité Totale du Tableau | Statut Mapping |
| :--- | :---: | :---: | :---: | :--- |
"""
    
    for stat in section_stats:
        status_str = "Mise à jour réussie" if stat['count'] > 0 else "Aucun inscrit"
        report_content += f"| **{stat['title']}** | {stat['count']} | {stat['formatted_empty']} | {stat['capacity']} | {status_str} |\n"
        
    report_content += """
---

## 🔍 Rapport d'Audit & Cohérence (Données de test initiales)
Ce rapport analyse les noms préremplis par l'utilisateur pour les tests et vérifie leur concordance avec la base HelloAsso réelle.

"""
    
    # Separate audit by status
    errors = [r for r in audit_results if r['type'] == 'ERROR']
    warnings = [r for r in audit_results if r['type'] == 'WARNING']
    oks = [r for r in audit_results if r['type'] == 'OK']
    
    if errors:
        report_content += "### 🚨 Discrepances Critiques (Adhérents de test introuvables dans la base de données)\n"
        for err in errors:
            report_content += f"- **[{err['section']}]** `{err['name']}` : {err['msg']}\n"
        report_content += "\n"
        
    if warnings:
        report_content += "### ⚠️ Alertes Administratives (Tarif / Statut incohérent)\n"
        for wrn in warnings:
            report_content += f"- **[{wrn['section']}]** `{wrn['name']}` : {wrn['msg']}\n"
        report_content += "\n"
        
    if oks:
        report_content += f"### ✅ Adhérents de test validés et trouvés ({len(oks)} membres)\n"
        report_content += "Tous les autres membres préremplis correspondent parfaitement aux dossiers d'adhésion HelloAsso.\n\n"

    report_content += "---\n\n## ❓ Sections Manquantes ou Non Mappées\n"
    if missing_sections:
        report_content += "Le script a identifié des sections dans le fichier Excel qui n'ont pas d'association de tarifs configurée :\n"
        for sec in missing_sections:
            report_content += f"- **{sec}** (Aucun adhérent de la base ne peut être assigné car cette section n'est pas configurée dans le mapping)\n"
    else:
        report_content += "Toutes les sections du fichier Excel sont correctement associées à des tarifs.\n"
        
    report_content += "\n---\n\n## 🛑 Erreurs, Alertes & Typologies\n"
    if possible_errors:
        for err in possible_errors:
            report_content += f"- ❌ {err}\n"
    else:
        report_content += "Aucune erreur bloquante n'a été détectée durant l'exécution. Tout s'est déroulé à la perfection !\n"
        
    # Write report file
    with open(REPORT_PATH, "w", encoding="utf-8") as rf:
        rf.write(report_content)
        
    print(f"💾 Rapport détaillé enregistré dans : {os.path.basename(REPORT_PATH)}")
    
    # Print high-level summary to console
    print("\n" + "="*70)
    print("📋 RÉSUMÉ DU RAPPORT GLOBAL:")
    print("="*70)
    print(f" Total sections traitées : {len(section_stats)}")
    print(f" Adhérents de test introuvables : {len(errors)}")
    print(f" Alertes administratives/typos  : {len(warnings) + len([e for e in possible_errors if 'titre erroné' in e])}")
    print("="*70)

if __name__ == "__main__":
    main()
