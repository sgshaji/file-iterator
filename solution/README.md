# Solution source — verification status

> **SUPERSEDED — see [`harness/`](../harness/) for the flow to run now.**
>
> This design was built *before* the reference solution export was available. Its
> architecture is sound at scale, but its agent invocation used a guessed
> child-flow placeholder; the export later proved the real mechanism is the
> `shared_agentnode` connector's `InvokeAgent` operation, addressing the agent by
> schema name.
>
> Retained deliberately, not deleted: this is the scale-out design to return to
> when the harness outgrows a single sequential pass. See
> [`docs/Reference-Solution-Analysis.md`](../docs/Reference-Solution-Analysis.md).

Read this before importing anything.

## What this is

An unpacked Power Platform solution containing the flow definitions for the
template regeneration design in
[`docs/Template-Regeneration-Solution-Design.md`](../docs/Template-Regeneration-Solution-Design.md).

```
solution/
  config/
    environment-variables.json            declaration of all 24 env vars + 3 connection references
    deployment-settings.test.json         generated; values filled in per environment
    deployment-settings.prod.json         generated; values filled in per environment
  src/
    Workflows/
      A-PlanRegenerationRun.json          all cost control; makes zero agent calls
      B-ProcessRegenerationBatch.json     the only flow that calls the agent or writes documents
      C-FinaliseRegenerationRun.json      closes a drained run, sends the summary
      D-RollbackRegenerationRun.json      manual restore from archive
      E1-StartIndexBackfill.json          seeds the folder-walk frontier
      E2-IndexBackfillWorker.json         the folder walk itself, chunked
      F-IndexDelta.json                   keeps the index current between walks
```

## Verification status — read this

**These flow definitions have never been imported into a Power Platform
environment and have never been executed.** They are hand-authored source, not
an export of something that ran.

What *has* been verified:

- Every file is valid JSON with exactly one trigger and a non-empty action set.
- Every `runAfter` reference resolves to an action in the same scope.
- Every environment variable and connection reference used by a flow is declared.
- Every SharePoint column read or written by a flow exists in
  `provisioning/lists.json`, and columns that flows filter on are indexed.
- The provisioning template and deployment settings are in sync with their sources.

Run all of it with:

```bash
python3 scripts/validate_solution.py
python3 scripts/generate_pnp_template.py --check
python3 scripts/generate_deployment_settings.py --check
```

What has **not** been verified, and what to expect on first import:

| Area | Risk |
|---|---|
| Connector `operationId` values | `HttpRequest`, `GetItems`, `PostItem`, `PatchItem`, `CopyFileAsync`, `CreateFile`, `GetFileContentByPath`, `GetOnUpdatedItems`, `SendEmailV2`, `StartAndWaitForApproval` are best-effort. Expect to correct some on import. |
| Trigger body token names | Trigger output property names may differ from those referenced in expressions. |
| Agent invocation | `STEP_2_Invoke_agent` in Flow B is a **placeholder** `Workflow` action. Replace it with the Copilot Studio agent action. The surrounding contract (input, validation, archive, write) does not change. |
| Solution metadata | `src/Other/` (`Solution.xml`, `Customizations.xml`) is not present. The pack step in CI will need it, or the flows can be imported individually while the solution shell is created in-product and exported. |
| End-to-end behaviour | Nothing. No run has ever happened. |

The investigation that preceded this design records the same honesty gap in its
own §9.6 — the folder-walk loop was assembled but never run end to end. Do not
repeat that mistake by treating this directory as finished work.

## Bring-up order

Do not skip steps, and do not reorder them. Each one is cheap; the failure it
prevents is not.

1. **Provision the lists** on a test site:
   `Invoke-PnPSiteTemplate -Path provisioning/pnp-provisioning-template.xml`
2. **Import the solution** to a test environment with
   `deployment-settings.test.json` pointing at a **test** library. Never at production.
3. **Run E1/E2** against the small test tree. Confirm the index is populated and
   the walk completes. This is the first thing to make green, because everything
   else assumes a correct index.
4. **Run Flow A with `fi_DryRun = true`.** Inspect the plan. Confirm the affected
   document count is what you expect. A wrong count here is a wrong bill later.
5. **Run Flow B on a single document** (`fi_MaxDocumentsPerRun = 1`). Confirm the
   archive copy exists and the output is correct before anything else runs.
6. **Measure the agent call**: duration and capacity consumed per document. The
   design's batch size and schedule are guesses until this number is real.
7. Only then raise `fi_MaxDocumentsPerRun` and set `fi_DryRun = false`.

## Safety properties worth not breaking

- `fi_DryRun` defaults to **true**. A fresh deployment cannot regenerate
  documents before someone has looked at a plan.
- The template folder and the output folder must be **strictly disjoint**.
  If they overlap, Flow B's writes re-trigger Flow A and the solution loops
  while spending agent capacity on every pass.
- Flow B's order is validate → archive → write. Any other order can destroy a
  good document on a bad agent response.
- Flow B stamps `TemplateFingerprint` on the output index row. Cost filter F3
  depends on it. If that stamp stops working, every run regenerates everything
  and the cost model collapses silently.
