from typing import List, Tuple

import pandas as pd
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.utils import get_column_letter
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

STATUSES = "Not Applied,Applied,Interview,Offer,Rejected"
WIDTHS = {"Job Title": 42, "Company": 28, "Location": 26, "Salary": 22, "Matched Skills": 30,
          "Skill Gaps": 30, "Skills Mentioned": 34, "Job URL Link": 40, "Follow-up Notes": 36}


def _clean(v):
    return ILLEGAL_CHARACTERS_RE.sub("", v) if isinstance(v, str) else v


def write_xlsx(out: pd.DataFrame, funnel: List[Tuple[str, int]], warnings: List[str], path: str) -> None:
    out = out.apply(lambda col: col.map(_clean) if col.dtype == object else col)
    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        out.to_excel(xw, sheet_name="Jobs", index=False)
        info = pd.DataFrame(funnel, columns=["Stage", "Jobs remaining"])
        info.to_excel(xw, sheet_name="Search Info", index=False)
        if warnings:
            pd.DataFrame({"Warnings": warnings}).to_excel(xw, sheet_name="Search Info", index=False,
                                                          startcol=3)
        ws = xw.sheets["Jobs"]
        n = len(out)
        header_fill = PatternFill("solid", start_color="1F3A5F")
        for i, col in enumerate(out.columns, start=1):
            cell = ws.cell(row=1, column=i)
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = header_fill
            cell.alignment = Alignment(vertical="center", wrap_text=True)
            ws.column_dimensions[get_column_letter(i)].width = WIDTHS.get(col, 16)
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions

        url_col = list(out.columns).index("Job URL Link") + 1
        for r in range(2, n + 2):
            c = ws.cell(row=r, column=url_col)
            if c.value:
                c.hyperlink = str(c.value)
                c.style = "Hyperlink"

        status_col = get_column_letter(list(out.columns).index("Application Status") + 1)
        dv = DataValidation(type="list", formula1=f'"{STATUSES}"', allow_blank=True)
        ws.add_data_validation(dv)
        dv.add(f"{status_col}2:{status_col}{max(n + 1, 2)}")
        xw.sheets["Search Info"].column_dimensions["A"].width = 28
        xw.sheets["Search Info"].column_dimensions["D"].width = 90


def to_csv_bytes(out: pd.DataFrame) -> bytes:
    return out.to_csv(index=False).encode("utf-8-sig")   # BOM so Excel reads UTF-8 correctly
