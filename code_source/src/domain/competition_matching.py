"""
Rapprochement HelloAsso <-> participants d'une compétition (logique pure, testable).

Entrées : items bruts de l'API HelloAsso v5 (helloasso_api.get_items) et les
participants d'une compétition (CompetitionRepository.list_participants).
Sorties : mises à jour de statut de paiement + rapport d'anomalies.

Croisement par ordre de priorité :
1. Numéro de licence FFME (champ personnalisé du formulaire HelloAsso) ;
2. Nom + prénom normalisés (accents/tirets/majuscules neutralisés).

Contrôle additionnel : le champ personnalisé « Compétition concernée » du formulaire
HelloAsso doit contenir le n° d'épreuve attendu (id_ffme communiqué dans l'invitation).
Un paiement sans ce n° (champ vide ou non conforme) n'est PAS marqué « Payé »
automatiquement : il est retourné dans `manual_review` pour correction manuelle.
"""
import re

from domain.utils import normalize_name, normalize_string

# États HelloAsso consideres comme un paiement valide
STATUTS_PAYES = {"processed", "validated", "registered"}

# Motifs reconnus pour extraire le type de formulaire depuis une URL HelloAsso
_URL_TYPE_MAP = {
    "evenements": "Event",
    "formulaires": None,      # type explicite dans le segment suivant
    "adhesions": "Membership",
    "campagnes": "Campaign",
    "dons": "Donation",
    "boutiques": "Shop",
    "crowdfundings": "Crowdfunding",
}


def parse_campaign_identifier(ref: str) -> dict:
    """Analyse l'identifiant / l'URL de campagne saisi par l'utilisateur.

    Accepte :
    - une URL complète (https://www.helloasso.com/associations/{org}/evenements/{slug}
      ou .../formulaires/{FormType}/{slug}) ;
    - un couple explicite « FormType:slug » (ex : « Event:competition-u11 ») ;
    - un slug brut (type « Event » par défaut : les compétitions sont des événements).

    Retourne {"form_type": str, "slug": str} ou lève ValueError si non exploitable.
    """
    raw = str(ref or "").strip()
    if not raw:
        raise ValueError("Aucun identifiant de campagne HelloAsso fourni.")

    if "helloasso.com" in raw.lower():
        path = re.split(r"associations/[^/]+/+", raw, maxsplit=1, flags=re.IGNORECASE)
        segments = [s.strip("/ ") for s in path[-1].split("/")]
        segments = [s for s in segments if s]
        if len(segments) >= 2:
            head = segments[0].lower()
            if head == "formulaires" and len(segments) >= 3:
                return {"form_type": segments[1].strip(), "slug": segments[2].strip()}
            if head in _URL_TYPE_MAP and _URL_TYPE_MAP[head]:
                return {"form_type": _URL_TYPE_MAP[head], "slug": segments[1].strip()}
        raise ValueError(f"URL HelloAsso non reconnue : {raw}")

    if ":" in raw:
        ftype, _, slug = raw.partition(":")
        ftype, slug = ftype.strip(), slug.strip()
        if ftype and slug:
            return {"form_type": ftype, "slug": slug}

    return {"form_type": "Event", "slug": raw}


def extract_licence(item: dict) -> str:
    """Extrait le numéro de licence FFME des champs personnalisés de l'item.

    Comme partout dans le projet, la réponse peut résider dans `answer` ou `value`.
    """
    for field in item.get("customFields") or []:
        name = str(field.get("name") or "")
        if "licence" in name.lower():
            val = field.get("answer", field.get("value") or "")
            digits = re.sub(r"\D", "", str(val or ""))
            if digits:
                return digits
    return ""


def extract_competition_number(item: dict, fallback: bool = True) -> str:
    """Extrait la valeur du champ personnalisé « Numéro de la compétition » de l'item.

    Ce champ est saisi par l'adhérent sur le formulaire HelloAsso (n° d'épreuve
    communiqué dans l'e-mail d'invitation via la variable {no_competition}).
    Comme partout dans le projet, la réponse peut résider dans `answer` ou `value`.

    - fallback=True (défaut) : si le champ n° est absent/vide, repli sur la valeur
      de « Compétition concernée » (utile pour le rattachement) ;
    - fallback=False : retourne uniquement la valeur du champ n° (affichage fidèle
      à HelloAsso : rien n'est affiché si l'adhérent n'a rien saisi).
    """
    # 1. On cherche d'abord le champ d'identifiant / numéro précis (ex: "Numéro de la compétition")
    for field in item.get("customFields") or []:
        name = normalize_string(field.get("name") or "")
        if "numero" in name and "competition" in name:
            val = field.get("answer") or field.get("value") or ""
            txt = str(val).strip()
            if txt:
                return txt

    # 2. Repli sur le champ historique "Compétition concernée"
    if not fallback:
        return ""
    for field in item.get("customFields") or []:
        name = normalize_string(field.get("name") or "")
        if "competition" in name and "concerne" in name:
            val = field.get("answer") or field.get("value") or ""
            txt = str(val).strip()
            if txt:
                return txt
    return ""


def extract_competition_name(item: dict) -> str:
    """Extrait la valeur du champ personnalisé « Compétition concernée » de l'item.

    Champ texte libre où l'adhérent décrit la compétition visée (ex : « Coupe
    régionale de bloc Ambérieu »). Comme partout dans le projet, la réponse peut
    résider dans `answer` ou `value`.
    """
    for field in item.get("customFields") or []:
        name = normalize_string(field.get("name") or "")
        if "competition" in name and "concerne" in name:
            val = field.get("answer") or field.get("value") or ""
            txt = str(val).strip()
            if txt:
                return txt
    return ""


def competition_number_ok(valeur_champ: str, no_competition: str) -> bool:
    """Vrai si le contrôle du n° d'épreuve est satisfait (ou désactivé).

    - no_competition vide : contrôle désactivé (n° d'épreuve non renseigné en base) ;
    - sinon le n° attendu doit apparaître dans la valeur saisie par l'adhérent
      (comparaison normalisée : minuscules, sans accents, espaces neutralisés).
    """
    expected = normalize_string(no_competition)
    if not expected:
        return True
    return expected in normalize_string(valeur_champ)


def summarize_items(items: list) -> list:
    """Projection tabulaire des articles HelloAsso pour affichage / miroir local.

    Les n° de licence et de compétition restent **à vide** lorsque l'adhérent ne
    les a pas saisis sur le formulaire (consigne métiier : ne rien inventer).
    """
    rows = []
    for item in items or []:
        rows.append({
            "id_item": item.get("id"),
            "payeur": _item_payer_name(item),
            "montant": _item_amount(item),
            "commande": str((item.get("order") or {}).get("id") or ""),
            "licence": extract_licence(item),
            "competition": extract_competition_number(item),
            "etat": str(item.get("state") or ""),
            "date_item": str(item.get("date") or ""),
        })
    return rows


def match_adherent_by_name(payer: str, adherents: list):
    """Retrouve un adhérent par nom + prénom (normalisés ; ordre des mots inversé accepté).

    - payer : « NOM Prénom » tel que saisi par le payeur sur HelloAsso ;
    - adherents : [{id, nom, prenom}] (instantané local).
    Retourne l'id de l'adhérent ou None si aucun rapprochement exact.
    """
    key = normalize_name(payer)
    if not key:
        return None
    keys = {key}
    parts = key.split()
    if len(parts) == 2:
        keys.add(" ".join(reversed(parts)))
    for a in adherents or []:
        full = normalize_name(f"{a.get('nom')} {a.get('prenom')}")
        if full in keys:
            return a.get("id")
    return None


def auto_link_items(items: list, competitions: list, adherents: list,
                    existing_links: dict = None) -> dict:
    """Calcule les liens automatiques article → (compétition, adhérent).

    - items : projection du miroir (summarize_items) ;
    - competitions : [{id, id_ffme, nom}] ;
    - adherents : [{id, num_licence, nom, prenom}] (instantané local) ;
    - existing_links : {id_item: source} — les liens 'manuel' sont préservés.

    La compétition provient du champ « Compétition concernée » (n° d'épreuve saisi) :
    sans champ exploitable, l'article n'est PAS lié automatiquement (il reste
    « à rattacher » manuellement). L'adhérent est déduit par n° de licence puis
    par nom normalisé (peut rester NULL si inconnu).
    Retourne {id_item: {"competition_id": int, "adherent_id": int|None, "source": "auto"}}.
    """
    existing_links = existing_links or {}
    by_licence = {}
    for a in adherents or []:
        lic = re.sub(r"\D", "", str(a.get("num_licence") or ""))
        if lic:
            by_licence.setdefault(lic, a)

    # Correspondance champ saisi -> compétition : égalité exacte d'abord, puis
    # « contient » (du n° le plus long au plus court pour privilégier la précision).
    comps_exact, comps_contains = {}, []
    for c in competitions or []:
        ref = normalize_string(c.get("id_ffme") or "")
        if not ref:
            continue
        comps_exact.setdefault(ref, c)
        comps_contains.append((ref, c))
    comps_contains.sort(key=lambda rc: len(rc[0]), reverse=True)

    links = {}
    for it in items or []:
        id_item = it.get("id_item")
        if id_item is None:
            continue
        if existing_links.get(id_item) == "manuel":
            continue
        if normalize_string(it.get("etat") or "") not in STATUTS_PAYES:
            continue

        saisie = normalize_string(it.get("competition") or "")
        comp = comps_exact.get(saisie) if saisie else None
        if comp is None and saisie:
            for ref, c in comps_contains:
                if ref in saisie:
                    comp = c
                    break
        if comp is None:
            continue  # compétition inconnue : rattachement manuel requis

        adherent = None
        lic = re.sub(r"\D", "", str(it.get("licence") or ""))
        if lic:
            adherent = by_licence.get(lic)
        if adherent is None:
            payer_id = match_adherent_by_name(it.get("payeur") or "", adherents or [])
            adherent = next((a for a in (adherents or [])
                             if a.get("id") == payer_id), None)

        links[id_item] = {
            "competition_id": comp.get("id"),
            "adherent_id": adherent.get("id") if adherent else None,
            "source": "auto",
        }
    return links


def _item_state(item: dict) -> str:
    return str(item.get("state") or "").strip().lower()


def _item_amount(item: dict) -> float:
    try:
        return round(float(item.get("amount") or 0) / 100.0, 2)
    except (TypeError, ValueError):
        return 0.0


def _item_payer_name(item: dict) -> str:
    user = item.get("user") or {}
    first = str(user.get("firstName") or "").strip()
    last = str(user.get("lastName") or "").strip()
    return f"{last} {first}".strip()


def match_items_to_participants(items: list, participants: list, prix_attendu: float = None,
                                no_competition: str = "") -> dict:
    """Croise les articles HelloAsso avec les participants de la compétition.

    - items : liste brute API (chaque item = un article vendu) ;
    - participants : dicts {adherent_id, nom, prenom, num_licence, statut_paiement, montant_paye} ;
    - prix_attendu : tarif d'inscription de la compétition (détection d'écart) ;
    - no_competition : n° d'épreuve attendu dans le champ « Compétition concernée » du
      formulaire HelloAsso (id_ffme de la compétition). Contrôle désactivé si vide.

    Retourne {
      "updates":          [(adherent_id, montant_paye), ...]        # à marquer « paye »
      "order_by_adherent": {adherent_id: "n° commande (, n°…)"}     # pour affichage
      "manual_review":    [{payer, montant, order_ref, licence, valeur_champ,
                             adherent_id, participant}, ...]         # correction manuelle proposée
      "anomalies":        [{"type", "severite", "titre", "detail"}] # rapport d'écarts
      "stats":            {nb_items, nb_payes, nb_matchs, nb_en_attente, nb_anomalies,
                           nb_manual_review}
    }
    """
    updates = []
    order_by_adherent = {}
    manual_review = []
    anomalies = []

    def anomaly(kind: str, severite: str, titre: str, detail: str):
        anomalies.append({"type": kind, "severite": severite, "titre": titre, "detail": detail})

    # Index des participants par licence puis par nom normalisé
    by_licence, by_name = {}, {}
    for p in participants:
        lic = re.sub(r"\D", "", str(p.get("num_licence") or ""))
        if lic:
            by_licence.setdefault(lic, p)
        key = normalize_name(f"{p.get('nom')} {p.get('prenom')}")
        if key:
            by_name.setdefault(key, p)

    seen_participants = {}
    nb_payes = 0

    for item in items or []:
        state = _item_state(item)
        if state in ("canceled", "cancelled"):
            continue
        amount = _item_amount(item)
        licence = extract_licence(item)
        payer = _item_payer_name(item)
        order_ref = str((item.get("order") or {}).get("id") or "")

        if state == "refunded":
            anomaly("remboursement", "info", "Paiement remboursé",
                    f"{payer or 'Inconnu'} ({amount:.2f} €, commande {order_ref}) est remboursé sur HelloAsso.")
            continue
        if state not in STATUTS_PAYES:
            anomaly("paiement_non_finalise", "info", "Paiement non finalisé",
                    f"{payer or 'Inconnu'} ({amount:.2f} €, commande {order_ref}) : statut HelloAsso « {state or 'inconnu'} ».")
            continue

        nb_payes += 1

        # Contrôle du n° d'épreuve (champ « Compétition concernée » du formulaire) :
        # absent ou non conforme -> PAS de passage automatique à « Payé », le paiement
        # part en correction manuelle (avec la valeur saisie sur HelloAsso en aide).
        valeur_champ = extract_competition_number(item)
        if not competition_number_ok(valeur_champ, no_competition):
            participant = None
            if licence:
                participant = by_licence.get(licence) or by_name.get(normalize_name(payer))
            else:
                participant = by_name.get(normalize_name(payer))
            if valeur_champ:
                anomaly("competition_ecartee", "avertissement", "N° de compétition non conforme",
                        f"{payer or 'Inconnu'} (commande {order_ref}) : le champ « Compétition concernée » "
                        f"indique « {valeur_champ} » au lieu du n° attendu « {no_competition} » ; "
                        f"validation manuelle requise.")
            else:
                anomaly("competition_manquante", "avertissement", "N° de compétition absent sur HelloAsso",
                        f"{payer or 'Inconnu'} (commande {order_ref}) : le champ « Compétition concernée » "
                        f"n'est pas renseigné sur HelloAsso ; validation manuelle requise.")
            manual_review.append({
                "payer": payer or "Inconnu",
                "montant": amount,
                "order_ref": order_ref,
                "licence": licence,
                "valeur_champ": valeur_champ,
                "adherent_id": participant.get("adherent_id") if participant else None,
                "participant": f"{participant.get('nom')} {participant.get('prenom')}" if participant else "",
            })
            continue

        participant = None
        if licence:
            participant = by_licence.get(licence)
            if participant is None:
                # Licence renseignée mais inconnue : tenter un rapprochement par nom en secours
                key = normalize_name(payer)
                participant = by_name.get(key)
                if participant:
                    anomaly("licence_ecartee", "avertissement", "Licence non reconnue",
                            f"{payer} (commande {order_ref}) : le n° de licence « {licence} » ne correspond "
                            f"à aucun participant ; rapproché par le nom (licence attendue : "
                            f"{participant.get('num_licence') or 'absente'}).")
        else:
            key = normalize_name(payer)
            participant = by_name.get(key)
            if participant:
                anomaly("paiement_sans_licence", "avertissement", "Paiement sans n° de licence",
                        f"{payer} (commande {order_ref}) : aucun champ « licence » valide sur HelloAsso ; "
                        f"rapproché par le nom (licence attendue : {participant.get('num_licence') or 'absente'}).")

        if participant is None:
            anomaly("paiement_inconnu", "erreur", "Paiement non identifié",
                    f"Paiement reçu ({amount:.2f} €, commande {order_ref}) pour « {payer or 'inconnu'} » "
                    f"{'(licence ' + licence + ') ' if licence else ''}sans participant correspondant "
                    f"({normalize_name(payer) or 'sans nom'}).")
            continue

        adherent_id = participant.get("adherent_id")
        nom_complet = f"{participant.get('nom')} {participant.get('prenom')}"
        previous = seen_participants.get(adherent_id)
        if previous is not None:
            anomaly("doublon", "erreur", "Plusieurs paiements",
                    f"{nom_complet} : plusieurs paiements détectés (commandes {previous} et {order_ref}). "
                    f"Vérifier sur HelloAsso (remboursement / double inscription ?).")
            seen_participants[adherent_id] = f"{previous}, {order_ref}"
            order_by_adherent[adherent_id] = seen_participants[adherent_id]
            updates.append((adherent_id, amount))
            continue
        seen_participants[adherent_id] = order_ref

        if prix_attendu is not None and prix_attendu > 0 and abs(amount - float(prix_attendu)) > 0.01:
            anomaly("ecart_tarif", "avertissement", "Écart de tarif",
                    f"{nom_complet} : {amount:.2f} € payés contre {float(prix_attendu):.2f} € attendus "
                    f"(commande {order_ref}).")

        order_by_adherent[adherent_id] = order_ref
        updates.append((adherent_id, amount))

    # Participants invités (sélectionnés) restés sans paiement : information de relance
    nb_en_attente = 0
    for p in participants:
        if not p.get("selectionne"):
            continue
        if p.get("statut_paiement") == "paye" and p.get("adherent_id") not in seen_participants:
            # Déjà marqué payé en base sans paiement détecté sur cette campagne : signaler
            anomaly("paiement_absent", "avertissement", "Payé en base sans paiement HelloAsso",
                    f"{p.get('nom')} {p.get('prenom')} est marqué « Payé » dans la base mais aucun "
                    f"paiement correspondant n'a été trouvé sur la campagne.")
        elif p.get("statut_paiement") != "paye":
            nb_en_attente += 1

    return {
        "updates": updates,
        "order_by_adherent": order_by_adherent,
        "manual_review": manual_review,
        "anomalies": anomalies,
        "stats": {
            "nb_items": len(items or []),
            "nb_payes": nb_payes,
            "nb_matchs": len({u[0] for u in updates}),
            "nb_en_attente": nb_en_attente,
            "nb_anomalies": len(anomalies),
            "nb_manual_review": len(manual_review),
        },
    }
