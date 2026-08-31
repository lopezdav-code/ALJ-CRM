"""
Rapport des données manquantes pour l'import FFME.

Parcourt les adhérents éligibles à l'export CSV FFME (saison active) et signale
chaque valeur de repli appliquée par le générateur (adresse/ville/code postal/
email/sexe par défaut, pays étranger, licence absente, personne à prévenir absente).

Génère un fichier Excel dans exports/ pour compléter les fiches adhérents.

Usage :
    python src/ffme_missing_report.py
"""
import os
import sys

_script_dir = os.path.dirname(os.path.abspath(__file__))
if _script_dir not in sys.path:
    sys.path.insert(0, _script_dir)

from paths import ROOT_DIR  # noqa: E402
from infrastructure.sqlite_repository import SqliteRepository  # noqa: E402


def build_report_rows():
    raw = SqliteRepository.load_direct_data(season_filter="2026-2027")
    rows = []
    for p0 in raw:
        p = {k: (v if v is not None else "") for k, v in p0.items()}
        tarif = str(p.get("tarif_name", "")).lower()
        amount = p.get("amount", 0.0) or 0.0
        status = str(p.get("status", "")).lower()
        commentaires = str(p.get("commentaires_correctif", "")).lower()
        is_manual = "ajout manuel" in commentaires
        if "attente" in tarif or (amount == 0.0 and not is_manual) or \
           "annul" in status or "cancel" in status or "termin" in status:
            continue  # exclu de l'export FFME

        lic = "".join(c for c in str(p.get("licence_ffme", "")) if c.isdigit())
        has_lic = 5 <= len(lic) <= 10

        missing = []
        if not str(p.get("address", "")).strip():
            missing.append("Adresse" + ("" if has_lic else " (repli: ADRESSE NON COMMUNIQUEE)"))
        if not str(p.get("city", "")).strip():
            missing.append("Ville" + ("" if has_lic else " (repli: JONAGE)"))
        if not "".join(c for c in str(p.get("zip_code", "")) if c.isdigit()):
            missing.append("Code postal" + ("" if has_lic else " (repli: 69330)"))
        email = str(p.get("email_primary", "")).strip() or str(p.get("payer_email", "")).strip()
        if not email:
            missing.append("Email" + ("" if has_lic else " (repli: contact@amicale-laique-jonage.fr)"))
        if not str(p.get("gender", "")).strip():
            missing.append("Sexe" + ("" if has_lic else " (repli: H)"))
        if not has_lic:
            missing.append("N° de licence FFME")
        if not str(p.get("emergency1_name", "")).strip():
            missing.append("Personne à prévenir 1")
        if not str(p.get("birth_date", "")).strip() and not str(p.get("birth_date_raw", "")).strip():
            missing.append("Date de naissance (fiche exclue de l'export)")
        if not missing:
            continue

        rows.append({
            "Nom": str(p.get("last_name", "")).upper(),
            "Prénom": str(p.get("first_name", "")),
            "Référence commande": p.get("order_ref", ""),
            "Tarif": p.get("tarif_name", ""),
            "Licence FFME": lic if lic else "(absente)",
            "Champs à compléter": " ; ".join(missing),
        })
    return rows


def main():
    from infrastructure.sqlite_repository import SqliteRepository
    SqliteRepository.setup_database()
    rows = build_report_rows()

    import pandas as pd
    out_dir = os.path.join(ROOT_DIR, "exports")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "Rapport_Donnees_Manquantes_FFME.xlsx")
    df = pd.DataFrame(rows)
    df.to_excel(out_path, index=False)
    print(f"📋 {len(rows)} fiche(s) à compléter -> {out_path}")
    return out_path


if __name__ == "__main__":
    main()
