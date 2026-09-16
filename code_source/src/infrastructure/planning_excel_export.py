"""
Export Excel du planning hebdomadaire des créneaux (bouton de l'onglet Créneaux).

Construit une grille « Lundi → Samedi », de 9h à 22h par pas de 30 minutes :
- un bloc fusionné par créneau, coloré selon le type de groupe
  (compétition = vert, perfectionnement = rose, cours = bleu, autonome = gris) ;
- le libellé du groupe (suffixe parenthésé « (jour / horaire) » retiré) ;
- une ligne encadrants : noms complets si la place le permet, sinon **initiales**
  (bloc trop court), sinon rien ;
- les heures en libellés à gauche ET à droite de la grille (9h, 10h, … 22h) ;
- hiérarchie des traits : lignes d'**heures** et cadre plus marqués (medium sombre)
  que les lignes des **demi-heures** (thin clair) ; blocs au contour médium.

Logique pure et testable : parse_horaire / clean_group_label / _initiales /
encadrants_text / assign_lanes, puis export_planning_excel (openpyxl).
"""
import math
import re

DAYS = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi"]
GRID_START = 9 * 60    # 9h00
GRID_END = 22 * 60     # 22h00
STEP = 30              # pas de 30 minutes
CHARS_PER_LINE = 16    # largeur estimée d'une sous-colonne en caractères

# Couleurs de fond par type de groupe (inspirées du site du club)
TYPE_FILLS = {
    "compétition": "D9EAD3",       # vert clair
    "perfectionnement": "F8C8DC",  # rose
    "cours": "D9E1F2",             # bleu lavande
    "autonome": "D9D9D9",          # gris
}
DEFAULT_FILL = "EFEFEF"
FILL_BLOC_AUTONOME = "FFD8A8"      # orange clair pastel (groupe « Autonome Bloc »)


def fill_for_item(item):
    """Couleur de fond d'un créneau : priorité au nom du groupe (« Autonome Bloc »
    = orange clair pastel), sinon le type de groupe."""
    from domain.utils import normalize_string
    label = normalize_string(item.get("groupe") or "")
    if "autonome" in label and "bloc" in label:
        return FILL_BLOC_AUTONOME
    return TYPE_FILLS.get(normalize_type(item.get("type")), DEFAULT_FILL)


def parse_horaire(horaires):
    """'18:00 - 20:00', '17:00 18:00', '9h30-12h' -> (début, fin) en minutes, ou None."""
    matches = re.findall(r"(\d{1,2})\s*[:hH]\s*(\d{1,2})?", str(horaires or ""))
    values = []
    for h, m in matches:
        h, m = int(h), int(m or 0)
        if h > 23 or m > 59:
            continue
        values.append(h * 60 + m)
    if len(values) < 2:
        return None
    start, end = values[0], values[1]
    if end <= start:
        return None
    return start, end


def clean_group_label(groupe):
    """Retire le suffixe parenthésé redondant « (jour / horaire) » de fin de libellé.

    « Enfants 2019-2020 (Mercredi 09h30) » -> « Enfants 2019-2020 » ;
    « Perfectionnement - U11-U13(1) » est conservé (le (1) distingue deux groupes).
    """
    name = str(groupe or "").strip()
    m = re.search(r"\(([^)]*)\)\s*$", name)
    if m and re.search(r"(?i)(lundi|mardi|mercredi|jeudi|vendredi|samedi|\d{1,2}\s*[h:])", m.group(1)):
        name = name[: m.start()].strip()
    return name


def _initiales(nom):
    """Initiales compactes d'un encadrant : « Camille DIDIER » -> « C.D. »."""
    words = [w for w in re.split(r"[\s\-'.]+", str(nom).strip()) if w]
    return ".".join(w[0].upper() for w in words) + "." if words else ""


def encadrants_text(encadrants, rows_span, label):
    """Ligne encadrants adaptée à la place du bloc (noms complets, initiales, ou rien)."""
    encadrants = [str(e).strip() for e in (encadrants or []) if str(e).strip()]
    if not encadrants or rows_span <= 0:
        return ""
    full = ", ".join(encadrants)
    initials = ", ".join(_initiales(e) for e in encadrants)
    label_lines = max(1, math.ceil(len(label) / CHARS_PER_LINE))
    free = max(0, rows_span - label_lines)
    if math.ceil((len(full) + 7) / CHARS_PER_LINE) <= free:
        return "Enc. : " + full
    if math.ceil(len(initials) / CHARS_PER_LINE) <= free:
        return initials
    return ""


def assign_lanes(slots):
    """Répartit les créneaux d'un jour en colonnes sans chevauchement.

    slots : [{start, end, …}] (minutes). Retourne ([(slot, lane)…], nb_lanes).
    """
    lanes = []
    out = []
    for s in sorted(slots, key=lambda x: (x["start"], x["end"])):
        for i, lane_end in enumerate(lanes):
            if s["start"] >= lane_end:
                lanes[i] = s["end"]
                out.append((s, i))
                break
        else:
            lanes.append(s["end"])
            out.append((s, len(lanes) - 1))
    return out, len(lanes)


def normalize_type(type_value):
    t = str(type_value or "").strip().lower()
    return t if t in TYPE_FILLS else "cours"


def export_planning_excel(planning_data, saison, out_path):
    """Construit le fichier Excel du planning hebdomadaire et retourne le chemin."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

    # 1. Créneaux valides regroupés par jour
    by_day = {day: [] for day in DAYS}
    for item in planning_data or []:
        span = parse_horaire(item.get("horaires"))
        jour = str(item.get("jour") or "").strip().capitalize()
        if not span or jour not in DAYS:
            continue
        start = max(span[0], GRID_START)
        end = min(span[1], GRID_END)
        if end <= start:
            continue
        by_day[jour].append({
            "start": start, "end": end,
            "label": clean_group_label(item.get("groupe")) or str(item.get("groupe") or "Créneau"),
            "fill": fill_for_item(item),
            "encadrants": item.get("encadrants") or [],
        })
    if not any(by_day.values()):
        raise ValueError("Aucun créneau exploitable dans le planning (jour + horaires requis).")

    # 2. Répartition en voies par jour + décalage colonnes
    day_lanes = {}
    offset = 0
    for day in DAYS:
        assignments, lanes = assign_lanes(by_day[day])
        day_lanes[day] = {"assignments": assignments, "lanes": lanes, "offset": offset}
        offset += max(1, lanes)
    total_lanes = offset

    # 3. Classeur
    wb = Workbook()
    ws = wb.active
    ws.title = "Planning"
    # Hiérarchie des traits : séparateurs de JOURS = thick noir, lignes d'HEURES et
    # cadre = medium sombre, lignes des DEMI-HEURES = thin clair, voies = thin.
    thin = Side(style="thin", color="BFBFBF")
    medium = Side(style="medium", color="404040")
    sep = Side(style="thin", color="595959")
    thick = Side(style="thick", color="000000")
    block_border = Border(left=medium, right=medium, top=medium, bottom=medium)
    header_fill = PatternFill("solid", fgColor="D9E1F2")
    center = Alignment(horizontal="center", vertical="center", wrap_text=True)

    nb_steps = (GRID_END - GRID_START) // STEP
    first_grid_row = 3
    last_grid_row = first_grid_row + nb_steps - 1
    col_left, col_right = 1, 2 + total_lanes

    # Bornes de colonnes par jour (pour les séparateurs verticaux marqués)
    day_cols = {}
    for day in DAYS:
        info = day_lanes[day]
        c_start = 2 + info["offset"]
        c_end = c_start + max(1, info["lanes"]) - 1
        day_cols[day] = (c_start, c_end)

    # Titre (saison)
    ws.merge_cells(start_row=1, start_column=2, end_row=1, end_column=1 + total_lanes)
    t = ws.cell(row=1, column=2, value=f"Saison {str(saison).replace('-', ' - ')}")
    t.font = Font(name="Calibri", size=12, bold=True)
    t.alignment = center
    for c in range(2, 2 + total_lanes):
        ws.cell(row=1, column=c).border = Border(left=medium, right=medium, top=medium, bottom=medium)

    # En-têtes de jours (fusionnés sur leurs voies)
    for day in DAYS:
        info = day_lanes[day]
        c_start, c_end = day_cols[day]
        if c_end > c_start:
            ws.merge_cells(start_row=2, start_column=c_start, end_row=2, end_column=c_end)
        h = ws.cell(row=2, column=c_start, value=day.upper())
        h.font = Font(name="Calibri", size=10, bold=True)
        h.alignment = center
        h.fill = header_fill
        for c in range(c_start, c_end + 1):
            cell = ws.cell(row=2, column=c)
            cell.border = Border(left=thick if c == c_start else sep,
                                 right=thick if c == c_end else sep,
                                 top=medium, bottom=medium)
            cell.fill = header_fill

    # Grille horaire + libellés gauche/droite
    for i in range(nb_steps):
        r = first_grid_row + i
        minutes = GRID_START + i * STEP
        ws.row_dimensions[r].height = 15
        label = f"{minutes // 60}h" if i % 2 == 0 else ""
        left = ws.cell(row=r, column=col_left, value=label)
        right = ws.cell(row=r, column=col_right, value=label)
        for cell in (left, right):
            cell.font = Font(name="Calibri", size=9, bold=True)
            cell.alignment = Alignment(horizontal="center", vertical="top")
        # Bordures de la ligne : bas médium si la ligne se termine sur une HEURE
        # (i impair) ou si c'est la dernière ; haut médium en début de grille.
        top = medium if i == 0 else (medium if i % 2 == 0 else thin)
        bottom = medium if (i % 2 == 1 or i == nb_steps - 1) else thin
        for c in range(2, 2 + total_lanes):
            # Séparateur de jour = trait épais ; voies d'un même jour = trait fin
            is_day_start = any(c == cs for cs, _ce in day_cols.values())
            is_day_end = any(c == ce for _cs, ce in day_cols.values())
            cell = ws.cell(row=r, column=c)
            cell.border = Border(left=thick if is_day_start else sep,
                                 right=thick if is_day_end else sep,
                                 top=top, bottom=bottom)

    # Blocs de créneaux
    for day in DAYS:
        info = day_lanes[day]
        for slot, lane in info["assignments"]:
            start_row = first_grid_row + (slot["start"] - GRID_START) // STEP
            end_row = first_grid_row + (slot["end"] - GRID_START + STEP - 1) // STEP - 1
            rows_span = end_row - start_row + 1
            enc = encadrants_text(slot["encadrants"], rows_span, slot["label"])
            text = slot["label"] + (("\n" + enc) if enc else "")
            col = 2 + info["offset"] + lane
            c_start, c_end = day_cols[day]
            left_b = thick if col == c_start else medium
            right_b = thick if col == c_end else medium
            for r in range(start_row, end_row + 1):
                cell = ws.cell(row=r, column=col)
                cell.border = Border(left=left_b, right=right_b, top=medium, bottom=medium)
                cell.fill = PatternFill("solid", fgColor=slot["fill"])
            ws.merge_cells(start_row=start_row, start_column=col, end_row=end_row, end_column=col)
            block = ws.cell(row=start_row, column=col, value=text)
            block.font = Font(name="Calibri", size=8, bold=True, color="1F4E79")
            block.alignment = center

    # Largeurs de colonnes
    ws.column_dimensions["A"].width = 4.5
    last_letter_col = col_right
    for c in range(2, 2 + total_lanes):
        from openpyxl.utils import get_column_letter
        ws.column_dimensions[get_column_letter(c)].width = 13.5
    from openpyxl.utils import get_column_letter as _g
    ws.column_dimensions[_g(last_letter_col)].width = 4.5

    # Mise en page : paysage, ajusté à une page en largeur
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True

    wb.save(out_path)
    return out_path


def export_planning_list_excel(planning_data, saison, out_path):
    """Extraction « liste » du planning : une ligne par créneau, au format de la BDD.

    Colonnes proches de la table `planning` : Jour, Groupe, Type, Horaires, Encadrants,
    Tarifs HelloAsso, Catégorie d'âge, bornes de naissance. Tri Lundi → Samedi puis
    heure de début ; les créneaux non exploitables horairement sont conservés (BDD).
    """
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

    headers = ["Jour", "Groupe", "Type", "Horaires", "Encadrants",
               "Tarifs HelloAsso", "Catégorie d'âge", "Naissance min", "Naissance max"]
    day_index = {day: i for i, day in enumerate(DAYS)}

    rows = []
    for item in planning_data or []:
        jour = str(item.get("jour") or "").strip()
        span = parse_horaire(item.get("horaires"))
        rows.append({
            "sort": (day_index.get(jour.capitalize(), len(DAYS)),
                     span[0] if span else 9999,
                     str(item.get("groupe") or "")),
            "jour": jour,
            "groupe": str(item.get("groupe") or ""),
            "type": str(item.get("type") or ""),
            "horaires": str(item.get("horaires") or ""),
            "encadrants": ", ".join(str(e).strip() for e in (item.get("encadrants") or []) if str(e).strip()),
            "tarifs": ", ".join(str(t).strip() for t in (item.get("helloasso_tarifs") or []) if str(t).strip()),
            "categorie_age": str(item.get("categorie_age") or ""),
            "naissance_min": str(item.get("naissance_min") or ""),
            "naissance_max": str(item.get("naissance_max") or ""),
        })
    rows.sort(key=lambda r: r["sort"])

    wb = Workbook()
    ws = wb.active
    ws.title = "Planning (liste)"
    thin = Side(style="thin", color="BFBFBF")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    header_fill = PatternFill("solid", fgColor="D9E1F2")

    ws.append(headers)
    for c, _h in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=c)
        cell.font = Font(name="Calibri", size=10, bold=True)
        cell.fill = header_fill
        cell.border = border
        cell.alignment = Alignment(horizontal="center", vertical="center")
    display = []
    for r_data in rows:
        line = [r_data["jour"], r_data["groupe"], r_data["type"], r_data["horaires"],
                r_data["encadrants"], r_data["tarifs"], r_data["categorie_age"],
                r_data["naissance_min"], r_data["naissance_max"]]
        display.append(line)
        ws.append(line)
        for c in range(1, len(headers) + 1):
            cell = ws.cell(row=ws.max_row, column=c)
            cell.border = border
            cell.alignment = Alignment(vertical="top", wrap_text=True)

    # Largeurs adaptées au contenu (bornées pour rester lisible)
    for c, h in enumerate(headers, start=1):
        longest = max([len(h)] + [len(str(line[c - 1])) for line in display]) if display else len(h)
        ws.column_dimensions[ws.cell(row=1, column=c).column_letter].width = min(42, max(10, longest + 2))
    ws.freeze_panes = "A2"

    wb.save(out_path)
    return out_path