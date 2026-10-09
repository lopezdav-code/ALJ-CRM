"""
Service d'expédition et de rendu d'e-mails sécurisé (contexte Compétitions & Adhérents).

Permet de :
1. Charger les modèles de mails configurés dans le CRM (table email_templates).
2. Résoudre les variables dynamiques ({first_name}, {last_name}, {num_licence},
   {no_competition}, {name_competition}, {montant_competition}, {date_competition}).
3. Générer un aperçu fidèle (texte brut et HTML) pour validation préalable.
4. Expédier les messages via l'API Gmail sécurisée du club (OAuth2) ou SMTP.
"""

from typing import Dict, Any, List, Optional

from domain.utils import apply_template_variables, format_montant
from infrastructure.sqlite_repository import SqliteRepository
from infrastructure.competition_firestore_repository import (
    CompetitionFirestoreRepository as CompetitionRepository,
)
from infrastructure.email_repository import EmailRepository
from email_html import build_email_html, build_signature_plain, get_inline_images


class EmailDispatchService:
    """Service d'orchestration pour l'envoi d'e-mails personnalisés."""

    @classmethod
    def list_templates(cls) -> List[Dict[str, Any]]:
        """Retourne la liste des modèles d'e-mails disponibles en base SQLite."""
        SqliteRepository.setup_database()
        return SqliteRepository.get_email_templates()

    @classmethod
    def get_template_by_name(cls, name: str) -> Optional[Dict[str, Any]]:
        """Recherche un modèle d'e-mail par son nom (insensible à la casse)."""
        name_clean = str(name or "").strip().lower()
        for t in cls.list_templates():
            if str(t.get("name") or "").strip().lower() == name_clean:
                return t
        return None

    @classmethod
    def get_competition_context(cls, competition_id: Optional[int]) -> Dict[str, str]:
        """Extrait les variables de contexte d'une compétition pour injection dans les modèles."""
        if not competition_id:
            return {}
        comp = CompetitionRepository.get_competition(competition_id)
        if not comp:
            return {}

        from domain.utils import format_periode
        date_formatted = format_periode(comp.date_competition, comp.date_fin)

        return {
            "competition_id": str(comp.id),
            "nom": comp.nom,
            "no_competition": str(comp.id_ffme or ""),
            "name_competition": comp.nom,
            "montant_competition": format_montant(comp.prix),
            "date_competition": date_formatted,
        }

    @classmethod
    def resolve_recipients(
        cls,
        recipient_ids: Optional[List[int]] = None,
        recipients_data: Optional[List[Dict[str, Any]]] = None
    ) -> List[Dict[str, Any]]:
        """
        Construit la liste normalisée des destinataires à partir soit :
        - d'une liste d'identifiants (adherent_id / user_id) ;
        - d'une liste de dictionnaires fournis directement.
        """
        resolved: List[Dict[str, Any]] = []

        # 1. Traitement par identifiants
        if recipient_ids:
            # Charger les profils depuis la base adhérents
            all_users = {
                u["id"]: u for u in SqliteRepository.get_connection().execute(
                    "SELECT id, first_name, last_name, email_primary, email_secondary, phone, licence_ffme FROM users"
                ).fetchall()
            }
            # Charger les profils depuis la base compétitions en secours
            comp_adh = {a["id"]: a for a in CompetitionRepository.list_adherents()}

            for uid in recipient_ids:
                u_row = all_users.get(uid)
                if u_row:
                    email_dest = (u_row["email_primary"] or u_row["email_secondary"] or "").strip()
                    resolved.append({
                        "id": uid,
                        "first_name": u_row["first_name"] or "",
                        "last_name": u_row["last_name"] or "",
                        "email": email_dest,
                        "licence_ffme": u_row["licence_ffme"] or "",
                    })
                elif uid in comp_adh:
                    a_info = comp_adh[uid]
                    resolved.append({
                        "id": uid,
                        "first_name": a_info.get("prenom") or "",
                        "last_name": a_info.get("nom") or "",
                        "email": a_info.get("email") or "",
                        "licence_ffme": a_info.get("num_licence") or "",
                    })

        # 2. Destinataires directs
        if recipients_data:
            for r in recipients_data:
                em = str(r.get("email") or "").strip()
                if em and "@" in em:
                    resolved.append({
                        "id": r.get("id"),
                        "first_name": r.get("first_name") or r.get("prenom") or "",
                        "last_name": r.get("last_name") or r.get("nom") or "",
                        "email": em,
                        "licence_ffme": r.get("licence_ffme") or r.get("num_licence") or "",
                    })

        return resolved

    @classmethod
    def preview(
        cls,
        template_name: Optional[str] = None,
        subject: Optional[str] = None,
        body: Optional[str] = None,
        recipient: Optional[Dict[str, Any]] = None,
        competition_id: Optional[int] = None,
        add_signature: bool = True
    ) -> Dict[str, str]:
        """Génère l'aperçu du sujet et du corps (texte brut + HTML) avec les variables résolues."""
        subj_tmpl = subject or ""
        body_tmpl = body or ""
        sender_email = None
        sender_name = None

        if template_name:
            t = cls.get_template_by_name(template_name)
            if t:
                subj_tmpl = subj_tmpl or t.get("subject") or ""
                body_tmpl = body_tmpl or t.get("body") or ""
                sender_email = t.get("sender_email")
                sender_name = t.get("sender_name")

        # Contexte
        comp_ctx = cls.get_competition_context(competition_id)
        dummy_recipient = recipient or {
            "first_name": "Jean",
            "last_name": "DUPONT",
            "email": "jean.dupont@example.com",
            "licence_ffme": "123456"
        }

        subj_rendered = apply_template_variables(subj_tmpl, dummy_recipient, comp_ctx)
        body_rendered = apply_template_variables(body_tmpl, dummy_recipient, comp_ctx)

        plain_text = body_rendered
        if add_signature:
            plain_text = body_rendered + "\n\n" + build_signature_plain()

        html_text = build_email_html(body_rendered, add_signature=add_signature, image_src_mode="cid")

        return {
            "subject": subj_rendered,
            "body_plain": plain_text,
            "body_html": html_text,
            "sender_email": sender_email or "",
            "sender_name": sender_name or ""
        }

    @classmethod
    def dispatch_emails(
        cls,
        template_name: Optional[str] = None,
        subject: Optional[str] = None,
        body: Optional[str] = None,
        recipient_ids: Optional[List[int]] = None,
        recipients: Optional[List[Dict[str, Any]]] = None,
        competition_id: Optional[int] = None,
        sender_email: Optional[str] = None,
        sender_name: Optional[str] = None,
        add_signature: bool = True
    ) -> Dict[str, Any]:
        """
        Envoie les e-mails aux destinataires ciblés avec injection des variables.
        """
        subj_tmpl = subject or ""
        body_tmpl = body or ""
        default_from_email = sender_email
        default_from_name = sender_name

        if template_name:
            t = cls.get_template_by_name(template_name)
            if t:
                subj_tmpl = subj_tmpl or t.get("subject") or ""
                body_tmpl = body_tmpl or t.get("body") or ""
                if not default_from_email:
                    default_from_email = t.get("sender_email")
                if not default_from_name:
                    default_from_name = t.get("sender_name")

        if not subj_tmpl or not body_tmpl:
            return {
                "status": "error",
                "message": "Le sujet et le corps de l'e-mail ne peuvent pas être vides.",
                "sent_count": 0,
                "errors_count": 0,
                "details": []
            }

        destinataires = cls.resolve_recipients(recipient_ids=recipient_ids, recipients_data=recipients)
        if not destinataires:
            return {
                "status": "error",
                "message": "Aucun destinataire avec une adresse e-mail valide n'a été trouvé.",
                "sent_count": 0,
                "errors_count": 0,
                "details": []
            }

        comp_ctx = cls.get_competition_context(competition_id)

        sent_count = 0
        errors_count = 0
        details = []

        for dest in destinataires:
            to_email = dest.get("email")
            full_name = f"{dest.get('first_name', '')} {dest.get('last_name', '')}".strip()

            if not to_email or "@" not in to_email:
                errors_count += 1
                details.append({
                    "id": dest.get("id"),
                    "name": full_name,
                    "email": to_email,
                    "status": "error",
                    "error": "Adresse e-mail invalide ou absente"
                })
                continue

            # Personnalisation
            sub_rendered = apply_template_variables(subj_tmpl, dest, comp_ctx)
            body_rendered = apply_template_variables(body_tmpl, dest, comp_ctx)

            plain_body = body_rendered
            inline_imgs = None
            if add_signature:
                plain_body = body_rendered + "\n\n" + build_signature_plain()
                inline_imgs = get_inline_images()

            html_body = build_email_html(body_rendered, add_signature=add_signature, image_src_mode="cid")

            try:
                ok = EmailRepository.send_email(
                    to_email=to_email,
                    subject=sub_rendered,
                    body=plain_body,
                    html_body=html_body,
                    inline_images=inline_imgs,
                    from_email=default_from_email,
                    from_name=default_from_name
                )
                if ok:
                    sent_count += 1
                    details.append({
                        "id": dest.get("id"),
                        "name": full_name,
                        "email": to_email,
                        "status": "sent"
                    })
                else:
                    errors_count += 1
                    details.append({
                        "id": dest.get("id"),
                        "name": full_name,
                        "email": to_email,
                        "status": "error",
                        "error": "Échec d'envoi EmailRepository"
                    })
            except Exception as ex:
                errors_count += 1
                details.append({
                    "id": dest.get("id"),
                    "name": full_name,
                    "email": to_email,
                    "status": "error",
                    "error": str(ex)
                })

        first_err = details[0]["error"] if details and "error" in details[0] else "Erreur d'envoi."
        return {
            "status": "success" if errors_count == 0 else ("partial" if sent_count > 0 else "error"),
            "sent_count": sent_count,
            "errors_count": errors_count,
            "total_recipients": len(destinataires),
            "message": "" if errors_count == 0 else first_err,
            "details": details
        }
