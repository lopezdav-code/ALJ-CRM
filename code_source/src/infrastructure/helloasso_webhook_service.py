"""
Service de réception et traitement des Webhooks HelloAsso (Paiements et Commandes).

Permet de :
1. Parser les notifications transmises par HelloAsso (événement Payment ou Order).
2. Extraire les articles vendus (items), leurs montants et champs personnalisés
   (licence FFME, numéro d'épreuve / compétition concernée).
3. Rapprocher automatiquement chaque article avec une compétition et un participant
   (via `domain.competition_matching`).
4. Mettre à jour immédiatement la base de données (marquage « payé », montant réglé,
   sauvegarde de l'article dans le miroir HelloAsso).

Sécurité (le contenu d'une notification n'est jamais cru sur parole) :
- Jeton secret : si HELLOASSO_WEBHOOK_TOKEN est défini, l'URL déclarée chez
  HelloAsso doit être « /webhooks/helloasso?token=<secret> » ; toute requête
  sans le bon jeton est refusée (401).
- Re-vérification : si les identifiants API HelloAsso sont disponibles, seuls les
  identifiants d'articles sont lus dans la notification ; montant, état, payeur et
  champs personnalisés sont relus depuis l'API HelloAsso officielle.
- En production (contrôle d'accès actif), une notification n'est traitée que si
  l'une au moins de ces deux vérifications est possible (fail-closed).
"""

import re
import json
import datetime
from typing import Dict, Any, List, Optional

import helloasso_api
from infrastructure.api_auth import auth_enforced, constant_time_equals
from infrastructure.secret_store import SecretStore

from domain.utils import normalize_name, normalize_string
from domain.competition_matching import (
    extract_licence,
    extract_competition_number,
    _item_amount,
    _item_payer_name,
    _item_state,
    STATUTS_PAYES,
    auto_link_items,
    summarize_items,
)
from infrastructure.competition_firestore_repository import (
    CompetitionFirestoreRepository as CompetitionRepository,
)

# Type helper pour tuple (défini AVANT la classe : les annotations sont évaluées
# à l'import en Python <= 3.13, une définition en fin de fichier lèverait NameError)
Tuple_Items = tuple[str, List[Dict[str, Any]]]

# Nombre maximal d'articles relus par notification (garde-fou anti-abus)
MAX_VERIFIED_ITEMS = 50


class WebhookRejected(Exception):
    """Notification refusée (code HTTP à renvoyer + message)."""

    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


class HelloAssoWebhookService:
    """Service de gestion des webhooks HelloAsso."""

    @classmethod
    def extract_items_from_payload(cls, payload: Dict[str, Any]) -> Tuple_Items:
        """
        Extrait les articles normalisés à partir de tout type de payload HelloAsso
        (événement 'Payment', 'Order', 'Form', ou liste brute d'articles).
        """
        event_type = payload.get("eventType") or "Unknown"
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload

        items = []

        # 1. Si le payload contient directement une liste d'items
        if isinstance(data.get("items"), list) and data.get("items"):
            items = data.get("items")
        # 2. Si le payload est lui-même un item individuel (contient un id et un montant)
        elif data.get("id") and (data.get("amount") is not None or data.get("price") is not None):
            items = [data]
        # 3. Événement 'Payment' contenant des paiements mais pas directement de liste items
        elif event_type == "Payment" or data.get("paymentMeans"):
            payer = data.get("payer") or {}
            user = {
                "firstName": payer.get("firstName") or data.get("payer_firstName") or "",
                "lastName": payer.get("lastName") or data.get("payer_lastName") or ""
            }
            order = data.get("order") or {}
            custom_fields = data.get("customFields") or []

            items = [{
                "id": data.get("id"),
                "amount": data.get("amount") or 0,
                "state": data.get("state") or "Processed",
                "date": data.get("date") or datetime.datetime.now().isoformat(),
                "user": user,
                "order": order,
                "customFields": custom_fields
            }]

        return event_type, items

    # ------------------------------------------------------------------
    # Vérification de l'authenticité
    # ------------------------------------------------------------------
    @classmethod
    def check_token(cls, token: Optional[str]) -> Optional[bool]:
        """True/False si un jeton secret est configuré (correct ou non), None sinon."""
        expected = (SecretStore.get_secret("HELLOASSO_WEBHOOK_TOKEN") or "").strip()
        if not expected:
            return None
        return bool(token) and constant_time_equals(token.strip(), expected)

    @staticmethod
    def _ids(objs) -> List[int]:
        ids = []
        for o in objs or []:
            raw = o.get("id") if isinstance(o, dict) else None
            try:
                ids.append(int(raw))
            except (TypeError, ValueError):
                continue
        return ids

    @classmethod
    def fetch_verified_items(cls, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Relit depuis l'API HelloAsso les articles visés par la notification.

        Seuls les identifiants (articles, commande, paiement) sont pris dans le
        payload ; un identifiant inconnu de HelloAsso est simplement ignoré.
        """
        event_type = payload.get("eventType") or ""
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        try:
            item_ids = cls._ids(data.get("items"))
            if not item_ids and data.get("id") is not None:
                order_id = None
                if event_type == "Payment":
                    payment = helloasso_api.get_payment(data.get("id")) or {}
                    item_ids = cls._ids(payment.get("items"))
                    order_id = (payment.get("order") or {}).get("id")
                elif event_type == "Order":
                    order_id = data.get("id")
                if not item_ids and order_id is not None:
                    order = helloasso_api.get_order(order_id) or {}
                    item_ids = cls._ids(order.get("items"))

            items = []
            for item_id in list(dict.fromkeys(item_ids))[:MAX_VERIFIED_ITEMS]:
                item = helloasso_api.get_item(item_id)
                if item and item.get("id") is not None:
                    items.append(item)
                else:
                    print(f"⚠️ [WEBHOOK_HELLOASSO] Article #{item_id} inconnu de l'API HelloAsso : ignoré")
            return items
        except helloasso_api.HelloAssoApiError as e:
            # 503 : HelloAsso renverra la notification plus tard
            raise WebhookRejected(503, f"Vérification auprès de HelloAsso impossible : {e}")

    @classmethod
    def handle_notification(cls, payload: Dict[str, Any], token: Optional[str] = None) -> Dict[str, Any]:
        """Point d'entrée sécurisé du webhook (lève WebhookRejected en cas de refus)."""
        token_ok = cls.check_token(token)
        if token_ok is False:
            raise WebhookRejected(401, "Jeton de notification HelloAsso absent ou invalide")

        if helloasso_api.credentials_configured():
            items = cls.fetch_verified_items(payload)
            report = cls.process_webhook(payload, items=items)
            report["verified"] = "api"
            return report

        if token_ok or not auth_enforced():
            report = cls.process_webhook(payload)
            report["verified"] = "token" if token_ok else "none"
            return report

        raise WebhookRejected(
            503,
            "Notification non vérifiable : configurez HELLOASSO_WEBHOOK_TOKEN "
            "ou les identifiants API HelloAsso sur le serveur.",
        )

    @staticmethod
    def item_form_slug(raw: Dict[str, Any]) -> str:
        return str((raw.get("order") or {}).get("formSlug") or raw.get("formSlug") or "").strip()

    @classmethod
    def competition_form_slug(cls) -> str:
        """Slug du formulaire HelloAsso des compétitions (réglage HELLOASSO_ANNUAL_CAMPAIGN)."""
        try:
            from domain.competition_matching import parse_campaign_identifier
            ref = CompetitionRepository.get_app_setting("HELLOASSO_ANNUAL_CAMPAIGN")
            if not isinstance(ref, str) or not ref.strip():
                return ""
            return parse_campaign_identifier(ref)["slug"]
        except Exception as e:
            print(f"⚠️ [WEBHOOK_HELLOASSO] Formulaire de compétition introuvable : {e}")
            return ""

    @classmethod
    def filter_competition_form(cls, raw_items: List[Dict[str, Any]]):
        """Sépare les articles du formulaire de compétition des autres.

        Retourne (articles_retenus, slugs_des_articles_écartés). Sans réglage, ou
        pour un article dont le formulaire est inconnu, rien n'est écarté.
        """
        expected = cls.competition_form_slug().lower()
        if not expected:
            return list(raw_items), []
        kept, others = [], []
        for raw in raw_items:
            slug = cls.item_form_slug(raw)
            if slug and slug.lower() != expected:
                others.append(slug)
            else:
                kept.append(raw)
        return kept, others

    # ------------------------------------------------------------------
    # Traitement
    # ------------------------------------------------------------------
    @classmethod
    def process_webhook(cls, payload: Dict[str, Any],
                        items: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """
        Traite une notification Webhook HelloAsso complète :
        - Extrait les articles.
        - Tente le rapprochement avec la compétition et le participant.
        - Met à jour le statut du participant en base si le match est établi.
        - Enregistre l'article dans le miroir HelloAsso pour l'audit.

        items : articles déjà vérifiés auprès de l'API HelloAsso (prioritaires sur
        le contenu du payload, qui ne sert alors qu'à connaître le type d'événement).
        """
        CompetitionRepository.setup_database()
        if items is None:
            event_type, raw_items = cls.extract_items_from_payload(payload)
        else:
            event_type, raw_items = (payload.get("eventType") or "Unknown"), list(items)

        # Seuls les articles du formulaire « compétitions » configuré sont traités :
        # les autres ventes HelloAsso de l'association (boutique, adhésions…) ne
        # doivent pas polluer le miroir des paiements de compétition.
        raw_items, other_forms = cls.filter_competition_form(raw_items)
        if other_forms:
            print(f"ℹ️ [WEBHOOK_HELLOASSO] {len(other_forms)} article(s) d'un autre formulaire ignoré(s) : "
                  + ", ".join(sorted({s or '?' for s in other_forms})))

        if not raw_items:
            return {
                "status": "ignored",
                "message": ("Articles hors formulaire de compétition : ignorés."
                            if other_forms else "Aucun article (item) exploitable dans ce payload."),
                "other_forms": sorted({s or "?" for s in other_forms}),
                "event_type": event_type,
                "processed_count": 0,
                "matches": [],
                "anomalies": []
            }

        # 1. Projeter les articles pour le moteur de matching
        summarized = summarize_items(raw_items)

        # 2. Récupérer l'état actuel des compétitions, adhérents et liens existants
        competitions = [c.to_dict() for c in CompetitionRepository.list_competitions()]
        adherents = CompetitionRepository.list_adherents()
        existing_links = CompetitionRepository.list_helloasso_links()

        # 3. Exécuter le matching automatique
        computed_links = auto_link_items(
            items=summarized,
            competitions=competitions,
            adherents=adherents,
            existing_links=existing_links
        )

        matches = []
        anomalies = []
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 4. Traitement et application en base de données pour chaque article
        for raw, sm in zip(raw_items, summarized, strict=False):
            id_item = sm.get("id_item")
            order_ref = sm.get("commande") or str((raw.get("order") or {}).get("id") or "")
            montant = float(sm.get("montant") or 0.0)
            date_item = sm.get("date_item") or now_str
            payer_name = sm.get("payeur") or ""
            licence = sm.get("licence") or ""
            comp_field = sm.get("competition") or ""
            etat = sm.get("etat") or ""

            # Sauvegarder l'article dans la table miroir helloasso_items
            nom_p, _, prenom_p = payer_name.partition(" ")
            campagne_slug = str((raw.get("order") or {}).get("formSlug") or raw.get("formSlug") or "")

            try:
                CompetitionRepository.sync_helloasso_mirror(
                    summarized=[sm],
                    raw_items=[raw],
                    campagne_slug=campagne_slug
                )
            except Exception as save_err:
                print(f"⚠️ [WEBHOOK_HELLOASSO] Erreur sauvegarde miroir item #{id_item} : {save_err}")

            # Vérifier si un lien automatique a été déterminé
            link_info = computed_links.get(id_item)
            if link_info and link_info.get("competition_id"):
                cid = link_info["competition_id"]
                aid = link_info.get("adherent_id")

                if aid:
                    # Enregistrer le lien dans item_links
                    CompetitionRepository.set_item_link(
                        id_item=id_item,
                        competition_id=cid,
                        adherent_id=aid,
                        source="webhook"
                    )

                    # Enregistrer le paiement dans la table participants
                    updated = CompetitionRepository.apply_helloasso_payment(
                        competition_id=cid,
                        adherent_id=aid,
                        montant_paye=montant,
                        order_ref=order_ref,
                        date_synchro=date_item
                    )

                    # Si le participant n'était pas encore enregistré pour cette compétition,
                    # l'ajouter comme participant sélectionné et payé
                    if not updated:
                        CompetitionRepository.add_participant(
                            competition_id=cid,
                            adherent_id=aid,
                            selectionne=True
                        )
                        CompetitionRepository.apply_helloasso_payment(
                            competition_id=cid,
                            adherent_id=aid,
                            montant_paye=montant,
                            order_ref=order_ref,
                            date_synchro=date_item
                        )

                    matches.append({
                        "id_item": id_item,
                        "competition_id": cid,
                        "adherent_id": aid,
                        "payer": payer_name,
                        "montant": montant,
                        "order_ref": order_ref,
                        "licence": licence,
                        "status": "paye"
                    })
                else:
                    # Compétition reconnue mais adhérent inconnu
                    anomalies.append({
                        "id_item": id_item,
                        "payer": payer_name,
                        "montant": montant,
                        "competition_id": cid,
                        "licence_saisie": licence,
                        "reason": "Compétition reconnue mais aucun adhérent trouvé par licence ou nom"
                    })
            else:
                # Épreuve non identifiée
                anomalies.append({
                    "id_item": id_item,
                    "payer": payer_name,
                    "montant": montant,
                    "licence_saisie": licence,
                    "competition_saisie": comp_field,
                    "reason": "Numéro ou nom de compétition non reconnu sur le formulaire HelloAsso"
                })

        return {
            "status": "success",
            "event_type": event_type,
            "processed_count": len(raw_items),
            "matched_count": len(matches),
            "anomalies_count": len(anomalies),
            "matches": matches,
            "anomalies": anomalies,
            "timestamp": now_str
        }
