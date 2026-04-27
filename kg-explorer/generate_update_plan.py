#!/usr/bin/env python3
"""Generate a documentation update plan from verification + location data.

Joins outdated verifications with fact locations to produce:
  - mental_models/update_plan.md   (human-readable diff-style report)
  - mental_models/update_plan.json (machine-readable action list)

Usage:
    python3 generate_update_plan.py                      # generate from existing files
    python3 generate_update_plan.py --no-llm             # skip LLM suggestions
    python3 generate_update_plan.py --waf-root /path     # custom WAF content root
    python3 generate_update_plan.py --proxy-url URL      # LLM proxy for suggestions
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import re
import sys
import urllib.request
from datetime import datetime, timezone
from typing import Any

# ─── paths ──────────────────────────────────────────────────────────────────

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent
DEFAULT_WAF_ROOT = REPO / "well-architected"
MENTAL_MODELS = HERE / "mental_models"

DEFAULT_VERIFICATIONS = MENTAL_MODELS / "verifications.json"
DEFAULT_LOCATIONS = MENTAL_MODELS / "fact_locations.json"
DEFAULT_OUTPUT_MD = MENTAL_MODELS / "update_plan.md"
DEFAULT_OUTPUT_JSON = MENTAL_MODELS / "update_plan.json"

# ─── LLM config ────────────────────────────────────────────────────────────

DEFAULT_PROXY_URL = "http://127.0.0.1:11435/v1"
DEFAULT_API_KEY = "copilot-proxy"
DEFAULT_MODEL = "claude-opus-4.6"

HIGH_CONFIDENCE_THRESHOLD = 0.8

HEADING_RE = re.compile(r"^(#{1,4})\s+(.+)$", re.MULTILINE)


# ─── helpers ────────────────────────────────────────────────────────────────

def load_json(path: pathlib.Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_env() -> None:
    """Load .env file from HERE if present, set as os.environ defaults."""
    env_file = HERE / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip().strip("'\"")
        os.environ.setdefault(key, val)


def get_llm_config(proxy_url: str | None) -> dict:
    """Resolve LLM config: CLI arg → env var → .env → default."""
    load_env()
    return {
        "base_url": proxy_url
        or os.environ.get("LLM_BINDING_HOST", DEFAULT_PROXY_URL),
        "model": os.environ.get("LLM_MODEL", DEFAULT_MODEL),
        "api_key": os.environ.get("OPENAI_API_KEY", os.environ.get("LLM_API_KEY", DEFAULT_API_KEY)),
    }


def fact_id(entity: str, fact: str) -> str:
    """Compute a stable fact_id as sha256 hash of entity+fact.

    Must match the hashing in verify_facts.py and locate_facts.py.
    """
    key = entity + "\0" + fact
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


# ─── file reading ───────────────────────────────────────────────────────────

def read_context_lines(
    file_path: pathlib.Path,
    line_approx: int | None,
    radius: int = 5,
) -> str:
    """Read ±radius lines around line_approx from the actual file.

    If line_approx is None, return the first paragraph under the first heading.
    """
    if not file_path.exists():
        return ""
    try:
        lines = file_path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return ""

    if line_approx is not None and 1 <= line_approx <= len(lines):
        start = max(0, line_approx - 1 - radius)
        end = min(len(lines), line_approx - 1 + radius + 1)
        return "\n".join(lines[start:end])

    # fallback: first paragraph after first heading
    for i, line in enumerate(lines):
        if HEADING_RE.match(line):
            para_lines: list[str] = []
            for j in range(i + 1, min(i + 20, len(lines))):
                if lines[j].strip() == "":
                    if para_lines:
                        break
                    continue
                if HEADING_RE.match(lines[j]):
                    break
                para_lines.append(lines[j])
            if para_lines:
                return "\n".join(para_lines)
    return ""


def resolve_file_path(file_ref: str | None, waf_root: pathlib.Path) -> pathlib.Path | None:
    """Resolve a file reference to an absolute path.

    Handles both "well-architected/mission-critical/foo.md" and
    "mission-critical/foo.md" formats.
    """
    if not file_ref:
        return None
    marker = "well-architected/"
    idx = file_ref.rfind(marker)
    if idx >= 0:
        rel = file_ref[idx + len(marker):]
    else:
        rel = file_ref
    abs_path = waf_root / rel
    return abs_path if abs_path.exists() else None


# ─── join logic ─────────────────────────────────────────────────────────────

def merge_verifications_and_locations(
    verifications: list[dict],
    locations: list[dict],
) -> list[dict]:
    """Join outdated verifications with locations on fact_id (sha256).

    Falls back to (entity, fact) tuple join if fact_id is missing.
    Returns merged dicts for outdated facts only.
    """
    # Build location index keyed by fact_id
    loc_by_id: dict[str, dict] = {}
    loc_by_tuple: dict[tuple[str, str], dict] = {}
    for loc in locations:
        fid = loc.get("fact_id") or fact_id(loc.get("entity", ""), loc.get("fact", ""))
        loc_by_id[fid] = loc
        loc_by_tuple[(loc.get("entity", ""), loc.get("fact", ""))] = loc

    merged: list[dict] = []
    for v in verifications:
        if v.get("verdict") != "outdated":
            continue

        fid = v.get("fact_id") or fact_id(v.get("entity", ""), v.get("fact", ""))
        loc = loc_by_id.get(fid) or loc_by_tuple.get(
            (v.get("entity", ""), v.get("fact", ""))
        )

        entry = {
            "fact_id": fid,
            "entity": v.get("entity", ""),
            "fact": v.get("fact", ""),
            "verdict": "outdated",
            "current_info": v.get("current_info", ""),
            "confidence": v.get("confidence", "unknown"),
            "source_url": v.get("source_url", ""),
            "reasoning": v.get("reasoning", ""),
            "verified_at": v.get("verified_at", ""),
            "search_query": v.get("search_query", ""),
        }

        # Extract location from best_location (nested) or top-level (fallback)
        if loc:
            best = loc.get("best_location") or {}
            entry.update({
                "file": best.get("file") or loc.get("file"),
                "heading": best.get("heading") or loc.get("heading"),
                "line_approx": best.get("line_approx") or loc.get("line_approx"),
                "context": best.get("context") or loc.get("context"),
                "location_confidence": best.get("location_confidence") or loc.get("match_score", 0.0),
                "candidate_locations": loc.get("candidate_locations"),
                "manual_location_needed": loc.get("manual_location_needed", False),
            })
        else:
            entry.update({
                "file": None, "heading": None, "line_approx": None,
                "context": None, "location_confidence": 0.0,
                "manual_location_needed": True,
            })

        merged.append(entry)

    return merged


# ─── LLM suggestion ────────────────────────────────────────────────────────

SUGGEST_SYSTEM = """You are a technical writer for Azure documentation.
Given the CURRENT TEXT from a document and the UPDATED FACT,
write a replacement paragraph that:
1. Preserves the original tone and style (Microsoft style guide)
2. Incorporates the corrected information
3. Keeps the same approximate length
4. Uses contractions, sentence-style capitalization
5. Does NOT add marketing language

Return ONLY the replacement text, no explanation."""

SUGGEST_USER = """FILE: {file_path}
SECTION: {heading}
CONTEXT:
{surrounding_paragraph}

OUTDATED CLAIM: "{fact}"
CURRENT INFORMATION: "{current_info}" (source: {source_url})

Generate a replacement sentence that:
1. States the current information accurately
2. Matches the tone and style of the surrounding context
3. Is concise and factual

Return ONLY the replacement text, no explanation."""


def llm_suggest(
    current_text: str,
    outdated_fact: str,
    current_info: str,
    source_url: str,
    file_path: str,
    heading: str,
    llm_config: dict,
) -> str | None:
    """Call LLM to generate a suggested replacement paragraph.

    Uses urllib (same pattern as ingest.py). Returns None on failure.
    """
    user_msg = SUGGEST_USER.format(
        file_path=file_path or "unknown",
        heading=heading or "unknown",
        surrounding_paragraph=current_text or "(not available)",
        fact=outdated_fact,
        current_info=current_info,
        source_url=source_url or "N/A",
    )

    payload = json.dumps({
        "model": llm_config["model"],
        "messages": [
            {"role": "system", "content": SUGGEST_SYSTEM},
            {"role": "user", "content": user_msg},
        ],
        "temperature": 0.3,
        "max_tokens": 500,
    }).encode("utf-8")

    url = f"{llm_config['base_url'].rstrip('/')}/chat/completions"
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {llm_config['api_key']}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        return (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        ) or None
    except Exception as e:
        print(f"  LLM suggestion failed: {e}", file=sys.stderr)
        return None


# ─── output generation ─────────────────────────────────────────────────────

def _confidence_label(score: float) -> str:
    if score >= 0.8:
        return "high"
    if score >= 0.5:
        return "medium"
    return "low"


def generate_markdown_plan(
    updates: list[dict],
    total_verified: int,
    total_outdated: int,
) -> str:
    """Render the human-readable update_plan.md."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    lines: list[str] = [
        "# Documentation Update Plan",
        "",
        f"Generated: {now}",
        f"Outdated facts: {total_outdated} of {total_verified} perishable facts need updates",
        "",
    ]

    # Summary table grouped by file
    files_summary: dict[str, list[dict]] = {}
    for u in updates:
        f = u.get("file") or "(unknown file)"
        files_summary.setdefault(f, []).append(u)

    lines.append("## Summary")
    lines.append("")
    lines.append("| File | Updates | Confidence |")
    lines.append("|------|---------|------------|")
    for f, items in sorted(files_summary.items()):
        conf_counts: dict[str, int] = {}
        for item in items:
            loc_conf = _confidence_label(item.get("location_confidence", 0.0))
            conf_counts[loc_conf] = conf_counts.get(loc_conf, 0) + 1
        conf_str = ", ".join(f"{v} {k}" for k, v in sorted(conf_counts.items(), reverse=True))
        fname = pathlib.PurePosixPath(f).name
        lines.append(f"| {fname} | {len(items)} | {conf_str} |")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Detailed entries grouped by file
    lines.append("## Updates")
    lines.append("")

    for f, items in sorted(files_summary.items()):
        lines.append(f"### {f}")
        lines.append("")

        for u in items:
            heading = u.get("heading") or "(heading unknown)"
            line_info = f" (line ~{u['line_approx']})" if u.get("line_approx") else ""
            loc_conf = u.get("location_confidence", 0.0)
            manual_review = loc_conf < HIGH_CONFIDENCE_THRESHOLD

            lines.append(f"#### Under \"{heading}\"{line_info}")
            lines.append("")
            lines.append(f"**Entity:** {u.get('entity', 'unknown')}")
            lines.append("")

            # Current text from file
            ctx = u.get("current_text") or u.get("context") or ""
            if ctx:
                lines.append("**Current text:**")
                for ctx_line in ctx.splitlines():
                    lines.append(f"> {ctx_line}")
                lines.append("")

            lines.append("**Outdated claim:**")
            lines.append(f"> {u.get('fact', '')}")
            lines.append("")

            lines.append("**Current information:**")
            lines.append(f"> {u.get('current_info', '')}")
            lines.append("")

            if manual_review:
                lines.append(
                    f"⚠️ **Manual review needed** — location confidence: "
                    f"{loc_conf:.2f}"
                )
                lines.append("")
            else:
                suggested = u.get("suggested_replacement")
                if suggested:
                    lines.append("**Suggested replacement:**")
                    lines.append("```diff")
                    lines.append(f"- {u.get('fact', '')}")
                    lines.append(f"+ {suggested}")
                    lines.append("```")
                else:
                    lines.append("**Suggested replacement:**")
                    lines.append("> Run with `--suggest` to generate LLM suggestions")
                lines.append("")

            if u.get("source_url"):
                lines.append(f"**Source:** {u['source_url']}")
            lines.append(f"**Confidence:** {u.get('confidence', 'unknown')}")
            lines.append(f"**Location confidence:** {loc_conf:.2f}")
            if u.get("verified_at"):
                lines.append(f"**Verified:** {u['verified_at']}")
            lines.append("")
            lines.append("---")
            lines.append("")

    return "\n".join(lines)


def generate_json_plan(
    updates: list[dict],
    total_verified: int,
    total_outdated: int,
    total_current: int,
    total_unverifiable: int,
) -> dict:
    """Machine-readable plan for automation."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    entries: list[dict] = []
    for u in updates:
        loc_conf = u.get("location_confidence", 0.0)
        entries.append({
            "fact_id": u.get("fact_id", ""),
            "entity": u.get("entity", ""),
            "fact": u.get("fact", ""),
            "status": "outdated",
            "current_info": u.get("current_info", ""),
            "file": u.get("file"),
            "heading": u.get("heading"),
            "line_approx": u.get("line_approx"),
            "location_confidence": round(loc_conf, 3),
            "suggested_replacement": u.get("suggested_replacement"),
            "source_url": u.get("source_url", ""),
            "confidence": u.get("confidence", "unknown"),
            "verified_at": u.get("verified_at", ""),
            "manual_review_needed": loc_conf < HIGH_CONFIDENCE_THRESHOLD,
        })

    return {
        "generated_at": now,
        "total_verified": total_verified,
        "total_outdated": total_outdated,
        "total_current": total_current,
        "total_unverifiable": total_unverifiable,
        "updates": entries,
    }


# ─── main ───────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "--verifications",
        type=pathlib.Path,
        default=DEFAULT_VERIFICATIONS,
        help="path to verifications.json",
    )
    ap.add_argument(
        "--locations",
        type=pathlib.Path,
        default=DEFAULT_LOCATIONS,
        help="path to fact_locations.json",
    )
    ap.add_argument(
        "--output-md",
        type=pathlib.Path,
        default=DEFAULT_OUTPUT_MD,
        help="output path for update_plan.md",
    )
    ap.add_argument(
        "--output-json",
        type=pathlib.Path,
        default=DEFAULT_OUTPUT_JSON,
        help="output path for update_plan.json",
    )
    ap.add_argument(
        "--waf-root",
        type=pathlib.Path,
        default=DEFAULT_WAF_ROOT,
        help="path to well-architected/ content dir",
    )
    ap.add_argument(
        "--no-llm",
        action="store_true",
        help="skip LLM replacement suggestions",
    )
    ap.add_argument(
        "--suggest",
        action="store_true",
        default=False,
        help="use LLM to generate replacement text for high-confidence locations",
    )
    ap.add_argument(
        "--proxy-url",
        type=str,
        default=None,
        help="LLM proxy URL (overrides env/default)",
    )
    args = ap.parse_args()

    # --no-llm overrides --suggest
    use_llm = args.suggest and not args.no_llm

    # ── load inputs ─────────────────────────────────────────────────────
    if not args.verifications.exists():
        print(f"ERROR: {args.verifications} not found. Run verify_facts.py first.", file=sys.stderr)
        return 1

    if not args.locations.exists():
        print(f"ERROR: {args.locations} not found. Run locate_facts.py first.", file=sys.stderr)
        return 1

    verifications: list[dict] = load_json(args.verifications)
    locations: list[dict] = load_json(args.locations)

    print(f"Loaded {len(verifications)} verifications, {len(locations)} locations")

    # ── count totals ────────────────────────────────────────────────────
    total_verified = len(verifications)
    verdicts = [v.get("verdict", "") for v in verifications]
    total_outdated = verdicts.count("outdated")
    total_current = verdicts.count("current")
    total_unverifiable = verdicts.count("unverifiable")

    print(f"Verdicts: {total_current} current, {total_outdated} outdated, "
          f"{total_unverifiable} unverifiable")

    if total_outdated == 0:
        print("No outdated facts found — nothing to update.")
        # Still write empty outputs for pipeline consistency
        args.output_md.parent.mkdir(parents=True, exist_ok=True)
        args.output_md.write_text(
            "# Documentation Update Plan\n\nNo outdated facts found.\n",
            encoding="utf-8",
        )
        args.output_json.write_text(
            json.dumps(generate_json_plan([], total_verified, 0, total_current, total_unverifiable), indent=2),
            encoding="utf-8",
        )
        return 0

    # ── merge ───────────────────────────────────────────────────────────
    merged = merge_verifications_and_locations(verifications, locations)
    print(f"Merged {len(merged)} outdated facts with location data")

    # ── read actual file context + optionally generate suggestions ──────
    llm_config = get_llm_config(args.proxy_url) if use_llm else None

    for i, entry in enumerate(merged, 1):
        file_path = resolve_file_path(entry.get("file"), args.waf_root)
        loc_conf = entry.get("location_confidence", 0.0)

        # Read context from actual file
        if file_path:
            ctx = read_context_lines(file_path, entry.get("line_approx"))
            if ctx:
                entry["current_text"] = ctx
        elif entry.get("context"):
            entry["current_text"] = entry["context"]

        # Generate LLM suggestion only for high-confidence locations
        if use_llm and loc_conf >= HIGH_CONFIDENCE_THRESHOLD and llm_config:
            print(f"  [{i}/{len(merged)}] Generating suggestion for: "
                  f"{entry.get('entity', '?')} — {entry.get('fact', '?')[:60]}...")
            suggestion = llm_suggest(
                current_text=entry.get("current_text", ""),
                outdated_fact=entry.get("fact", ""),
                current_info=entry.get("current_info", ""),
                source_url=entry.get("source_url", ""),
                file_path=entry.get("file", ""),
                heading=entry.get("heading", ""),
                llm_config=llm_config,
            )
            entry["suggested_replacement"] = suggestion
        else:
            entry["suggested_replacement"] = None

    # ── write outputs ───────────────────────────────────────────────────
    args.output_md.parent.mkdir(parents=True, exist_ok=True)

    md_content = generate_markdown_plan(merged, total_verified, total_outdated)
    args.output_md.write_text(md_content, encoding="utf-8")
    print(f"Wrote {args.output_md} ({len(md_content)} chars)")

    json_content = generate_json_plan(
        merged, total_verified, total_outdated, total_current, total_unverifiable,
    )
    json_text = json.dumps(json_content, indent=2, ensure_ascii=False)
    args.output_json.write_text(json_text, encoding="utf-8")
    print(f"Wrote {args.output_json} ({len(json_content['updates'])} entries)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
