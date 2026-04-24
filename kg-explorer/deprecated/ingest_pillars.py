#!/usr/bin/env python3
"""Ingest WAF pillar + design-guide docs into the existing LightRAG store."""
import asyncio, os, sys, pathlib, re
from functools import partial

PROXY_URL = "http://127.0.0.1:11435/v1"
API_KEY = "copilot-proxy"
LLM_MODEL = "claude-opus-4.6"
EMBED_MODEL = "text-embedding-3-small"
EMBED_DIM = 1536
RAG_DIR = pathlib.Path("pathlib.Path(__file__).parent.parent / "kg-explorer/lightrag_data")
WAF = pathlib.Path("pathlib.Path(__file__).parent.parent / "well-architected")

FILES = [
    # Reliability
    WAF/"reliability/principles.md",
    WAF/"reliability/checklist.md",
    WAF/"reliability/tradeoffs.md",
    WAF/"reliability/disaster-recovery.md",
    WAF/"reliability/failure-mode-analysis.md",
    WAF/"reliability/redundancy.md",
    # Security
    WAF/"security/principles.md",
    WAF/"security/checklist.md",
    WAF/"security/tradeoffs.md",
    # Performance Efficiency
    WAF/"performance-efficiency/principles.md",
    WAF/"performance-efficiency/checklist.md",
    WAF/"performance-efficiency/tradeoffs.md",
    # Operational Excellence
    WAF/"operational-excellence/principles.md",
    WAF/"operational-excellence/checklist.md",
    WAF/"operational-excellence/tradeoffs.md",
    WAF/"operational-excellence/safe-deployments.md",
    # Cost Optimization
    WAF/"cost-optimization/principles.md",
    WAF/"cost-optimization/checklist.md",
    WAF/"cost-optimization/tradeoffs.md",
    # Cross-cutting design guides
    WAF/"design-guides/health-modeling.md",
    WAF/"design-guides/regions-availability-zones.md",
]


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

    missing = [f for f in FILES if not f.exists()]
    if missing:
        print("MISSING:", missing); sys.exit(1)

    for i, f in enumerate(FILES, 1):
        text = f.read_text()
        if text.startswith("---"):
            m = re.match(r"^---\n.*?\n---\n", text, re.DOTALL)
            if m: text = text[m.end():]
        print(f"[{i}/{len(FILES)}] {f.name} ({len(text)} chars)", flush=True)
        try:
            await rag.ainsert(text, file_paths=[str(f)])
        except Exception as e:
            print(f"  ERROR: {e}", flush=True)

    print("DONE")

asyncio.run(main())
