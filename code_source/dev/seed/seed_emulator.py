"""
Remplit l'émulateur Firestore local avec des données FICTIVES (univers Harry Potter).

    cd code_source
    set -a && source dev/dev.env && set +a
    python dev/seed/seed_emulator.py

Réinitialise entièrement la base de l'émulateur puis reproduit le chemin de production :
1. base SQLite temporaire au schéma courant, alimentée par les mêmes fonctions que
   l'import HelloAsso (`SqliteRepository.upsert_members`, `save_planning_data`, …) ;
2. envoi vers Firestore avec `cloud_database.import_database` (format `crm_*` réel) ;
3. projection `adherents` / `planning` de la PWA, encadrants et compétitions via
   `CompetitionFirestoreRepository`.

Refuse de s'exécuter hors du mode dev (ALJ_ENV=dev + émulateur + projet demo-alj).
"""
import datetime
import json
import os
import random
import sys
import tempfile
import unicodedata

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.normpath(os.path.join(HERE, "..", "..", "src"))
sys.path.insert(0, SRC)
sys.path.insert(0, HERE)

from infrastructure import runtime_env  # noqa: E402

SEED = 42
SEASON = "2026-2027"
PREVIOUS_SEASON = "2025-2026"
RETURNING_RATIO = 0.7          # part des adhérents déjà inscrits la saison précédente
EMAIL_DOMAIN = "poudlard.example"   # domaine réservé : aucun e-mail ne peut être délivré

# Comptes Google fictifs de l'émulateur Auth, un par rôle (cf. firestore.rules / api_auth) :
# (identifiant, e-mail, nom affiché, custom claims)
DEV_ACCOUNTS = [
    ("dev-dumbledore", "albus.dumbledore@alj-escalade.fr", "Albus Dumbledore (admin)", {}),
    ("dev-snape", f"severus.snape@{EMAIL_DOMAIN}", "Severus Snape (coach)", {"coach": True}),
    ("dev-filch", f"argus.filch@{EMAIL_DOMAIN}", "Argus Filch (lecture)", {"readonly": True}),
]


def ensure_emulator() -> str:
    """Double garde : mode dev + émulateur + projet demo-*. Retourne l'hôte Firestore."""
    runtime_env.validate()
    host = runtime_env.firestore_emulator_host()
    project = runtime_env.project_id_override() or ""
    if not host or not project.startswith("demo-"):
        raise SystemExit("❌ Refusé : ce script n'écrit que dans l'émulateur Firebase "
                         "(ALJ_ENV=dev, FIRESTORE_EMULATOR_HOST, projet demo-*). "
                         "Lancez : set -a && source dev/dev.env && set +a")
    return host


def reset_emulator(host: str, project: str) -> None:
    url = f"http://{host}/emulator/v1/projects/{project}/databases/(default)/documents"
    resp = requests.delete(url, timeout=30)
    resp.raise_for_status()


def drop_server_cache() -> None:
    """Supprime le cache SQLite du serveur dev (ALJ_DATA_DIR) : la réinitialisation ne laisse
    pas de suppressions à synchroniser, le serveur reconstruira son cache depuis l'émulateur."""
    from infrastructure.sqlite_repository import SqliteRepository
    if not os.environ.get("ALJ_DATA_DIR"):
        # Sans dossier dédié, le chemin par défaut serait la base du poste (data/) : on n'y touche pas.
        print("ℹ️  ALJ_DATA_DIR non défini : cache du serveur dev conservé.")
        return
    db = SqliteRepository.get_db_path()
    for path in (db, db + "-wal", db + "-shm"):
        if os.path.exists(path):
            os.remove(path)


def seed_auth_accounts(auth_host: str, project: str) -> None:
    """Recrée les comptes de connexion (fournisseur google.com simulé, rôles par custom claims)."""
    base = f"http://{auth_host}"
    admin = {"Authorization": "Bearer owner"}   # jeton admin de l'émulateur
    requests.delete(f"{base}/emulator/v1/projects/{project}/accounts", timeout=30).raise_for_status()
    for sub, email, name, claims in DEV_ACCOUNTS:
        id_token = json.dumps({"sub": sub, "email": email, "email_verified": True, "name": name})
        resp = requests.post(
            f"{base}/identitytoolkit.googleapis.com/v1/accounts:signInWithIdp?key=demo",
            json={"postBody": f"id_token={id_token}&providerId=google.com",
                  "requestUri": "http://localhost", "returnSecureToken": True},
            timeout=30)
        resp.raise_for_status()
        if claims:
            requests.post(
                f"{base}/identitytoolkit.googleapis.com/v1/projects/{project}/accounts:update",
                headers=admin, json={"localId": resp.json()["localId"], "customAttributes": json.dumps(claims)},
                timeout=30).raise_for_status()


# --------------------------------------------------------------------------
# Données
# --------------------------------------------------------------------------
def planning_items(coaches):
    """Créneaux de la saison (bornes de naissance cohérentes avec age_rules)."""
    snape, mcgonagall, flitwick, sprout, lupin, hagrid = coaches
    items = [
        ("Loisir - Enfants 2017-2019", "cours", "U8-U10", "Mercredi", "14h00-15h30",
         [hagrid, sprout], ["Loisir - Enfants 2017-2019"], "2017-01-01", "2019-12-31"),
        ("Loisir - Collège (Groupe A)", "cours", "U12-U15", "Lundi", "18h30-20h00",
         [flitwick], ["Loisir collège - jeunes nés en 2012, 2013, 2014, 2015 - lundi 18h30"],
         "2012-01-01", "2015-12-31"),
        ("Loisir - Lycée", "cours", "U16-U18", "Jeudi", "18h30-20h00",
         [lupin], ["Loisir lycée - jeunes nés en 2009, 2010, 2011"], "2009-01-01", "2011-12-31"),
        ("Compétition - U11-U13", "compétition", "U11-U13", "Mercredi", "16h00-18h00",
         [snape, mcgonagall], ["Compétition U11-U13"], "2014-01-01", "2017-12-31"),
        ("Compétition - U15-U17-U19", "compétition", "U15-U19", "Vendredi", "18h00-20h00",
         [snape], ["Compétition U15 U17 - jeunes nés en 2008, 2009, 2010, 2011, 2012, 2013"],
         "2008-01-01", "2013-12-31"),
        ("Loisir - Adultes débutants", "cours", "Adultes", "Mardi", "20h00-22h00",
         [mcgonagall], ["Cours Adultes débutants"], "", ""),
        ("Autonome", "autonome", "Adultes", "Lundi / Jeudi", "20h00-22h30",
         [], ["Adultes autonomes"], "", ""),
        ("Autonome Bloc", "autonome", "Adultes", "Samedi", "10h00-12h00",
         [], ["Autonomes bloc"], "", ""),
    ]
    return [
        {"id": i, "groupe": g, "type": t, "categorie_age": cat, "jour": jour, "horaires": h,
         "encadrants": enc, "helloasso_tarifs": tarifs, "naissance_min": nmin, "naissance_max": nmax,
         "whatsapp_link": ""}
        for i, (g, t, cat, jour, h, enc, tarifs, nmin, nmax) in enumerate(items, start=1)
    ]


TARIF_AMOUNTS = {"cours": 210.0, "compétition": 260.0, "autonome": 150.0}


def ascii_slug(text: str) -> str:
    s = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return "".join(c for c in s.lower() if c.isalnum() or c == "-")


def build_people(fake, rng, planning):
    """Une personne = identité stable + créneau choisi selon son année de naissance."""
    from hp_names import ADULTS, STUDENTS
    youth = [p for p in planning if p["naissance_min"]]
    adults = [p for p in planning if not p["naissance_min"]]
    people = []
    for first, last, sex in STUDENTS:
        group = rng.choice(youth)
        y_min, y_max = int(group["naissance_min"][:4]), int(group["naissance_max"][:4])
        birth = fake.date_between_dates(datetime.date(y_min, 1, 1), datetime.date(y_max, 12, 31))
        people.append({"first": first, "last": last, "sex": sex, "birth": birth, "group": group,
                       "minor": True})
    for first, last, sex in ADULTS:
        birth = fake.date_between_dates(datetime.date(1960, 1, 1), datetime.date(2004, 12, 31))
        people.append({"first": first, "last": last, "sex": sex, "birth": birth,
                       "group": rng.choice(adults), "minor": False})
    return people


def member_record(fake, rng, person, season, order_no):
    """Enregistrement au format de l'import HelloAsso (clés lues par schema_v2)."""
    from hp_names import PARENTS
    from infrastructure.schema_v2 import DOB_COLUMN
    first, last, group = person["first"], person["last"], person["group"]
    email = f"{ascii_slug(first)}.{ascii_slug(last)}@{EMAIL_DOMAIN}"
    if person["minor"]:
        payer_first = PARENTS.get(last) or fake.first_name()
        payer_email = f"{ascii_slug(payer_first)}.{ascii_slug(last)}@{EMAIL_DOMAIN}"
    else:
        payer_first, payer_email = first, email
    start_year = int(season[:4])
    order_date = fake.date_between_dates(datetime.date(start_year, 6, 20), datetime.date(start_year, 9, 30))
    incomplete = rng.random() < 0.12      # quelques fiches à compléter (cas réels à tester)
    insured = rng.random() < 0.8
    return {
        "order_ref": f"DEV-{season[:4]}-{order_no:04d}",
        "order_date": order_date.strftime("%d/%m/%Y"),
        "status": "Validé",
        "payer_lastName": last.upper(),
        "payer_firstName": payer_first,
        "payer_email": payer_email,
        "tarif_name": group["helloasso_tarifs"][0],
        "amount": TARIF_AMOUNTS.get(group["type"], 200.0),
        "user_lastName": last.upper(),
        "user_firstName": first,
        DOB_COLUMN: person["birth"].strftime("%d/%m/%Y"),
        "champ_Sexe": "Féminin" if person["sex"] == "F" else "Masculin",
        "champ_Nationalité": "Française",
        "champ_Adresse : numéro et nom de rue": fake.street_address(),
        "champ_Code postal": rng.choice(["69330", "69150", "69120", "69800"]),
        "champ_Ville": rng.choice(["Jonage", "Meyzieu", "Décines-Charpieu", "Vaulx-en-Velin"]),
        "champ_Pays": "France",
        "champ_Téléphone ": "" if incomplete else fake.phone_number(),
        "champ_Adresse mail pour la réception des informations du club": email,
        "champ_Personne à prévenir en cas d'urgence - NOM  et PRENOM en majuscule":
            f"{last.upper()} {payer_first.upper()}" if person["minor"] else fake.name().upper(),
        "champ_Personne à prévenir en cas d'urgence - Téléphone": fake.phone_number(),
        "champ_Numéro de Licence FFME (6 chiffres)": "" if incomplete else str(rng.randint(100000, 999999)),
        "champ_En cas de prise de vue (Photo ou vidéo), j'autorise": "Oui" if rng.random() < 0.9 else "Non",
        "champ_Je m'engage à compléter mon questionnaire de santé": "" if incomplete else "Oui",
        "opt_Assurance Base": "Oui" if insured else "Non",
        "opt_Montant Assurance Base": 10.0 if insured else 0.0,
    }


EMAIL_TEMPLATES = [
    ("Bienvenue", "Bienvenue au club, {Prénom} !",
     "Bonjour {Prénom},\n\nTon inscription à la section escalade est validée. "
     "Rendez-vous au premier créneau !\n\nLe bureau"),
    ("Convocation compétition", "Convocation : {name_competition}",
     "Bonjour {Prénom},\n\nTu es sélectionné(e) pour {name_competition} le {date_competition}. "
     "Participation : {montant_competition} €.\n\nLes encadrants"),
]


# --------------------------------------------------------------------------
# Écriture
# --------------------------------------------------------------------------
def build_sqlite(path, fake, rng, coach_names):
    from infrastructure.sqlite_repository import SqliteRepository
    SqliteRepository.set_db_path(path)
    SqliteRepository.setup_database(force=True)

    planning = planning_items(coach_names)
    SqliteRepository.save_planning_data(planning)

    people = build_people(fake, rng, planning)
    current = [member_record(fake, rng, p, SEASON, i) for i, p in enumerate(people, start=1)]
    returning = [p for p in people if rng.random() < RETURNING_RATIO]
    previous = [member_record(fake, rng, p, PREVIOUS_SEASON, i) for i, p in enumerate(returning, start=1)]
    SqliteRepository.upsert_members(previous, PREVIOUS_SEASON)
    SqliteRepository.upsert_members(current, SEASON)

    for name, subject, body in EMAIL_TEMPLATES:
        SqliteRepository.save_email_template(name, subject, body, "", "ALJ Escalade (dev)")
    return len(current), len(previous)


def seed_competitions(coach_ids):
    from domain.competition_models import STATUT_CLOSE, STATUT_EN_COURS, STATUT_EN_PREPARATION, Competition
    from infrastructure.competition_firestore_repository import CompetitionFirestoreRepository as Repo

    snape, mcgonagall, flitwick = coach_ids[0], coach_ids[1], coach_ids[2]
    today = datetime.date.today()
    specs = [
        ("Coupe du Rhône de bloc", today - datetime.timedelta(days=35), 12.0, STATUT_CLOSE, "", snape, None),
        ("Open de Poudlard (difficulté)", today + datetime.timedelta(days=12), 15.0, STATUT_EN_COURS,
         "open-de-poudlard-dev", snape, mcgonagall),
        ("Championnat régional U15-U19", today + datetime.timedelta(days=40), 20.0, STATUT_EN_PREPARATION,
         "", snape, flitwick),
        ("Contest amical de Pré-au-Lard", today + datetime.timedelta(days=75), 8.0, STATUT_EN_PREPARATION,
         "", mcgonagall, None),
    ]
    competitors = [a["id"] for a in Repo.list_adherents(competition_only=True)]
    rng = random.Random(SEED)
    base_id = int(datetime.datetime(today.year, today.month, today.day).timestamp() * 1000)
    for i, (nom, date, prix, statut, ha, c1, c2) in enumerate(specs):
        comp = Competition(id=base_id + i, nom=nom, date_competition=date.isoformat(), prix=prix,
                           statut=statut, helloasso_ref=ha, coach1_id=c1, coach2_id=c2)
        comp_id = Repo.save_competition(comp)
        for adh_id in rng.sample(competitors, k=min(len(competitors), rng.randint(4, 9))):
            Repo.add_participant(comp_id, adh_id, selectionne=rng.random() < 0.8)
    return len(specs), len(competitors)


def main() -> int:
    host = ensure_emulator()
    project = runtime_env.project_id_override()

    from faker import Faker
    from hp_names import COACHES
    from infrastructure import cloud_database as cdb
    from infrastructure.competition_firestore_repository import CompetitionFirestoreRepository as Repo

    Faker.seed(SEED)
    fake = Faker("fr_FR")
    rng = random.Random(SEED)

    print(f"🧹 Réinitialisation de l'émulateur ({host}, projet {project})")
    reset_emulator(host, project)
    drop_server_cache()

    workdir = tempfile.mkdtemp(prefix="alj_seed_")
    db_path = os.path.join(workdir, "seed.db")
    n_cur, n_prev = build_sqlite(db_path, fake, rng, COACHES)
    print(f"🧙 {n_cur} adhésions {SEASON}, {n_prev} adhésions {PREVIOUS_SEASON} (dont réinscriptions)")

    written = cdb.import_database(db_path, cdb.RestStore())
    print(f"☁️  Collections crm_* : {written}")

    # Encadrants : identifiants fixes, Snape en premier (id 1)
    coach_ids = []
    for i, nom in enumerate(COACHES, start=1):
        coach_ids.append(Repo.save_coach(nom, coach_id=i))
    print(f"🧑‍🏫 Encadrants : {', '.join(COACHES)}")

    # Projection lue par la PWA (adherents / planning), depuis la base SQLite de seed
    rep = Repo.sync_adherents_from_main(SEASON)
    if rep.get("errors"):
        print(f"⚠️  Projection adherents : {rep['errors']}")

    n_comp, n_competitors = seed_competitions(coach_ids)
    print(f"🏆 {n_comp} compétitions ({n_competitors} compétiteurs éligibles)")

    seed_auth_accounts(os.environ["FIREBASE_AUTH_EMULATOR_HOST"], project)
    print("🔑 Comptes de connexion : " + ", ".join(email for _, email, _, _ in DEV_ACCOUNTS))
    print("✅ Terminé — UI de l'émulateur : http://localhost:4000/firestore")
    return 0


if __name__ == "__main__":
    sys.exit(main())
