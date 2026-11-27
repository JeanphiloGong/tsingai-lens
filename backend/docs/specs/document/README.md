# Document Contracts

These documents define the planned Document V2 storage and HTTP cutover. They are
owned by the Document module and must be updated with the implementation.

- [Data model](data-model.md)
- [HTTP API](api.md)

The runtime contract uses `filename` for the user-visible name and
`storage_key` for the server-owned object location. Historical migration files
may still mention the former split filename fields, but runtime code and new
schema revisions use only the target names.
