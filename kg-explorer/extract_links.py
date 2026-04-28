#!/usr/bin/env python3
"""Extract and classify all markdown links from WAF source files.

Parses markdown files, extracts [text](url) links, classifies them,
resolves relative paths to canonical WAF paths, and outputs data/links.json.

Usage:
    python3 extract_links.py                          # all SOURCES
    python3 extract_links.py --dir mission-critical   # single subdir
"""
from __future__ import annotations

import json
import pathlib
import re
import sys
from urllib.parse import urlparse

HERE = pathlib.Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
WAF_ROOT = REPO_ROOT / "well-architected"
OUT_DIR = HERE / "data"

LEARN_BASE = "https://learn.microsoft.com"

LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"}


def classify_link(url: str, source_file: pathlib.Path) -> dict | None:
    """Classify a link and return structured metadata, or None to skip."""
    url = url.strip()

    # Skip anchors and images
    if url.startswith("#"):
        return None
    parsed = urlparse(url)
    if pathlib.Path(parsed.path).suffix.lower() in IMAGE_EXTS:
        return None

    # Relative internal WAF link (../reliability/metrics.md#anchor)
    if url.startswith("../") or url.startswith("./"):
        anchor = parsed.fragment or None
        rel_path = url.split("#")[0].split("?")[0]
        resolved = (source_file.parent / rel_path).resolve()
        try:
            waf_rel = resolved.relative_to(WAF_ROOT)
        except ValueError:
            return {"type": "external", "url": url, "resolved": None}
        canonical = str(waf_rel)
        learn_slug = canonical.replace(".md", "")
        learn_url = f"{LEARN_BASE}/azure/well-architected/{learn_slug}"
        if anchor:
            learn_url += f"#{anchor}"
        return {
            "type": "internal-waf",
            "url": url,
            "resolved": canonical,
            "learn_url": learn_url,
            "anchor": anchor,
        }

    # Absolute Azure path (/azure/...)
    if url.startswith("/azure/"):
        learn_url = f"{LEARN_BASE}{url}"
        # Check if it's a WAF link
        waf_prefix = "/azure/well-architected/"
        if url.startswith(waf_prefix):
            slug = url[len(waf_prefix):]
            canonical = slug.split("#")[0].split("?")[0]
            if not canonical.endswith(".md"):
                canonical += ".md"
            return {
                "type": "internal-waf",
                "url": url,
                "resolved": canonical,
                "learn_url": learn_url,
                "anchor": urlparse(url).fragment or None,
            }
        return {
            "type": "azure-docs",
            "url": url,
            "learn_url": learn_url,
        }

    # Full URLs
    if url.startswith("http://") or url.startswith("https://"):
        if "learn.microsoft.com/azure/well-architected" in url:
            # Parse out the WAF slug
            path = urlparse(url).path
            waf_prefix = "/azure/well-architected/"
            if waf_prefix in path:
                slug = path[path.index(waf_prefix) + len(waf_prefix):]
                canonical = slug.split("?")[0]
                if not canonical.endswith(".md"):
                    canonical += ".md"
                return {
                    "type": "internal-waf",
                    "url": url,
                    "resolved": canonical,
                    "learn_url": url.split("?")[0],
                    "anchor": urlparse(url).fragment or None,
                }
        if "learn.microsoft.com" in url:
            return {"type": "azure-docs", "url": url, "learn_url": url}
        return {"type": "external", "url": url}

    return None


def extract_links_from_file(filepath: pathlib.Path) -> list[dict]:
    """Extract all links from a markdown file with context."""
    text = filepath.read_text(encoding="utf-8")
    links = []

    # Track current heading for context
    heading_re = re.compile(r"^(#{1,3})\s+(.+)$", re.MULTILINE)
    headings = [(m.start(), m.group(2).strip()) for m in heading_re.finditer(text)]

    for m in LINK_RE.finditer(text):
        link_text = m.group(1).strip()
        url = m.group(2).strip()

        classified = classify_link(url, filepath)
        if classified is None:
            continue

        # Find the heading this link is under
        pos = m.start()
        section = None
        for h_pos, h_text in reversed(headings):
            if h_pos < pos:
                section = h_text
                break

        classified["text"] = link_text
        classified["section"] = section
        links.append(classified)

    return links


def extract_all(sources_dir: str | None = None) -> dict:
    """Extract links from all source files. Returns {source_path: [links]}."""
    from ingest import SOURCES, SKIP_NAMES

    result: dict[str, list[dict]] = {}
    sources = [(d, r) for d, r in SOURCES if sources_dir is None or d == sources_dir]

    for sub, recursive in sources:
        d = WAF_ROOT / sub
        if not d.is_dir():
            continue
        it = d.rglob("*.md") if recursive else d.glob("*.md")
        for p in sorted(it):
            if p.name in SKIP_NAMES:
                continue
            rel = str(p.relative_to(WAF_ROOT))
            links = extract_links_from_file(p)
            if links:
                result[rel] = links

    return result


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", help="limit to a single subdir")
    ap.add_argument("--stats", action="store_true", help="print stats only")
    args = ap.parse_args()

    data = extract_all(args.dir)

    # Stats
    from collections import Counter
    type_counts = Counter()
    total = 0
    for links in data.values():
        for link in links:
            type_counts[link["type"]] += 1
            total += 1

    print(f"Extracted {total} links from {len(data)} files:")
    for t, c in type_counts.most_common():
        print(f"  {t}: {c}")

    # Internal WAF cross-references (the high-value ones)
    internal = []
    for source, links in data.items():
        for link in links:
            if link["type"] == "internal-waf":
                internal.append({"from": source, "to": link["resolved"], "text": link["text"]})

    print(f"\nInternal WAF cross-references: {len(internal)}")
    for ref in internal[:10]:
        print(f"  {ref['from']:45s} → {ref['to']}")

    if args.stats:
        return 0

    # Write output
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / "links.json"
    out_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n✓ wrote {out_path} ({out_path.stat().st_size / 1024:.0f} KB)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
