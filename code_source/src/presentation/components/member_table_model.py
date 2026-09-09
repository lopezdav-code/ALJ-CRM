from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QColor
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
        ("Déjà adhérent", "already_member"),
        ("Alerte", "warning")  # ⚠️ Conflit d'âge / bornes de naissance du groupe
    ]

    # Fond ambre clair pour signaler visuellement une anomalie d'âge
    WARNING_BACKGROUND = QColor("#FEF3C7")
    WARNING_FOREGROUND = QColor("#B45309")

    def __init__(self, members: List[Member] = None, parent=None):
        super().__init__(parent)
        self.members: List[Member] = members or []
        self._planning_data = None       # Cache du planning (bornes de naissance par groupe)
        self._tarif_to_item = {}         # tarif HelloAsso -> créneau du planning
        self._warning_cache = {}         # (tarif, date de naissance) -> liste de messages

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self.members)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(self.COLUMNS)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole) -> Any:
        if role == Qt.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.COLUMNS[section][0]
        return None

    def _ensure_planning(self):
        """Charge (une fois) le planning depuis SQLite pour connaître les bornes de naissance."""
        if self._planning_data is None:
            try:
                from infrastructure.sqlite_repository import SqliteRepository
                self._planning_data = SqliteRepository.load_planning_data(log_debug=False) or []
            except Exception as e:
                print(f"⚠️ [TABLE_ADHERENTS] Impossible de charger le planning pour le contrôle d'âge : {e}")
                self._planning_data = []
            self._tarif_to_item = {}
            for item in self._planning_data:
                for t in item.get("helloasso_tarifs", []) or []:
                    self._tarif_to_item.setdefault(str(t).strip().lower(), item)

    def get_member_warnings(self, member: Member) -> list:
        """Retourne les messages d'incohérence d'âge d'un adhérent (liste vide = conforme)."""
        cache_key = (str(member.tarif_name or "").strip(), str(member.birth_date or "").strip())
        if cache_key not in self._warning_cache:
            self._ensure_planning()
            try:
                from domain.age_rules import check_age_conflict, find_planning_item_for_tarif
                planning_item = self._tarif_to_item.get(cache_key[0].lower())
                self._warning_cache[cache_key] = check_age_conflict(
                    member.birth_date, member.tarif_name, planning_item
                )
            except Exception as e:
                print(f"⚠️ [TABLE_ADHERENTS] Erreur du contrôle d'âge : {e}")
                self._warning_cache[cache_key] = []
        return self._warning_cache[cache_key]

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
                
            if col_name == "warning":
                # Alerte ⚠️ en cas d'incohérence d'âge (adulte dans un groupe enfants /
                # collège / lycée, ou année de naissance hors bornes du groupe)
                warnings = self.get_member_warnings(member)
                if warnings:
                    return "⚠️"
                return ""

            return getattr(member, col_name, "")

        elif role == Qt.ToolTipRole:
            if col_name == "tarif_name":
                return ("Double-cliquez sur cette cellule pour changer de groupe (tarif)\n"
                        "parmi les tarifs disponibles de la saison active.")
            if col_name == "warning":
                warnings = self.get_member_warnings(member)
                if warnings:
                    return "Contrôle d'âge :\n" + "\n".join(f"• {w}" for w in warnings)
                return "Aucun problème d'âge détecté pour ce tarif."
            return None

        elif role == Qt.BackgroundRole:
            if col_name == "warning" and self.get_member_warnings(member):
                return self.WARNING_BACKGROUND
            return None

        elif role == Qt.ForegroundRole:
            if col_name == "warning" and self.get_member_warnings(member):
                return self.WARNING_FOREGROUND
            return None

        elif role == Qt.TextAlignmentRole:
            if col_name in ("licence_ffme", "amount", "order_date", "already_member", "diplome", "warning"):
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
        """Met à jour les données de la table (et rafraîchit le cache du contrôle d'âge)."""
        self.beginResetModel()
        self.members = new_members
        self._warning_cache = {}
        self._planning_data = None  # Forcer le rechargement du planning (bornes potentiellement modifiées)
        self.endResetModel()
