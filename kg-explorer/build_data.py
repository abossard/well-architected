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

DEFAULT_DOMAIN = "mission-critical"
TAXONOMY      = HERE / "mental_models" / "taxonomy.json"
CARDS         = HERE / "mental_models" / "cards.json"
FACTS         = HERE / "mental_models" / "facts.json"
VERIFICATIONS = HERE / "mental_models" / "verifications.json"
FACT_LOCATIONS = HERE / "mental_models" / "fact_locations.json"
LINKS         = HERE / "data" / "links.json"

OUT_DIRS = [
    HERE / "data",
    REPO / "docs" / "data",
]

LEARN_BASE     = "https://learn.microsoft.com/azure/well-architected"
MC_PATH_MARKER = "/mission-critical/"
GRAPHML_NS     = {"g": "http://graphml.graphdrawing.org/xmlns"}


def rag_paths(domain: str) -> tuple[pathlib.Path, pathlib.Path, pathlib.Path]:
    """Return (graphml, entity_chunks, text_chunks) paths for a domain."""
    rag_dir = HERE / f"lightrag_data_{domain}"
    return (
        rag_dir / "graph_chunk_entity_relation.graphml",
        rag_dir / "kv_store_entity_chunks.json",
        rag_dir / "kv_store_text_chunks.json",
    )

NODE_TYPES = {
    "MENTAL_MODEL", "PATTERN", "AZURE_SERVICE", "PROCESS",
    "CONCEPT", "METRIC", "ANTI_PATTERN", "TRADEOFF", "FACT", "OTHER",
    "FACT_TIMELESS", "FACT_PERISHABLE",
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


# ─── condensation ──────────────────────────────────────────────────────────

def condense_description(desc: str, max_chars: int = 120) -> str:
    """Trim to first sentence or max_chars, whichever is shorter."""
    if not desc:
        return ""
    desc = desc.strip()
    for end in (". ", ".\n", ".\t"):
        idx = desc.find(end)
        if 0 < idx < max_chars:
            return desc[: idx + 1]
    if len(desc) > max_chars:
        return desc[:max_chars].rsplit(" ", 1)[0] + "…"
    return desc


# ─── link integration ──────────────────────────────────────────────────────

def load_links() -> dict[str, list[dict]]:
    """Load extracted links from data/links.json."""
    if not LINKS.exists():
        return {}
    return load_json(LINKS)


def build_link_edges(links_data: dict[str, list[dict]],
                     entity_chunks: dict,
                     text_chunks: dict,
                     valid_ids: set[str],
                     centrality: Counter,
                     top_n_per_doc: int = 5) -> tuple[list[dict], dict[str, list[dict]]]:
    """Create cross-reference edges from extracted links.

    Returns (edges, node_links) where:
    - edges: list of {source, target, relation: "references", weight}
    - node_links: {entity_id: [link_metadata]} for detail panel

    Only the top-N most central entities per document participate in
    cross-reference edges to avoid combinatorial explosion.
    """
    # Build a map: waf_path → set of entity_ids that come from that path
    path_to_entities: dict[str, set[str]] = defaultdict(set)
    for eid, entry in entity_chunks.items():
        if eid not in valid_ids:
            continue
        for cid in entry.get("chunk_ids") or []:
            chunk = text_chunks.get(cid)
            if not chunk:
                continue
            rel = _normalize_path(chunk.get("file_path", "") or "")
            if rel:
                path_to_entities[rel].add(eid)

    # Pre-compute top-N entities per doc (by centrality)
    top_entities_per_doc: dict[str, set[str]] = {}
    for path, entities in path_to_entities.items():
        ranked = sorted(entities, key=lambda e: centrality.get(e, 0), reverse=True)
        top_entities_per_doc[path] = set(ranked[:top_n_per_doc])

    # Build edges from source docs to target docs via links
    ref_edges: list[dict] = []
    node_links: dict[str, list[dict]] = defaultdict(list)
    seen_edges: set[tuple] = set()

    for source_path, links in links_data.items():
        source_entities = path_to_entities.get(source_path, set())
        source_top = top_entities_per_doc.get(source_path, set())

        for link in links:
            # Attach link metadata to all entities from the source doc
            for eid in source_entities:
                node_links[eid].append({
                    "text": link.get("text", ""),
                    "url": link.get("learn_url") or link.get("url", ""),
                    "type": link.get("type", "external"),
                })

            # For internal-waf links, create edges between top entities only
            if link.get("type") == "internal-waf" and link.get("resolved"):
                target_path = link["resolved"]
                target_top = top_entities_per_doc.get(target_path, set())
                for se in source_top:
                    for te in target_top:
                        if se == te:
                            continue
                        key = (min(se, te), max(se, te))
                        if key in seen_edges:
                            continue
                        seen_edges.add(key)
                        ref_edges.append({
                            "source": se,
                            "target": te,
                            "relation": "references",
                            "weight": 1.5,
                        })

    return ref_edges, dict(node_links)


# ─── fact nodes ─────────────────────────────────────────────────────────────

def build_fact_nodes(facts: list[dict],
                     existing_nodes: dict[str, dict],
                     pos: dict[str, tuple[float, float]],
                     verifications: dict[str, dict] | None = None,
                     locations: dict[str, dict] | None = None) -> tuple[list[dict], list[dict]]:
    """Synthesize graph nodes and edges from extracted facts.

    Merges verification verdicts (only if URL+citation present) and
    source locations into each fact node's detail dict.
    """
    verifications = verifications or {}
    locations = locations or {}
    rng = random.Random(42)
    fact_nodes: list[dict] = []
    fact_edges: list[dict] = []
    entity_counters: dict[str, int] = {}
    verified_count = 0
    located_count = 0

    for f in facts:
        entity = f.get("entity", "")
        if not entity or entity not in existing_nodes:
            continue

        slug = _slugify(entity)
        idx = entity_counters.get(slug, 0)
        entity_counters[slug] = idx + 1

        fact_id = f"fact:{slug}:{idx}"
        hash_id = _compute_fact_id(entity, f.get("fact", ""))

        fact_type = f.get("type", "timeless")
        node_type = "FACT_TIMELESS" if fact_type == "timeless" else "FACT_PERISHABLE"

        parent = existing_nodes[entity]
        parent_depth = parent.get("depth", 0)
        parent_pos = pos.get(entity)
        if parent_pos:
            fx = round(parent_pos[0] + rng.uniform(-30, 30), 2)
            fy = round(parent_pos[1] + rng.uniform(-30, 30), 2)
        else:
            fx = round(rng.uniform(-100, 100), 2)
            fy = round(rng.uniform(-100, 100), 2)

        detail = {
            "fact": f.get("fact", ""),
            "fact_type": fact_type,
            "fact_id": hash_id,
            "shelf_life_months": f.get("shelf_life_months"),
            "confidence": f.get("confidence"),
            "verification_hint": f.get("verification_hint"),
            "source_entity": entity,
        }

        # Merge verification (only accepted if URL + real citation)
        v = verifications.get(hash_id)
        if v:
            detail["verified"] = v.get("verdict")
            detail["verified_at"] = v.get("verified_at")
            detail["current_info"] = v.get("current_info")
            detail["source_url"] = v.get("source_url")
            detail["source_excerpt"] = v.get("source_excerpt")
            detail["verification_notes"] = v.get("notes")
            verified_count += 1

        # Merge location
        loc = locations.get(hash_id)
        if loc:
            best = loc.get("best_location") or {}
            detail["source_file"] = best.get("file")
            detail["source_heading"] = best.get("heading")
            detail["source_line"] = best.get("line_approx")
            detail["location_confidence"] = best.get("location_confidence", 0.0)
            detail["manual_location_needed"] = loc.get("manual_location_needed", False)
            located_count += 1

        fact_node = {
            "id": fact_id,
            "type": node_type,
            "description": f.get("fact", ""),
            "mission_critical": True,
            "centrality": 0,
            "depth": parent_depth + 1,
            "x": fx,
            "y": fy,
            "fact_detail": detail,
        }
        fact_nodes.append(fact_node)
        fact_edges.append({
            "source": entity,
            "target": fact_id,
            "relation": "has_fact",
            "weight": 0.3,
        })

    if verified_count:
        print(f"  {verified_count} facts with verified citations")
    if located_count:
        print(f"  {located_count} facts with source locations")

    return fact_nodes, fact_edges

    return fact_nodes, fact_edges


def _compute_fact_id(entity: str, fact: str) -> str:
    """Stable fact_id matching verify_facts.py and locate_facts.py."""
    import hashlib
    return hashlib.sha256((entity + "\0" + fact).encode()).hexdigest()[:16]


def load_verifications() -> dict[str, dict]:
    """Load verifications.json, index by fact_id.

    Only accepts verifications that meet ALL of:
    1. Has source_url (non-empty)
    2. Has source_excerpt with actual content (>50 chars, not just metadata)
    3. Has both entity and fact text
    A verdict without a real citation from a real URL is not trustworthy.
    """
    if not VERIFICATIONS.exists():
        return {}
    raw = load_json(VERIFICATIONS)
    idx: dict[str, dict] = {}
    skipped_no_url = 0
    skipped_bad_excerpt = 0
    skipped_no_entity = 0
    dupes = 0
    for v in raw:
        entity = (v.get("entity") or "").strip()
        fact = (v.get("fact") or "").strip()
        if not entity or not fact:
            skipped_no_entity += 1
            continue
        fid = v.get("fact_id") or _compute_fact_id(entity, fact)
        url = (v.get("source_url") or "").strip()
        excerpt = (v.get("source_excerpt") or "").strip()
        if not url:
            skipped_no_url += 1
            continue
        # Reject boilerplate/empty excerpts — must have real page content
        is_boilerplate = (
            len(excerpt) < 50
            or ("Word Count:** 0" in excerpt and "Content Length:** 0" in excerpt)
            or ("Content:**\n" in excerpt and len(excerpt.split("Content:**\n")[-1].strip()) < 20)
        )
        if is_boilerplate:
            skipped_bad_excerpt += 1
            continue
        if fid in idx:
            dupes += 1
        idx[fid] = v
    if skipped_no_url:
        print(f"  ⚠ skipped {skipped_no_url} verifications without source URL")
    if skipped_bad_excerpt:
        print(f"  ⚠ skipped {skipped_bad_excerpt} verifications with empty/boilerplate excerpt")
    if skipped_no_entity:
        print(f"  ⚠ skipped {skipped_no_entity} verifications missing entity/fact")
    if dupes:
        print(f"  ⚠ {dupes} duplicate fact_ids (last-write-wins)")
    return idx


def load_fact_locations() -> dict[str, dict]:
    """Load fact_locations.json, index by fact_id."""
    if not FACT_LOCATIONS.exists():
        return {}
    raw = load_json(FACT_LOCATIONS)
    idx: dict[str, dict] = {}
    for loc in raw:
        entity = (loc.get("entity") or "").strip()
        fact = (loc.get("fact") or "").strip()
        if not entity or not fact:
            continue
        fid = loc.get("fact_id") or _compute_fact_id(entity, fact)
        idx[fid] = loc
    return idx


# ─── main build ────────────────────────────────────────────────────────────

def build(domain: str = DEFAULT_DOMAIN) -> dict:
    graphml_path, ec_path, tc_path = rag_paths(domain)

    print(f"→ Loading GraphML {graphml_path}")
    raw_nodes, raw_edges = load_graphml(graphml_path)
    print(f"  {len(raw_nodes)} nodes, {len(raw_edges)} raw edges")

    print("→ Loading taxonomy + cards + chunks + facts")
    taxonomy = load_json(TAXONOMY) if TAXONOMY.exists() else []
    cards    = load_json(CARDS) if CARDS.exists() else []
    facts    = load_json(FACTS) if FACTS.exists() else []
    ec       = load_json(ec_path)
    tc       = load_json(tc_path)

    tax_idx   = build_taxonomy_index(taxonomy)
    card_idx  = {c["name"]: c for c in cards}
    card_names = set(card_idx)

    # Index facts by entity name
    facts_by_entity: dict[str, list[dict]] = defaultdict(list)
    for f in facts:
        eid = f.get("entity", "")
        if eid:
            facts_by_entity[eid].append(f)

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
        # Attach extracted facts
        if nid in facts_by_entity:
            node["facts"] = facts_by_entity[nid]
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

    # 3. Cross-reference edges from extracted links.
    print("→ Integrating extracted links")
    links_data = load_links()
    ref_edges, node_links = build_link_edges(links_data, ec, tc, valid_ids, centrality)
    for re_ in ref_edges:
        key = (re_["source"], re_["target"], re_["relation"])
        if key not in seen:
            seen.add(key)
            edges_out.append(re_)
    print(f"  {len(ref_edges)} reference edges from {sum(len(v) for v in links_data.values())} extracted links")

    # Attach link metadata to nodes
    for n in nodes_out:
        nlinks = node_links.get(n["id"])
        if nlinks:
            n["links"] = nlinks

    # ─── precomputed layout ──────────────────────────────────────────────
    print("→ Computing layout (networkx spring_layout, weighted)")
    pos = compute_layout(nodes_out, edges_out)
    if pos:
        for n in nodes_out:
            p = pos.get(n["id"])
            if p:
                n["x"] = round(p[0], 2)
                n["y"] = round(p[1], 2)

    # ─── fact nodes ─────────────────────────────────────────────────────
    print("→ Loading verifications + locations")
    verifications = load_verifications()
    fact_locs = load_fact_locations()
    print(f"  {len(verifications)} valid verifications, {len(fact_locs)} fact locations")

    print("→ Building fact nodes")
    existing_node_map = {n["id"]: n for n in nodes_out}
    fact_nodes_list, fact_edges_list = build_fact_nodes(
        facts, existing_node_map, pos, verifications, fact_locs,
    )
    nodes_out.extend(fact_nodes_list)
    edges_out.extend(fact_edges_list)
    print(f"  {len(fact_nodes_list)} fact nodes, {len(fact_edges_list)} has_fact edges")

    # ─── stats ───────────────────────────────────────────────────────────
    docs_set: set[str] = set()
    for chunk in tc.values():
        rel = _normalize_path(chunk.get("file_path", "") or "")
        if rel:
            docs_set.add(rel)

    # Fact statistics
    all_facts = [f for n in nodes_out for f in (n.get("facts") or [])]
    perishable_facts = [f for f in all_facts if f.get("type") == "perishable"]
    fact_nodes_timeless = sum(1 for n in fact_nodes_list if n["type"] == "FACT_TIMELESS")
    fact_nodes_perishable = sum(1 for n in fact_nodes_list if n["type"] == "FACT_PERISHABLE")
    entity_count = len(nodes_out) - len(fact_nodes_list)

    # Verification coverage
    verified_current = sum(1 for n in fact_nodes_list if (n.get("fact_detail") or {}).get("verified") == "current")
    verified_outdated = sum(1 for n in fact_nodes_list if (n.get("fact_detail") or {}).get("verified") == "outdated")
    facts_with_location = sum(1 for n in fact_nodes_list if (n.get("fact_detail") or {}).get("source_file"))

    stats = {
        "docs":             len(docs_set),
        "nodes":            len(nodes_out),
        "entities":         entity_count,
        "edges":            len(edges_out),
        "mental_models":    sum(1 for n in nodes_out if n["type"] == "MENTAL_MODEL"),
        "mission_critical": sum(1 for n in nodes_out if n["mission_critical"]),
        "by_type":          dict(Counter(n["type"] for n in nodes_out)),
        "by_relation":      dict(Counter(e["relation"] for e in edges_out)),
        "missing_refs":     len(missing_refs),
        "facts_total":      len(all_facts),
        "facts_perishable": len(perishable_facts),
        "fact_nodes":       len(fact_nodes_list),
        "fact_nodes_timeless": fact_nodes_timeless,
        "fact_nodes_perishable": fact_nodes_perishable,
        "verified_current": verified_current,
        "verified_outdated": verified_outdated,
        "facts_with_location": facts_with_location,
    }

    # ─── depth assignment (BFS from MENTAL_MODEL seeds) ─────────────────
    # Each node gets a depth = shortest path distance from any MENTAL_MODEL.
    # UI starts at depth 3 (~2700 nodes) with a configurable slider.
    adj: dict[str, set[str]] = {}
    for e in edges_out:
        adj.setdefault(e["source"], set()).add(e["target"])
        adj.setdefault(e["target"], set()).add(e["source"])

    mm_seeds = {n["id"] for n in nodes_out if n["type"] == "MENTAL_MODEL"}
    depth_map: dict[str, int] = {nid: 0 for nid in mm_seeds}
    frontier = set(mm_seeds)
    for d in range(1, 20):
        next_frontier = set()
        for nid in frontier:
            for neighbor in adj.get(nid, set()):
                if neighbor not in depth_map:
                    depth_map[neighbor] = d
                    next_frontier.add(neighbor)
        if not next_frontier:
            break
        frontier = next_frontier

    max_depth = max(depth_map.values()) if depth_map else 0
    for n in nodes_out:
        n["depth"] = depth_map.get(n["id"], max_depth + 1)

    # Compute counts per depth for stats
    depth_counts = Counter(n["depth"] for n in nodes_out)
    cumulative = {}
    running = 0
    for d in sorted(depth_counts.keys()):
        running += depth_counts[d]
        cumulative[d] = running

    stats["depths"] = {str(d): cumulative[d] for d in sorted(cumulative.keys())}
    stats["max_depth"] = max_depth

    # mental-model ordering (layer → centrality desc → id) for prev/next nav.
    mm_with_cards = [
        n for n in nodes_out
        if n["type"] == "MENTAL_MODEL" and (n.get("mantra") or n.get("when_to_apply"))
    ]
    mm_with_cards.sort(key=lambda n: (
        n.get("layer") or "zz",
        -(n.get("centrality") or 0),
        n["id"],
    ))
    stats["model_order"] = [n["id"] for n in mm_with_cards]

    # ─── split into graph (slim) + details (rich) ────────────────────────
    graph_nodes = []
    details: dict[str, dict] = {}
    for n in nodes_out:
        is_fact = n.get("fact_detail") is not None
        slim = {
            "id":   n["id"],
            "type": n["type"],
            "deg":  n.get("centrality") or 0,
            "d":    n.get("depth", 99),
        }
        if "x" in n: slim["x"] = n["x"]
        if "y" in n: slim["y"] = n["y"]
        if n.get("mission_critical"): slim["mc"] = True
        if is_fact: slim["fact"] = True
        # Add verification verdict to slim node for UI color-coding
        if is_fact:
            fd = n.get("fact_detail") or {}
            if fd.get("verified"):
                slim["v"] = fd["verified"]  # "current" | "outdated"
        graph_nodes.append(slim)

        if is_fact:
            fd = n["fact_detail"]
            det: dict[str, Any] = {
                "type":              n["type"],
                "summary":           fd["fact"],
                "fact_type":         fd["fact_type"],
                "fact_id":           fd.get("fact_id"),
                "confidence":        fd.get("confidence"),
                "source_entity":     fd["source_entity"],
            }
            if fd.get("shelf_life_months"):
                det["shelf_life_months"] = fd["shelf_life_months"]
            if fd.get("verification_hint"):
                det["verification_hint"] = fd["verification_hint"]
            # Verification data (only present if URL + real citation)
            if fd.get("verified"):
                det["verified"] = fd["verified"]
                det["verified_at"] = fd.get("verified_at")
                det["current_info"] = fd.get("current_info")
                det["source_url"] = fd.get("source_url")
                det["source_excerpt"] = fd.get("source_excerpt")
                det["verification_notes"] = fd.get("verification_notes")
            # Source location data
            if fd.get("source_file"):
                det["source_file"] = fd["source_file"]
                det["source_heading"] = fd.get("source_heading")
                det["source_line"] = fd.get("source_line")
                det["location_confidence"] = fd.get("location_confidence")
                det["manual_location_needed"] = fd.get("manual_location_needed", False)
            details[n["id"]] = det
            continue

        docs = [
            {"title": d.get("title") or d.get("path") or "", "url": d["url"],
             **({"section": d["section"]} if d.get("section") else {})}
            for d in (n.get("source_docs") or [])
        ]
        det: dict[str, Any] = {
            "type":    n["type"],
            "summary": condense_description(n.get("description", "")),
        }
        if docs:
            det["docs"] = docs
        # Attach extracted links to details
        if n.get("links"):
            det["links"] = n["links"]
        # Attach facts with shelf-life metadata
        if n.get("facts"):
            det["facts"] = [
                {
                    "fact": f["fact"],
                    "type": f.get("type", "timeless"),
                    **({"shelf_life_months": f["shelf_life_months"]} if f.get("shelf_life_months") else {}),
                    **({"verification_hint": f["verification_hint"]} if f.get("verification_hint") else {}),
                    **({"confidence": f["confidence"]} if f.get("confidence") else {}),
                }
                for f in n["facts"]
            ]
        if n["type"] == "MENTAL_MODEL":
            for src, dst in (
                ("mantra", "mantra"),
                ("layer", "layer"),
                ("when_to_apply", "when"),
                ("without_it", "without"),
                ("key_tradeoff", "tradeoff"),
                ("builds_on", "builds_on"),
                ("enables", "enables"),
            ):
                v = n.get(src)
                if v:
                    det[dst] = v
        details[n["id"]] = det

    graph_edges = [
        {"s": e["source"], "t": e["target"], "r": e["relation"]}
        for e in edges_out
    ]

    graph = {"nodes": graph_nodes, "edges": graph_edges, "stats": stats}
    return graph, details


def main():
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--domain", default=DEFAULT_DOMAIN, help="domain for RAG data (default: mission-critical)")
    args = ap.parse_args()

    graph, details = build(domain=args.domain)
    graph_payload   = json.dumps(graph,   ensure_ascii=False, separators=(",", ":"))
    details_payload = json.dumps(details, ensure_ascii=False, separators=(",", ":"))
    for out_dir in OUT_DIRS:
        out_dir.mkdir(parents=True, exist_ok=True)
        gpath = out_dir / "graph.json"
        dpath = out_dir / "details.json"
        gpath.write_text(graph_payload,   encoding="utf-8")
        dpath.write_text(details_payload, encoding="utf-8")
        print(f"✓ wrote {gpath.relative_to(REPO)}  ({gpath.stat().st_size/1024:.0f} KB)")
        print(f"✓ wrote {dpath.relative_to(REPO)}  ({dpath.stat().st_size/1024:.0f} KB)")
        # remove stale combined file if present
        legacy = out_dir / "data.json"
        if legacy.exists():
            legacy.unlink()
            print(f"  removed stale {legacy.relative_to(REPO)}")
    s = graph["stats"]
    print(f"\nSummary:")
    print(f"  domain           : {args.domain}")
    print(f"  nodes            : {s['nodes']}")
    print(f"  entities         : {s['entities']}")
    print(f"  fact_nodes       : {s['fact_nodes']} (timeless: {s['fact_nodes_timeless']}, perishable: {s['fact_nodes_perishable']})")
    print(f"  edges            : {s['edges']}")
    print(f"  mental_models    : {s['mental_models']}")
    print(f"  mission_critical : {s['mission_critical']}")
    print(f"  docs             : {s['docs']}")
    print(f"  by_type          : {s['by_type']}")
    print(f"  by_relation      : {s['by_relation']}")


if __name__ == "__main__":
    sys.exit(main())
