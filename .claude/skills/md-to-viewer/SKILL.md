---
name: md-to-viewer
description: "Turn a Markdown document into a single-file, self-contained HTML viewer in a dark blueprint style — paginated sections with a sidebar, plus a built-in comment harness (annotate blocks, export comments to JSON/Markdown for a review loop). Use this when the user asks to turn a .md into HTML, build or regenerate an HTML companion or viewer for a Markdown doc, make a doc commentable or reviewable in the browser, or refresh a generated .html after editing its source .md. The Markdown is the source of truth; the HTML is regenerated from it, not edited by hand."
---

# Markdown → commentable HTML viewer

## What this produces

A **single `.html` file** (no build step, no dependencies beyond Google Fonts) that
presents a Markdown doc as a paginated, navigable viewer with an integrated commenting
system. It is **not** a literal Markdown render — the source is *reinterpreted* into a
vocabulary of styled primitives (semantic tables, callouts, stat cards, system diagrams,
workflow flows, two-column comparisons, syntax-colored code blocks).

Signature features baked into the template:
- **Sidebar + pagination** — one `<section>` per page; sidebar nav, prev/next pager, deep-linkable `#hash`, last-section memory.
- **Comment harness** — toggle comment mode, click any block to add a note, notes persist in `localStorage`. Export all comments to JSON or Markdown, or copy to clipboard. The intended loop: *reader comments → exports the file → drops it beside the source `.md` → tells Claude to read it.*
- **Theming** — dark / light / system (auto) toggle in the sidebar; persists in `localStorage` and follows the OS when set to auto. A head script applies the theme before first paint (no flash). When embedded in a parent index (e.g. an `<iframe>`), the viewer also accepts the parent's theme via a `#t=light|dark` URL hint and `postMessage` — needed because `file://` frames don't share `localStorage`.
- **Keyboard shortcuts** — `←`/`→` (or `[`/`]`) page nav · `T` cycle theme · `C` toggle comment mode.
- **Consistent design system** — themable grid background (dark + light token sets); Archivo / IBM Plex Sans / JetBrains Mono; fixed color semantics (green=good, amber=attention, red=removed, blue=optional, steel=code, violet=LLM).

## Bundled resources

- `assets/template.html` — the complete shell: full CSS design system, sidebar, pager, and the reusable comment/navigation `<script>`. Copy this and fill it in. The script is **config-driven via `<body>` data attributes** — never edit the JS.
- `references/primitives.md` — the catalog of content primitives with copy-paste HTML snippets and a Markdown→primitive mapping cheat-sheet. **Read this before transforming any non-trivial content.**

## Workflow

### 1. Read the source and the conventions
- Read the source `.md` in full.
- Read `references/primitives.md` to load the primitive vocabulary and the mapping cheat-sheet.
- If sibling `.html` viewers already exist next to the source (e.g. other docs in the same folder), open one to match its conventions (section granularity, tag usage, brand strings) — consistency across a doc set matters.

### 2. Decide the doc's identity (fills the `{{...}}` placeholders)
Pick these once per doc:

| Placeholder | What it is | Example |
|---|---|---|
| `{{TITLE}}` | browser tab title | `Coach App · The Pool (Cards)` |
| `{{BRAND_KICK}}` | sidebar eyebrow | `Coach App` |
| `{{BRAND_TITLE}}` | sidebar H1 (a `<br>` is fine) | `The<br>Pool` |
| `{{BRAND_SUB}}` | sidebar sub-line | `v1 · cards · CARD_META` |
| `{{DOC_SLUG}}` | short filename stem; sets export names `<slug>-comments.{json,md}` | `cards` |
| `{{STORAGE_KEY}}` | **globally unique** localStorage key — distinct per doc or comments collide | `coachapp-cards-comments-v1` |
| `{{EXPORT_TITLE}}` | H1 at the top of exported Markdown | `Cards (workout pool) review comments` |

### 3. Plan the sections
Split the source into pages. Each top-level topic (`#`/`##`) is usually one `<section>`;
a long section may split, a few tiny ones may merge. For each, draft: the zero-padded
`idx`, a terse lowercase `kick`, an `h2` title, and a one-line thesis `<p>`. Aim for a
handful of focused sections, not one giant scroll.

### 4. Transform content into primitives
For each section, map the source onto primitives from `references/primitives.md`
(tables→semantic tables with tag chips, blockquotes→`.note`, "X vs Y"→`.split`, steps→
`.flow`, architecture→`.diagram`/`.sys`, metrics→`.card2`, code→`.pre`). Reinterpret for
clarity — collapse redundant prose, surface the structure. Preserve all real information
and identifiers; do not invent facts the source doesn't contain.

### 5. Make every block commentable
Wrap each meaningful block in `<div class="commentable" data-anchor="UNIQUE" data-label="Human label">…</div>`.
- `data-anchor` must be **unique across the whole file** (prefix by section, e.g. `pool-run`, `pool-cardio`).
- `data-label` is the friendly name shown in the comment editor and exports.

### 6. Assemble and write
- Copy `assets/template.html`, fill the `<body>` data attributes and sidebar placeholders, and replace everything between `<!-- SECTIONS:START -->` and `<!-- SECTIONS:END -->` (including the two example sections) with the generated sections.
- Write the result to `<DOC_SLUG>.html` **next to the source `.md`** (matching the sibling naming convention if one exists, e.g. `ARCHITECTURE.md` → `arch.html`).
- Leave the `<script>` block untouched.

### 7. Verify
- Confirm the file is self-contained and well-formed (every `<section>`/`<div>` closed).
- Check that all `data-anchor` values are unique and `{{STORAGE_KEY}}` is unique to this doc.
- Quick check: open it or render with a headless tool if available; otherwise sanity-check structure. Report the path to the user and mention they can open it directly in a browser.

## Regenerating after edits
The `.md` is the source of truth. When it changes, **regenerate the whole `.html`** rather
than hand-patching — keep the same `{{STORAGE_KEY}}` so existing reader comments still
resolve to their anchors. If a commented block is removed or its `data-anchor` changes,
note that those comments will no longer attach.

## Incorporating exported comments
When a user drops a `<slug>-comments.md`/`.json` next to the doc and asks to address
feedback: read it, map each comment's `anchor`/`block` back to the source `.md`, apply the
content changes there, then regenerate the `.html`.
