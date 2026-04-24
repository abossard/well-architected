#!/usr/bin/env python3
"""Ingest WAF workload + service-guide docs (batch 2) into LightRAG."""
import asyncio, sys, pathlib, re
from functools import partial

PROXY_URL = "http://127.0.0.1:11435/v1"
API_KEY = "copilot-proxy"
LLM_MODEL = "claude-opus-4.6"
EMBED_MODEL = "text-embedding-3-small"
EMBED_DIM = 1536
RAG_DIR = pathlib.Path("/Users/abossard/Desktop/cxe/well-architected/kg-explorer/lightrag_data")
WAF_ROOT = pathlib.Path("/Users/abossard/Desktop/cxe/well-architected/well-architected")

MIN_CHARS = 100

# (subdir, recursive)
SOURCES = [
    ("service-guides", False),
    ("ai", False),
    ("saas", False),
    ("azure-virtual-desktop", False),
    ("azure-vmware", False),
    ("sustainability", False),
    ("sap", True),
    ("hpc", False),
    ("oracle-iaas", False),
]

SKIP_NAMES = {"TOC.md", "index.md"}


def collect_files():
    files = []
    for sub, recursive in SOURCES:
        d = WAF_ROOT / sub
        if not d.is_dir():
            continue
        it = d.rglob("*.md") if recursive else d.glob("*.md")
        for p in sorted(it):
            if p.name in SKIP_NAMES:
                continue
            files.append(p)
    return files


def strip_frontmatter(text: str) -> str:
    if text.startswith("---"):
        m = re.match(r"^---\n.*?\n---\n", text, re.DOTALL)
        if m:
            return text[m.end():]
    return text


async def main():
    from lightrag import LightRAG
    from lightrag.llm.openai import openai_complete_if_cache, openai_embed
    from lightrag.utils import EmbeddingFunc

    async def llm_func(prompt, system_prompt=None, history_messages=None, **kwargs):
        return await openai_complete_if_cache(
            LLM_MODEL, prompt, system_prompt=system_prompt,
            history_messages=history_messages,
            base_url=PROXY_URL, api_key=API_KEY, **kwargs)

    rag = LightRAG(
        working_dir=str(RAG_DIR),
        llm_model_func=llm_func,
        llm_model_name=LLM_MODEL,
        llm_model_max_async=2,
        embedding_batch_num=16,
        embedding_func_max_async=4,
        max_parallel_insert=1,
        embedding_func=EmbeddingFunc(
            embedding_dim=EMBED_DIM, max_token_size=8192,
            model_name=EMBED_MODEL,
            func=partial(openai_embed.func, model=EMBED_MODEL,
                         base_url=PROXY_URL, api_key=API_KEY)),
    )
    await rag.initialize_storages()

    files = collect_files()
    total = len(files)
    print(f"Collected {total} files", flush=True)

    for i, f in enumerate(files, 1):
        try:
            text = strip_frontmatter(f.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[{i}/{total}] READ ERROR {f}: {e}", flush=True)
            continue
        if len(text) < MIN_CHARS:
            print(f"[{i}/{total}] SKIP (too short) {f.relative_to(WAF_ROOT)} ({len(text)} chars)", flush=True)
            continue
        rel = f.relative_to(WAF_ROOT)
        print(f"[{i}/{total}] {rel} ({len(text)} chars)", flush=True)
        try:
            await rag.ainsert(text, file_paths=[str(f)])
        except Exception as e:
            print(f"  ERROR: {e}", flush=True)

    print("DONE", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
