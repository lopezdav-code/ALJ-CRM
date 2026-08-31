from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from typing import List, Any
from domain.models import Member

class MemberTableModel(QAbstractTableModel):
    """
    Modèle de table hautes performances pour l'affichage, le tri et le filtrage des adhérents.
    """
    COLUMNS = [
        ("N° Licence FFME", "licence_ffme"),
        ("Nom", "user_last_name"),
        ("Prénom", "user_first_name"),
        ("Tarif", "tarif_name"),
        ("Montant", "amount"),
        ("Date d'inscription", "order_date"),
        ("Diplômes/Autonomie", "diplome"),  # Nouvelle colonne de pictogrammes d'autonomie (Nouveau !)
        ("Statut", "status"),
        ("Déjà adhérent", "already_member")
    ]

    def __init__(self, members: List[Member] = None, parent=None):
        super().__init__(parent)
        self.members: List[Member] = members or []

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self.members)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(self.COLUMNS)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole) -> Any:
        if role == Qt.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.COLUMNS[section][0]
        return None

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        if not index.isValid() or not (0 <= index.row() < len(self.members)):
            return None

        member = self.members[index.row()]
        col_name = self.COLUMNS[index.column()][1]

        if role == Qt.DisplayRole:
            if col_name == "user_last_name":
                val = getattr(member, col_name, "")
                return str(val).strip().title() if val else ""
                
            if col_name == "user_first_name":
                val = getattr(member, col_name, "")
                return str(val).strip().title() if val else ""
                
            if col_name == "amount":
                return f"{member.amount:.2f} €"
                
            if col_name == "order_date":
                # Formater joliment la date d'inscription au format FR
                import pandas as pd
                try:
                    dt = pd.to_datetime(member.order_date)
                    if pd.notna(dt):
                        return dt.strftime("%d/%m/%Y")
                except Exception:
                    pass
                    
            if col_name == "diplome":
                # Construire les pictogrammes d'autonomie / passeport Orange (Nouveau !)
                icons = []
                # 1. Badge rouge (🔴)
                badge_rouge_val = str(getattr(member, "badge_rouge", "")).strip().lower()
                if badge_rouge_val == "oui":
                    icons.append("🔴")
                # 2. Autonomie bloc (🧱)
                autonomie_bloc_val = str(getattr(member, "autonomie_bloc", "")).strip().lower()
                if autonomie_bloc_val == "oui":
                    icons.append("🧱")
                # 3. Passeport Orange (🍊)
                passports_raw = str(getattr(member, "raw_passports", "")).strip().lower()
                if "orange" in passports_raw:
                    icons.append("🍊")
                    
                if icons:
                    return "  ".join(icons)
                return ""
                
            return getattr(member, col_name, "")
            
        elif role == Qt.TextAlignmentRole:
            if col_name in ("licence_ffme", "amount", "order_date", "already_member", "diplome"):
                return Qt.AlignmentFlag.AlignCenter
            return Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter

        elif role == Qt.EditRole:
            if col_name == "amount":
                try:
                    return float(member.amount)
                except Exception:
                    return 0.0
            if col_name == "order_date":
                import pandas as pd
                try:
                    dt = pd.to_datetime(member.order_date)
                    if pd.notna(dt):
                        return dt.strftime("%Y-%m-%d %H:%M:%S")
                except Exception:
                    pass
                return "1970-01-01 00:00:00"
            if col_name == "licence_ffme":
                val = str(getattr(member, "licence_ffme", "")).strip()
                try:
                    return int(val) if val else -1
                except ValueError:
                    return -1
            return getattr(member, col_name, "")

        elif role == Qt.UserRole:
            # Renvoyer l'objet complet pour le panneau latéral
            return member

        return None

    def sort(self, column: int, order: Qt.SortOrder = Qt.AscendingOrder):
        """Trie la table selon la colonne sélectionnée."""
        self.layoutAboutToBeChanged.emit()
        col_name = self.COLUMNS[column][1]
        
        reverse = (order == Qt.SortOrder.DescendingOrder)
        
        if col_name == "order_date":
            import pandas as pd
            import datetime
            def get_date_key(m):
                val = getattr(m, "order_date", None)
                if not val:
                    return pd.Timestamp.min
                try:
                    dt = pd.to_datetime(val)
                    if pd.notna(dt):
                        return dt
                except Exception:
                    pass
                return pd.Timestamp.min
            self.members.sort(key=get_date_key, reverse=reverse)
            
        elif col_name == "amount":
            def get_amount_key(m):
                try:
                    return float(getattr(m, "amount", 0.0))
                except Exception:
                    return 0.0
            self.members.sort(key=get_amount_key, reverse=reverse)
            
        elif col_name == "licence_ffme":
            def get_licence_key(m):
                val = str(getattr(m, "licence_ffme", "")).strip()
                try:
                    return int(val) if val else -1
                except ValueError:
                    return -1
            self.members.sort(key=get_licence_key, reverse=reverse)
            
        else:
            # Tri générique sur les attributs du modèle Member
            self.members.sort(key=lambda m: str(getattr(m, col_name, "")).lower(), reverse=reverse)
        
        self.layoutChanged.emit()

    def update_data(self, new_members: List[Member]):
        """Met à jour les données de la table."""
        self.beginResetModel()
        self.members = new_members
        self.endResetModel()
