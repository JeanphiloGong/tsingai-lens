# Research Contracts

This directory owns the Research HTTP contracts for the backend.

- [Objective API](objective-api.md) defines list, detail, discovery, scope, analysis, and
  published-result routes.
- The Research data model is documented in [data-model.md](data-model.md).

The API contract uses `workspace_id` for resource ownership. Authentication supplies the
current `user_id`. Objective creation provenance and derivation references are retained for
server-side audit and are not exposed in list responses.
