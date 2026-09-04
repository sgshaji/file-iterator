# Template regeneration solution

This is the authoritative Power Platform solution source.

It references the existing `PD Conversion Assistant` agent by schema name
`cree1_pdconversionassistant_08zNQw`; it does not copy or own that agent. The
proven invocation is `shared_agentnode` / `InvokeAgent` with
`body/agentId` and `body/prompt`.

## What is complete in source

- Explicit template-publish gate and duplicate-delivery suppression.
- A complete, paged plan over `DocumentIndex`; no 5,000-row aggregate action.
- Stable logical document keys across PDF/DOCX replacement.
- Deterministic source preference: PDF unless DOCX is newer.
- Durable work queue and one active batch run at a time.
- Connector retry disabled on the metered agent action.
- Strict parsing of `OK`, `FAILED` and `SKIPPED` reports.
- Byte-verification verdicts checked before a work item succeeds.
- Immediate durable agent-call accounting.
- SharePoint-list approval with a second-confirmation flag above the configured
  cap.
- Paged finalization counts.
- LIFO, paged rollback from the agent's archive manifests.
- Direct-children-only index backfill with persisted frontier, stale-claim
  recovery and post-walk deletion reconciliation.
- File create/modify/rename/delete and folder delete/rename/move handling.
- Generated Power Platform metadata and deployment settings.

## Flows

| File | Role |
|---|---|
| `A-PlanRegenerationRun.json` | A1 — create a planning run for an explicit publication |
| `A2-ContinueRegenerationPlan.json` | A2 — consume one bounded index page |
| `A3-ApproveRegenerationPlan.json` | A3 — apply `ApprovalDecision` from the run list |
| `B-ProcessRegenerationBatch.json` | B — process one bounded agent batch |
| `C-FinaliseRegenerationRun.json` | C — page terminal outcomes and close the run |
| `D-RollbackRegenerationRun.json` | D1 — lock the newest eligible run |
| `D2-ContinueRollback.json` | D2 — restore one bounded manifest page |
| `E1-StartIndexBackfill.json` | E1 — create a walk snapshot and seed its root |
| `E2-IndexBackfillWorker.json` | E2 — drain and reconcile the walk |
| `F-IndexDelta.json` | F — upsert file changes |
| `F2-IndexDelete.json` | F2 — process file/folder deletion |
| `F3-IndexFolderChange.json` | F3 — reconcile folder rename/move |

## Configuration

Generated deployment settings live under `config/`. Before deployment, the
workflow resolves tenant-specific values from the selected GitHub Environment:

- `FI_SITE_ADDRESS`
- `FI_WEB_SERVER_RELATIVE_URL`
- `FI_LIBRARY_URL_NAME`
- `FI_ROOT_FOLDER_PATH`
- `FI_TEMPLATE_FOLDER_PATH`
- `FI_SHAREPOINT_CONNECTION_ID`
- `FI_AGENT_CONNECTION_ID`

Deployment always forces `fi_DryRun=true`. Enabling live execution is a separate
tenant-side decision after inspecting a dry-run plan.

Only two connector bindings are required:

- SharePoint
- Agent (`shared_agentnode`)

## Approval

When A2 finishes planning a live run, the `RegenerationRun` item moves to
`AwaitingApproval` and `ApprovalDecision` is `Pending`.

A reviewer inspects `PlannedCount`, `RequiresSecondConfirmation` and the
persisted work items, then changes `ApprovalDecision` to `Approved` or
`Rejected`. A3 records the editor as `ApprovedBy` and moves the run to
`Approved` or `Cancelled`.

## Validation

Run from the repository root:

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
```

## Tenant acceptance (performed separately)

Source validation cannot prove connector tokens, import behavior or document
quality in the target tenant. Complete these steps after import:

1. Provision the five lists from
   `provisioning/pnp-provisioning-template.xml`.
2. Import the unmanaged package and bind SharePoint plus Agent connections.
3. Set all required environment variables; keep `fi_DryRun=true`.
4. Run E1 and wait for `IndexWalkRun.Status=Completed`.
5. Publish a template and confirm A1/A2 produce the expected dry-run work items
   with zero agent calls.
6. Set `fi_DryRun=false`, publish a new template version, approve one document,
   and verify exactly one agent call and a byte-verified output.
7. Run D1 and wait for D2; verify all displaced files are restored.
8. Increase the cap and batch size gradually from measured worst-case latency.

The solution must not be described as runtime-verified until these tenant steps
have passed.
