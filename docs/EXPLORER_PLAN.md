# WAF Knowledge Graph Explorer — Design Spec

## 1. Architecture Overview

Replace the current two-page setup (`index.html` landing + `graph.html` graph-only) with a
**single-page explorer** (`explorer.html`) that has **four co-equal views** accessible via a
persistent top nav. The graph is ONE view, not THE view.

```
DATA SOURCES (existing, no changes)
├── data/graph.json          613 nodes, 801 edges, stats
├── data/details.json        per-node: type, summary, docs[], links[], facts[]
└── mental_models/cards.json 54 cards: name, mantra, layer, when/without/tradeoff/builds/enables
```

### Views (tabs)

| Tab label     | Content                                    | Primary JSON source     |
|---------------|--------------------------------------------|-------------------------|
| **Graph**     | Full force-directed graph, all 613 nodes   | graph.json + details    |
| **Models**    | Browsable card grid of 54 mental models    | cards.json + details    |
| **Nodes**     | Searchable/filterable table of 613 nodes   | graph.json + details    |
| **Facts**     | Timeless vs perishable facts, sortable     | details.json (facts[])  |

All views share a **Detail Drawer** on the right that shows full node info when selected.

---

## 2. Global Layout (CSS Grid)

```
┌─────────────────────────────────────────────────────────────────────┐
│ TOPBAR  [☰ WAF Explorer]  [Graph] [Models] [Nodes] [Facts]  [🔍]  │  48px
├──────────────────────────────────────────────┬──────────────────────┤
│                                              │                      │
│              MAIN CONTENT                    │    DETAIL DRAWER     │
│           (view-dependent)                   │      400px           │
│                                              │                      │
│                                              │   Node/card details  │
│                                              │   + facts + links    │
│                                              │   + source docs      │
│                                              │                      │
│          calc(100% - 400px)                  │                      │
├──────────────────────────────────────────────┴──────────────────────┤
│ STATUSBAR   613 nodes · 801 edges · 54 models · 629 facts    24px  │
└─────────────────────────────────────────────────────────────────────┘
```

**CSS approach:**

```css
body {
  display: grid;
  grid-template-rows: 48px 1fr 24px;
  grid-template-columns: 1fr 400px;
  grid-template-areas:
    "topbar  topbar"
    "main    drawer"
    "status  status";
  height: 100vh;
  overflow: hidden;
}
```

Drawer collapses to 0px when nothing is selected (main expands to full width).
Responsive: below 900px, drawer becomes a bottom sheet (40vh).

---

## 3. Topbar Design

```
┌──────────────────────────────────────────────────────────────────────┐
│  ◆ WAF Explorer  │ [Graph] [Models] [Nodes] [Facts] │  🔍 Search…  │
└──────────────────────────────────────────────────────────────────────┘
         logo         ◄── tab buttons ──►             global search
```

- **Tabs** are `<button>` elements with `.active` class (amber background #f59e0b, dark text)
- **Global search** (input, min-width 260px) — searches across ALL views:
  - In Graph view: filters visible nodes + highlights matches
  - In Models view: filters card grid
  - In Nodes view: filters table rows
  - In Facts view: filters facts by text
- **Keyboard**: `/` focuses search, `Esc` clears, `Tab` cycles views (1-4)

---

## 4. View 1: Graph (Full Canvas)

### Layout

```
┌─────────────────────────────────────────────┬──────────────────────┐
│ [builds_on] [enables] [mentioned_with] [ref]│                      │
│                                             │  DETAIL DRAWER       │
│          ● Zero Trust                       │  ┌─────────────────┐ │
│         ╱ ╲                                 │  │ 🧠 Zero Trust   │ │
│    ● Defense ● Least                        │  │ ─────────────── │ │
│    In-Depth   Privilege                     │  │ security        │ │
│        │       │                            │  │                 │ │
│     ● Micro  ● Network                     │  │ "Never trust,   │ │
│     Segment   Security                      │  │ always verify"  │ │
│       │       Groups                        │  │                 │ │
│       ● Azure   ● Azure                    │  │ When to apply:  │ │
│       Firewall    Front Door                │  │ • Designing     │ │
│                                             │  │   network sec…  │ │
│  ┌──────────────────────────────────────┐   │  │                 │ │
│  │ Legend:                              │   │  │ Builds on:      │ │
│  │ ● Mental Model  ● Pattern           │   │  │ [Defense-In-D…] │ │
│  │ ● Azure Service ● Process           │   │  │ [Least Privil…] │ │
│  │ ● Concept       ● Metric            │   │  │                 │ │
│  │ ● Anti-pattern  ● Other             │   │  │ 📄 Source docs  │ │
│  └──────────────────────────────────────┘   │  └─────────────────┘ │
├─────────────────────────────────────────────┴──────────────────────┤
│ 613 nodes · 801 edges · Zoom: 1.0x                                 │
└────────────────────────────────────────────────────────────────────┘
```

### Key changes from current graph.html

| Current                       | New                                           |
|-------------------------------|-----------------------------------------------|
| Depth slider (progressive)    | **REMOVED** — show ALL 613 nodes always        |
| "All edges" toggle            | **4 edge-type toggles** (individually)         |
| Dimmed/promoted expansion     | **REMOVED** — all nodes visible at all times   |
| Canvas-only render            | Keep canvas + SVG label overlay (works well)   |

### Graph interactions

1. **Hover** → node glows, tooltip shows name + type
2. **Click** → selects node, populates Detail Drawer, highlights connected edges
3. **Double-click** → opens first source doc URL in new tab
4. **Pan/zoom** — d3-zoom on canvas (keep existing)
5. **Edge toggles** — 4 pill buttons top-left, each toggleable:
   - `builds_on` (amber, 39 edges) — ON by default
   - `enables` (indigo, 27 edges) — ON by default
   - `references` (green, 105 edges) — ON by default
   - `mentioned_with` (gray, 630 edges) — OFF by default (performance)

### D3 features to use

- **d3-zoom** for pan/zoom (existing, keep)
- **d3-quadtree** for hit-testing (existing, keep)
- **Canvas 2D** for node/edge rendering (existing, keep — needed for 613 nodes)
- **SVG overlay** for labels on mental model nodes only (existing, keep)
- **No d3-force** — use pre-computed x,y from graph.json (already present)

### Click-to-navigate from other views

When another view (Models, Nodes, Facts) triggers "show in graph":
1. Switch to Graph tab
2. Find node by id in `state.idx`
3. Compute target transform: `d3.zoomIdentity.translate(W/2 - n.x * k, H/2 - n.y * k).scale(k)`
   where `k = 2.5` (zoom in to neighborhood level)
4. Animate with `d3.transition().duration(600)` on the zoom behavior
5. Set `state.selected = n.id`, add golden ring highlight (3px stroke)
6. Populate Detail Drawer

---

## 5. View 2: Mental Model Cards

### Layout

```
┌─────────────────────────────────────────────┬──────────────────────┐
│                                             │                      │
│  Filter: [All layers ▼]  Sort: [A-Z ▼]     │  DETAIL DRAWER       │
│  ───────────────────────────────────────     │  (populated on       │
│                                             │   card click)        │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐    │                      │
│  │ 🧠       │ │ 🧠       │ │ 🧠       │    │                      │
│  │ Zero     │ │ Defense  │ │ CAP      │    │                      │
│  │ Trust    │ │ In-Depth │ │ Theorem  │    │                      │
│  │          │ │          │ │          │    │                      │
│  │ "Never   │ │ "Layer   │ │ "Pick    │    │                      │
│  │  trust…" │ │  defens…"│ │  two…"   │    │                      │
│  │          │ │          │ │          │    │                      │
│  │ security │ │ security │ │ data     │    │                      │
│  │ 19 conn  │ │ 12 conn  │ │ 8 conn   │    │                      │
│  │ [Graph ↗]│ │ [Graph ↗]│ │ [Graph ↗]│    │                      │
│  └──────────┘ └──────────┘ └──────────┘    │                      │
│                                             │                      │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐    │                      │
│  │ 🧠       │ │ 🧠       │ │ 🧠       │    │                      │
│  │ STRIDE   │ │ Least    │ │ Maturity │    │                      │
│  │          │ │ Privilege│ │ Model    │    │                      │
│  │ "Threat  │ │ "Grant   │ │ "Measur…"│    │                      │
│  │  model…" │ │  minimum │ │          │    │                      │
│  │          │ │  access" │ │          │    │                      │
│  │ security │ │ security │ │ org.     │    │                      │
│  │ 6 conn   │ │ 11 conn  │ │ 15 conn  │    │                      │
│  │ [Graph ↗]│ │ [Graph ↗]│ │ [Graph ↗]│    │                      │
│  └──────────┘ └──────────┘ └──────────┘    │                      │
│                                             │                      │
├─────────────────────────────────────────────┴──────────────────────┤
│ Showing 54 of 54 models · Layer: All                               │
└────────────────────────────────────────────────────────────────────┘
```

### Card component (single card)

```
┌───────────────────────────────────┐
│  🧠  Zero Trust          security │  ← icon + name + layer pill
│  ──────────────────────────────── │
│  "Never trust, always verify—    │  ← mantra (italic, amber left border)
│   assume breach everywhere."     │
│                                   │
│  When to apply:                   │  ← first 3 items, truncated
│  • Designing network security     │
│  • Handling internal traffic      │
│  • Architecting mission-critical  │
│                                   │
│  Builds on: [Defense-In-Depth]    │  ← chip buttons (clickable)
│             [Least-Privilege]     │
│                                   │
│  ⚡ 19 connections   [Graph ↗]    │  ← connection count + navigate btn
└───────────────────────────────────┘
```

### CSS for card grid

```css
.card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 16px;
  padding: 24px;
  overflow-y: auto;
}
```

### Card interactions

- **Click card** → populates Detail Drawer with full mental model info (all when_to_apply,
  without_it, tradeoff, enables, builds_on, source docs)
- **Click [Graph ↗]** → switches to Graph view, zooms to that node
- **Click chip** (e.g. [Defense-In-Depth]) → selects that node, populates drawer
- **Layer filter dropdown**: `All | security | structural | foundational | operational | data | organizational`
- **Sort dropdown**: `A-Z | Z-A | Most connections | Layer`

---

## 6. View 3: Full Node List

### Layout

```
┌─────────────────────────────────────────────┬──────────────────────┐
│                                             │                      │
│  Type: [All ▼]  Has facts: [☐]  Sort: [▼]  │  DETAIL DRAWER       │
│  ───────────────────────────────────────     │                      │
│                                             │                      │
│  NAME                  TYPE          DEG    │  (populated on       │
│  ──────────────────── ───────────── ────    │   row click)         │
│  ● Azure Well-Arch…   PROCESS        41    │                      │
│  ● Mission-Critical…  CONCEPT        24    │                      │
│  ● Azure              AZURE_SERVICE  23    │                      │
│  ● AKS                AZURE_SERVICE  15    │                      │
│  ● Deployment Stamp   PATTERN         6    │                      │
│  ● Azure Landing Z…   PATTERN         5    │                      │
│  ● Zero Trust         MENTAL_MODEL   19    │                      │
│  ● Defense-In-Depth   MENTAL_MODEL   12    │                      │
│  ● Cosmos DB          AZURE_SERVICE  11    │                      │
│  ● Health Modeling    PATTERN         8    │                      │
│  ● SLA               METRIC          7    │                      │
│  ● Noisy Neighbor…   ANTI_PATTERN    1    │                      │
│  │                                         │                      │
│  │  ↕ virtual scroll (613 rows)            │                      │
│  │                                         │                      │
│                                             │                      │
├─────────────────────────────────────────────┴──────────────────────┤
│ Showing 613 of 613 nodes · Type: All                               │
└────────────────────────────────────────────────────────────────────┘
```

### Columns

| Column    | Width  | Content                        | Sortable |
|-----------|--------|--------------------------------|----------|
| Color dot | 20px   | Colored by type                | —        |
| Name      | flex   | Node id text                   | ✓ A-Z    |
| Type      | 140px  | Type badge/pill                | ✓        |
| Degree    | 60px   | Edge count                     | ✓ desc   |
| Facts     | 50px   | Fact count (if > 0)            | ✓        |
| Action    | 32px   | [↗] graph navigate button      | —        |

### Node list interactions

- **Click row** → select node, populate Detail Drawer
- **Click [↗]** → switch to Graph, zoom to node
- **Type dropdown**: `All | MENTAL_MODEL (39) | PATTERN (88) | AZURE_SERVICE (178) | PROCESS (66) | CONCEPT (163) | METRIC (15) | ANTI_PATTERN (5) | OTHER (59)`
  - Each option shows count in parentheses
  - Selecting a type filters the list instantly
- **"Has facts" checkbox**: filters to only nodes with `facts.length > 0`
- **Sort dropdown**: `Name A-Z | Name Z-A | Most connected | Most facts | Type`
- **Search** (global topbar): filters by name substring match, case-insensitive
- **Virtual scroll**: only render ~50 visible rows at a time (DOM performance for 613 items)

### Type color mapping (consistent everywhere)

```
MENTAL_MODEL  → #f59e0b (amber)      PATTERN      → #3b82f6 (blue)
AZURE_SERVICE → #6366f1 (indigo)     PROCESS      → #22c55e (green)
CONCEPT       → #9ca3af (gray)       METRIC       → #ef4444 (red)
ANTI_PATTERN  → #e11d48 (rose)       OTHER        → #64748b (slate)
```

---

## 7. View 4: Facts Panel

### Layout

```
┌─────────────────────────────────────────────┬──────────────────────┐
│                                             │                      │
│  [Timeless (284)] [Perishable (345)] [All]  │  DETAIL DRAWER       │
│  Confidence: [All ▼]   Sort: [Shelf ▼]     │                      │
│  ───────────────────────────────────────     │                      │
│                                             │                      │
│  ┌─────────────────────────────────────┐    │                      │
│  │  ♾ TIMELESS · high confidence       │    │                      │
│  │  "Mission-critical workloads        │    │                      │
│  │   require zero-downtime deploys"    │    │                      │
│  │  📍 Mission-Critical Workload       │    │  (shows node detail  │
│  │                          [Graph ↗]  │    │   when fact's node   │
│  └─────────────────────────────────────┘    │   is clicked)        │
│                                             │                      │
│  ┌─────────────────────────────────────┐    │                      │
│  │  ⏳ PERISHABLE · 12 mo shelf life   │    │                      │
│  │  "Azure offers both IaaS and PaaS"  │    │                      │
│  │  🔍 Verify: Check Azure categories  │    │                      │
│  │  📍 Azure                [Graph ↗]  │    │                      │
│  └─────────────────────────────────────┘    │                      │
│                                             │                      │
│  ┌─────────────────────────────────────┐    │                      │
│  │  ⏳ PERISHABLE · 6 mo shelf life    │    │                      │
│  │  "AKS supports node auto-repair"    │    │                      │
│  │  🔍 Verify: Check AKS release notes │    │                      │
│  │  📍 AKS                 [Graph ↗]  │    │                      │
│  └─────────────────────────────────────┘    │                      │
│                                             │                      │
│  │  ↕ virtual scroll (629 facts)            │                      │
│                                             │                      │
├─────────────────────────────────────────────┴──────────────────────┤
│ 284 timeless · 345 perishable · 629 total facts                    │
└────────────────────────────────────────────────────────────────────┘
```

### Fact card design

**Timeless fact:**
```
┌─────────────────────────────────────────────┐
│ ♾  │ "Mission-critical workloads require    │  ← amber left border
│    │  zero-downtime deployments"            │
│    │                                         │
│    │  confidence: ●●●  high                  │  ← green dots
│    │  📍 Mission-Critical Workload [Graph ↗] │  ← source node link
└─────────────────────────────────────────────┘
```

**Perishable fact:**
```
┌─────────────────────────────────────────────┐
│ ⏳ │ "Azure offers both IaaS and PaaS"      │  ← red/rose left border
│    │                                         │
│    │  shelf life: 12 months                  │  ← countdown badge
│    │  confidence: ●●○  medium                │  ← yellow dots
│    │  🔍 Check Azure service categories      │  ← verification hint
│    │  📍 Azure                    [Graph ↗]  │  ← source node link
└─────────────────────────────────────────────┘
```

### Visual distinction: timeless vs perishable

| Attribute      | Timeless                  | Perishable                    |
|----------------|---------------------------|-------------------------------|
| Left border    | 3px solid #f59e0b (amber) | 3px solid #e11d48 (rose)      |
| Icon           | ♾ (infinity)              | ⏳ (hourglass)                |
| Background     | #161b22 (standard)        | #161b22 (standard)            |
| Extra fields   | —                         | shelf_life_months, verify hint |
| Badge          | `TIMELESS` pill (amber)   | `12 MO` pill (rose)           |

### Confidence indicators

```
high:   ●●● (green #22c55e)
medium: ●●○ (yellow #f59e0b)
low:    ●○○ (red #ef4444)
```

### Fact filters

- **Type toggle**: 3 pill buttons — `Timeless (284)` | `Perishable (345)` | `All (629)`
  Active button gets amber background
- **Confidence dropdown**: `All | High | Medium | Low`
- **Sort dropdown**: `Shelf life (ascending) | Shelf life (descending) | Confidence | Node name A-Z`
- **Search** (global): filters facts by text content match

---

## 8. Detail Drawer (Shared Right Panel)

The drawer is view-independent — any selection from any view populates it.

### Mental Model detail (full)

```
┌──────────────────────────────┐
│  🧠  Zero Trust              │  ← icon + name
│  ┌────────────────────────┐  │
│  │ security               │  │  ← layer pill
│  └────────────────────────┘  │
│                              │
│  "Never trust, always        │  ← mantra (blockquote, amber border)
│   verify—assume breach       │
│   everywhere."               │
│                              │
│  ─── Summary ───────────     │
│  The Zero Trust model…       │  ← from details.json summary
│                              │
│  ─── 🎯 When to apply ──    │
│  • Designing network sec…    │  ← all 5 items from cards.json
│  • Handling internal…        │
│  • Architecting mission…     │
│  • Establishing access…      │
│  • Building a security…      │
│                              │
│  ─── 💥 Without it ─────    │
│  • Lateral movement after…   │  ← all items
│  • Over-trusted internal…    │
│  • Implicit access grants…   │
│  • Flat networks with no…    │
│  • Delayed breach detect…    │
│                              │
│  ─── ⚖️ Key tradeoff ───    │
│  ┌────────────────────────┐  │
│  │ Stronger security at   │  │  ← purple left border box
│  │ the cost of increased  │  │
│  │ complexity, latency…   │  │
│  └────────────────────────┘  │
│                              │
│  ─── 🔗 Builds on ──────    │
│  [Defense-In-Depth]          │  ← clickable chips
│  [Least-Privilege Access]    │
│  [Network Perimeter]         │
│  [Security]                  │
│  [Segmentation Strategy]     │
│                              │
│  ─── 🔗 Enables ────────    │
│  [Micro-Segmentation]        │
│  [Network Security Groups]   │
│  [Azure Firewall]            │
│  [Mission-Critical Workl…]   │
│  [Security Readiness Plan]   │
│                              │
│  ─── 📑 Facts (if any) ─    │
│  ♾ "Zero trust requires…"   │
│  ⏳ "Azure AD supports…"    │
│                              │
│  ─── 🔗 Links ──────────    │
│  📄 Azure docs (12)          │
│  📄 Internal WAF (3)         │
│  📄 External (2)             │
│  [expand to see all]         │
│                              │
│  ─── 📄 Source docs ─────    │
│  ┌────────────────────────┐  │
│  │ Application design of  │  │  ← clickable, opens Learn URL
│  │ mission-critical…      │  │
│  │ learn.microsoft.com/…  │  │
│  └────────────────────────┘  │
│                              │
│  [← prev model] [next →]    │  ← only for mental models
└──────────────────────────────┘
```

### Generic node detail

```
┌──────────────────────────────┐
│  ☁️  AKS                     │  ← icon colored by type
│  ┌────────────────────────┐  │
│  │ AZURE SERVICE          │  │  ← type pill
│  └────────────────────────┘  │
│                              │
│  Azure Kubernetes Service…   │  ← summary from details.json
│                              │
│  ─── 📑 Facts ──────────    │
│  ♾ "AKS node pools allow…"  │
│  ⏳ "AKS supports 1.28…"    │  ← shelf life badge inline
│                              │
│  ─── 📎 Connected (15) ─    │
│  [Mission-Critical Workl…]   │  ← sorted by edge weight
│  [Azure]                     │
│  [Container Orchestration]   │
│  … (14 clickable chips)      │
│                              │
│  ─── 🔗 Links (9) ──────    │
│  • autoscaling (azure-docs)  │  ← grouped by link type
│  • AKS docs (azure-docs)     │
│  • k8s.io (external)         │
│                              │
│  ─── 📄 Source docs ─────    │
│  ┌────────────────────────┐  │
│  │ Mission-Critical App…  │  │
│  └────────────────────────┘  │
└──────────────────────────────┘
```

### Drawer behavior

- **Opens** with a 300ms slide from right (or already visible)
- **Close button** (X) top-right returns drawer to hidden state, main content expands
- **Drawer width**: fixed 400px on desktop, 100% bottom sheet on mobile
- Clicking a chip in the drawer **replaces** drawer content with that node
- Back button (←) in drawer header navigates breadcrumb history

---

## 9. Interaction Flow Diagram

```
  ┌──────────┐    click row     ┌──────────────┐
  │ Nodes    │ ───────────────→ │ Detail Drawer │
  │ List     │                  │ (node info)   │
  └──────────┘                  └──────┬───────┘
       │                               │
       │ click [↗]                     │ click chip
       ▼                               ▼
  ┌──────────┐    click node    ┌──────────────┐
  │ Graph    │ ───────────────→ │ Detail Drawer │
  │ (zoomed) │                  │ (new node)    │
  └──────────┘                  └──────────────┘
       ▲                               ▲
       │ click [Graph ↗]               │ click [Graph ↗]
       │                               │
  ┌──────────┐    click card    ┌──────────────┐
  │ Models   │ ───────────────→ │ Detail Drawer │
  │ Grid     │                  │ (model card)  │
  └──────────┘                  └──────────────┘
       ▲
       │ click 📍 node name
       │
  ┌──────────┐    click fact    ┌──────────────┐
  │ Facts    │ ───────────────→ │ Detail Drawer │
  │ Panel    │                  │ (source node) │
  └──────────┘                  └──────────────┘
```

### Navigation function: `navigateToGraph(nodeId)`

```
1. Set active tab = "Graph"
2. Show graph view, hide other views
3. Look up node: n = state.idx.get(nodeId)
4. If not found, show toast "Node not found"
5. Compute zoom target:
   k = 2.5
   tx = W/2 - n.x * k
   ty = H/2 - n.y * k
   targetTransform = d3.zoomIdentity.translate(tx, ty).scale(k)
6. Animate: d3.select(canvas).transition().duration(600)
            .call(zoomBehavior.transform, targetTransform)
7. Set state.selected = nodeId
8. Add highlight ring: 3px #f59e0b stroke around node
9. Pulse animation: ring scales 1.0 → 1.3 → 1.0 over 800ms
10. Populate Detail Drawer with node data
```

---

## 10. Data Flow Map

```
graph.json                         details.json
  ├─ nodes[] ──→ Graph canvas       ├─ [id].summary ──→ Drawer summary
  │  ├─ id     → label, hit-test    ├─ [id].type ──→ Drawer type pill
  │  ├─ type   → color, icon        ├─ [id].docs[] ──→ Drawer source docs
  │  ├─ deg    → node radius        ├─ [id].links[] ──→ Drawer links section
  │  ├─ x, y   → position           ├─ [id].facts[] ──→ Drawer facts + Facts view
  │  └─ mc     → (unused now)       │   ├─ .fact ──→ fact text
  ├─ edges[] ──→ Graph edges         │   ├─ .type ──→ timeless/perishable badge
  │  ├─ s, t   → source/target       │   ├─ .shelf_life_months ──→ shelf badge
  │  └─ r      → edge color/toggle   │   ├─ .confidence ──→ dot indicator
  └─ stats   ──→ Status bar           │   └─ .verification_hint ──→ verify text
                                      └─ [id].mantra ──→ Drawer blockquote (if MM)

cards.json (mental_models/)
  ├─ name ──→ card title, grid search
  ├─ mantra ──→ card subtitle, drawer quote
  ├─ layer ──→ layer pill, layer filter
  ├─ when_to_apply[] ──→ card preview (3), drawer full list
  ├─ without_it[] ──→ drawer "Without it" section
  ├─ key_tradeoff ──→ drawer tradeoff box
  ├─ builds_on[] ──→ card chips, drawer chips
  ├─ enables[] ──→ drawer chips
  └─ connections ──→ card badge, sort option
```

---

## 11. Tab/Panel Switching Mechanics

### State management

```javascript
const appState = {
  activeTab: 'graph',        // 'graph' | 'models' | 'nodes' | 'facts'
  selectedNode: null,        // node id string or null
  drawerOpen: false,         // true when a node/card is selected
  search: '',                // global search string

  // Graph-specific
  graphTransform: d3.zoomIdentity,
  edgeVisibility: { builds_on: true, enables: true, references: true, mentioned_with: false },

  // Models-specific
  modelLayerFilter: 'all',
  modelSort: 'name-asc',

  // Nodes-specific
  nodeTypeFilter: 'all',
  nodeHasFactsFilter: false,
  nodeSort: 'degree-desc',

  // Facts-specific
  factTypeFilter: 'all',    // 'all' | 'timeless' | 'perishable'
  factConfidenceFilter: 'all',
  factSort: 'shelf-asc',

  // Drawer
  drawerHistory: [],         // breadcrumb stack of node ids
};
```

### Tab switching

```javascript
function switchTab(tabName) {
  appState.activeTab = tabName;

  // Hide all view containers
  document.querySelectorAll('.view-panel').forEach(el => el.hidden = true);

  // Show active view
  document.getElementById(`view-${tabName}`).hidden = false;

  // Update tab button active states
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.tab === tabName);
  });

  // If switching to graph and a node is selected, ensure it's centered
  if (tabName === 'graph' && appState.selectedNode) {
    requestAnimationFrame(() => centerOnNode(appState.selectedNode));
  }

  // Re-render the active view (graph needs requestRender, others need list rebuild)
  if (tabName === 'graph') requestRender();
}
```

### View container structure (HTML)

```html
<div id="view-graph"  class="view-panel" hidden><!-- canvas + svg --></div>
<div id="view-models" class="view-panel" hidden><!-- card grid --></div>
<div id="view-nodes"  class="view-panel" hidden><!-- table --></div>
<div id="view-facts"  class="view-panel" hidden><!-- fact list --></div>
```

Only ONE view is visible at a time. The graph canvas persists (not destroyed on tab switch)
so zoom/pan state is preserved.

---

## 12. Responsive Behavior

### Breakpoints

| Width      | Layout                                                    |
|------------|-----------------------------------------------------------|
| > 1200px   | Full side-by-side: main + 400px drawer                    |
| 900–1200px | Main + 320px drawer (narrower)                            |
| < 900px    | Stacked: main 100%, drawer slides up as 45vh bottom sheet |

### Mobile (< 900px)

```
┌──────────────────────────┐
│ ◆ WAF  [≡ tabs]    [🔍] │  ← hamburger for tab menu
├──────────────────────────┤
│                          │
│      MAIN CONTENT        │
│    (graph/grid/list)     │
│         100%             │
│                          │
│                          │
├──────────────────────────┤  ← drag handle
│    DETAIL DRAWER          │
│    (bottom sheet)         │
│    45vh, scrollable       │
└──────────────────────────┘
```

### CSS responsive rules

```css
@media (max-width: 1200px) {
  body { grid-template-columns: 1fr 320px; }
}

@media (max-width: 900px) {
  body {
    grid-template-columns: 1fr;
    grid-template-rows: 48px 1fr auto 24px;
    grid-template-areas: "topbar" "main" "drawer" "status";
  }
  #drawer {
    border-left: none;
    border-top: 1px solid var(--border);
    max-height: 45vh;
    overflow-y: auto;
  }
  .card-grid { grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); }
  .tab-nav { display: none; }          /* hidden, use hamburger */
  .tab-nav.open { display: flex; }     /* toggled by hamburger */
}
```

---

## 13. Color System

All colors on the dark theme (#0d1117 background):

```
SURFACES
  --bg:        #0d1117   page background
  --surface:   #161b22   panels, cards, drawer
  --surface-2: #1c2128   hover states, nested panels
  --border:    #30363d   all borders

TEXT
  --text:      #e6edf3   primary text
  --muted:     #8b949e   secondary text, labels
  --link:      #58a6ff   clickable links

ACCENTS
  --accent:    #f59e0b   primary accent (amber) — mental models, active states
  --accent-2:  #6366f1   secondary accent (indigo) — source docs, service nodes

NODE TYPES (consistent across all views)
  --mm:        #f59e0b   Mental Model (amber)
  --pattern:   #3b82f6   Pattern (blue)
  --service:   #6366f1   Azure Service (indigo)
  --process:   #22c55e   Process (green)
  --concept:   #9ca3af   Concept (gray)
  --metric:    #ef4444   Metric (red)
  --anti:      #e11d48   Anti-pattern (rose)
  --other:     #64748b   Other (slate)

FACTS
  --timeless:  #f59e0b   Timeless fact border (amber)
  --perishable:#e11d48   Perishable fact border (rose)

EDGES
  builds_on:      rgba(245,158,11, 0.55)  amber
  enables:        rgba(99,102,241, 0.55)  indigo
  references:     rgba(34,197,94, 0.40)   green
  mentioned_with: rgba(139,148,158,0.18)  gray (subtle)
```

---

## 14. Performance Considerations

| Concern                              | Solution                                       |
|--------------------------------------|-------------------------------------------------|
| 613 nodes on canvas                  | Canvas 2D (not SVG DOM) — already implemented  |
| 801 edges rendering                  | Only draw enabled edge types; skip off-screen   |
| 630 mentioned_with edges             | OFF by default, warn before enabling             |
| 629 facts in list                    | Virtual scroll — render only visible ~30 rows    |
| 613 nodes in table                   | Virtual scroll or paginate (30 per page)         |
| 54 model cards                       | No virtualization needed (small count)           |
| details.json lazy load               | Already implemented — fetch on first need        |
| cards.json load                      | Fetch once on Models tab first open              |
| Tab switching                        | Hide/show, don't destroy — preserve scroll pos   |
| Graph zoom animation                 | d3.transition 600ms ease-out                     |

---

## 15. File Structure

```
docs/
├── explorer.html              ← NEW: single-page app (replaces graph.html as primary)
├── index.html                 ← KEEP: landing page, update link to explorer.html
├── graph.html                 ← KEEP: legacy, add redirect banner
├── data/
│   ├── graph.json             ← KEEP: no changes
│   └── details.json           ← KEEP: no changes
├── mental_models/
│   ├── cards.json             ← KEEP: no changes
│   └── ...
└── EXPLORER_PLAN.md           ← THIS FILE
```

### Implementation order

1. **Scaffold HTML** — grid layout, topbar with tabs, 4 view containers, drawer
2. **Port Graph view** — copy canvas/SVG logic from graph.html, remove depth slider, add edge toggles
3. **Build Nodes view** — table with virtual scroll, type filter dropdown, sorting
4. **Build Models view** — card grid from cards.json, layer filter, click-to-select
5. **Build Facts view** — extract facts from details.json, timeless/perishable split, virtual scroll
6. **Build Detail Drawer** — merge mental model card + generic card logic, add facts & links sections
7. **Wire cross-view navigation** — `navigateToGraph()`, chip clicks, [Graph ↗] buttons
8. **Polish** — responsive breakpoints, keyboard shortcuts, search integration, animations

---

## 16. Keyboard Shortcuts

| Key       | Action                                   |
|-----------|------------------------------------------|
| `/`       | Focus global search                      |
| `Esc`     | Clear search / close drawer / deselect   |
| `1`       | Switch to Graph tab                      |
| `2`       | Switch to Models tab                     |
| `3`       | Switch to Nodes tab                      |
| `4`       | Switch to Facts tab                      |
| `←` `→`   | Prev/next mental model (Graph + Models) |
| `Enter`   | In search: jump to first match           |

---

## 17. Search UX Detail

Global search input behavior per active view:

### Graph view
- As user types, non-matching nodes fade to 15% opacity
- Matching nodes keep full opacity + get a subtle white glow
- Edge rendering unchanged (edges to faded nodes also fade)
- Press Enter: select first match, zoom to it, populate drawer
- Clear search: all nodes return to full opacity

### Models view
- Filter cards in real-time: cards not matching name/mantra/layer are hidden
- CSS transition: `opacity 0.2s` on card hide/show
- No card rearrangement (avoids layout thrash) — just visibility toggle

### Nodes view
- Filter table rows in real-time by name substring
- Combined with type dropdown filter (AND logic)
- Status bar updates: "Showing 42 of 613 nodes"

### Facts view
- Filter facts by text content substring
- Combined with type toggle + confidence filter (AND logic)
- Status bar updates: "Showing 18 of 629 facts"

---

## 18. Accessibility

- All interactive elements are `<button>` or `<a>` (not div-with-onclick)
- `aria-label` on icon-only buttons
- `role="tablist"` on tab nav, `role="tab"` on buttons, `role="tabpanel"` on views
- `aria-selected` tracks active tab
- Graph canvas has `aria-label="Knowledge graph visualization"` + fallback text
- Fact confidence dots have `aria-label="confidence: high"`
- Color is never the ONLY differentiator — icons + text labels accompany all type indicators
- Focus visible outlines (2px amber) on all interactive elements

---

*This plan is a complete design spec. A developer can implement explorer.html
directly from these wireframes, data mappings, and interaction descriptions.*
