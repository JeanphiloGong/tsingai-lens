# Research Notes

This directory is for external domain context, literature summaries, and other
research-facing notes that inform the project but do not define implementation
truth.

Use lowercase kebab-case filenames for new notes. Keep research notes
header-free by default. If lifecycle or maintenance context matters, write it
in the body instead of a YAML metadata block.

## Allowed Content

- literature summaries
- domain background notes
- curated external references
- small supporting assets when versioning them in git is intentional

## Not Allowed

- secrets or credentials
- implementation source-of-truth docs
- random scratch notes without context or ownership

## Migration Note

When touched, legacy research material from root-level `docs/` should move here
or be replaced with an external link plus a short summary.

Legacy PDFs that still live under `docs/paper/` should be treated as supporting
assets only, not implementation source of truth.
