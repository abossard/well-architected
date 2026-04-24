import asyncio, json, pathlib, re, sys
from functools import partial

PROXY_URL = "http://127.0.0.1:11435/v1"
API_KEY = "copilot-proxy"
LLM_MODEL = "claude-opus-4.6"
EMBED_MODEL = "text-embedding-3-small"
RAG_DIR = pathlib.Path("/Users/abossard/Desktop/cxe/well-architected/kg-explorer/lightrag_data")
CARDS_PATH = pathlib.Path("/Users/abossard/Desktop/cxe/well-architected/kg-explorer/mental_models/cards.json")


async def main():
    from lightrag import LightRAG, QueryParam
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
        embedding_func=EmbeddingFunc(
            embedding_dim=1536, max_token_size=8192, model_name=EMBED_MODEL,
            func=partial(openai_embed, model=EMBED_MODEL,
                         base_url=PROXY_URL, api_key=API_KEY)),
    )
    await rag.initialize_storages()

    cards = json.loads(CARDS_PATH.read_text())
    new_cards = []

    # Backup first
    CARDS_PATH.with_name("cards.pre-overhaul.json").write_text(json.dumps(cards, indent=2))

    sem = asyncio.Semaphore(6)

    async def process(i, card):
        async with sem:
            name = card["name"]
            try:
                context = await rag.aquery(
                    f"What does the Azure Well-Architected Framework say about {name}? Include specific guidance, Azure services, metrics, patterns, and tradeoffs.",
                    param=QueryParam(mode="local")
                )
            except Exception as e:
                context = ""

            prompt = f"""Rewrite this mental model card for mission-critical Azure architects. Maximize information density.

STRICT RULES:
- mantra: Max 8 words. Imperative. Memorable. No articles (a/the).
- layer: One of: foundational, structural, operational, security, organizational, data
- when_to_apply: Exactly 4 bullets. Each max 10 words. Start with verb or "When".
- without_it: Exactly 4 bullets. Each = specific failure mode with consequence. Max 12 words.
- key_tradeoff: Name BOTH sides. Format: "X costs Y" or "More X means less Y". Max 15 words.
- builds_on: 2-4 prerequisite mental models (from the WAF). Only real model names.
- enables: 2-4 downstream mental models. Only real model names.
- NO filler: Remove "it is important", "you should", "consider", "ensure", "leverage"
- BE SPECIFIC: Name Azure services, metrics (RTO/RPO/SLA), patterns, or concrete failure modes
- connections: keep the original number

CURRENT CARD:
{json.dumps(card, indent=2)}

WAF CONTEXT:
{context[:2000] if context else "No additional context available."}

Return ONLY valid JSON with these exact fields: name, mantra, layer, when_to_apply, without_it, key_tradeoff, builds_on, enables, connections"""

            try:
                result = await openai_complete_if_cache(
                    LLM_MODEL, prompt, base_url=PROXY_URL, api_key=API_KEY
                )
                match = re.search(r'\{.*\}', result, re.DOTALL)
                if match:
                    new_card = json.loads(match.group())
                    new_card["connections"] = card.get("connections", 0)
                    print(f"[{i+1}/54] {name} ✅ {new_card.get('mantra','')}", flush=True)
                    return new_card
                else:
                    print(f"[{i+1}/54] {name} ⚠️ kept original (no JSON)", flush=True)
                    return card
            except Exception as e:
                print(f"[{i+1}/54] {name} ❌ kept original: {e}", flush=True)
                return card

    results = await asyncio.gather(*[process(i, c) for i, c in enumerate(cards)], return_exceptions=True)
    new_cards = []
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            print(f"[{i+1}/54] EXCEPTION kept original: {r}", flush=True)
            new_cards.append(cards[i])
        else:
            new_cards.append(r)

    CARDS_PATH.write_text(json.dumps(new_cards, indent=2))
    print(f"\nSaved {len(new_cards)} overhauled cards")

asyncio.run(main())
