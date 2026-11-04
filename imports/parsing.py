"""Bounded, data-only ingestion. No formulas, macros, or external links evaluated."""
import csv
from datetime import date, datetime
from hashlib import sha256
from io import BytesIO, StringIO
from pathlib import PurePath
from zipfile import BadZipFile, ZipFile

from django.conf import settings
from django.core.exceptions import ValidationError
from openpyxl import load_workbook

REQUIRED = ("question_number", "question_text", "option_a", "option_b", "option_c", "option_d", "correct_answer", "subject", "language")
OPTIONAL = ("explanation", "topic", "exam_categories", "previous_year_tags", "source_document", "source_page", "difficulty_level", "review_status", "verification_notes", "comments", "created_date", "updated_date", "updated_by")
COLUMNS = REQUIRED + OPTIONAL
MAX_CELL = 32000


def text(value):
    if value is None:
        return ""
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if not isinstance(value, (str, int, float, bool)):
        raise ValidationError("Unsupported spreadsheet cell type.")
    value = str(value)
    if len(value) > MAX_CELL:
        raise ValidationError(f"Cells must not exceed {MAX_CELL} characters.")
    return value


def parse_upload(upload, worksheet=""):
    data = upload.read(settings.IMPORT_MAX_UPLOAD_BYTES + 1)
    if not data or len(data) > settings.IMPORT_MAX_UPLOAD_BYTES:
        raise ValidationError("Upload a nonempty file no larger than 5 MB.")
    filename = PurePath(upload.name.replace("\\", "/")).name
    extension = filename.rsplit(".", 1)[-1].lower()
    selected = "CSV"
    try:
        if extension == "csv":
            decoded = data.decode("utf-8-sig")
            reader = csv.reader(StringIO(decoded, newline=""), strict=True)
            table = []
            for row in reader:
                if len(row) > 32:
                    raise ValidationError("At most 32 spreadsheet columns are supported.")
                table.append([text(cell) for cell in row])
                if len(table) > settings.IMPORT_MAX_ROWS + 1:
                    raise ValidationError("At most 2000 data rows are supported.")
        elif extension == "xlsx":
            with ZipFile(BytesIO(data)) as archive:
                entries = archive.infolist()
                if len(entries) > 1000 or sum(item.file_size for item in entries) > 30 * 1024 * 1024:
                    raise ValidationError("Workbook expands beyond the safe processing limit.")
                if any("vbaproject" in item.filename.lower() or "externallinks/" in item.filename.lower() for item in entries):
                    raise ValidationError("Macro and external-link workbooks are not supported.")
            book = load_workbook(BytesIO(data), read_only=True, data_only=False, keep_links=False)
            try:
                if not worksheet and len(book.sheetnames) != 1:
                    raise ValidationError("Select a worksheet by name: " + ", ".join(book.sheetnames))
                selected = worksheet or book.sheetnames[0]
                if selected not in book.sheetnames:
                    raise ValidationError("Unknown worksheet. Available: " + ", ".join(book.sheetnames))
                sheet = book[selected]
                sheet.reset_dimensions()
                table = []
                for cells in sheet.iter_rows():
                    if len(cells) > 32:
                        raise ValidationError("At most 32 spreadsheet columns are supported.")
                    if any(cell.data_type in {"f", "e"} for cell in cells):
                        raise ValidationError("Replace spreadsheet formulas/errors with plain values.")
                    table.append([text(cell.value) for cell in cells])
                    if len(table) > settings.IMPORT_MAX_ROWS + 1:
                        raise ValidationError("At most 2000 data rows are supported.")
            finally:
                book.close()
        else:
            raise ValidationError("Only UTF-8 CSV and .xlsx files are supported.")
    except (UnicodeDecodeError, csv.Error, BadZipFile, OSError, ValueError, KeyError) as error:
        raise ValidationError("The file could not be parsed. Use a valid UTF-8 CSV or XLSX workbook.") from error
    if len(table) < 2:
        raise ValidationError("The file needs headers and at least one data row.")
    headers = [cell.strip().lower() for cell in table[0]]
    named = [header for header in headers if header]
    if len(set(named)) != len(named):
        raise ValidationError("Duplicate column headers are not allowed.")
    missing = set(REQUIRED) - set(headers)
    unknown = set(named) - set(COLUMNS)
    if missing or unknown:
        raise ValidationError(f"Missing headers: {', '.join(sorted(missing)) or 'none'}. Unknown headers: {', '.join(sorted(unknown)) or 'none'}.")
    rows = []
    for number, cells in enumerate(table[1:], 2):
        if not any(cell.strip() for cell in cells):
            continue
        if any(value.strip() for value in cells[len(headers):]):
            raise ValidationError(f"Row {number}: values extend beyond the named columns.")
        row = dict.fromkeys(COLUMNS, "")
        for index, value in enumerate(cells[:len(headers)]):
            if not headers[index] and value.strip():
                raise ValidationError(f"Row {number}: unnamed columns must be empty.")
            if headers[index]:
                row[headers[index]] = value
        rows.append({"source_row": number, "values": row})
    if not rows:
        raise ValidationError("No data rows were found.")
    return {"filename": filename[:255], "file_sha256": sha256(data).hexdigest(), "worksheet": selected, "rows": rows}
