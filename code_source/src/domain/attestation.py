"""Module de génération des attestations de paiement (HTML & PDF).

Fournit :
- build_attestation(member, season, date_jour) -> code HTML autonome ;
- render_attestation_pdf(html) -> octets du fichier PDF (WeasyPrint en mémoire) ;
- get_safe_pdf_filename(last_name, first_name, order_ref) -> nom de fichier PDF sécurisé.
"""

import base64
import datetime
import io
import os
import re
from typing import Any, Optional

from paths import CODE_ROOT, ROOT_DIR, find_doc_template


def get_french_date(dt: Optional[datetime.date] = None) -> str:
    """Retourne une date formatée en français (ex: '14 juillet 2026')."""
    months = {
        1: "janvier", 2: "février", 3: "mars", 4: "avril",
        5: "mai", 6: "juin", 7: "juillet", 8: "août",
        9: "septembre", 10: "octobre", 11: "novembre", 12: "décembre"
    }
    now = dt or datetime.datetime.now()
    return f"{now.day} {months[now.month]} {now.year}"


def get_safe_pdf_filename(last_name: str, first_name: str, order_ref: Optional[str] = None) -> str:
    """Génère un nom de fichier PDF nettoyé pour l'attestation."""
    ln = "".join(c for c in str(last_name or "").strip().upper() if c.isalnum() or c in (" ", "-", "_"))
    fn = "".join(c for c in str(first_name or "").strip().capitalize() if c.isalnum() or c in (" ", "-", "_"))
    safe_ln = ln.replace(" ", "_") or "ANONYME"
    safe_fn = fn.replace(" ", "_") or "Adherent"

    if order_ref:
        clean_ref = "".join(c for c in str(order_ref).strip() if c.isalnum() or c in ("-", "_"))
        if clean_ref:
            return f"Attestation_{safe_ln}_{safe_fn}_{clean_ref}.pdf"

    return f"Attestation_{safe_ln}_{safe_fn}.pdf"


def _image_to_base64_data_uri(file_path: str, mime_type: str = "image/png") -> Optional[str]:
    """Lit une image locale et la retourne sous forme d'URI data:image."""
    if not file_path or not os.path.exists(file_path):
        return None
    try:
        with open(file_path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode("ascii")
            return f"data:{mime_type};base64,{encoded}"
    except Exception:
        return None


def _find_image_path(name: str) -> Optional[str]:
    """Localise une image (logo, signature) dans code_source ou à la racine."""
    candidates = [
        os.path.join(CODE_ROOT, name),
        os.path.join(ROOT_DIR, name),
        os.path.join(CODE_ROOT, "doc", name),
        os.path.join(CODE_ROOT, "web", name)
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return None


def build_attestation(
    member: Any,
    season: Optional[str] = None,
    date_jour: Optional[str] = None
) -> str:
    """Génère le code HTML complet et autonome d'une attestation de paiement.

    Règles conservées :
    - Montant > 0 obligatoire (lève ValueError si montant nul ou manquant).
    - Commandes annulées ignorées (lève ValueError si statut annulé).
    - Payeur par défaut = l'adhérent lui-même si non renseigné.
    - Images embarquées en base64 (rendu indépendant du système de fichiers).
    """
    # 1. Extraction des champs (supporte indifféremment dict ou objet)
    def _get(key, alt=None):
        if isinstance(member, dict):
            val = member.get(key)
            return val if val is not None else (member.get(alt) if alt else None)
        val = getattr(member, key, None)
        return val if val is not None else (getattr(member, alt, None) if alt else None)

    # 2. Validation du statut (les commandes annulées sont exclues)
    status = str(_get("status_norm", "status") or "").strip().lower()
    if "annul" in status or "cancel" in status:
        raise ValueError("Impossible de générer une attestation pour une commande annulée.")

    # 3. Validation et formatage du montant
    amount_raw = _get("amount")
    if amount_raw is None or str(amount_raw).strip() == "":
        raise ValueError("Le montant de la cotisation est manquant.")
    try:
        amount_val = float(str(amount_raw).replace(",", "."))
    except (ValueError, TypeError):
        raise ValueError(f"Montant de cotisation invalide : {amount_raw}")

    if amount_val <= 0:
        raise ValueError("Le montant de la cotisation doit être supérieur à zéro.")

    amount_str = f"{amount_val:.2f}".replace(".", ",")

    # 4. Formatage du nom et du prénom de l'adhérent
    user_first = str(_get("first_name", "user_first_name") or "").strip().capitalize()
    user_last = str(_get("last_name", "user_last_name") or "").strip().upper()

    if not user_last and not user_first:
        raise ValueError("L'adhérent doit avoir un nom ou prénom renseigné.")

    # 5. Formatage du payeur (payeur par défaut = l'adhérent)
    payer_first = str(_get("payer_first_name") or "").strip().capitalize()
    payer_last = str(_get("payer_last_name") or "").strip().upper()
    payer_full = str(_get("payer") or "").strip()

    if not payer_first and not payer_last:
        if payer_full:
            parts = payer_full.split()
            if len(parts) >= 2:
                payer_first = parts[0].capitalize()
                payer_last = " ".join(parts[1:]).upper()
            else:
                payer_first = parts[0].capitalize()
                payer_last = ""
        else:
            payer_first = user_first
            payer_last = user_last

    # 6. Date du jour et saison
    date_jour_fr = date_jour or get_french_date()
    if not season:
        season = str(_get("season_name") or "").strip()
    if not season:
        try:
            from domain.constants import get_active_season
            season = get_active_season()
        except Exception:
            season = "2026-2027"

    # 7. Chargement du template HTML
    template_path = find_doc_template("ATTESTATION_TEMPLATE.html")
    if not template_path or not os.path.exists(template_path):
        raise FileNotFoundError(f"Modèle d'attestation HTML introuvable : {template_path}")

    with open(template_path, "r", encoding="utf-8") as f:
        html = f.read()

    # 8. Remplacement des variables du modèle
    html = html.replace("{Date du jour}", date_jour_fr)
    html = html.replace("{Nom payeur}", payer_last)
    html = html.replace("{prénom payeur}", payer_first)
    html = html.replace("{Nom adhérent}", user_last)
    html = html.replace("{Prénom adhérent}", user_first)
    html = html.replace("{Montant}", amount_str)
    html = html.replace("{Saison}", season)

    # 9. Embarquement des images en base64 pour un HTML 100% autonome
    logo_path = _find_image_path("logo.png")
    if logo_path:
        logo_data = _image_to_base64_data_uri(logo_path, "image/png")
        if logo_data:
            html = re.sub(r'src=["\']logo\.png["\']', f'src="{logo_data}"', html)

    sig_path = _find_image_path("signature.jpg") or _find_image_path("doc/signature.jpg")
    if sig_path:
        sig_data = _image_to_base64_data_uri(sig_path, "image/jpeg")
        if sig_data:
            html = re.sub(r'src=["\'](?:doc/)?signature\.jpg["\']', f'src="{sig_data}"', html)

    return html


def _render_minimal_pdf_with_pydyf(html: str) -> bytes:
    """Générateur de secours pur Python (pydyf) si WeasyPrint n'a pas Pango sous Windows."""
    import pydyf

    # Extraction du texte pertinent depuis le HTML
    title_match = re.search(r"<h2>(.*?)</h2>", html, re.I)
    title = title_match.group(1).strip() if title_match else "Attestation de Paiement"

    adh_match = re.search(r"<span>Adhérent</span>\s*<strong>(.*?)</strong>", html, re.I | re.S)
    adherent = adh_match.group(1).strip() if adh_match else ""

    payer_match = re.search(r"<span>Payeur[^<]*</span>\s*<strong>(.*?)</strong>", html, re.I | re.S)
    payer = payer_match.group(1).strip() if payer_match else ""

    amount_match = re.search(r"<span>Montant perçu</span>\s*<strong>(.*?)</strong>", html, re.I | re.S)
    amount = amount_match.group(1).strip() if amount_match else ""

    date_match = re.search(r"Date\s*:\s*<strong>(.*?)</strong>", html, re.I)
    date_val = date_match.group(1).strip() if date_match else ""

    season_match = re.search(r"Saison\s*:\s*<strong>(.*?)</strong>", html, re.I)
    season_val = season_match.group(1).strip() if season_match else ""

    def clean(txt):
        import unicodedata
        return unicodedata.normalize("NFKD", str(txt or "")).encode("ascii", "ignore").decode("ascii").replace("(", "[").replace(")", "]")

    pdf = pydyf.PDF()
    font = pydyf.Dictionary({"Type": "/Font", "Subtype": "/Type1", "BaseFont": "/Helvetica"})
    font_bold = pydyf.Dictionary({"Type": "/Font", "Subtype": "/Type1", "BaseFont": "/Helvetica-Bold"})
    font_ref = pdf.add_object(font)
    font_b_ref = pdf.add_object(font_bold)

    stream_cmds = [
        b"BT",
        b"/F2 20 Tf 50 780 Td (ALJ Escalade - Amicale Laique de Jonage) Tj",
        f"/F1 11 Tf 0 -22 Td (Date : {clean(date_val)} | Saison : {clean(season_val)}) Tj".encode("ascii"),
        f"/F2 16 Tf 0 -38 Td ({clean(title).upper()}) Tj".encode("ascii"),
        b"/F1 11 Tf 0 -30 Td (Je soussigne, le President de l'Amicale Laique de Jonage - Section Escalade, certifie) Tj",
        b"0 -16 Td (que la personne mentionnee ci-dessous s'est acquittee de sa cotisation annuelle.) Tj",
        f"/F2 12 Tf 0 -36 Td (Adherent : {clean(adherent)}) Tj".encode("ascii"),
        f"/F1 11 Tf 0 -18 Td (Payeur : {clean(payer)}) Tj".encode("ascii"),
        f"/F2 12 Tf 0 -18 Td (Montant regle : {clean(amount)}) Tj".encode("ascii"),
        b"/F1 11 Tf 0 -18 Td (Reglement HelloAsso - Carte Bancaire) Tj",
        b"0 -40 Td (Attestation delivree pour faire valoir ce que de droit.) Tj",
        b"0 -40 Td (Pour le Bureau de l'ALJ Escalade) Tj",
        b"ET"
    ]

    stream = pydyf.Stream([b"\n".join(stream_cmds)])
    stream_ref = pdf.add_object(stream)

    page = pydyf.Dictionary({
        "Type": "/Page",
        "MediaBox": pydyf.Array([0, 0, 595, 842]),  # Format A4
        "Resources": pydyf.Dictionary({
            "Font": pydyf.Dictionary({
                "F1": font_ref,
                "F2": font_b_ref
            })
        }),
        "Contents": stream_ref
    })
    pdf.add_page(page)

    buf = io.BytesIO()
    pdf.write(buf)
    return buf.getvalue()


def render_attestation_pdf(html: str) -> bytes:
    """Génère le flux binaire PDF à partir du code HTML.

    Sous Linux (Cloud Run avec libpango), WeasyPrint assure le rendu complet.
    En environnement de test ou Windows sans bibliothèque C Pango, un fallback
    pur Python (pydyf) génère un document PDF binaire valide.
    """
    try:
        from weasyprint import HTML
        return HTML(string=html).write_pdf()
    except (ImportError, OSError):
        return _render_minimal_pdf_with_pydyf(html)
