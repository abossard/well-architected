#!/usr/bin/env python3
"""Build a knowledge graph JSON from mission-critical markdown files.

Nodes:
  - doc      : one per markdown file
  - h2       : top-level section heading
  - h3       : sub-section heading
  - product  : Azure service or tool
  - pattern  : architectural / resilience pattern
  - process  : practice, methodology, or workflow
  - concept  : abstract principle or quality attribute
  - metric   : measurable indicator (SLA, RTO, etc.)

Edges:
  - contains : doc -> h2 -> h3
  - mentions : doc -> term (when term appears in doc)
  - links    : doc -> doc (explicit markdown link to another doc)
  - related  : term -> term (co-occurrence in same doc, weighted)
"""
from __future__ import annotations
import json, re, os, collections, pathlib, html

SRC = pathlib.Path("/Users/abossard/Desktop/cxe/well-architected/well-architected/mission-critical")
OUT = pathlib.Path(__file__).parent / "graph.json"

# Classified domain terms. Each maps term -> node type.
TERM_TYPES: dict[str, str] = {}

_PRODUCTS = [
    "azure front door", "application gateway", "traffic manager",
    "api management", "event hubs", "service bus", "cosmos db", "azure sql",
    "azure kubernetes service", "aks", "app service", "container apps",
    "key vault", "managed identity", "private endpoint", "private link",
    "virtual network", "vnet", "network security group", "nsg",
    "ddos protection", "web application firewall",
    "application insights", "log analytics", "azure monitor",
    "bicep", "terraform", "arm template",
    "subscription", "resource group", "landing zone",
    "azure container registry", "acr",
]
_PATTERNS = [
    "deployment stamps", "deployment stamp", "scale unit", "scale units",
    "active-active", "active-passive", "multi-region",
    "blue-green deployment", "canary deployment",
    "circuit breaker", "bulkhead", "retry", "throttling", "idempotency",
    "data replication", "data partitioning", "sharding", "caching",
    "feature flag", "dark launch", "rollout", "rollback",
    "health model", "health modeling",
    "load balancing", "load balancer", "auto-scaling", "autoscaling",
    "failover", "failback",
    "region pairs", "paired region", "availability zones", "availability zone",
]
_PROCESSES = [
    "chaos engineering", "chaos testing", "game day",
    "failure mode analysis", "fma",
    "ci/cd", "infrastructure as code",
    "disaster recovery", "business continuity",
    "capacity planning", "cost optimization", "operational excellence",
    "synthetic transaction", "synthetic monitoring",
    "observability", "monitoring", "logging", "tracing",
    "encryption at rest", "encryption in transit",
]
_CONCEPTS = [
    "zero trust", "defense in depth", "least privilege",
    "resilience", "reliability", "availability", "scalability",
    "performance", "security", "workload", "sovereign cloud",
]
_METRICS = [
    "rto", "rpo", "slo", "sli", "sla",
    "latency", "throughput", "metrics", "tls",
]

for term in _PRODUCTS:  TERM_TYPES[term] = "product"
for term in _PATTERNS:  TERM_TYPES[term] = "pattern"
for term in _PROCESSES: TERM_TYPES[term] = "process"
for term in _CONCEPTS:  TERM_TYPES[term] = "concept"
for term in _METRICS:   TERM_TYPES[term] = "metric"

ALL_TERMS = list(TERM_TYPES.keys())
# Dedup preserve order, longest first
seen=set(); ALL_TERMS=[c for c in sorted(set(ALL_TERMS), key=lambda s:-len(s)) if not (c in seen or seen.add(c))]

def slugify(s): return re.sub(r"[^a-z0-9]+","-",s.lower()).strip("-")

def parse_file(path: pathlib.Path):
    text = path.read_text(encoding="utf-8")
    # strip YAML front matter
    if text.startswith("---"):
        m = re.match(r"^---\n.*?\n---\n", text, re.DOTALL)
        if m: text = text[m.end():]
    # strip code blocks
    text_no_code = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    title_m = re.search(r"^#\s+(.+)$", text_no_code, re.MULTILINE)
    title = title_m.group(1).strip() if title_m else path.stem
    h2s, h3s = [], []
    current_h2 = None
    for line in text_no_code.splitlines():
        m2 = re.match(r"^##\s+(.+?)\s*$", line)
        m3 = re.match(r"^###\s+(.+?)\s*$", line)
        if m2:
            current_h2 = m2.group(1).strip()
            h2s.append(current_h2)
        elif m3 and current_h2:
            h3s.append((current_h2, m3.group(1).strip()))
    # outbound markdown links to other local md files
    links = set()
    for m in re.finditer(r"\]\(([^)]+\.md)(?:#[^)]*)?\)", text_no_code):
        tgt = m.group(1).split("/")[-1]
        links.add(tgt)
    # term mentions
    term_counts = collections.Counter()
    low = text_no_code.lower()
    masked = low
    for c in ALL_TERMS:
        pat = r"\b" + re.escape(c) + r"\b"
        n = len(re.findall(pat, masked))
        if n:
            term_counts[c] += n
            masked = re.sub(pat, " " * len(c), masked)
    return dict(file=path.name, title=title, h2s=h2s, h3s=h3s,
                links=sorted(links), terms=dict(term_counts))

LEARN_BASE = "https://learn.microsoft.com/azure/well-architected/mission-critical"

def file_to_url(filename):
    """Convert markdown filename to Microsoft Learn URL."""
    return f"{LEARN_BASE}/{filename.replace('.md', '')}"

def build():
    files = sorted(SRC.glob("mission-critical-*.md"))
    docs = [parse_file(p) for p in files]
    nodes, edges = [], []
    node_ids=set()
    def add_node(nid, **kw):
        if nid in node_ids: return
        node_ids.add(nid); nodes.append({"id":nid, **kw})

    # doc nodes
    for d in docs:
        nid = "doc:"+d["file"]
        url = file_to_url(d["file"])
        add_node(nid, type="doc", label=d["title"], file=d["file"],
                 url=url, size=12+len(d["h2s"]))
    # heading nodes + contains edges
    for d in docs:
        doc_id = "doc:"+d["file"]
        base_url = file_to_url(d["file"])
        for h2 in d["h2s"]:
            hid = f"h2:{d['file']}::{slugify(h2)}"
            url = f"{base_url}#{slugify(h2)}"
            add_node(hid, type="h2", label=h2, file=d["file"], url=url, size=6)
            edges.append({"source":doc_id,"target":hid,"type":"contains","weight":1})
        for (h2, h3) in d["h3s"]:
            hid3 = f"h3:{d['file']}::{slugify(h2)}::{slugify(h3)}"
            hid2 = f"h2:{d['file']}::{slugify(h2)}"
            url = f"{base_url}#{slugify(h3)}"
            add_node(hid3, type="h3", label=h3, file=d["file"], url=url, size=3)
            edges.append({"source":hid2,"target":hid3,"type":"contains","weight":1})

    # doc -> doc links
    file_set = {d["file"] for d in docs}
    for d in docs:
        for tgt in d["links"]:
            if tgt in file_set and tgt != d["file"]:
                edges.append({"source":"doc:"+d["file"],"target":"doc:"+tgt,
                              "type":"links","weight":2})

    # term nodes (only terms appearing in >=1 doc)
    term_doc_count = collections.Counter()
    term_total = collections.Counter()
    for d in docs:
        for c,n in d["terms"].items():
            term_doc_count[c]+=1
            term_total[c]+=n
    for c,total in term_total.items():
        if total < 1: continue
        ntype = TERM_TYPES.get(c, "concept")
        cid = f"{ntype}:{slugify(c)}"
        add_node(cid, type=ntype, label=c, size=4+min(total,20),
                 total=total, docs=term_doc_count[c])
    # doc -> term mentions
    for d in docs:
        for c,n in d["terms"].items():
            ntype = TERM_TYPES.get(c, "concept")
            edges.append({"source":"doc:"+d["file"],
                          "target":f"{ntype}:{slugify(c)}",
                          "type":"mentions","weight":n})
    # term <-> term co-occurrence (same doc)
    co = collections.Counter()
    for d in docs:
        cs = sorted(d["terms"].keys())
        for i in range(len(cs)):
            for j in range(i+1,len(cs)):
                co[(cs[i],cs[j])] += 1
    for (a,b),w in co.items():
        if w>=2:
            atype = TERM_TYPES.get(a, "concept")
            btype = TERM_TYPES.get(b, "concept")
            edges.append({"source":f"{atype}:{slugify(a)}",
                          "target":f"{btype}:{slugify(b)}",
                          "type":"related","weight":w})

    graph = {"nodes":nodes,"edges":edges,
             "meta":{"docs":len(docs),"nodes":len(nodes),"edges":len(edges)}}
    OUT.write_text(json.dumps(graph, indent=2))
    print(f"Wrote {OUT}: {len(nodes)} nodes, {len(edges)} edges across {len(docs)} docs")

if __name__=="__main__":
    build()
