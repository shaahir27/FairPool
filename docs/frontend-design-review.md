# FairPool frontend redesign — 3 November 2026

## Diagnosis and direction

The existing discovery route leads with an AI request form and text-only pool cards.
The cobalt rail, page tint, inset wells and repeated notice bands compete for attention.
The initial production JavaScript is 418.30 kB (133.20 kB gzip), with all workspaces
eagerly imported. These are source/build findings; browser inspection was blocked by
Computer Use's URL-verification restriction and no customer study was conducted here.

Direction: a product-led shopping catalogue. The user's latest brief requests a brighter
palette with readable button states, followed by removal of the dark inset frame around
the main content. The working proposal now uses cerulean navigation/brand fields,
raspberry actions, blue reading surfaces and apricot support surfaces. Main content is
flush beside the sidebar: no rounded inset exposing a darker frame at its top/right edge.
Action fills and link accents have separate semantic roles. This is an implemented trial,
not a user-approved visual result.
No white page background, ornamental glass, fake
discounts, ratings, scarcity, sales figures or payment success. The existing logo and
shopping flow remain recognizable. Authentication retains its established split layout.

The Taste skill dealt `framed-sheet` (seed 637617078). Its separation by one tonal step
informed the initial layout; the inset frame was subsequently removed at the user's request.
White backgrounds are replaced with tinted surfaces. The UI/UX skill's liquid-glass/luxury output was rejected:
it suits neither everyday group shopping nor the loading-performance requirement.

[NN/G's color guidance](https://www.nngroup.com/articles/color-enhance-design/) supports
assigning consistent meaning to colors instead of overwhelming the interface. The
public catalogues of [Back Market](https://www.backmarket.com/en-us),
[IKEA](https://www.ikea.com/us/en/) and [MUJI](https://www.muji.us/) were consulted for
product/category navigation and information hierarchy. Their content was inspected via
web extraction; no claim is made of pixel-level browser analysis or copying their palette.

## Research and component shortlist

These are ten evaluated options, not a measured popularity ranking. Official sources:

| System | Relevant capability | Decision for this pass |
| --- | --- | --- |
| [shadcn/ui](https://ui.shadcn.com/docs) | Editable, composable component source | Use composition approach; preserve existing primitives |
| [Radix](https://www.radix-ui.com/primitives/docs/overview/introduction) | Unstyled accessible behavior | Suitable for future complex overlays; none needed here |
| [React Aria](https://react-aria.adobe.com/) | Accessible and adaptive interactions | Strong future option for complex selection controls |
| [Headless UI](https://headlessui.com/) | Unstyled Tailwind-friendly controls | Existing native controls meet this pass's needs |
| [daisyUI](https://daisyui.com/) | CSS component classes and themes | Avoid competing theme and component conventions |
| [Base UI](https://base-ui.com/) | Composable accessible primitives | Future alternative to Radix, not a second layer now |
| [Mantine](https://mantine.dev/) | Broad React controls and hooks | Migration cost exceeds the controls needed |
| [Material UI](https://mui.com/material-ui/) | Material components | Imposes another visual language |
| [Chakra UI](https://www.chakra-ui.com/) | Accessible component system | Existing Tailwind/tokens already cover foundations |
| [Ant Design](https://ant.design/docs/react/introduce/) | Enterprise application components | Better suited to dense administration than this catalogue |

[Baymard's listing research](https://baymard.com/research-articles/product-listing-information)
supports product imagery and enough attributes to evaluate products without opening
every detail. Apply that to available facts only: identity, variant, condition, seats,
deadline and the fact that price comes after bidding. Illustrations are generic category
art, not photographs or promises of exact appearance.
[Checkout research](https://baymard.com/research-articles/checkout-2024-launch) and
[upfront cost research](https://baymard.com/research-articles/show-shipping-costs-on-product-pages)
support preserving the explicit price breakdown, address reuse, and clear next actions.

## Implementation plan, decided before edits

1. Replace semantic palette roles globally and quiet the shared navigation, controls,
   typography, panel bands, checkout, address book and authentication surfaces.
2. Give discovery a product catalogue with shared lightweight SVG category illustrations,
   a functional local filter, truthful price messaging and quieter request assistance.
3. Carry the same product identity into the lobby, checkout and order detail. Retain
   state-machine-derived timelines, notices, consent and backend decisions.
4. Lazy-load workspace routes with an accessible loading fallback. Keep dependencies
   unchanged and compare production entry size against the baseline.
5. Run the full frontend suite, lint, typecheck/build, source contrast checks and Graphify
   update. Record visual-verification limits honestly; do not claim browser QA passed.

The live shared database is not part of this redesign. Existing uncommitted work by
other agents must be preserved. No commit or deployment is included.

## Verification and limits

- Prior redesign suite: 90 tests passed across 12 files. Existing React Router future-flag
  warnings remain in two test files; no failing tests.
- ESLint and production build/typecheck passed. `git diff --check` passed.
- Production entry JavaScript: 181.61 kB / 59.23 kB gzip, compared with the 418.30 kB /
  133.20 kB gzip baseline. This is entry payload, not total route payload or measured
  end-to-end loading speed. Additional route code downloads when needed.
- Source-token contrast checks passed at 4.5:1 or better for the checked body,
  secondary text, action label, navigation, link and illustration-caption pairs.
  This is not a full rendered accessibility audit.
- Read-only finish review found missing failed-download recovery, missing search-result
  announcements and a stale directional sentence. All three were corrected; tests
  cover filtering, its status announcement and rejected lazy-import recovery.
- Documentation validator: zero errors, one preexisting `/api/v1/nope` warning in
  `docs/progress.md`.
- Graphify AST update completed; SQL extraction remains limited by the missing SQL
  parser. Markdown semantics are not refreshed by this command.
- Browser access was stopped by Computer Use's URL-verification guard. Responsive CSS,
  actual font rendering, zoom, keyboard layout and the perceived palette still require
  visual verification. No screenshots, survey results or customer approval are claimed.

## Bright-palette evaluation and hover correction

Compared three candidate relationships before remapping the theme:

| Candidate | Evaluation |
| --- | --- |
| Cerulean + raspberry + apricot | Selected for this trial: blue navigation, distinct action color, warm supporting surfaces; action-label contrast 5.41:1 normally and 6.74:1 on hover |
| Cobalt + lemon | Text can pass contrast, but large blue/yellow fields repeat the combination already rejected by the user |
| Raspberry + amber + rose | Text can pass contrast, but a dominant pink family offers less separation between brand and supporting surfaces |

This is a task-specific design judgment, not evidence that a palette increases conversion.
[Material color roles](https://m3.material.io/styles/color/the-color-system) and
[Atlassian accent guidance](https://atlassian.design/foundations/color/accents) informed
separate foreground/background roles. [MDN transition guidance](https://developer.mozilla.org/en-US/docs/Web/CSS/Guides/Transitions/Using)
informed explicit, short background transitions with no hover-time text or layout animation.

The actual hover defect was a second desktop rule that replaced the action fill with a
blue mix while retaining dark text. The regression test reproduced 2.0:1 contrast before
the fix. There is now one primary hover fill, with a fixed label color. Fifteen source-color
checks cover button states, transition samples, navigation and content pairs. Authentication
support text and illustration captions were also adjusted after contrast checks; input
border opacity was raised from .6 (2.64:1) to .72 (3.35:1) on the main input surface.

These checks exercise CSS colors and cascade order. Browser frame rate, actual pointer
behavior and rendered palette appearance remain unverified because browser access is unavailable.
Final frontend verification for this pass: 105 tests passed across 13 files; lint and
production typecheck/build passed. No new dependencies, database changes or commit.
