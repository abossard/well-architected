#!/usr/bin/env python3
"""Ingest mission-critical markdown files into LightRAG via copilot-api proxy.

Uses:
- Claude Opus 4.6 for LLM (entity extraction, summarization)
- text-embedding-3-small for embeddings (1536 dims)
Both routed through copilot-api proxy → GitHub Copilot.

Prerequisites:
    1. Start the proxy:  npx copilot-api start --port 11435
    2. Run this script:  python3 ingest_lightrag.py
"""
import asyncio
import os
import sys
import pathlib
import re
import numpy as np

PROXY_URL = "http://127.0.0.1:11435/v1"
API_KEY = "copilot-proxy"
LLM_MODEL = "claude-opus-4.6"
EMBED_MODEL = "text-embedding-3-small"
EMBED_DIM = 1536

SRC_DIR = pathlib.Path(__file__).parent.parent / "well-architected" / "mission-critical"
RAG_DIR = pathlib.Path(__file__).parent / "lightrag_data"


async def main():
    # Verify proxy is up
    import urllib.request
    try:
        urllib.request.urlopen("http://127.0.0.1:11435/", timeout=3)
    except Exception as e:
        print(f"ERROR: Proxy not reachable at port 11435. Start copilot-api: npx copilot-api start --port 11435")
        sys.exit(1)

    from lightrag import LightRAG
    from lightrag.llm.openai import openai_complete_if_cache, openai_embed
    from lightrag.utils import EmbeddingFunc
    from functools import partial

    os.makedirs(RAG_DIR, exist_ok=True)

    async def llm_func(prompt, system_prompt=None, history_messages=None, **kwargs):
        return await openai_complete_if_cache(
            LLM_MODEL,
            prompt,
            system_prompt=system_prompt,
            history_messages=history_messages,
            base_url=PROXY_URL,
            api_key=API_KEY,
            **kwargs,
        )

    rag = LightRAG(
        working_dir=str(RAG_DIR),
        llm_model_func=llm_func,
        llm_model_name=LLM_MODEL,
        llm_model_max_async=2,
        embedding_batch_num=16,
        embedding_func_max_async=4,
        max_parallel_insert=1,
        embedding_func=EmbeddingFunc(
            embedding_dim=EMBED_DIM,
            max_token_size=8192,
            model_name=EMBED_MODEL,
            func=partial(
                openai_embed.func,
                model=EMBED_MODEL,
                base_url=PROXY_URL,
                api_key=API_KEY,
            ),
        ),
    )

    await rag.initialize_storages()

    # Collect markdown files
    md_files = sorted(SRC_DIR.glob("mission-critical-*.md"))
    print(f"Found {len(md_files)} files to ingest")

    for i, md_file in enumerate(md_files, 1):
        text = md_file.read_text(encoding="utf-8")

        # Strip YAML front matter
        if text.startswith("---"):
            import re
            m = re.match(r"^---\n.*?\n---\n", text, re.DOTALL)
            if m:
                text = text[m.end():]

        print(f"[{i}/{len(md_files)}] Ingesting {md_file.name} ({len(text)} chars)...")

        try:
            await rag.ainsert(text, file_paths=[str(md_file)])
        except Exception as e:
            print(f"  ERROR: {e}")
            # try again with smaller chunks for large files
            if len(text) > 10000:
                print("  Retrying with smaller text chunks...")
                chunks = [text[j:j+8000] for j in range(0, len(text), 7500)]
                for ci, chunk in enumerate(chunks):
                    try:
                        await rag.ainsert(chunk)
                        print(f"  Chunk {ci+1}/{len(chunks)} OK")
                    except Exception as e2:
                        print(f"  Chunk {ci+1} failed: {e2}")

    print(f"\nDone! LightRAG data stored in: {RAG_DIR}")
    print(f"You can now query it with: python3 query_lightrag.py 'your question'")

    # Quick test query
    print("\n--- Test query: 'What are deployment stamps?' ---")
    try:
        result = await rag.aquery("What are deployment stamps and why are they important for mission-critical workloads?")
        print(result[:500])
    except Exception as e:
        print(f"Query test failed: {e}")


if __name__ == "__main__":
    asyncio.run(main())
