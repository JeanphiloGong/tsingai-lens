# Research Agent Replay

This entry runs explicit S01-S21 conversations through the actual
ChatSessionService, including persisted approval and session permission paths.
It does not import untracked `.agent-runs` scripts or a second Agent runtime.

## Prepare Data

Use a disposable source checkout and a dedicated localhost PostgreSQL database
whose name ends in `_test`. Export only authorized research fixture data with
`pg_dump --format=custom --no-owner --no-privileges`, then restore that archive
into a fresh database using `pg_restore --no-owner --no-privileges`. Archive and
restore the corresponding backend data directory if Sources reference files.
Do not copy production credentials or connect this runner to a shared database.

Prepare 21 independent collections using the product's existing ingestion and
research APIs before taking the fixture snapshot. Supply real accessible papers
with Methods, Results and tables, and published Evidence/Finding for S16/S21.
Keep S18 deliberately partially prepared. These are scientific inputs: this
tool does not fabricate papers or wrong facts to obtain a passing result.
For S21, isolate the erroneous annotation while preserving immutable original
Source text, and record the researcher-verified expected correction.

Copy `scenarios.template.json` to a local untracked fixture document, replace
all `REPLACE` values and give each case an owned collection and explicit scope.
S07/S08/S10 need exact paper identities; S12/S14 include prerequisite dialogue.
Use a new restored fixture/database for each model, revision or permission mode.

## Run

Export `LENS_TEST_DATABASE_URL` and provider environment variables in the shell.
From backend, with the existing virtual environment:

```bash
python -m scripts.evaluation.research_agent.run_scenarios --help
python -m scripts.evaluation.research_agent.run_scenarios --snapshot --output /tmp/fixture-snapshot.json
```

Put the snapshot object in the fixture's `expected_snapshot` property. Then:

```bash
python -m scripts.evaluation.research_agent.run_scenarios --fixture /tmp/fixture.json --output /tmp/S21-report.json --scenario S21
```

The script validates every template value and scientific input fingerprint
before starting the application. An existing output path is rejected. After
each scenario it saves trajectories, exact calls and grants, limits, model,
prompt version, source revision/diff digest, fixture digest and database
fingerprints. It never prints credentials or exception messages. Reports can
contain research text; retain them locally unless explicitly authorized to share.

Omit `--scenario` to run all 21. Default permissions are `confirm`.
`--mode auto` grants only `automatic_actions` listed per fixture case; do not
select this mode for cases without a meaningful grant. `--mode read_only`
requires a fixture whose expected statuses reflect rejected writes. A turn can
set `revoke: true` before its message. Use the database concurrency tests for
revocation during a claim; this script's between-turn revocation is different.

Explicit test approvals are limited to the next exact pending tool and the
action whitelist. Scope grants do not simulate approval clicks. New sessions
reset to confirm. Automatic-grant cases skip explicit fixture approvals for
covered actions and must still require successful write tools in their checks.

## Judge Results

Technical checks cover expected status, complete dialogue, required successful
tools, no-tool replies, no scientific writes, and incomplete termination. A
required tool proves an observation occurred, not complete scientific reading.
Scientific review, immutable version relations and recall remain `incomplete`
until a researcher compares the saved trajectory and database against the rubric.
Keep S08 unknown grade versus proven difference, S13 UTS versus yield strength,
and S17 unread literature versus absence of prior validation as explicit checks.

The report records failures rather than retrying an entire write conversation.
Provider retry policy belongs to the production Runner. Resume a failed study
using a fresh isolated fixture; never blindly rerun a partially saved case.
