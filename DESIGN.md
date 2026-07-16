# RetroPlatinas — Design System

Reference for the site's visual language, imported from the Claude Design docs
*RetroPlatina Home* (landing page), *RetroPlatina Perfil* (design system + profile screen)
and *RetroPlatina Identidade* (brand identity). The design is dark-first and mobile-first;
the source concept is **platinum** — precious metal + mastering a set (100%).

The Claude Design project is the source of truth for the visual language; this file records
what ships. Where a source doc contradicts itself, the **rendered mockup wins** — its
embedded code blocks are annotations and go stale.

Tokens live in `tailwind.config.js`; spacing and type use Tailwind's default 4px scale.
Reusable partials live in `templates/components/`. See `CLAUDE.md` → *Frontend* for the
build pipeline.

## Palette ("Teal Platina")

Blue-graphite base with saturated teal on identifiers, CTAs and tabs, and violet supporting
highlights. Gold is reserved for medals and points; cold platinum marks the mastered state.

The source doc explores two other directions — *Platina Quente* (warm amber-graphite with
indigo/orange) and *Violeta Troféu* — and archives both. Platina Quente shipped briefly and
was reverted; don't reintroduce it without changing the design doc first.

| Token | Hex | Use |
| --- | --- | --- |
| `bg` | `#0b0e13` | page background |
| `surface` | `#171c25` | filled cards (game cards, wall bubbles) |
| `surface2` | `#1e2531` | nested tiles, chips |
| `elevated` | `#27303d` | bar tracks, award tiles |
| `line` / `line2` | `#29313d` / `#3b4657` | borders (containers / interactive) |
| `txt` / `txt-muted` / `txt-faint` | `#e6ecf3` / `#97a4b5` / `#5f6b7c` | text ramp |
| `brand` (`dim`/`ink`/`hi`) | `#34dcc4` (`#1c5e56`/`#06201b`/`#7fe9db`) | teal accent; `hi` is link hover |
| `brand2` | `#b09cff` | violet secondary highlight |
| `gold` (`dim`/`deep`) | `#f2b84b` (`#8a6a2c`/`#c98d2e`) | points, unlocked badges; `deep` is the gradient stop |

## Radii

Three tiers, taken from the rendered mockup. The source doc also embeds a `tailwind.config.js`
block claiming `card: 0.75rem` / `tile: 0.625rem` — that block is **stale**; every surface it
actually draws is 3–6px. The mockup's 5px and 6px tiers both land on `chip`: one pixel on a
26px chip is not a distinction worth a token.

| Token | Value | Use |
| --- | --- | --- |
| `rounded-card` | `0.1875rem` (3px) | containers, panels, tables, buttons, wall/user avatars |
| `rounded-tile` | `0.25rem` (4px) | game cards, covers, badges, award tiles, stat tiles, bubbles |
| `rounded-chip` | `0.375rem` (6px) | console tags, achievement icon cells, segmented bars |

`rounded-full` stays on pills and dots; `rounded-sm` (2px) on heat bars, legend swatches and
module accent strips. The 96px identity avatar is a one-off `rounded-[18px]`.

## Typography

Three system-font roles — **no web fonts are loaded** (deliberate; keeps it fast and
period-appropriate):

- `font-display` — 'Arial Narrow', 'Roboto Condensed', Arial, sans-serif — titles, labels, UI.
- `font-sans` — Arial, Helvetica, sans-serif — body, bio, comments.
- `font-mono` — 'Courier New', Courier, monospace — numbers, points, tags.

The logo's `RP` monogram and the deferred console icons use Tahoma — a mark, not a UI role.

## Canonical product states

Each state has its own colour (`state-*` tokens) reused across the whole product:

| State | Token | Meaning |
| --- | --- | --- |
| locked | `state-locked` `#313b49` | not yet unlocked; desaturated, no glow |
| unlocked | `gold` | solid gold + subtle shimmer on hover |
| hardcore | `state-hardcore` `#e0552f` | red border over gold; no save states |
| softcore | `state-softcore` `#7e93b1` | blue border; valid unlock, lower weight |
| progress | `state-progress` `#d8922f` | amber; set started, not beaten |
| beaten | `state-beaten` `#5cc48c` | green; core set conditions met |
| platinum | `state-platinum` `#c2c9d8` | steel-platinum + glow; 100% hardcore |

`state-*` utilities are **safelisted** in `tailwind.config.js` because they're composed from
data (`state='beaten'` → `text-state-beaten`) and can't be found by scanning the markup. The
same applies to `text-`/`bg-` on `brand` and `gold`, which award and bar tones compose.

**Tones are token names, never hex.** Placeholder data ships a `tone`/`bar_tone` key holding a
token name; the template sets one colour class and everything else keys off `currentColor`
(borders, glows, the event-award radial fill). That is why the awards need no per-tone branch —
and why inline `style="color:#…"` must not come back: it silently survives a retheme.

## Components (`templates/components/`)

Each is a small `{% include ... with ... %}` partial, reused across screens:

| Partial | Args | Used in |
| --- | --- | --- |
| `logo.html` | `variant` (lockup/selo), `size` | header, footer |
| `game-card.html` | `initials, title, meta, state, state_label, pct, icons, icons_more` | profile (mobile games panel); future game lists |
| `achievement-badge.html` | `state, size, label` | badge states |
| `progress-bar-segmented.html` | `not_pct, beaten_pct, plat_pct, height` | progression table, mobile console cards |
| `console-tag.html` | `label, variant` (table/default), `tone` | progression table, mobile console cards, home sets |
| `user-line.html` | `initials, name, meta, delta, href` | leaderboards/lists |
| `stat-line.html` | `label, value, sub` | profile stats rail, home numbers |

`game-card.html` renders the doc's **mobile** card (cover 46, title 14, `bg-surface`). The doc's
design-system showcase card is a third variant rendered on no route — not built. The desktop
recent-game card is a genuinely different structure (percent beside the bar, 20-column grid)
with one call site, so it stays inline in `sec-recent-games.html`: `{% include %}` has no body
slot, and a partial per call site is not reuse.

## Profile screen

- **Desktop** — `1fr / 328px`, **rail on the right**, main column first in source order.
  Rail order: awards → stats → heat.
- **Surfaces** — rail cards and tables are **border-only, transparent over `bg`**. Only game
  cards and non-owner wall bubbles are filled. The awards block has no card wrapper at all.
- **Identity banner** — flat on desktop with a rule under it; the brand gradient wash is
  mobile-only.
- **Heat** — intensity is encoded as **bar opacity** (`0.35 + v/max·0.65`), not just height.
  Opacity is formatted to a string in Python: Django localises floats, and a pt-BR `0,74`
  would silently break the inline style.

### Mobile profile

Sticky tabs, one HTMX route per tab (`/users/<username>/panel/<tab>/`) — no client state. Each
tab is its **own** design, not a squeezed desktop:

- **overview** — 2-column compact stat tiles capped at 6, with the social/average rows behind a
  native `<details>` expander, then a 64px heat card (mobile uses a 52px bar span; desktop 74px).
- **games** — game cards carrying a 7-column achievement strip (14 cells) + a `+N` chip.
- **progress** — console cards with the Total row emphasised and its tag in brand, then the
  completion list with a hide-completed pill and a search field.
- **awards** — event awards first (radial-gradient tiles), then a horizontal badge carousel.
- **wall** — the desktop section, made responsive rather than duplicated.

Interactions are native or CSS-only. Nothing here is wired: the page renders placeholder data
from `apps/accounts/fake_profile.py`, so the search field, the hide-completed pill, `+N`,
"see all", "load more" and the wall composer are static — the same convention as the existing
`href="#"` stubs. Delete that module and wire these together when real aggregation lands.

## Home landing page

`templates/home.html` is assembled almost entirely from the tokens above; a few small patterns
are written inline (no new partial — `{% include %}` has no body slot, so a one-off box shell
isn't worth a file):

- **Module box** — the 2000s-style bordered card with a header bar: `rounded-card border
  border-line bg-surface` over a `bg-surface2` header holding a 3px accent strip
  (`bg-brand`/`bg-gold`/`bg-state-platinum`) + title. The recurring container for every block.
- **Hero strip** — compact conversion header, border-only, with headline, sub, honesty chips
  and dual CTA. One strip, never a full-height hero.
- **Changelog entry** — tag pill (colour per category) + title + body.
- **Empty-state card** — dashed border + pulsing `animate-rp-pulse` dot + honest line + CTA.
  The fallback for any data block with nothing to show; keeps "new", never "dead".
- **Contribute path** — token icon tile + title + description + link, one per path.

Column order follows the doc: main is what's new → available sets → how to contribute; the
sidebar is how to start → numbers → activity → open source. Mobile promotes the numbers tiles
directly under the strip. "Online now" shows a pulsing brand dot when anyone is on and a faint
dash when nobody is, so the template branches on data rather than on a pre-baked `"—"`.

Placeholder data lives in `apps/core/fake_home.py`; delete it when real aggregation lands.

## Honesty carve-out

The source docs contain content we deliberately **do not** ship. Structure is imported; these
claims are not:

- **Changelog dates** ("há 2 dias") — we don't publish a history we didn't have.
- **Emulators** — the docs list DuckStation, PCSX-ReDux and RetroArch. Only DuckStation is
  tested, so only DuckStation is listed.
- **Links to routes that don't exist** — "ver todo o feed", "histórico completo", Documentação,
  Fórum, Discord. A link that 404s is worse than an absent one.

The design docs also carry their own annotations — the numbered section headers, the principle
cards, and the trailing `↳ …` notes explaining mobile-vs-desktop decisions. Those address the
reader of the doc, not the user; they never ship.

**Known debt:** `/games/`, `/ranking/` and `/feed/` are linked from the header, footer and the
hero's primary CTA but have no `urls.py` yet, so they 404 today. They predate this carve-out;
removing the hero CTA is a product decision, not a drift fix.

## Identity

The **"Medalha RP"** logo is a struck platinum medal: serrated crown, dotted ring,
`RP` monogram, three amber sparks, amber ribbon. All SVG, on the same tokens.

- **Variants** — *Emblema* (with ribbon; achievement screens, sharing), *Selo* (no ribbon;
  header/small), *Monocromático* (single colour stamp). `components/logo.html` ships the
  Selo mark + the horizontal wordmark lockup.
- **Wordmark** — the UI renders **"RetroPlatinas"** (plural, matching the repo). The source
  design's singular "RetroPlatina" wordmark is adapted to the plural. "Platinas" uses the
  platinum gradient. (The identity doc's prose says the lockup is Tahoma Bold; its markup
  renders `font-display` — the markup wins.)
- **Minimum sizes** — emblem 40px, selo 20px, lockup 130px. Clear space = the disc radius.
- **Favicon** (`static/img/favicon.svg`) — Selo at larger sizes; at 16px it degrades to an
  amber spark inside a platinum coin. Self-contained (its own gradient defs), since an
  external favicon can't reference the document's shared defs.

The logo and favicon are platinum and gold, so they are palette-independent — a retheme of the
brand accent does not touch them. `.rp-hatch` is likewise a warm neutral in every source doc,
including the teal ones; it is artwork placeholder texture, not a brand colour.

### Deferred: branded console-icon system

The identity doc defines a richer console tag than the plain chip shipped here — an SVG
pastille (**never real hardware**) encoding three axes, plus a platinum sheen:

- **Form** — rounded square = console · pill = handheld · straight square = computer ·
  hexagon = arcade.
- **Colour** — hue per manufacturer family (same luminance/chroma): Nintendo `#e5544b`,
  Sony `#4f8ff0`, Sega `#7b6cf0`, Atari `#eab04d`, NEC `#b06ccf`, SNK `#f0803a`,
  Computer `#8aa4c8`, Arcade `#34dcc4`. Fill 16%, border 90%.
- **Text** — 2–4 char abbreviation in Tahoma 700 (≤2 chars @11px, 3 @8.5px, 4 @7px).

A new console is added by defining the three axes. Build this from the identity doc — not
by reverse-engineering the emulator — when the console tag needs upgrading.
