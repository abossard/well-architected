import asyncio, json, pathlib, re
from functools import partial

PROXY_URL = "http://127.0.0.1:11435/v1"
API_KEY = "copilot-proxy"
LLM_MODEL = "claude-opus-4.6"
EMBED_MODEL = "text-embedding-3-small"
RAG_DIR = pathlib.Path("/Users/abossard/Desktop/cxe/well-architected/kg-explorer/lightrag_data")
REPO_ROOT = pathlib.Path("/Users/abossard/Desktop/cxe/well-architected")
WAF_ROOT = REPO_ROOT / "well-architected"


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
            embedding_dim=1536, max_token_size=8192, model_name=EMBED_MODEL,
            func=partial(openai_embed.func, model=EMBED_MODEL,
                         base_url=PROXY_URL, api_key=API_KEY)),
    )
    await rag.initialize_storages()

    # Load existing doc statuses to skip already-ingested files
    with open(RAG_DIR / "kv_store_doc_status.json") as f:
        doc_status = json.load(f)
    ingested_paths = {v.get("file_path") for v in doc_status.values() if v.get("file_path")}

    with open(RAG_DIR / "kv_store_entity_chunks.json") as f:
        ent_before = len(json.load(f))
    with open(RAG_DIR / "kv_store_relation_chunks.json") as f:
        rel_before = len(json.load(f))
    print(f"BEFORE: {len(ingested_paths)} docs, {ent_before} entities, {rel_before} relations")

    dirs = ["reliability", "security", "performance-efficiency",
            "operational-excellence", "cost-optimization", "design-guides", "architect-role"]
    files = []
    for d in dirs:
        files.extend(sorted((WAF_ROOT / d).glob("*.md")))
    files.extend(sorted(WAF_ROOT.glob("*.md")))

    # Filter out already-ingested
    pending = []
    skipped = 0
    for f in files:
        rel = str(f.relative_to(REPO_ROOT))
        if rel in ingested_paths:
            skipped += 1
            continue
        pending.append(f)

    print(f"Found {len(files)} files; {skipped} already ingested; {len(pending)} pending")

    for i, f in enumerate(pending, 1):
        rel = str(f.relative_to(REPO_ROOT))
        text = f.read_text(encoding="utf-8")
        if text.startswith("---"):
            m = re.match(r"^---\n.*?\n---\n", text, re.DOTALL)
            if m:
                text = text[m.end():]
        if len(text.strip()) < 100:
            print(f"[{i}/{len(pending)}] SKIP {rel} (too short)")
            continue
        print(f"[{i}/{len(pending)}] {rel} ({len(text)} chars)", flush=True)
        try:
            await rag.ainsert(text, file_paths=[rel])
        except Exception as e:
            print(f"  ERROR: {e}")

    with open(RAG_DIR / "kv_store_entity_chunks.json") as f:
        ent_after = len(json.load(f))
    with open(RAG_DIR / "kv_store_relation_chunks.json") as f:
        rel_after = len(json.load(f))
    print(f"\nBatch 1 complete: {ent_after} entities (+{ent_after - ent_before}), "
          f"{rel_after} relations (+{rel_after - rel_before})")


asyncio.run(main())
