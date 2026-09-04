# file-iterator

Template-triggered document regeneration in a SharePoint library above the
5,000-item list-view threshold.

The production source is [`solution/`](solution/). It reuses the existing PD
Conversion Assistant agent and gives Power Automate responsibility for
enumeration, planning, approval, bounded execution, accounting and rollback.

## Current requirement

When a template is explicitly published, regenerate every affected logical
document under the configured source root:

- enumerate at any folder depth without recursive SharePoint queries;
- exclude `Archive` and `AD Documents` before descending;
- support `.pdf` and `.docx`, exactly matching the deployed agent contract;
- invoke the agent at most once for the selected member of a PDF/DOCX pair;
- persist all work so runs resume without duplicating paid calls;
- require an audited approval before execution;
- preserve and restore every displaced file;
- use SharePoint plus the existing agent connector only—no premium custom
  connector and no Entra application registration.

Legacy `.doc` files are an explicit migration prerequisite. They must be
converted to `.docx` before indexing; the flow never spends a metered call on a
format the deployed skill rejects.

## Authoritative implementation

| Stage | Flow | Responsibility |
|---|---|---|
| Plan | A1 | Accept an explicit template publication and create a durable `Planning` run |
| Plan | A2 | Page through `DocumentIndex`, select one preferred source per logical document, and persist work items |
| Approve | A3 | Apply the human `ApprovalDecision` recorded on the SharePoint run item |
| Execute | B | Claim a bounded batch and invoke `shared_agentnode/InvokeAgent` once per work item |
| Finalize | C | Aggregate terminal outcomes in bounded pages and close the run |
| Roll back | D1 | Validate LIFO eligibility and lock a terminal run |
| Roll back | D2 | Restore a bounded page of agent archive manifests |
| Index | E1 | Start a complete index walk |
| Index | E2 | Drain the direct-children frontier and reconcile stale rows |
| Delta | F | Upsert file create/modify/rename events |
| Delta | F2 | Exclude deleted files and queue reconciliation for deleted folders |
| Delta | F3 | Queue reconciliation for folder rename/move events |

Five SharePoint lists hold durable state:

- `DocumentIndex`
- `RegenerationRun`
- `RegenerationWorkItem`
- `WalkFrontier`
- `IndexWalkRun`

See [`solution/README.md`](solution/README.md) for configuration, deployment and
tenant bring-up.

## Other repository areas

| Path | Purpose |
|---|---|
| [`reference-solution/`](reference-solution/) | Read-only export proving the existing agent schema name, invocation operation and skill contract |
| [`harness/`](harness/) | Diagnostic single-run fixture; useful for first-call inspection, not the production orchestrator |
| [`provisioning/`](provisioning/) | Canonical list schema plus generated PnP template |
| [`scripts/`](scripts/) | Flow generators, drift checks and R1-R7 semantic validation |
| [`docs/`](docs/) | Investigation, reference analysis and architecture rationale |

## Validation

```powershell
python scripts\generate_planning_flows.py --check
python scripts\generate_processing_flow.py --check
python scripts\generate_finalization_flow.py --check
python scripts\generate_rollback_flow.py --check
python scripts\generate_folder_update_flow.py --check
python scripts\generate_solution_shell.py --check
python scripts\generate_pnp_template.py --check
python scripts\generate_deployment_settings.py --check
python scripts\validate_solution.py
python scripts\validate_requirements.py
python scripts\validate_harness.py
python scripts\check_reference_untouched.py
```

`validate_requirements.py` maps implementation invariants to R1-R7. CI also
packs both Power Platform sources with `pac solution pack`.

## Completion boundary

The repository is statically complete and packable. Importing into a tenant,
binding connections and performing the live D1-D7 acceptance sequence require
the target Power Platform/SharePoint environment and are intentionally handled
separately.
