#!/usr/bin/env python3
"""Generate a beautiful static HTML page from mental model mining results.

Reads cards.json, taxonomy.json, summary.json and produces a polished
single-page app with:
- Formatted model cards with expandable details
- Taxonomy browser grouped by category
- Usage guide with explanations
- Interactive D3 graph

Usage: python3 build_pages.py
"""
import json
import os
import pathlib
import re
from collections import Counter

OUT = pathlib.Path(__file__).parent / "mental_models"
DOCS = pathlib.Path(__file__).parent.parent / "docs"

cards = json.loads((OUT / "cards.json").read_text())
taxonomy = json.loads((OUT / "taxonomy.json").read_text())
summary = json.loads((OUT / "summary.json").read_text())

cat_counts = Counter(t["category"] for t in taxonomy)

# Group taxonomy
categories = {}
for t in sorted(taxonomy, key=lambda x: x["entity"]):
    cat = t["category"]
    if cat not in categories:
        categories[cat] = []
    categories[cat].append(t["entity"])

# Build name → card slug lookup for linking
def slugify(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")

card_files = {f.replace(".html", "") for f in os.listdir(OUT / "cards")
              if f.endswith(".html") and f != "index.html"} if (OUT / "cards").exists() else set()

mental_model_names = {t["entity"] for t in taxonomy if t["category"] == "MENTAL_MODEL"}

def linkify_name(name):
    """If a name has a card diagram page, return a link to it."""
    slug = slugify(name)
    if slug in card_files:
        return f'<a href="cards/{slug}.html" class="model-link">{name}</a>'
    return name

def linkify_list(names_csv):
    """Turn a comma-separated list of names into linked names."""
    if names_csv == "—":
        return "—"
    parts = [n.strip() for n in names_csv.split(",")]
    return ", ".join(linkify_name(p) for p in parts)

LAYER_EMOJI = {
    "foundational": "🧠", "structural": "🏗️", "operational": "⚙️",
    "security": "🔒", "organizational": "🏛️", "data": "📊",
}
LAYER_COLOR = {
    "foundational": "#f59e0b", "structural": "#3b82f6", "operational": "#10b981",
    "security": "#ef4444", "organizational": "#a855f7", "data": "#8b5cf6",
}
CAT_COLOR = {
    "MENTAL_MODEL": "#f59e0b", "PATTERN": "#3b82f6", "PROCESS": "#10b981",
    "METRIC": "#ef4444", "AZURE_SERVICE": "#6366f1", "CONCEPT": "#8b949e",
    "TRADEOFF": "#f97316", "ANTI_PATTERN": "#dc2626", "OTHER": "#4b5563",
}
CAT_EMOJI = {
    "MENTAL_MODEL": "🧠", "PATTERN": "🔷", "PROCESS": "⚙️",
    "METRIC": "📏", "AZURE_SERVICE": "☁️", "CONCEPT": "💡",
    "TRADEOFF": "⚖️", "ANTI_PATTERN": "🚫", "OTHER": "📦",
}

def card_html(card):
    layer = card.get("layer", "foundational")
    emoji = LAYER_EMOJI.get(layer, "🧠")
    color = LAYER_COLOR.get(layer, "#f59e0b")
    conns = card.get("connections", 0)
    slug = slugify(card["name"])
    has_tree = slug in card_files

    when_items = "".join(f"<li>{w}</li>" for w in card.get("when_to_apply", []))
    fail_items = "".join(f"<li>{w}</li>" for w in card.get("without_it", []))
    builds = linkify_list(", ".join(card.get("builds_on", [])) or "—")
    enables = linkify_list(", ".join(card.get("enables", [])) or "—")
    tree_link = f'<a href="cards/{slug}.html" class="tree-link">🌳 Explore connection tree →</a>' if has_tree else ""

    return f"""
    <div class="model-card" data-layer="{layer}">
      <div class="card-header">
        <div class="card-title-row">
          <span class="layer-badge" style="background:{color}20;color:{color};border-color:{color}40">{emoji} {layer}</span>
          <span class="conn-badge">{conns} connections</span>
        </div>
        <h3>{linkify_name(card['name'])}</h3>
        <p class="mantra">"{card.get('mantra', '')}"</p>
      </div>
      <div class="card-body">
        <div class="card-section">
          <h4>🎯 When to apply</h4>
          <ul>{when_items}</ul>
        </div>
        <div class="card-section">
          <h4>💥 Without it</h4>
          <ul>{fail_items}</ul>
        </div>
        <div class="card-section">
          <h4>⚖️ Key tradeoff</h4>
          <p>{card.get('key_tradeoff', '—')}</p>
        </div>
        <div class="card-section card-links">
          <div><strong>🔗 Builds on:</strong> {builds}</div>
          <div><strong>🔗 Enables:</strong> {enables}</div>
        </div>
        {tree_link}
      </div>
    </div>"""

def taxonomy_section(cat, items):
    emoji = CAT_EMOJI.get(cat, "📦")
    color = CAT_COLOR.get(cat, "#8b949e")
    pills = []
    for item in items:
        slug = slugify(item)
        if cat == "MENTAL_MODEL" and slug in card_files:
            pills.append(f'<a href="cards/{slug}.html" class="tax-pill tax-link" style="border-color:{color}40">{item}</a>')
        else:
            pills.append(f'<span class="tax-pill" style="border-color:{color}40">{item}</span>')
    return f"""
    <div class="tax-group">
      <h3 style="color:{color}">{emoji} {cat} <span class="tax-count">({len(items)})</span></h3>
      <div class="tax-pills">{"".join(pills)}</div>
    </div>"""

cards_html = "".join(card_html(c) for c in cards)
taxonomy_html = "".join(
    taxonomy_section(cat, items)
    for cat, items in sorted(categories.items(), key=lambda x: -len(x[1]))
)

# Anti-patterns section
anti_patterns = categories.get("ANTI_PATTERN", [])
ap_html = "".join(f"<li>🚫 {ap}</li>" for ap in anti_patterns)

# Tradeoffs section
tradeoffs = categories.get("TRADEOFF", [])
tr_html = "".join(f"<li>⚖️ {t}</li>" for t in tradeoffs)

page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>Mental Models — Mission-Critical Azure Well-Architected Framework</title>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<style>
  :root {{
    --bg:#0d1117; --surface:#161b22; --border:#30363d; --fg:#c9d1d9;
    --muted:#8b949e; --accent:#58a6ff; --gold:#f59e0b;
  }}
  * {{ box-sizing:border-box; }}
  html {{ background:var(--bg); color:var(--fg);
    font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }}
  body {{ margin:0; padding:0; }}

  .hero {{ text-align:center; padding:48px 20px 32px; }}
  .hero h1 {{ font-size:36px; margin:0; }}
  .hero h1 span {{ color:var(--gold); }}
  .hero .subtitle {{ color:var(--muted); font-size:16px; margin:8px 0 24px; max-width:600px; display:inline-block; }}

  .stats {{ display:flex; justify-content:center; gap:24px; flex-wrap:wrap; margin:24px 0; }}
  .stat {{ text-align:center; }}
  .stat .n {{ font-size:36px; font-weight:700; color:var(--accent); line-height:1; }}
  .stat .l {{ font-size:12px; color:var(--muted); margin-top:4px; }}

  .container {{ max-width:1100px; margin:0 auto; padding:0 20px; }}

  .nav {{ display:flex; gap:8px; justify-content:center; margin:32px 0; flex-wrap:wrap; }}
  .nav a {{ background:var(--surface); border:1px solid var(--border); border-radius:8px;
    padding:8px 16px; color:var(--fg); text-decoration:none; font-size:14px; font-weight:500; }}
  .nav a:hover {{ border-color:var(--accent); color:var(--accent); }}

  section {{ margin:48px 0; }}
  section > h2 {{ font-size:22px; margin:0 0 8px; padding-bottom:8px; border-bottom:1px solid var(--border); }}
  section > .desc {{ color:var(--muted); font-size:14px; margin:0 0 24px; }}

  /* Guide section */
  .guide {{ background:var(--surface); border:1px solid var(--border); border-radius:12px;
    padding:24px; margin:24px 0; }}
  .guide h3 {{ margin:0 0 12px; color:var(--accent); font-size:16px; }}
  .guide p {{ color:var(--muted); font-size:14px; margin:8px 0; }}
  .guide ol, .guide ul {{ color:var(--fg); font-size:14px; padding-left:20px; }}
  .guide li {{ margin:6px 0; }}
  .guide code {{ background:#21262d; padding:2px 6px; border-radius:4px; font-size:13px; }}

  /* Model cards */
  .cards-grid {{ display:grid; grid-template-columns:repeat(auto-fill, minmax(480px, 1fr)); gap:16px; }}
  .model-card {{ background:var(--surface); border:1px solid var(--border); border-radius:12px;
    overflow:hidden; transition:border-color .2s; }}
  .model-card:hover {{ border-color:var(--accent); }}
  .card-header {{ padding:20px 20px 12px; }}
  .card-title-row {{ display:flex; gap:8px; align-items:center; margin-bottom:8px; }}
  .layer-badge {{ display:inline-block; padding:2px 10px; border-radius:10px;
    font-size:11px; font-weight:600; border:1px solid; }}
  .conn-badge {{ font-size:11px; color:var(--muted); }}
  .card-header h3 {{ margin:0; font-size:18px; }}
  .mantra {{ font-style:italic; color:#e6edf3; font-size:15px; margin:6px 0 0; }}
  .card-body {{ padding:0 20px 20px; }}
  .card-section {{ margin:12px 0; }}
  .card-section h4 {{ margin:0 0 4px; font-size:13px; color:var(--muted); }}
  .card-section ul {{ margin:4px 0; padding-left:18px; font-size:13px; }}
  .card-section li {{ margin:3px 0; }}
  .card-section p {{ font-size:13px; margin:4px 0; }}
  .card-links {{ font-size:12px; color:var(--muted); }}
  .card-links div {{ margin:4px 0; }}
  .card-links strong {{ color:var(--fg); }}

  /* Taxonomy */
  .tax-group {{ margin:20px 0; }}
  .tax-group h3 {{ font-size:15px; margin:0 0 8px; }}
  .tax-count {{ font-weight:400; color:var(--muted); font-size:13px; }}
  .tax-pills {{ display:flex; flex-wrap:wrap; gap:6px; }}
  .tax-pill {{ display:inline-block; padding:3px 10px; background:#21262d;
    border:1px solid var(--border); border-radius:16px; font-size:12px; }}

  /* Warnings/Anti-patterns */
  .warn-list {{ list-style:none; padding:0; }}
  .warn-list li {{ padding:6px 12px; margin:4px 0; background:#21262d;
    border-radius:8px; font-size:14px; }}

  /* Filter */
  .filter-row {{ display:flex; gap:8px; margin:16px 0; flex-wrap:wrap; align-items:center; }}
  .filter-chip {{ display:inline-flex; align-items:center; gap:4px; padding:4px 10px;
    background:#21262d; border:1px solid var(--border); border-radius:16px;
    font-size:12px; cursor:pointer; }}
  .filter-chip input {{ margin:0; }}
  .filter-chip.active {{ border-color:var(--accent); }}

  @media (max-width:600px) {{
    .cards-grid {{ grid-template-columns:1fr; }}
    .hero h1 {{ font-size:24px; }}
    .stats {{ gap:16px; }}
  }}
</style>
</head>
<body>

<div class="hero">
  <h1>🧠 <span>Mental Models</span> for Mission-Critical Systems</h1>
  <div class="subtitle">
    54 mental models, 161 patterns, 9 anti-patterns extracted from 880 entities
    across 34 Azure Well-Architected Framework documents using LightRAG + Claude Opus 4.6
  </div>
  <div class="stats">
    <div class="stat"><div class="n">54</div><div class="l">Mental Models</div></div>
    <div class="stat"><div class="n">161</div><div class="l">Patterns</div></div>
    <div class="stat"><div class="n">168</div><div class="l">Azure Services</div></div>
    <div class="stat"><div class="n">980</div><div class="l">Relations</div></div>
    <div class="stat"><div class="n">9</div><div class="l">Anti-patterns</div></div>
  </div>
  <div class="nav">
    <a href="#guide">📖 How to use</a>
    <a href="#cards">🃏 Model cards</a>
    <a href="#taxonomy">📂 Full taxonomy</a>
    <a href="#warnings">⚠️ Anti-patterns</a>
    <a href="../graph.html">🕸️ Knowledge graph</a>
  </div>
</div>

<div class="container">

  <section id="guide">
    <h2>📖 How to use this information</h2>
    <p class="desc">This is a decision-support tool, not a checklist. Use it to build architectural intuition.</p>

    <div class="guide">
      <h3>For architects starting a new mission-critical project</h3>
      <ol>
        <li><strong>Start with the foundational models</strong> (🧠 gold cards) — these are ways of <em>thinking</em>, not specific technologies. Internalize "Blast Radius", "Assume Failure", and "Simplicity" before choosing any Azure service.</li>
        <li><strong>Use the structural models</strong> (🏗️ blue cards) to shape your architecture — Scale Units, Health Modeling, Active/Active. These determine your deployment topology.</li>
        <li><strong>Apply operational models</strong> (⚙️ green cards) to decide how you'll run it — Automation, Observability, Chaos Engineering, Error Budgets.</li>
        <li><strong>Check anti-patterns</strong> — scan the ⚠️ section below to verify you're not drifting toward known failure modes.</li>
      </ol>
    </div>

    <div class="guide">
      <h3>For teams reviewing an existing workload</h3>
      <ol>
        <li><strong>Pick 3-5 model cards</strong> most relevant to your current pain points</li>
        <li><strong>Read the "Without it" section</strong> — if you recognize your system, that model needs attention</li>
        <li><strong>Check the "Builds on" links</strong> — you might be missing a prerequisite mental model</li>
        <li><strong>Explore the <a href="../graph.html" style="color:var(--accent)">knowledge graph</a></strong> to trace connections between concepts</li>
      </ol>
    </div>

    <div class="guide">
      <h3>For learning and onboarding</h3>
      <p>Mental models are listed in dependency order. The top cards are foundational — everything else builds on them. Reading order:</p>
      <ol>
        <li>Blast Radius → Simplicity → Assume Failure (foundations)</li>
        <li>Scale Units → Health Modeling → Active/Active (structure)</li>
        <li>Automation → Observability → Error Budgets (operations)</li>
        <li>Zero Trust → Defense in Depth (security)</li>
      </ol>
      <p>Each card's <strong>"Key tradeoff"</strong> tells you what you're giving up — there are no free lunches in reliability engineering.</p>
    </div>

    <div class="guide">
      <h3>Understanding the data</h3>
      <p><strong>Centrality</strong> = how many connections a concept has in the knowledge graph. High centrality = the concept touches many other areas.</p>
      <p><strong>Bridge score</strong> = how much a concept connects otherwise-disconnected parts of the graph. High bridge = removing this concept would fragment understanding.</p>
      <p><strong>Layer</strong> = where the model sits in the thinking hierarchy. You must internalize lower layers before upper layers are useful.</p>
    </div>
  </section>

  <section id="cards">
    <h2>🃏 Mental Model Cards</h2>
    <p class="desc">Top {len(cards)} mental models ranked by graph centrality. Each card is one screen — mantra first, details on demand.</p>

    <div class="filter-row">
      <span style="color:var(--muted);font-size:12px;">Filter by layer:</span>
      <label class="filter-chip"><input type="checkbox" data-layer="all" checked/> All</label>
      <label class="filter-chip"><input type="checkbox" data-layer="foundational" checked/> 🧠 Foundational</label>
      <label class="filter-chip"><input type="checkbox" data-layer="structural" checked/> 🏗️ Structural</label>
      <label class="filter-chip"><input type="checkbox" data-layer="operational" checked/> ⚙️ Operational</label>
      <label class="filter-chip"><input type="checkbox" data-layer="security" checked/> 🔒 Security</label>
      <label class="filter-chip"><input type="checkbox" data-layer="data" checked/> 📊 Data</label>
    </div>

    <div class="cards-grid">
      {cards_html}
    </div>
  </section>

  <section id="warnings">
    <h2>⚠️ Anti-patterns & Tradeoffs</h2>
    <p class="desc">Known failure modes and tension pairs identified in the knowledge graph. If you see these in your system, investigate.</p>

    <div style="display:grid;grid-template-columns:1fr 1fr;gap:24px;">
      <div>
        <h3 style="color:#dc2626;">🚫 Anti-patterns</h3>
        <ul class="warn-list">{ap_html}</ul>
      </div>
      <div>
        <h3 style="color:#f97316;">⚖️ Tradeoffs</h3>
        <ul class="warn-list">{tr_html}</ul>
      </div>
    </div>
  </section>

  <section id="taxonomy">
    <h2>📂 Full Taxonomy ({len(taxonomy)} entities)</h2>
    <p class="desc">Every entity in the knowledge graph, classified by Claude Opus 4.6 into 9 categories.</p>
    {taxonomy_html}
  </section>

  <footer style="color:var(--muted);font-size:12px;margin:48px 0 24px;padding-top:16px;border-top:1px solid var(--border);">
    Built from <a href="https://github.com/MicrosoftDocs/well-architected" style="color:var(--accent)">MicrosoftDocs/well-architected</a>
    using <a href="https://github.com/HKUDS/LightRAG" style="color:var(--accent)">LightRAG</a> +
    Claude Opus 4.6 via <a href="https://github.com/ericc-ch/copilot-api" style="color:var(--accent)">copilot-api</a>.
    <a href="https://github.com/abossard/well-architected/tree/mental-models/kg-explorer" style="color:var(--accent)">Source code</a>
  </footer>
</div>

<script>
document.querySelectorAll('.filter-row input').forEach(cb => {{
  cb.addEventListener('change', () => {{
    const allCb = document.querySelector('[data-layer=all]');
    if (cb.dataset.layer === 'all') {{
      document.querySelectorAll('.filter-row input').forEach(c => c.checked = cb.checked);
    }} else {{
      allCb.checked = false;
    }}
    const active = new Set();
    document.querySelectorAll('.filter-row input:checked').forEach(c => {{
      if (c.dataset.layer !== 'all') active.add(c.dataset.layer);
    }});
    const showAll = document.querySelector('[data-layer=all]').checked;
    document.querySelectorAll('.model-card').forEach(card => {{
      card.style.display = (showAll || active.has(card.dataset.layer)) ? '' : 'none';
    }});
  }});
}});
</script>
</body>
</html>"""

(OUT / "index.html").write_text(page)
print(f"Generated {OUT / 'index.html'} ({len(page)} bytes)")

# Also copy to docs
DOCS.mkdir(exist_ok=True)
(DOCS / "mental_models").mkdir(exist_ok=True)
(DOCS / "mental_models" / "index.html").write_text(page)
print(f"Copied to {DOCS / 'mental_models' / 'index.html'}")
