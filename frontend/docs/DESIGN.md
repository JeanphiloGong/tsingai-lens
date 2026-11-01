---
name: TsingAI-Lens
description: Evidence-first research workspace
colors:
  brand-primary: '#2563eb'
  brand-primary-hover: '#1d4ed8'
  on-brand: '#ffffff'
  brand-soft: '#eff6ff'
  bg-page: '#f7f9fc'
  bg-subtle: '#f2f6fb'
  surface-card: '#ffffff'
  text-primary: '#0f172a'
  text-secondary: '#64748b'
  border-default: '#e6ebf2'
  border-strong: '#d7e0ec'
  success-text: '#15803d'
  warning-text: '#b45309'
  danger-text: '#b91c1c'
  dark-brand-primary: '#4b8bff'
  dark-on-brand: '#0b1424'
  dark-bg-page: '#0b1424'
  dark-surface-card: 'rgba(16, 26, 44, 0.94)'
  dark-text-primary: '#e6efff'
  dark-text-secondary: '#a7b6cf'
typography:
  body:
    fontFamily: 'Inter, Manrope, Noto Sans SC, PingFang SC, Microsoft YaHei, Avenir Next, Segoe UI, sans-serif'
    lineHeight: 1.6
  label:
    fontSize: '0.85rem'
  code:
    fontFamily: 'IBM Plex Mono, JetBrains Mono, ui-monospace, SFMono-Regular, Menlo, Consolas, monospace'
rounded:
  sm: '10px'
  md: '12px'
  lg: '16px'
  xl: '20px'
spacing:
  compact: '8px'
  control: '12px'
  group: '16px'
  panel: '20px'
components:
  button-primary:
    backgroundColor: '{colors.brand-primary}'
    textColor: '{colors.on-brand}'
    rounded: '{rounded.md}'
    padding: '10px 16px'
  button-ghost:
    backgroundColor: '{colors.surface-card}'
    textColor: '{colors.text-primary}'
    rounded: '{rounded.md}'
    padding: '10px 16px'
  input:
    rounded: '{rounded.md}'
    padding: '10px 12px'
  card:
    rounded: '{rounded.md}'
    padding: '20px'
---

# Design System: TsingAI-Lens

## Overview

The visual system supports reading and comparing research evidence. Preserve the
existing A2 Lens mark, blue actions, slate text, and quiet surfaces. Tables and
source locations carry the product's character; the application shell should
make those artifacts easy to reach.

This is an extraction from the current implementation, not a new visual identity.
[layout.css](../src/routes/layout.css) owns runtime tokens and global primitives;
this document records their use. The frontmatter records observed values, not an
additional stylesheet. Spacing names describe recurring measurements rather than
new CSS variables. The [component sidecar](.impeccable/design.json) contains
illustrative snippets; application code remains in its existing owning files.

## Colors

**Primary:** brand blue identifies actions, focus, and active navigation. Use
`--on-brand` for text on a solid brand surface: it switches from white to dark ink
in dark mode. This token is shared by primary buttons, icon buttons, the home
primary action, and the Research Agent launcher.

**Neutral:** page, subtle background, and card surfaces separate context from
content. Secondary text retains sufficient contrast for labels and metadata.
Consume the existing semantic tokens instead of undefined names such as
`--surface-panel` or `--primary`.

**State:** success, warning, danger, and information colors accompany written
status labels. Color alone must not communicate analysis state or selection.

The dark theme uses the same roles, with pale text and a lighter action blue.
The monochrome A2 asset is inverted on dark application surfaces; the light login
surface keeps its original black mark.

## Typography

Use the existing multilingual sans-serif stack for reading and interface labels.
Fonts are system fallbacks unless actually installed; the application does not
currently ship these families as web fonts. Keep scientific statements in normal
sentence case. Use numeric alignment in data tables and units beside values.

Headings identify the current task or scientific statement. Avoid duplicating
that heading in an eyebrow label. Provenance remains metadata below a Finding's
statement, not another heading above it. Preserve code typography for actual
code, identifiers, or existing code-oriented fields.

## Layout

The current Collection is the research workspace boundary. Papers are files
inside it; Objectives describe questions over an explicit ready-paper scope;
Findings belong to a published Objective analysis. These are not nested
collections. The route ownership and detailed behavior remain in the
[collection route guide](../src/routes/collections/README.md).

The shared shell places brand and collection context on the left and functional
account/preferences controls on the right. On narrow screens it wraps. Primary
navigation exposes Overview, Papers, Objectives, and AI Copilot. More contains
Evidence Map, Feedback, and Settings. Objective screens use compact collection
context so the question and result receive space.

Keep actions within the viewport down to 320px. Home cards shrink and wrap action
rows; long names wrap without increasing the page width. Wide comparison tables
scroll inside a named, keyboard-focusable region rather than widening the page.
The existing global breakpoints are recorded in the sidecar; page-specific
breakpoints remain local to their components.

## Elevation & Depth

Use the existing small shadows for raised controls and surfaces. Dropdowns and
dialogs have a clear stacking relationship. The main reading surface stays plain;
the removed grid did not encode research data. Do not add decorative elevation
to evidence rows or scientific comparisons.

Existing transitions use short ease timings. Respect the global reduced-motion
rule; changing a state must not depend on animation completing.

## Shapes

Controls use the existing small and medium rounded corners; larger shells use
the large radius. Pills are compact status or metadata markers. Preserve the
A2 logo's geometry rather than generating an alternative logo.

## Components

- **Buttons:** use `.btn` variants or the existing `IconButton.svelte`. Keep an
  accessible name for icon-only actions and show loading/disabled states.
- **Fields:** visible labels, native required-field semantics, and a solid
  keyboard focus outline. Existing validation stays at the form boundary.
- **Navigation:** active links expose `aria-current="page"` and an underline.
  The More disclosure opens with native keyboard behavior; Escape closes it and
  returns focus to its summary.
- **Preferences:** theme and language are disclosure groups with ordinary buttons
  and `aria-pressed`; do not apply menu roles without complete menu behavior.
- **Create dialog:** native `showModal()`, a heading-connected accessible name,
  inert background, Escape dismissal, and focus restoration. Do not hand-build
  a second focus trap around the native dialog.
- **Evidence table:** semantic headers, tabular numerals, local scrolling, exact
  Source links, and explicit missing/limited values. Retain prior published
  Findings when a subsequent analysis fails.

## Do's and Don'ts

- Do preserve the collection → papers → Objective → Finding → Source context.
- Do use existing semantic tokens and verify both light and dark themes.
- Do check actual Chinese and English labels at narrow widths.
- Do make keyboard focus and current navigation visible without relying on color.
- Don't advertise unavailable search, shortcuts, notification, or account actions.
- Don't present a relevant paper as proven Evidence or a failed rerun as lost results.
- Don't add another component library or wrappers for isolated visual fixes.
- Don't turn detector suggestions into proof of usability or WCAG compliance.
