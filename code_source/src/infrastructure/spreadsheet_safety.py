"""
Spreadsheet formula injection protection for generated Excel and CSV files.

Member data comes from the public HelloAsso form: a value such as `=HYPERLINK(...)`
or `=WEBSERVICE(...)` would be stored as a formula by openpyxl (any string starting
with "=") and evaluated when a volunteer opens the file, which can exfiltrate the
other rows. The application never writes formulas on purpose, so generated
workbooks are forced to plain text, except the formulas of the template they were
built from (snapshot taken right after loading it).
"""
import re
from typing import Any, FrozenSet, Tuple

# Leading characters that make Excel / LibreOffice evaluate a CSV cell
_CSV_TRIGGERS = ("=", "+", "-", "@", "\t", "\r")
# Signed numbers and phone numbers ("+33 6 12 34 56 78", "-12.5") stay as they are
_PLAIN_SIGNED = re.compile(r"^[+-][\d\s().,]*$")


def _formula_cells(workbook):
    for ws in workbook.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                if cell.data_type == "f":
                    yield cell


def template_formulas(workbook) -> FrozenSet[Tuple[str, str]]:
    """Formulas of a freshly loaded template, as (coordinate, formula) pairs.

    Keyed by coordinate rather than sheet name so formulas survive sheet copies."""
    return frozenset((cell.coordinate, str(cell.value)) for cell in _formula_cells(workbook))


def neutralize_formulas(workbook, keep: FrozenSet[Tuple[str, str]] = frozenset()) -> None:
    """Every formula cell not listed in `keep` becomes text (displayed value unchanged)."""
    for cell in _formula_cells(workbook):
        if (cell.coordinate, str(cell.value)) not in keep:
            cell.data_type = "s"


def safe_to_excel(df, path, **kwargs) -> None:
    """DataFrame.to_excel without formula evaluation (openpyxl engine)."""
    import pandas as pd

    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        df.to_excel(writer, **kwargs)
        neutralize_formulas(writer.book)


def csv_safe(value: Any) -> Any:
    """Prefixes a CSV value with an apostrophe when a spreadsheet would evaluate it."""
    if not isinstance(value, str) or not value.startswith(_CSV_TRIGGERS):
        return value
    if _PLAIN_SIGNED.match(value):
        return value
    return "'" + value
