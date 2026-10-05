"""AS9102 forms from a reviewed inspection, and their exports.

    Form 1  part number accountability     title block + project + reviewer input
    Form 2  product accountability         materials, special processes, functional tests
    Form 3  characteristic accountability  one row per balloon

Exports: an Excel workbook (one sheet per form), a PDF of the three forms, and
the drawing with its balloons drawn on. Until the inspection is signed every
export is stamped DRAFT.
"""
from __future__ import annotations

import os
import re
import textwrap
from datetime import datetime, timezone
from pathlib import Path

#: specifications a note can cite for a material or process
_SPEC = re.compile(r"\b(AMS[- ]?\d{4}[A-Z]?|AMS[- ]?QQ[- ]?[A-Z]-\d+|MIL[- ][A-Z]+[- ]\d+[A-Z]?|ASTM[- ]?[A-Z]\d+"
                   r"|SAE[- ]?[A-Z]+\d+|IS[- ]?\d{3,5}(?::\d{4})?|BS[- ]?\d{3,5}|DIN[- ]?\d{3,5}|NAS[- ]?\d+)\b", re.I)
_PROCESS_WORDS = re.compile(r"\b(HARDEN|HEAT[- ]TREAT|NITRID|CARBURI|ANODI[SZ]|PLAT(E|ED|ING)|PASSIVAT|PAINT|"
                            r"POWDER[- ]COAT|BLACKEN|PHOSPHAT|SHOT[- ]PEEN|WELD|BRAZ|NDT|PENETRANT|MAGNETIC PARTICLE)",
                            re.I)
_DRAWING_STANDARDS = {"ISO 2768", "ISO 1101", "ISO 8015", "ASME Y14.5", "ISO 1302", "ISO 128", "ISO 286",
                      "ISO 21920", "BS 8888", "IS 919", "IS 2102"}


#: Unicode TTFs for the PDF exports (Base-14 Helvetica has no Ø, ≤, – or ⟂).
_FONT_CANDIDATES = [
    ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
    ("C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/segoeuib.ttf"),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ("/usr/share/fonts/dejavu/DejaVuSans.ttf", "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf"),
]
_ASCII = {"–": "-", "—": "-", "≤": "<=", "≥": ">=", "Ø": "DIA ", "⌀": "DIA ", "±": "+/-", "°": " deg", "µ": "u",
          "×": "x", "“": '"', "”": '"', "→": "->"}


def _fonts() -> tuple[str, str] | None:
    env = os.environ.get("FAI_PDF_FONT")
    cands = ([(env, os.environ.get("FAI_PDF_FONT_BOLD", env))] if env else []) + _FONT_CANDIDATES
    for reg, bold in cands:
        if reg and Path(reg).exists() and Path(bold).exists():
            return reg, bold
    return None


def _ascii(s: str) -> str:
    return "".join(_ASCII.get(ch, ch if ord(ch) < 128 else "?") for ch in s)


def form1(title: dict, project: dict, options: dict, signoff: dict | None) -> dict:
    return {
        "part_number": project.get("part_number") or title.get("drawing_number") or "",
        "part_name": project.get("part_name") or title.get("title") or "",
        "serial_number": options.get("serial_number", ""),
        "fai_report_number": options.get("fai_report_number", ""),
        "part_revision": title.get("revision") or options.get("revision", ""),
        "drawing_number": title.get("drawing_number") or "",
        "drawing_revision": title.get("revision") or "",
        "additional_changes": options.get("additional_changes", ""),
        "manufacturing_process_reference": options.get("process_reference", ""),
        "organization_name": options.get("organization", ""),
        "supplier_code": options.get("supplier_code", ""),
        "po_number": options.get("po_number", ""),
        "customer": project.get("customer", ""),
        "fai_type": options.get("fai_type", "Detail"),
        "fai_scope": options.get("fai_scope", "Full FAI"),
        "reason": options.get("reason", "New part"),
        "material": title.get("material") or "",
        "standard": options.get("standard", ""),
        "signed_by": (signoff or {}).get("name", ""),
        "signed_role": (signoff or {}).get("role", ""),
        "signed_at": (signoff or {}).get("at", ""),
    }


def form2(title: dict, notes: list[dict], bom_row: dict | None) -> list[dict]:
    rows = []
    if title.get("material"):
        m = title["material"]
        spec = (re.search(r"\(([^)]+)\)", m) or [None, ""])[1]
        rows.append({"type": "Material", "name": re.sub(r"\s*\(.*\)", "", m).strip(), "specification": spec,
                     "code": "", "supplier": "", "approval": "", "certificate": "", "source": "title block"})
    if title.get("finish"):
        rows.append({"type": "Special process", "name": title["finish"], "specification": "", "code": "",
                     "supplier": "", "approval": "", "certificate": "", "source": "title block"})
    for n in notes:
        text = re.sub(r"^\d+\.\s*", "", n["text"])
        specs = [s for s in _SPEC.findall(text) if s.upper() not in _DRAWING_STANDARDS]
        if _PROCESS_WORDS.search(text) or specs:
            rows.append({"type": "Special process" if _PROCESS_WORDS.search(text) else "Specification",
                         "name": text, "specification": ", ".join(specs), "code": "", "supplier": "", "approval": "",
                         "certificate": "", "source": f"note {n.get('number') or ''}".strip()})
    if bom_row and bom_row.get("material") and not any(r["type"] == "Material" for r in rows):
        rows.append({"type": "Material", "name": bom_row["material"], "specification": "", "code": "", "supplier": "",
                     "approval": "", "certificate": "", "source": "BOM / PO"})
    return rows


def form3(chars: list[dict]) -> list[dict]:
    out = []
    for c in chars:
        loc = f"Sheet {c['page'] + 1}" + (f", zone {c['zone']}" if c.get("zone") else "")
        out.append({"no": c["no"], "location": loc, "designator": c.get("key", ""), "requirement": c["requirement"],
                    "nominal": c.get("nominal"), "lower": c.get("lower"), "upper": c.get("upper"),
                    "results": c.get("result", ""),
                    "status": c.get("status", "open") if c.get("inspect", True) else "n/a (" + c["type"].lower() + ")",
                    "tooling": c.get("tooling", "") or c.get("method", ""), "nc_number": c.get("nc_number", ""),
                    "tol_source": c.get("tol_source", ""), "cad": c.get("cad_value"), "cad_status": c.get("cad_status", ""),
                    "inspect": c.get("inspect", True)})
    return out


def build(result: dict, project: dict, signoff: dict | None) -> dict:
    return {"form1": form1(result["title"], project, result.get("options", {}), signoff),
            "form2": form2(result["title"], result.get("notes", []), result.get("bom_row")),
            "form3": form3(result["characteristics"])}


# ------------------------------------------------------------------ exports

def write_xlsx(forms: dict, path: str | Path, draft: bool) -> Path:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, Side

    thin = Side(style="thin", color="000000")
    box = Border(left=thin, right=thin, top=thin, bottom=thin)
    wb = Workbook()
    ws = wb.active
    ws.title = "Form 1"
    ws.append(["AS9102 Form 1 — Part Number Accountability" + ("   [DRAFT — NOT SIGNED]" if draft else "")])
    ws["A1"].font = Font(bold=True, size=13)
    for k, v in forms["form1"].items():
        ws.append([k.replace("_", " ").capitalize(), v])
    ws.column_dimensions["A"].width = 34
    ws.column_dimensions["B"].width = 50

    ws2 = wb.create_sheet("Form 2")
    ws2.append(["AS9102 Form 2 — Product Accountability" + ("   [DRAFT]" if draft else "")])
    ws2["A1"].font = Font(bold=True, size=13)
    hdr2 = ["Type", "Material or process name", "Specification number", "Code", "Special process supplier code",
            "Customer approval verification", "Certificate of conformance number", "Read from"]
    ws2.append(hdr2)
    for r in forms["form2"]:
        ws2.append([r["type"], r["name"], r["specification"], r["code"], r["supplier"], r["approval"],
                    r["certificate"], r["source"]])
    ws2.append([])
    ws2.append(["Functional testing", "None identified on the drawing"])
    for col, w in zip("ABCDEFGH", (16, 44, 22, 10, 18, 18, 22, 14)):
        ws2.column_dimensions[col].width = w

    ws3 = wb.create_sheet("Form 3")
    ws3.append(["AS9102 Form 3 — Characteristic Accountability, Verification and Compatibility Evaluation"
                + ("   [DRAFT]" if draft else "")])
    ws3["A1"].font = Font(bold=True, size=13)
    hdr3 = ["Char. no.", "Reference location", "Characteristic designator", "Requirement", "Nominal", "Lower limit",
            "Upper limit", "Results", "Status", "Designed / qualified tooling", "Nonconformance number",
            "Tolerance from", "CAD measured", "CAD check"]
    ws3.append(hdr3)
    for r in forms["form3"]:
        ws3.append([r["no"], r["location"], r["designator"], r["requirement"], r["nominal"], r["lower"], r["upper"],
                    r["results"], r["status"], r["tooling"], r["nc_number"], r["tol_source"], r["cad"], r["cad_status"]])
    for col, w in zip("ABCDEFGHIJKLMN", (8, 18, 12, 52, 10, 11, 11, 16, 10, 24, 16, 14, 12, 12)):
        ws3.column_dimensions[col].width = w
    for sheet, hdr_row in ((ws2, 2), (ws3, 2)):
        for cell in sheet[hdr_row]:
            cell.font = Font(bold=True)
            cell.alignment = Alignment(wrap_text=True, vertical="top")
        for row in sheet.iter_rows(min_row=hdr_row, max_row=sheet.max_row):
            for cell in row:
                if cell.value is not None:
                    cell.border = box
    f1 = forms["form1"]
    ws3.append([])
    ws3.append(["Signature", f1.get("signed_by") or "—", "Role", f1.get("signed_role") or "—", "Date",
                f1.get("signed_at") or "—"])
    path = Path(path)
    wb.save(path)
    return path


def write_pdf(forms: dict, path: str | Path, draft: bool) -> Path:
    import pymupdf

    doc = pymupdf.open()
    W, H, M = 842, 595, 28
    fonts = _fonts()
    REG, BOLD = ("fr", "fb") if fonts else ("helv", "hebo")
    clean = (lambda t: t) if fonts else _ascii

    def put(page, xy, text, size, bold=False):
        page.insert_text(xy, clean(str(text)), fontsize=size, fontname=BOLD if bold else REG)

    def new_page(title: str):
        p = doc.new_page(width=W, height=H)
        if fonts:
            p.insert_font(fontname="fr", fontfile=fonts[0])
            p.insert_font(fontname="fb", fontfile=fonts[1])
        put(p, (M, M + 8), title, 12, True)
        if draft:
            put(p, (W - M - 150, M + 8), "DRAFT — NOT SIGNED", 10, True)
        p.draw_line((M, M + 16), (W - M, M + 16), width=0.6)
        return p, M + 32

    def table(title: str, cols: list[tuple[str, float]], rows: list[list]):
        page, y = new_page(title)
        widths = [w * (W - 2 * M) for _, w in cols]

        def row(vals, bold=False):
            nonlocal page, y
            lines = []
            for v, w in zip(vals, widths):
                s = "" if v is None else str(v)
                per = max(4, int((w - 6) / 4.1))
                lines.append(textwrap.wrap(s, per, break_long_words=True) or [""])
            h = 11 * max(len(x) for x in lines) + 4
            if y + h > H - M:
                page, y = new_page(title + " (continued)")
            x = M
            for chunk, w in zip(lines, widths):
                page.draw_rect(pymupdf.Rect(x, y, x + w, y + h), width=0.4)
                for k, ln in enumerate(chunk):
                    put(page, (x + 3, y + 10 + 11 * k), ln, 7.5, bold)
                x += w
            y += h

        row([c for c, _ in cols], bold=True)
        for r in rows:
            row(r)
        return page, y

    f1 = forms["form1"]
    page, y = new_page("AS9102 Form 1 — Part Number Accountability")
    for k, v in f1.items():
        put(page, (M, y), k.replace("_", " ").capitalize(), 8.5)
        put(page, (M + 220, y), v or "—", 8.5, True)
        y += 14
    table("AS9102 Form 2 — Product Accountability",
          [("Type", .12), ("Material / process", .32), ("Specification", .16), ("Code", .08),
           ("Supplier code", .1), ("Approval", .1), ("C of C", .12)],
          [[r["type"], r["name"], r["specification"], r["code"], r["supplier"], r["approval"], r["certificate"]]
           for r in forms["form2"]] or [["—", "None identified", "", "", "", "", ""]])
    page, y = table("AS9102 Form 3 — Characteristic Accountability",
                    [("No.", .05), ("Location", .1), ("Requirement", .37), ("Lower", .08), ("Upper", .08),
                     ("Results", .12), ("Status", .07), ("Tooling", .13)],
                    [[r["no"], r["location"], r["requirement"], r["lower"], r["upper"], r["results"], r["status"],
                      r["tooling"]] for r in forms["form3"]])
    if y + 30 > H - M:
        page, y = new_page("Sign-off")
    put(page, (M, y + 20), f"Signed: {f1.get('signed_by') or '—'}    Role: {f1.get('signed_role') or '—'}    "
                           f"Date: {f1.get('signed_at') or '—'}", 9, True)
    path = Path(path)
    doc.save(str(path))
    doc.close()
    return path


def write_ballooned(src_pdf: str | Path, chars: list[dict], path: str | Path, draft: bool) -> Path:
    import pymupdf

    doc = pymupdf.open(str(src_pdf))
    for c in chars:
        if not c.get("balloon") or c["page"] >= len(doc):
            continue
        page = doc[c["page"]]
        # Coordinates are in the page's displayed frame; PyMuPDF draws in the
        # unrotated frame, so map through the derotation matrix.
        mat = page.derotation_matrix
        x, y = c["balloon"]
        p = pymupdf.Point(x, y) * mat
        b = c.get("bbox") or [x, y, x, y]
        anchor = pymupdf.Point(b[0], b[1] + min((b[3] - b[1]) / 2, 6.0)) * mat     # first line of the callout
        r = 7.5
        page.draw_line(p, anchor, color=(0, 0, 0), width=0.5)
        page.draw_circle(p, r, color=(0, 0, 0), fill=(0, 0, 0), width=0.6)
        label = str(c["no"])
        fs = 7 if len(label) < 3 else 5.5
        tw = pymupdf.get_text_length(label, fontname="hebo", fontsize=fs)
        page.insert_text((p.x - tw / 2, p.y + fs * 0.36), label, fontsize=fs, fontname="hebo", color=(1, 1, 1),
                         rotate=page.rotation)
    if draft:
        for page in doc:
            page.insert_text((30, 30), f"DRAFT FAI BALLOONING - {datetime.now(timezone.utc):%Y-%m-%d}", fontsize=9,
                             fontname="hebo", color=(0, 0, 0))
    path = Path(path)
    doc.save(str(path))
    doc.close()
    return path
