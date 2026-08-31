import os
import openpyxl
from openpyxl.styles import Border, Side, PatternFill, Font, Alignment
from paths import ROOT_DIR

def clean_filename(name):
    """Nettoie le nom d'un groupe pour en faire un nom de fichier valide."""
    safe = "".join(c for c in name if c.isalnum() or c in (" ", "-", "_"))
    safe = safe.replace(" ", "_")
    return safe.strip("_")

def format_contact_name(full_name_str):
    """
    Formate un nom de contact (NOM Prénom) d'urgence :
    - Met le nom de famille en MAJUSCULES (ex: LOPEZ).
    - Met le prénom en minuscules avec la première lettre en majuscule (ex: David).
    Gère intelligemment les noms composés et les casses hétérogènes d'origine.
    """
    raw_name = str(full_name_str).strip()
    if not raw_name:
        return ""
        
    words = [w.strip() for w in raw_name.split() if w.strip()]
    if not words:
        return ""
        
    if len(words) == 1:
        # Un seul mot : on assume que c'est un NOM de famille par défaut (donc MAJUSCULES)
        return words[0].upper()
        
    # Heuristique pour séparer NOM et Prénom
    has_upper = any(w.isupper() and len(w) > 1 for w in words)
    has_lower = any(not w.isupper() for w in words)
    
    formatted_words = []
    if has_upper and has_lower:
        # Cas mixte (ex: "LOPEZ David" ou "David LOPEZ")
        for w in words:
            if "-" in w:
                parts = [p.capitalize() for p in w.split("-")]
                w_cap = "-".join(parts)
            else:
                w_cap = w.capitalize()
                
            if w.isupper() and len(w) > 1:
                formatted_words.append(w.upper()) # NOM reste en MAJUSCULES
            else:
                formatted_words.append(w_cap) # Prénom mis en Capitalize (ex: David)
    else:
        # Cas uniforme (ex: "lopez david" ou "LOPEZ DAVID")
        # Par convention administrative, le premier mot est considéré comme le NOM de famille (MAJUSCULES)
        # et les suivants sont considérés comme les Prénoms (Capitalize)
        for idx, w in enumerate(words):
            if "-" in w:
                parts = [p.capitalize() for p in w.split("-")]
                w_cap = "-".join(parts)
            else:
                w_cap = w.capitalize()
                
            if idx == 0:
                formatted_words.append(w.upper()) # Premier mot = NOM en majuscules
            else:
                formatted_words.append(w_cap) # Autres mots = Prénoms
                
    return " ".join(formatted_words)

def generate_urgency_contacts_sheet(participants_data):
    """
    Génère une liste globale triée des contacts d'urgence de tous les adhérents actifs,
    conçue pour une impression propre sur feuille A4 verticale.
    """
    root_dir = ROOT_DIR
    output_dir = os.path.join(root_dir, "exports")
    os.makedirs(output_dir, exist_ok=True)
    
    # 1. Filtrer les adhérents actifs (montant > 0, exclure les listes d'attente, exclure les annulés)
    active_participants = []
    for p in participants_data:
        t_name = str(p.get("tarif_name") or "").lower()
        amount = p.get("amount", 0.0)
        status = str(p.get("status") or "").lower()
        if "attente" in t_name or amount == 0.0 or "annul" in status:
            continue
        active_participants.append(p)
        
    # Trier par Nom de famille puis Prénom (insensible à la casse)
    active_participants.sort(key=lambda x: (
        str(x.get("last_name") or "").strip().lower(),
        str(x.get("first_name") or "").strip().lower()
    ))
    
    # 2. Créer un nouveau classeur Excel avec openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Contacts Urgence"
    
    # Activer le quadrillage pour l'impression
    ws.views.sheetView[0].showGridLines = True
    
    # Styles
    thin_gray = Side(style='thin', color='CCCCCC')
    thick_blue = Side(style='medium', color='1E3A8A')
    double_blue = Side(style='double', color='1E3A8A')
    
    border_thin = Border(left=thin_gray, right=thin_gray, top=thin_gray, bottom=thin_gray)
    border_header = Border(left=thin_gray, right=thin_gray, top=thick_blue, bottom=double_blue)
    
    fill_header = PatternFill(start_color="F2F4F8", end_color="F2F4F8", fill_type="solid")
    fill_zebra = PatternFill(start_color="F9F9F9", end_color="F9F9F9", fill_type="solid")
    fill_white = PatternFill(start_color="FFFFFF", end_color="FFFFFF", fill_type="solid")
    
    font_main_title = Font(name="Segoe UI", size=12, bold=True, color="1E3A8A")
    font_sub_title = Font(name="Segoe UI", size=10, bold=True, color="EA580C") # Orange pour urgence
    font_info = Font(name="Segoe UI", size=9, bold=False, color="4B5563")
    font_header = Font(name="Segoe UI", size=9, bold=True, color="374151")
    font_data = Font(name="Segoe UI", size=9, bold=False, color="1F2937")
    
    align_center = Alignment(horizontal="center", vertical="center")
    align_left = Alignment(horizontal="left", vertical="center")
    align_wrap_left = Alignment(horizontal="left", vertical="center", wrap_text=True)
    
    # 3. Remplir l'en-tête (Informations d'Urgence et Coordonnées ALJ)
    ws['A1'] = "📍 AMICALE LAÏQUE DE JONAGE (ALJ) - SECTION ESCALADE"
    ws['A1'].font = font_main_title
    
    ws['A2'] = "📞 NUMÉROS ET CONTACTS D'URGENCE :"
    ws['A2'].font = font_sub_title
    
    ws['A3'] = "Urgence : 112 | Samu : 15 | Pompiers : 18 | Police : 17 | SOS Médecins : 36 24"
    ws['A3'].font = Font(name="Segoe UI", size=9, bold=True, color="991B1B") # Rouge foncé pour les numéros
    
    ws['A4'] = "Gendarmerie Jonage : 17 | Mairie de Jonage : 04 78 31 21 10 | Notre adresse : ALJ Espace Agora, 23 Rue du Lavoir, 69330 Jonage"
    ws['A4'].font = font_info
    
    # Fusionner les lignes d'en-tête pour un rendu parfait sur A4
    for r in (1, 2, 3, 4):
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=4)
        
    # Sauter la ligne 5 (laisser vide)
    
    # 4. En-tête du tableau sur la Ligne 6
    headers = ["Nom", "Prénom", "Groupe / Cours", "Contacts d'Urgence"]
    for col_idx, h_text in enumerate(headers, 1):
        cell = ws.cell(row=6, column=col_idx, value=h_text)
        cell.font = font_header
        cell.fill = fill_header
        cell.alignment = align_left if col_idx != 4 else align_wrap_left
        cell.border = border_header
        
    # 5. Remplir la liste des adhérents
    row_idx = 7
    for p in active_participants:
        last_name = str(p.get("last_name") or "").strip().upper()
        first_name = str(p.get("first_name") or "").strip().capitalize()
        group_name = str(p.get("tarif_name") or "").strip()
        
        # Concaténer les deux contacts d'urgence (avec formatage NOM et Prénom)
        c1_name_raw = str(p.get("emergency1_name") or "").strip()
        c1_name = format_contact_name(c1_name_raw)
        c1_tel = str(p.get("emergency1_phone") or "").strip()
        
        c2_name_raw = str(p.get("emergency2_name") or "").strip()
        c2_name = format_contact_name(c2_name_raw)
        c2_tel = str(p.get("emergency2_phone") or "").strip()
        
        contacts = []
        if c1_name or c1_tel:
            contacts.append(f"1) {c1_name} ({c1_tel})" if c1_tel else f"1) {c1_name}")
        if c2_name or c2_tel:
            contacts.append(f"2) {c2_name} ({c2_tel})" if c2_tel else f"2) {c2_name}")
            
        contact_str = "\n".join(contacts) if contacts else "-"
        
        # Écriture dans les cellules
        cell_last = ws.cell(row=row_idx, column=1, value=last_name)
        cell_first = ws.cell(row=row_idx, column=2, value=first_name)
        cell_group = ws.cell(row=row_idx, column=3, value=group_name)
        cell_contact = ws.cell(row=row_idx, column=4, value=contact_str)
        
        is_zebra = (row_idx % 2 == 0)
        row_fill = fill_zebra if is_zebra else fill_white
        
        # Appliquer les polices, alignements et bordures
        for col_col, cell in enumerate((cell_last, cell_first, cell_group, cell_contact), 1):
            cell.font = font_data
            cell.fill = row_fill
            cell.border = border_thin
            if col_col == 4:
                cell.alignment = align_wrap_left
            else:
                cell.alignment = align_left
                
        row_idx += 1
        
    # 6. Définir des largeurs de colonnes fixes et élégantes pour l'impression A4 Portrait
    ws.column_dimensions['A'].width = 18  # Nom
    ws.column_dimensions['B'].width = 18  # Prénom
    ws.column_dimensions['C'].width = 28  # Groupe
    ws.column_dimensions['D'].width = 42  # Contacts d'urgence (largeur généreuse pour les numéros)
    
    # Ajuster la hauteur des lignes de données pour afficher les multilignes proprement
    for r in range(7, row_idx):
        ws.row_dimensions[r].height = 28
        
    # 7. Forcer la mise en page d'impression sur format A4 Portrait (Vertical)
    ws.page_setup.orientation = 'portrait'  # Portrait
    ws.page_setup.paperSize = 9  # PAPERSIZE_A4 (9 dans Excel Page Setup)
    
    # Ajuster pour que tout rentre sur la largeur de la page (Fit to 1 page wide)
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.page_setup.fitToPage = True
    
    # 8. Sauvegarder le classeur Excel final
    save_filename = "Liste_Contacts_Urgence_ALJ.xlsx"
    save_path = os.path.join(output_dir, save_filename)
    wb.save(save_path)
    wb.close()
    
    print(f"[URGENCY] Liste d'urgence globale générée avec succès : {save_filename}")
    return True, save_filename
