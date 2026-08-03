"""
Turns a query result (columns + rows) into a downloadable file.

Kept separate from db.py / llm.py deliberately -- this module only ever
touches data that has ALREADY passed through the masked view and the
safety gate. It never queries the database itself, so it can't become a
way to bypass masking.
"""

import csv
import io
import os
import uuid

from openpyxl import Workbook

# Where generated files are temporarily stored before download.
DOWNLOAD_DIR = os.path.join(os.path.dirname(__file__), "webapp", "downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

MAX_AGE_SECONDS = 60 * 60 * 6  # auto-cleanup files older than 6 hours


def _cleanup_old_files():
    import time
    now = time.time()
    for fname in os.listdir(DOWNLOAD_DIR):
        fpath = os.path.join(DOWNLOAD_DIR, fname)
        try:
            if now - os.path.getmtime(fpath) > MAX_AGE_SECONDS:
                os.remove(fpath)
        except OSError:
            pass


def export_to_xlsx(columns, rows, base_filename: str = "results") -> tuple[str, str]:
    """
    Writes rows to a .xlsx file. Returns (file_id, filename) -- file_id is
    the random token used in the download URL, filename is the
    human-readable name shown to the user when they save it.
    """
    _cleanup_old_files()

    wb = Workbook()
    ws = wb.active
    ws.title = "Results"

    if columns:
        ws.append(list(columns))
    for row in rows:
        # Convert any non-primitive types (e.g. Decimal, date) to strings
        # so openpyxl doesn't choke on unsupported types.
        safe_row = [str(v) if not isinstance(v, (int, float, str, type(None))) else v for v in row]
        ws.append(safe_row)

    # Light auto-fit: cap column width at something reasonable.
    for col_cells in ws.columns:
        length = max((len(str(c.value)) if c.value is not None else 0) for c in col_cells)
        col_letter = col_cells[0].column_letter
        ws.column_dimensions[col_letter].width = min(max(length + 2, 10), 40)

    file_id = uuid.uuid4().hex
    filename = f"{base_filename}.xlsx"
    filepath = os.path.join(DOWNLOAD_DIR, f"{file_id}.xlsx")
    wb.save(filepath)

    return file_id, filename


def export_to_csv(columns, rows, base_filename: str = "results") -> tuple[str, str]:
    """Same idea as export_to_xlsx, but writes a plain .csv file."""
    _cleanup_old_files()

    file_id = uuid.uuid4().hex
    filename = f"{base_filename}.csv"
    filepath = os.path.join(DOWNLOAD_DIR, f"{file_id}.csv")

    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if columns:
            writer.writerow(columns)
        writer.writerows(rows)

    return file_id, filename


def resolve_download_path(file_id: str, extension: str) -> str | None:
    """Given a file_id from a previous export, returns the real filepath
    if it still exists (may have been auto-cleaned up after MAX_AGE_SECONDS)."""
    path = os.path.join(DOWNLOAD_DIR, f"{file_id}.{extension}")
    return path if os.path.isfile(path) else None
