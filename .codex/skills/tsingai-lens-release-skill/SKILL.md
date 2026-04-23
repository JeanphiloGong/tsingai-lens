---
name: tsingai-lens-release-skill
description: v0.1.0 - Draft and execute the evidenced TsingAI-Lens release flow for tags, GitHub releases, and Docker image publishing.
---

# TsingAI-Lens Release Skill

## Trigger and Scope

Use this skill when you need to prepare, draft, or execute a TsingAI-Lens
release.

In scope:
- align the repo's release version surfaces before tagging
- draft release notes in the repository's current public style
- create and push the release tag that triggers image publishing
- watch the `release-images.yml` workflow
- create or update the GitHub Release page for the tag

Out of scope:
- inventing a new semver or version-bump policy
- changing `.github/workflows/release-images.yml`, Docker Hub repositories, or
  release secrets
- adding publish targets beyond the existing Docker Hub backend/frontend images
- assuming every historical tag must have a separate GitHub Release page when
  the repository has already rolled one tag into a later hosted release

## Repository Release Evidence

Use these sources before making release decisions:

- `.github/workflows/release-images.yml`
  The authoritative publish trigger. A push to a `v*` tag builds and pushes:
  - `jeanphilo/tsingai-lens-backend:<tag>`
  - `jeanphilo/tsingai-lens-frontend:<tag>`
  If the tag contains no hyphen, the workflow also publishes `latest` for both
  images.
- `README.md`
  Documents release-image deployment and uses `<release-tag>` as the operator
  input for `LENS_VERSION`.
- `docker-compose.release.yml`
  Encodes the default deploy images and default release tag.
- `backend/pyproject.toml`
  Current backend package version source.
- `backend/main.py`
  Current FastAPI app version source.
- `frontend/package.json`
  Current frontend package version source.
- GitHub releases `v0.3.0`, `v0.3.2`, and `v0.3.3`
  Evidence for the repository's release-note voice, compare-link format, and
  reference style.
- GitHub release `v0.3.2`
  Evidence that `v0.3.1` had a tag without a separate hosted release page, so
  the skill must not assume a one-tag-one-release-page rule without checking
  operator intent.

## Required Inputs

- target tag, for example `v0.3.4`
- repository root, default `.` at the project root
- intended release commit or branch tip
- compare-from tag when it should not be auto-inferred from the latest hosted
  release

## Optional Inputs

- release PR URL
- tracking issue URL
- explicit statement that this tag should not get its own hosted GitHub Release
- exact verification commands run for this release

## Defaults

- tag rule: `v*`
- stable tag semantics:
  a tag without `-` publishes versioned backend/frontend images and also
  publishes `latest`
- prerelease-like tag semantics:
  a tag with `-` still publishes versioned images but does not publish
  `latest`
- version text:
  strip the leading `v` from the target tag when checking version files
- version surfaces that should agree before tagging:
  - `backend/pyproject.toml`
  - `backend/main.py`
  - `frontend/package.json`
- deployment-default surface to verify when the release intends to move the
  default image tag:
  - `docker-compose.release.yml`
- hosted release platform: GitHub Releases
- release-note language and voice:
  Chinese, with one plain-language user explanation first
- release-note section order:
  - `## 用户说明`
  - `## New Features`
  - `## Bug Fixes`
  - `## Documentation`
  - `## Chores`
  - `## Changelog`
- reference lines:
  - `Full Changelog: https://github.com/JeanphiloGong/tsingai-lens/compare/<from>...<to>`
  - `Release PR: <url>` or `Release PR #<n>: <url>` when present
  - `Tracking Issue: <url>` when present
- unknown handling:
  - `TODO(repo-verify)` for non-blocking gaps
  - `BLOCK` for missing facts that make tag or publish execution unsafe

## Workflow

1. Preflight repository state.
   - Verify you are at the repository root.
   - Verify the worktree is clean or that the operator explicitly wants to tag
     the current dirty state.
   - Verify the target tag does not already exist locally or on `origin`.
   - Verify the release commit is the intended commit to publish.

2. Align release version surfaces.
   - Derive `release_version` from the target tag by removing the leading `v`.
   - Check `backend/pyproject.toml`, `backend/main.py`, and
     `frontend/package.json` for that exact version string.
   - If this release is also updating the default deploy target, check that
     `docker-compose.release.yml` uses the same tag in `LENS_VERSION`.
   - Do not invent extra version surfaces. If another file looks versioned but
     is not part of the release evidence, mention it separately instead of
     blocking the release.

3. Draft release notes in the repository's current style.
   - Start with `## 用户说明`.
   - That section is for end users only.
   - Do not use technical terms, internal module names, class names, API
     language, schema names, test names, or workflow names in that section.
   - In `## 用户说明`, explain only:
     - who should upgrade
     - the most direct user-visible changes
     - how the day-to-day workflow changes, if at all
   - After `## 用户说明`, switch to the standard release sections:
     - `## New Features`
     - `## Bug Fixes`
     - `## Documentation`
     - `## Chores`
     - `## Changelog`
   - Group bullets for humans instead of listing one PR per bullet by default.
   - Put internal refactors, dependency work, CI stabilization, and release
     process adjustments under `## Chores`.
   - Always include a `Full Changelog` compare link when the compare range is
     known.
   - Include `Release PR` and `Tracking Issue` lines when they exist.
   - If a tag is intentionally rolled into a later hosted release, say so
     explicitly in the release body instead of silently omitting it.

4. Trigger the publish path by tag push.
   - Fetch tags before tagging:
     `git fetch origin --tags`
   - Create the tag only after version surfaces are aligned.
   - Push the tag to `origin`.
   - The tag push is what triggers `.github/workflows/release-images.yml`.
   - BLOCK if the target tag already exists remotely or if version surfaces are
     inconsistent.

5. Watch release-image publication.
   - Monitor the GitHub Actions run for `release-images.yml`.
   - Expected image tags after a successful stable release:
     - `jeanphilo/tsingai-lens-backend:<tag>`
     - `jeanphilo/tsingai-lens-frontend:<tag>`
     - `jeanphilo/tsingai-lens-backend:latest`
     - `jeanphilo/tsingai-lens-frontend:latest`
   - Expected image tags after a successful hyphenated tag:
     - `jeanphilo/tsingai-lens-backend:<tag>`
     - `jeanphilo/tsingai-lens-frontend:<tag>`
   - If the workflow fails, stop and report the failing job rather than
     claiming the release is published.

6. Create or update the GitHub Release page.
   - Use the release notes drafted in step 3.
   - The title should match the tag unless the operator explicitly wants a
     different release name.
   - Keep the compare link and repo references in the body.
   - If this tag should remain tag-only and be rolled into a later hosted
     release, record that explicitly instead of fabricating a release page.

7. Report the release result.
   - Include the final tag, release version, version surfaces checked, workflow
     status, release URL, compare range, and any unresolved `TODO(repo-verify)`
     items.

## Release Notes Template

Use this as the default shape when drafting the release body:

```md
## 用户说明

<1-2 short paragraphs in plain language only. No technical terms. Explain who
should upgrade, what will feel better, and whether the user needs to change
their usual workflow.>

## New Features
- <user-facing feature summary>
- <user-facing feature summary>

## Bug Fixes
- <behavioral fix summary>
- <behavioral fix summary>

## Documentation
- <docs change summary>
- <docs change summary>

## Chores
- <internal refactor, infra, or maintenance summary>
- <internal refactor, infra, or maintenance summary>

## Changelog
Full Changelog: https://github.com/JeanphiloGong/tsingai-lens/compare/<from>...<to>
Release PR: <url>
Tracking Issue: <url>
```

Delete empty sections instead of leaving placeholders.

## Output Format

```text
## Release Request
- target_tag:
- release_version:
- compare_from:
- compare_to:
- release_commit:

## Preflight
- repo_root:
- worktree_clean:
- remote_tag_exists:
- version_surfaces_checked:
- deployment_default_checked:

## Release Notes
- notes_ready:
- release_pr:
- tracking_issue:
- compare_link:

## Trigger
- tag_created:
- tag_pushed:
- trigger_source: .github/workflows/release-images.yml

## Verification
- workflow_status:
- expected_images:
- latest_expected:

## Hosted Release
- release_page_status:
- release_url:

## Unknowns
- blocking:
- non_blocking:

## Final Decision
- status: ready | blocked | published | partial
- next_action:
```

## Guardrails

- Do not invent a new version bump policy for this repository.
- Do not create or push the tag when the checked version surfaces disagree.
- Do not assume a hyphenated tag should publish `latest`; the workflow says it
  should not.
- Do not claim Docker publication succeeded until `release-images.yml` has
  completed successfully.
- Do not omit the compare link when the previous release tag is known.
- Do not assume every tag must have a standalone hosted release page; the
  repository already has one counterexample.
- Do not edit release workflows, Docker Hub settings, or secrets as part of a
  normal release run.

## Unknowns

- `TODO(repo-verify)` preferred operator path for GitHub Release creation:
  GitHub UI versus `gh release create` / `gh release edit`
- `TODO(repo-verify)` whether every stable `vX.Y.Z` tag should normally get its
  own hosted GitHub Release page
- `TODO(repo-verify)` retry policy when a tag has already been pushed and image
  publication partially failed

## Verification Hooks

- Confirm the target tag matches the checked repo version surfaces.
- Confirm the compare link uses the exact GitHub compare format already seen in
  prior releases.
- Confirm the `## 用户说明` section stays plain-language and does not contain
  technical vocabulary.
- Confirm the release references include the items that actually exist for this
  release, not guessed placeholders.
- Confirm the publish claim matches the real GitHub Actions outcome.
