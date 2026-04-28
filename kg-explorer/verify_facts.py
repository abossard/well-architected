#!/usr/bin/env python3
"""Verify perishable facts against the web using MCP web-search + LLM judge.

Workflow per fact:
  1. Build a search query from the entity + fact text
  2. Phase 1: get-web-search-summaries via MCP to find candidate URLs
  3. Phase 2: get-single-web-page-content on best MS Learn URL via MCP
  4. Feed page excerpt + claim to LLM judge (OpenAI-compatible API)
  5. Write verdict to verifications.jsonl (one line per fact, resume-safe)
  6. At end, compact JSONL → verifications.json (array format)

Usage:
    python3 verify_facts.py                     # verify all perishable
    python3 verify_facts.py --entity AKS        # single entity
    python3 verify_facts.py --dry-run           # list facts, don't verify
    python3 verify_facts.py --force             # re-verify everything
    python3 verify_facts.py --delay 2.0         # delay between queries
    python3 verify_facts.py --mcp-cmd "node /path/to/index.js"
"""
from __future__ import annotations

import argparse
import asyncio
import datetime
import fcntl
import hashlib
import json
import os
import pathlib
import re
import shlex
import struct
import subprocess
import sys
import time
import urllib.error
import urllib.request
from typing import Any

# ─── paths ──────────────────────────────────────────────────────────
HERE = pathlib.Path(__file__).resolve().parent
DEFAULT_FACTS = HERE / "mental_models" / "facts.json"
DEFAULT_OUTPUT = HERE / "mental_models" / "verifications.json"
DEFAULT_JOURNAL = HERE / "mental_models" / "verifications.jsonl"

# ─── .env loader (no dependencies) ─────────────────────────────────
_ENV_LINE_RE = re.compile(
    r"""^\s*(?:export\s+)?([A-Za-z_]\w*)\s*=\s*(?:"([^"]*)"|'([^']*)'|(\S+))\s*$"""
)


def load_dotenv(path: pathlib.Path | None = None) -> None:
    """Parse a .env file and set os.environ defaults (no overwrite)."""
    p = path or HERE / ".env"
    if not p.is_file():
        return
    for line in p.read_text().splitlines():
        m = _ENV_LINE_RE.match(line)
        if m:
            key = m.group(1)
            val = m.group(2) if m.group(2) is not None else (m.group(3) if m.group(3) is not None else m.group(4))
            os.environ.setdefault(key, val)


# ─── config helpers ─────────────────────────────────────────────────
def get_proxy_url(cli_val: str | None) -> str:
    if cli_val:
        return cli_val
    return os.environ.get("LLM_BINDING_HOST", "http://127.0.0.1:11435/v1")


def get_mcp_cmd(cli_val: str | None) -> list[str]:
    raw = cli_val or os.environ.get("WEB_SEARCH_MCP_CMD", "")
    if not raw:
        print("ERROR: No MCP command specified.", file=sys.stderr)
        print("  Use --mcp-cmd or set WEB_SEARCH_MCP_CMD in .env", file=sys.stderr)
        sys.exit(1)
    return shlex.split(raw)


def get_llm_model() -> str:
    return os.environ.get("LLM_MODEL", "claude-opus-4.6")


def get_api_key() -> str:
    return os.environ.get("OPENAI_API_KEY", os.environ.get("LLM_API_KEY", "copilot-proxy"))


# ─── stable fact_id ────────────────────────────────────────────────
def fact_id(entity: str, fact: str) -> str:
    return hashlib.sha256((entity + "\0" + fact).encode()).hexdigest()[:16]


# ═══════════════════════════════════════════════════════════════════
#  MCP Stdio Client — persistent subprocess, JSON-RPC 2.0
# ═══════════════════════════════════════════════════════════════════

class McpStdioClient:
    """Persistent MCP server subprocess with JSON-RPC 2.0 protocol."""

    def __init__(self, cmd: list[str], call_timeout: float = 60.0):
        self._cmd = cmd
        self._call_timeout = call_timeout
        self._proc: subprocess.Popen | None = None
        self._next_id = 1
        self._lock = asyncio.Lock()
        self._stderr_task: asyncio.Task | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    # ── lifecycle ────────────────────────────────────────────────────
    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._spawn()
        await self._initialize()

    def _spawn(self) -> None:
        self._proc = subprocess.Popen(
            self._cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
        # Drain stderr in background to avoid deadlock
        self._stderr_task = asyncio.ensure_future(self._drain_stderr())

    async def _drain_stderr(self) -> None:
        """Read stderr in a thread to prevent pipe buffer deadlock."""
        loop = asyncio.get_running_loop()
        while self._proc and self._proc.stderr:
            try:
                line = await loop.run_in_executor(None, self._proc.stderr.readline)
                if not line:
                    break
                text = line.decode(errors="replace").rstrip()
                if text:
                    print(f"  [mcp-stderr] {text}", file=sys.stderr, flush=True)
            except Exception:
                break

    async def _initialize(self) -> None:
        resp = await self._rpc("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "verify_facts", "version": "1.0.0"},
        })
        if "error" in resp:
            raise RuntimeError(f"MCP initialize failed: {resp['error']}")
        # Send initialized notification (no id, no response expected)
        await self._send_notification("notifications/initialized", {})

    async def stop(self) -> None:
        await self._stop_process()

    async def _stop_process(self) -> None:
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.stdin.close()  # type: ignore[union-attr]
            except Exception:
                pass
            try:
                self._proc.terminate()
                self._proc.wait(timeout=5)
            except Exception:
                self._proc.kill()
        self._proc = None
        if self._stderr_task and not self._stderr_task.done():
            self._stderr_task.cancel()

    async def _ensure_alive(self) -> None:
        if self._proc is None or self._proc.poll() is not None:
            print("  [mcp] Process died, restarting...", file=sys.stderr, flush=True)
            self._spawn()
            await self._initialize()

    # ── JSON-RPC transport ──────────────────────────────────────────
    async def _send_notification(self, method: str, params: dict) -> None:
        msg = {"jsonrpc": "2.0", "method": method, "params": params}
        raw = json.dumps(msg) + "\n"
        async with self._lock:
            assert self._proc and self._proc.stdin
            await self._loop.run_in_executor(None, self._proc.stdin.write, raw.encode())  # type: ignore[union-attr]
            await self._loop.run_in_executor(None, self._proc.stdin.flush)  # type: ignore[union-attr]

    async def _rpc(self, method: str, params: dict) -> dict:
        async with self._lock:
            await self._ensure_alive()
            req_id = self._next_id
            self._next_id += 1
            msg = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}
            raw = json.dumps(msg) + "\n"
            if not (self._proc and self._proc.stdin and self._proc.stdout):
                raise RuntimeError("MCP process not available")
            await self._loop.run_in_executor(None, self._proc.stdin.write, raw.encode())  # type: ignore[union-attr]
            await self._loop.run_in_executor(None, self._proc.stdin.flush)  # type: ignore[union-attr]
            # Read lines until we get a response with matching id
            try:
                while True:
                    line = await asyncio.wait_for(
                        self._loop.run_in_executor(None, self._proc.stdout.readline),  # type: ignore[union-attr]
                        timeout=self._call_timeout,
                    )
                    if not line:
                        raise RuntimeError("MCP process closed stdout")
                    line_s = line.decode(errors="replace").strip()
                    if not line_s:
                        continue
                    try:
                        resp = json.loads(line_s)
                    except json.JSONDecodeError:
                        continue
                    if resp.get("id") == req_id:
                        return resp
                    # else: notification or mismatched id, keep reading
            except asyncio.TimeoutError:
                # Process is poisoned after timeout — restart it
                print("    ⚠ MCP timeout — restarting process", flush=True)
                await self._stop_process()
                raise RuntimeError(f"MCP call timed out after {self._call_timeout}s")

    # ── high-level tool call ────────────────────────────────────────
    async def call_tool(self, name: str, arguments: dict) -> Any:
        # _ensure_alive is called inside _rpc under the lock
        resp = await self._rpc("tools/call", {"name": name, "arguments": arguments})
        if "error" in resp:
            raise RuntimeError(f"MCP tool error: {resp['error']}")
        result = resp.get("result", {})
        # MCP returns content as list of {type, text} objects
        content = result.get("content", [])
        texts = [c.get("text", "") for c in content if c.get("type") == "text"]
        return "\n".join(texts) if texts else json.dumps(result)


# ═══════════════════════════════════════════════════════════════════
#  Web search helpers
# ═══════════════════════════════════════════════════════════════════

def build_search_query(entry: dict) -> str:
    """Build a targeted search query from entity + fact text."""
    entity = entry["entity"]
    fact_text = entry["fact"]
    hint = entry.get("verification_hint", "")
    # Use verification_hint if present (it's a pre-built search suggestion)
    if hint and len(hint) > 10:
        return f"Azure {entity} {hint}"
    # Remove the entity name from fact to avoid redundancy, keep core claim
    core = fact_text.replace(entity, "").strip()
    # Trim to key terms (first ~60 chars)
    if len(core) > 60:
        core = " ".join(core[:60].split()[:-1])
    return f"Azure {entity} {core}"


def pick_best_url(summaries_text: str) -> str | None:
    """Extract the best Microsoft Learn URL from search summaries."""
    urls = re.findall(r'https?://learn\.microsoft\.com/[^\s"\'<>]+', summaries_text)
    if urls:
        return urls[0]
    # Fallback: any microsoft.com URL
    urls = re.findall(r'https?://[^\s"\'<>]*microsoft\.com[^\s"\'<>]*', summaries_text)
    return urls[0] if urls else None


async def search_and_fetch(
    mcp: McpStdioClient, query: str
) -> tuple[str, str | None, str]:
    """Search using full-web-search (includes content), fall back to summaries.

    Returns (evidence_text, source_url, raw_summaries).
    """
    # Try full-web-search first (Brave-based, includes page content)
    try:
        full_result = await mcp.call_tool(
            "full-web-search", {"query": query, "limit": "3", "includeContent": "true"}
        )
        source_url = pick_best_url(full_result)
        if full_result and len(full_result.strip()) > 200:
            return full_result[:4000], source_url, full_result
    except Exception as e:
        print(f"    [search] full-web-search failed: {e}", file=sys.stderr)

    # Fallback: summaries only
    try:
        summaries = await mcp.call_tool(
            "get-web-search-summaries", {"query": query, "limit": "5"}
        )
        source_url = pick_best_url(summaries)
        return summaries[:4000], source_url, summaries
    except Exception as e:
        print(f"    [search] summaries also failed: {e}", file=sys.stderr)
        return "", None, ""


# ═══════════════════════════════════════════════════════════════════
#  LLM Judge
# ═══════════════════════════════════════════════════════════════════

JUDGE_SYSTEM = """You are a fact-checker for Azure technical documentation.
Compare the CLAIM against the EVIDENCE and return a JSON verdict.

Return ONLY this JSON (no markdown fences, no extra text):
{
  "status": "current" | "outdated" | "unverifiable",
  "current_info": "what the evidence says",
  "source_url": "the authoritative URL",
  "notes": "explanation of any discrepancy",
  "confidence": "high" | "medium" | "low"
}"""

JUDGE_USER = """CLAIM: "{fact}" (about {entity})

EVIDENCE (from {source_url}):
{evidence}

Return ONLY the JSON verdict."""


def _llm_request(proxy_url: str, model: str, api_key: str,
                 system: str, user: str) -> str:
    """Synchronous OpenAI-compatible chat completion (stdlib only)."""
    url = proxy_url.rstrip("/") + "/chat/completions"
    body = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.1,
        "max_tokens": 500,
    }).encode()
    req = urllib.request.Request(
        url, data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read())
    return data["choices"][0]["message"]["content"]


def _parse_json_verdict(text: str) -> dict | None:
    """Extract JSON from LLM response, handling markdown fences."""
    # Strip markdown fences if present
    text = re.sub(r"^```(?:json)?\s*\n?", "", text.strip())
    text = re.sub(r"\n?```\s*$", "", text.strip())
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to find JSON object in the text
        m = re.search(r"\{[^{}]*\}", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group())
            except json.JSONDecodeError:
                pass
    return None


async def judge_fact(
    entity: str, fact_text: str, evidence: str,
    source_url: str | None, proxy_url: str, model: str, api_key: str,
) -> dict:
    """Call LLM judge and parse verdict. Retries up to 2x on parse failure."""
    user_prompt = JUDGE_USER.format(
        fact=fact_text,
        entity=entity,
        source_url=source_url or "unknown",
        evidence=evidence[:4000],
    )
    loop = asyncio.get_running_loop()
    for attempt in range(3):
        try:
            raw = await loop.run_in_executor(
                None, _llm_request, proxy_url, model, api_key, JUDGE_SYSTEM, user_prompt
            )
            verdict = _parse_json_verdict(raw)
            if verdict and "status" in verdict:
                return verdict
            print(f"    [judge] Parse failed (attempt {attempt + 1}), raw: {raw[:200]}", file=sys.stderr)
        except Exception as e:
            print(f"    [judge] Error (attempt {attempt + 1}): {e}", file=sys.stderr)
            if attempt < 2:
                await asyncio.sleep(2 ** attempt)

    return {
        "status": "unverifiable",
        "current_info": None,
        "source_url": source_url,
        "notes": "LLM judge failed after 3 attempts",
        "confidence": "low",
    }


# ═══════════════════════════════════════════════════════════════════
#  JSONL journal for resume safety
# ═══════════════════════════════════════════════════════════════════

def load_journal(path: pathlib.Path) -> dict[str, dict]:
    """Load existing JSONL journal, return {fact_id: record}."""
    results: dict[str, dict] = {}
    if not path.is_file():
        return results
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
            fid = rec.get("fact_id")
            if fid:
                results[fid] = rec
        except json.JSONDecodeError:
            continue
    return results


def append_journal(path: pathlib.Path, record: dict) -> None:
    """Append one JSON record to the JSONL journal with file locking."""
    line = json.dumps(record, ensure_ascii=False) + "\n"
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        os.write(fd, line.encode())
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def compact_journal(journal_path: pathlib.Path, output_path: pathlib.Path) -> None:
    """Compact JSONL journal to a single JSON array file."""
    records = load_journal(journal_path)
    # Sort by entity then fact for stable output
    sorted_records = sorted(records.values(), key=lambda r: (r.get("entity", ""), r.get("fact", "")))
    output_path.write_text(json.dumps(sorted_records, indent=2, ensure_ascii=False) + "\n")
    print(f"Compacted {len(sorted_records)} records → {output_path}")


# ═══════════════════════════════════════════════════════════════════
#  Orchestration
# ═══════════════════════════════════════════════════════════════════

async def verify_one(
    entry: dict,
    mcp: McpStdioClient,
    proxy_url: str,
    model: str,
    api_key: str,
    journal_path: pathlib.Path,
    semaphore: asyncio.Semaphore,
    delay: float,
) -> dict:
    """Full pipeline for one fact: search → fetch → judge → journal."""
    entity = entry["entity"]
    fact_text = entry["fact"]
    fid = fact_id(entity, fact_text)

    async with semaphore:
        print(f"  ▶ [{fid[:8]}] {entity}: {fact_text[:60]}...", flush=True)
        query = build_search_query(entry)

        try:
            evidence, source_url, _summaries = await search_and_fetch(mcp, query)
        except Exception as e:
            print(f"    [search] Failed: {e}", file=sys.stderr)
            evidence = ""
            source_url = None

        if not evidence.strip():
            verdict = {
                "status": "unverifiable",
                "current_info": None,
                "source_url": None,
                "notes": "Search returned no results",
                "confidence": "low",
            }
        else:
            verdict = await judge_fact(
                entity, fact_text, evidence, source_url,
                proxy_url, model, api_key,
            )

        record = {
            "fact_id": fid,
            "entity": entity,
            "fact": fact_text,
            "verdict": verdict.get("status", "unverifiable"),
            "current_info": verdict.get("current_info"),
            "source_url": verdict.get("source_url", source_url),
            "source_excerpt": (evidence[:500] if evidence else None),
            "verified_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
            "notes": verdict.get("notes"),
            "confidence": verdict.get("confidence", "low"),
        }

        append_journal(journal_path, record)
        status_icon = {"current": "✓", "outdated": "✗", "unverifiable": "?"}.get(record["verdict"], "?")
        print(f"    {status_icon} {record['verdict']} (confidence: {record['confidence']})", flush=True)

        if delay > 0:
            await asyncio.sleep(delay)

        return record


async def verify_all(facts: list[dict], args: argparse.Namespace) -> list[dict]:
    """Load existing journal (resume), verify remaining, compact output."""
    load_dotenv()

    proxy_url = get_proxy_url(args.proxy_url)
    model = get_llm_model()
    api_key = get_api_key()
    mcp_cmd = get_mcp_cmd(args.mcp_cmd)
    journal_path = pathlib.Path(args.journal)
    output_path = pathlib.Path(args.output)

    # Filter to perishable unless --force covers all
    if not args.all_types:
        facts = [f for f in facts if f.get("type") == "perishable"]

    # Filter by entity if specified
    if args.entity:
        entity_lower = args.entity.lower()
        facts = [f for f in facts if f["entity"].lower() == entity_lower]

    if not facts:
        print("No matching facts to verify.")
        return []

    # Resume: load existing journal, skip already-verified
    existing = load_journal(journal_path)
    if not args.force:
        pending = [f for f in facts if fact_id(f["entity"], f["fact"]) not in existing]
    else:
        pending = facts

    print(f"Facts: {len(facts)} total, {len(existing)} already verified, {len(pending)} pending")
    print(f"Proxy: {proxy_url}  Model: {model}")
    print(f"MCP cmd: {' '.join(mcp_cmd)}")
    print(f"Journal: {journal_path}")

    if args.dry_run:
        print("\n--- Dry run: facts to verify ---")
        for f in pending:
            fid = fact_id(f["entity"], f["fact"])
            q = build_search_query(f)
            print(f"  [{fid[:8]}] {f['entity']}: {f['fact'][:60]}...")
            print(f"           query: {q}")
        return []

    if not pending:
        print("Nothing to do — all facts already verified.")
        compact_journal(journal_path, output_path)
        return list(existing.values())

    # Limit count
    if args.max:
        pending = pending[: args.max]
        print(f"Limited to {args.max} facts (--max)")

    # Start MCP server
    mcp = McpStdioClient(mcp_cmd, call_timeout=args.timeout)
    print("Starting MCP server...", flush=True)
    try:
        await mcp.start()
        print("MCP server ready.", flush=True)
    except Exception as e:
        print(f"ERROR: Failed to start MCP server: {e}", file=sys.stderr)
        sys.exit(1)

    semaphore = asyncio.Semaphore(args.concurrency)
    results: list[dict] = []

    try:
        # Run sequentially with semaphore control for concurrency
        tasks = [
            verify_one(f, mcp, proxy_url, model, api_key, journal_path, semaphore, args.delay)
            for f in pending
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        # Handle exceptions in results
        clean_results = []
        for i, r in enumerate(results):
            if isinstance(r, Exception):
                print(f"  ERROR verifying fact {i}: {r}", file=sys.stderr)
            else:
                clean_results.append(r)
        results = clean_results
    finally:
        await mcp.stop()

    # Compact journal → JSON array
    compact_journal(journal_path, output_path)

    return results


# ═══════════════════════════════════════════════════════════════════
#  CLI
# ═══════════════════════════════════════════════════════════════════

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "--facts", default=str(DEFAULT_FACTS),
        help="Path to facts.json (default: mental_models/facts.json)",
    )
    ap.add_argument(
        "--output", default=str(DEFAULT_OUTPUT),
        help="Path to verifications.json output (default: mental_models/verifications.json)",
    )
    ap.add_argument(
        "--journal", default=str(DEFAULT_JOURNAL),
        help="Path to verifications.jsonl journal (default: mental_models/verifications.jsonl)",
    )
    ap.add_argument("--entity", help="Verify only facts for this entity")
    ap.add_argument("--dry-run", action="store_true", help="List facts to verify, don't execute")
    ap.add_argument("--force", action="store_true", help="Re-verify even if result exists")
    ap.add_argument("--all-types", action="store_true", help="Verify all fact types, not just perishable")
    ap.add_argument("--delay", type=float, default=1.0, help="Delay in seconds between queries (default: 1.0)")
    ap.add_argument("--concurrency", type=int, default=3, help="Max parallel verifications (default: 3)")
    ap.add_argument("--max", type=int, default=0, help="Stop after N facts (0 = unlimited)")
    ap.add_argument("--timeout", type=float, default=30.0, help="Per-MCP-call timeout in seconds (default: 30)")
    ap.add_argument("--mcp-cmd", help="MCP server command (e.g. 'node /path/to/index.js')")
    ap.add_argument("--proxy-url", help="LLM proxy URL (default: from LLM_BINDING_HOST env)")
    return ap


def main() -> int:
    args = build_parser().parse_args()

    facts_path = pathlib.Path(args.facts)
    if not facts_path.is_file():
        print(f"ERROR: facts file not found: {facts_path}", file=sys.stderr)
        return 1

    facts = json.loads(facts_path.read_text())
    print(f"Loaded {len(facts)} facts from {facts_path}")

    results = asyncio.run(verify_all(facts, args))
    if results:
        counts = {}
        for r in results:
            s = r.get("verdict", "unknown")
            counts[s] = counts.get(s, 0) + 1
        print(f"\nResults: {counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
