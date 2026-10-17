import html as _html
import json
import re
import unicodedata
from typing import Any
import pandas as pd


def sanitize_email_header(value: Any) -> str:
    """E-mail header value without line breaks (header injection from member data)."""
    return " ".join(str(value or "").splitlines()).strip()


def json_for_script(obj: Any) -> str:
    """JSON safe to embed inside an inline <script> block.

    json.dumps does not escape `</script>` or `<!--`: a member value containing them
    would end the script and inject markup. `<`, `>`, `&` and the JS line separators
    are emitted as \\u escapes, which JSON.parse / JS literals decode back unchanged.
    """
    out = json.dumps(obj, ensure_ascii=False)
    for char, escape in (("<", "\\u003c"), (">", "\\u003e"), ("&", "\\u0026"),
                         (" ", "\\u2028"), (" ", "\\u2029")):
        out = out.replace(char, escape)
    return out

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

def format_periode(debut, fin=None) -> str:
    """Période d'une compétition pour les e-mails : « 12/03/2026 » ou
    « 12/03/2026 au 13/03/2026 » (fin vide ou identique au début = un seul jour)."""
    def fr(v):
        parts = str(v or "").strip().split("-")
        return f"{parts[2][:2]}/{parts[1]}/{parts[0]}" if len(parts) == 3 else str(v or "").strip()
    d, f = fr(debut), fr(fin)
    return d if (not f or f == d or not d) else f"{d} au {f}"


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


def apply_template_variables(text: str, member: Any, competition_context: dict = None,
                             escape_html: bool = False) -> str:
    """Remplace les variables de personnalisation {…} d'un sujet ou corps d'e-mail.

    Gère indifféremment un objet (ex: Member, SimpleNamespace) ou un dictionnaire :
    - {Prénom}/{Nom}/{first_name}/{last_name} : nom et prénom du destinataire ;
    - {num_licence} : licence FFME du destinataire ;
    - variables compétition : {no_competition}, {name_competition}, {montant_competition},
      {date_competition}, {whatapp_Id}, {bloc_whatsapp} (laissées telles quelles si absentes du contexte).

    escape_html=True: values are HTML-escaped, for a template already converted to HTML
    (member data comes from the public HelloAsso form and must never add markup).
    """
    if text is None:
        return ""
    ctx = competition_context or {}
    out = str(text)

    if isinstance(member, dict):
        first = str(member.get("user_first_name") or member.get("first_name") or member.get("prenom") or "").strip().title()
        last = str(member.get("user_last_name") or member.get("last_name") or member.get("nom") or "").strip().upper()
        licence = str(member.get("licence_ffme") or member.get("num_licence") or "").strip()
        tarif = str(member.get("tarif_name") or member.get("tarif") or "").strip()
        season = str(member.get("season_name") or member.get("season") or "").strip()
    else:
        first = str(getattr(member, "user_first_name", getattr(member, "first_name", getattr(member, "prenom", ""))) or "").strip().title()
        last = str(getattr(member, "user_last_name", getattr(member, "last_name", getattr(member, "nom", ""))) or "").strip().upper()
        licence = str(getattr(member, "licence_ffme", getattr(member, "num_licence", "")) or "").strip()
        tarif = str(getattr(member, "tarif_name", getattr(member, "tarif", "")) or "").strip()
        season = str(getattr(member, "season_name", getattr(member, "season", "")) or "").strip()

    enc = _html.escape if escape_html else (lambda v: v)
    out = out.replace("{Prénom}", enc(first))
    out = out.replace("{Nom}", enc(last))
    out = out.replace("{first_name}", enc(first))
    out = out.replace("{last_name}", enc(last))
    out = out.replace("{num_licence}", enc(licence))
    if tarif:
        out = out.replace("{tarif}", enc(tarif))
    if season:
        out = out.replace("{season}", enc(season))

    for key in ("no_competition", "name_competition", "montant_competition", "date_competition"):
        val = str(ctx.get(key) or "").strip()
        if val:
            out = out.replace("{" + key + "}", enc(val))

    wa_val = str(
        ctx.get("whatapp_Id")
        or ctx.get("whatsapp_link")
        or ctx.get("whatsapp_id")
        or ctx.get("whatapp_id")
        or ctx.get("whatsappLink")
        or ""
    ).strip()

    if wa_val:
        bloc_wa = enc(f"Voici le lien du groupe WhatApp dédié à cette compétition : {wa_val}")
        for b_key in ("bloc_whatsapp", "bloc_whatapp", "whatsapp_bloc"):
            out = out.replace("{" + b_key + "}", bloc_wa)
        for wa_key in ("whatapp_Id", "whatsapp_id", "whatapp_id", "whatsapp_Id", "whatsapp_link", "whatapp_link"):
            out = out.replace("{" + wa_key + "}", enc(wa_val))
    elif competition_context is not None:
        for b_key in ("bloc_whatsapp", "bloc_whatapp", "whatsapp_bloc"):
            out = out.replace("{" + b_key + "}", "")
        # Masquer la ligne dédiée au lien WhatsApp lorsqu'aucun lien n'est configuré
        out = re.sub(
            r"(?m)^[^\n]*\{(?:whatapp_Id|whatsapp_id|whatapp_id|whatsapp_Id|whatsapp_link|whatapp_link)\}[^\n]*\r?\n?",
            "",
            out,
        )
        out = re.sub(r"\n{3,}", "\n\n", out)
    return out

