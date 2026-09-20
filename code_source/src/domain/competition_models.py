"""
Modèles métier du module de gestion des compétitions (base dédiée database_Competition.db).

Ces modèles sont purs (aucune dépendance Qt / réseau) afin d'être réutilisables
par l'application de bureau, le serveur web et les tests unitaires.
"""
from dataclasses import dataclass

# Statuts possibles d'une compétition (cycle de vie)
STATUT_EN_PREPARATION = "en_preparation"
STATUT_EN_COURS = "en_cours"
STATUT_CLOSE = "close"
STATUTS_COMPETITION = (STATUT_EN_PREPARATION, STATUT_EN_COURS, STATUT_CLOSE)

LIBELLES_STATUT_COMPETITION = {
    STATUT_EN_PREPARATION: "En préparation",
    STATUT_EN_COURS: "En cours",
    STATUT_CLOSE: "Clos",
}

# Statuts de paiement d'un participant
PAIEMENT_NON_INVITE = "non_invite"
PAIEMENT_EN_ATTENTE = "en_attente"
PAIEMENT_PAYE = "paye"
STATUTS_PAIEMENT = (PAIEMENT_NON_INVITE, PAIEMENT_EN_ATTENTE, PAIEMENT_PAYE)

LIBELLES_STATUT_PAIEMENT = {
    PAIEMENT_NON_INVITE: "Non invité",
    PAIEMENT_EN_ATTENTE: "En attente",
    PAIEMENT_PAYE: "Payé",
}

LIBELLE_VERS_STATUT_PAIEMENT = {v: k for k, v in LIBELLES_STATUT_PAIEMENT.items()}
LIBELLE_VERS_STATUT_COMPETITION = {v: k for k, v in LIBELLES_STATUT_COMPETITION.items()}


@dataclass
class Competition:
    """Une épreuve de la saison (compétition FFME)."""
    id: int = None
    id_ffme: str = ""
    nom: str = ""
    date_competition: str = ""       # ISO AAAA-MM-JJ
    prix: float = 0.0                # tarif d'inscription en euros
    statut: str = STATUT_EN_PREPARATION
    helloasso_ref: str = ""          # slug ou URL de la campagne HelloAsso dédiée
    created_at: str = ""
    updated_at: str = ""
    coach1_id: int = None
    coach2_id: int = None
    coach3_id: int = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "id_ffme": self.id_ffme,
            "nom": self.nom,
            "date_competition": self.date_competition,
            "prix": self.prix,
            "statut": self.statut,
            "helloasso_ref": self.helloasso_ref,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "coach1_id": self.coach1_id,
            "coach2_id": self.coach2_id,
            "coach3_id": self.coach3_id,
        }

    @classmethod
    def from_row(cls, row: dict) -> "Competition":
        return cls(
            id=row.get("id"),
            id_ffme=str(row.get("id_ffme") or ""),
            nom=str(row.get("nom") or ""),
            date_competition=str(row.get("date_competition") or ""),
            prix=float(row.get("prix") or 0.0),
            statut=str(row.get("statut") or STATUT_EN_PREPARATION),
            helloasso_ref=str(row.get("helloasso_ref") or ""),
            created_at=str(row.get("created_at") or ""),
            updated_at=str(row.get("updated_at") or ""),
            coach1_id=row.get("coach1_id"),
            coach2_id=row.get("coach2_id"),
            coach3_id=row.get("coach3_id"),
        )


@dataclass
class Participant:
    """Lien entre un adhérent et une compétition (inscription + suivi du paiement)."""
    id: int = None
    competition_id: int = None
    adherent_id: int = None
    # Champs dénormalisés (copie adhérent pour affichage et export autonome) :
    nom: str = ""
    prenom: str = ""
    num_licence: str = ""
    email: str = ""
    tarif: str = ""
    selectionne: bool = False
    statut_paiement: str = PAIEMENT_NON_INVITE
    date_synchro_helloasso: str = ""
    montant_paye: float = 0.0
    commande_helloasso: str = ""     # n° de commande HelloAsso (renseigné à la synchro)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "competition_id": self.competition_id,
            "adherent_id": self.adherent_id,
            "nom": self.nom,
            "prenom": self.prenom,
            "num_licence": self.num_licence,
            "email": self.email,
            "tarif": self.tarif,
            "selectionne": bool(self.selectionne),
            "statut_paiement": self.statut_paiement,
            "date_synchro_helloasso": self.date_synchro_helloasso,
            "montant_paye": self.montant_paye,
            "commande_helloasso": self.commande_helloasso,
        }

    @classmethod
    def from_row(cls, row: dict) -> "Participant":
        sel = row.get("selectionne")
        return cls(
            id=row.get("id"),
            competition_id=row.get("competition_id"),
            adherent_id=row.get("adherent_id"),
            nom=str(row.get("nom") or ""),
            prenom=str(row.get("prenom") or ""),
            num_licence=str(row.get("num_licence") or ""),
            email=str(row.get("email") or ""),
            tarif=str(row.get("tarif") or ""),
            selectionne=bool(sel) and str(sel) not in ("0", "Non", "non"),
            statut_paiement=str(row.get("statut_paiement") or PAIEMENT_NON_INVITE),
            date_synchro_helloasso=str(row.get("date_synchro_helloasso") or ""),
            montant_paye=float(row.get("montant_paye") or 0.0),
            commande_helloasso=str(row.get("commande_helloasso") or ""),
        )
