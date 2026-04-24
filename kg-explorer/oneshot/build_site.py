#!/usr/bin/env python3
"""One command to rebuild ALL site data.

Pipeline:
  1. (optional) Mine taxonomy/cards from LightRAG with LLM
  2. Export LightRAG GraphML -> graph.json
  3. Build site-data.json
  4. Generate per-card radial tree HTMLs
  5. Copy every produced artifact into docs/

HTML shells (docs/index.html, docs/graph.html, docs/mental_models/index.html)
are static - they load the JSON files at runtime, so they never need regeneration.

Usage:
    python3 build_site.py                 # rebuild everything (needs copilot-api proxy)
    python3 build_site.py --skip-mine     # reuse cached taxonomy/cards/summary
    python3 build_site.py --skip-trees    # skip per-card tree diagrams
    python3 build_site.py --top 60        # number of cards to generate when mining
"""
from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DOCS = ROOT.parent / "docs"
MM_SRC = ROOT / "mental_models"
MM_DOCS = DOCS / "mental_models"
CARDS_SRC = MM_SRC / "cards"
CARDS_DOCS = MM_DOCS / "cards"
GRAPH_JSON_SRC = ROOT / "graph.json"
GRAPH_JSON_DOCS = DOCS / "graph.json"

PROXY_URL = "http://127.0.0.1:11435"


def proxy_up() -> bool:
    try:
        urllib.request.urlopen(PROXY_URL, timeout=3)
        return True
    except Exception:
        return False


def snapshot_stats() -> dict:
    stats = {}
    try:
        g = json.loads(GRAPH_JSON_SRC.read_text())
        stats["graph_nodes"] = g.get("meta", {}).get("nodes")
        stats["graph_edges"] = g.get("meta", {}).get("edges")
        stats["graph_docs"] = g.get("meta", {}).get("docs")
    except Exception:
        pass
    try:
        stats["cards"] = len(json.loads((MM_SRC / "cards.json").read_text()))
    except Exception:
        pass
    try:
        stats["taxonomy"] = len(json.loads((MM_SRC / "taxonomy.json").read_text()))
    except Exception:
        pass
    return stats


def export_graph() -> None:
    """Export LightRAG GraphML -> kg-explorer/graph.json (no proxy needed)."""
    print("\n[1/5] Exporting LightRAG graph -> graph.json")
    import export_lightrag_graph
    export_lightrag_graph.build_d3_graph()


async def run_mining(top: int) -> None:
    """Run the mental model miner: classify entities + emit cards + summary."""
    print(f"\n[2/5] Mining mental models (top={top}) - needs copilot-api proxy")
    import mine_mental_models as mm

    # Replicate mm.main() without argparse, so we can pass args programmatically.
    nodes, edges = mm.load_graph()
    print(f"  graph: {len(nodes)} nodes, {len(edges)} edges")
    centrality = mm.compute_centrality(nodes, edges)
    bridge_scores = mm.find_bridges(edges)
    descriptions = {
        nid: data.get("description", data.get("entity_type", ""))
        for nid, data in nodes.items()
    }
    sorted_entities = sorted(nodes.keys(), key=lambda n: centrality.get(n, 0), reverse=True)

    mm.OUT_DIR.mkdir(exist_ok=True)
    print(f"  classifying {len(sorted_entities)} entities...")
    taxonomy: list[dict] = []
    for i in range(0, len(sorted_entities), 40):
        batch = sorted_entities[i:i + 40]
        try:
            taxonomy.extend(await mm.classify_entities(batch, descriptions))
        except Exception as e:
            print(f"    batch {i}: {e}")
            taxonomy.extend([{"entity": e, "category": "OTHER"} for e in batch])
    (mm.OUT_DIR / "taxonomy.json").write_text(json.dumps(taxonomy, indent=2))

    mental_models = [t for t in taxonomy if t["category"] == "MENTAL_MODEL"]
    mental_models.sort(key=lambda t: centrality.get(t["entity"], 0), reverse=True)

    cards = await mm.extract_mental_model_cards(mental_models[:top], nodes, edges, max_cards=top)
    (mm.OUT_DIR / "cards.json").write_text(json.dumps(cards, indent=2))

    from collections import Counter
    cat_counts = Counter(t["category"] for t in taxonomy)
    tradeoffs = [t["entity"] for t in taxonomy if t["category"] == "TRADEOFF"]
    anti_patterns = [t["entity"] for t in taxonomy if t["category"] == "ANTI_PATTERN"]
    summary = {
        "total_entities": len(nodes),
        "total_edges": len(edges),
        "classified": len(taxonomy),
        "categories": dict(cat_counts.most_common()),
        "top_mental_models": [
            {
                "name": mm_["entity"],
                "centrality": centrality.get(mm_["entity"], 0),
                "bridge_score": round(bridge_scores.get(mm_["entity"], 0), 3),
            }
            for mm_ in mental_models[:top]
        ],
        "tradeoffs": tradeoffs,
        "anti_patterns": anti_patterns,
    }
    (mm.OUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2))
    print(f"  wrote taxonomy ({len(taxonomy)}), cards ({len(cards)}), summary")


def build_site_data() -> None:
    """Produce mental_models/site-data.json (mirrored to docs/)."""
    print("\n[3/5] Building site-data.json")
    import datetime
    import os
    from collections import defaultdict

    cards = json.loads((MM_SRC / "cards.json").read_text())
    taxonomy = json.loads((MM_SRC / "taxonomy.json").read_text())
    summary = json.loads((MM_SRC / "summary.json").read_text())

    categories: dict[str, list[str]] = defaultdict(list)
    for t in taxonomy:
        categories[t["category"]].append(t["entity"])
    for cat in categories:
        categories[cat].sort(key=str.lower)
    cat_counts = {cat: len(items) for cat, items in categories.items()}

    cards_dir = CARDS_DOCS
    if cards_dir.exists():
        card_slugs = sorted(
            f.replace(".html", "")
            for f in os.listdir(cards_dir)
            if f.endswith(".html") and f != "index.html"
        )
    else:
        card_slugs = []

    doc_status_path = ROOT / "lightrag_data" / "kv_store_doc_status.json"
    docs_count = 0
    if doc_status_path.exists():
        try:
            docs_count = len(json.loads(doc_status_path.read_text()))
        except Exception:
            docs_count = 0

    stats = {
        "docs": docs_count,
        "entities": summary.get("total_entities", sum(cat_counts.values())),
        "relations": summary.get("total_edges", 0),
        "cards": len(cards),
        "mental_models": cat_counts.get("MENTAL_MODEL", 0),
        "patterns": cat_counts.get("PATTERN", 0),
        "anti_patterns": cat_counts.get("ANTI_PATTERN", 0),
        "tradeoffs": cat_counts.get("TRADEOFF", 0),
        "azure_services": cat_counts.get("AZURE_SERVICE", 0),
        "processes": cat_counts.get("PROCESS", 0),
        "metrics": cat_counts.get("METRIC", 0),
        "concepts": cat_counts.get("CONCEPT", 0),
    }

    site = {
        "generated_by": "build_site.py",
        "generated_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "schema_version": 1,
        "stats": stats,
        "cards": cards,
        "taxonomy": dict(categories),
        "category_counts": cat_counts,
        "anti_patterns": sorted(categories.get("ANTI_PATTERN", []), key=str.lower),
        "tradeoffs": sorted(categories.get("TRADEOFF", []), key=str.lower),
        "top_mental_models": summary.get("top_mental_models", []),
        "card_slugs": card_slugs,
    }

    payload = json.dumps(site, indent=2, ensure_ascii=False)
    MM_SRC.mkdir(exist_ok=True)
    MM_DOCS.mkdir(parents=True, exist_ok=True)
    (MM_SRC / "site-data.json").write_text(payload, encoding="utf-8")
    (MM_DOCS / "site-data.json").write_text(payload, encoding="utf-8")
    print(f"  stats: {stats['docs']} docs, {stats['entities']} entities, "
          f"{stats['relations']} relations, {stats['cards']} cards")


def generate_trees() -> None:
    print("\n[4/5] Generating per-card tree diagrams")
    import networkx as nx
    import generate_card_diagram as gcd

    graph = nx.read_graphml(gcd.GRAPH_PATH)
    tax = gcd.load_taxonomy()
    cards = json.loads(gcd.CARDS_PATH.read_text())
    for c in cards:
        gcd.generate_for_card(c, graph, tax)
    gcd.generate_index(cards)
    print(f"  generated {len(cards)} card diagrams + index")


def copy_to_docs() -> None:
    """Mirror every produced artifact into docs/."""
    print("\n[5/5] Copying artifacts to docs/")
    MM_DOCS.mkdir(parents=True, exist_ok=True)

    # Top-level graph.json (consumed by docs/graph.html).
    shutil.copy2(GRAPH_JSON_SRC, GRAPH_JSON_DOCS)
    print(f"  {GRAPH_JSON_DOCS.relative_to(DOCS.parent)}")

    # Mental-models JSON data.
    for name in ("cards.json", "taxonomy.json", "summary.json", "site-data.json"):
        src = MM_SRC / name
        if src.exists():
            shutil.copy2(src, MM_DOCS / name)
            print(f"  {(MM_DOCS / name).relative_to(DOCS.parent)}")

    # Per-card tree HTMLs + their index.
    if CARDS_SRC.exists():
        CARDS_DOCS.mkdir(parents=True, exist_ok=True)
        for f in CARDS_SRC.glob("*.html"):
            shutil.copy2(f, CARDS_DOCS / f.name)
        print(f"  {CARDS_DOCS.relative_to(DOCS.parent)}/ ({len(list(CARDS_SRC.glob('*.html')))} files)")


def print_summary(before: dict, after: dict) -> None:
    print("\n" + "=" * 60)
    print("BUILD COMPLETE")
    print("=" * 60)
    keys = ["graph_docs", "graph_nodes", "graph_edges", "taxonomy", "cards"]
    labels = {
        "graph_docs": "docs",
        "graph_nodes": "graph nodes",
        "graph_edges": "graph edges",
        "taxonomy": "classified entities",
        "cards": "mental-model cards",
    }
    for k in keys:
        b, a = before.get(k), after.get(k)
        arrow = "" if b == a else f"  (was {b})"
        print(f"  {labels[k]:<20} {a}{arrow}")


async def run(args: argparse.Namespace) -> int:
    before = snapshot_stats()

    proxy_ok = proxy_up()
    if not proxy_ok:
        print(f"⚠️  copilot-api proxy not reachable at {PROXY_URL}")
        if not args.skip_mine:
            print("    mining requires the proxy. Start it or use --skip-mine.")
            return 2
        print("    continuing with cached taxonomy/cards.")

    export_graph()

    if not args.skip_mine:
        await run_mining(args.top)
    else:
        print("\n[2/5] SKIPPED mining (using cached taxonomy/cards)")

    build_site_data()

    if not args.skip_trees:
        generate_trees()
    else:
        print("\n[4/5] SKIPPED tree diagram generation")

    copy_to_docs()
    print_summary(before, snapshot_stats())
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skip-mine", action="store_true", help="reuse cached taxonomy/cards (no LLM calls)")
    ap.add_argument("--skip-trees", action="store_true", help="skip per-card tree diagram generation")
    ap.add_argument("--top", type=int, default=54, help="number of mental-model cards to generate")
    args = ap.parse_args()
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
