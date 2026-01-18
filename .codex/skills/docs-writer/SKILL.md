---
name: backend-docs-skill
description: Write backend architecture, API, data flow, and operations docs; use when asked to document backend systems or APIs.
---

# Backend Docs Writer

## Workflow
1. Clarify doc type and audience (architecture, API, ADR, runbook, onboarding).
2. Collect inputs: system scope, services, data stores, auth, dependencies, constraints.
3. Outline the doc with clear sections and assumptions.
4. Draft with concrete facts and explicit TODOs for unknowns.
5. Validate against provided sources and align terminology.
6. Provide open questions and next steps.

## Required Inputs
- System purpose and scope
- Service list and responsibilities
- Data stores, schemas, and data ownership
- Auth and security model
- Dependencies and integrations
- Deployment or runtime constraints
- Existing API specs or endpoints

## Output Format
### Architecture Doc
## Overview
## System Context
## Components and Responsibilities
## Data Flow
## API/Contract Summary
## Failure Modes and Recovery
## Operational Notes
## Open Questions

### API Doc
## Overview
## Base URL and Auth
## Endpoints
## Errors
## Examples
## Rate Limits and SLAs
## Changelog (if requested)

## Guardrails
- Do not invent endpoints, data fields, or behaviors.
- Mark unknowns as TODO and ask for clarification.
- Keep terminology consistent with existing code and docs.
- Use ASCII unless existing docs use another language.
