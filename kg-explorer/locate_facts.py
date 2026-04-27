#!/usr/bin/env python3
"""locate_facts.py — locate each fact from facts.json in the WAF source files.

Uses LightRAG chunk data to find candidate markdown files, then fuzzy-matches
fact text against file content to produce ranked candidate locations.

Dependencies: stdlib only (json, pathlib, hashlib, re, argparse, collections).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import string
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_DOMAIN = "mission-critical"

# ---------------------------------------------------------------------------
# Path helpers (mirrors build_data._normalize_path)
# ---------------------------------------------------------------------------

def _normalize_path(fp: str) -> str | None:
    """Return WAF-relative path like 'mission-critical/foo.md', or None."""
    if not fp:
        return None
    fp = fp.strip()
    if "<SEP>" in fp:
        fp = fp.split("<SEP>", 1)[0].strip()
    marker = "/well-architected/"
    idx = fp.rfind(marker)
    if idx < 0:
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


# ---------------------------------------------------------------------------
# Text normalization & fuzzy matching
# ---------------------------------------------------------------------------

_PUNCT_TABLE = str.maketrans("", "", string.punctuation)


def _tokenize(text: str) -> list[str]:
    """Lowercase, strip punctuation, collapse whitespace → token list."""
    text = text.lower().translate(_PUNCT_TABLE)
    return re.split(r"\s+", text.strip())


def token_overlap_ratio(query: str, target: str) -> tuple[float, list[str]]:
    """Return (overlap_ratio, matched_tokens) between query and target.

    Ratio = |query_tokens ∩ target_tokens| / |query_tokens|
    """
    q_tokens = set(_tokenize(query))
    t_tokens = set(_tokenize(target))
    if not q_tokens:
        return 0.0, []
    matched = q_tokens & t_tokens
    return len(matched) / len(q_tokens), sorted(matched)


# ---------------------------------------------------------------------------
# Stable fact_id (same as verify_facts.py)
# ---------------------------------------------------------------------------

def fact_id(entity: str, fact: str) -> str:
    return hashlib.sha256((entity + "\0" + fact).encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Heading finder
# ---------------------------------------------------------------------------

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)


def _find_nearest_heading(content: str, match_pos: int) -> str | None:
    """Find the nearest markdown heading above match_pos."""
    best: str | None = None
    for m in _HEADING_RE.finditer(content):
        if m.start() <= match_pos:
            best = m.group(0).strip()
        else:
            break
    return best


def _line_number_at(content: str, pos: int) -> int:
    """1-based line number for character position."""
    return content[:pos].count("\n") + 1


# ---------------------------------------------------------------------------
# Sliding-window best match
# ---------------------------------------------------------------------------

def _best_window_match(
    fact_text: str, content: str, window_lines: int = 8
) -> tuple[float, int, str]:
    """Slide a window over content lines, return (best_ratio, best_pos, context).

    Returns the window with the highest token overlap against fact_text.
    """
    lines = content.split("\n")
    q_tokens = set(_tokenize(fact_text))
    if not q_tokens:
        return 0.0, 0, ""

    best_ratio = 0.0
    best_start_line = 0
    best_window_text = ""

    for i in range(max(1, len(lines) - window_lines + 1)):
        window = "\n".join(lines[i : i + window_lines])
        w_tokens = set(_tokenize(window))
        matched = q_tokens & w_tokens
        ratio = len(matched) / len(q_tokens)
        if ratio > best_ratio:
            best_ratio = ratio
            best_start_line = i
            best_window_text = window

    # char position of best_start_line
    pos = sum(len(lines[j]) + 1 for j in range(best_start_line))
    return best_ratio, pos, best_window_text.strip()


# ---------------------------------------------------------------------------
# Core locator
# ---------------------------------------------------------------------------

def load_json(path: Path) -> Any:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def discover_domains() -> list[str]:
    """Return available domain names based on lightrag_data_* dirs."""
    return sorted(
        d.name.removeprefix("lightrag_data_")
        for d in HERE.iterdir()
        if d.is_dir() and d.name.startswith("lightrag_data_")
    )


def locate_facts(
    *,
    domain: str,
    waf_root: Path,
    entity_filter: str | None = None,
    dry_run: bool = False,
) -> list[dict]:
    """Locate facts and return list of fact-location records."""
    facts_path = HERE / "mental_models" / "facts.json"
    rag_dir = HERE / f"lightrag_data_{domain}"
    entity_chunks_path = rag_dir / "kv_store_entity_chunks.json"
    text_chunks_path = rag_dir / "kv_store_text_chunks.json"

    # Load data
    facts = load_json(facts_path)
    entity_chunks: dict = load_json(entity_chunks_path) if entity_chunks_path.exists() else {}
    text_chunks: dict = load_json(text_chunks_path) if text_chunks_path.exists() else {}

    # Build chunk_id → (waf_rel_path, content) index
    chunk_index: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for cid, chunk in text_chunks.items():
        fp = chunk.get("file_path", "")
        rel = _normalize_path(fp)
        content = chunk.get("content", "")
        if rel:
            chunk_index[cid].append((rel, content))

    # Optionally filter by entity
    if entity_filter:
        ef_lower = entity_filter.lower()
        facts = [f for f in facts if f.get("entity", "").lower() == ef_lower]

    if dry_run:
        _print_dry_run_stats(facts, entity_chunks, text_chunks, chunk_index, domain, waf_root)
        return []

    results: list[dict] = []
    # file content cache
    file_cache: dict[str, str | None] = {}

    for f in facts:
        entity = f.get("entity", "")
        fact_text = f.get("fact", "")
        fid = fact_id(entity, fact_text)

        # 1. entity → chunk_ids
        entity_entry = entity_chunks.get(entity, {})
        chunk_ids = entity_entry.get("chunk_ids", [])

        # Collect candidate files from chunks
        candidate_files: dict[str, str] = {}  # rel_path → chunk_content
        for cid in chunk_ids:
            for rel_path, content in chunk_index.get(cid, []):
                if rel_path not in candidate_files:
                    candidate_files[rel_path] = content

        # Also try fuzzy entity lookup (case-insensitive)
        if not chunk_ids:
            for ename, edata in entity_chunks.items():
                if ename.lower() == entity.lower():
                    for cid in edata.get("chunk_ids", []):
                        for rel_path, content in chunk_index.get(cid, []):
                            if rel_path not in candidate_files:
                                candidate_files[rel_path] = content
                    break

        # 2. Score each candidate file
        candidates: list[dict] = []
        seen_files: set[str] = set()

        for rel_path, chunk_content in candidate_files.items():
            if rel_path in seen_files:
                continue
            seen_files.add(rel_path)

            # Read actual file from waf_root
            full_path = waf_root / rel_path
            if rel_path not in file_cache:
                try:
                    file_cache[rel_path] = full_path.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    file_cache[rel_path] = None

            file_content = file_cache[rel_path]
            if file_content is None:
                # Fall back to chunk content
                file_content = chunk_content

            # Sliding-window fuzzy match
            ratio, pos, context = _best_window_match(fact_text, file_content)

            if ratio < 0.3:
                continue

            heading = _find_nearest_heading(file_content, pos)
            line_approx = _line_number_at(file_content, pos)

            # Score: match_ratio * 1.0 + heading relevance * 0.2
            heading_bonus = 0.0
            if heading:
                h_ratio, _ = token_overlap_ratio(fact_text, heading)
                heading_bonus = h_ratio * 0.2

            score = min(1.0, ratio + heading_bonus)
            q_tokens = set(_tokenize(fact_text))
            matched = q_tokens & set(_tokenize(context))

            candidates.append({
                "file": rel_path,
                "heading": heading,
                "line_approx": line_approx,
                "context": _truncate(context, 300),
                "location_confidence": round(score, 3),
                "match_evidence": f"matched tokens: {', '.join(sorted(matched))}",
            })

        # Sort by confidence descending
        candidates.sort(key=lambda c: c["location_confidence"], reverse=True)

        best = candidates[0] if candidates else None
        manual_needed = best is None or best["location_confidence"] < 0.6

        results.append({
            "fact_id": fid,
            "entity": entity,
            "fact": fact_text,
            "candidate_locations": candidates,
            "best_location": best,
            "manual_location_needed": manual_needed,
        })

    return results


def _truncate(s: str, max_len: int) -> str:
    if len(s) <= max_len:
        return s
    return s[: max_len - 3] + "..."


def _print_dry_run_stats(
    facts: list,
    entity_chunks: dict,
    text_chunks: dict,
    chunk_index: dict,
    domain: str,
    waf_root: Path,
) -> None:
    """Print summary stats without writing output."""
    entities_in_facts = {f.get("entity", "") for f in facts}
    entities_in_chunks = set(entity_chunks.keys())
    matched_entities = entities_in_facts & entities_in_chunks
    unmatched = entities_in_facts - entities_in_chunks

    # Count unique files in chunk index
    unique_files: set[str] = set()
    for entries in chunk_index.values():
        for rel, _ in entries:
            unique_files.add(rel)

    print(f"Domain:              {domain}")
    print(f"WAF root:            {waf_root}")
    print(f"Facts loaded:        {len(facts)}")
    print(f"Entities in facts:   {len(entities_in_facts)}")
    print(f"Entities in chunks:  {len(entities_in_chunks)}")
    print(f"Matched entities:    {len(matched_entities)}")
    print(f"Unmatched entities:  {len(unmatched)}")
    if unmatched:
        for e in sorted(unmatched):
            print(f"  - {e}")
    print(f"Text chunks:         {len(text_chunks)}")
    print(f"Unique files:        {len(unique_files)}")
    print(f"WAF root exists:     {waf_root.is_dir()}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Locate facts from facts.json in WAF source files."
    )
    parser.add_argument(
        "--domain",
        default=DEFAULT_DOMAIN,
        help=f"LightRAG domain (default: {DEFAULT_DOMAIN})",
    )
    parser.add_argument(
        "--entity",
        default=None,
        help="Process only facts for this entity",
    )
    parser.add_argument(
        "--waf-root",
        type=Path,
        default=None,
        help="Path to well-architected content dir (default: auto-detect)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print stats only, no output file",
    )
    args = parser.parse_args()

    waf_root = args.waf_root
    if waf_root is None:
        waf_root = HERE.parent / "well-architected"
    waf_root = waf_root.resolve()

    results = locate_facts(
        domain=args.domain,
        waf_root=waf_root,
        entity_filter=args.entity,
        dry_run=args.dry_run,
    )

    if args.dry_run:
        return

    out_dir = HERE / "mental_models"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "fact_locations.json"
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=2, ensure_ascii=False)

    # Summary
    total = len(results)
    located = sum(1 for r in results if not r["manual_location_needed"])
    manual = total - located
    high_conf = sum(
        1 for r in results
        if r["best_location"] and r["best_location"]["location_confidence"] >= 0.8
    )
    print(f"Wrote {out_path}")
    print(f"  Total facts:       {total}")
    print(f"  Located (≥0.6):    {located}")
    print(f"  High confidence:   {high_conf}")
    print(f"  Manual needed:     {manual}")


if __name__ == "__main__":
    main()
