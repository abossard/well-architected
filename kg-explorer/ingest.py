#!/usr/bin/env python3
"""Unified ingestion: pull every WAF markdown file into LightRAG.

Replaces ingest_lightrag.py + ingest_all_waf.py + ingest_batch2.py.

Already-ingested files (tracked in kv_store_doc_status.json) are skipped,
so re-running the script only picks up new or changed docs.

Usage:
    python3 ingest.py                    # ingest everything
    python3 ingest.py --dir reliability  # ingest a single subdir only
    python3 ingest.py --dry-run          # list pending files, don't ingest

Requires the copilot-api proxy on port 11435.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
import re
import sys
import urllib.request
from functools import partial

PROXY_URL = "http://127.0.0.1:11435/v1"
API_KEY = "copilot-proxy"
LLM_MODEL = "claude-opus-4.6"
EMBED_MODEL = "text-embedding-3-small"
EMBED_DIM = 1536

ROOT = pathlib.Path(__file__).resolve().parent
REPO_ROOT = ROOT.parent
WAF_ROOT = REPO_ROOT / "well-architected"

# Per-domain RAG directory to prevent future mixing
DEFAULT_DOMAIN = "mission-critical"
RAG_DIR_BASE = ROOT / "lightrag_data"

MIN_CHARS = 100
SKIP_NAMES = {"TOC.md", "index.md"}

LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"}

# (subdir, recursive) — focused on mission-critical + curated cross-refs
SOURCES: list[tuple[str, bool]] = [
    ("mission-critical", False),
]


def rag_dir_for_domain(domain: str) -> pathlib.Path:
    """Per-domain RAG directory to prevent cross-domain mixing."""
    return ROOT / f"lightrag_data_{domain}"


def strip_frontmatter(text: str) -> str:
    if text.startswith("---"):
        m = re.match(r"^---\n.*?\n---\n", text, re.DOTALL)
        if m:
            return text[m.end():]
    return text


def extract_link_context(text: str, filepath: pathlib.Path) -> str:
    """Extract outbound links from markdown and format as a references section.

    Appended to the text before LightRAG ingestion so the LLM entity extractor
    picks up cross-reference relationships.
    """
    from urllib.parse import urlparse

    refs: list[str] = []
    for m in LINK_RE.finditer(text):
        link_text = m.group(1).strip()
        url = m.group(2).strip()
        if url.startswith("#"):
            continue
        parsed = urlparse(url)
        if pathlib.Path(parsed.path).suffix.lower() in IMAGE_EXTS:
            continue
        if not link_text:
            continue
        refs.append(f"- {link_text}: {url}")

    if not refs:
        return ""
    return "\n\n## References and Cross-links\n\nThis document references the following:\n" + "\n".join(refs)


def collect_files(only_dir: str | None = None) -> list[pathlib.Path]:
    files: list[pathlib.Path] = []
    sources = [(d, r) for d, r in SOURCES if only_dir is None or d == only_dir]
    for sub, recursive in sources:
        d = WAF_ROOT / sub
        if not d.is_dir():
            continue
        it = d.rglob("*.md") if recursive else d.glob("*.md")
        for p in sorted(it):
            if p.name in SKIP_NAMES:
                continue
            files.append(p)
    # Root-level *.md (framework overview etc.)
    if only_dir is None:
        for p in sorted(WAF_ROOT.glob("*.md")):
            if p.name not in SKIP_NAMES:
                files.append(p)
    return files


def already_ingested(rag_dir: pathlib.Path) -> set[str]:
    doc_status = rag_dir / "kv_store_doc_status.json"
    if not doc_status.exists():
        return set()
    data = json.loads(doc_status.read_text())
    return {v.get("file_path") for v in data.values() if v.get("file_path")}


def ensure_proxy() -> None:
    try:
        urllib.request.urlopen("http://127.0.0.1:11435/", timeout=3)
    except Exception:
        print(
            "ERROR: copilot-api proxy not reachable at :11435. "
            "Start it with: npx copilot-api start --port 11435",
            file=sys.stderr,
        )
        sys.exit(1)


async def ingest(files: list[pathlib.Path], rag_dir: pathlib.Path) -> None:
    from lightrag import LightRAG
    from lightrag.llm.openai import openai_complete_if_cache, openai_embed
    from lightrag.utils import EmbeddingFunc

    async def llm_func(prompt, system_prompt=None, history_messages=None, **kwargs):
        return await openai_complete_if_cache(
            LLM_MODEL, prompt, system_prompt=system_prompt,
            history_messages=history_messages,
            base_url=PROXY_URL, api_key=API_KEY, **kwargs,
        )

    rag = LightRAG(
        working_dir=str(rag_dir),
        llm_model_func=llm_func,
        llm_model_name=LLM_MODEL,
        llm_model_max_async=2,
        embedding_batch_num=16,
        embedding_func_max_async=4,
        max_parallel_insert=1,
        embedding_func=EmbeddingFunc(
            embedding_dim=EMBED_DIM, max_token_size=8192, model_name=EMBED_MODEL,
            func=partial(openai_embed.func, model=EMBED_MODEL,
                         base_url=PROXY_URL, api_key=API_KEY),
        ),
    )
    await rag.initialize_storages()

    total = len(files)
    for i, f in enumerate(files, 1):
        try:
            raw = f.read_text(encoding="utf-8")
            text = strip_frontmatter(raw)
        except Exception as e:
            print(f"[{i}/{total}] READ ERROR {f}: {e}", flush=True)
            continue
        if len(text.strip()) < MIN_CHARS:
            print(f"[{i}/{total}] SKIP (too short) {f.relative_to(REPO_ROOT)}", flush=True)
            continue

        # Append link context so LLM captures cross-references
        link_ctx = extract_link_context(text, f)
        if link_ctx:
            text += link_ctx

        rel = str(f.relative_to(REPO_ROOT))
        print(f"[{i}/{total}] {rel} ({len(text)} chars, {'+links' if link_ctx else 'no links'})", flush=True)
        try:
            await rag.ainsert(text, file_paths=[rel])
        except Exception as e:
            print(f"  ERROR: {e}", flush=True)


async def main_async(args: argparse.Namespace) -> int:
    domain = args.domain or DEFAULT_DOMAIN
    rag_dir = rag_dir_for_domain(domain)
    rag_dir.mkdir(parents=True, exist_ok=True)

    files = collect_files(args.dir)
    ingested = already_ingested(rag_dir)
    pending = [
        f for f in files
        if str(f) not in ingested and str(f.relative_to(REPO_ROOT)) not in ingested
    ]

    print(f"Domain: {domain}")
    print(f"RAG dir: {rag_dir}")
    print(f"Found {len(files)} markdown files ({len(ingested)} already ingested, {len(pending)} pending)")
    if args.dry_run:
        for f in pending:
            print(f"  {f.relative_to(REPO_ROOT)}")
        return 0
    if not pending:
        print("Nothing to do.")
        return 0

    ensure_proxy()
    await ingest(pending, rag_dir)
    print("DONE")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", help="limit ingestion to a single subdir (e.g. reliability)")
    ap.add_argument("--domain", default=DEFAULT_DOMAIN, help="domain name for per-domain RAG isolation (default: mission-critical)")
    ap.add_argument("--dry-run", action="store_true", help="print pending files, don't ingest")
    args = ap.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
