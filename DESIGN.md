# RetroPlatinas — Design System

Reference for the site's visual language, imported from the Claude Design docs
*RetroPlatina Perfil* (design system + profile screen) and *RetroPlatina Identidade*
(brand identity). The design is dark-first and mobile-first; the source concept is
**platinum** — precious metal + mastering a set (100%).

Tokens live in `tailwind.config.js`; spacing and type use Tailwind's default 4px scale.
Reusable partials live in `templates/components/`. See `CLAUDE.md` → *Frontend* for the
build pipeline.

## Palette ("Platina Quente")

Warm amber-graphite base with a complementary identity: indigo-violet (opposite of the
reference's yellow) on identifiers and orange (opposite of blue) on highlights. Gold stays
for medals, steel-platinum for the mastered state.

| Token | Hex | Use |
| --- | --- | --- |
| `bg` | `#100d09` | page background |
| `surface` | `#181510` | cards |
| `surface2` | `#1e1a13` | nested tiles |
| `elevated` | `#252017` | bar tracks, chips |
| `line` / `line2` | `#302a20` / `#463d2e` | borders (rest / hover) |
| `txt` / `txt-muted` / `txt-faint` | `#ece5d6` / `#a89d87` / `#6d6353` | text ramp |
| `brand` (`dim`/`ink`) | `#6a67e0` (`#35356f`/`#f2f3ff`) | indigo-violet accent |
| `brand2` | `#ef7f2b` | orange secondary highlight |
| `gold` (`dim`) | `#f0c04a` (`#8a6a2c`) | points, unlocked badges |

## Typography

Three system-font roles — **no web fonts are loaded** (deliberate; keeps it fast and
period-appropriate):

- `font-display` — 'Arial Narrow', 'Roboto Condensed', Arial, sans-serif — titles, labels, UI.
- `font-sans` — Arial, Helvetica, sans-serif — body, bio, comments.
- `font-mono` — 'Courier New', Courier, monospace — numbers, points, tags.

## Canonical product states

Each state has its own colour (`state-*` tokens) reused across the whole product:

| State | Token | Meaning |
| --- | --- | --- |
| locked | `state-locked` `#3a342a` | not yet unlocked; desaturated, no glow |
| unlocked | `gold` | solid gold + subtle shimmer on hover |
| hardcore | `state-hardcore` `#e0552f` | red border over gold; no save states |
| softcore | `state-softcore` `#7e93b1` | blue border; valid unlock, lower weight |
| progress | `state-progress` `#d8922f` | amber; set started, not beaten |
| beaten | `state-beaten` `#93aa4e` | green; core set conditions met |
| platinum | `state-platinum` `#c2c9d8` | steel-platinum + glow; 100% hardcore |

`state-*` colour utilities are **safelisted** in `tailwind.config.js` because they're
composed from data (`state='beaten'` → `text-state-beaten`) and can't be found by
scanning the markup.

## Components (`templates/components/`)

Each is a small `{% include ... with ... %}` partial, reused across screens:

| Partial | Args | Used in |
| --- | --- | --- |
| `logo.html` | `variant` (lockup/selo), `size` | header, footer |
| `game-card.html` | `initials, title, meta, state, state_label, pct` | profile (mobile games panel); future game lists |
| `achievement-badge.html` | `state, size, label` | badge states |
| `progress-bar-segmented.html` | `not_pct, beaten_pct, plat_pct, height` | progression by console |
| `console-tag.html` | `label` | progression table |
| `user-line.html` | `initials, name, meta, delta, href` | leaderboards/lists |
| `stat-line.html` | `label, value, sub` | profile stats rail |

## Home landing page

`templates/home.html` is assembled almost entirely from the tokens above; a few small
patterns are written inline (no new partial — Django `{% include %}` has no body slot, so a
one-off box shell isn't worth a file):

- **Module box** — the 2000s-style bordered card with a header bar: `rounded-card border
  border-line bg-surface` over a `bg-surface2` header holding a 3px accent strip
  (`bg-brand`/`bg-gold`/`bg-state-platinum`) + title + optional mono meta. The recurring
  container for every home block.
- **Hero strip** — compact conversion header (`from-brand/5` gradient) with headline, sub,
  honesty chips, dual CTA. One strip, never a full-height hero.
- **Changelog entry** — tag pill (colour per category) + title + body; dateless (real
  highlights only, no invented history).
- **Empty-state card** — dashed border + pulsing `animate-rp-glow` dot + honest line + CTA.
  The fallback for any data block with nothing to show; keeps "new", never "dead".
- **Contribute path** — token icon tile + title + description + link, one per path.

The dynamic blocks (numbers, activity, sets) render placeholder data from
`apps/core/fake_home.py`, same stand-in approach as the profile; delete that module when real
aggregation lands.

## Identity

The **"Medalha RP"** logo is a struck platinum medal: serrated crown, dotted ring,
`RP` monogram, three amber sparks, amber ribbon. All SVG, on the same tokens.

- **Variants** — *Emblema* (with ribbon; achievement screens, sharing), *Selo* (no ribbon;
  header/small), *Monocromático* (single colour stamp). `components/logo.html` ships the
  Selo mark + the horizontal wordmark lockup.
- **Wordmark** — the UI renders **"RetroPlatinas"** (plural, matching the repo). The source
  design's singular "RetroPlatina" wordmark is adapted to the plural. "Platinas" uses the
  platinum gradient.
- **Minimum sizes** — emblem 40px, selo 20px, lockup 130px. Clear space = the disc radius.
- **Favicon** (`static/img/favicon.svg`) — Selo at larger sizes; at 16px it degrades to an
  amber spark inside a platinum coin. Self-contained (its own gradient defs), since an
  external favicon can't reference the document's shared defs.

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

## Deferred behaviours (mobile)

The mobile profile ships a functional responsive layout; a few density refinements from
the design are intentionally deferred:

- Achievement grids become a scrollable strip + "+N" drawer (currently a wrapping grid).
- Progression becomes an accordion (currently a responsive stacking table).
- Completion becomes a sortable table with a "hide completed" toggle (currently a static
  responsive list).
- On the home, the sidebar blocks (open source, how to start) collapse into accordions and the
  main/sidebar blocks interleave (numbers promoted up); currently the home stacks the numbers
  tiles up top and keeps every block expanded in a single column.
