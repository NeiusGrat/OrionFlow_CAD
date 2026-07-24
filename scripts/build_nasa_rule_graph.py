"""Build the NASA normative rule graph from public NASA Technical Standards.

Why this exists
---------------
OrionFlow must never let a model recall an engineering requirement from
memory. NASA Technical Standards are US Government works in the public domain,
so unlike the licensed ASME/ISO material catalogued in ``sources.json`` their
text *can* be quoted and shipped. Each standard numbers its own requirements
with a stable tag (``[TFSR 3]``, ``[FSR 12]``, ...), which makes the document a
rule graph that can be transcribed rather than interpreted.

Every emitted rule carries standard + revision + requirement tag + section +
page, so any statement the agent surfaces can be checked against the source
PDF. Nothing here paraphrases: the ``statement`` field is the verbatim
normative sentence. If a requirement cannot be parsed cleanly it is dropped,
never guessed.

Usage
-----
    python scripts/build_nasa_rule_graph.py            # download + extract
    python scripts/build_nasa_rule_graph.py --check    # verify committed graph

Requires ``pypdf`` and network access. The *runtime* retrieval module
(``orion_agent/harness/nasa_rules.py``) reads only the committed JSON and needs
neither.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import re
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Optional

_ROOT = Path(__file__).resolve().parents[1]
_OUT = _ROOT / "orion_agent" / "knowledge" / "mechanical" / "nasa_rules.json"
_CACHE = _ROOT / "data" / "nasa_standards"
_BASE = "https://standards.nasa.gov"
_UA = {"User-Agent": "Mozilla/5.0 (OrionFlow knowledge builder)"}

# Standards worth transcribing for text -> FeatureGraph reasoning. Each maps to
# the requirement-tag prefix that standard uses for its numbered requirements.
STANDARDS: dict[str, dict[str, str]] = {
    "NASA-STD-5001": {"tag": "FSR", "domain": "structural_margins",
                      "title": "Structural Design and Test Factors of Safety "
                               "for Spaceflight Hardware"},
    "NASA-STD-5002": {"tag": "LAR", "domain": "loads",
                      "title": "Load Analyses of Spacecraft and Payloads"},
    "NASA-STD-5006": {"tag": "GWR", "domain": "joining",
                      "title": "General Welding Requirements for Aerospace "
                               "Materials"},
    "NASA-STD-5009": {"tag": "NER", "domain": "inspection",
                      "title": "Nondestructive Evaluation Requirements for "
                               "Fracture-Critical Metallic Components"},
    "NASA-STD-5017": {"tag": "DDMR", "domain": "mechanisms",
                      "title": "Design and Development Requirements for "
                               "Mechanisms"},
    "NASA-STD-5019": {"tag": "FCR", "domain": "fracture_control",
                      "title": "Fracture Control Requirements for Spaceflight "
                               "Hardware"},
    "NASA-STD-5020": {"tag": "TFSR", "domain": "fasteners",
                      "title": "Requirements for Threaded Fastening Systems in "
                               "Spaceflight Hardware"},
    "NASA-STD-6016": {"tag": "MPR", "domain": "materials",
                      "title": "Standard Materials and Processes Requirements "
                               "for Spacecraft"},
}

_TAG_RE = re.compile(r"\[([A-Z]{2,6})\s*(\d+)\]")
# Running headers/footers repeat on every page and otherwise bleed into a
# requirement whose tag sits near a page break or inside a figure caption.
# Deliberately conservative: only unambiguous page furniture. Figure/Table
# captions are left alone because a normative sentence often wraps onto a line
# beginning "Table 2, Minimum Design and Test Factors...".
_BOILERPLATE_RE = re.compile(
    r"^[ \t]*(?:APPROVED FOR PUBLIC RELEASE.*|Controlled by:.*|"
    r"NASA-(?:STD|HDBK)-\d{4}[A-Z]?(?:[ \t]+w/[ \t]*CHANGE[ \t]*\d+)?[ \t]*|"
    r"\d+[ \t]+of[ \t]+\d+)[ \t]*$",
    re.I | re.M)
_SEC_RE = re.compile(r"(\d+(?:\.\d+){1,4})\s+([A-Z][A-Za-z0-9 ,/&'()-]{3,70})\s*$")
_REV_RE = re.compile(r"NASA-(?:STD|HDBK)-\d{4}([A-Z])?", re.I)
_NUM_RE = re.compile(r"\d")
_RATIONALE_RE = re.compile(r"\[Rationale:\s*(.*?)\]\s*", re.S)

# Topic keywords -> retrieval tags. Deliberately small and mechanical; this is
# for lexical retrieval, not classification.
_TOPICS: dict[str, tuple[str, ...]] = {
    "preload": ("preload", "torque", "tension"),
    "margin_of_safety": ("margin of safety", "factor of safety", "fitting factor"),
    "separation": ("separation", "gapping"),
    "fatigue": ("fatigue", "life", "cyclic"),
    "fracture": ("fracture", "crack", "flaw", "damage tolerance"),
    "clearance": ("clearance", "interference", "backlash"),
    "thread": ("thread", "locking", "nut", "bolt", "screw", "fastener"),
    "weld": ("weld", "braze", "joint"),
    "material": ("material", "alloy", "corrosion", "allowable"),
    "tolerance": ("tolerance", "dimensional analysis", "fit"),
    "load": ("limit load", "ultimate load", "yield"),
    "test": ("test", "verification", "inspection", "proof"),
    "mechanism": ("mechanism", "bearing", "gear", "actuator", "lubric"),
}


def _fetch(url: str, timeout: int = 180) -> bytes:
    request = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def resolve_pdf_url(standard: str) -> Optional[str]:
    """Scrape the standard's landing page for its current PDF link."""
    html = _fetch(f"{_BASE}/standard/NASA/{standard}", timeout=60).decode(
        "utf-8", "ignore")
    links = re.findall(r'href="([^"]*\.pdf[^"]*)"', html, re.I)
    if not links:
        return None
    current = [link for link in links if "Historical" not in link]
    link = (current or links)[0]
    return link if link.startswith("http") else _BASE + link


def download(standard: str) -> Optional[Path]:
    _CACHE.mkdir(parents=True, exist_ok=True)
    path = _CACHE / f"{standard}.pdf"
    if path.exists() and path.stat().st_size > 50_000:
        return path
    url = resolve_pdf_url(standard)
    if not url:
        return None
    path.write_bytes(_fetch(url))
    return path


# PDFs written with the Symbol font expose Greek letters in the private-use
# area (U+F000 + ASCII code), so "Γ" extracts as U+F047. Repairing these keeps
# engineering symbols readable; folding typographic quotes keeps retrieval
# robust. Mathematical operators are left intact -- "≤" carries meaning.
_SYMBOL_GREEK = {
    "A": "Α", "B": "Β", "G": "Γ", "D": "Δ", "E": "Ε", "Z": "Ζ", "H": "Η",
    "Q": "Θ", "I": "Ι", "K": "Κ", "L": "Λ", "M": "Μ", "N": "Ν", "X": "Ξ",
    "O": "Ο", "P": "Π", "R": "Ρ", "S": "Σ", "T": "Τ", "U": "Υ", "F": "Φ",
    "C": "Χ", "Y": "Ψ", "W": "Ω",
    "a": "α", "b": "β", "g": "γ", "d": "δ", "e": "ε", "z": "ζ", "h": "η",
    "q": "θ", "i": "ι", "k": "κ", "l": "λ", "m": "μ", "n": "ν", "x": "ξ",
    "o": "ο", "p": "π", "r": "ρ", "s": "σ", "t": "τ", "u": "υ", "f": "φ",
    "c": "χ", "y": "ψ", "w": "ω",
}
_TYPOGRAPHY = {"‘": "'", "’": "'", "“": '"', "”": '"',
               "–": "-", "—": "-", "−": "-", " ": " "}


def _repair_glyph(char: str) -> str:
    code = ord(char)
    if 0xF000 <= code <= 0xF0FF:
        return _SYMBOL_GREEK.get(chr(code - 0xF000), "")
    if 0xE000 <= code <= 0xF8FF:  # unmapped private use -> drop, never guess
        return ""
    return _TYPOGRAPHY.get(char, char)


def _normalize(text: str) -> str:
    text = "".join(_repair_glyph(char) for char in text)
    return re.sub(r"\s+", " ", text).strip()


def _page_index(pdf_path: Path) -> tuple[str, list[tuple[int, int]]]:
    """Concatenated document text plus (char offset -> page number) markers."""
    import pypdf

    reader = pypdf.PdfReader(str(pdf_path))
    chunks: list[str] = []
    index: list[tuple[int, int]] = []
    offset = 0
    for number, page in enumerate(reader.pages, start=1):
        text = _BOILERPLATE_RE.sub("", page.extract_text() or "")
        index.append((offset, number))
        chunks.append(text)
        offset += len(text)
    return "".join(chunks), index


def _page_of(position: int, index: list[tuple[int, int]]) -> int:
    page = 1
    for offset, number in index:
        if position >= offset:
            page = number
        else:
            break
    return page


def _section_before(text: str, position: int) -> tuple[Optional[str], Optional[str]]:
    window = text[max(0, position - 200):position]
    for line in reversed([ln.strip() for ln in window.split("\n") if ln.strip()]):
        match = _SEC_RE.search(line)
        if match:
            return match.group(1), _normalize(match.group(2))
    return None, None


def _topics(statement: str) -> list[str]:
    lowered = statement.lower()
    return sorted(topic for topic, words in _TOPICS.items()
                  if any(word in lowered for word in words))


def _revision(pdf_path: Path, standard: str) -> Optional[str]:
    """Revision letter, read from the document's own title block."""
    import pypdf

    reader = pypdf.PdfReader(str(pdf_path))
    head = (reader.pages[0].extract_text() or "")[:2000]
    for match in _REV_RE.finditer(head):
        if match.group(1):
            return match.group(1).upper()
    return None


def extract(standard: str, pdf_path: Path) -> list[dict[str, Any]]:
    """Parse a standard's numbered requirements into rule records."""
    meta = STANDARDS[standard]
    expected_tag = meta["tag"]
    text, index = _page_index(pdf_path)
    matches = [m for m in _TAG_RE.finditer(text) if m.group(1) == expected_tag]
    revision = _revision(pdf_path, standard)

    rules: dict[int, dict[str, Any]] = {}
    for position, match in enumerate(matches):
        number = int(match.group(2))
        # A tag can appear as a figure label or a compliance-matrix row before
        # the requirement itself. Keep the first occurrence that parses into a
        # well-formed normative statement rather than blindly the first.
        if number in rules:
            continue
        stop = (matches[position + 1].start() if position + 1 < len(matches)
                else min(len(text), match.end() + 1500))
        body = _normalize(text[match.end():stop])
        if not body:
            continue

        rationale_match = _RATIONALE_RE.search(body)
        rationale = _normalize(rationale_match.group(1)) if rationale_match else None
        body = _RATIONALE_RE.sub(" ", body)

        # The requirement sentence begins immediately after its tag. A "shall"
        # far downstream means this occurrence is a figure label or matrix row
        # and the window ran on into unrelated text -- reject it so a later,
        # well-formed occurrence of the same tag can win.
        shall = re.search(r"\bshall\b", body[:400])
        if not shall:  # not a normative statement; skip rather than guess
            continue
        statement = body
        cut = re.search(r"(?<=[.])\s+(?=[A-Z0-9])", statement[shall.end():])
        if cut and shall.end() + cut.start() < 900:
            statement = statement[:shall.end() + cut.start() + 1]
        statement = _normalize(statement)
        # The sentence cut lands just past the period, so the *next* list
        # item's marker ("b.", "(2)") tags along. Drop it: it belongs to a
        # sibling requirement, not this one.
        statement = re.sub(r"\s+(?:[a-z]\.|\(\d+\)|\d+\.)\s*$", "", statement)
        if len(statement) < 25:
            continue

        section, section_title = _section_before(text, match.start())
        rules[number] = {
            "id": f"{standard.lower().replace('-', '_')}.{expected_tag.lower()}_{number}",
            "standard": standard,
            "standard_title": meta["title"],
            "revision": revision,
            "requirement_tag": f"{expected_tag} {number}",
            "domain": meta["domain"],
            "section": section,
            "section_title": section_title,
            "page": _page_of(match.start(), index),
            "statement": statement[:1200],
            "rationale": (rationale[:800] if rationale else None),
            "has_numeric": bool(_NUM_RE.search(statement)),
            "topics": _topics(statement + " " + (section_title or "")),
            "authority": "normative_reference",
            "source": f"nasa_{standard.lower().replace('-', '_')}",
        }
    return [rules[key] for key in sorted(rules)]


def build() -> dict[str, Any]:
    def one(standard: str) -> tuple[str, list[dict[str, Any]]]:
        try:
            path = download(standard)
            if path is None:
                print(f"  {standard}: no PDF link found", file=sys.stderr)
                return standard, []
            return standard, extract(standard, path)
        except Exception as exc:  # noqa: BLE001 - report and continue
            print(f"  {standard}: {type(exc).__name__}: {exc}", file=sys.stderr)
            return standard, []

    results = list(ThreadPoolExecutor(4).map(one, STANDARDS))
    rules: list[dict[str, Any]] = []
    for standard, extracted in results:
        print(f"  {standard}: {len(extracted)} requirements")
        rules.extend(extracted)
    rules.sort(key=lambda r: (r["standard"], int(r["requirement_tag"].split()[1])))
    return {
        "schema_version": "1.0",
        "package": "orionflow.knowledge.mechanical.nasa_rules",
        "version": "0.1.0",
        "generated": _dt.date.today().isoformat(),
        "generator": "scripts/build_nasa_rule_graph.py",
        "license": "NASA Technical Standards are works of the US Government "
                   "and are in the public domain; requirement text is quoted "
                   "verbatim with document, section, and page provenance.",
        "rules": rules,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="validate the committed graph instead of rebuilding")
    args = parser.parse_args()

    if args.check:
        sys.path.insert(0, str(_ROOT))  # runnable from anywhere
        from orion_agent.harness import nasa_rules

        errors = nasa_rules.validate_package()
        for error in errors:
            print(error)
        print(f"{len(nasa_rules.rules())} rules, {len(errors)} problems")
        return 1 if errors else 0

    print("Building NASA rule graph...")
    data = build()
    _OUT.parent.mkdir(parents=True, exist_ok=True)
    with _OUT.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=1, ensure_ascii=False)
        handle.write("\n")
    print(f"wrote {len(data['rules'])} rules -> {_OUT.relative_to(_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
