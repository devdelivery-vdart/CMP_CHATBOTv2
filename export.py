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
from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer

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


def _to_display_str(value) -> str:
    """Shared by every export format: converts any non-primitive value
    (Decimal, date, etc.) to a plain string, and None to an empty
    string, so no writer chokes on a type it doesn't understand."""
    if value is None:
        return ""
    if isinstance(value, (int, float, str)):
        return str(value)
    return str(value)


def export_to_xlsx(columns, rows, base_filename: str = "results") -> tuple[str, str]:
    """
    Writes rows to a .xlsx file. Returns (file_id, filename) -- file_id is
    the random token used in the download URL, filename is the
    human-readable name shown to the user when they save it.

    The sheet is protected read-only (see _apply_read_only_protection
    below): every cell can be selected and copied, but not edited, and
    the sheet/workbook structure can't be renamed, deleted, or
    rearranged. This is a USABILITY guard (stops an accidental edit
    from being mistaken for real data later), not a security boundary
    -- see that function's docstring for why.

    IF YOU NEED SOMETHING THAT CAN'T BE CASUALLY RE-EDITED AT ALL,
    USE export_to_pdf() INSTEAD -- there is no way to make a .xlsx file
    genuinely tamper-proof while it remains a valid, openable Excel
    file (Excel's own Review tab removes sheet protection in a couple
    of clicks, with or without the password). A PDF has no equivalent
    one-click "unprotect" action, which is the real reason to reach for
    it when "can't be edited" needs to actually mean something.
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

    _apply_read_only_protection(wb, ws)

    file_id = uuid.uuid4().hex
    filename = f"{base_filename}.xlsx"
    filepath = os.path.join(DOWNLOAD_DIR, f"{file_id}.xlsx")
    wb.save(filepath)

    return file_id, filename


def _apply_read_only_protection(wb, ws) -> None:
    """
    Makes the exported report copy-able but not editable in Excel.

    HOW: openpyxl cells default to locked=True already -- "locked" only
    takes effect once sheet protection itself is switched on, which is
    what this function actually does. Selection (needed for copy/paste)
    is explicitly kept enabled -- it's a separate flag from "locked",
    and would otherwise be blocked too.

    WHAT THIS IS NOT: a security boundary. The protection password
    below is a fixed, non-secret string -- anyone with Excel's Review
    tab can remove it in a couple of clicks once they know it exists
    (or even guess a common default). Its only real purpose is
    friction against an ACCIDENTAL edit (a stray keystroke overwriting
    a cell before the file gets forwarded/archived) -- never rely on
    this to keep a genuinely sensitive export from being modified by
    someone who wants to modify it.

    WHY THE PASSWORD IS A FIXED, KNOWN STRING RATHER THAN RANDOMIZED
    PER FILE (a deliberate choice, not an oversight): since this was
    never meant to be real security, a fixed, documented password
    means someone with a legitimate reason to edit their own export
    (e.g. reformatting before forwarding it) can intentionally remove
    the protection themselves without needing to contact anyone.
    Randomizing it per-file would only add inconvenience for a
    legitimate use case, with zero actual security gain (protection
    removal in Excel/most tooling doesn't meaningfully require knowing
    the real password anyway). If a download genuinely needs to resist
    casual editing, use export_to_pdf() instead of trying to harden this.

    NOT APPLIED TO CSV: export_to_csv() has no equivalent -- CSV is
    plain text with no protection concept at the file-format level, so
    "read-only export" is an .xlsx-only capability. If the read-only
    property specifically matters for a given download, prefer
    export_to_xlsx() over export_to_csv() -- or export_to_pdf() if it
    needs to be meaningfully harder to alter than either.
    """
    ws.protection.sheet = True
    ws.protection.selectLockedCells = False    # False = selection NOT disabled -> copy still works
    ws.protection.selectUnlockedCells = False  # (there are no unlocked cells here, but stay consistent)
    ws.protection.password = "vdart-report"    # friction only -- see docstring; not a real secret

    # Also prevent renaming/deleting/reordering/inserting sheets, and
    # inserting/deleting rows or columns on this one.
    ws.protection.insertRows = True
    ws.protection.insertColumns = True
    ws.protection.deleteRows = True
    ws.protection.deleteColumns = True
    ws.protection.formatCells = True
    ws.protection.formatColumns = True
    ws.protection.formatRows = True

    wb.security.lockStructure = True


def export_to_pdf(columns, rows, base_filename: str = "results", title: str | None = None) -> tuple[str, str]:
    """
    Writes rows to a .pdf file as a formatted table. Returns
    (file_id, filename), same shape as export_to_xlsx.

    Use this instead of export_to_xlsx() specifically when "can't be
    casually edited" needs to actually be true -- see
    _apply_read_only_protection's docstring for why xlsx protection
    doesn't provide that. A PDF has no built-in one-click "make this
    editable again" action the way a protected Excel sheet does, which
    is the real (still not absolute -- a PDF CAN be edited with the
    right tools, just with meaningfully more friction) reason to prefer
    it here.

    Layout notes:
    - Landscape orientation by default, since staffing query results
      commonly have more columns than a portrait page comfortably fits.
    - Every cell is wrapped in a Paragraph (not a bare string) so long
      values wrap onto multiple lines instead of silently overflowing
      or getting clipped -- this matters here specifically because
      recruiter/client names and masked emails vary a lot in length.
    - The header row repeats on every page (repeatRows=1 in the Table
      constructor) so a long result set spanning several pages never
      loses its column labels partway through.
    """
    _cleanup_old_files()

    styles = getSampleStyleSheet()
    cell_style = ParagraphStyle(
        "ExportCell", parent=styles["Normal"], fontSize=7.5, leading=9,
    )
    header_style = ParagraphStyle(
        "ExportHeader", parent=styles["Normal"], fontSize=8, leading=10,
        textColor=colors.white, fontName="Helvetica-Bold",
    )

    table_data = []
    if columns:
        table_data.append([Paragraph(_to_display_str(c), header_style) for c in columns])
    for row in rows:
        table_data.append([Paragraph(_to_display_str(v), cell_style) for v in row])

    doc_elements = []
    if title:
        doc_elements.append(Paragraph(title, styles["Title"]))
        doc_elements.append(Spacer(1, 0.2 * inch))

    if table_data:
        num_cols = len(table_data[0])
        table = Table(table_data, repeatRows=1 if columns else 0)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1d73d5")),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#c9d6e0")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f8fb")]),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        doc_elements.append(table)
    else:
        doc_elements.append(Paragraph("No results to display.", styles["Normal"]))

    file_id = uuid.uuid4().hex
    filename = f"{base_filename}.pdf"
    filepath = os.path.join(DOWNLOAD_DIR, f"{file_id}.pdf")

    doc = SimpleDocTemplate(
        filepath,
        pagesize=landscape(letter),
        leftMargin=0.4 * inch, rightMargin=0.4 * inch,
        topMargin=0.4 * inch, bottomMargin=0.4 * inch,
    )
    doc.build(doc_elements)

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