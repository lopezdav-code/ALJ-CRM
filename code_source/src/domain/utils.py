import unicodedata
import pandas as pd

def normalize_string(s) -> str:
    """
    Normalisation générale d'une chaîne : conversion en minuscules, 
    retrait des accents (NFD/Mn) et suppression des espaces superflus.
    """
    if s is None or pd.isna(s):
        return ""
    s = str(s).strip().lower()
    # Retrait des accents
    s = "".join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')
    return s

def normalize_name(s) -> str:
    """
    Normalisation spécifique pour la comparaison des noms et prénoms d'adhérents.
    En plus du retrait des accents et minuscules, remplace les tirets par des espaces
    et nettoie les doubles espaces.
    """
    s = normalize_string(s)
    # Remplacer les tirets par des espaces
    s = s.replace("-", " ")
    # Supprimer les doubles espaces
    return " ".join(s.split())

def normalize_key_part(s) -> str:
    """
    Normalisation spécifique pour les clés de créneaux/tarifs du planning.
    Retire les espaces, tirets et deux-points pour des comparaisons robustes.
    """
    s = normalize_string(s)
    return s.replace("-", "").replace(" ", "").replace(":", "")

def clean_city_name(city_raw) -> str:
    """
    Harmonise et nettoie les noms de villes pour éviter les doublons (ex: Villette d'Anthon).
    """
    if city_raw is None or pd.isna(city_raw):
        return "Inconnue"
    c = str(city_raw).replace("’", "'").replace("‘", "'").replace("-", " ").strip()
    c = c.upper()
    c = c.replace(" D ", " D'").replace(" D' ", " D'")
    c = c.title()
    return " ".join(c.split())
