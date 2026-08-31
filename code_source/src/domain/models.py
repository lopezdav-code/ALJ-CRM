from dataclasses import dataclass, field
from typing import Dict, Any, Optional

@dataclass
class InsuranceOptions:
    has_base: bool = False
    amount_base: float = 0.0
    has_base_plus: bool = False
    amount_base_plus: float = 0.0
    has_base_plus_plus: bool = False
    amount_base_plus_plus: float = 0.0
    has_ski: bool = False
    amount_ski: float = 0.0
    has_vtt: bool = False
    amount_vtt: float = 0.0
    has_trail: bool = False
    amount_trail: float = 0.0

@dataclass
class Member:
    order_ref: str
    order_date: str
    status: str
    tarif_name: str
    amount: float
    user_last_name: str
    user_first_name: str
    payer_first_name: str
    payer_last_name: str
    payer_email: str
    birth_date: str = ""
    gender: str = ""
    nationality: str = ""
    address: str = ""
    zip_code: str = ""
    city: str = ""
    country: str = ""
    phone: str = ""
    primary_email: str = ""
    secondary_email: str = ""
    emergency_contact_name_1: str = ""
    emergency_contact_phone_1: str = ""
    emergency_contact_name_2: str = ""
    emergency_contact_phone_2: str = ""
    photo_auth: str = ""
    health_q_auth: str = ""
    is_tribe: str = ""
    licence_ffme: str = ""
    insurance: InsuranceOptions = field(default_factory=InsuranceOptions)
    commentaires_correctif: str = ""
    email_sent_date: str = ""
    member_id: str = ""
    badge_rouge: str = "Non"
    autonomie_bloc: str = "Non"
    raw_passports: str = ""
    raw_diplomas: str = ""
    parental_auth_autonomous: str = "Non"  # Nouveau !
    parental_auth_family: str = "Non"      # Nouveau !
    already_member: str = "Non"

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Member":
        """Crée une instance de Member à partir d'un dictionnaire brut (ex: HelloAsso ou Excel)."""
        ins = InsuranceOptions(
            has_base=data.get("opt_Assurance Base") == "Oui",
            amount_base=float(data.get("opt_Montant Assurance Base", 0.0) or 0.0),
            has_base_plus=data.get("opt_Assurance Base +") == "Oui",
            amount_base_plus=float(data.get("opt_Montant Assurance Base +", 0.0) or 0.0),
            has_base_plus_plus=data.get("opt_Assurance Base ++") == "Oui",
            amount_base_plus_plus=float(data.get("opt_Montant Assurance Base ++", 0.0) or 0.0),
            has_ski=data.get("opt_Assurance Option ski de piste") == "Oui",
            amount_ski=float(data.get("opt_Montant Assurance Option ski de piste", 0.0) or 0.0),
            has_vtt=data.get("opt_Assurance Option VTT") == "Oui",
            amount_vtt=float(data.get("opt_Montant Assurance Option VTT", 0.0) or 0.0),
            has_trail=data.get("opt_Assurance Option Trail") == "Oui",
            amount_trail=float(data.get("opt_Montant Assurance Option Trail", 0.0) or 0.0),
        )

        def clean_float_str(val) -> str:
            s = str(val or "").strip()
            if s.endswith(".0"):
                return s[:-2]
            return s

        return cls(
            order_ref=str(data.get("order_ref") or ""),
            order_date=str(data.get("order_date") or ""),
            status=str(data.get("status") or ""),
            tarif_name=str(data.get("tarif_name") or "").strip(),
            amount=float(data.get("amount", 0.0) or 0.0),
            user_last_name=str(data.get("user_lastName") or "").strip(),
            user_first_name=str(data.get("user_firstName") or "").strip(),
            payer_first_name=str(data.get("payer_firstName") or "").strip(),
            payer_last_name=str(data.get("payer_lastName") or "").strip(),
            payer_email=str(data.get("payer_email") or "").strip(),
            birth_date=str(data.get("champ_Date de naissance de l'adhérent") or data.get("birth_date") or "").strip(),
            gender=str(data.get("champ_Sexe") or data.get("gender") or "").strip(),
            nationality=str(data.get("champ_Nationalité") or data.get("nationality") or "").strip(),
            address=str(data.get("champ_Adresse : numéro et nom de rue") or data.get("address") or "").strip(),
            zip_code=clean_float_str(data.get("champ_Code postal") or data.get("zip_code")),
            city=str(data.get("champ_Ville") or data.get("city") or "").strip(),
            country=str(data.get("champ_Pays") or data.get("country") or "").strip(),
            phone=str(data.get("champ_Téléphone ") or data.get("phone") or "").strip(),
            primary_email=str(data.get("champ_Adresse mail pour la réception des informations du club") or data.get("primary_email") or "").strip(),
            secondary_email=str(data.get("champ_Deuxième adresse mail pour la réception des informations du club") or data.get("secondary_email") or "").strip(),
            emergency_contact_name_1=str(data.get("champ_Personne à prévenir en cas d'urgence - NOM  et PRENOM en majuscule") or data.get("emergency_contact_name_1") or "").strip(),
            emergency_contact_phone_1=str(data.get("champ_Personne à prévenir en cas d'urgence - Téléphone") or data.get("emergency_contact_phone_1") or "").strip(),
            emergency_contact_name_2=str(data.get("champ_Parent 2  à prévenir en cas d'urgence - NOM ET PRENOM (en majuscule)") or data.get("emergency_contact_name_2") or "").strip(),
            emergency_contact_phone_2=str(data.get("champ_Parent 2 - Numéro de téléphone portable") or data.get("emergency_contact_phone_2") or "").strip(),
            photo_auth=str(data.get("champ_En cas de prise de vue (Photo ou vidéo), j'autorise...") or data.get("photo_auth") or "").strip(),
            health_q_auth=str(data.get("champ_Je m'engage à compléter mon questionnaire de santé...") or data.get("health_q_auth") or "").strip(),
            is_tribe=str(data.get("champ_Famille : nous sommes une tribu de 3...") or data.get("is_tribe") or "").strip(),
            licence_ffme=clean_float_str(data.get("champ_Numéro de Licence FFME (6 chiffres)") or data.get("licence_ffme")),
            insurance=ins,
            commentaires_correctif=str(data.get("commentaires_correctif") or "").strip(),
            email_sent_date=str(data.get("email_sent_date") or "").strip(),
            badge_rouge=str(data.get("badge_rouge") or "Non").strip(),
            autonomie_bloc=str(data.get("autonomie_bloc") or "Non").strip(),
            raw_passports=str(data.get("raw_passports") or "").strip(),
            raw_diplomas=str(data.get("raw_diplomas") or "").strip(),
            parental_auth_autonomous=str(data.get("parental_auth_autonomous") or "Non").strip(),
            parental_auth_family=str(data.get("parental_auth_family") or "Non").strip(),
            already_member="Oui" if int(data.get("already_member", 0) or 0) > 0 or str(data.get("already_member", "")).strip().lower() in ("oui", "yes", "true", "1") else "Non"
        )

    def to_dict(self) -> Dict[str, Any]:
        """Exporte l'adhérent sous forme de dictionnaire plat compatible avec l'Excel historique."""
        return {
            "order_ref": self.order_ref,
            "order_date": self.order_date,
            "status": self.status,
            "tarif_name": self.tarif_name,
            "amount": self.amount,
            "user_lastName": self.user_last_name,
            "user_firstName": self.user_first_name,
            "payer_firstName": self.payer_first_name,
            "payer_lastName": self.payer_last_name,
            "payer_email": self.payer_email,
            "champ_Date de naissance de l'adhérent": self.birth_date,
            "champ_Sexe": self.gender,
            "champ_Nationalité": self.nationality,
            "champ_Adresse : numéro et nom de rue": self.address,
            "champ_Code postal": self.zip_code,
            "champ_Ville": self.city,
            "champ_Pays": self.country,
            "champ_Téléphone ": self.phone,
            "champ_Adresse mail pour la réception des informations du club": self.primary_email,
            "champ_Deuxième adresse mail pour la réception des informations du club": self.secondary_email,
            "champ_Personne à prévenir en cas d'urgence - NOM  et PRENOM en majuscule": self.emergency_contact_name_1,
            "champ_Personne à prévenir en cas d'urgence - Téléphone": self.emergency_contact_phone_1,
            "champ_Parent 2  à prévenir en cas d'urgence - NOM ET PRENOM (en majuscule)": self.emergency_contact_name_2,
            "champ_Parent 2 - Numéro de téléphone portable": self.emergency_contact_phone_2,
            "champ_En cas de prise de vue (Photo ou vidéo), j'autorise...": self.photo_auth,
            "champ_Je m'engage à compléter mon questionnaire de santé...": self.health_q_auth,
            "champ_Famille : nous sommes une tribu de 3...": self.is_tribe,
            "champ_Numéro de Licence FFME (6 chiffres)": self.licence_ffme,
            "opt_Assurance Base": "Oui" if self.insurance.has_base else "Non",
            "opt_Montant Assurance Base": self.insurance.amount_base,
            "opt_Assurance Base +": "Oui" if self.insurance.has_base_plus else "Non",
            "opt_Montant Assurance Base +": self.insurance.amount_base_plus,
            "opt_Assurance Base ++": "Oui" if self.insurance.has_base_plus_plus else "Non",
            "opt_Montant Assurance Base ++": self.insurance.amount_base_plus_plus,
            "opt_Assurance Option ski de piste": "Oui" if self.insurance.has_ski else "Non",
            "opt_Montant Assurance Option ski de piste": self.insurance.amount_ski,
            "opt_Assurance Option VTT": "Oui" if self.insurance.has_vtt else "Non",
            "opt_Montant Assurance Option VTT": self.insurance.amount_vtt,
            "opt_Assurance Option Trail": "Oui" if self.insurance.has_trail else "Non",
            "opt_Montant Assurance Option Trail": self.insurance.amount_trail,
            "commentaires_correctif": self.commentaires_correctif,
            "email_sent_date": self.email_sent_date,
            "badge_rouge": self.badge_rouge,
            "autonomie_bloc": self.autonomie_bloc,
            "raw_passports": self.raw_passports,
            "raw_diplomas": self.raw_diplomas,
            "parental_auth_autonomous": self.parental_auth_autonomous,
            "parental_auth_family": self.parental_auth_family,
            "already_member": self.already_member
        }
