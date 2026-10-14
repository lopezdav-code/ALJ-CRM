"""
Service d'automatisation quotidienne des résultats de compétitions FFME / MyCompet.

Exécute chaque jour (par exemple à 07h00) :
1. Sélectionne les compétitions passées sans résultats complets.
2. Tente de récupérer automatiquement les résultats officiels depuis MyCompet FFME.
3. Rapproche et met à jour les classements des compétiteurs du club.
4. Envoie un e-mail de notification récapitulatif avec un tableau HTML soigné
   à l'adresse configurée (par défaut : david.lopez@alj-jonage.fr).
"""

from __future__ import annotations

import os
import sys
import datetime
from typing import List, Dict, Any, Optional, Tuple

# Injection du dossier src dans sys.path si nécessaire
_src_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from infrastructure.email_repository import EmailRepository
from infrastructure.sqlite_repository import SqliteRepository
from mycompet_scraper import fetch_and_parse_mycompet_results, normalize_result_url, find_mycompet_result_url

DEFAULT_NOTIFICATION_EMAIL = "david.lopez@alj-jonage.fr"
SETTING_NOTIFICATION_EMAIL = "RESULTATS_NOTIFICATION_EMAIL"
SETTING_BATCH_LAST_RUN = "RESULTATS_BATCH_LAST_RUN"
SETTING_BATCH_LAST_STATUS = "RESULTATS_BATCH_LAST_STATUS"


class CompetitionResultsBatchService:
    """Orchestre la détection quotidienne des résultats et la notification par e-mail."""

    @classmethod
    def get_notification_email(cls) -> str:
        """Retourne l'e-mail de notification configuré, ou l'adresse par défaut."""
        try:
            val = SqliteRepository.get_app_setting(SETTING_NOTIFICATION_EMAIL, "")
            if val and "@" in str(val).strip():
                return str(val).strip()
        except Exception:
            pass
        return DEFAULT_NOTIFICATION_EMAIL

    @classmethod
    def set_notification_email(cls, email: str) -> bool:
        """Enregistre l'adresse e-mail de notification."""
        clean = str(email or "").strip()
        if not clean or "@" not in clean or "." not in clean:
            raise ValueError("Adresse e-mail de notification invalide.")

        ok = False
        try:
            ok = SqliteRepository.save_app_setting(SETTING_NOTIFICATION_EMAIL, clean)
        except Exception:
            pass

        # Miroir Firestore si disponible
        try:
            from infrastructure.competition_firestore_repository import CompetitionFirestoreRepository
            CompetitionFirestoreRepository.save_app_setting(SETTING_NOTIFICATION_EMAIL, clean)
            ok = True
        except Exception:
            pass

        return ok

    @classmethod
    def get_batch_status(cls) -> Dict[str, Any]:
        """Retourne les indicateurs du dernier passage du batch."""
        last_run = SqliteRepository.get_app_setting(SETTING_BATCH_LAST_RUN, "") or ""
        last_status = SqliteRepository.get_app_setting(SETTING_BATCH_LAST_STATUS, "") or ""
        return {
            "notification_email": cls.get_notification_email(),
            "last_run": last_run,
            "last_status": last_status,
            "cron_schedule": "Tous les jours à 07h00"
        }

    @classmethod
    def is_competition_past(cls, comp: Dict[str, Any], today: Optional[datetime.date] = None) -> bool:
        """Vérifie si une compétition est déjà réalisée et terminée."""
        if today is None:
            today = datetime.date.today()

        date_fin_str = str(comp.get("date_fin") or "").strip()
        date_debut_str = str(comp.get("date_competition") or "").strip()
        target_str = date_fin_str or date_debut_str

        if not target_str:
            return False

        try:
            c_date = datetime.date.fromisoformat(target_str[:10])
            return c_date <= today
        except Exception:
            return False

    @classmethod
    def has_results(cls, comp: Dict[str, Any]) -> bool:
        """Vérifie si une compétition a déjà des résultats enregistrés."""
        # Si un horodatage de synchronisation existe et au moins un classement est présent
        synced_at = comp.get("resultats_synced_at")
        parts = comp.get("participants") or []
        has_rankings = any(bool(str(p.get("classement") or "").strip() or str(p.get("resultat_ffme") or "").strip()) for p in parts)
        return bool(synced_at and has_rankings)

    @classmethod
    def list_pending_competitions(cls, force: bool = False) -> List[Dict[str, Any]]:
        """
        Sélectionne les compétitions passées qui n'ont pas encore de résultats enregistrés.
        Cherche dans Firestore en priorité, puis dans SQLite en secours.
        """
        comps = []
        today = datetime.date.today()

        # 1. Tentative de lecture Firestore
        try:
            from infrastructure.firestore_client import FirestoreClient
            raw_docs = FirestoreClient.get_collection("competitions")
            for doc in (raw_docs or []):
                doc_dict = dict(doc)
                if cls.is_competition_past(doc_dict, today):
                    if force or not cls.has_results(doc_dict):
                        comps.append(doc_dict)
        except Exception as e:
            print(f"⚠️ [BATCH_RESULTATS] Lecture Firestore impossible, repli SQLite : {e}")

        # 2. Si aucune compétition trouvée via Firestore, essayer SQLite
        if not comps:
            try:
                from infrastructure.competition_repository import CompetitionRepository
                if os.path.exists(CompetitionRepository.get_db_path()):
                    CompetitionRepository.setup_database()
                    conn = CompetitionRepository.get_connection()
                    try:
                        rows = conn.execute("SELECT * FROM competitions").fetchall()
                        for r in rows:
                            row_dict = dict(r)
                            cid = row_dict.get("id")
                            # Charger les participants
                            part_rows = conn.execute("SELECT * FROM participants WHERE competition_id = ?", (cid,)).fetchall()
                            row_dict["participants"] = [dict(p) for p in part_rows]
                            if cls.is_competition_past(row_dict, today):
                                if force or not cls.has_results(row_dict):
                                    comps.append(row_dict)
                    finally:
                        conn.close()
            except Exception as e:
                print(f"⚠️ [BATCH_RESULTATS] Lecture SQLite impossible : {e}")

        return comps

    @classmethod
    def sync_results_for_competition(cls, comp: Dict[str, Any], club_keyword: str = "JONAGE") -> Tuple[int, List[Dict[str, Any]], str]:
        """
        Tente de trouver et de récupérer les résultats MyCompet pour une compétition.
        Retourne : (nombre_d_athletes_classes, liste_des_resultats_adherents, url_utilisee)
        """
        cid = str(comp.get("id") or comp.get("doc_id") or "")
        nom = comp.get("nom") or ""
        date = comp.get("date_competition") or ""
        lieu = comp.get("lieu") or ""
        id_ffme = str(comp.get("id_ffme") or "")

        url = str(comp.get("url_resultats") or comp.get("id_resultat_ffme") or "").strip()

        # Recherche automatique de l'URL si absente
        if not url:
            auto_url = find_mycompet_result_url(nom, date, lieu, id_ffme)
            if auto_url:
                url = auto_url

        if not url:
            return 0, [], ""

        try:
            scraped = fetch_and_parse_mycompet_results(url, club_keyword)
        except Exception as e:
            print(f"⚠️ [BATCH_RESULTATS] Échec scraping {nom} ({url}) : {e}")
            return 0, [], url

        if not scraped:
            return 0, [], url

        canonical_url = normalize_result_url(url)
        now_iso = datetime.datetime.now().isoformat()

        # Indexer les résultats scrapés
        by_licence = {}
        by_name = {}
        for r in scraped:
            lic = str(r.get("licence") or "").strip()
            if lic:
                by_licence[lic] = r
            full = f"{r.get('nom', '')} {r.get('prenom', '')}".strip().lower()
            if full:
                by_name[full] = r

        participants = list(comp.get("participants") or [])
        matched_athletes = []
        matched_count = 0

        for p in participants:
            p_lic = str(p.get("num_licence") or "").strip()
            p_name = f"{p.get('nom', '')} {p.get('prenom', '')}".strip().lower()

            match = by_licence.get(p_lic) or by_name.get(p_name)
            if match:
                matched_count += 1
                cl = str(match.get("classement") or "").strip()
                tot = int(match.get("total_categorie") or 0)
                p["classement"] = cl
                p["total_categorie"] = tot
                suffix = f" / {tot}" if tot > 0 else "e"
                p["resultat_ffme"] = f"{cl}{suffix}" if cl else ""
                p["categorie_ffme"] = match.get("categorie") or ""
                p["performance_ffme"] = match.get("performance") or ""
                p["resultat_synced_at"] = now_iso

                matched_athletes.append({
                    "nom": p.get("nom") or match.get("nom"),
                    "prenom": p.get("prenom") or match.get("prenom"),
                    "num_licence": p_lic or match.get("licence"),
                    "categorie": match.get("categorie") or p.get("categorie") or "",
                    "classement": cl,
                    "total_categorie": tot,
                    "resultat_ffme": p["resultat_ffme"],
                    "performance": match.get("performance") or ""
                })

        # Trier les athlètes par classement
        def _sort_rank(a):
            try:
                return int(a["classement"])
            except Exception:
                return 9999

        matched_athletes.sort(key=_sort_rank)

        # Si des résultats ont été matchés, enregistrer dans Firestore et SQLite
        if matched_count > 0:
            # 1. Sauvegarde Firestore
            try:
                from infrastructure.firestore_client import FirestoreClient
                FirestoreClient.update_fields("competitions", cid, {
                    "participants": participants,
                    "url_resultats": canonical_url,
                    "resultats_synced_at": now_iso
                })
            except Exception as e:
                print(f"⚠️ [BATCH_RESULTATS] Sauvegarde Firestore impossible : {e}")

            # 2. Sauvegarde SQLite miroir
            try:
                from infrastructure.competition_repository import CompetitionRepository
                if os.path.exists(CompetitionRepository.get_db_path()):
                    CompetitionRepository.setup_database()
                    conn = CompetitionRepository.get_connection()
                    try:
                        conn.execute(
                            "UPDATE competitions SET url_resultats = ?, resultats_synced_at = ? WHERE id = ? OR id_ffme = ?",
                            (canonical_url, now_iso, cid, cid)
                        )
                        for p in participants:
                            aid = p.get("adherent_id")
                            if aid:
                                conn.execute(
                                    """UPDATE participants SET classement = ?, total_categorie = ?, resultat_ffme = ?,
                                       categorie_ffme = ?, performance_ffme = ?, resultat_synced_at = ?
                                       WHERE (competition_id = ? OR competition_id = (SELECT id FROM competitions WHERE id_ffme = ?))
                                       AND adherent_id = ?""",
                                    (p.get("classement") or "", int(p.get("total_categorie") or 0), p.get("resultat_ffme") or "",
                                     p.get("categorie_ffme") or "", p.get("performance_ffme") or "",
                                     now_iso, cid, cid, aid)
                                )
                        conn.commit()
                    finally:
                        conn.close()
            except Exception as e:
                print(f"⚠️ [BATCH_RESULTATS] Sauvegarde SQLite locale impossible : {e}")

        return matched_count, matched_athletes, canonical_url

    @classmethod
    def build_results_email_html(cls, comp_results_list: List[Dict[str, Any]]) -> str:
        """Génère un e-mail HTML soigné présentant les tableaux de résultats des compétitions."""
        comp_sections = []

        for item in comp_results_list:
            nom_comp = item.get("nom") or "Compétition"
            date_comp = item.get("date") or ""
            lieu_comp = item.get("lieu") or ""
            url = item.get("url") or ""
            athletes = item.get("athletes") or []

            # Formatage de la date si possible
            date_formatted = date_comp
            try:
                d = datetime.date.fromisoformat(date_comp[:10])
                date_formatted = d.strftime("%d/%m/%Y")
            except Exception:
                pass

            meta_parts = [p for p in [date_formatted, lieu_comp] if p]
            meta_str = " · ".join(meta_parts)

            rows_html = []
            for ath in athletes:
                cl = str(ath.get("classement") or "").strip()
                tot = ath.get("total_categorie")
                badge_style = "font-weight:700;"
                medal = ""
                if cl == "1":
                    medal = "🥇 "
                    badge_style += " color:#B45309; background:#FEF3C7; padding:2px 8px; border-radius:4px;"
                elif cl == "2":
                    medal = "🥈 "
                    badge_style += " color:#475569; background:#F1F5F9; padding:2px 8px; border-radius:4px;"
                elif cl == "3":
                    medal = "🥉 "
                    badge_style += " color:#9A3412; background:#FFEDD5; padding:2px 8px; border-radius:4px;"

                rank_display = f"{medal}{cl}e" if cl else "—"
                if tot and tot > 0 and cl:
                    rank_display += f" / {tot}"

                perf = str(ath.get("performance") or "").strip() or "—"
                cat = str(ath.get("categorie") or "").strip() or "—"
                lic = str(ath.get("num_licence") or "").strip() or "—"
                nom_prenom = f"<b>{ath.get('nom', '').upper()}</b> {ath.get('prenom', '').title()}"

                rows_html.append(f"""
                  <tr style="border-bottom:1px solid #E2E8F0;">
                    <td style="padding:10px 12px; font-size:13.5px; color:#1E293B;">{nom_prenom}</td>
                    <td style="padding:10px 12px; font-size:13px; color:#475569;">{cat}</td>
                    <td style="padding:10px 12px; font-size:13.5px; text-align:center;"><span style="{badge_style}">{rank_display}</span></td>
                    <td style="padding:10px 12px; font-size:12.5px; color:#64748B;">{perf}</td>
                    <td style="padding:10px 12px; font-size:12px; color:#94A3B8; font-family:monospace;">{lic}</td>
                  </tr>
                """)

            table_body = "".join(rows_html) if rows_html else '<tr><td colspan="5" style="padding:20px; text-align:center; color:#94A3B8;">Aucun athlète classé trouvé pour le club.</td></tr>'

            url_btn = f'<a href="{url}" style="display:inline-block; font-size:12px; font-weight:600; color:#2563EB; text-decoration:none; margin-top:6px;" target="_blank">🔗 Voir les résultats officiels sur MyCompet FFME ➔</a>' if url else ''

            comp_sections.append(f"""
              <div style="background:#FFFFFF; border:1px solid #E2E8F0; border-radius:10px; margin-bottom:24px; overflow:hidden; box-shadow:0 1px 3px rgba(15,23,42,0.06);">
                <div style="background:#163A5F; color:#FFFFFF; padding:14px 18px;">
                  <h2 style="margin:0; font-size:17px; font-weight:700;">🧗 {nom_comp}</h2>
                  {f'<div style="font-size:12.5px; color:#93C5FD; margin-top:3px;">{meta_str}</div>' if meta_str else ''}
                </div>
                <div style="padding:16px 18px;">
                  <div style="overflow-x:auto;">
                    <table style="width:100%; border-collapse:collapse; text-align:left;">
                      <thead>
                        <tr style="background:#F8FAFC; border-bottom:2px solid #CBD5E1; font-size:12px; color:#475569; text-transform:uppercase;">
                          <th style="padding:8px 12px;">Athlète</th>
                          <th style="padding:8px 12px;">Catégorie</th>
                          <th style="padding:8px 12px; text-align:center;">Classement</th>
                          <th style="padding:8px 12px;">Performance</th>
                          <th style="padding:8px 12px;">Licence</th>
                        </tr>
                      </thead>
                      <tbody>
                        {table_body}
                      </tbody>
                    </table>
                  </div>
                  <div style="margin-top:12px; text-align:right;">
                    {url_btn}
                  </div>
                </div>
              </div>
            """)

        all_sections_html = "".join(comp_sections)
        nb_comps = len(comp_results_list)
        plural = "s" if nb_comps > 1 else ""

        html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Résultats de Compétition — ALJ Escalade</title>
</head>
<body style="margin:0; padding:20px; font-family:-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color:#F1F5F9; color:#1E293B;">
  <div style="max-width:720px; margin:0 auto;">
    
    <!-- En-tête -->
    <div style="background:linear-gradient(135deg, #163A5F 0%, #1E40AF 100%); color:#FFFFFF; padding:22px 24px; border-radius:12px 12px 0 0; text-align:center;">
      <div style="font-size:12px; font-weight:700; letter-spacing:1px; text-transform:uppercase; color:#93C5FD; margin-bottom:4px;">Amicale Laïque de Jonage · Escalade</div>
      <h1 style="margin:0; font-size:22px; font-weight:800;">🏆 Nouveaux Résultats de Compétition FFME</h1>
      <p style="margin:8px 0 0; font-size:14px; color:#E0E7FF;">Les résultats officiels de {nb_comps} compétition{plural} viennent d'être synchronisés depuis MyCompet.</p>
    </div>

    <!-- Contenu principal -->
    <div style="background:#F8FAFC; padding:24px 20px; border-left:1px solid #E2E8F0; border-right:1px solid #E2E8F0;">
      {all_sections_html}
    </div>

    <!-- Pied de page -->
    <div style="background:#FFFFFF; border:1px solid #E2E8F0; border-top:none; border-radius:0 0 12px 12px; padding:16px 20px; text-align:center; font-size:12px; color:#64748B;">
      <p style="margin:0 0 6px;">
        🤖 <b>Notification automatique</b> envoyée par le batch quotidien ALJ Escalade (07h00).
      </p>
      <p style="margin:0; font-size:11.5px; color:#94A3B8;">
        Ces résultats sont désormais enregistrés dans la base et consultables directement sur la page Compétitions du club.
      </p>
    </div>

  </div>
</body>
</html>
"""
        return html

    @classmethod
    def send_notification_email(cls, comp_results_list: List[Dict[str, Any]], to_email: Optional[str] = None) -> bool:
        """Envoie l'e-mail de synthèse avec les tableaux de résultats."""
        if not comp_results_list:
            return False

        recipient = (to_email or cls.get_notification_email()).strip()
        if not recipient or "@" not in recipient:
            print(f"⚠️ [BATCH_RESULTATS] Adresse de notification invalide : '{recipient}'")
            return False

        nb_comps = len(comp_results_list)
        if nb_comps == 1:
            nom_c = comp_results_list[0].get("nom") or "Compétition"
            subject = f"🏆 Résultats officiels disponibles : {nom_c}"
        else:
            subject = f"🏆 Résultats officiels disponibles pour {nb_comps} compétitions"

        html_body = cls.build_results_email_html(comp_results_list)

        # Corps texte brut en repli
        lines = [
            f"ALJ Escalade - Nouveaux résultats officiels FFME ({nb_comps} compétition(s))",
            "=" * 50,
            ""
        ]
        for c in comp_results_list:
            lines.append(f"Compétition : {c.get('nom')} ({c.get('date', '')})")
            if c.get("url"):
                lines.append(f"MyCompet : {c.get('url')}")
            lines.append("Résultats du club :")
            for ath in (c.get("athletes") or []):
                lines.append(f" - {ath.get('nom')} {ath.get('prenom')} ({ath.get('categorie')}) : {ath.get('resultat_ffme')} [{ath.get('performance')}]")
            lines.append("")

        plain_body = "\n".join(lines)

        try:
            ok = EmailRepository.send_email(
                to_email=recipient,
                subject=subject,
                body=plain_body,
                html_body=html_body,
                from_email="inscription@alj-escalade.fr",
                from_name="ALJ Escalade - Résultats Compétitions"
            )
            if ok:
                print(f"✅ [BATCH_RESULTATS] E-mail de notification envoyé avec succès à {recipient}")
            else:
                print(f"❌ [BATCH_RESULTATS] Échec lors de l'envoi de l'e-mail à {recipient}")
            return ok
        except Exception as e:
            print(f"❌ [BATCH_RESULTATS] Erreur envoi e-mail notification : {e}")
            return False

    @classmethod
    def run_daily_batch(cls, force: bool = False, to_email: Optional[str] = None) -> Dict[str, Any]:
        """
        Exécution principale du batch quotidien.
        1. Sélectionne les compétitions finies sans résultats.
        2. Scrape MyCompet.
        3. Met à jour les résultats des athlètes.
        4. Envoie l'e-mail récapitulatif si des résultats sont découverts.
        """
        now_iso = datetime.datetime.now().isoformat()
        notification_email = (to_email or cls.get_notification_email()).strip()

        print(f"🚀 [BATCH_RESULTATS] Démarrage du batch quotidien ({now_iso}) — Notif: {notification_email}")

        pending = cls.list_pending_competitions(force=force)
        print(f"🔍 [BATCH_RESULTATS] {len(pending)} compétition(s) éligible(s) sans résultats détectée(s).")

        results_found_list = []
        details = []

        for comp in pending:
            cid = str(comp.get("id") or comp.get("doc_id") or "")
            nom = comp.get("nom") or "Compétition"
            print(f"⏳ [BATCH_RESULTATS] Recherche des résultats pour #{cid} « {nom} »...")

            matched_count, athletes, url = cls.sync_results_for_competition(comp)

            if matched_count > 0:
                print(f"🎉 [BATCH_RESULTATS] {matched_count} athlète(s) classé(s) trouvé(s) pour « {nom} » !")
                item = {
                    "id": cid,
                    "nom": nom,
                    "date": comp.get("date_competition") or "",
                    "lieu": comp.get("lieu") or "",
                    "url": url,
                    "athletes": athletes,
                    "status": "found"
                }
                results_found_list.append(item)
                details.append(item)
            else:
                print(f"ℹ️ [BATCH_RESULTATS] Aucun résultat officiel disponible pour le moment pour « {nom} ».")
                details.append({
                    "id": cid,
                    "nom": nom,
                    "date": comp.get("date_competition") or "",
                    "lieu": comp.get("lieu") or "",
                    "url": url,
                    "athletes": [],
                    "status": "pending"
                })

        # Envoi de l'e-mail si des résultats ont été trouvés
        email_sent = False
        if results_found_list:
            print(f"📧 [BATCH_RESULTATS] Envoi de l'e-mail récapitulatif pour {len(results_found_list)} compétition(s)...")
            email_sent = cls.send_notification_email(results_found_list, to_email=notification_email)
        else:
            print("ℹ️ [BATCH_RESULTATS] Aucun nouveau résultat à notifier aujourd'hui.")

        # Enregistrement des statuts d'exécution
        status_msg = f"{len(pending)} vérifiée(s), {len(results_found_list)} résultat(s) trouvé(s)"
        if email_sent:
            status_msg += f" (E-mail envoyé à {notification_email})"
        elif results_found_list:
            status_msg += " (Échec envoi e-mail)"

        try:
            SqliteRepository.set_app_setting(SETTING_BATCH_LAST_RUN, now_iso)
            SqliteRepository.set_app_setting(SETTING_BATCH_LAST_STATUS, status_msg)
        except Exception:
            pass

        return {
            "status": "success",
            "executed_at": now_iso,
            "competitions_checked": len(pending),
            "competitions_updated": len(results_found_list),
            "email_sent": email_sent,
            "notification_email": notification_email,
            "details": details
        }


if __name__ == "__main__":
    # Exécution directe CLI
    import argparse
    parser = argparse.ArgumentParser(description="Batch quotidien de récupération des résultats MyCompet FFME.")
    parser.add_argument("--force", action="store_true", help="Forcer l'analyse même si déjà synchronisée")
    parser.add_argument("--email", type=str, default="", help="Adresse e-mail de notification personnalisée")
    args = parser.parse_args()

    res = CompetitionResultsBatchService.run_daily_batch(force=args.force, to_email=args.email or None)
    print("\n--- RAPPORT DU BATCH ---")
    print(f"Date : {res['executed_at']}")
    print(f"Compétitions analysées : {res['competitions_checked']}")
    print(f"Résultats trouvés : {res['competitions_updated']}")
    print(f"E-mail expédié : {'Oui' if res['email_sent'] else 'Non'}")
