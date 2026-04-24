#!/usr/bin/env python3
"""build_data.py — merge LightRAG graph + taxonomy + cards into a unified data.json.

Pure, deterministic, no LLM. Outputs to kg-explorer/data/data.json and docs/data/data.json.
"""
from __future__ import annotations

import json
import math
import pathlib
import random
import re
import shutil
import sys
import time
import urllib.parse
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from typing import Any

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent

GRAPHML       = HERE / "lightrag_data" / "graph_chunk_entity_relation.graphml"
ENTITY_CHUNKS = HERE / "lightrag_data" / "kv_store_entity_chunks.json"
TEXT_CHUNKS   = HERE / "lightrag_data" / "kv_store_text_chunks.json"
TAXONOMY      = HERE / "mental_models" / "taxonomy.json"
CARDS         = HERE / "mental_models" / "cards.json"

OUT_PATHS = [
    HERE / "data" / "data.json",
    REPO / "docs" / "data" / "data.json",
]

LEARN_BASE     = "https://learn.microsoft.com/azure/well-architected"
MC_PATH_MARKER = "/mission-critical/"
GRAPHML_NS     = {"g": "http://graphml.graphdrawing.org/xmlns"}

NODE_TYPES = {
    "MENTAL_MODEL", "PATTERN", "AZURE_SERVICE", "PROCESS",
    "CONCEPT", "METRIC", "ANTI_PATTERN", "TRADEOFF", "OTHER",
}

# ─── loaders ────────────────────────────────────────────────────────────────

def load_json(path: pathlib.Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_graphml(path: pathlib.Path) -> tuple[dict[str, dict], list[dict]]:
    tree = ET.parse(path)
    root = tree.getroot()
    key_map = {k.get("id"): k.get("attr.name") for k in root.findall("g:key", GRAPHML_NS)}
    graph = root.find("g:graph", GRAPHML_NS)

    def data_dict(el) -> dict:
        out = {}
        for d in el.findall("g:data", GRAPHML_NS):
            name = key_map.get(d.get("key"))
            if name:
                out[name] = d.text or ""
        return out

    nodes: dict[str, dict] = {}
    for n in graph.findall("g:node", GRAPHML_NS):
        nid = (n.get("id") or "").strip().strip('"')
        if not nid:
            continue
        d = data_dict(n)
        nodes[nid] = {
            "id": nid,
            "entity_type": d.get("entity_type", "").strip(),
            "description": d.get("description", "").strip(),
            "source_id":   d.get("source_id", ""),
            "file_path":   d.get("file_path", ""),
        }

    edges: list[dict] = []
    for e in graph.findall("g:edge", GRAPHML_NS):
        s = (e.get("source") or "").strip().strip('"')
        t = (e.get("target") or "").strip().strip('"')
        if not s or not t:
            continue
        d = data_dict(e)
        try:
            w = float(d.get("weight") or 1.0)
        except ValueError:
            w = 1.0
        edges.append({
            "source": s,
            "target": t,
            "weight": w,
            "keywords": d.get("keywords", ""),
            "description": d.get("description", ""),
            "file_path":   d.get("file_path", ""),
        })
    return nodes, edges


# ─── source-doc extraction ─────────────────────────────────────────────────

def _normalize_path(fp: str) -> str | None:
    """Return the WAF-relative path like 'mission-critical/foo.md', or None.

    Both absolute (/.../well-architected/well-architected/mission-critical/foo.md)
    and already-relative (well-architected/mission-critical/foo.md) inputs are
    normalized by splitting on the last '/well-architected/' boundary.
    """
    if not fp:
        return None
    fp = fp.strip()
    # handle GraphML <SEP>-joined lists: take the first path only
    if "<SEP>" in fp:
        fp = fp.split("<SEP>", 1)[0].strip()
    # split on the *last* occurrence of /well-architected/
    marker = "/well-architected/"
    idx = fp.rfind(marker)
    if idx < 0:
        # also tolerate leading "well-architected/..."
        if fp.startswith("well-architected/"):
            rel = fp[len("well-architected/"):]
        else:
            return None
    else:
        rel = fp[idx + len(marker):]
    rel = rel.strip().lstrip("/")
    if not rel.endswith(".md"):
        return None
    return rel


def file_path_to_learn_url(fp: str, anchor: str | None = None) -> str | None:
    rel = _normalize_path(fp)
    if not rel:
        return None
    slug = rel[:-3] if rel.endswith(".md") else rel
    url = f"{LEARN_BASE}/{slug}"
    if anchor:
        url += f"#{anchor}"
    return url


def _slugify(text: str) -> str:
    t = re.sub(r"[^\w\s-]", "", text.lower()).strip()
    return re.sub(r"[\s_-]+", "-", t)[:80]


_H1_RE = re.compile(r"^#\s+(.+)$", re.M)
_H2_RE = re.compile(r"^##\s+(.+)$", re.M)
_H3_RE = re.compile(r"^###\s+(.+)$", re.M)


def _doc_title_from_content(content: str, fallback_path: str) -> str:
    m = _H1_RE.search(content or "")
    if m:
        return m.group(1).strip().strip("#").strip()
    # fallback: basename without extension, title-cased
    base = pathlib.Path(fallback_path).stem.replace("-", " ").replace("_", " ")
    return base.title()


def _best_section_for(entity_id: str, content: str) -> str | None:
    """Find the heading closest *preceding* the first mention of entity_id."""
    if not content or not entity_id:
        return None
    hay = content.lower()
    needle = entity_id.lower()
    pos = hay.find(needle)
    if pos < 0:
        # take the first h2 as a best-effort fallback
        m = _H2_RE.search(content)
        return m.group(1).strip() if m else None
    # scan all h2/h3 up to pos, take the last one
    last = None
    for rx in (_H2_RE, _H3_RE):
        for m in rx.finditer(content):
            if m.start() > pos:
                break
            last = m.group(1).strip()
    return last


def collect_source_docs(entity_id: str,
                        entity_chunks: dict,
                        text_chunks: dict,
                        limit: int = 5) -> list[dict]:
    entry = entity_chunks.get(entity_id) or {}
    chunk_ids = entry.get("chunk_ids") or []
    seen_paths: dict[str, dict] = {}
    for cid in chunk_ids:
        chunk = text_chunks.get(cid)
        if not chunk:
            continue
        fp = chunk.get("file_path", "")
        rel = _normalize_path(fp)
        if not rel:
            continue
        if rel in seen_paths:
            continue
        content = chunk.get("content", "") or ""
        section = _best_section_for(entity_id, content)
        anchor = _slugify(section) if section else None
        url = file_path_to_learn_url(fp, anchor)
        if not url:
            continue
        title = _doc_title_from_content(content, rel)
        seen_paths[rel] = {
            "title": title,
            "section": section or "",
            "url": url,
            "path": rel,
        }
        if len(seen_paths) >= limit:
            break
    return list(seen_paths.values())


# ─── mission-critical tagging ──────────────────────────────────────────────

def is_mission_critical(entity_id: str,
                        entity_chunks: dict,
                        text_chunks: dict,
                        card_names: set[str]) -> bool:
    # cards.json membership is authoritative
    if entity_id in card_names:
        return True
    entry = entity_chunks.get(entity_id) or {}
    chunk_ids = entry.get("chunk_ids") or []
    if not chunk_ids:
        return False
    for cid in chunk_ids:
        chunk = text_chunks.get(cid)
        if not chunk:
            continue
        if MC_PATH_MARKER in (chunk.get("file_path") or ""):
            return True
    return False


# ─── centrality ────────────────────────────────────────────────────────────

def compute_centrality(node_ids, edges) -> Counter:
    c: Counter = Counter()
    valid = set(node_ids)
    for e in edges:
        if e["source"] in valid and e["target"] in valid:
            c[e["source"]] += 1
            c[e["target"]] += 1
    return c


# ─── layout (precomputed, deterministic) ───────────────────────────────────

def compute_layout(nodes: list[dict], edges: list[dict],
                   scale: float = 900.0,
                   iterations: int = 80) -> dict[str, tuple[float, float]]:
    """Run a weighted spring layout once at build time so the browser can
    just render — no runtime force simulation.

    - Semantic edges (builds_on/enables) pull strongly; mentioned_with pulls
      weakly, so dense "mentioned_with" fan-outs don't drown out structure.
    - Mission-critical nodes seed near the center; everything else seeds on
      an outer ring, matching the previous runtime seed.
    - Deterministic: fixed seed.
    """
    try:
        import networkx as nx
    except ImportError:
        print("  ⚠ networkx not available — skipping layout (browser will fall back)")
        return {}

    G = nx.Graph()
    for n in nodes:
        G.add_node(n["id"])
    for e in edges:
        rel = e.get("relation")
        if rel in ("builds_on", "enables"):
            w = 5.0
        else:
            w = max(0.05, float(e.get("weight", 1.0)) * 0.12)
        s, t = e["source"], e["target"]
        if s == t:
            continue
        if G.has_edge(s, t):
            G[s][t]["weight"] += w
        else:
            G.add_edge(s, t, weight=w)

    rng = random.Random(42)
    init: dict[str, tuple[float, float]] = {}
    mc = [n for n in nodes if n.get("mission_critical")]
    rest = [n for n in nodes if not n.get("mission_critical")]
    for i, n in enumerate(mc):
        a = 2 * math.pi * i / max(1, len(mc))
        init[n["id"]] = (
            math.cos(a) * 0.15 + rng.uniform(-0.02, 0.02),
            math.sin(a) * 0.15 + rng.uniform(-0.02, 0.02),
        )
    for i, n in enumerate(rest):
        a = 2 * math.pi * i / max(1, len(rest)) + math.pi
        init[n["id"]] = (
            math.cos(a) * 0.75 + rng.uniform(-0.04, 0.04),
            math.sin(a) * 0.75 + rng.uniform(-0.04, 0.04),
        )

    t0 = time.time()
    pos = nx.spring_layout(
        G, pos=init, weight="weight",
        k=None, iterations=iterations, seed=42,
    )
    dt = time.time() - t0
    print(f"  layout: {len(pos)} positions in {dt:.1f}s  ({iterations} iterations)")

    # center + scale to world coords (roughly ±scale)
    xs = [p[0] for p in pos.values()]
    ys = [p[1] for p in pos.values()]
    cx = (min(xs) + max(xs)) / 2
    cy = (min(ys) + max(ys)) / 2
    span = max(max(xs) - min(xs), max(ys) - min(ys), 1e-6)
    k = (2 * scale) / span
    return {nid: ((x - cx) * k, (y - cy) * k) for nid, (x, y) in pos.items()}


# ─── taxonomy merge ────────────────────────────────────────────────────────

def build_taxonomy_index(taxonomy: list) -> dict[str, str]:
    idx: dict[str, str] = {}
    for item in taxonomy:
        name = (item.get("entity") or "").strip()
        cat  = (item.get("category") or "").strip().upper()
        if not name or not cat:
            continue
        if cat not in NODE_TYPES:
            cat = "OTHER"
        idx[name] = cat
    return idx


def merge_card_onto_node(node: dict, card: dict) -> None:
    for k in ("mantra", "layer", "when_to_apply", "without_it", "key_tradeoff"):
        if card.get(k):
            node[k] = card[k]


# ─── main build ────────────────────────────────────────────────────────────

def build() -> dict:
    print(f"→ Loading GraphML {GRAPHML.name}")
    raw_nodes, raw_edges = load_graphml(GRAPHML)
    print(f"  {len(raw_nodes)} nodes, {len(raw_edges)} raw edges")

    print("→ Loading taxonomy + cards + chunks")
    taxonomy = load_json(TAXONOMY)
    cards    = load_json(CARDS)
    ec       = load_json(ENTITY_CHUNKS)
    tc       = load_json(TEXT_CHUNKS)

    tax_idx   = build_taxonomy_index(taxonomy)
    card_idx  = {c["name"]: c for c in cards}
    card_names = set(card_idx)

    print("→ Building nodes")
    nodes_out: list[dict] = []
    for nid, n in raw_nodes.items():
        node_type = tax_idx.get(nid)
        if not node_type:
            et = (n.get("entity_type") or "OTHER").upper()
            node_type = et if et in NODE_TYPES else "OTHER"
        node = {
            "id":               nid,
            "type":             node_type,
            "description":      n.get("description", ""),
            "mission_critical": is_mission_critical(nid, ec, tc, card_names),
            "source_docs":      collect_source_docs(nid, ec, tc),
        }
        if nid in card_idx:
            node["type"] = "MENTAL_MODEL"
            node["mission_critical"] = True
            merge_card_onto_node(node, card_idx[nid])
        nodes_out.append(node)

    valid_ids = {n["id"] for n in nodes_out}
    centrality = compute_centrality(valid_ids, raw_edges)
    for n in nodes_out:
        n["centrality"] = centrality.get(n["id"], 0)

    # ─── edges ───────────────────────────────────────────────────────────
    print("→ Building edges")
    edges_out: list[dict] = []
    seen: set[tuple] = set()

    # 1. Synthesize builds_on / enables from cards.json.
    missing_refs: list[tuple[str, str, str]] = []

    def add_semantic(src: str, dst: str, rel: str):
        if dst not in valid_ids:
            missing_refs.append((src, dst, rel))
            return
        key = (src, dst, rel)
        if key in seen:
            return
        seen.add(key)
        edges_out.append({"source": src, "target": dst, "relation": rel, "weight": 2.0})

    for card in cards:
        src = card.get("name")
        if not src or src not in valid_ids:
            continue
        for dst in card.get("builds_on") or []:
            add_semantic(src, dst, "builds_on")
        for dst in card.get("enables") or []:
            add_semantic(src, dst, "enables")

    if missing_refs:
        print(f"  ⚠ {len(missing_refs)} card refs point to unknown nodes "
              f"(first 5: {missing_refs[:5]})")

    # 2. All other GraphML edges → mentioned_with (dedup canonical).
    semantic_pairs = {(e["source"], e["target"]) for e in edges_out}
    semantic_pairs |= {(e["target"], e["source"]) for e in edges_out}

    for e in raw_edges:
        s, t = e["source"], e["target"]
        if s not in valid_ids or t not in valid_ids or s == t:
            continue
        if (s, t) in semantic_pairs:
            continue
        a, b = sorted([s, t])
        key = (a, b, "mentioned_with")
        if key in seen:
            continue
        seen.add(key)
        edges_out.append({
            "source": a, "target": b,
            "relation": "mentioned_with",
            "weight": e.get("weight", 1.0),
        })

    # ─── precomputed layout ──────────────────────────────────────────────
    print("→ Computing layout (networkx spring_layout, weighted)")
    pos = compute_layout(nodes_out, edges_out)
    if pos:
        for n in nodes_out:
            p = pos.get(n["id"])
            if p:
                n["x"] = round(p[0], 2)
                n["y"] = round(p[1], 2)

    # ─── stats ───────────────────────────────────────────────────────────
    docs_set: set[str] = set()
    for chunk in tc.values():
        rel = _normalize_path(chunk.get("file_path", "") or "")
        if rel:
            docs_set.add(rel)

    stats = {
        "docs":             len(docs_set),
        "nodes":            len(nodes_out),
        "edges":            len(edges_out),
        "mental_models":    sum(1 for n in nodes_out if n["type"] == "MENTAL_MODEL"),
        "mission_critical": sum(1 for n in nodes_out if n["mission_critical"]),
        "by_type":          dict(Counter(n["type"] for n in nodes_out)),
        "by_relation":      dict(Counter(e["relation"] for e in edges_out)),
        "missing_refs":     len(missing_refs),
    }

    return {"nodes": nodes_out, "edges": edges_out, "stats": stats}


def main():
    data = build()
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    for out in OUT_PATHS:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(payload, encoding="utf-8")
        print(f"✓ wrote {out.relative_to(REPO)}  ({out.stat().st_size/1024:.0f} KB)")
    s = data["stats"]
    print(f"\nSummary:")
    print(f"  nodes            : {s['nodes']}")
    print(f"  edges            : {s['edges']}")
    print(f"  mental_models    : {s['mental_models']}")
    print(f"  mission_critical : {s['mission_critical']}")
    print(f"  docs             : {s['docs']}")
    print(f"  by_type          : {s['by_type']}")
    print(f"  by_relation      : {s['by_relation']}")


if __name__ == "__main__":
    sys.exit(main())
