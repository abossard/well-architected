#!/usr/bin/env python3
"""Query the LightRAG knowledge base for mission-critical content.

Usage:
    python3 query_lightrag.py "What patterns ensure zero downtime?"
    python3 query_lightrag.py --mode naive "deployment stamps"
    python3 query_lightrag.py --mode local "health modeling"
    python3 query_lightrag.py --mode global "mission critical design principles"
    python3 query_lightrag.py --mode hybrid "How do I achieve 99.999% availability?"
"""
import asyncio
import os
import sys
import pathlib
from functools import partial

PROXY_URL = "http://127.0.0.1:11435/v1"
API_KEY = "copilot-proxy"
LLM_MODEL = "claude-opus-4.6"
EMBED_MODEL = "text-embedding-3-small"
EMBED_DIM = 1536
RAG_DIR = pathlib.Path(__file__).parent / "lightrag_data"


async def main():
    import argparse
    parser = argparse.ArgumentParser(description="Query mission-critical LightRAG")
    parser.add_argument("query", help="Your question")
    parser.add_argument("--mode", choices=["naive", "local", "global", "hybrid"],
                        default="hybrid", help="Search mode (default: hybrid)")
    args = parser.parse_args()

    from lightrag import LightRAG, QueryParam
    from lightrag.llm.openai import openai_complete_if_cache, openai_embed
    from lightrag.utils import EmbeddingFunc
    from functools import partial

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

    print(f"Mode: {args.mode}")
    print(f"Query: {args.query}")
    print("-" * 60)

    result = await rag.aquery(args.query, param=QueryParam(mode=args.mode))
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
