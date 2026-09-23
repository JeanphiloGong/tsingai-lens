# Chat Correction Dataset Contract

P4 turns an owner-reviewed P3 correction sample into a reproducible evaluation
snapshot. It is a data boundary for later offline experiments, not a second
Chat trajectory and not an Objective Finding export.

The caller supplies a collection, owned `(session_id, sample_id, split)`
selections, and a document-to-paper-family inventory. The service authenticates
the collection and every session, rebuilds each sample from the current P2/P3
trajectory, verifies the stored sample and review digests, and checks that every
Source identity resolves in the same collection. Only the effective `accept`
decision can create an accepted row. Other outcomes become explicit exclusion
records with their reason.

Each accepted row retains the exact P1 model request, ordered message and tool
observations, corrected assistant target, P3 review ID/digest, Source records,
paper-family assignments, root session tree, requested split, and a SHA-256
`content_digest`. The manifest uses canonical JSON and computes a stable digest
over provenance, rows, and exclusions; its creation timestamp and database ID
are outside that content identity. Repeating a freeze with the same provenance
therefore returns the same immutable snapshot.

Partition checks reject a paper family or root Chat session tree that appears in
both `train` and `eval`. A stale or withdrawn sample is excluded from a new
manifest, while an older manifest remains readable and digest-verifiable. Reads
never reclassify old rows from current review state.

The JSONL download contains one manifest record, one record per accepted row,
and one record per exclusion. Empty manifests are valid and are intentionally
not considered trainable; P6 performs the non-empty partition and model checks.
