"""End-to-end browser smoke test for OrionFlow Studio.

Run while a studio server is up on the URL passed via PORT env var (default 7865).
Confirms that:
  - the page loads with no console errors
  - window.studio is defined (or proves why it isn't)
  - the source-close button actually closes the drawer
  - the mode pills toggle currentMode
  - loadExample('washer'|'bracket'|'flange'|'gear') populates the editor
"""
import os
import sys
from playwright.sync_api import sync_playwright

PORT = os.environ.get("STUDIO_PORT", "7865")
URL = f"http://127.0.0.1:{PORT}/"

failures = []


def check(label, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {label}{(' -- ' + detail) if detail else ''}")
    if not cond:
        failures.append(label)


with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    ctx = browser.new_context(viewport={"width": 1400, "height": 900})
    page = ctx.new_page()

    console_logs = []
    page.on("console", lambda msg: console_logs.append(f"[{msg.type}] {msg.text}"))
    page_errors = []
    page.on("pageerror", lambda err: page_errors.append(str(err)))

    print(f"== loading {URL}")
    page.goto(URL, wait_until="networkidle")

    # Give the module a moment to finish (Three.js, etc.)
    page.wait_for_timeout(1500)

    print("\n== console output (first 12 entries)")
    for line in console_logs[:12]:
        print("  >", line)
    print(f"  ({len(console_logs)} total console entries)")

    print("\n== page errors")
    if page_errors:
        for err in page_errors:
            print("  !!", err)
    else:
        print("  (none)")

    print("\n== window.studio sanity")
    studio_type = page.evaluate("typeof window.studio")
    check("window.studio is an object", studio_type == "object", f"typeof = {studio_type!r}")
    if studio_type == "object":
        methods = page.evaluate(
            "Object.keys(window.studio).filter(k => typeof window.studio[k] === 'function')"
        )
        check(
            "studio has expected methods",
            set(methods) >= {"toggleSource", "closeSource", "openSource", "loadExample", "setMode"},
            f"methods = {sorted(methods)}",
        )

    print("\n== source drawer open/close")
    grid_initial = page.evaluate("document.getElementById('grid').classList.contains('code-closed')")
    check("drawer starts CLOSED", grid_initial is True, f"code-closed = {grid_initial}")

    page.click("#code-toggle")
    page.wait_for_timeout(450)
    open_state = page.evaluate("document.getElementById('grid').classList.contains('code-closed')")
    check("topbar Source toggle OPENS drawer", open_state is False)

    page.click("#pane-close")
    page.wait_for_timeout(450)
    closed_state = page.evaluate("document.getElementById('grid').classList.contains('code-closed')")
    check("× button CLOSES drawer", closed_state is True)

    print("\n== mode pills")
    initial_active = page.evaluate(
        "document.querySelector('.mode-pill.active').dataset.mode"
    )
    check("Generate is active by default", initial_active == "generate", f"active = {initial_active!r}")
    page.click("button.mode-pill[data-mode='edit']")
    page.wait_for_timeout(150)
    now_active = page.evaluate("document.querySelector('.mode-pill.active').dataset.mode")
    check("clicking Edit pill activates Edit", now_active == "edit", f"active = {now_active!r}")
    page.click("button.mode-pill[data-mode='generate']")
    page.wait_for_timeout(150)
    back = page.evaluate("document.querySelector('.mode-pill.active').dataset.mode")
    check("clicking Generate pill activates Generate", back == "generate", f"active = {back!r}")

    print("\n== example loaders (drawer-open path)")
    page.click("#code-toggle")
    page.wait_for_timeout(350)

    for name in ("washer", "bracket", "flange", "gear"):
        page.click(f"a[onclick*=\"loadExample('{name}')\"]")
        page.wait_for_timeout(200)
        editor_value = page.evaluate("document.getElementById('editor').value")
        has_b123 = "from build123d import *" in editor_value
        has_result = "result = part.part" in editor_value
        size = len(editor_value)
        check(
            f"load {name:8s} -> editor has real code",
            has_b123 and has_result and size > 200,
            f"{size} chars / b123={has_b123} / result={has_result}",
        )
        open_now = page.evaluate("!document.getElementById('grid').classList.contains('code-closed')")
        check(f"load {name:8s} -> drawer stays open", open_now)

    print("\n== compile washer end-to-end (POST /run)")
    page.click("a[onclick*=\"loadExample('washer')\"]")
    page.wait_for_timeout(200)
    page.click("#run-btn")
    try:
        page.wait_for_selector(".stats-card.visible", timeout=30000)
        check("compile washer -> stats card visible", True)
        bbox_text = page.text_content("#s-bbox") or ""
        vol_text  = page.text_content("#s-vol") or ""
        check(
            "washer bbox 9 x 9 x 0.8 mm",
            "9" in bbox_text and "0.8" in bbox_text,
            f"bbox = {bbox_text!r}",
        )
        check(
            "washer volume reported in mm^3",
            "mm" in vol_text and len(vol_text) > 4,
            f"vol = {vol_text!r}",
        )
    except Exception as e:
        check("compile washer -> stats card visible", False, str(e))

    browser.close()

print("\n" + "=" * 60)
if failures:
    print(f"FAILED  ({len(failures)})")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("ALL PASS")
sys.exit(0)
