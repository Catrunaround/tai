"""
Slide theme CSS for HTML artifact mode.

This CSS is injected into the iframe that renders model-generated HTML slides.
The model is given a reference of available classes so it can use them in its output.

Design system inspired by Pencil slide guidelines:
- Layout contracts for common slide patterns
- Professional typography scale (min 28px body)
- High-contrast dark mode palette with accent colors
- Smooth transitions and interactive patterns
"""

SLIDE_THEME_CSS = """\
/* ============================================================
   TAI SLIDE DESIGN SYSTEM
   Based on Pencil slide guidelines: clarity > readability > hierarchy
   ============================================================ */

/* === Reset & Base === */
* { margin: 0; padding: 0; box-sizing: border-box; }

:root {
    /* --- Color System --- */
    --bg-page:      #0A0F1C;
    --bg-surface:   #1E293B;
    --bg-surface-2: #334155;
    --bg-inset:     #0F172A;

    --text-primary:   #F1F5F9;
    --text-secondary: #94A3B8;
    --text-muted:     #64748B;
    --text-inverted:  #0A0F1C;

    --accent-cyan:    #22D3EE;
    --accent-purple:  #A78BFA;
    --accent-green:   #34D399;
    --accent-amber:   #FBBF24;
    --accent-red:     #F87171;
    --accent-blue:    #60A5FA;

    --border-subtle:  rgba(255, 255, 255, 0.08);
    --border-accent:  rgba(34, 211, 238, 0.3);

    --shadow-card:    0 4px 24px rgba(0, 0, 0, 0.25);
    --shadow-glow:    0 0 20px rgba(34, 211, 238, 0.15);

    /* --- Typography --- */
    --font-display: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
    --font-mono:    'SF Mono', 'Fira Code', 'Cascadia Code', 'JetBrains Mono', monospace;

    /* --- Spacing --- */
    --space-xs: 4px;
    --space-sm: 8px;
    --space-md: 16px;
    --space-lg: 24px;
    --space-xl: 32px;
    --space-2xl: 48px;
    --space-3xl: 64px;

    /* --- Radius --- */
    --radius-sm: 6px;
    --radius-md: 12px;
    --radius-lg: 16px;
    --radius-pill: 100px;

    /* --- Transitions --- */
    --ease-out: cubic-bezier(0.16, 1, 0.3, 1);
    --duration: 0.3s;
}

body.slide {
    font-family: var(--font-display);
    color: var(--text-primary);
    background: transparent;
    line-height: 1.5;
    padding: 0;
    -webkit-font-smoothing: antialiased;
}

/* ============================================================
   LAYOUT CONTRACTS — Pencil slide patterns translated to CSS
   Each layout is a full-slide composition. Pick ONE per slide.
   ============================================================ */

/* --- Layout: Cover (layout-01) — Title + subtitle, centered --- */
.layout-cover {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    text-align: center;
    min-height: 100%;
    padding: var(--space-3xl);
    gap: var(--space-lg);
}
.layout-cover h2 { font-size: 2.8rem; font-weight: 700; line-height: 1.1; }
.layout-cover .subtitle { font-size: 1.3rem; color: var(--text-secondary); max-width: 600px; }

/* --- Layout: Split (layout-05/06) — Two columns, concept + visual --- */
.layout-split {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: var(--space-2xl);
    align-items: center;
    min-height: 100%;
    padding: var(--space-2xl);
}
.layout-split > .col { display: flex; flex-direction: column; gap: var(--space-md); }

/* --- Layout: Pillars (layout-07) — 3 equal columns --- */
.layout-pillars {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: var(--space-lg);
    padding: var(--space-2xl);
    align-items: start;
}

/* --- Layout: Compare (layout-08) — Side-by-side comparison --- */
.layout-compare {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: var(--space-2xl);
    padding: var(--space-2xl);
}
.layout-compare > .compare-col {
    background: var(--bg-surface);
    border-radius: var(--radius-lg);
    padding: var(--space-xl);
    display: flex;
    flex-direction: column;
    gap: var(--space-md);
}

/* --- Layout: KPI (layout-09) — Big number hero --- */
.layout-kpi {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    text-align: center;
    min-height: 100%;
    padding: var(--space-3xl);
    gap: var(--space-md);
}
.layout-kpi .kpi-number {
    font-size: 5rem;
    font-weight: 800;
    line-height: 1;
    background: linear-gradient(135deg, var(--accent-cyan), var(--accent-purple));
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
}
.layout-kpi .kpi-label { font-size: 1rem; color: var(--text-muted); text-transform: uppercase; letter-spacing: 2px; }

/* --- Layout: Process (layout-13) — Horizontal step flow --- */
.layout-process {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    min-height: 100%;
    padding: var(--space-2xl);
    gap: var(--space-2xl);
}
.process-flow {
    display: flex;
    align-items: center;
    gap: var(--space-md);
    width: 100%;
    justify-content: center;
}
.process-step {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: var(--space-sm);
    flex: 1;
    max-width: 200px;
    text-align: center;
}
.process-step .step-icon {
    width: 56px;
    height: 56px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 1.5rem;
    font-weight: 700;
    color: var(--text-inverted);
    transition: transform var(--duration) var(--ease-out), box-shadow var(--duration) var(--ease-out);
}
.process-step:hover .step-icon { transform: scale(1.15); box-shadow: var(--shadow-glow); }
.process-arrow { color: var(--text-muted); font-size: 1.5rem; flex-shrink: 0; }

/* --- Layout: Matrix (layout-15) — 2x2 grid --- */
.layout-matrix {
    display: grid;
    grid-template-columns: 1fr 1fr;
    grid-template-rows: 1fr 1fr;
    gap: var(--space-lg);
    padding: var(--space-2xl);
    min-height: 100%;
}

/* --- Layout: List (layout-19) — Title + items --- */
.layout-list {
    display: flex;
    flex-direction: column;
    padding: var(--space-2xl);
    gap: var(--space-lg);
}

/* --- Layout: Stack — Vertical centered content (default) --- */
.layout-stack {
    display: flex;
    flex-direction: column;
    padding: var(--space-xl) var(--space-2xl);
    gap: var(--space-lg);
}

/* ============================================================
   TYPOGRAPHY — Pencil slide scale: titles 2-4rem, body 1-1.2rem
   ============================================================ */

h2 { font-size: 2rem; font-weight: 700; color: var(--text-primary); line-height: 1.15; }
h3 { font-size: 1.4rem; font-weight: 600; color: var(--text-primary); line-height: 1.25; }
h4 { font-size: 1.15rem; font-weight: 600; color: var(--text-primary); }
p  { font-size: 1rem; color: var(--text-secondary); line-height: 1.6; }
strong { color: var(--text-primary); }
em { color: var(--text-secondary); font-style: italic; }
a  { color: var(--accent-cyan); text-decoration: none; }
hr { border: none; border-top: 1px solid var(--border-subtle); margin: var(--space-lg) 0; }

.label {
    font-family: var(--font-mono);
    font-size: 0.75rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 2px;
    color: var(--accent-cyan);
}
.text-lg { font-size: 1.25rem; }
.text-sm { font-size: 0.875rem; }
.text-xs { font-size: 0.75rem; }
.text-center { text-align: center; }
.text-muted { color: var(--text-muted); }
.text-cyan { color: var(--accent-cyan); }
.text-purple { color: var(--accent-purple); }
.text-green { color: var(--accent-green); }
.text-amber { color: var(--accent-amber); }
.text-red { color: var(--accent-red); }
.text-blue { color: var(--accent-blue); }
.font-bold { font-weight: 700; }
.font-medium { font-weight: 500; }
.font-mono { font-family: var(--font-mono); }

/* ============================================================
   CARDS — Glassmorphism-inspired with accent borders
   ============================================================ */

.card {
    background: var(--bg-surface);
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-md);
    padding: var(--space-xl);
    transition: transform var(--duration) var(--ease-out), box-shadow var(--duration) var(--ease-out);
}
.card:hover {
    transform: translateY(-2px);
    box-shadow: var(--shadow-card);
}

.card-cyan {
    background: var(--bg-surface);
    border: 1px solid var(--border-subtle);
    border-left: 4px solid var(--accent-cyan);
    border-radius: var(--radius-md);
    padding: var(--space-xl);
    transition: transform var(--duration) var(--ease-out), box-shadow var(--duration) var(--ease-out);
}
.card-cyan:hover { transform: translateY(-2px); box-shadow: 0 4px 24px rgba(34, 211, 238, 0.1); }

.card-purple {
    background: var(--bg-surface);
    border: 1px solid var(--border-subtle);
    border-left: 4px solid var(--accent-purple);
    border-radius: var(--radius-md);
    padding: var(--space-xl);
    transition: transform var(--duration) var(--ease-out), box-shadow var(--duration) var(--ease-out);
}
.card-purple:hover { transform: translateY(-2px); box-shadow: 0 4px 24px rgba(167, 139, 250, 0.1); }

.card-green {
    background: var(--bg-surface);
    border: 1px solid var(--border-subtle);
    border-left: 4px solid var(--accent-green);
    border-radius: var(--radius-md);
    padding: var(--space-xl);
    transition: transform var(--duration) var(--ease-out), box-shadow var(--duration) var(--ease-out);
}
.card-green:hover { transform: translateY(-2px); box-shadow: 0 4px 24px rgba(52, 211, 153, 0.1); }

.card-amber {
    background: var(--bg-surface);
    border: 1px solid var(--border-subtle);
    border-left: 4px solid var(--accent-amber);
    border-radius: var(--radius-md);
    padding: var(--space-xl);
    transition: transform var(--duration) var(--ease-out), box-shadow var(--duration) var(--ease-out);
}
.card-amber:hover { transform: translateY(-2px); box-shadow: 0 4px 24px rgba(251, 191, 36, 0.1); }

/* Feature card — gradient icon + content row */
.feature-card {
    display: flex;
    gap: var(--space-lg);
    align-items: center;
    background: var(--bg-surface);
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-md);
    padding: var(--space-xl);
    transition: transform var(--duration) var(--ease-out), box-shadow var(--duration) var(--ease-out);
}
.feature-card:hover { transform: translateY(-2px); box-shadow: var(--shadow-card); }
.feature-card .icon-box {
    width: 48px;
    height: 48px;
    border-radius: var(--radius-sm);
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 1.25rem;
    font-weight: 700;
    color: var(--text-inverted);
    flex-shrink: 0;
}
.feature-card .feature-text { flex: 1; display: flex; flex-direction: column; gap: var(--space-xs); }

/* Gradient backgrounds for icon boxes */
.gradient-cyan   { background: linear-gradient(135deg, #22D3EE, #0891B2); }
.gradient-purple { background: linear-gradient(135deg, #A78BFA, #7C3AED); }
.gradient-green  { background: linear-gradient(135deg, #34D399, #059669); }
.gradient-amber  { background: linear-gradient(135deg, #FBBF24, #D97706); }
.gradient-red    { background: linear-gradient(135deg, #F87171, #DC2626); }
.gradient-blue   { background: linear-gradient(135deg, #60A5FA, #2563EB); }

/* ============================================================
   INTERACTIVE COMPONENTS
   ============================================================ */

/* Accordion / Expandable */
.expandable { border: 1px solid var(--border-subtle); border-radius: var(--radius-md); overflow: hidden; }
.expandable-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: var(--space-md) var(--space-lg);
    background: var(--bg-surface);
    cursor: pointer;
    user-select: none;
    transition: background var(--duration);
}
.expandable-header:hover { background: var(--bg-surface-2); }
.expandable-body {
    padding: var(--space-lg);
    background: var(--bg-inset);
    border-top: 1px solid var(--border-subtle);
}

/* Reveal button */
.reveal-btn {
    display: inline-flex;
    align-items: center;
    gap: var(--space-sm);
    padding: var(--space-sm) var(--space-md);
    background: var(--bg-surface);
    border: 1px solid var(--border-accent);
    border-radius: var(--radius-pill);
    color: var(--accent-cyan);
    font-size: 0.875rem;
    font-weight: 500;
    cursor: pointer;
    transition: all var(--duration) var(--ease-out);
}
.reveal-btn:hover { background: rgba(34, 211, 238, 0.1); transform: scale(1.02); }

/* Tabs */
.tabs { display: flex; gap: var(--space-xs); border-bottom: 1px solid var(--border-subtle); }
.tab {
    padding: var(--space-sm) var(--space-md);
    font-size: 0.875rem;
    font-weight: 500;
    color: var(--text-muted);
    cursor: pointer;
    border-bottom: 2px solid transparent;
    transition: all var(--duration);
}
.tab.active, .tab:hover { color: var(--accent-cyan); border-bottom-color: var(--accent-cyan); }
.tab-panel { padding: var(--space-lg) 0; }

/* ============================================================
   UTILITY CLASSES
   ============================================================ */

/* Lists */
ul, ol { padding-left: 1.5rem; margin: var(--space-sm) 0; }
li { margin-bottom: var(--space-xs); color: var(--text-secondary); }
li::marker { color: var(--accent-cyan); }

/* Flexbox */
.flex { display: flex; }
.flex-col { flex-direction: column; }
.flex-wrap { flex-wrap: wrap; }
.items-center { align-items: center; }
.items-start { align-items: flex-start; }
.justify-between { justify-content: space-between; }
.justify-center { justify-content: center; }
.gap-xs { gap: var(--space-xs); }
.gap-sm { gap: var(--space-sm); }
.gap-md { gap: var(--space-md); }
.gap-lg { gap: var(--space-lg); }
.gap-xl { gap: var(--space-xl); }

/* Spacing */
.mt-sm { margin-top: var(--space-sm); }
.mt-md { margin-top: var(--space-md); }
.mt-lg { margin-top: var(--space-lg); }
.mb-sm { margin-bottom: var(--space-sm); }
.mb-md { margin-bottom: var(--space-md); }
.mb-lg { margin-bottom: var(--space-lg); }
.p-md { padding: var(--space-md); }
.p-lg { padding: var(--space-lg); }
.w-full { width: 100%; }

/* Code */
pre {
    background: var(--bg-inset);
    border: 1px solid var(--border-subtle);
    border-radius: var(--radius-sm);
    padding: var(--space-lg);
    overflow-x: auto;
    font-size: 0.875rem;
}
code {
    font-family: var(--font-mono);
    font-size: 0.9em;
}
:not(pre) > code {
    background: var(--bg-surface-2);
    padding: 0.15em 0.4em;
    border-radius: 4px;
    color: var(--accent-cyan);
}

/* Tables */
table { width: 100%; border-collapse: collapse; }
th {
    text-align: left;
    padding: var(--space-sm) var(--space-md);
    background: var(--bg-surface);
    border-bottom: 1px solid var(--border-subtle);
    font-weight: 600;
    font-size: 0.875rem;
    color: var(--text-primary);
}
td {
    padding: var(--space-sm) var(--space-md);
    border-bottom: 1px solid var(--border-subtle);
    font-size: 0.875rem;
    color: var(--text-secondary);
}
tr:hover td { background: rgba(255, 255, 255, 0.02); }

/* Badges */
.badge {
    display: inline-block;
    padding: 0.15rem 0.6rem;
    border-radius: var(--radius-pill);
    font-size: 0.7rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 1px;
}
.badge-cyan   { background: rgba(34, 211, 238, 0.15); color: var(--accent-cyan); }
.badge-purple { background: rgba(167, 139, 250, 0.15); color: var(--accent-purple); }
.badge-green  { background: rgba(52, 211, 153, 0.15); color: var(--accent-green); }
.badge-amber  { background: rgba(251, 191, 36, 0.15); color: var(--accent-amber); }

/* Divider */
.divider { border-top: 1px solid var(--border-subtle); margin: var(--space-lg) 0; }

/* ============================================================
   ANIMATIONS — Slide entry & micro-interactions
   ============================================================ */

@keyframes fadeInUp {
    from { opacity: 0; transform: translateY(16px); }
    to { opacity: 1; transform: translateY(0); }
}
@keyframes fadeIn {
    from { opacity: 0; }
    to { opacity: 1; }
}
.animate-in > * {
    animation: fadeInUp 0.5s var(--ease-out) both;
}
.animate-in > *:nth-child(1) { animation-delay: 0s; }
.animate-in > *:nth-child(2) { animation-delay: 0.08s; }
.animate-in > *:nth-child(3) { animation-delay: 0.16s; }
.animate-in > *:nth-child(4) { animation-delay: 0.24s; }
.animate-in > *:nth-child(5) { animation-delay: 0.32s; }
.animate-in > *:nth-child(6) { animation-delay: 0.40s; }
.animate-in > *:nth-child(7) { animation-delay: 0.48s; }
.animate-in > *:nth-child(8) { animation-delay: 0.56s; }
"""

# Concise class reference for the prompt (model doesn't need full CSS, just class names + purpose)
CSS_CLASS_REFERENCE = """\
LAYOUT CONTRACTS (pick ONE per slide based on content type):
  .layout-cover       — centered title + subtitle (opening/closing slides)
  .layout-split       — two-column grid; use .col for each side (concept + visual)
  .layout-pillars     — three equal columns (features, comparisons)
  .layout-compare     — two .compare-col side by side (before/after, pros/cons)
  .layout-kpi         — big number hero; use .kpi-number + .kpi-label (stats, metrics)
  .layout-process     — centered flow; use .process-flow > .process-step (pipelines, workflows)
  .layout-matrix      — 2x2 grid (quadrant analysis, categories)
  .layout-list        — vertical title + items (bullet points, checklists)
  .layout-stack       — vertical content flow (default, general purpose)

CARDS (wrap content groups — all have hover lift animation):
  .card               — neutral card with subtle border
  .card-cyan          — cyan left border accent
  .card-purple        — purple left border accent
  .card-green         — green left border accent
  .card-amber         — amber left border accent

FEATURE CARDS (icon + text row):
  <div class="feature-card">
    <div class="icon-box gradient-cyan">1</div>
    <div class="feature-text">
      <h3>Title</h3>
      <p>Description</p>
    </div>
  </div>

GRADIENT BACKGROUNDS (for icon-box, step-icon, or any small element):
  .gradient-cyan / .gradient-purple / .gradient-green
  .gradient-amber / .gradient-red / .gradient-blue

PROCESS FLOW (inside .layout-process):
  <div class="process-flow">
    <div class="process-step">
      <div class="step-icon gradient-cyan">1</div>
      <h4>Step Name</h4>
      <p class="text-sm text-muted">Description</p>
    </div>
    <span class="process-arrow">→</span>
    <!-- more steps... -->
  </div>

INTERACTIVE COMPONENTS:
  Accordion:
    <div class="expandable">
      <div class="expandable-header">Title <span>▼</span></div>
      <div class="expandable-body">Hidden content</div>
    </div>

  Tabs:
    <div class="tabs">
      <div class="tab active">Tab 1</div>
      <div class="tab">Tab 2</div>
    </div>
    <div class="tab-panel">Panel content</div>

  Reveal:
    <button class="reveal-btn">Show Answer</button>

TYPOGRAPHY:
  .label             — uppercase monospace label (e.g., "CONCEPT", "STEP 1")
  .text-lg           — larger emphasis text
  .text-sm / .text-xs — smaller text
  .text-muted        — gray text
  .text-cyan / .text-purple / .text-green / .text-amber / .text-red / .text-blue
  .font-bold / .font-medium / .font-mono

KPI (inside .layout-kpi):
  <span class="kpi-number">98.5%</span>
  <span class="kpi-label">System Uptime</span>

ANIMATION (add to a parent container for staggered child entry):
  .animate-in        — children fade in with staggered delay

BADGES:
  <span class="badge badge-cyan">New</span>
  .badge-cyan / .badge-purple / .badge-green / .badge-amber

LAYOUT UTILITIES:
  .flex / .flex-col / .items-center / .justify-between / .justify-center
  .gap-xs / .gap-sm / .gap-md / .gap-lg / .gap-xl
  .mt-sm / .mt-md / .mt-lg / .mb-sm / .mb-md / .mb-lg

CODE: <pre><code class="language-python">...</code></pre>
TABLES: <table> <th> <td> — styled automatically
DIVIDER: <div class="divider"></div>
SEMANTIC HTML: <h2> <h3> <h4> <p> <ul> <ol> <strong> <em> — all styled
"""
