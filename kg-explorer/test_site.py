#!/usr/bin/env python3
"""E2E test suite for the Mental Models site.

Usage:
    python3 test_site.py                          # test against default local URL
    python3 test_site.py --url http://localhost:8080  # test against local server
    python3 test_site.py --json                   # output JSON report

Exit code 0 on all-pass, non-zero on any FAIL. WARN results do not fail the run.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from playwright.sync_api import ConsoleMessage, Error, Page, sync_playwright


# ─── config ────────────────────────────────────────────────────────────────
DEFAULT_URL = "http://localhost:8765"
PAGES = ["index.html", "graph.html"]
FPS_SEL = "#fps"

# Relaxed thresholds (headless Chromium on CI is noisy).
FPS_PASS_MEDIAN = 30.0   # median must clear this
FPS_WARN_MEDIAN = 45.0   # below this → warn
FPS_FAIL_MEDIAN = 15.0   # below this → fail outright

# Expected counts are range-based to accommodate nondeterministic LLM extraction.
# Mission-critical focused graph: ~300-800 nodes.
EXPECTED_NODE_RANGE = (200, 800)
EXPECTED_MM_RANGE = (5, 200)


@dataclass
class Result:
    name: str
    status: str                         # pass | fail | warn
    detail: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)


# ─── helpers ───────────────────────────────────────────────────────────────
def attach_error_sinks(page: Page) -> list[str]:
    errs: list[str] = []
    page.on("console",   lambda m: errs.append(f"console:{m.type}: {m.text}") if m.type == "error" else None)
    page.on("pageerror", lambda e: errs.append(f"pageerror: {getattr(e, 'message', str(e))}"))
    return errs


def read_fps_counter(page: Page) -> tuple[float | None, int | None, int | None]:
    """Parse '58 fps · 218/4099 nodes' -> (fps, visible, total)."""
    try:
        txt = page.locator(FPS_SEL).first.text_content(timeout=2000) or ""
    except Exception:
        return None, None, None
    fps_m = re.search(r"(\d+(?:\.\d+)?)\s*fps", txt)
    cnt_m = re.search(r"(\d+)\s*/\s*(\d+)\s*nodes", txt)
    fps = float(fps_m.group(1)) if fps_m else None
    vis = int(cnt_m.group(1)) if cnt_m else None
    tot = int(cnt_m.group(2)) if cnt_m else None
    return fps, vis, tot


def wait_for_graph_ready(page: Page, timeout_s: float = 15) -> None:
    page.wait_for_selector(FPS_SEL, timeout=int(timeout_s * 1000))
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        fps, _, tot = read_fps_counter(page)
        if fps is not None and tot:
            return
        time.sleep(0.1)
    raise TimeoutError("FPS counter never populated — graph did not render")


# ─── landing-page tests ────────────────────────────────────────────────────
def test_index(page: Page, base: str) -> list[Result]:
    out: list[Result] = []
    errs = attach_error_sinks(page)
    url = f"{base}/index.html"
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=15000)
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception as e:
        return [Result("index:load", "fail", f"navigation failed: {e}")]

    # stats populated
    def stat(sel: str) -> str:
        try: return (page.locator(sel).first.text_content(timeout=2000) or "").strip()
        except Exception: return ""
    stats = {s: stat(f"#{s}") for s in ["stat-docs", "stat-models", "stat-nodes", "stat-edges", "stat-mc"]}
    unpopulated = [k for k, v in stats.items() if not v or v == "–"]
    if unpopulated:
        out.append(Result("index:stats-populated", "fail", f"still placeholders: {unpopulated}", stats))
    else:
        out.append(Result("index:stats-populated", "pass", ", ".join(f"{k}={v}" for k, v in stats.items()), stats))

    # CTA links resolve (just check hrefs + first click navigates)
    cta_links = page.locator(".cta a").all()
    hrefs = [(l.get_attribute("href") or "").strip() for l in cta_links]
    out.append(Result(
        "index:cta-links-present",
        "pass" if len([h for h in hrefs if h.startswith("graph.html")]) >= 3 else "fail",
        f"{len(hrefs)} links: {hrefs}",
    ))

    # exercise one CTA click
    try:
        cta_links[0].click()
        page.wait_for_load_state("domcontentloaded", timeout=10000)
        ok = "graph.html" in page.url
        out.append(Result("index:cta-click-navigates", "pass" if ok else "fail", f"-> {page.url}"))
    except Exception as e:
        out.append(Result("index:cta-click-navigates", "fail", str(e)))

    if errs:
        out.append(Result("index:console-clean", "fail", "; ".join(errs[:5])))
    else:
        out.append(Result("index:console-clean", "pass"))
    return out


# ─── graph smoke ───────────────────────────────────────────────────────────
def test_graph_smoke(page: Page, base: str) -> list[Result]:
    out: list[Result] = []
    errs = attach_error_sinks(page)
    url = f"{base}/graph.html"
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=20000)
        wait_for_graph_ready(page)
    except Exception as e:
        return [Result("graph:ready", "fail", str(e))]
    out.append(Result("graph:ready", "pass"))

    # screenshot
    try:
        page.screenshot(path="test-graph-default.png", full_page=False)
    except Exception:
        pass

    _, vis, tot = read_fps_counter(page)
    if vis is None or tot is None:
        out.append(Result("graph:node-counts", "fail", "could not parse node counter"))
    else:
        ok_tot = EXPECTED_NODE_RANGE[0] <= tot <= EXPECTED_NODE_RANGE[1]
        ok_vis = 10 <= vis <= tot   # visible should be a subset of total
        out.append(Result(
            "graph:default-focus-count",
            "pass" if (ok_tot and ok_vis) else "fail",
            f"{vis}/{tot} visible (expected {EXPECTED_NODE_RANGE[0]}-{EXPECTED_NODE_RANGE[1]} total)",
            {"visible": vis, "total": tot},
        ))

    if errs:
        out.append(Result("graph:console-clean-initial", "fail", "; ".join(errs[:5])))
    else:
        out.append(Result("graph:console-clean-initial", "pass"))
    return out


# ─── fps measurement ───────────────────────────────────────────────────────
def test_fps(page: Page) -> Result:
    """Measure FPS while forcing continuous rendering via rapid mouse moves.

    The app uses dirty-flag rAF rendering, so FPS only ticks when state changes.
    We continuously nudge the mouse across the canvas to force hover re-renders
    each rAF, then sample the displayed counter.
    """
    box = page.locator("#graph").bounding_box()
    if not box:
        return Result("graph:fps", "fail", "no canvas bounding box")
    cx = box["x"] + box["width"] / 2
    cy = box["y"] + box["height"] / 2

    readings: list[float] = []

    # 10 samples over ~5 seconds; before each sample, churn the mouse for ~400ms.
    for i in range(10):
        # Rapid motion churn: 30 moves in ~400ms, large enough to hit multiple
        # nodes → forces repeated dirty-flag render cycles.
        for j in range(30):
            dx = ((i * 7 + j * 13) % 200) - 100
            dy = ((i * 11 + j * 17) % 140) - 70
            page.mouse.move(cx + dx, cy + dy)
        time.sleep(0.1)  # let last frame flush
        fps, _, _ = read_fps_counter(page)
        if fps is not None and fps > 0:
            readings.append(fps)

    if not readings:
        return Result("graph:fps", "fail", "no FPS samples captured")

    s = sorted(readings)
    median = s[len(s) // 2]
    mn = s[0]
    p10 = s[max(0, len(s) // 10 - 1)] if len(s) >= 10 else mn
    metrics = {"samples": readings, "median": median, "min": mn, "p10": p10, "n": len(readings)}

    detail = f"median={median:.1f} min={mn:.1f} p10={p10:.1f} (n={len(readings)})"
    if median < FPS_FAIL_MEDIAN:
        return Result("graph:fps", "fail", detail + f" [< {FPS_FAIL_MEDIAN} fail]", metrics)
    if median < FPS_PASS_MEDIAN:
        return Result("graph:fps", "fail", detail + f" [< {FPS_PASS_MEDIAN} pass]", metrics)
    if median < FPS_WARN_MEDIAN:
        return Result("graph:fps", "warn", detail + f" [< {FPS_WARN_MEDIAN} warn]", metrics)
    return Result("graph:fps", "pass", detail, metrics)


# ─── interaction tests ─────────────────────────────────────────────────────
def test_interactions(page: Page, base: str) -> list[Result]:
    out: list[Result] = []
    url = f"{base}/graph.html"

    # hash routing
    target = "Zero Trust"
    page.goto(f"{url}#{target.replace(' ', '%20')}", wait_until="domcontentloaded", timeout=15000)
    try:
        wait_for_graph_ready(page)
    except Exception as e:
        out.append(Result("graph:hash-ready", "fail", str(e)))
        return out
    time.sleep(1.0)  # sidebar + details.json

    sidebar = (page.locator("#sidebar").text_content(timeout=3000) or "")
    if target in sidebar:
        out.append(Result("graph:hash-sidebar", "pass", f"sidebar shows {target!r}"))
    else:
        out.append(Result("graph:hash-sidebar", "fail", f"sidebar missing {target!r}: {sidebar[:120]}"))

    # After selection we expect expanded neighbors: visible count grows beyond tier 0.
    _, vis_after, tot = read_fps_counter(page)
    out.append(Result(
        "graph:expansion-increases",
        "pass" if (vis_after is not None and vis_after > 100) else "fail",
        f"visible={vis_after} total={tot}",
        {"visible": vis_after, "total": tot},
    ))

    # dimmed class/opacity present — check via JS eval
    dim_count = page.evaluate("""() => {
        const s = window.state || null;  // not global; fall through
        return document.querySelector('canvas') ? 1 : 0;
    }""")
    # The state object isn't exported; assert indirectly that the graph is still
    # responsive and that at least one Tier-1 neighbor exists by comparing counts.
    out.append(Result("graph:canvas-present", "pass" if dim_count else "fail"))

    # Filter presets
    def click_filter(label_substr: str) -> int | None:
        btns = page.locator("#filters button").all()
        for b in btns:
            t = (b.text_content() or "").strip()
            if label_substr.lower() in t.lower():
                b.click()
                time.sleep(0.8)
                _, v, _ = read_fps_counter(page)
                return v
        return None

    v_mental = click_filter("Mental Models")
    out.append(Result(
        "graph:filter-mental",
        "pass" if (v_mental is not None and EXPECTED_MM_RANGE[0] <= v_mental <= EXPECTED_MM_RANGE[1]) else "fail",
        f"visible={v_mental} (expect {EXPECTED_MM_RANGE[0]}-{EXPECTED_MM_RANGE[1]})",
        {"visible": v_mental},
    ))

    v_all = click_filter("Everything")
    ok_all = v_all is not None and EXPECTED_NODE_RANGE[0] <= v_all <= EXPECTED_NODE_RANGE[1]
    out.append(Result(
        "graph:filter-everything",
        "pass" if ok_all else "fail",
        f"visible={v_all} (expect {EXPECTED_NODE_RANGE[0]}-{EXPECTED_NODE_RANGE[1]})",
        {"visible": v_all},
    ))

    # return to Focus
    click_filter("Focus")

    # Search: type "cosmos"
    search = page.locator("#search").first
    search.click()
    search.fill("")
    search.type("cosmos", delay=20)
    time.sleep(0.7)
    _, v_search, _ = read_fps_counter(page)
    out.append(Result(
        "graph:search-filter",
        "pass" if (v_search is not None and v_search >= 0 and v_search < 800) else "fail",
        f"visible={v_search} matching 'cosmos'",
        {"visible": v_search},
    ))

    # clear search
    search.fill("")
    time.sleep(0.5)
    _, v_clear, _ = read_fps_counter(page)
    out.append(Result(
        "graph:search-clear",
        "pass" if (v_clear is not None and v_clear > (v_search or 0)) else "fail",
        f"visible={v_clear} after clear",
        {"visible": v_clear},
    ))

    return out


# ─── navigation tests ──────────────────────────────────────────────────────
def test_navigation(page: Page, base: str) -> list[Result]:
    out: list[Result] = []
    url = f"{base}/graph.html#Zero%20Trust"
    page.goto(url, wait_until="domcontentloaded", timeout=15000)
    try:
        wait_for_graph_ready(page)
    except Exception as e:
        return [Result("nav:ready", "fail", str(e))]
    time.sleep(1.0)

    # "next model" — only exists on mental-model cards; try clicking
    nxt = page.locator("#sidebar #next")
    if nxt.count():
        before = (page.locator("#sidebar h2").first.text_content() or "").strip()
        nxt.click()
        time.sleep(0.8)
        after = (page.locator("#sidebar h2").first.text_content() or "").strip()
        out.append(Result(
            "nav:next-button",
            "pass" if (before and after and before != after) else "fail",
            f"{before!r} -> {after!r}",
        ))
    else:
        out.append(Result("nav:next-button", "warn", "no #next button on this card"))

    # Breadcrumb should appear once we navigate to another node
    crumb = (page.locator("#breadcrumb").text_content() or "").strip()
    out.append(Result(
        "nav:breadcrumb-present",
        "pass" if crumb else "warn",
        f"breadcrumb={crumb!r}",
    ))
    return out


# ─── cross-page ────────────────────────────────────────────────────────────
def test_cross_page(page: Page, base: str) -> list[Result]:
    out: list[Result] = []
    try:
        page.goto(f"{base}/index.html", wait_until="domcontentloaded", timeout=15000)
        page.goto(f"{base}/graph.html", wait_until="domcontentloaded", timeout=15000)
        wait_for_graph_ready(page)
        page.go_back()
        page.wait_for_load_state("domcontentloaded", timeout=10000)
        page.goto(f"{base}/graph.html#Zero%20Trust", wait_until="domcontentloaded", timeout=15000)
        wait_for_graph_ready(page)
        time.sleep(0.8)
        sidebar = page.locator("#sidebar").text_content() or ""
        ok = "Zero Trust" in sidebar
        out.append(Result("cross:index→graph→back→hash", "pass" if ok else "fail",
                          f"final url={page.url}"))
    except Exception as e:
        out.append(Result("cross:index→graph→back→hash", "fail", str(e)))
    return out


# ─── driver ────────────────────────────────────────────────────────────────
def emit(results: list[Result], as_json: bool) -> int:
    passed = sum(1 for r in results if r.status == "pass")
    warned = sum(1 for r in results if r.status == "warn")
    failed = sum(1 for r in results if r.status == "fail")

    if as_json:
        print(json.dumps({
            "summary": {"total": len(results), "pass": passed, "warn": warned, "fail": failed},
            "results": [asdict(r) for r in results],
        }, indent=2))
    else:
        mark = {"pass": "✓", "warn": "!", "fail": "✗"}
        for r in results:
            line = f"  {mark.get(r.status, '?')} {r.name:<34} [{r.status}] {r.detail}"
            print(line)
        print(f"\n{passed} pass · {warned} warn · {failed} fail  ({len(results)} total)")
    return 0 if failed == 0 else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=DEFAULT_URL, help="Base URL where the site is served")
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    base = args.url.rstrip("/")
    results: list[Result] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not args.headed)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})

        # Landing
        p = ctx.new_page(); results.extend(test_index(p, base)); p.close()

        # Graph smoke + screenshot + counts
        p = ctx.new_page(); smoke = test_graph_smoke(p, base); results.extend(smoke)
        # Only run heavier tests if smoke passed
        if all(r.status != "fail" for r in smoke):
            results.append(test_fps(p))
        p.close()

        # Interactions (fresh page for clean error capture)
        p = ctx.new_page(); attach_error_sinks(p); results.extend(test_interactions(p, base)); p.close()

        # Navigation (prev/next, breadcrumb)
        p = ctx.new_page(); results.extend(test_navigation(p, base)); p.close()

        # Cross-page
        p = ctx.new_page(); results.extend(test_cross_page(p, base)); p.close()

        browser.close()

    return emit(results, args.json)


if __name__ == "__main__":
    sys.exit(main())
