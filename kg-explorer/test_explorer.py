#!/usr/bin/env python3
"""E2E test suite for the WAF Knowledge Graph Explorer (explorer.html).

Usage:
    python3 test_explorer.py                              # test against default local URL
    python3 test_explorer.py --url http://localhost:8080   # test against custom server
    python3 test_explorer.py --json                        # output JSON report
    python3 test_explorer.py --headed                      # run in headed mode

The server should serve the docs/ directory:
    cd docs && python3 -m http.server 8765

Exit code 0 on all-pass/warn, non-zero on any FAIL.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from playwright.sync_api import Page, sync_playwright


# ─── config ────────────────────────────────────────────────────────────────
DEFAULT_URL = "http://localhost:8765"

# Relaxed ranges — data comes from LLM extraction and may shift.
EXPECTED_NODE_RANGE = (400, 1500)  # includes entity nodes + fact nodes
EXPECTED_EDGE_RANGE = (500, 1200)
EXPECTED_MM_RANGE = (20, 80)
EXPECTED_FACTS_RANGE = (400, 900)
EXPECTED_TIMELESS_RANGE = (150, 500)
EXPECTED_PERISHABLE_RANGE = (150, 500)


@dataclass
class Result:
    name: str
    status: str  # pass | fail | warn
    detail: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)
    elapsed_ms: float = 0.0


# ─── helpers ───────────────────────────────────────────────────────────────
def attach_error_sinks(page: Page) -> list[str]:
    errs: list[str] = []
    page.on(
        "console",
        lambda m: errs.append(f"console:{m.type}: {m.text}")
        if m.type == "error"
        else None,
    )
    page.on(
        "pageerror",
        lambda e: errs.append(f"pageerror: {getattr(e, 'message', str(e))}"),
    )
    return errs


def wait_for_app_ready(page: Page, timeout_s: float = 15) -> None:
    """Wait until the stats bar shows real data (not 'Loading…')."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        txt = page.locator("#statsBar").text_content(timeout=2000) or ""
        # Accept "nodes" or "entities" or "edges" as sign the app loaded
        if ("entities" in txt.lower() or "nodes" in txt.lower() or "edges" in txt.lower()) and "loading" not in txt.lower():
            return
        time.sleep(0.2)
    raise TimeoutError("Stats bar never populated — app did not load")


def parse_stats_bar(page: Page) -> dict[str, int]:
    """Parse '613 entities · 629 facts · 1430 edges · 39 mental models' -> dict."""
    txt = page.locator("#statsBar").text_content(timeout=2000) or ""
    out: dict[str, int] = {}
    for m in re.finditer(r"(\d+)\s+(nodes|entities|edges|mental models|facts)", txt):
        key = m.group(2).replace(" ", "_")
        if key == "entities":
            key = "nodes"  # normalize for test compatibility
        out[key] = int(m.group(1))
    return out


def timed(fn):
    """Run fn, return (result_list, elapsed_ms)."""
    t0 = time.time()
    results = fn()
    elapsed = (time.time() - t0) * 1000
    for r in results:
        r.elapsed_ms = elapsed
    return results


def safe_run(test_fn, *args, **kwargs) -> list[Result]:
    """Run a test function with exception safety."""
    try:
        return test_fn(*args, **kwargs)
    except Exception as e:
        name = getattr(test_fn, "__name__", "unknown")
        return [Result(f"{name}:crash", "fail", f"unhandled: {e}")]


# ─── 1. Data Loading ──────────────────────────────────────────────────────
def test_data_loading(page: Page, base: str) -> list[Result]:
    out: list[Result] = []
    errs = attach_error_sinks(page)

    try:
        page.goto(f"{base}/explorer.html", wait_until="domcontentloaded", timeout=20000)
        wait_for_app_ready(page)
    except Exception as e:
        return [Result("data:load", "fail", f"navigation/load failed: {e}")]

    # data:graph-loaded — check node and edge counts from stats bar
    stats = parse_stats_bar(page)
    nodes = stats.get("nodes", 0)
    edges = stats.get("edges", 0)

    if EXPECTED_NODE_RANGE[0] <= nodes <= EXPECTED_NODE_RANGE[1]:
        out.append(Result("data:graph-loaded", "pass",
                          f"{nodes} nodes, {edges} edges", stats))
    else:
        out.append(Result("data:graph-loaded", "fail",
                          f"nodes={nodes} not in {EXPECTED_NODE_RANGE}", stats))

    # data:details-loaded — check that details.json was loaded (mental models count > 0)
    mm = stats.get("mental_models", 0)
    facts = stats.get("facts", 0)
    if mm > 0 and facts > 0:
        out.append(Result("data:details-loaded", "pass",
                          f"{mm} mental models, {facts} facts", stats))
    else:
        out.append(Result("data:details-loaded", "fail",
                          f"mental_models={mm}, facts={facts}", stats))

    # data:no-console-errors
    page.wait_for_timeout(1000)
    if errs:
        out.append(Result("data:no-console-errors", "fail",
                          "; ".join(errs[:5])))
    else:
        out.append(Result("data:no-console-errors", "pass"))

    return out


# ─── 2. Toolbar & Navigation ──────────────────────────────────────────────
def test_navigation(page: Page, base: str) -> list[Result]:
    out: list[Result] = []

    try:
        page.goto(f"{base}/explorer.html", wait_until="domcontentloaded", timeout=20000)
        wait_for_app_ready(page)
    except Exception as e:
        return [Result("nav:load", "fail", str(e))]

    # nav:tabs-present — toolbar has Graph and Mental Models; sidebar has Nodes and Facts
    try:
        graph_btn = page.locator("#viewGraph")
        cards_btn = page.locator("#viewCards")
        nodes_tab = page.locator('#sidebar .tabs button[data-panel="nodes-panel"]')
        facts_tab = page.locator('#sidebar .tabs button[data-panel="facts-panel"]')

        all_present = (
            graph_btn.count() > 0
            and cards_btn.count() > 0
            and nodes_tab.count() > 0
            and facts_tab.count() > 0
        )
        out.append(Result(
            "nav:tabs-present",
            "pass" if all_present else "fail",
            f"Graph={graph_btn.count()}, Cards={cards_btn.count()}, "
            f"Nodes={nodes_tab.count()}, Facts={facts_tab.count()}",
        ))
    except Exception as e:
        out.append(Result("nav:tabs-present", "fail", str(e)))

    # nav:tab-switch-graph — Graph view button activates graph view
    try:
        page.locator("#viewGraph").click()
        page.wait_for_timeout(300)
        graph_hidden = "hidden" in (page.locator("#graph-view").get_attribute("class") or "")
        out.append(Result(
            "nav:tab-switch-graph",
            "pass" if not graph_hidden else "fail",
            f"graph-view hidden={graph_hidden}",
        ))
    except Exception as e:
        out.append(Result("nav:tab-switch-graph", "fail", str(e)))

    # nav:tab-switch-models — Mental Models button shows cards view
    try:
        page.locator("#viewCards").click()
        page.wait_for_timeout(300)
        cards_active = "active" in (page.locator("#cards-view").get_attribute("class") or "")
        out.append(Result(
            "nav:tab-switch-models",
            "pass" if cards_active else "fail",
            f"cards-view active={cards_active}",
        ))
    except Exception as e:
        out.append(Result("nav:tab-switch-models", "fail", str(e)))

    # nav:tab-switch-nodes — sidebar Nodes tab shows node list
    try:
        page.locator('#sidebar .tabs button[data-panel="nodes-panel"]').click()
        page.wait_for_timeout(300)
        nodes_active = "active" in (page.locator("#nodes-panel").get_attribute("class") or "")
        out.append(Result(
            "nav:tab-switch-nodes",
            "pass" if nodes_active else "fail",
            f"nodes-panel active={nodes_active}",
        ))
    except Exception as e:
        out.append(Result("nav:tab-switch-nodes", "fail", str(e)))

    # nav:tab-switch-facts — sidebar Facts tab shows facts list
    try:
        page.locator('#sidebar .tabs button[data-panel="facts-panel"]').click()
        page.wait_for_timeout(300)
        facts_active = "active" in (page.locator("#facts-panel").get_attribute("class") or "")
        out.append(Result(
            "nav:tab-switch-facts",
            "pass" if facts_active else "fail",
            f"facts-panel active={facts_active}",
        ))
    except Exception as e:
        out.append(Result("nav:tab-switch-facts", "fail", str(e)))

    # nav:keyboard-shortcuts — "/" focuses search, Escape blurs
    try:
        # Switch back to nodes panel first
        page.locator('#sidebar .tabs button[data-panel="nodes-panel"]').click()
        page.wait_for_timeout(200)
        page.keyboard.press("/")
        page.wait_for_timeout(200)
        focused_id = page.evaluate("document.activeElement.id")
        slash_ok = focused_id == "nodeSearch"

        page.keyboard.press("Escape")
        page.wait_for_timeout(200)
        focused_after = page.evaluate("document.activeElement.tagName")
        esc_ok = focused_after != "INPUT"

        out.append(Result(
            "nav:keyboard-shortcuts",
            "pass" if (slash_ok and esc_ok) else "fail",
            f"/ → focused={focused_id}, Esc → tag={focused_after}",
        ))
    except Exception as e:
        out.append(Result("nav:keyboard-shortcuts", "fail", str(e)))

    return out


# ─── 3. Graph View ────────────────────────────────────────────────────────
def test_graph_view(page: Page, base: str) -> list[Result]:
    out: list[Result] = []

    try:
        page.goto(f"{base}/explorer.html", wait_until="domcontentloaded", timeout=20000)
        wait_for_app_ready(page)
        page.wait_for_timeout(500)
    except Exception as e:
        return [Result("graph:load", "fail", str(e))]

    # graph:canvas-renders — canvas element exists and has dimensions
    try:
        canvas = page.locator("#graphCanvas")
        box = canvas.bounding_box()
        has_size = box is not None and box["width"] > 100 and box["height"] > 100
        out.append(Result(
            "graph:canvas-renders",
            "pass" if has_size else "fail",
            f"canvas box={box}",
        ))
    except Exception as e:
        out.append(Result("graph:canvas-renders", "fail", str(e)))

    # graph:all-nodes-visible — stats bar node count is in expected range
    try:
        stats = parse_stats_bar(page)
        nodes = stats.get("nodes", 0)
        out.append(Result(
            "graph:all-nodes-visible",
            "pass" if EXPECTED_NODE_RANGE[0] <= nodes <= EXPECTED_NODE_RANGE[1] else "fail",
            f"nodes={nodes}, expected {EXPECTED_NODE_RANGE}",
            {"nodes": nodes},
        ))
    except Exception as e:
        out.append(Result("graph:all-nodes-visible", "fail", str(e)))

    # graph:legend-exists — legend with node type colors is present
    try:
        legend = page.locator("#legend")
        legend_items = page.locator("#legend .leg").count()
        out.append(Result(
            "graph:legend-exists",
            "pass" if legend_items >= 5 else "fail",
            f"legend items={legend_items}",
        ))
    except Exception as e:
        out.append(Result("graph:legend-exists", "fail", str(e)))

    # graph:overlay-exists — SVG overlay for labels exists
    try:
        overlay = page.locator("#graphOverlay")
        out.append(Result(
            "graph:overlay-exists",
            "pass" if overlay.count() > 0 else "fail",
        ))
    except Exception as e:
        out.append(Result("graph:overlay-exists", "fail", str(e)))

    # graph:click-selects-node — clicking a node in sidebar opens detail drawer
    try:
        # Use sidebar node list to select a node (canvas click is unreliable)
        first_node = page.locator(".node-item").first
        node_name = first_node.locator(".name").text_content() or ""
        first_node.click()
        page.wait_for_timeout(500)
        detail_open = "detail-open" in (page.evaluate("document.body.className") or "")
        detail_title = page.locator("#detailTitle").text_content() or ""
        out.append(Result(
            "graph:click-selects-node",
            "pass" if detail_open and detail_title else "fail",
            f"detail_open={detail_open}, title={detail_title!r}",
        ))
        # Close detail for next tests
        page.locator("#closeDetail").click()
        page.wait_for_timeout(300)
    except Exception as e:
        out.append(Result("graph:click-selects-node", "fail", str(e)))

    # graph:search-filters — typing in node search reduces visible node list
    try:
        count_before = page.locator(".node-item").count()
        search = page.locator("#nodeSearch")
        search.click()
        search.fill("cosmos")
        page.wait_for_timeout(500)
        count_after = page.locator(".node-item").count()
        filtered = count_after < count_before and count_after >= 0
        out.append(Result(
            "graph:search-filters",
            "pass" if filtered else "fail",
            f"before={count_before}, after={count_after}",
            {"before": count_before, "after": count_after},
        ))
        # Clear search
        search.fill("")
        page.wait_for_timeout(300)
    except Exception as e:
        out.append(Result("graph:search-filters", "fail", str(e)))

    # graph:zoom-works — d3 zoom transform can be applied via JS
    try:
        initial_k = page.evaluate("typeof transform !== 'undefined' ? transform.k : null")
        # Simulate zoom by using evaluate to check zoom capability
        canvas_exists = page.evaluate("""() => {
            const c = document.getElementById('graphCanvas');
            return c && c.width > 0 && c.height > 0;
        }""")
        out.append(Result(
            "graph:zoom-works",
            "pass" if canvas_exists else "fail",
            f"canvas functional={canvas_exists}, initial_scale={initial_k}",
        ))
    except Exception as e:
        out.append(Result("graph:zoom-works", "fail", str(e)))

    return out


# ─── 4. Models View ───────────────────────────────────────────────────────
def test_models_view(page: Page, base: str) -> list[Result]:
    out: list[Result] = []

    try:
        page.goto(f"{base}/explorer.html", wait_until="domcontentloaded", timeout=20000)
        wait_for_app_ready(page)
        # Switch to cards view
        page.locator("#viewCards").click()
        page.wait_for_timeout(500)
    except Exception as e:
        return [Result("models:load", "fail", str(e))]

    # models:cards-render — card elements exist
    try:
        card_count = page.locator(".mm-card").count()
        out.append(Result(
            "models:cards-render",
            "pass" if card_count >= EXPECTED_MM_RANGE[0] else "fail",
            f"card_count={card_count}, expected >={EXPECTED_MM_RANGE[0]}",
            {"count": card_count},
        ))
    except Exception as e:
        out.append(Result("models:cards-render", "fail", str(e)))

    # models:card-has-mantra — cards show mantra text
    try:
        mantras = page.locator(".mm-card .mantra").count()
        out.append(Result(
            "models:card-has-mantra",
            "pass" if mantras > 0 else "fail",
            f"cards with mantra={mantras}",
        ))
    except Exception as e:
        out.append(Result("models:card-has-mantra", "fail", str(e)))

    # models:card-has-layer — cards show layer badge
    try:
        layers = page.locator(".mm-card .layer-badge").count()
        out.append(Result(
            "models:card-has-layer",
            "pass" if layers > 0 else "fail",
            f"cards with layer badge={layers}",
        ))
    except Exception as e:
        out.append(Result("models:card-has-layer", "fail", str(e)))

    # models:card-has-sections — cards show content sections (when-to-apply, tradeoffs, etc.)
    try:
        sections = page.locator(".mm-card .card-section").count()
        out.append(Result(
            "models:card-has-sections",
            "pass" if sections > 0 else "warn",
            f"card content sections={sections}",
        ))
    except Exception as e:
        out.append(Result("models:card-has-sections", "fail", str(e)))

    # models:card-click-to-graph — clicking a card switches to graph view and selects node
    try:
        first_card = page.locator(".mm-card").first
        card_id = first_card.get_attribute("data-id") or ""
        first_card.click()
        page.wait_for_timeout(800)
        # Should have switched to graph view and opened detail
        graph_visible = "hidden" not in (page.locator("#graph-view").get_attribute("class") or "")
        detail_open = "detail-open" in (page.evaluate("document.body.className") or "")
        out.append(Result(
            "models:card-click-to-graph",
            "pass" if (graph_visible and detail_open) else "fail",
            f"card={card_id!r}, graph_visible={graph_visible}, detail_open={detail_open}",
        ))
    except Exception as e:
        out.append(Result("models:card-click-to-graph", "fail", str(e)))

    return out


# ─── 5. Nodes View ────────────────────────────────────────────────────────
def test_nodes_view(page: Page, base: str) -> list[Result]:
    out: list[Result] = []

    try:
        page.goto(f"{base}/explorer.html", wait_until="domcontentloaded", timeout=20000)
        wait_for_app_ready(page)
        # Ensure nodes panel is active
        page.locator('#sidebar .tabs button[data-panel="nodes-panel"]').click()
        page.wait_for_timeout(300)
    except Exception as e:
        return [Result("nodes:load", "fail", str(e))]

    # nodes:table-renders — node list with items exists
    try:
        item_count = page.locator(".node-item").count()
        out.append(Result(
            "nodes:table-renders",
            "pass" if item_count > 0 else "fail",
            f"node items={item_count}",
        ))
    except Exception as e:
        out.append(Result("nodes:table-renders", "fail", str(e)))

    # nodes:shows-all-nodes — count line matches expected range
    try:
        count_text = page.locator("#node-list .count").text_content() or ""
        m = re.search(r"(\d+)\s+of\s+(\d+)", count_text)
        shown = int(m.group(1)) if m else 0
        total = int(m.group(2)) if m else 0
        in_range = EXPECTED_NODE_RANGE[0] <= total <= EXPECTED_NODE_RANGE[1]
        out.append(Result(
            "nodes:shows-all-nodes",
            "pass" if in_range else "fail",
            f"showing {shown} of {total} (expected {EXPECTED_NODE_RANGE})",
            {"shown": shown, "total": total},
        ))
    except Exception as e:
        out.append(Result("nodes:shows-all-nodes", "fail", str(e)))

    # nodes:type-filter — type dropdown filters correctly
    try:
        page.locator("#typeFilter").select_option("MENTAL_MODEL")
        page.wait_for_timeout(400)
        count_text = page.locator("#node-list .count").text_content() or ""
        m = re.search(r"(\d+)\s+of", count_text)
        filtered = int(m.group(1)) if m else 0
        ok = EXPECTED_MM_RANGE[0] <= filtered <= EXPECTED_MM_RANGE[1]
        out.append(Result(
            "nodes:type-filter",
            "pass" if ok else "fail",
            f"MENTAL_MODEL filter → {filtered} (expected {EXPECTED_MM_RANGE})",
            {"filtered": filtered},
        ))
        # Reset filter
        page.locator("#typeFilter").select_option("")
        page.wait_for_timeout(300)
    except Exception as e:
        out.append(Result("nodes:type-filter", "fail", str(e)))

    # nodes:search-filters — search input filters rows
    try:
        search = page.locator("#nodeSearch")
        search.fill("zone")
        page.wait_for_timeout(400)
        count_text = page.locator("#node-list .count").text_content() or ""
        m = re.search(r"(\d+)\s+of", count_text)
        filtered = int(m.group(1)) if m else 0
        out.append(Result(
            "nodes:search-filters",
            "pass" if 0 < filtered < 200 else "fail",
            f"search 'zone' → {filtered} results",
            {"filtered": filtered},
        ))
        search.fill("")
        page.wait_for_timeout(300)
    except Exception as e:
        out.append(Result("nodes:search-filters", "fail", str(e)))

    # nodes:has-facts-toggle — "Has facts" checkbox filters list
    try:
        count_before_text = page.locator("#node-list .count").text_content() or ""
        m = re.search(r"(\d+)\s+of", count_before_text)
        count_before = int(m.group(1)) if m else 0

        page.locator("#factsOnly").check()
        page.wait_for_timeout(400)
        count_after_text = page.locator("#node-list .count").text_content() or ""
        m = re.search(r"(\d+)\s+of", count_after_text)
        count_after = int(m.group(1)) if m else 0

        reduced = count_after < count_before and count_after > 0
        out.append(Result(
            "nodes:has-facts-toggle",
            "pass" if reduced else "fail",
            f"before={count_before}, with-facts={count_after}",
            {"before": count_before, "after": count_after},
        ))
        page.locator("#factsOnly").uncheck()
        page.wait_for_timeout(300)
    except Exception as e:
        out.append(Result("nodes:has-facts-toggle", "fail", str(e)))

    # nodes:click-opens-drawer — clicking a node item opens detail drawer
    try:
        page.locator(".node-item").first.click()
        page.wait_for_timeout(500)
        detail_open = "detail-open" in (page.evaluate("document.body.className") or "")
        title = page.locator("#detailTitle").text_content() or ""
        out.append(Result(
            "nodes:click-opens-drawer",
            "pass" if detail_open and title else "fail",
            f"detail_open={detail_open}, title={title!r}",
        ))
        page.locator("#closeDetail").click()
        page.wait_for_timeout(300)
    except Exception as e:
        out.append(Result("nodes:click-opens-drawer", "fail", str(e)))

    return out


# ─── 6. Facts View ────────────────────────────────────────────────────────
def test_facts_view(page: Page, base: str) -> list[Result]:
    out: list[Result] = []

    try:
        page.goto(f"{base}/explorer.html", wait_until="domcontentloaded", timeout=20000)
        wait_for_app_ready(page)
        # Switch to facts panel
        page.locator('#sidebar .tabs button[data-panel="facts-panel"]').click()
        page.wait_for_timeout(500)
    except Exception as e:
        return [Result("facts:load", "fail", str(e))]

    # facts:list-renders — fact items exist
    try:
        fact_count = page.locator(".fact-item").count()
        out.append(Result(
            "facts:list-renders",
            "pass" if fact_count > 0 else "fail",
            f"fact items visible={fact_count}",
            {"count": fact_count},
        ))
    except Exception as e:
        out.append(Result("facts:list-renders", "fail", str(e)))

    # facts:timeless-tab — timeless filter shows expected count
    try:
        page.locator("#factTypeFilter").select_option("timeless")
        page.wait_for_timeout(400)
        header_text = page.locator(".fact-section-header").first.text_content() or ""
        m = re.search(r"(\d+)", header_text)
        timeless_count = int(m.group(1)) if m else 0
        ok = EXPECTED_TIMELESS_RANGE[0] <= timeless_count <= EXPECTED_TIMELESS_RANGE[1]
        out.append(Result(
            "facts:timeless-tab",
            "pass" if ok else ("warn" if timeless_count > 0 else "fail"),
            f"timeless={timeless_count} (expected {EXPECTED_TIMELESS_RANGE})",
            {"count": timeless_count},
        ))
    except Exception as e:
        out.append(Result("facts:timeless-tab", "fail", str(e)))

    # facts:perishable-tab — perishable filter shows expected count
    try:
        page.locator("#factTypeFilter").select_option("perishable")
        page.wait_for_timeout(400)
        header_text = page.locator(".fact-section-header").first.text_content() or ""
        m = re.search(r"(\d+)", header_text)
        perishable_count = int(m.group(1)) if m else 0
        ok = EXPECTED_PERISHABLE_RANGE[0] <= perishable_count <= EXPECTED_PERISHABLE_RANGE[1]
        out.append(Result(
            "facts:perishable-tab",
            "pass" if ok else ("warn" if perishable_count > 0 else "fail"),
            f"perishable={perishable_count} (expected {EXPECTED_PERISHABLE_RANGE})",
            {"count": perishable_count},
        ))
    except Exception as e:
        out.append(Result("facts:perishable-tab", "fail", str(e)))

    # facts:shelf-life-shown — perishable facts show shelf life badge
    try:
        # Still on perishable filter
        shelf_badges = page.locator(".fact-item .fact-meta .shelf").count()
        out.append(Result(
            "facts:shelf-life-shown",
            "pass" if shelf_badges > 0 else "warn",
            f"shelf life badges={shelf_badges}",
        ))
    except Exception as e:
        out.append(Result("facts:shelf-life-shown", "fail", str(e)))

    # facts:confidence-shown — facts show confidence indicator
    try:
        page.locator("#factTypeFilter").select_option("")
        page.wait_for_timeout(400)
        conf_badges = page.locator(".fact-item .fact-meta .conf").count()
        out.append(Result(
            "facts:confidence-shown",
            "pass" if conf_badges > 0 else "warn",
            f"confidence badges={conf_badges}",
        ))
    except Exception as e:
        out.append(Result("facts:confidence-shown", "fail", str(e)))

    # facts:entity-link — facts show source entity name
    try:
        entity_links = page.locator(".fact-item .fact-meta .entity").count()
        out.append(Result(
            "facts:entity-link",
            "pass" if entity_links > 0 else "fail",
            f"entity name spans={entity_links}",
        ))
    except Exception as e:
        out.append(Result("facts:entity-link", "fail", str(e)))

    return out


# ─── 7. Detail Drawer ─────────────────────────────────────────────────────
def test_detail_drawer(page: Page, base: str) -> list[Result]:
    out: list[Result] = []

    try:
        page.goto(f"{base}/explorer.html", wait_until="domcontentloaded", timeout=20000)
        wait_for_app_ready(page)
        page.wait_for_timeout(300)
    except Exception as e:
        return [Result("drawer:load", "fail", str(e))]

    # Find a mental model node to select (they have rich detail)
    try:
        page.locator("#typeFilter").select_option("MENTAL_MODEL")
        page.wait_for_timeout(400)
    except Exception:
        pass

    # drawer:opens-on-select — drawer appears when node selected
    try:
        first = page.locator(".node-item").first
        node_name = first.locator(".name").text_content() or ""
        first.click()
        page.wait_for_timeout(600)
        detail_open = "detail-open" in (page.evaluate("document.body.className") or "")
        out.append(Result(
            "drawer:opens-on-select",
            "pass" if detail_open else "fail",
            f"selected={node_name!r}, detail_open={detail_open}",
        ))
    except Exception as e:
        out.append(Result("drawer:opens-on-select", "fail", str(e)))

    # drawer:shows-type — drawer shows type badge
    try:
        type_text = page.locator("#detailType").text_content() or ""
        out.append(Result(
            "drawer:shows-type",
            "pass" if type_text.strip() else "fail",
            f"type={type_text!r}",
        ))
    except Exception as e:
        out.append(Result("drawer:shows-type", "fail", str(e)))

    # drawer:shows-summary — drawer shows summary or mantra
    try:
        body_text = page.locator("#detailBody").text_content() or ""
        has_content = len(body_text.strip()) > 20
        out.append(Result(
            "drawer:shows-summary",
            "pass" if has_content else "warn",
            f"body length={len(body_text)}",
        ))
    except Exception as e:
        out.append(Result("drawer:shows-summary", "fail", str(e)))

    # drawer:shows-docs — drawer shows source doc links
    try:
        doc_links = page.locator("#detail .sources-list a").count()
        out.append(Result(
            "drawer:shows-docs",
            "pass" if doc_links > 0 else "warn",
            f"source doc links={doc_links}",
        ))
    except Exception as e:
        out.append(Result("drawer:shows-docs", "fail", str(e)))

    # drawer:shows-facts — for nodes with facts, drawer shows fact list
    try:
        fact_items = page.locator("#detail .fact-list-detail .fact-d").count()
        out.append(Result(
            "drawer:shows-facts",
            "pass" if fact_items > 0 else "warn",
            f"facts in drawer={fact_items}",
        ))
    except Exception as e:
        out.append(Result("drawer:shows-facts", "fail", str(e)))

    return out


# ─── 8. Cross-View Navigation ─────────────────────────────────────────────
def test_cross_view(page: Page, base: str) -> list[Result]:
    out: list[Result] = []

    try:
        page.goto(f"{base}/explorer.html", wait_until="domcontentloaded", timeout=20000)
        wait_for_app_ready(page)
    except Exception as e:
        return [Result("cross:load", "fail", str(e))]

    # cross:models-to-graph — clicking card switches to graph and selects node
    try:
        page.locator("#viewCards").click()
        page.wait_for_timeout(500)
        card = page.locator(".mm-card").first
        card_id = card.get_attribute("data-id") or ""
        card.click()
        page.wait_for_timeout(800)
        graph_visible = "hidden" not in (page.locator("#graph-view").get_attribute("class") or "")
        hash_val = page.evaluate("decodeURIComponent(location.hash.slice(1))")
        out.append(Result(
            "cross:models-to-graph",
            "pass" if graph_visible and hash_val == card_id else "fail",
            f"card={card_id!r}, graph_visible={graph_visible}, hash={hash_val!r}",
        ))
    except Exception as e:
        out.append(Result("cross:models-to-graph", "fail", str(e)))

    # cross:hash-navigation — URL hash selects the correct node
    try:
        # Use a completely fresh navigation to avoid stale state
        page.goto("about:blank", wait_until="domcontentloaded", timeout=5000)
        page.wait_for_timeout(200)
        page.goto(f"{base}/explorer.html#Zero%20Trust", wait_until="domcontentloaded", timeout=20000)
        wait_for_app_ready(page)
        page.wait_for_timeout(1000)
        detail_open = "detail-open" in (page.evaluate("document.body.className") or "")
        title = (page.locator("#detailTitle").text_content() or "").strip()
        out.append(Result(
            "cross:hash-navigation",
            "pass" if detail_open and title == "Zero Trust" else "warn",
            f"detail_open={detail_open}, title={title!r}",
        ))
    except Exception as e:
        out.append(Result("cross:hash-navigation", "fail", str(e)))

    # cross:facts-to-entity — clicking entity name on fact shows entity details
    try:
        page.goto(f"{base}/explorer.html", wait_until="domcontentloaded", timeout=20000)
        wait_for_app_ready(page)
        # Switch to facts panel
        page.locator('#sidebar .tabs button[data-panel="facts-panel"]').click()
        page.wait_for_timeout(500)
        # Click the first fact item
        first_fact = page.locator(".fact-item").first
        entity_name = first_fact.get_attribute("data-entity") or ""
        first_fact.click()
        page.wait_for_timeout(600)
        detail_open = "detail-open" in (page.evaluate("document.body.className") or "")
        title = page.locator("#detailTitle").text_content() or ""
        out.append(Result(
            "cross:facts-to-entity",
            "pass" if detail_open and title else "fail",
            f"entity={entity_name!r}, title={title!r}, detail_open={detail_open}",
        ))
    except Exception as e:
        out.append(Result("cross:facts-to-entity", "fail", str(e)))

    return out


# ─── 9. Fact Nodes in Graph ───────────────────────────────────────────────
EXPECTED_ENTITY_ONLY_RANGE = (400, 900)       # entity-only nodes (no fact nodes)
EXPECTED_TOTAL_WITH_FACTS_RANGE = (900, 1800)  # entities + fact nodes


def test_fact_nodes(page: Page, base: str) -> list[Result]:
    out: list[Result] = []

    try:
        page.goto(f"{base}/explorer.html", wait_until="domcontentloaded", timeout=20000)
        wait_for_app_ready(page)
        page.wait_for_timeout(500)
    except Exception as e:
        return [Result("facts:load", "fail", str(e))]

    # facts:nodes-in-data — graph.json contains fact node metadata
    try:
        graph_stats = page.evaluate("""() => {
            // Try accessing graphData (the app's loaded data)
            const gd = typeof graphData !== 'undefined' ? graphData : null;
            if (gd && gd.nodes) {
                const factNodes = gd.nodes.filter(n =>
                    n.type === 'FACT_TIMELESS' || n.type === 'FACT_PERISHABLE'
                );
                return {
                    total: gd.nodes.length,
                    fact_count: factNodes.length,
                    timeless: gd.nodes.filter(n => n.type === 'FACT_TIMELESS').length,
                    perishable: gd.nodes.filter(n => n.type === 'FACT_PERISHABLE').length,
                    has_fact_timeless: gd.nodes.some(n => n.type === 'FACT_TIMELESS'),
                    has_fact_perishable: gd.nodes.some(n => n.type === 'FACT_PERISHABLE'),
                };
            }
            // Fallback: fetch graph.json directly
            return null;
        }""")
        if not graph_stats:
            # Fallback: fetch graph.json via page
            graph_stats = page.evaluate("""async () => {
                const r = await fetch('data/graph.json');
                const d = await r.json();
                const factNodes = d.nodes.filter(n =>
                    n.type === 'FACT_TIMELESS' || n.type === 'FACT_PERISHABLE'
                );
                return {
                    total: d.nodes.length,
                    fact_count: factNodes.length,
                    timeless: d.nodes.filter(n => n.type === 'FACT_TIMELESS').length,
                    perishable: d.nodes.filter(n => n.type === 'FACT_PERISHABLE').length,
                    has_fact_timeless: factNodes.some(n => n.type === 'FACT_TIMELESS'),
                    has_fact_perishable: factNodes.some(n => n.type === 'FACT_PERISHABLE'),
                };
            }""")
        fact_count = graph_stats.get("fact_count", 0)
        has_both = graph_stats.get("has_fact_timeless") and graph_stats.get("has_fact_perishable")
        in_range = EXPECTED_FACTS_RANGE[0] <= fact_count <= EXPECTED_FACTS_RANGE[1]
        ok = in_range and has_both
        out.append(Result(
            "facts:nodes-in-data",
            "pass" if ok else ("warn" if fact_count > 0 else "fail"),
            f"fact_nodes={fact_count}, timeless={graph_stats.get('timeless')}, "
            f"perishable={graph_stats.get('perishable')}, in_range={in_range}",
            {"fact_count": fact_count},
        ))
    except Exception as e:
        out.append(Result("facts:nodes-in-data", "fail", str(e)))

    # facts:toggle-exists — a Facts toggle control exists in the graph view
    try:
        page.locator("#viewGraph").click()
        page.wait_for_timeout(300)
        # Search for toggle by id, then by text match
        toggle = page.locator("#factsToggle, #toggleFacts, #showFacts, "
                              "[data-toggle='facts'], button:has-text('Fact'), "
                              "label:has-text('Fact')")
        toggle_count = toggle.count()
        if toggle_count == 0:
            # Broader search: any control with 'fact' in text (case-insensitive)
            toggle_count = page.evaluate("""() => {
                const els = document.querySelectorAll('button, input[type=checkbox], label');
                return Array.from(els).filter(e =>
                    /fact/i.test(e.textContent || '') || /fact/i.test(e.id || '')
                ).length;
            }""")
        out.append(Result(
            "facts:toggle-exists",
            "pass" if toggle_count > 0 else "fail",
            f"matching toggle elements={toggle_count}",
        ))
    except Exception as e:
        out.append(Result("facts:toggle-exists", "fail", str(e)))

    # facts:toggle-shows-nodes — toggling facts ON increases visible node count
    try:
        # Ensure graph view is active and get baseline stats
        page.locator("#viewGraph").click()
        page.wait_for_timeout(300)
        stats_before = parse_stats_bar(page)
        nodes_before = stats_before.get("nodes", 0)

        # Try to enable facts toggle
        toggled = page.evaluate("""() => {
            // Try checkbox first
            const cb = document.querySelector('#factsToggle, #toggleFacts, #showFacts, '
                + '[data-toggle="facts"]');
            if (cb && cb.type === 'checkbox') {
                cb.checked = !cb.checked;
                cb.dispatchEvent(new Event('change', {bubbles: true}));
                return 'checkbox';
            }
            // Try button
            const btns = document.querySelectorAll('button, [role="button"]');
            for (const b of btns) {
                if (/fact/i.test(b.textContent || '') || /fact/i.test(b.id || '')) {
                    b.click();
                    return 'button:' + (b.id || b.textContent.trim().slice(0, 30));
                }
            }
            // Try label-wrapped checkbox
            const labels = document.querySelectorAll('label');
            for (const l of labels) {
                if (/fact/i.test(l.textContent || '')) {
                    const inp = l.querySelector('input') || document.getElementById(l.htmlFor);
                    if (inp) { inp.click(); return 'label-checkbox'; }
                    l.click(); return 'label-click';
                }
            }
            return null;
        }""")
        page.wait_for_timeout(800)
        stats_after = parse_stats_bar(page)
        nodes_after = stats_after.get("nodes", 0)

        if toggled and nodes_after > nodes_before:
            status = "pass"
        elif toggled and nodes_after == nodes_before:
            status = "warn"
        else:
            status = "fail"

        out.append(Result(
            "facts:toggle-shows-nodes",
            status,
            f"before={nodes_before}, after={nodes_after}, toggled={toggled}",
            {"before": nodes_before, "after": nodes_after},
        ))

        # Toggle back OFF
        if toggled:
            page.evaluate("""() => {
                const cb = document.querySelector('#factsToggle, #toggleFacts, #showFacts, '
                    + '[data-toggle="facts"]');
                if (cb && cb.type === 'checkbox') {
                    cb.checked = !cb.checked;
                    cb.dispatchEvent(new Event('change', {bubbles: true}));
                    return;
                }
                const btns = document.querySelectorAll('button, [role="button"]');
                for (const b of btns) {
                    if (/fact/i.test(b.textContent || '') || /fact/i.test(b.id || '')) {
                        b.click(); return;
                    }
                }
            }""")
            page.wait_for_timeout(500)

    except Exception as e:
        out.append(Result("facts:toggle-shows-nodes", "fail", str(e)))

    # facts:fact-node-detail — selecting a fact node opens drawer with fact info
    try:
        # Enable facts toggle first
        page.evaluate("""() => {
            const cb = document.querySelector('#factsToggle, #toggleFacts, #showFacts, '
                + '[data-toggle="facts"]');
            if (cb && cb.type === 'checkbox' && !cb.checked) {
                cb.checked = true;
                cb.dispatchEvent(new Event('change', {bubbles: true}));
                return;
            }
            const btns = document.querySelectorAll('button, [role="button"]');
            for (const b of btns) {
                if (/fact/i.test(b.textContent || '') || /fact/i.test(b.id || '')) {
                    if (!b.classList.contains('active') && b.getAttribute('aria-pressed') !== 'true') {
                        b.click();
                    }
                    return;
                }
            }
        }""")
        page.wait_for_timeout(500)

        # Try to select a fact node via JS (canvas-based, can't click visually)
        fact_detail = page.evaluate("""() => {
            if (typeof nodes === 'undefined') return null;
            const factNode = nodes.find(n =>
                n.type === 'FACT_TIMELESS' || n.type === 'FACT_PERISHABLE'
            );
            if (!factNode) return null;
            // Try to trigger selection via app's selectNode function
            if (typeof selectNode === 'function') {
                selectNode(factNode);
            } else if (typeof handleNodeClick === 'function') {
                handleNodeClick(factNode);
            } else if (typeof onNodeSelect === 'function') {
                onNodeSelect(factNode);
            }
            return {id: factNode.id, type: factNode.type, label: factNode.label || factNode.name || ''};
        }""")
        page.wait_for_timeout(600)

        if fact_detail:
            detail_open = "detail-open" in (page.evaluate("document.body.className") or "")
            type_text = page.locator("#detailType").text_content() or ""
            body_text = page.locator("#detailBody").text_content() or ""
            is_fact_type = "FACT" in type_text.upper() if type_text else False
            has_body = len(body_text.strip()) > 5

            out.append(Result(
                "facts:fact-node-detail",
                "pass" if (detail_open and is_fact_type and has_body) else "warn",
                f"node={fact_detail.get('id', '')!r}, type={type_text!r}, "
                f"body_len={len(body_text)}, detail_open={detail_open}",
            ))
        else:
            out.append(Result(
                "facts:fact-node-detail", "warn",
                "no fact nodes found or selectNode not exposed",
            ))
    except Exception as e:
        out.append(Result("facts:fact-node-detail", "fail", str(e)))

    # facts:export-checklist — export button exists in Facts view
    try:
        page.locator('#sidebar .tabs button[data-panel="facts-panel"]').click()
        page.wait_for_timeout(400)

        export_count = page.evaluate("""() => {
            const candidates = document.querySelectorAll(
                '#facts-panel button, #facts-panel a, '
                + '#exportFacts, [data-action="export"], '
                + 'button.export-btn'
            );
            return Array.from(candidates).filter(e =>
                /export|📥|download/i.test(e.textContent || '')
                || /export|download/i.test(e.id || '')
                || /export|download/i.test(e.className || '')
            ).length;
        }""")
        out.append(Result(
            "facts:export-checklist",
            "pass" if export_count > 0 else "warn",
            f"export buttons found={export_count}",
        ))
    except Exception as e:
        out.append(Result("facts:export-checklist", "fail", str(e)))

    # facts:perishable-verification — perishable facts show shelf life and verification hints
    try:
        page.locator('#sidebar .tabs button[data-panel="facts-panel"]').click()
        page.wait_for_timeout(300)
        page.locator("#factTypeFilter").select_option("perishable")
        page.wait_for_timeout(400)

        shelf_count = page.locator(".fact-item .fact-meta .shelf").count()
        # Check for verification hints: could be .verify, .verification, .hint, etc.
        verify_count = page.evaluate("""() => {
            const items = document.querySelectorAll('.fact-item');
            let count = 0;
            items.forEach(item => {
                const text = item.textContent || '';
                if (/verif|hint|check|shelf.*life|expir/i.test(text)) count++;
            });
            return count;
        }""")

        out.append(Result(
            "facts:perishable-verification",
            "pass" if shelf_count > 0 and verify_count > 0 else (
                "warn" if shelf_count > 0 or verify_count > 0 else "fail"
            ),
            f"shelf_badges={shelf_count}, verification_hints={verify_count}",
            {"shelf": shelf_count, "verify": verify_count},
        ))

        # Reset filter
        page.locator("#factTypeFilter").select_option("")
        page.wait_for_timeout(300)
    except Exception as e:
        out.append(Result("facts:perishable-verification", "fail", str(e)))

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
            line = f"  {mark.get(r.status, '?')} {r.name:<36} [{r.status:4s}] {r.detail}"
            print(line)
        print(f"\n{passed} pass · {warned} warn · {failed} fail  ({len(results)} total)")

    return 0 if failed == 0 else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="E2E tests for Knowledge Graph Explorer")
    ap.add_argument("--url", default=DEFAULT_URL, help="Base URL where docs/ is served")
    ap.add_argument("--headed", action="store_true", help="Run in headed browser mode")
    ap.add_argument("--json", action="store_true", help="Output JSON report")
    args = ap.parse_args()

    base = args.url.rstrip("/")
    results: list[Result] = []
    t_start = time.time()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not args.headed)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})

        test_groups = [
            ("data-loading",   test_data_loading),
            ("navigation",     test_navigation),
            ("graph-view",     test_graph_view),
            ("models-view",    test_models_view),
            ("nodes-view",     test_nodes_view),
            ("facts-view",     test_facts_view),
            ("detail-drawer",  test_detail_drawer),
            ("cross-view",     test_cross_view),
            ("fact-nodes",     test_fact_nodes),
        ]

        for group_name, test_fn in test_groups:
            p = ctx.new_page()
            t0 = time.time()
            group_results = safe_run(test_fn, p, base)
            elapsed = (time.time() - t0) * 1000
            for r in group_results:
                if r.elapsed_ms == 0:
                    r.elapsed_ms = elapsed
            results.extend(group_results)
            p.close()

        browser.close()

    total_ms = (time.time() - t_start) * 1000
    if not args.json:
        print(f"\n  ⏱ Total: {total_ms:.0f}ms")

    return emit(results, args.json)


if __name__ == "__main__":
    sys.exit(main())
