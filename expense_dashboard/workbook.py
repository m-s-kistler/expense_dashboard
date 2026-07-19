from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from zipfile import ZipFile
import re
from xml.etree import ElementTree as ET

import pandas as pd


WORKBOOK_PATH = Path("Finance Dashboard and Annual Budget System.xlsx")
MONTH_SHEETS = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]

NS = {
    "main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
    "officeRel": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}


def _column_number(column: str) -> int:
    number = 0
    for char in column:
        number = number * 26 + ord(char) - 64
    return number


def _split_cell(reference: str) -> tuple[str, int]:
    match = re.match(r"([A-Z]+)(\d+)", reference)
    if not match:
        raise ValueError(f"Invalid cell reference: {reference}")
    return match.group(1), int(match.group(2))


def _shared_strings(archive: ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []

    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    return [
        "".join(text.text or "" for text in item.findall(".//main:t", NS))
        for item in root.findall("main:si", NS)
    ]


def _cell_text(cell: ET.Element, strings: list[str]) -> str:
    cell_type = cell.attrib.get("t")
    if cell_type == "s":
        value = cell.find("main:v", NS)
        return strings[int(value.text)] if value is not None and value.text else ""
    if cell_type == "inlineStr":
        return "".join(text.text or "" for text in cell.findall(".//main:t", NS))

    value = cell.find("main:v", NS)
    return value.text if value is not None and value.text else ""


def _sheet_target(archive: ZipFile, sheet_name: str) -> str:
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    relationship_map = {
        rel.attrib["Id"]: rel.attrib["Target"]
        for rel in relationships.findall("rel:Relationship", NS)
    }

    for sheet in workbook.findall("main:sheets/main:sheet", NS):
        if sheet.attrib["name"] == sheet_name:
            relationship_id = sheet.attrib[
                "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
            ]
            target = relationship_map[relationship_id].lstrip("/")
            return target if target.startswith("xl/") else f"xl/{target}"

    raise KeyError(f"Sheet not found: {sheet_name}")


def _excel_date(value: object) -> str | None:
    if value is None or value == "":
        return None
    try:
        serial = float(value)
    except (TypeError, ValueError):
        parsed = pd.to_datetime(value, errors="coerce")
        if pd.isna(parsed):
            return None
        return parsed.strftime("%Y-%m-%d")

    # Excel serial dates use 1899-12-30 as the practical origin.
    return (datetime(1899, 12, 30) + timedelta(days=serial)).strftime("%Y-%m-%d")


def _money(value: object) -> float | None:
    if value is None or value == "":
        return None
    text = str(value).replace(",", "").replace("$", "").strip()
    try:
        return round(abs(float(text)), 2)
    except ValueError:
        return None


def extract_month_transactions(
    workbook_path: str | Path = WORKBOOK_PATH,
) -> pd.DataFrame:
    rows = []
    workbook_path = Path(workbook_path)

    with ZipFile(workbook_path) as archive:
        strings = _shared_strings(archive)
        for sheet_name in MONTH_SHEETS:
            root = ET.fromstring(archive.read(_sheet_target(archive, sheet_name)))
            row_cells: dict[int, dict[str, str]] = {}

            for cell in root.findall(".//main:sheetData/main:row/main:c", NS):
                reference = cell.attrib.get("r")
                if not reference:
                    continue
                column, row_number = _split_cell(reference)
                if 68 <= row_number <= 1001 and column in {"E", "H", "I", "L", "O"}:
                    row_cells.setdefault(row_number, {})[column] = _cell_text(cell, strings)

            for row_number, cells in sorted(row_cells.items()):
                date = _excel_date(cells.get("E"))
                amount = _money(cells.get("H"))
                category_type = str(cells.get("I", "")).strip()
                category = str(cells.get("L", "")).strip()
                description = str(cells.get("O", "")).strip()

                if not date or amount is None or not category_type or not category:
                    continue

                rows.append(
                    {
                        "month": sheet_name,
                        "workbook_row": row_number,
                        "date": date,
                        "amount": amount,
                        "category_type": category_type,
                        "category": category,
                        "description": description,
                    }
                )

    return pd.DataFrame(rows)


def _sheet_cells(archive: ZipFile, sheet_name: str) -> dict[str, str]:
    strings = _shared_strings(archive)
    root = ET.fromstring(archive.read(_sheet_target(archive, sheet_name)))
    cells = {}
    for cell in root.findall(".//main:sheetData/main:row/main:c", NS):
        reference = cell.attrib.get("r")
        if reference:
            cells[reference] = _cell_text(cell, strings)
    return cells


def extract_setup_obligations(
    workbook_path: str | Path = WORKBOOK_PATH,
) -> pd.DataFrame:
    rows = []
    workbook_path = Path(workbook_path)

    with ZipFile(workbook_path) as archive:
        cells = _sheet_cells(archive, "Setup")

    for row_number in range(7, 28):
        name = str(cells.get(f"B{row_number}", "")).strip()
        if not name or name == "Total":
            continue
        rows.append(
            {
                "category_type": "Income",
                "name": name,
                "month": None,
                "due_day": None,
                "expected_amount": _money(cells.get(f"E{row_number}")) or 0.0,
                "sort_order": row_number,
            }
        )

    for row_number in range(7, 52):
        name = str(cells.get(f"H{row_number}", "")).strip()
        if not name or name == "Total":
            continue
        rows.append(
            {
                "category_type": "Variable Expenses",
                "name": name,
                "month": None,
                "due_day": None,
                "expected_amount": _money(cells.get(f"M{row_number}")) or 0.0,
                "sort_order": row_number,
            }
        )

    for row_number in range(57, 77):
        name = str(cells.get(f"B{row_number}", "")).strip()
        if not name or name == "Total":
            continue
        rows.append(
            {
                "category_type": "Savings",
                "name": name,
                "month": None,
                "due_day": None,
                "expected_amount": _money(cells.get(f"E{row_number}")) or 0.0,
                "sort_order": row_number,
            }
        )

    for row_number in range(7, 52):
        name = str(cells.get(f"R{row_number}", "")).strip()
        if not name or name == "Total":
            continue
        rows.append(
            {
                "category_type": "Monthly Bills",
                "name": name,
                "month": None,
                "due_day": _money(cells.get(f"W{row_number}")),
                "expected_amount": _money(cells.get(f"Y{row_number}")) or 0.0,
                "sort_order": row_number,
            }
        )

    for row_number in range(82, 102):
        name = str(cells.get(f"B{row_number}", "")).strip()
        if not name:
            continue
        rows.append(
            {
                "category_type": "Debt",
                "name": name,
                "month": None,
                "due_day": _money(cells.get(f"F{row_number}")),
                "expected_amount": _money(cells.get(f"I{row_number}")) or 0.0,
                "balance": _money(cells.get(f"K{row_number}")) or 0.0,
                "minimum_payment": _money(cells.get(f"Q{row_number}")) or 0.0,
                "interest_rate": float(cells.get(f"V{row_number}") or 0),
                "sort_order": row_number,
            }
        )

    non_monthly_columns = {
        "January": ("F", "I"),
        "February": ("J", "M"),
        "March": ("R", "U"),
        "April": ("V", "Y"),
        "May": ("Z", "AB"),
        "June": ("AC", "AE"),
        "July": ("AF", "AH"),
        "August": ("AI", "AK"),
        "September": ("AL", "AN"),
        "October": ("AO", "AQ"),
        "November": ("AR", "AT"),
        "December": ("AU", "AW"),
    }
    for row_number in range(110, 131):
        name = str(cells.get(f"B{row_number}", "")).strip()
        if not name or name == "Total":
            continue
        for month_index, (month, (due_column, amount_column)) in enumerate(
            non_monthly_columns.items(),
            start=1,
        ):
            due_day = _money(cells.get(f"{due_column}{row_number}"))
            expected_amount = _money(cells.get(f"{amount_column}{row_number}")) or 0.0
            if due_day is None and expected_amount == 0:
                continue
            rows.append(
                {
                    "category_type": "Non-Monthly Bills",
                    "name": name,
                    "month": month,
                    "due_day": due_day,
                    "expected_amount": expected_amount,
                    "sort_order": (month_index * 1000) + row_number,
                }
            )

    return pd.DataFrame(rows)
