import os
import re
import json
import openpyxl
import datetime
from openpyxl.styles import Border, Side, PatternFill, Font, Alignment
from openpyxl.utils import range_boundaries, get_column_letter
from paths import ROOT_DIR

def style_range(ws, cell_range, outer_side, inner_side=None):
    """Applique un contour extérieur et des bordures intérieures optionnelles à une plage de cellules."""
    min_col, min_row, max_col, max_row = range_boundaries(cell_range)
    for row in range(min_row, max_row + 1):
        for col in range(min_col, max_col + 1):
            cell = ws.cell(row=row, column=col)
            b_left = outer_side if col == min_col else inner_side
            b_right = outer_side if col == max_col else inner_side
            b_top = outer_side if row == min_row else inner_side
            b_bottom = outer_side if row == max_row else inner_side
            
            # Ne pas écraser les bordures existantes de la cellule si on n'a pas défini de bordure intérieure
            cell.border = Border(
                left=b_left or cell.border.left, 
                right=b_right or cell.border.right, 
                top=b_top or cell.border.top, 
                bottom=b_bottom or cell.border.bottom
            )

DAY_NAME_TO_WEEKDAY = {
    "lundi": 1,
    "mardi": 2,
    "mercredi": 3,
    "jeudi": 4,
    "vendredi": 5,
    "samedi": 6,
    "dimanche": 7
}

def clean_filename(name):
    """Nettoie le nom d'un groupe pour en faire un nom de fichier valide."""
    safe = "".join(c for c in name if c.isalnum() or c in (" ", "-", "_"))
    safe = safe.replace(" ", "_")
    # Limiter la longueur et retirer les d'underscores multiples
    safe = re.sub(r'_{2,}', '_', safe)
    return safe.strip("_")

def format_encadrants(encadrants_list):
    """Sépare les prénoms et noms des encadrants pour correspondre aux cases séparées du template."""
    if not encadrants_list:
        return "-", "-"
    first_names = []
    last_names = []
    for enc in encadrants_list:
        parts = enc.strip().split(" ", 1)
        if len(parts) == 2:
            first_names.append(parts[0].capitalize())
            last_names.append(parts[1].upper())
        else:
            first_names.append(enc.capitalize())
            last_names.append("")
    return " / ".join(last_names), " / ".join(first_names)

def find_planning_match_dynamically(tarif_name, planning_data):
    """
    Recherche dynamiquement l'association de cours dans planning.json
    en s'appuyant sur des règles sémantiques robustes (mots-clés, jours, horaires).
    """
    t_lower = tarif_name.lower()
    matches = []
    
    # 1. Extraction des caractéristiques du tarif
    is_autonome = "autonome" in t_lower
    is_compet = "compétition" in t_lower or "competition" in t_lower
    is_debutant = "débutant" in t_lower or "debutant" in t_lower or "débutants" in t_lower
    is_lycee = "lycée" in t_lower or "lycee" in t_lower
    is_college = "collège" in t_lower or "college" in t_lower
    is_bloc = "bloc" in t_lower
    is_perf = "perfectionnement" in t_lower or "perf" in t_lower
    
    day_keywords = {
        "lundi": "Lundi",
        "mardi": "Mardi",
        "mercredi": "Mercredi",
        "jeudi": "Jeudi",
        "vendredi": "Vendredi",
        "samedi": "Samedi",
        "dimanche": "Dimanche"
    }
    target_day = None
    for k, v in day_keywords.items():
        if k in t_lower:
            target_day = v
            break
            
    # Recherche d'heure (ex: "18h30" -> 18, "13h" -> 13)
    hour_match = re.search(r"(\d+)h", t_lower)
    target_hour = int(hour_match.group(1)) if hour_match else None

    # 2. Recherche de correspondances dans les lignes de planning.json
    for idx_item, item in enumerate(planning_data, 1):
        g_name = str(item.get("groupe") or "").lower()
        g_type = str(item.get("type") or "").lower()
        g_day = str(item.get("jour") or "").lower()
        g_time = str(item.get("horaires") or "")
        
        # A. Créneaux Autonomes
        if is_autonome and ("autonome" in g_name or "autonome" in g_type):
            matches.append(item)
            continue
            
        # B. Compétition
        if is_compet and "compétition" in g_name:
            is_u11_u13 = any(x in t_lower for x in ["u11", "u13", "2015", "2016", "2017", "2018"])
            if is_u11_u13 and "u11-u15" in g_name:
                matches.append(item)
            elif not is_u11_u13 and ("u15-u19" in g_name or "u15-u17-u19" in g_name or "u15" in g_name):
                matches.append(item)
            continue
            
        # C. Bloc
        if is_bloc and "bloc" in g_name:
            matches.append(item)
            continue
            
        # D. Perfectionnement / Difficulté
        if is_perf and ("perfectionnement" in g_name or "perf" in g_name or "difficult" in g_name or "difficulté" in g_name):
            matches.append(item)
            continue
            
        # E. Collège
        if is_college and "collège" in g_name:
            if target_day and target_day.lower() == g_day:
                matches.append(item)
            elif not target_day:
                matches.append(item)
            continue
            
        # F. Lycée
        if is_lycee and "lycée" in g_name:
            matches.append(item)
            continue
            
        # G. Débutants Adultes
        if is_debutant and "débutants" in g_name:
            matches.append(item)
            continue
            
        # H. Loisir Enfants
        if "enfants" in t_lower and "enfants" in g_name:
            if target_day and target_day.lower() == g_day:
                if target_hour:
                    if f"{target_hour:02d}:" in g_time or f" {target_hour}:" in g_time or f"{target_hour}:" in g_time:
                        matches.append(item)
                else:
                    matches.append(item)
            elif not target_day:
                matches.append(item)
            continue

    # 3. Aggégation des correspondances
    if matches:
        all_coaches = []
        all_slots = []
        distinct_jours = []
        
        for m in matches:
            for enc in m.get("encadrants", []):
                if enc not in all_coaches:
                    all_coaches.append(enc)
            
            day_name = m.get("jour") or ""
            time_slot = m.get("horaires") or ""
            if day_name and time_slot:
                slot_str = f"{day_name} {time_slot}"
                if slot_str not in all_slots:
                    all_slots.append(slot_str)
            
            # Extraire les jours individuels de l'entrée de planning
            day_field = str(m.get("jour") or "").strip()
            for part in re.split(r"[/,;\s]+and\s+|[/,;\s]+et\s+|[/,;]+", day_field):
                p_clean = part.strip().lower()
                if p_clean in DAY_NAME_TO_WEEKDAY:
                    day_cap = p_clean.capitalize()
                    if day_cap not in distinct_jours:
                        distinct_jours.append(day_cap)
                    
        if len(all_slots) > 1:
            if is_compet:
                if "u11" in t_lower:
                    horaires_str = "Lundi 18h-20h, Mercredi 16h-18h, Vendredi 18h-20h"
                else:
                    horaires_str = "Lundi 18h00-20h30, Mercredi 18h00-20h00, Vendredi 18h30-20h30"
            else:
                horaires_str = ", ".join(all_slots)
        else:
            horaires_str = all_slots[0] if all_slots else "-"
            
        return {
            "groupe_planning": matches[0].get("groupe", tarif_name),
            "horaires": horaires_str,
            "encadrants": all_coaches,
            "jours": distinct_jours
        }
        
    return None

def generate_presence_sheets(selected_groups, participants_data, start_date_str=None, end_date_str=None, merge_groups=False, auth_only=False):
    """
    Génère des feuilles de présence au format Excel pour les groupes spécifiés.
    Génère un fichier par groupe de tarif (colonne tarif_name) ou un seul fichier fusionné (Nouveau !).
    """
    root_dir = ROOT_DIR
    template_path = os.path.join(root_dir, "Template Export liste adhérents à imprimer.xlsx")
    output_dir = os.path.join(root_dir, "exports", "fiches_presence")
    
    os.makedirs(output_dir, exist_ok=True)
    
    if not os.path.exists(template_path):
        print(f"[ERREUR PRESENCE] Le fichier modèle est introuvable au chemin : {template_path}")
        return False, f"Modèle introuvable : {template_path}"
        
    # Charger le planning directement depuis SQLite
    try:
        from infrastructure.sqlite_repository import SqliteRepository
        planning_data = SqliteRepository.load_planning_data()
        print(f"[PRESENCE] {len(planning_data)} créneaux de cours chargés depuis la BDD SQLite.")
    except Exception as pe:
        print(f"[ATTENTION PRESENCE] Impossible de charger le planning depuis SQLite, repli vide : {pe}")
        planning_data = []
            
    # Parser les dates facultatives de début et fin
    start_date = None
    end_date = None
    if start_date_str and start_date_str.strip():
        try:
            start_date = datetime.datetime.strptime(start_date_str.strip(), "%d/%m/%Y").date()
        except ValueError:
            pass
    if end_date_str and end_date_str.strip():
        try:
            end_date = datetime.datetime.strptime(end_date_str.strip(), "%d/%m/%Y").date()
        except ValueError:
            pass
            
    # Plus besoin de charger tarif_mapping.json car les correspondances sont stockées directement dans la BDD SQLite
    tarif_mapping = {}

    # Définition des Styles de design demandés
    thin_gray = Side(style='thin', color='CCCCCC')
    thick_blue = Side(style='medium', color='1E3A8A')
    medium_black = Side(style='medium', color='000000')
    double_blue = Side(style='double', color='1E3A8A')

    border_cell_thin = Border(left=thin_gray, right=thin_gray, top=thin_gray, bottom=thin_gray)
    border_cell_header = Border(left=thin_gray, right=thin_gray, top=thick_blue, bottom=double_blue)
    border_metadata = Border(left=thick_blue, right=thick_blue, top=thick_blue, bottom=thick_blue)

    # Couleurs de fond
    fill_zebra_light_gray = PatternFill(start_color="EAEAEA", end_color="EAEAEA", fill_type="solid") # Une ligne sur deux active
    fill_white = PatternFill(start_color="FFFFFF", end_color="FFFFFF", fill_type="solid")
    fill_header_date = PatternFill(start_color="F2F4F8", end_color="F2F4F8", fill_type="solid") # En-tête des dates
    fill_metadata = PatternFill(start_color="E6EEF8", end_color="E6EEF8", fill_type="solid") # En-têtes groupe / encadrants

    font_slot_title = Font(name="Segoe UI", size=16, bold=True, color="1E3A8A") # TITRE DU CRENEAU EN GROS (E1)
    font_metadata = Font(name="Segoe UI", size=10, bold=True, color="1E3A8A")
    font_date_header = Font(name="Segoe UI", size=8, bold=True, color="374151")
    font_student_name = Font(name="Segoe UI", size=9, bold=False, color="1F2937")

    align_center = Alignment(horizontal="center", vertical="center")
    align_left = Alignment(horizontal="left", vertical="center")

    generated_files = []
    
    # 1. Préparer les groupes à boucler et leurs participants
    if merge_groups and len(selected_groups) > 1:
        # Créer un nom combiné descriptif (ex: "Adultes autonomes & Jeunes Adultes")
        combined_group_name = " & ".join(selected_groups)
        if len(combined_group_name) > 80:
            combined_group_name = "Groupes Fusionnés"
            
        merged_participants = []
        for g in selected_groups:
            if g == "Adultes & Jeunes Adultes autonomes":
                sub_parts = [
                    p for p in participants_data 
                    if p.get("tarif_name") or "".strip() in ("Adultes autonomes", "Jeunes Adultes autonomes - nés entre 2001 et 2008")
                    and "annul" not in str(p.get("status") or "").lower()
                ]
            else:
                sub_parts = [
                    p for p in participants_data 
                    if p.get("tarif_name") or "".strip() == g
                    and "annul" not in str(p.get("status") or "").lower()
                ]
            for p in sub_parts:
                if p not in merged_participants:
                    merged_participants.append(p)
                    
        participants_by_group = {combined_group_name: merged_participants}
        loop_groups = [combined_group_name]
    else:
        participants_by_group = {}
        for group_name in selected_groups:
            if group_name == "Adultes & Jeunes Adultes autonomes":
                participants_by_group[group_name] = [
                    p for p in participants_data 
                    if p.get("tarif_name") or "".strip() in ("Adultes autonomes", "Jeunes Adultes autonomes - nés entre 2001 et 2008")
                    and "annul" not in str(p.get("status") or "").lower()
                ]
            else:
                participants_by_group[group_name] = [
                    p for p in participants_data 
                    if p.get("tarif_name") or "".strip() == group_name
                    and "annul" not in str(p.get("status") or "").lower()
                ]
        loop_groups = selected_groups

    for group_name in loop_groups:
        group_participants = participants_by_group[group_name]
        
        # Trier par prénom adhérent (user_firstName), insensible à la casse
        group_participants.sort(key=lambda x: str(x.get("user_firstName") or "").strip().lower())
        
        # 2. Charger une nouvelle copie du template
        wb = openpyxl.load_workbook(template_path)
        ws = wb.active
        
        # 3. Tenter d'associer le tarif avec le planning via la configuration de BDD (IHM)
        if merge_groups:
            # Essayer de trouver un cours autonome dans le planning ou par défaut prendre le premier sous-groupe
            lookup_name = selected_groups[0]
            for g in selected_groups:
                if "autonome" in g.lower():
                    lookup_name = "Adultes autonomes" if g == "Adultes & Jeunes Adultes autonomes" else g
                    break
        else:
            lookup_name = "Adultes autonomes" if group_name == "Adultes & Jeunes Adultes autonomes" else group_name
            
        match_info = None
        
        # 3.1 Vérifier d'abord si des créneaux possèdent ce tarif HelloAsso configuré via l'IHM
        matches = []
        for item in planning_data:
            linked_tarifs = item.get("helloasso_tarifs", [])
            if any(str(t).strip().lower() == lookup_name.strip().lower() for t in linked_tarifs):
                matches.append(item)
                
        if matches:
            all_coaches = []
            all_slots = []
            distinct_jours = []
            for m in matches:
                for enc in m.get("encadrants", []):
                    if enc not in all_coaches:
                        all_coaches.append(enc)
                day_name = m.get("jour") or ""
                time_slot = m.get("horaires") or ""
                if day_name and time_slot:
                    slot_str = f"{day_name} {time_slot}"
                    if slot_str not in all_slots:
                        all_slots.append(slot_str)
                
                day_field = str(m.get("jour") or "").strip()
                for part in re.split(r"[/,;\s]+and\s+|[/,;\s]+et\s+|[/,;]+", day_field):
                    p_clean = part.strip().lower()
                    if p_clean in DAY_NAME_TO_WEEKDAY:
                        distinct_jours.append(p_clean.capitalize())
                        
            horaires_str = ", ".join(all_slots) if all_slots else "-"
            t_lower = group_name.lower()
            if "autonome" in t_lower:
                horaires_str = "Lundi-Mercredi-Jeudi-Vendredi-Samedi (Créneaux autonomes)"
            elif "compétition" in t_lower or "competition" in t_lower:
                if "u11" in t_lower:
                    horaires_str = "Lun 18h-20h, Mer 16h-18h, Ven 18h-20h"
                else:
                    horaires_str = "Lun 18h00-20h30, Mer 18h00-20h00, Ven 18h30-20h30"
                    
            match_info = {
                "groupe_planning": matches[0].get("groupe", group_name),
                "horaires": horaires_str,
                "encadrants": all_coaches,
                "jours": distinct_jours
            }
            
        if not match_info:
            # 3.2 Repli 1 : Tenter d'associer le tarif avec le planning via l'ancienne matrice d'ID(s)
            mapped_slot_ids = tarif_mapping.get(lookup_name)
            if mapped_slot_ids and mapped_slot_ids.strip():
                target_ids = [idx.strip() for idx in str(mapped_slot_ids).split(";")]
                matches = []
                for idx_item, item in enumerate(planning_data, 1):
                    item_id = str(item.get("id", idx_item)).strip()
                    if item_id in target_ids:
                        matches.append(item)
                        
                if matches:
                    all_coaches = []
                    all_slots = []
                    distinct_jours = []
                    for m in matches:
                        for enc in m.get("encadrants", []):
                            if enc not in all_coaches:
                                all_coaches.append(enc)
                        day_name = m.get("jour") or ""
                        time_slot = m.get("horaires") or ""
                        if day_name and time_slot:
                            slot_str = f"{day_name} {time_slot}"
                            if slot_str not in all_slots:
                                all_slots.append(slot_str)
                        
                        day_field = str(m.get("jour") or "").strip()
                        for part in re.split(r"[/,;\s]+and\s+|[/,;\s]+et\s+|[/,;]+", day_field):
                            p_clean = part.strip().lower()
                            if p_clean in DAY_NAME_TO_WEEKDAY:
                                distinct_jours.append(p_clean.capitalize())
                                
                    horaires_str = ", ".join(all_slots) if all_slots else "-"
                    if len(all_slots) > 1:
                        t_lower = group_name.lower()
                        if "autonome" in t_lower:
                            horaires_str = "Lundi-Mercredi-Jeudi-Vendredi-Samedi (Créneaux autonomes)"
                        elif "compétition" in t_lower or "competition" in t_lower:
                            if "u11" in t_lower:
                                horaires_str = "Lun 18h-20h, Mer 16h-18h, Ven 18h-20h"
                            else:
                                horaires_str = "Lun 18h00-20h30, Mer 18h00-20h00, Ven 18h30-20h30"
                                
                    match_info = {
                        "groupe_planning": matches[0].get("groupe", group_name),
                        "horaires": horaires_str,
                        "encadrants": all_coaches,
                        "jours": distinct_jours
                    }
                        
        if not match_info:
            # 3.3 Repli 2 : Tenter l'analyse dynamique sémantique par défaut
            match_info = find_planning_match_dynamically(group_name, planning_data)
        
        if match_info:
            encadrants_list = match_info["encadrants"]
            horaire = match_info["horaires"]
            group_days = match_info.get("jours", [])
        else:
            encadrants_list = []
            horaire = "-"
            group_days = []
            
        # Si aucun jour n'est détecté par le planning, on devine d'après le tarif_name
        if not group_days:
            for d_name in DAY_NAME_TO_WEEKDAY:
                if d_name in group_name.lower():
                    group_days.append(d_name.capitalize())
                    
        # Si toujours vide (ex: Adultes autonomes), on utilise par défaut du Lundi au Samedi (votre demande !)
        if not group_days:
            group_days = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi"]
                    
        coach_last, coach_first = format_encadrants(encadrants_list)
        count_members = len(group_participants)
        
        # 4. Remplir les cellules d'en-tête du template et appliquer du style/bordures
        ws.sheet_view.showGridLines = False
        
        formatted_coaches = f"{coach_first} {coach_last}".strip()
        formatted_coaches = formatted_coaches if formatted_coaches != "- -" else "-"
        
        # Si impression fusionnée, ne pas noter les horaires et le nom des encadrants dans G2 et L2 (votre demande !)
        if merge_groups:
            formatted_coaches = "-"
            horaire = "-"
        
        # Nettoyage des anciennes cases C1:Q2 si elles existaient dans le template
        for r in range(1, 3):
            for c_idx in range(3, 18):
                cell_to_clean = ws.cell(row=r, column=c_idx)
                cell_to_clean.value = None
                cell_to_clean.border = Border()
                cell_to_clean.fill = PatternFill(fill_type=None)

        ws['C1'] = group_name  # Nom du groupe
        ws['C2'] = f"Créneau : {count_members} personnes"
        ws['G2'] = formatted_coaches
        ws['L2'] = f"Horaire : {horaire}"

        # Style du bloc d'en-tête C1:O2 en une seule "carte"
        ws.merge_cells("C1:O1")
        ws.merge_cells("C2:F2")
        ws.merge_cells("G2:K2")
        ws.merge_cells("L2:O2")

        for row in range(1, 3):
            for col in range(3, 16):
                c = ws.cell(row=row, column=col)
                c.fill = fill_metadata
                if row == 1:
                    c.font = font_slot_title
                    c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
                else:
                    c.font = font_metadata

        # Alignements spécifiques pour la ligne 2
        ws['C2'].alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
        ws['G2'].alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws['L2'].alignment = Alignment(horizontal="right", vertical="center", wrap_text=True)

        # Bordure globale pour toute la carte C1:O2
        style_range(ws, "C1:O2", thick_blue, inner_side=thin_gray)
        
        # Vider entièrement la ligne 3 pour qu'elle reste vide (Saut de ligne sous l'en-tête)
        for col in range(1, 100):
            c_cell = ws.cell(row=3, column=col)
            c_cell.value = None
            c_cell.border = Border()
            c_cell.fill = PatternFill(fill_type=None)

        # 5. Remplir la ligne 4 avec les dates de séances calculées et les nouvelles colonnes Badge Rouge / Passeport Orange
        session_dates = []
        if start_date and end_date and start_date <= end_date and group_days:
            target_weekdays = [DAY_NAME_TO_WEEKDAY[d.lower()] for d in group_days if d.lower() in DAY_NAME_TO_WEEKDAY]
            if target_weekdays:
                curr = start_date
                while curr <= end_date:
                    if curr.isoweekday() in target_weekdays:
                        session_dates.append(curr)
                    curr += datetime.timedelta(days=1)
                    
        # Définir l'en-tête pour les trois colonnes d'audits de badges et d'autonomie FFME
        ws.cell(row=4, column=3, value="Badge rouge")
        ws.cell(row=4, column=4, value="Bloc")
        ws.cell(row=4, column=5, value="Passeport Orange")
        ws.column_dimensions['C'].width = 12
        ws.column_dimensions['D'].width = 8
        ws.column_dimensions['E'].width = 15

        start_date_col = 7 if auth_only else 6
        if auth_only:
            # Saisie de l'en-tête "Autorisation" en colonne F (6) (votre demande !)
            ws.cell(row=4, column=6, value="Autorisation")
            ws.column_dimensions['F'].width = 18

        if session_dates:
            col_idx = start_date_col # Les dates de séances commencent maintenant à la colonne F (Col 6) ou G (Col 7)
            for s_date in session_dates:
                # Écrire la date au format JJ/MM sur la ligne 4 !
                cell = ws.cell(row=4, column=col_idx, value=s_date.strftime("%d/%m"))
                cell.font = font_date_header
                cell.fill = fill_header_date
                cell.alignment = align_center
                cell.border = border_cell_header # Jolie bordure comme Prénom/Nom !
                ws.column_dimensions[get_column_letter(col_idx)].width = 5
                col_idx += 1
            # Vider le reste des en-têtes de colonnes de dates de la ligne 4
            for col in range(col_idx, 100):
                ws.cell(row=4, column=col, value=None)
        else:
            ws.cell(row=4, column=start_date_col, value="Date")
            ws.cell(row=4, column=start_date_col).font = font_date_header
            ws.cell(row=4, column=start_date_col).fill = fill_header_date
            ws.cell(row=4, column=start_date_col).alignment = align_center
            ws.cell(row=4, column=start_date_col).border = border_cell_header
            ws.column_dimensions[get_column_letter(start_date_col)].width = 5
            for col in range(start_date_col + 1, 100):
                ws.cell(row=4, column=col, value=None)
        
        # 6. Remplir la liste des élèves (Prénom en col A, Nom en col B, Badge en col C, Bloc en col D, Passeport en col E, Autorisation en col F optionnelle)
        row_idx = 5
        max_active_col = start_date_col + len(session_dates) - 1 if session_dates else start_date_col
        
        for p in group_participants:
            first_name = str(p.get("user_firstName") or "").strip().capitalize()
            last_name = str(p.get("user_lastName") or "").strip().upper()
            badge_rouge = str(p.get("badge_rouge", "Non")).strip()
            autonomie_bloc = str(p.get("autonomie_bloc", "Non")).strip()
            has_orange = "Oui" if "orange" in str(p.get("raw_passports") or "").lower() else "Non"
            
            # Saisie de prénom, nom, badge rouge, autonomie bloc et passeport orange
            cell_first = ws.cell(row=row_idx, column=1, value=first_name)
            cell_last = ws.cell(row=row_idx, column=2, value=last_name)
            cell_badge = ws.cell(row=row_idx, column=3, value=badge_rouge)
            cell_bloc = ws.cell(row=row_idx, column=4, value=autonomie_bloc)
            cell_orange = ws.cell(row=row_idx, column=5, value=has_orange)
            
            cells_to_style = [cell_first, cell_last, cell_badge, cell_bloc, cell_orange]
            
            if auth_only:
                # Composer les autorisations (votre demande !)
                auths = []
                if str(p.get("parental_auth_autonomous", "Non")).strip() == "Oui":
                    auths.append("Autonomes")
                if str(p.get("parental_auth_family", "Non")).strip() == "Oui":
                    auths.append("Famille")
                auths_str = ", ".join(auths) if auths else "Aucune"
                cell_auth = ws.cell(row=row_idx, column=6, value=auths_str)
                cells_to_style.append(cell_auth)
            
            # Alternance couleur (une ligne sur deux)
            is_zebra = (row_idx % 2 == 0)
            row_fill = fill_zebra_light_gray if is_zebra else fill_white
            
            # Appliquer le style au prénom, nom, et nouvelles colonnes
            for cell in cells_to_style:
                cell.font = font_student_name
                cell.fill = row_fill
                cell.alignment = align_left if cell in (cell_first, cell_last) else align_center
                cell.border = border_cell_thin
                
            # Appliquer le quadrillage (bordures minces) et le fond zébré aux colonnes de dates actives de cette ligne
            for col in range(start_date_col, max_active_col + 1):
                c_cell = ws.cell(row=row_idx, column=col)
                c_cell.fill = row_fill
                c_cell.border = border_cell_thin
                
            # Pour toutes les colonnes au-delà de max_active_col (colonnes sans dates), aucune couleur de fond ni bordure !
            for col in range(max_active_col + 1, 100):
                c_cell = ws.cell(row=row_idx, column=col)
                c_cell.fill = PatternFill(fill_type=None)
                c_cell.border = Border()
                
            row_idx += 1
            
        # Effacer entièrement et enlever TOUTES les bordures des lignes vides de row_idx à 200 !
        for r in range(row_idx, 201):
            no_fill = PatternFill(fill_type=None)
            no_border = Border()
            for col in range(1, 100):
                c_cell = ws.cell(row=r, column=col)
                c_cell.value = None
                c_cell.fill = no_fill
                c_cell.border = no_border
                
        # Style pour la ligne 4 (Prénom / Nom / Badge / Bloc / Passeport en-têtes de colonnes)
        header_cols = (1, 2, 3, 4, 5, 6) if auth_only else (1, 2, 3, 4, 5)
        for c_idx in header_cols:
            cell_hdr = ws.cell(row=4, column=c_idx)
            cell_hdr.font = font_date_header
            cell_hdr.alignment = align_left if c_idx < 3 else align_center
            cell_hdr.border = border_cell_header
            cell_hdr.fill = fill_header_date

        # 7. Appliquer les bordures renforcées de changement de mois (uniquement sur les colonnes actives de dates)
        if len(session_dates) > 1:
            for i in range(len(session_dates) - 1):
                # Si le mois change entre deux séances consécutives
                if session_dates[i].month != session_dates[i+1].month:
                    col_sep = start_date_col + i
                    # On applique une bordure droite moyenne verticale de la ligne 4 (dates) jusqu'à la dernière ligne d'élève active
                    for r_border in range(4, row_idx):
                        cell_border = ws.cell(row=r_border, column=col_sep)
                        
                        # Créer une nouvelle bordure fusionnant les styles existants mais renforçant la droite
                        cell_border.border = Border(
                            left=cell_border.border.left or thin_gray,
                            right=medium_black,
                            top=cell_border.border.top or thin_gray,
                            bottom=cell_border.border.bottom or thin_gray
                        )

        # 8. Ajouter une bordure extérieure épaisse pour tout le tableau (ligne 4 à row_idx - 1)
        table_top_row = 4
        table_bottom_row = row_idx - 1
        table_left_col = 1
        table_right_col = max_active_col
        
        for r in range(table_top_row, table_bottom_row + 1):
            for c in range(table_left_col, table_right_col + 1):
                cell = ws.cell(row=r, column=c)
                
                b_left = cell.border.left
                b_right = cell.border.right
                b_top = cell.border.top
                b_bottom = cell.border.bottom
                
                if r == table_top_row:
                    b_top = thick_blue
                if r == table_bottom_row:
                    b_bottom = thick_blue
                if c == table_left_col:
                    b_left = thick_blue
                if c == table_right_col:
                    b_right = thick_blue
                    
                cell.border = Border(left=b_left, right=b_right, top=b_top, bottom=b_bottom)

        # 9. Ajouter le logo logo.png s'il existe à l'emplacement A1
        logo_path = os.path.join(root_dir, "logo.png")
        if os.path.exists(logo_path):
            try:
                from openpyxl.drawing.image import Image
                img = Image(logo_path)
                # Adapter la taille pour un rendu élégant (90x90 px)
                img.width = 90
                img.height = 90
                ws.add_image(img, 'A1')
                print("[PRESENCE] Logo inséré avec succès en A1.")
            except Exception as ie:
                print(f"[ATTENTION PRESENCE] Impossible d'insérer le logo : {ie}")
                
        # 9. Forcer la mise en page en A3 Vertical (Portrait) pour l'impression
        ws.page_setup.orientation = 'portrait'  # Portrait
        ws.page_setup.paperSize = 8  # PAPERSIZE_A3 (8 dans Excel Page Setup)
        
        # 10. Sauvegarder le fichier Excel de manière sécurisée
        safe_name = clean_filename(group_name)
        save_filename = f"Feuille_Presence_{safe_name}.xlsx"
        save_path = os.path.join(output_dir, save_filename)
        
        try:
            wb.save(save_path)
            wb.close()
        except PermissionError:
            wb.close()
            print(f"[ERREUR PRESENCE] Le fichier '{save_filename}' est verrouillé car il est actuellement ouvert dans Microsoft Excel.")
            return False, f"Le fichier '{save_filename}' est actuellement ouvert dans Microsoft Excel. Veuillez le fermer et relancer la génération."
            
        generated_files.append(save_filename)
        print(f"[PRESENCE] Feuille générée avec succès ({count_members} inscrits, {len(session_dates)} séances) : {save_filename}")
        
    return True, generated_files
