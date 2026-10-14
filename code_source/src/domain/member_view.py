"""Member list of the web pages, computed on the server (port of `buildMembersData`,
web/shared/alj-members.js, which rebuilt it in the browser from the crm_* collections).

Pure functions: rows in, dicts out (no database access).
"""

import json
import re
from typing import Any, Dict, Iterable, List, Optional

from domain.age_rules import age_at, get_season_start_date, parse_birth_date
from domain.utils import normalize_string

STATUS_MAP = {
    "processed": "Traité", "validated": "Validé", "validé": "Validé", "valide": "Validé",
    "terminé": "Terminé", "termine": "Terminé", "annulé": "Annulé", "annule": "Annulé",
    "canceled": "Annulé", "en cours": "En cours",
}


def normalize_status(status) -> str:
    raw = str(status or "").strip()
    return STATUS_MAP.get(raw.lower(), raw)


def normalize_gender(value) -> str:
    s = str(value or "").strip().lower()
    if s in ("f", "femme", "féminin", "feminin"):
        return "Femme"
    if s in ("h", "m", "homme", "masculin"):
        return "Homme"
    return str(value or "").strip()


_FIRST_NAME_WORD = re.compile(r"(^|[\s\-'’])([a-zà-öø-ÿ])", re.IGNORECASE)
_CITY_PARTICLES = frozenset({"de", "des", "du", "d", "en", "sur", "sous", "les", "la", "le"})
_DIGIT_PAIR = re.compile(r"([0-9]{2})(?=[0-9])")


def fmt_last_name(name) -> str:
    """Last names in capitals: "de lima" -> "DE LIMA"."""
    return str(name or "").strip().upper()


def fmt_first_name(name) -> str:
    """Each word capitalized, compound names included: "JEAN-PIERRE" -> "Jean-Pierre"."""
    s = str(name or "").strip().lower()
    return _FIRST_NAME_WORD.sub(lambda m: m.group(1) + m.group(2).upper(), s)


def fmt_city(city) -> str:
    """Words capitalized, French particles lower case except first:
    "VILLETTE D'ANTHON" -> "Villette d'Anthon"."""
    s = re.sub(r"\s+", " ", str(city or "").strip().replace("’", "'").replace("‘", "'"))

    def cap_word(word: str, first: bool) -> str:
        parts = re.split(r"(')", word)
        return "".join(
            p if p == "'"
            else p.lower() if not first and p.lower() in _CITY_PARTICLES
            else p[:1].upper() + p[1:].lower()
            for p in parts)

    out, index = [], 0
    for tok in re.split(r"([-\s])", s):
        if tok == "-" or (tok and tok.isspace()):
            out.append(tok)
            continue
        out.append(cap_word(tok, index == 0))
        index += 1
    return "".join(out)


def fmt_phone(phone) -> str:
    """Digits by pairs, +33/0033 turned into 0: "+33619984329" -> "06 19 98 43 29"."""
    s = re.sub(r"^(\+33|0033)\s*", "0", str(phone or "").strip())
    digits = re.sub(r"[^0-9]", "", s)
    if len(digits) == 9 and digits[0] != "0":
        digits = "0" + digits
    if len(digits) == 10 or (len(digits) > 4 and len(digits) % 2 == 0):
        return _DIGIT_PAIR.sub(r"\1 ", digits)
    return s


def _tarifs(row: Dict[str, Any]) -> List[str]:
    """`helloasso_tarifs` of a planning row, already decoded or as JSON text."""
    raw = row.get("helloasso_tarifs") or []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw or "[]")
        except ValueError:
            raw = []
    return [str(t).strip() for t in raw or [] if str(t or "").strip()]


def _by_id(planning: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(planning, key=lambda r: int(r.get("id") or 0))


def tarif_slots(planning: Iterable[Dict[str, Any]]) -> Dict[str, Dict[str, str]]:
    """{normalized tariff: slot} where a slot is {groupe, categorie_age, type, jour, horaires}.

    A tariff listed by several planning rows belongs to the **first** row by id (the rule of
    the web pages, plan S11)."""
    slots: Dict[str, Dict[str, str]] = {}
    for row in _by_id(planning):
        groupe = str(row.get("groupe") or "").strip()
        if not groupe:
            continue
        for tarif in _tarifs(row):
            slots.setdefault(normalize_string(tarif), {
                "groupe": groupe,
                "categorie_age": row.get("categorie_age") or "",
                "type": row.get("type") or "",
                "jour": row.get("jour") or "",
                "horaires": row.get("horaires") or "",
            })
    return slots


def creneaux(planning: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Slot groups of the planning, each with the tariffs it covers, sorted by name."""
    by_name: Dict[str, Dict[str, Any]] = {}
    for row in _by_id(planning):
        groupe = str(row.get("groupe") or "").strip()
        if not groupe:
            continue
        group = by_name.setdefault(groupe, {"groupe": groupe, "tarifs": [],
                                            "categorie_age": row.get("categorie_age") or "",
                                            "type": row.get("type") or ""})
        for tarif in _tarifs(row):
            if tarif not in group["tarifs"]:
                group["tarifs"].append(tarif)
    return sorted(by_name.values(), key=lambda g: normalize_string(g["groupe"]))


def member_row(row: Dict[str, Any], slots: Dict[str, Dict[str, str]],
               ref_date) -> Dict[str, Any]:
    """One member of a season (one purchase) as the pages use it."""
    tarif = row.get("tarif_name") or ""
    slot: Optional[Dict[str, str]] = slots.get(normalize_string(tarif))
    birth = row.get("birth_date") or ""
    parsed = parse_birth_date(birth)
    age = age_at(parsed, ref_date) if parsed else None
    text = {k: row.get(k) or "" for k in (
        "address", "zip_code", "email_primary", "email_secondary", "licence_ffme",
        "health_commitment", "photo_auth", "badge_rouge", "autonomie_bloc", "raw_passports",
        "raw_diplomas", "payer_email", "order_ref", "order_date", "status", "document_sante",
        "email_sent_date", "commentaires_correctif", "season_name")}
    return {
        **text,
        "last_name": fmt_last_name(row.get("last_name")),
        "first_name": fmt_first_name(row.get("first_name")),
        "city": fmt_city(row.get("city")),
        "phone": fmt_phone(row.get("phone")),
        "emergency1_name": fmt_first_name(row.get("emergency1_name")),
        "emergency1_phone": fmt_phone(row.get("emergency1_phone")),
        "emergency2_name": fmt_first_name(row.get("emergency2_name")),
        "emergency2_phone": fmt_phone(row.get("emergency2_phone")),
        "passeport_orange": "",  # read by getMemberDiplomes; no such column in the database
        "user_id": row.get("user_id"),
        "purchase_id": row.get("purchase_id"),
        "birth_date": birth,
        "age": age if age is not None and age >= 0 else None,
        "gender": normalize_gender(row.get("gender")),
        "payer": " ".join(p for p in (row.get("payer_first_name"), row.get("payer_last_name")) if p),
        "tarif_name": tarif,
        "amount": row.get("amount"),
        "status_norm": normalize_status(row.get("status")),
        "creneau_groupe": slot["groupe"] if slot else "",
        "categorie": (slot["categorie_age"] or slot["type"]) if slot else "",
        "creneau_details": f"{slot['jour']} {slot['horaires']}".strip() if slot else "",
    }


def build_members(rows: Iterable[Dict[str, Any]], planning: Iterable[Dict[str, Any]],
                  season: str) -> List[Dict[str, Any]]:
    """Members of `season`, ages at the season start (1 September), sorted by name."""
    slots = tarif_slots(planning)
    ref_date = get_season_start_date(season)
    members = [member_row(r, slots, ref_date) for r in rows]
    members.sort(key=lambda m: (normalize_string(m["last_name"]), normalize_string(m["first_name"])))
    return members
