#!/usr/bin/env python3
"""Densify mental model cards and verify top cards against LightRAG.

- Loads all cards from mental_models/cards.json
- Computes information density via spaCy (entities + noun chunks + tech terms / tokens)
- For TOP N cards by centrality (connections), queries LightRAG to verify grounding
- For cards with density < THRESHOLD, asks Opus to rewrite with RAG context
- Writes densified cards back and prints before/after comparison
"""
import asyncio
import json
import pathlib
import re
import sys
from functools import partial

import httpx
import spacy

PROXY_URL = "http://127.0.0.1:11435/v1"
API_KEY = "copilot-proxy"
LLM_MODEL = "claude-opus-4.6"
EMBED_MODEL = "text-embedding-3-small"
EMBED_DIM = 1536

ROOT = pathlib.Path(__file__).parent
RAG_DIR = ROOT / "lightrag_data"
CARDS_PATH = ROOT / "mental_models" / "cards.json"
REPORT_PATH = ROOT / "mental_models" / "density_report.json"

DENSITY_FLUFFY = 0.30
DENSITY_GOOD = 0.40
TOP_N_VERIFY = 10

# Azure / WAF technical vocabulary treated as "technical terms" for density.
TECH_TERMS = {
    "azure", "aks", "vm", "vmss", "sla", "slo", "sli", "rpo", "rto", "mttr", "mtbf",
    "iops", "throughput", "latency", "p95", "p99", "tco", "capex", "opex",
    "blob", "queue", "cosmos", "sql", "postgres", "redis", "kafka", "event", "hub",
    "kubernetes", "container", "pod", "node", "cluster", "region", "zone",
    "failover", "replication", "backup", "restore", "snapshot", "checkpoint",
    "autoscale", "scaling", "throttle", "circuit", "breaker", "retry", "idempotent",
    "jwt", "oauth", "rbac", "abac", "tls", "mTLS", "kms", "hsm", "ssl", "cert",
    "vnet", "subnet", "nsg", "firewall", "waf", "ddos", "cdn", "dns",
    "tenant", "workload", "pillar", "tradeoff", "pattern", "anti-pattern",
    "observability", "telemetry", "metric", "log", "trace", "alert", "dashboard",
    "chaos", "canary", "blue-green", "rolling", "stamp", "bulkhead", "sidecar",
    "cache", "queue", "batch", "stream", "etl", "pipeline", "ingest",
}

FILLER_PATTERNS = [
    r"\bit is important to\b", r"\byou should consider\b", r"\bin order to\b",
    r"\bthere (is|are)\b", r"\bvery\b", r"\bsimply\b", r"\bbasically\b",
]

# ---------- Density ----------

_nlp = None

def nlp():
    global _nlp
    if _nlp is None:
        _nlp = spacy.load("en_core_web_sm")
    return _nlp


def density(text: str) -> dict:
    if not text or not text.strip():
        return {"density": 0.0, "tokens": 0, "entities": 0, "chunks": 0, "tech": 0}
    doc = nlp()(text)
    tokens = [t for t in doc if not t.is_space and not t.is_punct]
    n_tokens = len(tokens) or 1
    n_ent = len(doc.ents)
    n_chunks = sum(1 for _ in doc.noun_chunks)
    low = text.lower()
    n_tech = sum(1 for term in TECH_TERMS if re.search(rf"\b{re.escape(term)}\b", low))
    n_filler = sum(len(re.findall(p, low)) for p in FILLER_PATTERNS)
    score = (n_ent + n_chunks + n_tech - n_filler) / n_tokens
    return {
        "density": round(max(0.0, score), 3),
        "tokens": n_tokens,
        "entities": n_ent,
        "chunks": n_chunks,
        "tech": n_tech,
        "filler": n_filler,
    }


def card_text(card: dict) -> str:
    parts = [card.get("mantra", ""), card.get("key_tradeoff", "")]
    parts += card.get("when_to_apply", []) or []
    parts += card.get("without_it", []) or []
    return " ".join(parts)


def card_density(card: dict) -> dict:
    return density(card_text(card))


# ---------- LightRAG ----------

async def make_rag():
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
        working_dir=str(RAG_DIR),
        llm_model_func=llm_func,
        llm_model_name=LLM_MODEL,
        embedding_func=EmbeddingFunc(
            embedding_dim=EMBED_DIM, max_token_size=8192, model_name=EMBED_MODEL,
            func=partial(openai_embed.func, model=EMBED_MODEL,
                         base_url=PROXY_URL, api_key=API_KEY),
        ),
    )
    await rag.initialize_storages()
    return rag


async def rag_query(rag, question: str) -> str:
    from lightrag import QueryParam
    try:
        return await rag.aquery(question, param=QueryParam(mode="local"))
    except Exception as e:
        return f"[RAG error: {e}]"


# ---------- LLM rewrite ----------

REWRITE_PROMPT = """Rewrite this mental model card to maximize information density. Rules:
- Every word must earn its place
- Use imperative voice
- No filler phrases ('it is important to', 'you should consider')
- Lead with the action or consequence
- Include specific Azure services, metrics, or patterns where relevant
- Mantra: max 10 words, memorable
- When_to_apply: each bullet max 12 words
- Without_it: each bullet = specific failure mode, not vague risk
- Key_tradeoff: name both sides explicitly

Current card: {card_json}

Context from WAF docs: {rag_context}

Return ONLY valid JSON with the same structure (keys: mantra, when_to_apply, without_it, key_tradeoff). No prose, no code fences."""


async def llm_chat(client: httpx.AsyncClient, user: str) -> str:
    r = await client.post(
        f"{PROXY_URL}/chat/completions",
        headers={"Authorization": f"Bearer {API_KEY}"},
        json={
            "model": LLM_MODEL,
            "messages": [{"role": "user", "content": user}],
            "temperature": 0.3,
            "max_tokens": 1500,
        },
        timeout=180.0,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def extract_json(text: str):
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        raise ValueError("no JSON object found")
    return json.loads(m.group(0))


async def rewrite_card(client, rag, card: dict) -> dict:
    q = (f"What does the Azure Well-Architected Framework say about {card['name']}? "
         f"Specific guidance, recommendations, tradeoffs, and Azure services.")
    ctx = await rag_query(rag, q)
    ctx = ctx[:4000] if isinstance(ctx, str) else str(ctx)[:4000]
    prompt = REWRITE_PROMPT.format(card_json=json.dumps(card, indent=2), rag_context=ctx)
    raw = await llm_chat(client, prompt)
    new = extract_json(raw)
    updated = dict(card)
    for k in ("mantra", "when_to_apply", "without_it", "key_tradeoff"):
        if k in new and new[k]:
            updated[k] = new[k]
    return updated


# ---------- Verification (task 1) ----------

async def verify_top_cards(rag, cards):
    top = sorted(cards, key=lambda c: c.get("connections", 0), reverse=True)[:TOP_N_VERIFY]
    print(f"\n=== TASK 1: Verifying top {len(top)} cards by centrality ===\n")
    flags = []
    for c in top:
        q = (f"What does the Azure Well-Architected Framework say about {c['name']}? "
             f"What specific guidance, recommendations, and tradeoffs does it mention?")
        ans = await rag_query(rag, q)
        ans_lc = (ans or "").lower()
        name_tokens = [w.lower() for w in re.findall(r"\w+", c["name"]) if len(w) > 3]
        hits = sum(1 for t in name_tokens if t in ans_lc)
        generic = ("i cannot" in ans_lc or "no information" in ans_lc
                   or "not mentioned" in ans_lc or len(ans) < 300)
        grounded = hits > 0 and not generic
        status = "OK" if grounded else "FLAG"
        print(f"[{status}] {c['name']} (conn={c['connections']}) | RAG chars={len(ans)} name-hits={hits}")
        if not grounded:
            flags.append(c["name"])
        # brief snippet
        snippet = re.sub(r"\s+", " ", ans)[:220]
        print(f"    RAG: {snippet}")
    print(f"\nFlagged (possibly not grounded): {flags or 'none'}")
    return flags


# ---------- Main ----------

async def main():
    cards = json.loads(CARDS_PATH.read_text())
    print(f"Loaded {len(cards)} cards from {CARDS_PATH}")

    print("\nComputing density (before)...")
    before = {c["name"]: card_density(c) for c in cards}
    fluffy = [c for c in cards if before[c["name"]]["density"] < DENSITY_FLUFFY]
    good = [c for c in cards if before[c["name"]]["density"] >= DENSITY_GOOD]
    avg_before = sum(b["density"] for b in before.values()) / len(before)
    print(f"  avg density: {avg_before:.3f}")
    print(f"  fluffy (<{DENSITY_FLUFFY}): {len(fluffy)}")
    print(f"  good    (>={DENSITY_GOOD}): {len(good)}")

    rag = await make_rag()

    # Task 1: verify top cards
    flags = await verify_top_cards(rag, cards)

    # Task 2: rewrite fluffy cards
    if not fluffy:
        print("\nNo fluffy cards. Done.")
        REPORT_PATH.write_text(json.dumps({"before": before, "after": before, "flags": flags}, indent=2))
        return

    print(f"\n=== TASK 2: Rewriting {len(fluffy)} fluffy cards ===\n")
    async with httpx.AsyncClient() as client:
        # bounded concurrency
        sem = asyncio.Semaphore(3)

        async def work(c):
            async with sem:
                try:
                    new = await rewrite_card(client, rag, c)
                    print(f"  rewrote: {c['name']}")
                    return c["name"], new
                except Exception as e:
                    print(f"  FAILED {c['name']}: {e}")
                    return c["name"], None

        results = await asyncio.gather(*[work(c) for c in fluffy])

    updates = {n: v for n, v in results if v is not None}
    new_cards = [updates.get(c["name"], c) for c in cards]

    after = {c["name"]: card_density(c) for c in new_cards}
    avg_after = sum(a["density"] for a in after.values()) / len(after)

    CARDS_PATH.write_text(json.dumps(new_cards, indent=2) + "\n")
    REPORT_PATH.write_text(json.dumps({
        "avg_before": avg_before, "avg_after": avg_after,
        "before": before, "after": after, "flags": flags,
        "rewritten": sorted(updates.keys()),
    }, indent=2))

    print("\n=== Before / After ===")
    print(f"  avg density: {avg_before:.3f} -> {avg_after:.3f}  (Δ {avg_after-avg_before:+.3f})")
    print(f"  rewritten: {len(updates)}/{len(fluffy)}")
    print(f"\nPer-card (fluffy only):")
    for c in fluffy:
        n = c["name"]
        b = before[n]["density"]; a = after[n]["density"]
        mark = "✓" if a > b else "–"
        print(f"  {mark} {n:40s}  {b:.3f} -> {a:.3f}")
    print(f"\nSaved: {CARDS_PATH}")
    print(f"Report: {REPORT_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
