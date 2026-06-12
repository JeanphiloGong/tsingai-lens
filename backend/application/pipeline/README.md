# Application Pipeline Layer

This package owns application workflow orchestration.

Pipeline modules decide which application steps run, in which dependency order,
how step state is recorded, and how pipeline state is projected into task
status. Concrete implementation logic remains in the owning `application/source`,
`application/core`, `application/derived`, and `infra` modules.
