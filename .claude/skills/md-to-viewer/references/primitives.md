# Content primitives

The viewer is **not** a literal Markdown render. Reinterpret the source into these
primitives — they all use classes already styled in `template.html`. Copy a snippet,
fill it with real content, drop it inside a `.commentable` block.

> Color semantics are consistent everywhere: **green** = good / keep / primary,
> **amber** = changed / attention / caution, **red** = removed / blocked / danger,
> **blue** = optional, **steel** = code/deterministic, **violet** = LLM/AI/dynamic.

---

## Structural shell (every section uses these)

### Section + header
One `<section>` per "page" of the doc. `data-name` is the sidebar label; `id` must be unique.

```html
<section class="section" data-name="Short nav label" id="unique-id">
  <div class="shead">
    <div class="idx">02</div>                         <!-- zero-padded order -->
    <div class="meta">
      <div class="kick">eyebrow / category</div>       <!-- lowercase, terse -->
      <h2>Section title</h2>
      <p>One sentence the reader can grasp the whole page from.</p>
    </div>
  </div>
  <!-- commentable blocks go here -->
</section>
```

### Commentable wrapper
Wrap **every** meaningful block (a table, a diagram, a list, a callout cluster). This is
what gets a "＋ note" affordance. `data-anchor` must be **globally unique** in the file;
`data-label` is the human name shown in exports.

```html
<div class="commentable" data-anchor="sec2-flow" data-label="Request flow">
  <h3>Heading inside the block</h3>
  ...content...
</div>
```

`<h3>` renders with a rotated-diamond bullet. Use `<p class="lede">` for a sub-intro line.

---

## Tables (the workhorse)

Markdown tables become semantic tables. Plain text stays text; **values that carry
meaning become `.tag` chips** and **identifiers/keys become `<code>`** (renders green).

```html
<table>
  <tr><th>field</th><th>status</th><th>note</th></tr>
  <tr><td><code>user_id</code></td><td><span class="tag keep">keep</span></td><td>unchanged</td></tr>
  <tr><td><code>legacy</code></td><td><span class="tag drop">drop</span></td><td>removed in v2</td></tr>
</table>
```

Tag variants: `keep` (green) · `swap` (amber) · `drop` (red) · `opt` (blue) ·
`code` (steel) · `llm` (violet). Use `<em>` for parenthetical dim asides inside cells.

---

## Callouts & lists

```html
<!-- bulleted list, house style: bold the term, dim the explanation -->
<ul class="clean">
  <li><b>Derive-don't-emit</b> — code fills the fixed fields so they can't be wrong.</li>
</ul>

<!-- side note; .warn for the one thing not to miss -->
<div class="note"><b>Note:</b> neutral aside, steel left-border.</div>
<div class="note warn"><b>Watch out:</b> amber left-border for the critical caveat.</div>
```

---

## Stat / metric cards
For a row of headline numbers or key/value facts.

```html
<div class="cards">
  <div class="card2"><div class="lab">latency p50</div><div class="big green">42<small> ms</small></div></div>
  <div class="card2"><div class="lab">model</div><div class="big violet">opus</div></div>
  <div class="card2"><div class="lab">cost</div><div class="big red">$0.18</div></div>
</div>
```
`.big` accepts `.green` / `.violet` / `.red`; nest `<small>` for units.

---

## Two-column comparison (`.split`)
For "deterministic vs LLM", "before vs after", "A vs B". `.col.det` = steel/`≡` bullets,
`.col.llm` = violet/`✦` bullets.

```html
<div class="split">
  <div class="col det">
    <div class="ch">Code <span class="pill">deterministic</span></div>
    <ul class="clean"><li>fills fixed fields</li><li>validates picks</li></ul>
  </div>
  <div class="col llm">
    <div class="ch">LLM <span class="pill">judgment</span></div>
    <ul class="clean"><li>chooses card + dose</li><li>one nutrition lever</li></ul>
  </div>
</div>
<!-- optional decision gate below a split -->
<div class="gate"><span class="gt">SAFETY GATE</span><span class="gd">knee_pain &gt; 3 ⇒ block all impact cards.</span></div>
```

---

## System diagram (`.diagram` + `.sys`)
Boxes in columns with labeled arrows between. Box variants: `io` (green), `store`
(steel), `engine`/`agent` (violet), `head` (dashed group label).

```html
<div class="diagram">
  <div class="sys">
    <div class="sys-col">
      <div class="box io"><div class="t">Client</div><small>iOS app</small></div>
    </div>
    <div class="sys-arrows">
      <div class="awrap"><span class="alabel">POST /plan</span><span class="aglyph">→</span></div>
    </div>
    <div class="sys-col wide">
      <div class="box engine"><div class="t">Planner</div><small>LLM + validator</small></div>
      <div class="box store"><div class="t">Postgres</div><small>plans, cards</small></div>
    </div>
  </div>
  <div class="sys-foot">source of truth: CARD_META</div>
</div>
```

---

## Workflow / pipeline (`.flow` + `.node`)
Vertical sequence of steps with arrows. Node variants: `data` (steel), `router` (amber),
`agent` (violet), `opt` (dashed/faded). Use `.branch` for conditional offshoots.

```html
<div class="flow">
  <div class="node data"><span class="nm">ingest</span><span class="ty">DATA</span><span class="nd">profile + readiness</span></div>
  <div class="arrow">↓</div>
  <div class="node router"><span class="nm">route</span><span class="ty">ROUTER</span><span class="nd">RED / AMBER / GREEN</span></div>
  <div class="branch fail">└─ RED → rest only</div>
  <div class="arrow">↓</div>
  <div class="node agent"><span class="nm">plan</span><span class="ty">LLM</span><span class="nd">picks card + dose</span></div>
</div>
```

---

## Code / pseudo-block (`.pre`)
Monospace block with manual syntax coloring. Wrap tokens in spans: `.g` green, `.v`
violet, `.a` amber, `.s` steel, `.d` faint/comment. `white-space:pre`, so format by hand.

```html
<div class="pre"><span class="d">// LLM emits only this</span>
{ <span class="g">"card"</span>: <span class="a">"threshold"</span>, <span class="g">"dose"</span>: <span class="v">40</span> }</div>
```

---

## Mapping cheat-sheet (Markdown → primitive)

| Source Markdown | Becomes |
|---|---|
| `#` / `##` heading that starts a topic | a new `<section>` (`.shead`) |
| `###` / `####` sub-heading | `<h3>` inside a `.commentable` |
| table | styled `<table>`, meaningful values → `.tag`, keys → `<code>` |
| `> blockquote` | `.note` (or `.note.warn` if it warns) |
| bullet list | `ul.clean` |
| "X vs Y" prose or two parallel lists | `.split` |
| numbered steps / a pipeline | `.flow` of `.node`s |
| ASCII/box diagram or "A → B → C" architecture | `.diagram` / `.sys` |
| headline numbers, key metrics | `.cards` / `.card2` |
| fenced code / JSON | `.pre` with hand-applied token spans |
| inline `` `code` `` | `<code>` |
| **bold** lead-in on a list item | `<b>` (renders bright against dim body) |
