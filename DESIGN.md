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
   3px accent strip `w-strip` in `brand`/`brand2`/`gold`/`state-platinum`/`state-hardcore`) over a
   `border-line2` hairline. No box, no header bar, no fill.
2. **Rows** — split by `border-t border-line` hairlines, the first row of a list without one
   (`first:border-t-0`; `components/stat-line.html` does it for statistics).
3. **Procedural content** (how to start, how to contribute) — a numbered list behind a left
   rule: `border-l-2 border-brand-dim pl-4`, the step number in `font-data text-brand`.
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
| `brand2` | `#b09cff` | violet secondary highlight; subsets (heading strip, chip, completion seal) |
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

Two families, **self-hosted** from `static/fonts/` (SIL OFL 1.1, licences beside the files) —
no request leaves the site for a font. Variable woff2, weights 400–700, `latin` and `latin-ext`
subsets (Portuguese is in `latin`); the two `latin` files are preloaded in `base.html`.

- [Oxanium](https://github.com/sevmeyer/oxanium) — chamfered, machined letterforms: the platinum
  trophy and the console HUD. Two roles:
  - `font-display` — titles, headings, navigation, tabs, buttons.
  - `font-data` — points, ranks, counts, dates, tags, step numbers. Same face with tabular
    figures (`tnum`), so numbers line up in columns.
- [Atkinson Hyperlegible Next](https://github.com/googlefonts/atkinson-hyperlegible-next) —
  `font-sans`: body, descriptions, bio, comments. Built for legibility at small sizes.

Arial is the fallback of every role while a font loads (`font-display: swap`).

Code — conditions, `settings.ini` snippets, memory addresses, code-note text, revision diffs, hashes —
keeps Tailwind's default `font-mono` (the system monospace): its columns have to align.

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
| beaten | `state-beaten` `#5cc48c` | green; every official progression and win-condition achievement unlocked, any mode |
| platinum | `state-platinum` `#c2c9d8` | steel-platinum; every official achievement of a game's core set unlocked in hardcore |
| subset completed | `brand2` `#b09cff` | violet; every official achievement of a subset unlocked in hardcore |

`state-*` utilities are **safelisted** in `tailwind.config.js` because they're composed from
data (`state='beaten'` → `text-state-beaten`) and can't be found by scanning the markup. The
same applies to `text-`/`bg-` on `brand` (the pattern covers `brand2` too) and `gold`, which
award, seal, bar and heading-strip tones compose.

**Tones are token names, never hex.** View data ships a `tone`/`state` key holding a
token name; the template sets one colour class and the border keys off `currentColor`. Inline
`style="color:#…"` must not come back: it silently survives a retheme.

## Components (`templates/components/`)

Each is a small `{% include ... with ... %}` partial, reused across screens:

| Partial | Args | Used in |
| --- | --- | --- |
| `section-heading.html` | `title, accent` | every section |
| `site-menu.html` | `nav_class, account_class` | header: desktop row and mobile disclosure |
| `form-fields.html` | `form` | login, register, password change, edit profile, comment form |
| `logo.html` | `variant` (lockup/selo), `size` | header, footer |
| `game-card.html` | `initials, title, href, meta, state, state_label, pct, icons, icons_more, subsets` | profile (mobile games panel); future game lists |
| `empty-state.html` | `title, body, href, cta` | every data block with nothing to show (home sets and activity, profile sections, comments) |
| `achievement-badge.html` | `state, size, label` | badge states |
| `progress-bar-segmented.html` | `not_pct, beaten_pct, plat_pct, height` | console progression (desktop and mobile) |
| `console-tag.html` | `label, variant` (table/default), `tone` | console progression, home sets |
| `user-line.html` | `initials, name, meta, delta, href` | leaderboards/lists |
| `stat-line.html` | `label, value, sub` | profile statistics, home numbers, achievement page unlocks |
| `status-chip.html` | `achievement` | game page achievement rows, achievement page header |
| `set-chip.html` | `game` | anything of a subset listed outside its section: leaderboard rows, unlock rows, achievement and leaderboard headers, profile subset rows |
| `set-game-link.html` | `game, link_class` | unlock rows (home, feed, profile), achievement editor header |
| `subset-progress.html` | `subsets` | profile games played (desktop cards and completion, mobile cards and completion) |

Titles go in with an inline translation: `{% include "components/section-heading.html" with
title=_("Recent activity") %}`.

Django renders form widgets without classes, so `.rp-form` (in `static/css/input.css`) styles
the inputs, selects and help lists inside a form, and `form-fields.html` renders labels, help
text and errors around them.

The desktop recent-game card is a genuinely different structure from `game-card.html`
(percent beside the bar, 20-column achievement grid) with one call site, so it stays inline in
`sec-recent-games.html`.

## Sets and subsets

A game is a **core set** (its own 100%) plus any number of **subsets** (`bonus`, `challenge`,
`specialty`, `exclusive`), each a `Game` row under its parent. The site shows a subset only
inside its core game:

- **Where a subset lives** — a subset has no page of its own: `/games/<subset id>/` redirects to
  its section of the core game's page, `/games/<core id>/#set-<subset id>`
  (`Game.get_absolute_url`). Listings (home, games list, profile games played, ranking) hold
  core games only.
- **Order** — the core set, then subsets by type (bonus, challenge, specialty, exclusive), oldest
  first (`site_set_order`).
- **Accent** — the core set keeps `brand`; a subset's heading strip, chip and completion seal are
  `brand2` (violet).
- **Subset chip** (`components/set-chip.html`) — an outlined `brand2` chip, "*Bonus* subset"
  (pt-BR "Subset *Bônus*"), the type in its `title`. Anything of a subset listed away from its
  section names it: the core game's title links the subset's section and the chip follows it
  (`components/set-game-link.html`). A core set carries no chip.
- **Seals** — the **platinum** (`state-platinum`) is the core set's: every official achievement
  of it unlocked in hardcore. A subset with every official achievement unlocked in hardcore
  earns its own **Completed** seal (`brand2`; pt-BR *Concluído*). Neither counts the other.
- **Points** — every set's official achievements score, so points, the ranking and the
  achievements counted on the profile cover subsets too.

## Navigation

- **Desktop (`lg` and up)** — logo, then the nav (Games, Ranking, Feed, Search, How to start, Docs),
  then the account links and the language select, in one sticky row.
- **Below `lg`** — the logo and a native `<details id="site-menu">` disclosure labelled
  *Menu*. Opening it drops a full-width panel under the header with the same nav stacked,
  then the account links and the language select. No JavaScript.
- Both are the same `site-menu.html`, so a link is added once.
- **Notification bell** — for a logged-in user, at the right of the header on every width,
  beside *Menu* below `lg` (see *Notifications*).
- At 380px nothing overflows horizontally; the language select lives in the menu there.
- **Footer** — Games, Ranking, Feed, How to start and Docs.

## Docs

`/docs/` and its pages (`templates/docs/`), listed in navigation order by `DOC_PAGES` in
`apps/core/docs.py`; a slug outside it answers 404. Every page extends `docs/layout.html`.

- **Docs navigation** — `<nav id="docs-nav">`: *Documentation* (the index) over the page list.
  On `lg` and up it is a 224px (`w-56`) column left of the page, the list behind the procedural
  left rule; below `lg` it sits above the page as a wrapped row over a `border-line2` hairline.
  The current entry is `brand` with `aria-current="page"`.
- **Page** — a `max-w-2xl` column: the title, one intro line, then ruled sections. Steps use the
  procedural numbered list; facts and questions are hairline-split rows; code sits in an outlined
  `<pre>`. External links end in ↗ and open in a new tab.
- **Index** — one row per page: its title (linking it) and its one-line summary.
- **Live data** — the getting-started page shows this site's origin as the DuckStation
  `[Cheevos] Host`; the statuses page renders the real status chips; the FAQ lists every
  registered disc hash (game, console, label, MD5) or an empty state.

## Profile screen

`/users/<username>/`, built by `apps/accounts/profile.py` from the shared `apps/core/stats.py`
queries: only official achievements count, a hardcore unlock (which also writes its softcore
twin) counts once per mode, and inactive accounts hold no rank. Points and achievement counts
cover every set; games played are core games, each with the subsets the player started (an
unlock in any mode) inside it.

- **Desktop** — main column (`flex-1`) plus a 320px rail (`w-80`) **on the right**, main column
  first in source order. Main: recently played → recent unlocks → progress by console →
  completion (the last two only once the user has played a game). Rail: platinums & awards →
  statistics → recent progress (heat).
- **Surfaces** — every block is a ruled section on `bg`. Only the recent-game cards are filled;
  award tiles use the hatch placeholder with a 2px `currentColor` border, platinums first, then
  subset seals (`brand2`, linking the subset's section, titled "*game* — *subset* subset ·
  Completed"), then beaten games.
- **Identity banner** — flat, a hairline under it. Identicon, name, bio (escaped, line breaks
  kept) and member since, then the follow control: the follower and following counts (active
  users only) linking the friends page, and the viewer's button — *Follow* (filled `brand`) or
  *Unfollow* (outlined) for another logged-in user, a *Follow* link to log in for a visitor,
  nothing for the owner, and on an inactive profile only an *Unfollow* for whoever already
  follows it. The button posts with HTMX and swaps the whole control
  (`accounts/partials/follow-control.html`), so the follower count follows; a session expired
  meanwhile sends the browser to log in and back to the profile. The owner gets an *Edit profile*
  link. Hardcore and softcore points
  sit side by side split by a vertical hairline, each with its global rank (`#N of M`, M being
  the active users with points in that mode) or *unranked*. Under a hairline, *playing now*
  (a session pinged within `PLAYING_NOW_TTL`, with its rich presence and mode) or, without
  one, the game played last.
- **Recent unlocks** — the last 20, newest first: badge through the `/Badge/` route with a
  hardcore or softcore border, title, game, local date and points.
- **Statistics** — achievements per mode (softcore includes hardcore, subsets included), games
  played, beaten, platinums (core sets), subsets completed, average completion (core sets), then hardcore and softcore points earned in the last 7 days
  and in the last 30 days (a mode counts an achievement when it reaches that mode, so softcore
  counts first unlocks in any mode and leaves out a later hardcore upgrade) and per week since
  joining (softcore includes hardcore).
- **Heat** — 14 days of points earned, today last. Intensity is encoded as **bar opacity**
  (`0.35 + v/max·0.65`), not just height. Opacity is formatted to a string in Python: Django
  localises floats, and a pt-BR `0,74` would silently break the inline style.
- **Empty states** — every list falls back to `empty-state.html`; the owner's version links to
  the getting-started guide.

Completion lists every played game unpaginated, so there is no "load more". Under a game in the
recently played cards, the completion rows and the mobile game cards,
`components/subset-progress.html` lists each subset started behind a `border-line` left rule: its
chip, *n*/*total* and, once completed, *Completed* in `brand2`.

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
login page). It edits the bio (at most `BIO_MAX_LENGTH`, 100 characters, which the help text
states and the textarea's `maxlength` enforces) in the auth-page shape below and returns to the
profile on save.

### Friends page

`/users/<username>/friends/` (`templates/accounts/friends.html`), built by
`apps/accounts/friends.py`; linked from the profile's follower and following counts. Following
is one-way: following someone does not make them follow back.

- **Header** — a ruled section: "*user*'s friends" and a link back to the profile.
- **Lists** — *Following* and *Followers*, two ruled sections side by side from `lg`, stacked
  below. Rows (`accounts/partials/friend-row.html`): identicon, profile link, hardcore and
  softcore points in their state colours; the most recent follow first, active users only,
  unpaginated. Each list falls back to `empty-state.html`.

## Home landing page

`templates/home.html`, built by `apps/core/home.py` from the shared `apps/core/stats.py`
queries: only official achievements count, inactive accounts are left out, and a hardcore
unlock's softcore twin is not counted again.

- **Hero strip** — headline, sub, a `font-data` status line and the dual CTA, over a `border-line2`
  rule. One strip, never a full-height hero.
- **Changelog entry** — a `font-data` category label in its colour + title + body, as a ruled row.
  The new-set entry shows only once a set has an official achievement.
- **Set card** — a game object, so it is filled (`bg-surface`). One per core game with an
  official achievement in its core set, by title: the icon through the `/Images/` route, title,
  console, the core set's official achievements, points and players (active users with points
  who unlocked one of them, as the numbers count players) and, when it has any, how many subsets
  it has (`brand2`); the card links to the game page.
- **Numbers** — games with an official achievement, official achievements, players (active
  users with points) and unlocks, each counted once.
- **Playing now** — sessions pinged within `PLAYING_NOW_TTL`: identicon, user, game, rich
  presence and mode, the first 10 listed and the total under them. Hidden while nobody plays.
- **Recent activity** — the last 8 unlocks site-wide, newest first: badge with a hardcore
  border when earned in hardcore, user, achievement, game (with the subset chip for a subset's
  achievement), console and relative time.
- **Empty state** — a pulsing `animate-rp-pulse` dot + honest line + optional CTA, no box. The
  fallback for sets and activity with nothing to show; keeps "new", never "dead".
- **How to start / How to contribute** — procedural lists behind the left rule.

Column order: main is what's new → available sets → how to contribute; the sidebar is how to
start → numbers → playing now → activity → open source. Below `md` the two columns dissolve
into one list (`display: contents`) and `order-first` lifts **how to start** and **the
numbers** to the top, right under the hero. The how-to-start block is the short version and
links to the full guide.

## Games list

`/games/` (`templates/games/list.html`), built by `apps/games/listing.py` from the shared
`apps/core/stats.py` queries; linked from the nav and the footer as *Games*, from the nav as
*Search* (to the search field, `#game-search`) and from the home hero's *See the games*.

- **Header** — a ruled section: the title and one line saying what is listed by default and
  how to list every game.
- **Filters** — a plain GET form inside `.rp-form`: title search (case-insensitive substring),
  console select, minimum official achievements (a number field, default `1`) and order
  (*Alphabetical*, the default; *Most achievements*; *Most players*, the active users with a
  `PlayerGame` for it). A game with no official achievement has no set to play, so it is
  listed only once the minimum is set to `0`. Unofficial achievements never count. A filter the form rejects
  (unknown console or order, negative or non-numeric minimum, an over-long search) answers 400.
- **Live search** — HTMX upgrades the form: any input (`input changed delay:300ms`) or a submit
  fetches `/games/results/`, the bare results block (`templates/games/partials/results.html`),
  and swaps `#games-results`. The fragment answers with `HX-Replace-Url` set to the matching
  `/games/?…` URL, so the address bar always reloads the full list as shown. It replaces rather
  than pushes: htmx's history snapshot keeps the form's rendered values, not the typed ones, so
  a pushed entry would come back on Back with results under stale filters. Without JavaScript
  a submit button (in `<noscript>`) sends the same form to `/games/`.
- **Cards** — game objects, so filled (`bg-surface`), 24 a page in a 1/2/3-column grid: the
  icon through the `/Images/` route, title, console tag and official achievements; the card
  links to the game page. The section heading counts the matching games.
- **Pages** — as on the leaderboard page, each link carrying the search and filters (the
  query string minus `page`) and swapping `#games-results` through `/games/results/`; a page
  the list does not have answers 404.
- **Empty states** — with a search or filter, *No games match these filters* with a link back
  to the bare list; without one, the home's no-official-sets line.

## Game page

`/games/<id>/` (`templates/games/detail.html`), built by `apps/games/page.py`; an unknown game
answers 404. Every game title on the home, the profile and the games list links here.

- **Header** — a ruled section: the icon through the `/Images/` route (a game object, so it sits
  on `bg-surface`), title, console tag and name, then the core set's official achievements and
  their points side by side split by a vertical hairline, and the description (escaped, line
  breaks kept). Unofficial achievements never count. Outlined buttons under it: *New achievement*
  for a logged-in viewer (the achievement editor), *Code notes*, and *New subset* for staff.
- **Tabs** — underline tabs (`.rp-tab`): *Achievements*, *Leaderboards*, *Recent players*.
  Each loads through HTMX from `/games/<id>/panel/<tab>/`, which answers the tab bar with its
  tab active plus the panel, swapped into `#game-tabs`; the active state is rendered by the
  server, no client script. A subset has no panel route (404).
- **Achievements** — one ruled section per set (`<section id="set-<id>">`, `scroll-mt-20` so the
  sticky header leaves the anchor visible), in site order (see *Sets and subsets*):
  - **Heading** — *Core set* (`brand` strip) or the subset's title (`brand2` strip).
  - **What it is** — one muted line: the core set is the game's own 100%; a bonus subset holds
    challenges taken on while playing normally; a challenge subset, a specific challenge run; a
    specialty or exclusive subset needs a different disc or version (alongside the core set, or
    on its own). A subset's description (escaped) follows.
  - **Totals** — a `font-data` line: the set's official achievements and their points (`gold`).
  - **Progress** — for a logged-in viewer, on a set with official achievements: a bar
    (`state-progress`, or the seal's colour once complete), "*n*/*total* unlocked (*h* hardcore)
    · *pct*%" (floored), and the outlined seal chip when earned: *Platinum* on the core set,
    *Completed* on a subset.
  - **Opt-in** (bonus and challenge subsets) — every subset is off until the player turns it on.
    A logged-in viewer gets an outlined `role="switch"` button, *Play this subset* with an
    *On*/*Off* mark (`brand` border and dot when on), that POSTs `play=on|off` to
    `/games/<subset id>/play/` with HTMX and swaps the control (`games/partials/opt-in.html`);
    without htmx the form returns to the subset's section. A visitor gets *Log in to play this
    subset*, returning to the section. Under it, a faint line: the change applies the next time
    the game is opened in the emulator. Anything other than `on`/`off` answers 400; the core set,
    a specialty or an exclusive subset answers 404.
  - **Disc** (specialty and exclusive subsets) — instead of a switch, the discs it plays from:
    each hash's label and its MD5 in `font-mono`, or a line saying none is linked yet.
  - **New achievement in this subset** — a `brand` link for a logged-in viewer, opening the editor
    with that subset chosen.
  - **Rows** — the set's official achievements in the order the emulator receives them, then its
    unofficial ones collapsed in a native `<details id="unofficial-<id>">` whose summary is
    *Unofficial* in `gold` (pt-BR *Não oficiais*, `achievement section` context) with their count;
    hidden when the set has none. Every row carries an outlined status chip after its title:
    *Official* in `brand`, *Unofficial* in `gold`. For a logged-in viewer an unlocked badge has a
    2px `state-hardcore` or `state-softcore` border with the mode and local date under the
    description; a locked one comes from the `_lock` route, faded, with muted text. An anonymous
    visitor sees the plain badges, no progress and no unlock filters. Each title links to the
    achievement page. Under the points, an *Edit* link in `brand` on the rows the viewer may edit
    (their own, or every row for staff), and a *History* link on every row. A set with nothing
    to show says so (`empty-state.html`).
- **Filters** — logged-in viewers get *All / Unlocked / Locked* outlined chips over the sets, the
  active one in `brand`; each reloads the panel through the same HTMX route (`?filter=`) and
  applies to every set, official and unofficial rows alike. Each set has its own empty state per
  filter.
- **Leaderboards** — a row per leaderboard, the core set's first, then each subset's with its
  subset chip: title (linking to its leaderboard page), description and its entries by active
  users. Scores and ranks belong to the leaderboard page.
- **Recent players** — the 20 active users who played the core game last: identicon, profile
  link, the core set's official achievements unlocked (and how many in hardcore) and when they
  last played.
- **Comments** — under the tabs, the shared comments section (see *Comments*).

### New subset

`/games/<id>/subsets/new/` (`templates/games/subset-new.html`), staff only (another user gets
403, a visitor the login page, a subset 404), in the editor's shape: hairline rows explaining the
four types (the game page's own explanations), then the type, the subset title and an optional description. The subset goes on the
core game's console, titled RA's way (`<game> [Subset - <title>]`); saving returns to its
section. Staff also add subsets inline on the game in the admin; a specialty or exclusive
subset's disc hash is linked there.

## Achievement page

`/games/<id>/achievements/<aid>/` (`templates/achievements/detail.html`), in a `max-w-3xl`
column; every achievement, official or unofficial, has a page anyone opens.

- **Header** — a ruled section: a link back to the game (the core game's title; a subset's
  achievement links its section and carries the subset chip), the badge (a game object, on
  `bg-surface`), the title with its status chip (`components/status-chip.html`, as on the game
  page), a `font-data` line with the points in `gold`, the type when it has one and the author's profile
  link, then the description (escaped, line breaks kept). Outlined buttons under it: *Edit
  achievement* for its author or staff, and *History*.
- **Unlocks** — stat lines: the active users who unlocked it in any mode, those in hardcore, and
  the active users who played the game it is recorded on (the core game for a core, bonus or
  challenge achievement; the subset's own disc for a specialty or exclusive one). An unofficial achievement shows one muted line
  instead: it is never awarded.
- **Comments** — the shared comments section (see *Comments*).

## Comments

`templates/comments/partials/thread.html`, built by `apps/comments/threads.py`, at the bottom of
the game page and of the achievement page, as `<section id="comments">`.

- **Heading** — the comment count as a ruled section heading.
- **Rows** — oldest first, split by hairlines: the author's identicon, profile link and local
  timestamp on a `font-data` line, the content under it (escaped, line breaks kept). Its author and
  staff get a small *Delete* in `danger` at the right of the `font-data` line, which asks to confirm.
  No comments shows the empty state.
- **Form** — for a logged-in viewer, under a `border-line2` rule: the content textarea (at most
  2000 characters) and a filled *Post comment* button. An anonymous visitor gets a *Log in to
  comment* link that returns to the section.
- **HTMX** — adding (`POST …/comments/` on the game or achievement URL) and deleting
  (`POST /comments/<id>/delete/`) answer the whole section, swapped in place of `#comments`; an
  invalid comment comes back with its error in the form. Without htmx loaded, the forms post
  normally and return to the page. An htmx post after the session expired answers `HX-Redirect`
  to the login page, which returns to the section.
- **Moderation** — staff also delete comments in the admin.

## Notifications

The bell (`templates/notifications/partials/bell.html`, rendered by `{% notification_bell %}`)
and `/notifications/` (`templates/notifications/list.html`), built by
`apps/notifications/display.py`. An achievement's author is notified when someone else comments
on it, unlocks it (a player's first unlock only) or changes its status; the message is rendered
in the reader's language when shown, and names the subset of an achievement that is not in a
core set ("… “*achievement*” in the *Bonus* subset …"), stored as the `set` parameter.

- **Bell** — a native `<details id="notification-menu">`: an outlined bell icon with the unread
  count in `font-data` `brand` (none when everything is read). The count polls
  `/notifications/unread/` every `POLL_SECONDS` (60 s); once the session is gone it answers 286
  and htmx stops polling. Opening the bell fetches `/notifications/menu/` (the latest 10) into
  the panel, a ruled section with a *See all notifications* link; full width under the header
  below `lg`, a `w-96` panel under the bell from `lg`.
- **Rows** (`partials/row.html`, shared by the menu and the page) — split by hairlines: a dot
  (`brand` unread, `line` read), the message (`txt` unread, `txt-muted` read) and the relative
  time on a `font-data` line. Each row is a form: posting it to `/notifications/<id>/read/` marks it
  read and opens what it is about.
- **Page** — a ruled header with the title and, when something is unread, an outlined *Mark all
  as read* button (`POST /notifications/read/`); the rows newest first, 50 a page, with the
  ranking's previous/next links. Empty, it shows the empty state.

## Achievement editor

`/games/<id>/achievements/new/` and `/games/<id>/achievements/<aid>/edit/`
(`templates/achievements/edit.html`): the auth-page shape below in a `max-w-2xl` column, the
title over a `border-line2` rule with the game linked under it. Editing shows the author, created
and last-updated times as hairline-split `font-data` rows, then the current badge unlocked and locked
(game objects, on `bg-surface`), then the form: on creation only, the set (*Core set* or one of
the core game's subsets, "*title* (*type* subset)", the game of the URL chosen first; an
achievement stays in its set afterwards), then title, description, points, type, a new badge
upload, the condition (`mem_addr`, checked by the rcheevos parser) and the status. Under the
title, the core game links the game page, and an existing subset achievement carries its chip. Saving returns
to the edit page with the message *Achievement saved.*; *Back to the game* sits under a hairline,
followed, once the achievement exists, by *History*.

## Achievement history

`/games/<id>/achievements/<aid>/history/` (`templates/achievements/history.html`), built by
`apps/achievements/revisions.py`, in a `max-w-3xl` column; visible to anyone.

- **Header** — a ruled section: a link back to the game (with the subset chip, as on the
  achievement page), the title, one muted line on what the
  page lists and, for its author or staff, an outlined *Edit achievement* button.
- **Revisions** — a section headed by the revision count, newest first, rows split by hairlines.
  Each row's `font-data` line carries the number (`#N`, bold `txt`), the local timestamp, the editor's
  profile link in `brand` (or *unknown editor*) and, on the latest revision when the achievement
  still holds it, a `gold` *current* mark. Under it, each changed field's label (uppercase
  `font-display`) over a `font-data` line diff against the revision before: removed lines in `danger`
  prefixed `-`, added ones in `state-beaten` prefixed `+`, kept ones in `txt-faint`. `mem_addr`
  is split one condition per line, alt groups starting a new one; status and type show their
  labels. A row that changed nothing says so.
- **Revert** — a small outlined *Revert to this revision* button (`rounded-tile`) at the right
  of the `font-data` line, POSTing to `…/history/<rid>/revert/`, only on rows the viewer may revert to:
  their author or staff, points they may set in the editor, values other than the
  current ones. Reverting adds a revision and returns to the page with *Achievement reverted.*

## Leaderboard page

`/games/<id>/leaderboards/<lb_id>/` (`templates/leaderboards/detail.html`), built by
`apps/leaderboards/page.py`; an unknown game or leaderboard, a leaderboard of another game and a
page the board does not have answer 404.

- **Header** — a ruled section: a link back to the game (with the subset chip for a subset's
  leaderboard, as on the achievement page), the title, the description, then the entry count and
  whether lower or higher is better.
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
  ranking, ties share it, as on the profile), identicon, profile link, the official
  achievements unlocked in the mode (each once, subsets included), the platinums (core sets with
  every official achievement unlocked in hardcore, in both modes) and the mode's points, earned
  in every set. Only active users with
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

- **Header** — a ruled section: the title and one line saying how many unlocks are listed, whose
  (the site's or the followed players') and how often they refresh.
- **Filter** — *All* (`/feed/`, the default) and *Friends* (`/feed/?filter=friends`) outlined
  chips, the active one in `brand` (`aria-current`). *Friends* lists only the unlocks of the
  active users the viewer follows and needs a session: a visitor is sent to log in and back. An
  unknown filter answers 400. Empty, *Friends* links the ranking to find players to follow.
- **Rows** — the last 50 unlocks of official achievements by active users, newest first, each
  once (a hardcore unlock's softcore twin is left out, an earlier softcore unlock of the same
  achievement is its own row): identicon, "*user* unlocked “*achievement*” in *game*" (profile
  and game page links; a subset's achievement links its section, followed by the subset chip),
  console, relative time and the badge; an unlock earned in hardcore
  carries a *hardcore* mark and a `state-hardcore` badge border (`line2` otherwise). Empty, it
  shows the home's no-unlocks empty state.
- **Polling** — a wrapper around the list polls `/feed/list/` (carrying the filter) every
  `POLL_SECONDS` (30 s, `hx-trigger="every 30s"`) and swaps its contents; the fragment
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
- **Links to routes that don't exist** — "histórico completo", "see all",
  Fórum, Discord. A link that 404s is worse than an absent one.

The design docs also carry their own annotations — the numbered section headers, the principle
cards, and the trailing `↳ …` notes explaining mobile-vs-desktop decisions. Those address the
reader of the doc, not the user; they never ship.

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
