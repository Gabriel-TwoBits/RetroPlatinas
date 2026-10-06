# RetroPlatinas — Design System

Reference for the site's visual language. It started from the Claude Design docs
*RetroPlatina Home* (landing page), *RetroPlatina Perfil* (design system + profile screen)
and *RetroPlatina Identidade* (brand identity), then was flattened into **ruled sections**
after design review: the filled, tinted, glowing boxes of the source read as a generic
template. The design is dark-first and mobile-first; the source concept is **platinum** —
precious metal + mastering a set (100%).

This file records what ships and wins over the source docs wherever they disagree.

Tokens live in `tailwind.config.js`; spacing and type use Tailwind's default 4px scale, and
markup uses tokens and the default scale only — no arbitrary `[…]` values. Reusable partials
live in `templates/components/`. See `CLAUDE.md` → *Frontend* for the build pipeline.

## Ruled sections

The one layout rule every screen follows:

1. **Section** — a heading (`components/section-heading.html`: `font-display` 14px semibold,
   3px accent strip `w-strip` in `brand`/`gold`/`state-platinum`/`state-hardcore`) over a
   `border-line2` hairline. No box, no header bar, no fill.
2. **Rows** — split by `border-t border-line` hairlines, the first row of a list without one
   (`first:border-t-0`; `components/stat-line.html` does it for statistics).
3. **Procedural content** (how to start, how to contribute) — a numbered list behind a left
   rule: `border-l-2 border-brand-dim pl-4`, the step number in `font-mono text-brand`.
4. **Fill only on game objects** — game cards, covers and award tiles keep `bg-surface`
   (or the `.rp-hatch` artwork placeholder). Everything else sits on `bg`.
5. **Flat** — no glows (`shadow-[…]`), radial fills, gradients or tinted washes. One flat
   token colour plus at most a 1px border. The only exception is identity art: the logo SVG
   and the wordmark gradient (`wordmark-hi` → `wordmark-lo`), see *Identity*.
6. **No top-right descriptions** — a section heading carries no caption, count or legend to
   its right. Only an actionable link that goes somewhere real may sit there.
7. **No sections without a concept** — a block ships only when the roadmap defines what it
   means. Event awards, the user wall, forum posts, sets requested, RetroRatio, weighted
   points, the retail/hack split, "suggest the next game" and "NEW" badges are hidden until
   they exist.

## Palette ("Teal Platina")

Blue-graphite base with saturated teal on identifiers, CTAs and tabs, and violet supporting
highlights. Gold is reserved for medals and points; cold platinum marks the mastered state.

The source doc explores two other directions — *Platina Quente* (warm amber-graphite with
indigo/orange) and *Violeta Troféu* — and archives both. Neither ships.

| Token | Hex | Use |
| --- | --- | --- |
| `bg` | `#0b0e13` | page background; also the dropdown and input background |
| `surface` | `#171c25` | game objects only (game cards, set cards) |
| `surface2` | `#1e2531` | placeholder image fill (`apps/images/rendering.py`) |
| `elevated` | `#27303d` | bar tracks |
| `line` / `line2` | `#29313d` / `#3b4657` | hairlines between rows / under headings and around controls |
| `txt` / `txt-muted` / `txt-faint` | `#e6ecf3` / `#97a4b5` / `#5f6b7c` | text ramp |
| `brand` (`dim`/`ink`/`hi`) | `#34dcc4` (`#1c5e56`/`#06201b`/`#7fe9db`) | teal accent; `dim` is the procedural left rule, `hi` is link hover |
| `brand2` | `#b09cff` | violet secondary highlight |
| `gold` (`dim`) | `#f2b84b` (`#8a6a2c`) | points, unlocked achievements |
| `danger` | `#e0552f` | form errors |

## Radii

| Token | Value | Use |
| --- | --- | --- |
| `rounded-card` | `0.1875rem` (3px) | game cards, buttons, inputs, code blocks |
| `rounded-tile` | `0.25rem` (4px) | covers, badges, award tiles, primary CTAs |
| `rounded-chip` | `0.375rem` (6px) | console tags, achievement cells, segmented bars |

`rounded-full` stays on dots and progress-bar tracks; `rounded-sm` (2px) on heat bars and
section accent strips. The 80px identity avatar (the identicon from `/UserPic/<username>.png`)
uses `rounded-2xl`.

## Typography

Three system-font roles — **no web fonts are loaded** (deliberate; keeps it fast and
period-appropriate):

- `font-display` — 'Arial Narrow', 'Roboto Condensed', Arial, sans-serif — titles, labels, UI.
- `font-sans` — Arial, Helvetica, sans-serif — body, bio, comments.
- `font-mono` — 'Courier New', Courier, monospace — numbers, points, tags, step numbers.

The smallest size is `text-xs` (12px); the source's 9–11px micro-labels are gone. The logo's
`RP` monogram and the deferred console icons use Tahoma — a mark, not a UI role.

## Canonical product states

Each state has its own colour (`state-*` tokens) reused across the whole product:

| State | Token | Meaning |
| --- | --- | --- |
| locked | `state-locked` `#313b49` | not yet unlocked; outlined, faded |
| unlocked | `gold` | flat gold |
| hardcore | `state-hardcore` `#e0552f` | red border over gold; no save states |
| softcore | `state-softcore` `#7e93b1` | blue border; valid unlock, same points |
| progress | `state-progress` `#d8922f` | amber; set started, not beaten |
| beaten | `state-beaten` `#5cc48c` | green; every published progression and win-condition achievement unlocked, any mode |
| platinum | `state-platinum` `#c2c9d8` | steel-platinum; every published achievement unlocked in hardcore |

`state-*` utilities are **safelisted** in `tailwind.config.js` because they're composed from
data (`state='beaten'` → `text-state-beaten`) and can't be found by scanning the markup. The
same applies to `text-`/`bg-` on `brand` and `gold`, which award, bar and heading-strip tones
compose.

**Tones are token names, never hex.** View data ships a `tone`/`state` key holding a
token name; the template sets one colour class and the border keys off `currentColor`. Inline
`style="color:#…"` must not come back: it silently survives a retheme.

## Components (`templates/components/`)

Each is a small `{% include ... with ... %}` partial, reused across screens:

| Partial | Args | Used in |
| --- | --- | --- |
| `section-heading.html` | `title, accent` | every section |
| `site-menu.html` | `nav_class, account_class` | header: desktop row and mobile disclosure |
| `form-fields.html` | `form` | login, register, password change, edit profile |
| `logo.html` | `variant` (lockup/selo), `size` | header, footer |
| `game-card.html` | `initials, title, href, meta, state, state_label, pct, icons, icons_more` | profile (mobile games panel); future game lists |
| `empty-state.html` | `title, body, href, cta` | every data block with nothing to show (home sets and activity, profile sections) |
| `achievement-badge.html` | `state, size, label` | badge states |
| `progress-bar-segmented.html` | `not_pct, beaten_pct, plat_pct, height` | console progression (desktop and mobile) |
| `console-tag.html` | `label, variant` (table/default), `tone` | console progression, home sets |
| `user-line.html` | `initials, name, meta, delta, href` | leaderboards/lists |
| `stat-line.html` | `label, value, sub` | profile statistics, home numbers |

Titles go in with an inline translation: `{% include "components/section-heading.html" with
title=_("Recent activity") %}`.

Django renders form widgets without classes, so `.rp-form` (in `static/css/input.css`) styles
the inputs and help lists inside a form, and `form-fields.html` renders labels, help text and
errors around them.

The desktop recent-game card is a genuinely different structure from `game-card.html`
(percent beside the bar, 20-column achievement grid) with one call site, so it stays inline in
`sec-recent-games.html`.

## Navigation

- **Desktop (`lg` and up)** — logo, then the nav (Games, Ranking, Feed, Search, How to start),
  then the account links and the language select, in one sticky row.
- **Below `lg`** — the logo and a native `<details id="site-menu">` disclosure labelled
  *Menu*. Opening it drops a full-width panel under the header with the same nav stacked,
  then the account links and the language select. No JavaScript.
- Both are the same `site-menu.html`, so a link is added once.
- At 380px nothing overflows horizontally; the language select lives in the menu there.

## Profile screen

`/users/<username>/`, built by `apps/accounts/profile.py` from the shared `apps/core/stats.py`
queries: only published achievements count, a hardcore unlock (which also writes its softcore
twin) counts once per mode, and inactive accounts hold no rank.

- **Desktop** — main column (`flex-1`) plus a 320px rail (`w-80`) **on the right**, main column
  first in source order. Main: recently played → recent unlocks → progress by console →
  completion (the last two only once the user has played a game). Rail: platinums & awards →
  statistics → recent progress (heat).
- **Surfaces** — every block is a ruled section on `bg`. Only the recent-game cards are filled;
  award tiles use the hatch placeholder with a 2px `currentColor` border, platinums first, then
  beaten games.
- **Identity banner** — flat, a hairline under it. Identicon, name, bio (escaped, line breaks
  kept) and member since; the owner gets an *Edit profile* link. Hardcore and softcore points
  sit side by side split by a vertical hairline, each with its global rank (`#N of M`, M being
  the active users with points in that mode) or *unranked*. Under a hairline, *playing now*
  (a session pinged within `PLAYING_NOW_TTL`, with its rich presence and mode) or, without
  one, the game played last.
- **Recent unlocks** — the last 20, newest first: badge through the `/Badge/` route with a
  hardcore or softcore border, title, game, local date and points.
- **Statistics** — achievements per mode (softcore includes hardcore), games played, beaten,
  platinums, average completion, points earned in the last 7 and 30 days and per week since
  joining.
- **Heat** — 14 days of points earned, today last. Intensity is encoded as **bar opacity**
  (`0.35 + v/max·0.65`), not just height. Opacity is formatted to a string in Python: Django
  localises floats, and a pt-BR `0,74` would silently break the inline style.
- **Empty states** — every list falls back to `empty-state.html`; the owner's version links to
  the getting-started guide.

Completion lists every played game unpaginated, so there is no "load more".

### Mobile profile

Sticky underline tabs, one HTMX route per tab (`/users/<username>/panel/<tab>/`) — no client
state beyond the active underline. Order: **overview → awards → games → progress**.

- **overview** — the statistics rows (the desktop section, reused), a 64px heat strip, then
  the recent unlocks.
- **awards** — platinums first, then beaten games, as a horizontal tile carousel.
- **games** — game cards carrying a 7-column achievement strip (14 cells) + a `+N` count.
- **progress** — console rows with the Total row emphasised and its tag in brand, then the
  completion rows.

### Edit profile

`/users/<username>/edit/`, the owner only (another user gets 403, an anonymous visitor the
login page). It edits the bio (`BIO_MAX_LENGTH` characters) in the auth-page shape below and
returns to the profile on save.

## Home landing page

`templates/home.html`, built by `apps/core/home.py` from the shared `apps/core/stats.py`
queries: only published achievements count, inactive accounts are left out, and a hardcore
unlock's softcore twin is not counted again.

- **Hero strip** — headline, sub, a mono status line and the dual CTA, over a `border-line2`
  rule. One strip, never a full-height hero.
- **Changelog entry** — a mono category label in its colour + title + body, as a ruled row.
  The new-set entry shows only once a set is published.
- **Set card** — a game object, so it is filled (`bg-surface`). One per game with a published
  achievement, by title: the icon through the `/Images/` route, title, console, published
  achievements, points and players (active users with points who unlocked one of them, as the
  numbers count players); the card links to the game page.
- **Numbers** — games with a published achievement, published achievements, players (active
  users with points) and unlocks, each counted once.
- **Playing now** — sessions pinged within `PLAYING_NOW_TTL`: identicon, user, game, rich
  presence and mode, the first 10 listed and the total under them. Hidden while nobody plays.
- **Recent activity** — the last 8 unlocks site-wide, newest first: badge with a hardcore
  border when earned in hardcore, user, achievement, game, console and relative time.
- **Empty state** — a pulsing `animate-rp-pulse` dot + honest line + optional CTA, no box. The
  fallback for sets and activity with nothing to show; keeps "new", never "dead".
- **How to start / How to contribute** — procedural lists behind the left rule.

Column order: main is what's new → available sets → how to contribute; the sidebar is how to
start → numbers → playing now → activity → open source. Below `md` the two columns dissolve
into one list (`display: contents`) and `order-first` lifts **how to start** and **the
numbers** to the top, right under the hero. The how-to-start block is the short version and
links to the full guide.

## Game page

`/games/<id>/` (`templates/games/detail.html`), built by `apps/games/page.py`; an unknown game
answers 404. Every game title on the home and the profile links here.

- **Header** — a ruled section: the icon through the `/Images/` route (a game object, so it sits
  on `bg-surface`), title, console tag and name, then the published achievements and their
  points side by side split by a vertical hairline, and the description (escaped, line breaks
  kept). Drafts never count.
- **Tabs** — underline tabs (`.rp-tab`): *Achievements*, *Leaderboards*, *Recent players*.
  Each loads through HTMX from `/games/<id>/panel/<tab>/`, which answers the tab bar with its
  tab active plus the panel, swapped into `#game-tabs`; the active state is rendered by the
  server, no client script.
- **Achievements** — ruled sections in the order the emulator receives them: *Verified* (the
  quality seal, `state-platinum` strip), then *Community*, then *Your drafts* (`gold` strip,
  each row marked *draft*), which only the drafts' author sees. A group with nothing to show is
  hidden. For a logged-in viewer an unlocked badge has a 2px `state-hardcore` or
  `state-softcore` border with the mode and local date under the description; a locked one
  comes from the `_lock` route, faded, with muted text. An anonymous visitor sees the plain
  badges and no filters.
- **Filters** — logged-in viewers get *All / Unlocked / Locked* outlined chips over the list,
  the active one in `brand`; each reloads the achievements panel through the same HTMX route
  (`?filter=`). Each filter has its own empty state, except on a game with no achievements the
  viewer can see, where every filter shows the no-achievements one.
- **Leaderboards** — a row per leaderboard: title (linking to its leaderboard page),
  description and its entries by active users. Scores and ranks belong to the leaderboard page.
- **Recent players** — the 20 active users who played last: identicon, profile link, published
  achievements unlocked (and how many in hardcore) and when they last played.

## Leaderboard page

`/games/<id>/leaderboards/<lb_id>/` (`templates/leaderboards/detail.html`), built by
`apps/leaderboards/page.py`; an unknown game or leaderboard, a leaderboard of another game and a
page the board does not have answer 404.

- **Header** — a ruled section: a link back to the game, the title, the description, then the
  entry count and whether lower or higher is better.
- **Your position** — a logged-in viewer whose entry is not on the current page gets it in its
  own section above the board, with its rank on the whole board.
- **Ranking** — 100 entries a page, best first, from active users only: rank (ties share it),
  identicon, profile link, submission date and the score. The viewer's own row carries a 2px
  `brand` left rule, a `brand` name and a *you* mark (`aria-current`).
- **Scores** — rendered exactly as rcheevos renders them in the emulator, by the leaderboard's
  format: `apps/leaderboards/formatting.py` ports `rc_format_value`, exposed to templates as
  `{{ score|leaderboard_score:format }}` (`{% load leaderboard_scores %}`). TIME/FRAMES is frames
  at 60 fps (`5000` → `1:23.33`), and grouping uses commas whatever the language, as in the
  emulator. `scripts/format-score.sh` runs the vendored C so the tests compare against it.
- **Pages** — *Previous* / *Page N of M* / *Next* under a hairline, only when there is more than
  one page. Each link is a plain `?page=N` link that HTMX upgrades: it fetches the page, swaps
  `#leaderboard-board` out of it (`hx-select`) and pushes the URL.

## Ranking page

`/ranking/` (`templates/accounts/ranking.html`), built by `apps/accounts/ranking.py` from the
shared `apps/core/stats.py` queries; linked from the nav and the footer as *Ranking*.

- **Header** — a ruled section: the title and one line saying what ranks players and how often
  the board refreshes.
- **Modes** — *Hardcore* (the default) and *Softcore* outlined chips, the active one in `brand`
  (`aria-current`). Each is a plain `?mode=` link that HTMX upgrades: it fetches the page, swaps
  `#ranking-board` out of it (`hx-select`) and pushes the URL. An unknown mode answers 400.
- **Board** — a section headed *Hardcore points* (`state-hardcore` strip) or *Softcore points*
  (`state-softcore`), the count of ranked players, then 100 rows a page: rank (competition
  ranking, ties share it, as on the profile), identicon, profile link, the published
  achievements unlocked in the mode (each once), the platinums (games with every published
  achievement unlocked in hardcore, in both modes) and the mode's points. Only active users with
  points in the mode are ranked.
- **Pages** — as on the leaderboard page, each link carrying the mode; a page the ranking does
  not have answers 404.
- **Cache** — the board (`templates/accounts/partials/ranking-board.html`) is rendered without
  the request and cached for `BOARD_CACHE_MINUTES` per mode, page and language, so every viewer
  shares it; the header around it, which shows the logged-in user, is rendered per request. The
  board must never read the request or the user.

## Feed page

`/feed/` (`templates/feed/feed.html`), built by `apps/core/feed.py` from the shared
`apps/core/stats.py` queries; linked from the nav and the footer as *Feed*.

- **Header** — a ruled section: the title and one line saying how many unlocks are listed and
  how often they refresh.
- **Filter** — *All* (active, `brand`, `aria-current`) and *Friends* outlined chips. *Friends* is
  disabled (`aria-disabled`, faint, no link) with a note under the chips until following exists.
- **Rows** — the last 50 unlocks of published achievements by active users, newest first, each
  once (a hardcore unlock's softcore twin is left out, an earlier softcore unlock of the same
  achievement is its own row): identicon, "*user* unlocked “*achievement*” in *game*" (profile
  and game page links), console, relative time and the badge; an unlock earned in hardcore
  carries a *hardcore* mark and a `state-hardcore` badge border (`line2` otherwise). Empty, it
  shows the home's no-unlocks empty state.
- **Polling** — a wrapper around the list polls `/feed/list/` every `POLL_SECONDS` (30 s,
  `hx-trigger="every 30s"`) and swaps its contents; the fragment
  (`templates/feed/partials/feed-list.html`) is the bare list, so the trigger stays on the
  wrapper. Nothing is cached: the relative times must stay current.

## Getting started page

`/docs/getting-started/` (`templates/docs/getting-started.html`), linked from the nav as
*How to start* and from the home block. A single column (`max-w-2xl`): title and intro, then
the five steps as a procedural list (create an account, get DuckStation, set `[Cheevos] Host`
in `settings.ini` — the snippet shows this site's own origin —, log in through the GUI, play),
then a short hardcore section. Every string is translatable.

## Auth pages

Login, register, password change and edit profile share one shape: a `max-w-sm` column, the
title over a `border-line2` rule, `form-fields.html` inside `.rp-form`, a full-width brand
button, and the alternate action under a hairline.

## Honesty carve-out

The source docs contain content we deliberately **do not** ship. Structure is imported; these
claims are not:

- **Changelog dates** ("há 2 dias") — we don't publish a history we didn't have.
- **Emulators** — the docs list DuckStation, PCSX-ReDux and RetroArch. Only DuckStation is
  tested, so only DuckStation is listed.
- **Links to routes that don't exist** — "ver todo o feed", "histórico completo", "see all",
  Fórum, Discord. A link that 404s is worse than an absent one.

The design docs also carry their own annotations — the numbered section headers, the principle
cards, and the trailing `↳ …` notes explaining mobile-vs-desktop decisions. Those address the
reader of the doc, not the user; they never ship.

**Known debt:** `/games/` is linked from the header, footer and the hero's secondary CTA but
has no `urls.py` yet, so it 404s today. They predate this carve-out;
removing them is a product decision, not a drift fix.

## Identity

The **"Medalha RP"** logo is a struck platinum medal: serrated crown, dotted ring,
`RP` monogram, three amber sparks, amber ribbon. All SVG, on the same tokens.

- **Variants** — *Emblema* (with ribbon; achievement screens, sharing), *Selo* (no ribbon;
  header/small), *Monocromático* (single colour stamp). `components/logo.html` ships the
  Selo mark + the horizontal wordmark lockup.
- **Wordmark** — the UI renders **"RetroPlatinas"** (plural, matching the repo). The source
  design's singular "RetroPlatina" wordmark is adapted to the plural. "Platinas" uses the
  platinum gradient (`from-wordmark-hi to-wordmark-lo`), the one gradient outside the logo SVG. (The identity doc's prose says the lockup is Tahoma Bold; its markup
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
