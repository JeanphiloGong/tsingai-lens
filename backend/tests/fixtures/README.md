# Backend Test Fixtures

This directory owns backend test fixture guidance and lightweight tracked
fixture helpers.

Large local expert gold-set data should stay under:

```text
backend/tests/fixtures/local_expert_gold/
```

That path is ignored by git. Use it for local PDF and CSV annotation exports
that support Core extraction evaluation without committing expert data,
copyrighted papers, or large binaries.
