"""
Hiérarchie des groupes de créneaux (table planning) pour les listes de sélection
de l'IHM : fiches de présence (Exporter), filtres Adhérents et Attestations.

Un groupe de créneau du planning peut regrouper plusieurs tarifs HelloAsso :
le matching membres/tarifs est à la charge de l'appelant (payload de tarifs
rattaché à chaque créneau). Ce module reste pur : il reçoit la liste des
créneaux déjà agrégés (SqliteRepository.load_creneaux_groups()).
"""
import re

from domain.utils import normalize_string

SECTION_ORDER = ("Collège", "Enfants", "Perfectionnement", "Compétition")


def is_autonome_creneau(creneau) -> bool:
    """Vrai si le créneau (nom du groupe ou l'un de ses tarifs) est un créneau autonome."""
    if "autonome" in normalize_string(creneau.get("groupe") or ""):
        return True
    return any("autonome" in normalize_string(t) for t in creneau.get("tarifs") or [])


def accent_class_pattern(word: str) -> str:
    """Motif regex insensible aux accents (é/è/ê, à, î...) pour découper les libellés."""
    tr = str.maketrans({
        "e": "[eèéêë]", "a": "[aàâä]", "i": "[iîï]", "o": "[oôö]",
        "u": "[uùûü]", "c": "[cç]", "y": "[yÿ]",
    })
    return word.translate(tr)


def shorten_group_label(name: str, keyword: str, drop_patterns=()) -> str:
    """Retire du libellé le nom de rubrique (et autres motifs) devenus redondants.
    Ex : « Compétition - U11-U15 » dans la rubrique Compétition -> « U11-U15 »."""
    parts = re.split(accent_class_pattern(keyword), name, flags=re.IGNORECASE)
    rest = max(parts, key=len) if len(parts) > 1 else name
    for dp in drop_patterns:
        rest = re.sub(dp, "", rest, flags=re.IGNORECASE)
    rest = re.sub(r"\s{2,}", " ", rest).strip(" \t-–—")
    if rest.startswith("(") and rest.endswith(")"):
        rest = rest[1:-1].strip()
    return rest if rest else name


def build_creneau_items(creneaux, include_autonome=True):
    """Organise les créneaux en rubriques hiérarchiques :
    - créneaux hors rubrique d'abord (Autonome, Adultes débutants, Lycée...), sans titre ;
    - puis Collège, Enfants (sous-rubriques par tranche d'âge 2016-2018 / 2019-2020),
      Perfectionnement et Compétition.
    Retourne une liste de (kind, libellé, nom_brut) où kind ∈ {'section', 'sub-section', 'group'}.
    `include_autonome=False` exclut les créneaux autonomes (export des cours)."""
    buckets = {"Collège": [], "Enfants": {}, "Perfectionnement": [], "Compétition": []}
    others = []
    for c in creneaux:
        name = str(c.get("groupe") or "").strip()
        if not name:
            continue
        if not include_autonome and is_autonome_creneau(c):
            continue
        n = normalize_string(name)
        if "competition" in n:
            buckets["Compétition"].append((name, shorten_group_label(name, "competition")))
        elif "college" in n:
            buckets["Collège"].append((name, shorten_group_label(name, "college")))
        elif "enfants" in n:
            m = re.search(r"20\d\d\s*-\s*20\d\d", n)
            sub = m.group(0).replace(" ", "") if m else "Autres tranches"
            short = shorten_group_label(name, "enfants", (r"20\d\d\s*-\s*20\d\d",))
            buckets["Enfants"].setdefault(sub, []).append((name, short))
        elif "perfectionnement" in n:
            buckets["Perfectionnement"].append((name, shorten_group_label(name, "perfectionnement")))
        else:
            others.append((name, name))

    items = []
    # Les créneaux hors rubrique sont listés en premier, sans titre de rubrique.
    items.extend(("group", short, name) for name, short in sorted(others))
    for section in SECTION_ORDER:
        entries = buckets.get(section)
        if not entries:
            continue
        items.append(("section", section, section))
        if isinstance(entries, dict):
            for sub in sorted(entries):
                items.append(("sub-section", sub, sub))
                items.extend(("group", short, name) for name, short in sorted(entries[sub]))
        else:
            items.extend(("group", short, name) for name, short in sorted(entries))
    return items


def prune_empty_sections(blocks):
    """Retire les rubriques (section / sub-section) sans aucun créneau exploitable
    en dessous : utile quand l'appelant filtre les créneaux dont le payload est vide.
    Les blocs attendus sont des tuples (kind, label, payload) avec
    kind ∈ {'section', 'sub-section', 'group'} ; l'ordre est préservé."""
    n = len(blocks)
    keep = [True] * n
    for i, (kind, _label, _payload) in enumerate(blocks):
        if kind not in ("section", "sub-section"):
            continue
        level = 0 if kind == "section" else 1
        has_group = False
        for j in range(i + 1, n):
            k2 = blocks[j][0]
            if k2 == "group":
                has_group = True
                break
            # Un nouveau titre de niveau >= arrête la recherche de descendants
            if k2 == "section" or (k2 == "sub-section" and level == 1):
                break
        if not has_group:
            keep[i] = False
    return [b for i, b in enumerate(blocks) if keep[i]]