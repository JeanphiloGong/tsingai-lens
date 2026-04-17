# Application-Layer One-Shot Cutover Plan

## Summary

This document records the direct-cutover plan for cleaning
`backend/application/` from its current mixed state into a domain-only
application layout.

This is intentionally a hard switch, not a staged migration.

After this plan is executed, `backend/application/` should no longer expose
flat compatibility files such as `collection_service.py`,
`task_service.py`, or `protocol_extract_service.py`.

## Why This Plan Exists

The current application node is visibly between two architectures:

- real domain packages already exist under `collections/`, `indexing/`,
  `workspace/`, `documents/`, `evidence/`, `comparisons/`, `goals/`,
  `protocol/`, `graph/`, and `reports/`
- legacy flat entrypoints still exist at the application root as forwarding
  shims
- some Core-versus-Protocol parsing seams still use overlapping names such as
  `source_service.py` and `section_service.py`

That shape increases cognitive load and obscures ownership.

The governing rule for this cleanup is strict:

- no compatibility layer should remain after the cutover
- no old import path should be preserved "for safety"
- all callers must be updated to real implementations in the same task

## Scope

This plan covers:

- all flat `backend/application/*.py` compatibility shims
- caller import rewrites in runtime code and tests
- cleanup of overlapping Documents/Protocol parsing seams
- relocation of shared non-domain helpers out of the application root

This plan does not cover:

- controller package refactoring
- public API path changes
- Goal Consumer implementation
- Source/indexing GraphRAG retirement beyond application import cleanup

## Target End State

After the cutover:

- `backend/application/` root keeps only:
  - `__init__.py`
  - `README.md`
- all runtime and test imports use domain-package paths
- no top-level `*_service.py` or root runner shim remains
- Protocol no longer re-exports Core parsing helpers under duplicate service
  names
- shared helper code that does not belong to one application domain no longer
  lives at the application root

## Direct-Cutover Rules

1. Do not add new shims, wrappers, facades, or forwarding files.
2. Do not keep dual import paths during or after the task.
3. Rewrite all callers before deleting the old files.
4. Delete dead code and obsolete exports in the same task.
5. Treat test imports as first-class callers; they must be rewritten rather
   than left on legacy paths.

## File Actions

### Delete Root Compatibility Files

Delete these flat application-root shims once callers are rewritten:

- `application/artifact_registry_service.py`
- `application/collection_service.py`
- `application/graph_service.py`
- `application/index_run_mode_service.py`
- `application/index_task_runner.py`
- `application/report_service.py`
- `application/task_service.py`
- `application/workspace_service.py`
- `application/protocol_block_service.py`
- `application/protocol_document_meta_service.py`
- `application/protocol_extract_service.py`
- `application/protocol_normalize_service.py`
- `application/protocol_pipeline_service.py`
- `application/protocol_search_service.py`
- `application/protocol_section_service.py`
- `application/protocol_sop_service.py`
- `application/protocol_source_service.py`
- `application/protocol_validate_service.py`

### Keep Domain Packages As The Only Runtime Entrypoints

The cutover should leave these package roots as the only supported application
import seams:

- `application.collections.*`
- `application.indexing.*`
- `application.workspace.*`
- `application.documents.*`
- `application.evidence.*`
- `application.comparisons.*`
- `application.goals.*`
- `application.protocol.*`
- `application.graph.*`
- `application.reports.*`

### Rename The Real Duplicate Parsing Seams

These files are not compatibility shims; they are real implementations with
confusing overlapping names and should be renamed in the same cutover:

- `application/documents/source_service.py`
  -> `application/documents/input_service.py`
- `application/protocol/source_service.py`
  -> `application/protocol/artifact_service.py`

Reason:

- the Documents file owns shared collection-input loading and document-record
  assembly for the Core
- the Protocol file owns persistence helpers for protocol branch artifacts
- keeping both named `source_service.py` hides the Core-versus-Protocol
  boundary

### Remove Protocol Re-Export Naming For Core Parsing

Current state:

- `application/protocol/section_service.py` only re-exports
  `application.documents.section_service.build_sections`

Direct-cutover rule:

- delete `application/protocol/section_service.py`
- update Protocol callers to import the Documents-owned section builder
  directly

This makes the dependency direction explicit:

- Documents owns shared parsing
- Protocol consumes that parsing

### Move Shared Codec Out Of The Application Root

Move:

- `application/backbone_codec.py`

To:

- `infra/persistence/backbone_codec.py`

Reason:

- the codec is a storage-shaping helper shared by multiple application domains
- it is not itself an application domain
- leaving it at the application root keeps the root namespace acting as a junk
  drawer

## Import Rewrite Matrix

### Root Service Paths To Remove

- `application.collection_service`
  -> `application.collections.service`
- `application.task_service`
  -> `application.indexing.task_service`
- `application.index_task_runner`
  -> `application.indexing.index_task_runner`
- `application.index_run_mode_service`
  -> `application.indexing.run_mode_service`
- `application.workspace_service`
  -> `application.workspace.service`
- `application.artifact_registry_service`
  -> `application.workspace.artifact_registry_service`
- `application.graph_service`
  -> `application.graph.service`
- `application.report_service`
  -> `application.reports.service`

### Root Protocol Paths To Remove

- `application.protocol_block_service`
  -> `application.protocol.block_service`
- `application.protocol_document_meta_service`
  -> `application.protocol.document_meta_service`
- `application.protocol_extract_service`
  -> `application.protocol.extract_service`
- `application.protocol_normalize_service`
  -> `application.protocol.normalize_service`
- `application.protocol_pipeline_service`
  -> `application.protocol.pipeline_service`
- `application.protocol_search_service`
  -> `application.protocol.search_service`
- `application.protocol_section_service`
  -> direct Documents import after the Protocol re-export is deleted
- `application.protocol_sop_service`
  -> `application.protocol.sop_service`
- `application.protocol_source_service`
  -> `application.protocol.artifact_service`
- `application.protocol_validate_service`
  -> `application.protocol.validate_service`

### Shared Parsing Imports To Rewrite

- any Protocol caller importing `application.protocol.section_service`
  -> `application.documents.section_service`
- any caller importing `application.documents.source_service`
  -> `application.documents.input_service`
- any caller importing `application.protocol.source_service`
  -> `application.protocol.artifact_service`
- any caller importing `application.backbone_codec`
  -> `infra.persistence.backbone_codec`

## Execution Order

1. Rewrite runtime imports inside `backend/application/` to final domain paths.
2. Rewrite controller imports to final domain paths.
3. Rewrite all unit and integration test imports to final domain paths.
4. Rename the real Documents/Protocol parsing files and update all callers.
5. Move `backbone_codec.py` into `infra/persistence/` and rewrite all imports.
6. Delete all root compatibility shims.
7. Delete the Protocol section re-export file.
8. Remove empty directories or dead exports left by the cutover.

This order matters because the old files must remain only until all callers are
moved, and then they must be deleted immediately.

## Verification

### Structural Checks

- `find backend/application -maxdepth 1 -type f`
  should return only `__init__.py` and `README.md`
- `rg "application\\.[a-z_]+_service" backend --glob '!backend/docs/**'`
  should return no legacy flat application import paths
- `rg "application\\.protocol_section_service|application\\.protocol_source_service|application\\.documents\\.source_service|application\\.backbone_codec" backend`
  should return no runtime or test references

### Runtime Checks

- `python3 -m compileall backend/application backend/controllers backend/tests`
- targeted pytest for:
  - application services
  - router tests
  - task runner integration
  - app-layer API integration

### Acceptance Checks

- controllers import only domain-packaged application modules
- tests import only domain-packaged application modules
- Protocol consumes Documents-owned parsing directly
- application root no longer acts as a second service namespace

## Risks

- test files currently contain a large share of legacy imports and will need a
  broad but mechanical rewrite
- the Documents/Protocol rename touches real implementation files, not only
  imports, so call-site verification must be done after rename
- moving `backbone_codec.py` changes multiple domains at once and should not be
  split into a separate cleanup later

## Done Criteria

This plan is complete only when all of the following are true:

- no root application compatibility file remains
- no runtime or test code imports a deleted flat application path
- no Protocol re-export remains for Core parsing
- the application root contains no generic utility or service file outside
  `__init__.py` and `README.md`
- verification commands pass in the active development environment
