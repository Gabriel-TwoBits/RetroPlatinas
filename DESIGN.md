# RetroPlatinas — Design System

Reference for the site's visual language, imported from the Claude Design docs
*RetroPlatina Perfil* (design system + profile screen) and *RetroPlatina Identidade*
(brand identity). The design is dark-first and mobile-first; the source concept is
**platinum** — precious metal + mastering a set (100%).

Tokens live in `tailwind.config.js`; spacing and type use Tailwind's default 4px scale.
Reusable partials live in `templates/components/`. See `CLAUDE.md` → *Frontend* for the
build pipeline.

## Palette ("Platina Fria")

| Token | Hex | Use |
| --- | --- | --- |
| `bg` | `#0b0e13` | page background |
| `surface` | `#12161d` | cards |
| `surface2` | `#171c25` | nested tiles |
| `elevated` | `#1e242f` | bar tracks, chips |
| `line` / `line2` | `#262d39` / `#39434f` | borders (rest / hover) |
| `txt` / `txt-muted` / `txt-faint` | `#e8ebf1` / `#98a2b3` / `#5c6675` | text ramp |
| `brand` (`dim`/`ink`) | `#34dcc4` (`#1c8f80`/`#05221e`) | teal accent |
| `gold` | `#f2b84b` | points, unlocked badges |

## Typography

Three system-font roles — **no web fonts are loaded** (deliberate; keeps it fast and
period-appropriate):

- `font-display` — Tahoma, Verdana, Geneva, sans-serif — titles, labels, UI.
- `font-sans` — Arial, Helvetica, sans-serif — body, bio, comments.
- `font-mono` — 'Courier New', Courier, monospace — numbers, points, tags.

## Canonical product states

Each state has its own colour (`state-*` tokens) reused across the whole product:

| State | Token | Meaning |
| --- | --- | --- |
| locked | `state-locked` `#3a434f` | not yet unlocked; desaturated, no glow |
| unlocked | `gold` | solid gold + subtle shimmer on hover |
| hardcore | `state-hardcore` `#ff6b57` | red border over gold; no save states |
| softcore | `state-softcore` `#8aa4c8` | blue border; valid unlock, lower weight |
| progress | `state-progress` `#eab04d` | amber; set started, not beaten |
| beaten | `state-beaten` `#48c78e` | green; core set conditions met |
| platinum | `state-platinum` `#b09cff` | violet-platinum + glow; 100% hardcore |

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

## Identity

The **"Medalha RP"** logo is a struck platinum medal: serrated crown, dotted ring,
`RP` monogram, three teal sparks, teal ribbon. All SVG, on the same tokens.

- **Variants** — *Emblema* (with ribbon; achievement screens, sharing), *Selo* (no ribbon;
  header/small), *Monocromático* (single colour stamp). `components/logo.html` ships the
  Selo mark + the horizontal wordmark lockup.
- **Wordmark** — the UI renders **"RetroPlatinas"** (plural, matching the repo). The source
  design's singular "RetroPlatina" wordmark is adapted to the plural. "Platinas" uses the
  platinum gradient.
- **Minimum sizes** — emblem 40px, selo 20px, lockup 130px. Clear space = the disc radius.
- **Favicon** (`static/img/favicon.svg`) — Selo at larger sizes; at 16px it degrades to a
  teal spark inside a platinum coin. Self-contained (its own gradient defs), since an
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
