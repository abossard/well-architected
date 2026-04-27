# Fact Verification + Documentation Update Pipeline — Implementation Plan

## Data Flow Diagram

```
facts.json (629 facts, 102 perishable)
       │
       ▼
┌──────────────────────┐     web search      ┌─────────────────────┐
│  verify_facts.py     │ ──── via MCP ────▶  │  verifications.json │
│  (LLM judge)         │     + LLM judge     │  (102 results)      │
└──────────────────────┘                     └────────┬────────────┘
                                                      │
facts.json ───┐                                       │
              ▼                                       │
┌──────────────────────┐     kv_store_*      ┌────────┴────────────┐
│  locate_facts.py     │ ── chunk trace ──▶  │  fact_locations.json │
│  (fuzzy match)       │     + heading scan  │  (629 entries)       │
└──────────────────────┘                     └────────┬────────────┘
                                                      │
              ┌───────────────────────────────────────┘
              ▼                    ▼
┌──────────────────────┐   ┌──────────────────────┐
│ generate_update_plan │   │  build_data.py       │
│  (LLM suggestions)  │   │  (graph enrichment)  │
└──────┬───────────────┘   └──────┬───────────────┘
       │                          │
       ▼                          ▼
  update_plan.md            graph.json + details.json
  update_plan.json          (verification badges,
                             file locations, "needs update")
```

## End-to-End Workflow

```bash
# 1. Verify perishable facts against the web (≈15 min for 102 facts)
python3 verify_facts.py --mcp-cmd "npx copilot-api" --concurrency 5

# 2. Trace ALL facts to source markdown locations (pure local, fast)
python3 locate_facts.py --domain mission-critical

# 3. Generate human-readable + machine-readable update plan
python3 generate_update_plan.py

# 4. Rebuild the graph with verification badges + locations
python3 build_data.py --domain mission-critical

# 5. Review and apply
open mental_models/update_plan.md   # human reviews
# OR: automated apply via update_plan.json (future)
```

---

## Script 1: `verify_facts.py`

### Purpose
Web-search each perishable fact, use an LLM judge to compare the fact against
current search results, produce a structured verdict.

### CLI Interface

```
python3 verify_facts.py [OPTIONS]

  --facts PATH          Path to facts.json          (default: mental_models/facts.json)
  --output PATH         Path to verifications.json  (default: mental_models/verifications.json)
  --concurrency N       Parallel verification tasks (default: 3)
  --only-perishable     Skip timeless facts          (default: True)
  --force               Re-verify even if result exists in output
  --max N               Stop after N facts (for testing)
  --dry-run             Print search queries, don't execute
```

LLM/proxy config via environment (loaded from `.env` if present):
- `LLM_BINDING_HOST` — base URL (default: `http://127.0.0.1:11435/v1`)
- `LLM_MODEL` — model name (default: `claude-opus-4.6`)
- `LLM_API_KEY` — API key (default: `copilot-proxy`)

### Core Functions

```python
# ─── config ─────────────────────────────────────────────────────────
HERE = pathlib.Path(__file__).resolve().parent
DEFAULT_FACTS   = HERE / "mental_models" / "facts.json"
DEFAULT_OUTPUT  = HERE / "mental_models" / "verifications.json"

def load_env():
    """Load .env from HERE if present, populate os.environ defaults."""

def get_llm_config() -> dict:
    """Return {base_url, model, api_key} from env vars."""

# ─── search ─────────────────────────────────────────────────────────
async def web_search(query: str, num_results: int = 5) -> list[dict]:
    """Search via httpx to a search API.

    Returns: [{"title": ..., "snippet": ..., "url": ...}]

    Strategy: use the verification_hint + entity + fact keywords.
    Search query template:
      f'{entity} {core_claim} site:learn.microsoft.com OR site:azure.microsoft.com'
    Fallback (if <2 results):
      f'{entity} {core_claim} Azure'
    """

def build_search_query(fact: dict) -> str:
    """Build a targeted search query from a fact entry.

    Examples:
      entity="AKS", fact="AKS has a scale limit of 1,000 nodes per cluster"
      → "AKS scale limit nodes per cluster site:learn.microsoft.com"

      entity="Azure Monitor", hint="Check Azure Monitor default behavior docs"
      → "Azure Monitor enabled default subscriptions site:learn.microsoft.com"
    """

# ─── LLM judge ──────────────────────────────────────────────────────
JUDGE_SYSTEM = """You are a fact-checker for Azure documentation.
Given a FACT from documentation and SEARCH RESULTS from the web,
determine if the fact is still accurate.

Respond with EXACTLY this JSON (no markdown fences):
{
  "verdict": "current" | "outdated" | "unverifiable",
  "current_info": "what the current truth is, if different",
  "confidence": "high" | "medium" | "low",
  "source_url": "best source URL from search results",
  "reasoning": "1-2 sentence explanation"
}
"""

JUDGE_USER = """ENTITY: {entity}
FACT: {fact}
VERIFICATION HINT: {hint}

SEARCH RESULTS:
{search_results}
"""

async def judge_fact(fact: dict, search_results: list[dict],
                     llm_config: dict) -> dict:
    """Call LLM to compare fact against search results.

    Uses openai-compatible API at llm_config["base_url"].
    Returns parsed JSON verdict.
    Retries up to 2x on parse failure.
    """

# ─── orchestration ──────────────────────────────────────────────────
async def verify_one(fact: dict, llm_config: dict,
                     semaphore: asyncio.Semaphore) -> dict:
    """Full pipeline for one fact: search → judge → result dict."""

async def verify_all(facts: list[dict], args) -> list[dict]:
    """Load existing results (resume), verify remaining, write output.

    Resume logic: load verifications.json, skip facts whose
    (entity, fact) tuple already has a result unless --force.
    """
```

### Output: `mental_models/verifications.json`

```json
[
  {
    "entity": "AKS",
    "fact": "AKS has a scale limit of 1,000 nodes per cluster",
    "fact_type": "perishable",
    "verdict": "outdated",
    "current_info": "AKS supports up to 5,000 nodes per cluster as of 2024",
    "confidence": "high",
    "source_url": "https://learn.microsoft.com/azure/aks/quotas-skus-regions",
    "reasoning": "Microsoft docs confirm the limit was raised to 5,000 nodes.",
    "verified_at": "2025-07-24T14:32:00Z",
    "search_query": "AKS scale limit nodes per cluster site:learn.microsoft.com"
  },
  {
    "entity": "Azure Monitor",
    "fact": "Azure Monitor is enabled by default for all Azure subscriptions",
    "verdict": "current",
    "current_info": null,
    "confidence": "high",
    "source_url": "https://learn.microsoft.com/azure/azure-monitor/overview",
    "reasoning": "Azure Monitor overview confirms it is automatically enabled.",
    "verified_at": "2025-07-24T14:33:00Z",
    "search_query": "Azure Monitor enabled default all subscriptions site:learn.microsoft.com"
  }
]
```

### Error Handling
- **Search failure**: log warning, mark verdict `"unverifiable"`, `confidence: "low"`
- **LLM parse failure**: retry 2x with stricter prompt; if still fails, `"unverifiable"`
- **Network timeout**: exponential backoff (2s, 4s, 8s), then skip
- **Resume**: on any crash, re-run picks up where it left off via existing output

---

## Script 2: `locate_facts.py`

### Purpose
Trace each fact back to its exact location in the source markdown using the
LightRAG chunk stores. No LLM needed — pure local computation.

### CLI Interface

```
python3 locate_facts.py [OPTIONS]

  --facts PATH          Path to facts.json             (default: mental_models/facts.json)
  --output PATH         Path to fact_locations.json     (default: mental_models/fact_locations.json)
  --domain DOMAIN       RAG domain                      (default: mission-critical)
  --waf-root PATH       Path to well-architected/ dir   (default: ../well-architected)
```

### Algorithm

```
For each fact in facts.json:
  1. Look up entity in kv_store_entity_chunks.json → get chunk_ids[]
  2. For each chunk_id, look up kv_store_text_chunks.json → get file_path + content
  3. Fuzzy-match the fact text against chunk content (see matching strategy below)
  4. Read the actual markdown file from disk
  5. Find the best heading (##/###) preceding the match location
  6. Record file, heading, approximate line number, surrounding context
```

### Core Functions

```python
# ─── config ─────────────────────────────────────────────────────────
HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent
DEFAULT_WAF = REPO / "well-architected"

def rag_paths(domain: str) -> tuple[pathlib.Path, pathlib.Path]:
    """Return (entity_chunks_path, text_chunks_path)."""
    rag = HERE / f"lightrag_data_{domain}"
    return rag / "kv_store_entity_chunks.json", rag / "kv_store_text_chunks.json"

# ─── fuzzy matching ─────────────────────────────────────────────────
def normalize_text(s: str) -> str:
    """Lowercase, collapse whitespace, strip punctuation for matching."""

def fuzzy_score(fact_text: str, chunk_content: str) -> float:
    """Score how well a fact matches within a chunk.

    Strategy (ordered by priority):
    1. Exact substring match (normalized) → score 1.0
    2. Token overlap (Jaccard on 3-grams) → score 0.0-0.9
    3. Key-term presence: extract numbers, proper nouns, service names
       from fact; count how many appear in chunk → bonus

    Returns float 0.0-1.0. Threshold for "match": >= 0.4
    """

def find_best_chunk(fact: dict,
                    entity_chunks: dict,
                    text_chunks: dict) -> dict | None:
    """Find the chunk that best matches this fact.

    Returns: {"chunk_id": ..., "file_path": ..., "content": ..., "score": ...}
    or None if no match above threshold.

    Lookup order:
    1. entity_chunks[fact["entity"]] → chunk_ids → text_chunks[cid]
    2. If entity not found, try case-insensitive key match
    3. If still nothing, scan ALL text_chunks for file_path containing
       the entity name (brute-force fallback, slow but thorough)
    """

# ─── heading extraction ────────────────────────────────────────────
HEADING_RE = re.compile(r'^(#{1,4})\s+(.+)$', re.MULTILINE)

def find_heading_and_line(fact_text: str,
                          file_path: pathlib.Path) -> dict:
    """Read the actual markdown file, locate the fact, return position.

    Returns: {
        "heading": "## Design recommendations",
        "heading_level": 2,
        "line_approx": 145,
        "context": "...the surrounding 3 lines..."
    }

    Algorithm:
    1. Read the file, split into lines
    2. Normalize and search for fact keywords (longest unique phrase)
    3. If found: line_approx = line number, heading = nearest ## above
    4. If not found in file but found in chunk:
       - Use chunk content to find heading
       - line_approx = None (chunk matched but file line unknown)
    5. Last resort: return first ## heading in the file, line_approx = None
    """

# ─── main ──────────────────────────────────────────────────────────
def locate_all(facts: list[dict], domain: str, waf_root: pathlib.Path) -> list[dict]:
    """Locate every fact. Returns list of location entries."""
    ec = load_json(rag_paths(domain)[0])
    tc = load_json(rag_paths(domain)[1])

    results = []
    for fact in facts:
        chunk_match = find_best_chunk(fact, ec, tc)
        if not chunk_match:
            results.append({
                "entity": fact["entity"],
                "fact": fact["fact"],
                "fact_type": fact.get("type", "timeless"),
                "file": None,
                "heading": None,
                "line_approx": None,
                "context": None,
                "match_score": 0.0,
                "match_method": "not_found",
            })
            continue

        file_rel = chunk_match["file_path"]  # e.g. "well-architected/mission-critical/foo.md"
        file_abs = REPO / file_rel
        pos = find_heading_and_line(fact["fact"], file_abs) if file_abs.exists() else {}

        results.append({
            "entity": fact["entity"],
            "fact": fact["fact"],
            "fact_type": fact.get("type", "timeless"),
            "file": file_rel,
            "heading": pos.get("heading"),
            "heading_level": pos.get("heading_level"),
            "line_approx": pos.get("line_approx"),
            "context": pos.get("context"),
            "match_score": round(chunk_match["score"], 3),
            "match_method": "chunk_trace",  # or "brute_force"
        })
    return results
```

### Output: `mental_models/fact_locations.json`

```json
[
  {
    "entity": "AKS",
    "fact": "AKS has a scale limit of 1,000 nodes per cluster",
    "fact_type": "perishable",
    "file": "well-architected/mission-critical/mission-critical-application-platform.md",
    "heading": "## Kubernetes (AKS)",
    "heading_level": 2,
    "line_approx": 145,
    "context": "AKS currently supports a maximum of 1,000 nodes per cluster. If you need more nodes...",
    "match_score": 0.87,
    "match_method": "chunk_trace"
  },
  {
    "entity": "Azure Cosmos DB",
    "fact": "Azure Cosmos DB is a globally distributed, highly available NoSQL database service",
    "fact_type": "timeless",
    "file": "well-architected/mission-critical/mission-critical-data-platform.md",
    "heading": "## Globally distributed, multi-write datastore",
    "heading_level": 2,
    "line_approx": 32,
    "context": "Azure Cosmos DB is used as the primary datastore...",
    "match_score": 0.72,
    "match_method": "chunk_trace"
  }
]
```

### Error Handling
- **Entity not in entity_chunks**: log warning, set `match_method: "not_found"`
- **File doesn't exist on disk**: use chunk content only, set `line_approx: null`
- **No heading found**: set `heading: null`, include file path only
- **Multiple equally good matches**: take the one from the highest-priority file (mission-critical > other)

---

## Script 3: `generate_update_plan.py`

### Purpose
Combine verification results (what's outdated) with fact locations (where in the docs)
to produce a human-readable markdown report and a machine-readable JSON action list.

### CLI Interface

```
python3 generate_update_plan.py [OPTIONS]

  --verifications PATH  Path to verifications.json      (default: mental_models/verifications.json)
  --locations PATH      Path to fact_locations.json      (default: mental_models/fact_locations.json)
  --output-md PATH      Path to update_plan.md           (default: mental_models/update_plan.md)
  --output-json PATH    Path to update_plan.json         (default: mental_models/update_plan.json)
  --waf-root PATH       Path to well-architected/ dir    (default: ../well-architected)
  --suggest             Use LLM to generate replacement text (default: False)
```

### Core Functions

```python
def merge_verifications_and_locations(
    verifications: list[dict],
    locations: list[dict]
) -> list[dict]:
    """Join on (entity, fact). Returns list of merged dicts.

    Only includes facts where verdict == "outdated".
    Adds all location fields to each verification entry.
    """

def read_context_lines(file_path: pathlib.Path,
                       line_approx: int | None,
                       radius: int = 5) -> str:
    """Read ±radius lines around line_approx from the actual file.

    Returns the text block. If line_approx is None, returns the
    paragraph under the heading instead.
    """

SUGGEST_SYSTEM = """You are a technical writer for Azure documentation.
Given the CURRENT TEXT from a document and the UPDATED FACT,
write a replacement paragraph that:
1. Preserves the original tone and style (Microsoft style guide)
2. Incorporates the corrected information
3. Keeps the same approximate length
4. Uses contractions, sentence-style capitalization
5. Does NOT add marketing language

Return ONLY the replacement text, no explanation.
"""

async def suggest_replacement(current_text: str,
                              outdated_fact: str,
                              current_info: str,
                              llm_config: dict) -> str:
    """LLM-generate a suggested replacement paragraph."""

def generate_markdown_plan(updates: list[dict]) -> str:
    """Render update_plan.md.

    Format per update:
    ---
    ### {file} (line ~{line_approx})

    **Under:** `{heading}`
    **Entity:** {entity}

    **Current text:**
    > {context from the actual file}

    **Outdated fact:**
    > {fact}

    **Correct information:**
    > {current_info}

    **Suggested replacement:**
    > {suggested text OR "Run with --suggest to generate"}

    **Source:** {source_url}
    **Confidence:** {confidence}
    **Verified:** {verified_at}
    ---
    """

def generate_json_plan(updates: list[dict]) -> list[dict]:
    """Machine-readable plan for automation.

    Each entry:
    {
      "file": "well-architected/mission-critical/...",
      "heading": "## Kubernetes (AKS)",
      "line_approx": 145,
      "entity": "AKS",
      "outdated_fact": "AKS has a scale limit of 1,000 nodes...",
      "current_info": "AKS supports up to 5,000 nodes...",
      "source_url": "https://...",
      "confidence": "high",
      "verified_at": "2025-07-24T14:32:00Z",
      "current_text": "...the actual lines from the file...",
      "suggested_text": "...replacement..." or null,
      "status": "pending"
    }
    """
```

### Output: `mental_models/update_plan.md`

```markdown
# Documentation Update Plan

Generated: 2025-07-24T15:00:00Z
Outdated facts found: 7 of 102 perishable facts verified

## Summary

| File | Updates | Confidence |
|------|---------|------------|
| mission-critical-application-platform.md | 3 | 2 high, 1 medium |
| mission-critical-data-platform.md | 2 | 2 high |
| mission-critical-health-modeling.md | 2 | 1 high, 1 low |

---

## Updates

### well-architected/mission-critical/mission-critical-application-platform.md

#### Under "## Kubernetes (AKS)" (line ~145)

**Entity:** AKS

**Current text:**
> AKS currently supports a maximum of 1,000 nodes per cluster. If you need
> more nodes, you can create additional clusters.

**Outdated fact:**
> AKS has a scale limit of 1,000 nodes per cluster

**Correct information:**
> AKS supports up to 5,000 nodes per cluster

**Suggested replacement:**
> AKS supports a maximum of 5,000 nodes per cluster. If you need more nodes,
> you can create additional clusters.

**Source:** https://learn.microsoft.com/azure/aks/quotas-skus-regions
**Confidence:** high
**Verified:** 2025-07-24

---
```

### Output: `mental_models/update_plan.json`

```json
{
  "generated_at": "2025-07-24T15:00:00Z",
  "total_verified": 102,
  "total_outdated": 7,
  "total_current": 89,
  "total_unverifiable": 6,
  "updates": [
    {
      "file": "well-architected/mission-critical/mission-critical-application-platform.md",
      "heading": "## Kubernetes (AKS)",
      "line_approx": 145,
      "entity": "AKS",
      "outdated_fact": "AKS has a scale limit of 1,000 nodes per cluster",
      "current_info": "AKS supports up to 5,000 nodes per cluster",
      "source_url": "https://learn.microsoft.com/azure/aks/quotas-skus-regions",
      "confidence": "high",
      "verified_at": "2025-07-24T14:32:00Z",
      "current_text": "AKS currently supports a maximum of 1,000 nodes...",
      "suggested_text": "AKS supports a maximum of 5,000 nodes...",
      "status": "pending"
    }
  ]
}
```

### Error Handling
- **Verification exists but no location**: include in plan with `"line_approx": null`, note "manual location needed"
- **Location exists but file deleted**: skip, log warning
- **LLM suggestion fails**: set `suggested_text: null`, note "manual edit needed"

---

## Script 4: `build_data.py` Changes

### What Changes

Add two new optional loaders that merge verification + location data into the
existing graph/details output. The key principle: **if the files don't exist,
everything works exactly as before.**

### New Constants (after line 28)

```python
VERIFICATIONS = HERE / "mental_models" / "verifications.json"
FACT_LOCATIONS = HERE / "mental_models" / "fact_locations.json"
```

### New Loader Function

```python
def load_verifications() -> dict[tuple[str, str], dict]:
    """Load verifications.json into a lookup by (entity, fact).

    Returns {} if file doesn't exist.
    """
    if not VERIFICATIONS.exists():
        return {}
    data = load_json(VERIFICATIONS)
    return {(v["entity"], v["fact"]): v for v in data}


def load_fact_locations() -> dict[tuple[str, str], dict]:
    """Load fact_locations.json into a lookup by (entity, fact).

    Returns {} if file doesn't exist.
    """
    if not FACT_LOCATIONS.exists():
        return {}
    data = load_json(FACT_LOCATIONS)
    return {(loc["entity"], loc["fact"]): loc for loc in data}
```

### Changes in `build()` Function

#### After loading facts (line 536):

```python
verifications = load_verifications()
fact_locations = load_fact_locations()
if verifications:
    print(f"  loaded {len(verifications)} verifications")
if fact_locations:
    print(f"  loaded {len(fact_locations)} fact locations")
```

#### In `build_fact_nodes()` — extend `fact_detail` (line 504-511):

Add `verifications` and `fact_locations` parameters. For each fact:

```python
fact_key = (entity, f.get("fact", ""))
v = verifications.get(fact_key)
loc = fact_locations.get(fact_key)

fact_node["fact_detail"] = {
    "fact": f.get("fact", ""),
    "fact_type": fact_type,
    "shelf_life_months": f.get("shelf_life_months"),
    "confidence": f.get("confidence"),
    "verification_hint": f.get("verification_hint"),
    "source_entity": entity,
    # NEW: verification fields
    "verified": v.get("verdict") if v else None,            # "current"|"outdated"|"unverifiable"|null
    "verified_at": v.get("verified_at") if v else None,     # ISO timestamp
    "current_info": v.get("current_info") if v else None,   # corrected fact text
    "source_url": v.get("source_url") if v else None,       # verification source
    "verify_confidence": v.get("confidence") if v else None, # "high"|"medium"|"low"
    # NEW: location fields
    "source_file": loc.get("file") if loc else None,
    "source_heading": loc.get("heading") if loc else None,
    "source_line": loc.get("line_approx") if loc else None,
}
```

#### In the details serialization (line 764-776):

Extend the fact detail output:

```python
if is_fact:
    fd = n["fact_detail"]
    det = {
        "type":              n["type"],
        "summary":           fd["fact"],
        "fact_type":         fd["fact_type"],
        "confidence":        fd.get("confidence"),
        "source_entity":     fd["source_entity"],
        # verification
        "verified":          fd.get("verified"),         # NEW
        "verified_at":       fd.get("verified_at"),      # NEW
        "current_info":      fd.get("current_info"),     # NEW
        "source_url":        fd.get("source_url"),       # NEW
        "verify_confidence": fd.get("verify_confidence"),# NEW
        # location
        "source_file":       fd.get("source_file"),      # NEW
        "source_heading":    fd.get("source_heading"),    # NEW
        "source_line":       fd.get("source_line"),       # NEW
    }
    # ... existing shelf_life + verification_hint logic
```

#### Also merge into entity-level `facts` array (line 569-571):

When attaching facts to parent entity nodes, also include verification status:

```python
if nid in facts_by_entity:
    enriched = []
    for f in facts_by_entity[nid]:
        fk = (nid, f.get("fact", ""))
        v = verifications.get(fk)
        loc = fact_locations.get(fk)
        entry = dict(f)
        if v:
            entry["verified"] = v.get("verdict")
            entry["verified_at"] = v.get("verified_at")
            entry["current_info"] = v.get("current_info")
        if loc:
            entry["source_file"] = loc.get("file")
            entry["source_heading"] = loc.get("heading")
        enriched.append(entry)
    node["facts"] = enriched
```

#### New stats (line 680+):

```python
stats["facts_verified"] = sum(1 for v in verifications.values() if v.get("verdict"))
stats["facts_outdated"] = sum(1 for v in verifications.values() if v.get("verdict") == "outdated")
stats["facts_located"] = sum(1 for loc in fact_locations.values() if loc.get("file"))
```

---

## Script 5: Explorer UI Changes

### Slim Graph Node (`graph.json`)

Add to fact nodes in the slim representation:

```json
{"id": "fact:aks:0", "type": "FACT_PERISHABLE", "deg": 0, "d": 3,
 "mc": true, "fact": true, "v": "outdated"}
```

The `"v"` field is the verification verdict: `"current"`, `"outdated"`, `"unverifiable"`, or absent.

### Details Panel (`details.json`)

Fact detail entries gain:

```json
{
  "type": "FACT_PERISHABLE",
  "summary": "AKS has a scale limit of 1,000 nodes per cluster",
  "fact_type": "perishable",
  "verified": "outdated",
  "verified_at": "2025-07-24",
  "current_info": "AKS supports up to 5,000 nodes per cluster",
  "source_url": "https://learn.microsoft.com/azure/aks/quotas-skus-regions",
  "verify_confidence": "high",
  "source_file": "well-architected/mission-critical/mission-critical-application-platform.md",
  "source_heading": "## Kubernetes (AKS)",
  "source_line": 145
}
```

### UI Rendering (in `index.html` or React components)

#### Verification Badges (node circles)

```
Color mapping for fact nodes:
  verified == "current"      → green ring (#22c55e)
  verified == "outdated"     → orange ring (#f97316)
  verified == "unverifiable" → gray ring (#9ca3af)
  verified == null           → no ring (not yet verified)
```

#### Detail Panel Additions

When a fact node is selected, show:

```html
<!-- Verification status -->
<div class="badge badge-{verdict}">{verdict}</div>
<span class="text-sm text-gray-500">Verified {verified_at}</span>

<!-- If outdated -->
<div class="alert alert-warning">
  <strong>Needs update:</strong> {current_info}
  <a href="{source_url}">Source ↗</a>
</div>

<!-- Source location link -->
<a href="https://learn.microsoft.com/azure/well-architected/{source_file_slug}#{heading_slug}">
  📄 {source_file} → {source_heading} (line ~{source_line})
</a>
```

#### "Needs Update" Filter / Sort

Add to existing filter controls:

```
[x] Show only facts needing update    (filters to verified=="outdated")
Sort by: [ ] Entity  [x] Needs Update  [ ] Confidence
```

In graph stats panel:

```
Facts: 629 total, 102 perishable
Verified: 96 ✓  |  Outdated: 7 ⚠  |  Unverifiable: 5 ?
```

---

## Configuration — No Hardcoded Paths

All scripts use the same pattern:

```python
HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent

# Defaults (relative to script location)
DEFAULT_FACTS       = HERE / "mental_models" / "facts.json"
DEFAULT_DOMAIN      = "mission-critical"
DEFAULT_WAF_ROOT    = REPO / "well-architected"

# All overridable via CLI args
# LLM config via .env or env vars:
#   LLM_BINDING_HOST, LLM_MODEL, LLM_API_KEY
```

`.env` loading (shared pattern):

```python
def load_dotenv():
    env_path = HERE / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip())
```

---

## File-by-File Summary

| File | Type | Size Est. | Dependencies |
|------|------|-----------|--------------|
| `verify_facts.py` | New script | ~250 LOC | httpx, openai (async) |
| `locate_facts.py` | New script | ~200 LOC | json, re, pathlib (stdlib only) |
| `generate_update_plan.py` | New script | ~200 LOC | json, optional openai |
| `build_data.py` | Modified | +~60 LOC | existing deps |
| `mental_models/verifications.json` | Generated output | ~50 KB | |
| `mental_models/fact_locations.json` | Generated output | ~80 KB | |
| `mental_models/update_plan.md` | Generated output | ~20 KB | |
| `mental_models/update_plan.json` | Generated output | ~30 KB | |

---

## Error Handling Summary

| Stage | Error | Recovery |
|-------|-------|----------|
| `verify_facts.py` | Search API down | Mark `"unverifiable"`, continue |
| `verify_facts.py` | LLM timeout | Retry 2x, then `"unverifiable"` |
| `verify_facts.py` | Crash mid-run | Resume from existing output file |
| `verify_facts.py` | Invalid LLM JSON | Retry with stricter prompt, then skip |
| `locate_facts.py` | Entity not in chunk store | `match_method: "not_found"`, null fields |
| `locate_facts.py` | Source .md file missing | Use chunk content only, `line_approx: null` |
| `locate_facts.py` | No heading found | `heading: null`, file path only |
| `generate_update_plan.py` | No verifications.json | Error: "Run verify_facts.py first" |
| `generate_update_plan.py` | No locations.json | Still works, locations shown as "unknown" |
| `generate_update_plan.py` | LLM suggestion fails | `suggested_text: null` |
| `build_data.py` | verifications.json missing | Silently skip (backward compatible) |
| `build_data.py` | fact_locations.json missing | Silently skip (backward compatible) |

---

## Testing Approach

```bash
# Unit test: verify_facts search query builder
python3 -c "from verify_facts import build_search_query; ..."

# Unit test: locate_facts fuzzy matching
python3 -c "from locate_facts import fuzzy_score; ..."

# Integration: run locate on a single fact
python3 locate_facts.py --max 1

# Integration: run verify on a single fact (needs proxy)
python3 verify_facts.py --max 1

# Full pipeline: dry-run
python3 verify_facts.py --dry-run
python3 locate_facts.py
python3 generate_update_plan.py
python3 build_data.py

# Validate output schemas
python3 -c "
import json
v = json.load(open('mental_models/verifications.json'))
assert all('verdict' in x for x in v)
l = json.load(open('mental_models/fact_locations.json'))
assert all('entity' in x for x in l)
"
```
