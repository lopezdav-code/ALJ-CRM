import os
import requests
import lxml.html
import pandas as pd
from paths import ROOT_DIR

def scrape_mycompet(progress_callback=None) -> str:
    """
    Scrape les résultats de compétitions FFME depuis https://escalade.online/resultat/
    et génère un fichier Excel consolidé dans exports/MyCompet.xlsx.
    Retourne le chemin d'accès au fichier généré.
    """
    disciplines = ["BLOC", "VITESSE", "DIFFICULTÉ"]
    list_cat = ["U13", "U13", "U15", "U15", "U17", "U17", "U19", "U19", "SÉNIOR", "SÉNIOR", "VÉTÉRAN", "VÉTÉRAN"]
    list_sexe = ["FEMME", "HOMME", "FEMME", "HOMME", "FEMME", "HOMME", "FEMME", "HOMME", "FEMME", "HOMME", "FEMME", "HOMME"]
    
    def detect_criterion(tbl_element, keywords):
        # Récupérer l'élément parent externe
        parent = tbl_element.getparent()
        if parent is not None:
            html_snippet = lxml.html.tostring(parent, encoding="utf-8").decode("utf-8").upper()
        else:
            html_snippet = lxml.html.tostring(tbl_element, encoding="utf-8").decode("utf-8").upper()
            
        if len(html_snippet) < 50:
            html_snippet = lxml.html.tostring(tbl_element, encoding="utf-8").decode("utf-8").upper()
            
        # Nettoyage UTF-8 et accents
        html_snippet = html_snippet.replace("Ã©", "E").replace("É", "E")
        
        for kw in keywords:
            kw_clean = kw.upper().replace("É", "E")
            if kw_clean in html_snippet:
                return kw
        return ""

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept-Encoding": "identity"
    }
    
    all_rows = []
    header_cols = []
    
    for num_page in range(1, 4):
        disc = disciplines[num_page - 1]
        url = f"https://escalade.online/resultat/classement_{num_page}.html"
        
        if progress_callback:
            progress_callback(f"🌐 Téléchargement de la discipline : {disc}...", 30 + num_page * 15)
            
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code != 200:
            raise Exception(f"Impossible de charger la page {url} (code {response.status_code})")
            
        # Parser le HTML
        html_text = response.text
        doc = lxml.html.fromstring(html_text)
        tables = doc.xpath("//table")
        
        if progress_callback:
            progress_callback(f"📊 Analyse des données de {disc} ({len(tables)} tableaux)...", 30 + num_page * 15 + 5)
            
        valid_table_count = 0
        for tbl in tables:
            rows = tbl.xpath(".//tr")
            if len(rows) > 2:
                valid_table_count += 1
                
                # 1. Détection de la catégorie et du sexe
                cat = detect_criterion(tbl, ["U13", "U15", "U17", "U19", "SÉNIOR", "SENIOR", "VÉTÉRAN", "VETERAN"])
                sexe = detect_criterion(tbl, ["FEMME", "HOMME", "DAMES", "MESSIEURS"])
                
                # Normalisation
                if cat == "SENIOR": cat = "SÉNIOR"
                if cat == "VETERAN": cat = "VÉTÉRAN"
                if sexe == "DAMES": sexe = "FEMME"
                if sexe == "MESSIEURS": sexe = "HOMME"
                
                # Repli automatique
                if not cat:
                    cat = list_cat[(valid_table_count - 1) % 12]
                if not sexe:
                    sexe = list_sexe[(valid_table_count - 1) % 12]
                    
                # 2. Lecture des lignes du tableau
                for r in rows:
                    # Chercher les td, sinon th
                    cells = r.xpath(".//td")
                    if len(cells) == 0:
                        cells = r.xpath(".//th")
                        is_header_row = True
                    else:
                        is_header_row = False
                        
                    cell_texts = [cell.text_content().strip() for cell in cells]
                    
                    if is_header_row:
                        # Si on n'a pas encore défini les en-têtes globaux de colonnes
                        if not header_cols and len(cell_texts) > 0:
                            header_cols = ["Discipline", "Catégorie", "Sexe"] + cell_texts
                    else:
                        # Ligne de données
                        data_row = [disc, cat, sexe] + cell_texts
                        all_rows.append(data_row)
                        
    if not all_rows:
        raise Exception("Aucune donnée de classement trouvée sur le site.")
        
    # Construire les noms de colonnes si absents
    if not header_cols:
        max_cols = max(len(row) for row in all_rows)
        header_cols = ["Discipline", "Catégorie", "Sexe"] + [f"Col {i}" for i in range(4, max_cols + 1)]
        
    # S'assurer que chaque ligne de données a le même nombre de colonnes que l'en-tête (en complétant par du vide)
    num_headers = len(header_cols)
    for idx, r in enumerate(all_rows):
        if len(r) < num_headers:
            all_rows[idx] = r + [""] * (num_headers - len(r))
        elif len(r) > num_headers:
            all_rows[idx] = r[:num_headers]
            
    # Créer le DataFrame pandas
    df = pd.DataFrame(all_rows, columns=header_cols)
    
    if progress_callback:
        progress_callback("💾 Enregistrement et mise en page du fichier Excel...", 90)
        
    # Enregistrer le résultat
    dest_file = os.path.join(ROOT_DIR, "exports", "MyCompet.xlsx")
    os.makedirs(os.path.dirname(dest_file), exist_ok=True)
    df.to_excel(dest_file, index=False)
    
    # Rendre l'ajustement automatique des colonnes avec openpyxl pour faire un joli rendu Excel !
    import openpyxl
    wb = openpyxl.load_workbook(dest_file)
    ws = wb.active
    
    # Rendre l'en-tête gras (Font style)
    from openpyxl.styles import Font
    bold_font = Font(bold=True)
    for cell in ws[1]:
        cell.font = bold_font
        
    # Auto-fit columns
    for col in ws.columns:
        max_len = max(len(str(cell.value or '')) for cell in col)
        col_letter = openpyxl.utils.get_column_letter(col[0].column)
        ws.column_dimensions[col_letter].width = max(max_len + 3, 10)
        
    wb.save(dest_file)
    wb.close()
    
    return dest_file
