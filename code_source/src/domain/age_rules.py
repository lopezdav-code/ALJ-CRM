"""
Règles de contrôle d'âge des inscriptions (bornes de date de naissance par groupe).

Règles métier :
- La saison démarre le 01/09 de l'année de début (ex : saison 2026-2027 -> 01/09/2026).
- Un adhérent est « adulte » s'il a 18 ans révolus à la date de début de saison.
- Chaque groupe (créneau) du planning peut porter des bornes de date de naissance
  (colonnes naissance_min / naissance_max, format ISO 'AAAA-MM-JJ').
- À défaut de bornes configurées, les années de naissance sont déduites du libellé
  du tarif HelloAsso (ex : « jeunes nés en 2011, 2012, 2013, 2014 »).
- Un adulte ne peut pas souscrire à un groupe enfants / collège / lycée.
"""
import datetime
import re

ADULT_AGE = 18
SEASON_START_MONTH = 9
SEASON_START_DAY = 1

# Mots-clés identifiant un groupe « jeunes » (enfants / collège / lycée)
YOUTH_KEYWORDS = ("collège", "college", "lycée", "lycee", "enfant")

# Années plausibles uniquement (évite de capturer des horaires, montants, etc.)
_YEAR_RE = re.compile(r"(?<!\d)(19\d{2}|20\d{2})(?!\d)")

_BIRTH_FORMATS = (
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d",
    "%Y-%m-%d %H:%M:%S",
    "%d/%m/%Y",
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%y",
)


def get_season_start_date(season=None):
    """Retourne la date de début de la saison (01/09 de l'année de début)."""
    if not season:
        try:
            from domain.constants import get_active_season
            season = get_active_season()
        except Exception:
            season = None
    try:
        start_year = int(str(season).strip().split("-")[0])
    except (ValueError, IndexError, AttributeError):
        start_year = datetime.date.today().year
    return datetime.date(start_year, SEASON_START_MONTH, SEASON_START_DAY)


def age_at(birth_date, ref_date):
    """Âge révolu à la date de référence (None si dates invalides)."""
    if not birth_date or not ref_date:
        return None
    try:
        return ref_date.year - birth_date.year - (
            (ref_date.month, ref_date.day) < (birth_date.month, birth_date.day)
        )
    except Exception:
        return None


def parse_birth_date(val):
    """Convertit une date de naissance (datetime, date, ISO, jj/mm/aaaa) en datetime.date, sinon None."""
    if val is None:
        return None
    if isinstance(val, datetime.datetime):
        return val.date()
    if isinstance(val, datetime.date):
        return val
    s = str(val).strip()
    if not s or s.lower() in ("nan", "none", "nat"):
        return None
    if "T" in s:
        s = s[:19]
    for fmt in _BIRTH_FORMATS:
        try:
            return datetime.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def extract_birth_years(text):
    """Extrait les années de naissance plausibles d'un libellé (tarif ou groupe).

    Gère les formulations HelloAsso : « nés en 2011, 2012, 2013, 2014 »,
    « nés entre 2001 et 2008 », « enfants 2016-2018 »...

    Les années >= à l'année de début de saison sont ignorées : ce sont des
    libellés de saison (ex : « déjà licenciés FFME pour 2026-2027 »), pas des
    années de naissance (un adhérent ne peut pas être né pendant la saison en cours).
    """
    if not text:
        return []
    years = {int(m.group(0)) for m in _YEAR_RE.finditer(str(text))}
    season_start_year = get_season_start_date().year
    return sorted(y for y in years if y < season_start_year)


def _parse_iso_or_none(val):
    s = str(val or "").strip()
    if not s:
        return None
    return parse_birth_date(s)


def get_group_birth_bounds(planning_item):
    """Bornes (min, max) en datetime.date depuis les colonnes naissance_min / naissance_max."""
    if not planning_item:
        return (None, None)
    return (
        _parse_iso_or_none(planning_item.get("naissance_min")),
        _parse_iso_or_none(planning_item.get("naissance_max")),
    )


def bounds_from_tarif_name(tarif_name):
    """Bornes déduites des années de naissance présentes dans le libellé du tarif."""
    years = extract_birth_years(tarif_name)
    if not years:
        return (None, None)
    return (
        datetime.date(min(years), 1, 1),
        datetime.date(max(years), 12, 31),
    )


def resolve_birth_bounds(planning_item, tarif_name):
    """Bornes effectives : colonnes du créneau en priorité, sinon déduction depuis le tarif."""
    bounds = get_group_birth_bounds(planning_item)
    if bounds[0] or bounds[1]:
        return bounds
    return bounds_from_tarif_name(tarif_name)


def is_youth_group(planning_item, tarif_name="", bounds=None, season_start=None):
    """Vrai si le groupe est réservé aux jeunes (enfants / collège / lycée).

    Détection combinée :
    1. Mots-clés « jeunes » dans le nom du groupe ou le libellé du tarif,
       sauf mention explicite « adulte » (ex : « U19 Adulte perfectionnement »,
       « Jeunes Adultes autonomes »).
    2. Bornes de naissance dont le membre le plus âgé est mineur au 01/09.
    """
    if season_start is None:
        season_start = get_season_start_date()

    name = str((planning_item or {}).get("groupe") or "")
    combined = f"{name} {tarif_name or ''}".lower()

    if "adulte" in combined:
        return False
    for kw in YOUTH_KEYWORDS:
        if kw in combined:
            return True

    if bounds is None:
        bounds = get_group_birth_bounds(planning_item)
    min_bound = (bounds or (None, None))[0]
    if min_bound:
        oldest_age = age_at(min_bound, season_start)
        if oldest_age is not None and oldest_age < ADULT_AGE:
            return True
    return False


def check_age_conflict(birth_date_raw, tarif_name, planning_item=None, season=None):
    """Contrôle une inscription au regard des bornes de naissance du groupe.

    Retourne la liste des messages d'incohérence (liste vide = inscription conforme).
    """
    birth = parse_birth_date(birth_date_raw)
    if birth is None:
        return [
            f"Date de naissance absente ou illisible ('{str(birth_date_raw or '').strip()}') : "
            f"contrôle d'âge impossible pour le tarif '{str(tarif_name or '').strip()}'"
        ]

    season_start = get_season_start_date(season)
    bounds = resolve_birth_bounds(planning_item, tarif_name)
    messages = []

    min_bound, max_bound = bounds
    if min_bound and birth < min_bound:
        messages.append(
            f"Né(e) le {birth.strftime('%d/%m/%Y')} : antérieur à la borne du groupe "
            f"(naissances admises à partir du {min_bound.strftime('%d/%m/%Y')})"
        )
    if max_bound and birth > max_bound:
        messages.append(
            f"Né(e) le {birth.strftime('%d/%m/%Y')} : postérieur à la borne du groupe "
            f"(naissances admises jusqu'au {max_bound.strftime('%d/%m/%Y')})"
        )

    age = age_at(birth, season_start)
    if age is not None and age >= ADULT_AGE and is_youth_group(
        planning_item, tarif_name, bounds, season_start
    ):
        messages.append(
            f"Adulte ({age} ans au {season_start.strftime('%d/%m/%Y')}) : "
            f"interdit dans un groupe enfants / collège / lycée"
        )

    return messages


def find_planning_item_for_tarif(tarif_name, planning_data):
    """Retrouve le créneau du planning associé à un tarif HelloAsso (mapping IHM)."""
    target = str(tarif_name or "").strip().lower()
    if not target or not planning_data:
        return None
    for item in planning_data:
        for t in item.get("helloasso_tarifs", []) or []:
            if str(t).strip().lower() == target:
                return item
    return None
