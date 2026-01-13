"""Retrieval package integrating the GraphRAG standard pipeline."""

import sys

# Allow absolute imports like `import retrieval...` even though the package
# is nested under `backend`.
sys.modules.setdefault("retrieval", sys.modules[__name__])
