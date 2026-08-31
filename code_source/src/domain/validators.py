import re
from typing import Any

EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")

def validate_amount(val: Any) -> float:
    """
    Convertit et valide un montant financier de manière extrêmement robuste.
    Gère les virgules, les espaces, les symboles de devises et les valeurs vides.
    """
    if val is None:
        return 0.0
        
    if isinstance(val, (int, float)):
        return float(val)
        
    # S'il s'agit d'une chaîne de caractères, on la nettoie
    val_str = str(val).strip()
    if not val_str:
        return 0.0
        
    # Retirer les symboles de monnaie classiques
    val_str = val_str.replace("€", "").replace("EUR", "").replace("eur", "").strip()
    
    # Remplacer les virgules par des points et nettoyer les espaces internes
    val_str = val_str.replace(",", ".").replace(" ", "")
    
    try:
        return float(val_str)
    except ValueError as e:
        raise ValueError(
            f"Le montant '{val}' n'est pas un nombre valide. "
            f"Veuillez entrer un nombre décimal correct (ex: 246.50 ou 246,50)."
        ) from e

def validate_email(email_str: Any) -> str:
    """
    Valide et normalise une adresse e-mail.
    Retourne l'adresse nettoyée ou lève une exception claire.
    """
    if email_str is None:
        return ""
        
    email_clean = str(email_str).strip().lower()
    if not email_clean:
        return ""
        
    if not EMAIL_REGEX.match(email_clean):
        raise ValueError(
            f"L'adresse e-mail '{email_str}' est invalide. "
            f"Elle doit respecter le format standard (ex: nom@domaine.com)."
        )
        
    return email_clean
