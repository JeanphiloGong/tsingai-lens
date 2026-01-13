# Decision Log

Append-only. Record final decisions here.

- id: dec-2025-01-14-001
  timestamp: 2025-01-14T10:30:00+08:00
  decision: Use JWT for session tokens.
  context: Need stateless auth for web and mobile.
  options: [JWT, opaque sessions]
  rationale: Shared validation across services.
  impacts: Backend auth middleware and token rotation.
  owner: ai/tech-lead/rep-01
  followups: ["Define token TTL", "Add refresh flow"]
  links: []
