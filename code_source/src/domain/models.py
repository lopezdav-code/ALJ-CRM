from dataclasses import dataclass, field
from typing import Dict, Any

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
    is_modified: str = "Non"
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
        """
        Crée une instance de Member à partir d'un dictionnaire brut.
        Phase 4 : lecture bilingue — noms v2 (last_name, email_primary, emergency1_name...)
        prioritaires, libellés legacy (user_lastName, champ_*, opt_*) en repli.
        """
        def pick(*keys, default=""):
            for k in keys:
                v = data.get(k)
                if v is not None and str(v).strip() != "":
                    return v
            return default

        def clean_float_str(val) -> str:
            s = str(val or "").strip()
            if s.endswith(".0"):
                return s[:-2]
            return s

        # Options d'assurance : opt_* legacy, ou liste purchase_options v2 si fournie
        opt_list = data.get("purchase_options") or []
        if isinstance(opt_list, list) and opt_list:

            def opt_amount(*names):
                for o in opt_list:
                    if isinstance(o, dict) and str(o.get("option_name") or "").strip() in names:
                        try:
                            return float(o.get("amount") or 0.0)
                        except (ValueError, TypeError):
                            return 0.0
                return 0.0

            ins = InsuranceOptions(
                has_base=opt_amount("Assurance Base") > 0 or data.get("opt_Assurance Base") == "Oui",
                amount_base=opt_amount("Assurance Base") or float(data.get("opt_Montant Assurance Base", 0.0) or 0.0),
                has_base_plus=opt_amount("Assurance Base +") > 0 or data.get("opt_Assurance Base +") == "Oui",
                amount_base_plus=opt_amount("Assurance Base +") or float(data.get("opt_Montant Assurance Base +", 0.0) or 0.0),
                has_base_plus_plus=opt_amount("Assurance Base ++") > 0 or data.get("opt_Assurance Base ++") == "Oui",
                amount_base_plus_plus=opt_amount("Assurance Base ++") or float(data.get("opt_Montant Assurance Base ++", 0.0) or 0.0),
                has_ski=opt_amount("Assurance Option ski de piste") > 0 or data.get("opt_Assurance Option ski de piste") == "Oui",
                amount_ski=opt_amount("Assurance Option ski de piste") or float(data.get("opt_Montant Assurance Option ski de piste", 0.0) or 0.0),
                has_vtt=opt_amount("Assurance Option VTT") > 0 or data.get("opt_Assurance Option VTT") == "Oui",
                amount_vtt=opt_amount("Assurance Option VTT") or float(data.get("opt_Montant Assurance Option VTT", 0.0) or 0.0),
                has_trail=opt_amount("Assurance Option Trail") > 0 or data.get("opt_Assurance Option Trail") == "Oui",
                amount_trail=opt_amount("Assurance Option Trail") or float(data.get("opt_Montant Assurance Option Trail", 0.0) or 0.0),
            )
        else:
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

        return cls(
            order_ref=str(data.get("order_ref") or ""),
            order_date=str(data.get("order_date") or ""),
            status=str(data.get("status") or ""),
            tarif_name=str(data.get("tarif_name") or "").strip(),
            amount=float(data.get("amount", 0.0) or 0.0),
            user_last_name=str(pick("last_name", "user_lastName")).strip(),
            user_first_name=str(pick("first_name", "user_firstName")).strip(),
            payer_first_name=str(pick("payer_first_name", "payer_firstName")).strip(),
            payer_last_name=str(pick("payer_last_name", "payer_lastName")).strip(),
            payer_email=str(pick("payer_email", "payer_email_order")).strip(),
            birth_date=str(pick("champ_Date de naissance de l'adhérent", "birth_date", "birth_date_raw")).strip(),
            gender=str(pick("champ_Sexe", "gender")).strip(),
            nationality=str(pick("champ_Nationalité", "nationality")).strip(),
            address=str(pick("champ_Adresse : numéro et nom de rue", "address")).strip(),
            zip_code=clean_float_str(pick("champ_Code postal", "zip_code")),
            city=str(pick("champ_Ville", "city")).strip(),
            country=str(pick("champ_Pays", "country")).strip(),
            phone=str(pick("champ_Téléphone ", "phone")).strip(),
            primary_email=str(pick("champ_Adresse mail pour la réception des informations du club", "email_primary", "primary_email")).strip(),
            secondary_email=str(pick("champ_Deuxième adresse mail pour la réception des informations du club", "email_secondary", "secondary_email")).strip(),
            emergency_contact_name_1=str(pick("champ_Personne à prévenir en cas d'urgence - NOM  et PRENOM en majuscule", "emergency1_name", "emergency_contact_name_1")).strip(),
            emergency_contact_phone_1=str(pick("champ_Personne à prévenir en cas d'urgence - Téléphone", "emergency1_phone", "emergency_contact_phone_1")).strip(),
            emergency_contact_name_2=str(pick("champ_Parent 2  à prévenir en cas d'urgence - NOM ET PRENOM (en majuscule)", "emergency2_name", "emergency_contact_name_2")).strip(),
            emergency_contact_phone_2=str(pick("champ_Parent 2 - Numéro de téléphone portable", "emergency2_phone", "emergency_contact_phone_2")).strip(),
            photo_auth=str(pick("champ_En cas de prise de vue (Photo ou vidéo), j'autorise...", "photo_auth")).strip(),
            health_q_auth=str(pick("champ_Je m'engage à compléter mon questionnaire de santé...", "health_commitment", "health_q_auth")).strip(),
            is_tribe=str(pick("champ_Famille : nous sommes une tribu de 3...", "is_tribe")).strip(),
            licence_ffme=clean_float_str(pick("champ_Numéro de Licence FFME (6 chiffres)", "licence_ffme")),
            insurance=ins,
            is_modified=str(data.get("is_modified") or "Non").strip(),
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
            "is_modified": self.is_modified,
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
