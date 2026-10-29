# Current frontend UI quality review

Reviewed 2026-10-29 against the current workspace code, using Impeccable critique,
polish, audit, and document/extract. This review does not cover the Figma designs.

## Scope and method

The running SvelteKit application was inspected in visible Chrome at 320, 390,
768, and 1440px, including English/Chinese and light/dark states. API data came
from existing browser-test fixtures, updated locally to match the current
Collection and DocumentProfile response shapes. No backend analysis or remote writes were performed.

The user approved two independent reviewers. Both agents failed with service
HTTP 403, so the assessment continued in one context. The human-facing critique
was written before reading detector results. Scores are subjective heuristics,
not measured usability or accessibility certification.

Concrete scenario: a materials researcher enters an LPBF 316L collection,
inspects its papers, opens a heat-treatment Objective, compares published tensile
results (580 and 620 MPa), and inspects a Finding and its exact Source. A failed
analysis retry must retain the prior published results. Collection defines the
workspace; files define available material; Objective defines the question and
selected scope; Finding states an evidence-backed result; Source supports audit.
This review changes presentation and keyboard behavior, not that scientific chain.

## Critique and applied polish

| Heuristic (0–4) | Before | After | Evidence |
|---|---:|---:|---|
| Status visibility | 3 | 3 | Processing/failure labels and published-version context remain |
| Match to research work | 3 | 3 | Explicit scope, experiment comparisons, and Source paths remain |
| User control | 2 | 3 | Native modal blocks background focus; Escape restores focus |
| Consistency | 2 | 3 | Shared focus, active route treatment, and semantic theme tokens |
| Error prevention | 3 | 3 | No change to scope approval or write contracts |
| Recognition | 2 | 3 | Four direct destinations; secondary routes grouped under More |
| Efficiency | 1 | 2 | Removed inactive shortcut/search; compact Objective context |
| Visual hierarchy | 2 | 3 | Removed decorative grid, duplicate labels and prominent future cards |
| Recovery | 3 | 3 | Published Finding survives a failed rerun |
| Help and guidance | 2 | 2 | Existing guidance; no new onboarding tested |
| Total | 23/40 | 28/40 | Single-reviewer assessment of the inspected surfaces |

The A2 mark and blue/slate palette remain. Dark mode now makes the monochrome
mark visible. Primary button text uses the shared `--on-brand` token. Existing
undefined color variables in experimental results and Objective scope were
replaced with defined semantic tokens. Future capability cards remain available
in a collapsed disclosure. Nonfunctional global search, notification and account
menu controls were removed; functioning local search and logout remain.

## Technical audit

| Priority | Finding | Outcome |
|---|---|---|
| High | Unnamed custom modal permitted background interaction | Native dialog with heading, inert background and verified focus restoration |
| High | Faint keyboard focus and color-only route state | Solid outlines, underlined active link and `aria-current` |
| Medium | Home cards clipped actions at 320px | Cards shrink and wrap actions; regression passes |
| Medium | Seven equal navigation destinations crowded mobile layouts | Primary four plus More; compact Objective context |
| Medium | Chinese UI retained English document language | Language subscription now updates `html[lang]` |
| Medium | Undefined table/scope colors and dark logo visibility | Existing tokens reused; theme-aware foreground and logo treatment |
| Medium | Large conversation bundle loads in the document workspace | Recorded below; route/lifecycle changes deferred |
| Medium | Current Collection contract migration leaves type/fixture mismatches | Recorded in verification; no compatibility layer added |

The static detector fell from 15 to 13 suggestions: the grid and one progress
accent were removed. Remaining suggestions concern thick side borders in
Evidence Map, chat, Source highlighting, evaluation, and the Objective detail
status banner. Some encode quotes or selected evidence; they need contextual
review, not automatic deletion. They are not WCAG findings.

Touch targets below 44px are an improvement opportunity, not automatically an
AA failure; WCAG 2.2 AA has a 24px minimum with exceptions. Wide comparison tables
use intentional local scrolling. Dark button contrast was evaluated after the
existing transition settled; the transient light-background sample was rejected.
A complete screen-reader, touch-device, zoom and contrast audit remains unrun.

## Performance evidence

Production build succeeds. The bundle manifest identifies ResearchConversation
at about 532 kB minified / 173 kB gzip; PDF.js is about 470 kB / 143 kB gzip, with a
2.36 MB worker. PDF.js and its worker are dynamic entries. The inspected home,
Finding and document-list loads did not fetch either PDF resource.

A local production-preview sample with fixture APIs, fresh headless contexts and
no CPU/network throttling observed no tasks over 50ms. This is a diagnostic
sample, not field Core Web Vitals or real backend latency. The document-list
load includes roughly 1 MB of decoded JavaScript because the conversation is
mounted with the reading workspace. Consider loading it on first open while
preserving conversation and split-reader state; that lifecycle change needs its
own regression coverage. No bundler, dependency or deployment settings changed.

## Verification and limits

The commit candidate was subsequently verified in an isolated copy containing
only the staged UI changes over the existing committed contracts. Type checking
reported 0 errors and 0 warnings; the production build, all 12 targeted browser
tests, and all 13 Finding component tests passed. The browser tests completed the
desktop/mobile failed-retry → retained Finding → exact Source path. The earlier
mixed-workspace failures below belong to the separate, unstaged contract work;
they are retained as the original audit record.

- `npm run build`: passed; existing >500 kB chunk warning remains.
- `npm run check`: 4 errors, 0 warnings in the mixed workspace. Three errors are stale
  `id` properties in `assistant-page.svelte.spec.ts`; one is `item.id` in
  `documents/+layout.svelte`. These appeared with a separate in-progress
  Collection contract change during this review, outside the polish edits.
- Targeted `page-audit.spec.ts`: 6 passed (mobile chrome, language metadata,
  dialog focus, narrow cards, More navigation, and Objectives → Finding entry).
- `FindingWorkbench.svelte.spec.ts` and `FindingEvidenceSummary.svelte.spec.ts`:
  13 passed, including on-demand summary and exact Source links.
- Extended `objective-workspace.spec.ts`: 4 responsive results tests passed;
  2 failed-retry/Source tests failed because their expected paper title became
  the fallback “文献 1” under the current contract/fixture combination. The
  captured links still include `source_ref`, evidence ID, page and return URL;
  the complete click-through assertions did not run past the title mismatch.
- `python3 scripts/check_docs_governance.py`: passed (36 governed documents,
  77 Markdown files).

The visual pass uses the actual frontend with controlled data; it does not prove
that real persisted data or an analysis service completes the research chain.
Desktop focus and window stacking remained unchanged during visible verification.
Both task-owned browser tabs and their leases were released; the local dev and
preview servers were stopped. Other browser sessions were preserved.
Temporary logs/screenshots were kept outside the repository. The design rules
live in [DESIGN.md](DESIGN.md); the route guide remains the behavior authority.

No new runtime component abstraction or compatibility layer was added. One
permanent semantic color token was extracted into the existing CSS token set.
Cleanup removed handlers/state/styles for retired controls and grid, unused
labels, and obsolete navigation helpers. Unrelated workspace changes remain.
