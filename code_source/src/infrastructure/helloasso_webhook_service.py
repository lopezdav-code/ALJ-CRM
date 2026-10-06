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
"""

import re
import json
import datetime
from typing import Dict, Any, List, Optional

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
from infrastructure.competition_repository import CompetitionRepository


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

    @classmethod
    def process_webhook(cls, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Traite une notification Webhook HelloAsso complète :
        - Extrait les articles.
        - Tente le rapprochement avec la compétition et le participant.
        - Met à jour le statut du participant en base si le match est établi.
        - Enregistre l'article dans le miroir HelloAsso pour l'audit.
        """
        CompetitionRepository.setup_database()
        event_type, raw_items = cls.extract_items_from_payload(payload)

        if not raw_items:
            return {
                "status": "ignored",
                "message": "Aucun article (item) exploitable dans ce payload.",
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


# Type helper pour tuple
Tuple_Items = tuple[str, List[Dict[str, Any]]]
