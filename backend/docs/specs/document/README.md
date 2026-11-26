# Document Contracts

These documents define the planned Document V2 storage and HTTP cutover. They are
owned by the Document module and must be updated with the implementation.

- [Data model](data-model.md)
- [HTTP API](api.md)

The current runtime still has migration work pending. `original_filename` and
`stored_filename` remain historical baseline names until the V2 Alembic revision
runs. The target contract uses `filename` and `storage_key`.
