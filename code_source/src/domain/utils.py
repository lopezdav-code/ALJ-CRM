import unicodedata
from typing import Any
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

def format_montant(prix) -> str:
    """Formate un montant en euros pour les e-mails : 15 -> « 15 », 15.5 -> « 15,50 »
    (séparateur décimal français, centimes nuls omis). None / vide / invalide -> « »."""
    if prix is None or (isinstance(prix, str) and not prix.strip()):
        return ""
    try:
        p = round(float(prix), 2)
    except (TypeError, ValueError):
        return ""
    txt = f"{p:.2f}".replace(".", ",")
    return txt[:-3] if txt.endswith(",00") else txt


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


def apply_template_variables(text: str, member: Any, competition_context: dict = None) -> str:
    """Remplace les variables de personnalisation {…} d'un sujet ou corps d'e-mail.

    Gère indifféremment un objet (ex: Member, SimpleNamespace) ou un dictionnaire :
    - {Prénom}/{Nom}/{first_name}/{last_name} : nom et prénom du destinataire ;
    - {num_licence} : licence FFME du destinataire ;
    - variables compétition : {no_competition}, {name_competition}, {montant_competition},
      {date_competition} (laissées telles quelles si absentes du contexte).
    """
    if text is None:
        return ""
    ctx = competition_context or {}
    out = str(text)

    if isinstance(member, dict):
        first = str(member.get("user_first_name") or member.get("first_name") or member.get("prenom") or "").strip().title()
        last = str(member.get("user_last_name") or member.get("last_name") or member.get("nom") or "").strip().upper()
        licence = str(member.get("licence_ffme") or member.get("num_licence") or "").strip()
    else:
        first = str(getattr(member, "user_first_name", getattr(member, "first_name", getattr(member, "prenom", ""))) or "").strip().title()
        last = str(getattr(member, "user_last_name", getattr(member, "last_name", getattr(member, "nom", ""))) or "").strip().upper()
        licence = str(getattr(member, "licence_ffme", getattr(member, "num_licence", "")) or "").strip()

    out = out.replace("{Prénom}", first)
    out = out.replace("{Nom}", last)
    out = out.replace("{first_name}", first)
    out = out.replace("{last_name}", last)
    out = out.replace("{num_licence}", licence)

    for key in ("no_competition", "name_competition", "montant_competition", "date_competition"):
        val = str(ctx.get(key) or "").strip()
        if val:
            out = out.replace("{" + key + "}", val)
    return out

