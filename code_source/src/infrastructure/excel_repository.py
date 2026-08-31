import os
import glob
import datetime
import json
import time
import pandas as pd
from paths import CODE_ROOT, ROOT_DIR
from domain.constants import (
    get_drive_temp_filename,
    get_corrective_files_pattern,
    get_save_filename_template
)

# Phase 3 - mapping canonique unique (import depuis domain.constants)
from domain.constants import CORRECTIVE_MAP

class ExcelRepository:
    """
    Gère la persistence locale et la mise en forme de la base de données Excel des adhérents.
    """

    @staticmethod
    def parse_date_to_datetime(val):
        """Parse un format de date d'Excel ou HelloAsso en objet datetime ou conserve la valeur brute."""
        if not val or pd.isna(val):
            return ""
        if hasattr(val, "to_pydatetime"):
            return val.to_pydatetime()
        if isinstance(val, (datetime.datetime, datetime.date)):
            if isinstance(val, datetime.date) and not isinstance(val, datetime.datetime):
                return datetime.datetime(val.year, val.month, val.day)
            return val
            
        val_str = str(val).strip()
        if not val_str:
            return ""
            
        for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%d/%m/%Y %H:%M:%S", "%d/%m/%y", "%Y-%m-%d %H:%M:%S"):
            try:
                if "T" in val_str and fmt == "%Y-%m-%dT%H:%M:%S":
                    return datetime.datetime.strptime(val_str[:19], fmt)
                return datetime.datetime.strptime(val_str, fmt)
            except Exception:
                pass
        return val_str

    @classmethod
    def load_direct_data(cls, file_path: str) -> list:
        """
        Charge de manière brute le contenu d'un fichier Excel d'adhésion et le renvoie comme liste d'adhérents.
        Utilise SQLite en arrière-plan comme source de vérité.
        """
        from infrastructure.sqlite_repository import SqliteRepository
        return SqliteRepository.load_direct_data(file_path)

    @staticmethod
    def sanitize_for_excel(rows) -> list:
        """Nettoie les types complexes (listes, NaN, etc.) pour prévenir les plantages COM Excel."""
        import math
        sanitized_rows = []
        for row in rows:
            sanitized_row = []
            for val in row:
                if val is None:
                    new_val = ""
                elif isinstance(val, (list, tuple, set)):
                    new_val = ", ".join(str(x) for x in val)
                elif isinstance(val, dict):
                    new_val = json.dumps(val, ensure_ascii=False)
                elif pd.isna(val):
                    new_val = ""
                elif isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
                    new_val = ""
                elif hasattr(val, "to_pydatetime") or isinstance(val, (datetime.datetime, datetime.date)):
                    try:
                        if hasattr(val, "to_pydatetime"):
                            dt_val = val.to_pydatetime()
                        elif isinstance(val, datetime.date) and not isinstance(val, datetime.datetime):
                            dt_val = datetime.datetime(val.year, val.month, val.day)
                        else:
                            dt_val = val
                        
                        if hasattr(dt_val, "tzinfo") and dt_val.tzinfo is not None:
                            dt_val = dt_val.replace(tzinfo=None)
                        
                        epoch = datetime.datetime(1899, 12, 30)
                        delta = dt_val - epoch
                        new_val = delta.days + (delta.seconds + delta.microseconds / 1000000.0) / 86400.0
                    except Exception:
                        new_val = ""
                elif "numpy" in str(type(val)):
                    type_name = type(val).__name__
                    if "int" in type_name:
                        new_val = int(val)
                    elif "float" in type_name:
                        try:
                            f_val = float(val)
                            if math.isnan(f_val) or math.isinf(f_val):
                                new_val = ""
                            else:
                                new_val = f_val
                        except Exception:
                            new_val = ""
                    else:
                        new_val = str(val)
                elif isinstance(val, (list, tuple, set)):
                    new_val = ", ".join(str(x) for x in val)
                elif isinstance(val, dict):
                    new_val = json.dumps(val, ensure_ascii=False)
                elif not isinstance(val, (str, int, float, bool)):
                    new_val = str(val)
                else:
                    new_val = val
                sanitized_row.append(new_val)
            sanitized_rows.append(sanitized_row)
        return sanitized_rows

    @classmethod
    def update_member_in_excel(cls, latest_file: str, original_order_ref: str, original_last_name: str, original_first_name: str, updated_fields: dict, comment_text: str):
        """
        Met à jour de manière chirurgicale un adhérent dans la base de données.
        Surcharge de update_member_in_excel pour rediriger vers SqliteRepository.
        """
        from infrastructure.sqlite_repository import SqliteRepository
        return SqliteRepository.update_member_in_excel(
            latest_file, original_order_ref, original_last_name, original_first_name, updated_fields, comment_text
        )
