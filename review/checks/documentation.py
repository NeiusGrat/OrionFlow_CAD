"""D7 Documentation consistency: do the BOM and the CAD describe the same product?"""
from __future__ import annotations

import re
from collections import defaultdict

from .base import CheckConfig, Evidence, Finding, Quantity, check

CONSUMABLE = re.compile(r"cable|wire|glue|loctite|adhesive|tape|zip\s?tie|grease|label|sticker|threadlock|heat.?shrink", re.I)


def _row_ev(r: dict) -> Evidence:
    return Evidence(type="bom_row", id=r["key"], label=f"{r['file']} row {r['row']}: {r['part_number'] or r['name']}")


@check("DOC-BOM-CAD", "1.0.0", "documentation", "BOM matches the CAD", requires=["bom_rows"])
def doc_bom_cad(graph, cfg: CheckConfig) -> list[Finding]:
    """Every CAD part has a BOM row and every BOM row a CAD part; quantities agree (rows naming one part are summed)."""
    names = {p.id: p.name for p in graph.parts}
    count = defaultdict(int)
    for i in graph.instances:
        count[i.part_id] += 1
    inst_of = defaultdict(list)
    for i in graph.instances:
        inst_of[i.part_id].append(i)
    matched = defaultdict(list)
    for r in graph.bom_rows:
        if r["part_id"] and r["method"] != "none":
            matched[r["part_id"]].append(r)
    out: list[Finding] = []
    if graph.stats.flat and not matched:
        # a flattened export has no part names, so not one row could be matched by name: say that once,
        # instead of listing every row and every part as missing
        return [Finding(
            check_id="DOC-BOM-CAD", check_version="1.0.0", domain="documentation", severity="major",
            title="BOM cannot be matched: the STEP has no part names",
            statement=f"{graph.source.name} was exported as one body, so its {graph.stats.parts} parts carry made-up names and "
                      f"none of the {len(graph.bom_rows)} BOM rows can be matched to them. Quantities and missing parts "
                      f"cannot be checked until the file is re-exported with its assembly tree, or rows are paired by hand.",
            measured=Quantity(value=0, unit="rows matched"), expected=Quantity(value=len(graph.bom_rows), unit="rows", basis="every BOM row"),
            evidence=[Evidence(type="file", id=graph.source.name, label=graph.source.name, sha256=graph.source.sha256)]
                     + [_row_ev(r) for r in graph.bom_rows[:3]],
            recommendation="Re-export the STEP as an assembly with part names, or pair rows by hand in the BOM lens.",
            key="flat-unmatched")]

    for pid, rows in matched.items():
        qtys = [r["quantity"] for r in rows if r["quantity"] is not None]
        if not qtys:
            continue
        want = sum(qtys)
        have = count[pid]
        if abs(want - have) > 1e-6:
            how = ", ".join(sorted({r["method"] for r in rows}))
            rows_txt = " + ".join(f"row {r['row']} ({r['quantity']:g})" for r in rows) if len(rows) > 1 else f"row {rows[0]['row']}"
            out.append(Finding(
                check_id="DOC-BOM-CAD", check_version="1.0.0", domain="documentation", severity="major",
                title="BOM quantity differs from the assembly",
                statement=f"The BOM orders {want:g} × {rows[0]['part_number'] or rows[0]['name']} ({rows_txt}); the assembly "
                          f"places {have} of {names[pid]}. Either parts are missing from the CAD or the BOM orders the wrong count.",
                measured=Quantity(value=have, unit="in CAD"), expected=Quantity(value=want, unit="in BOM", basis=f"BOM, matched {how}"),
                evidence=[_row_ev(r) for r in rows] + [Evidence(type="part", id=pid, label=names[pid])]
                         + [Evidence(type="instance", id=i.id, label=i.name) for i in inst_of[pid][:6]],
                recommendation="Count the part in the build: correct the BOM quantity or add the missing copies to the CAD.",
                key=f"qty:{pid}"))
        mats = sorted({r["material"] for r in rows if r["material"]})
        if len(mats) > 1:
            out.append(Finding(
                check_id="DOC-BOM-CAD", check_version="1.0.0", domain="documentation", severity="minor",
                title="BOM rows give one part two materials",
                statement=f"{names[pid]} is listed as {' and as '.join(mats)} on different BOM rows.",
                measured=Quantity(text=" / ".join(mats)), expected=Quantity(text="one material", basis="one part, one material"),
                evidence=[_row_ev(r) for r in rows] + [Evidence(type="part", id=pid, label=names[pid])],
                recommendation="Make the rows agree, or split the part into two part numbers.", key=f"mat:{pid}"))

    for p in graph.parts:
        if p.id in matched:
            continue
        out.append(Finding(
            check_id="DOC-BOM-CAD", check_version="1.0.0", domain="documentation", severity="major",
            title="CAD part has no BOM row",
            statement=f"{p.name} ({count[p.id]} in the assembly) is not on the BOM: it will not be ordered or made.",
            measured=Quantity(value=count[p.id], unit="in CAD"), expected=Quantity(text="a BOM row", basis="every CAD part is ordered or made"),
            evidence=[Evidence(type="part", id=p.id, label=p.name)] + [Evidence(type="instance", id=i.id, label=i.name) for i in inst_of[p.id][:6]],
            recommendation="Add the part to the BOM, or pair it with its row by hand if it is there under another name.",
            key=f"nobom:{p.id}"))

    for r in graph.bom_rows:
        if r["part_id"] and r["method"] != "none":
            if r["method"] == "ai" and r["confidence"] < 0.8:
                out.append(Finding(
                    check_id="DOC-BOM-CAD", check_version="1.0.0", domain="documentation", severity="info",
                    title="AI-matched BOM row needs confirmation",
                    statement=f"Row {r['row']} '{r['part_number'] or r['name']}' was matched to {names.get(r['part_id'], '?')} by AI "
                              f"with confidence {r['confidence']:.2f}. Confirm or change it.",
                    evidence=[_row_ev(r), Evidence(type="part", id=r["part_id"], label=names.get(r["part_id"]))],
                    recommendation="Confirm the pairing in the BOM lens.", key=f"ai:{r['key']}"))
            continue
        text = f"{r['part_number']} {r['name']} {r['type']}"
        from interface_check.rules.checks import is_hardware
        consumable = bool(CONSUMABLE.search(text)) or is_hardware(text)
        label = r["part_number"] or r["name"]
        alias = f" ({r['name']})" if r["part_number"] and r["name"] and r["name"] != r["part_number"] else ""
        qty = f", qty {r['quantity']:g}," if r["quantity"] is not None else ","
        tail = " It reads as hardware or a consumable, which CAD often leaves out." if consumable else ""
        out.append(Finding(
            check_id="DOC-BOM-CAD", check_version="1.0.0", domain="documentation",
            severity="minor" if consumable else "major",
            title="BOM row has no part in the CAD",
            statement=f"Row {r['row']} '{label}'{alias}{qty} matches no part in the assembly.{tail}",
            measured=Quantity(text="not in CAD"), expected=Quantity(value=r["quantity"], unit="in BOM", basis=f"{r['file']} row {r['row']}"),
            evidence=[_row_ev(r)],
            recommendation="Add the part to the CAD, remove the row, or pair it by hand if it is in the CAD under another name.",
            key=f"nocad:{r['key']}"))
    return out
