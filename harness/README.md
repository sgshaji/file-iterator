# PD Conversion Harness

A harness for the existing **PD Conversion Assistant** agent: it decides *what* to
convert, invokes the agent once per position, and reports *what actually happened*.

The agent already works. This is the machinery around it.

> **Diagnostic fixture, not the production orchestrator.**
> The complete implementation is [`solution/`](../solution/). Use this harness
> only for focused enumeration and first-agent-call diagnostics.

---

## Verification status — read this first

**No flow in this directory has ever been imported into a Power Platform
environment, and no agent call has ever been made from it.**

What that means in practice:

| Verified | How |
|---|---|
| Flow JSON is well-formed and structurally sound | `scripts/validate_harness.py` |
| The flow matches its generator | `generate_harness_flow.py --check` |
| No `runAfter` points at a non-sibling | validator (it caught one during development) |
| No `If`/`Switch`/`Scope` has all branches empty | validator |
| Agent invoked by the mechanism the export proves works | validator |
| The reference export is unmodified | `check_reference_untouched.py` |
| Contract constants match `pd_tools.py` | validator |
| The validator actually catches real defects | **run against the reference flow; it flags every documented defect** |

| Not verified | Why |
|---|---|
| The solution imports | Needs a tenant |
| Connector `operationId`s and trigger token names | Best-effort; taken from the export where available, inferred otherwise |
| The folder walk returns correct results | Needs a real library — D2 below |
| The agent returns what the flow expects | Needs a real invocation — D5 |
| Any document is actually converted | D6 |

The last point in the "verified" column is the one that matters most. A validator
that only ever passes on its author's own work proves nothing. This one was run
against `PDConversionWorkflow-6E2CE50C-...json` from the reference export, and it
flags the empty exclusion branches, the `RecursiveAll` enumeration, the CAML
query, the discarded agent response, the unconditional `Succeeded`, the
hard-coded demo-tenant literals and the 5,000-item pagination policy — the
defects documented independently in
[`docs/Reference-Solution-Analysis.md`](../docs/Reference-Solution-Analysis.md).

The investigation report is candid that its own folder-walk loop was assembled
but never run end-to-end (§9.6). The same caveat applies here, and inventing a
stronger claim would be worse than useless.

---

## What it does

```
Explicit trigger  (typed inputs, each defaulting to an environment variable)
   │
   ├─ RESOLVE      inputs coalesced against environment variables, once
   ├─ GATE         reject unusable configuration before enumerating anything
   │
   ├─ WALK         breadth-first, DIRECT CHILDREN ONLY
   │                 exclusions applied BEFORE descending
   │                 bounded by maxFolderDepth and maxFoldersScanned
   │                 truncation recorded, never silent
   │
   ├─ PLAN         ◀── observable stage 1, produced at zero cost
   │                 "plannedInvocations" = agent calls this run will make
   │
   ├─ dryRun? ─── yes ──▶ stop here. Nothing spent.
   │      │
   │      no
   │      ▼
   ├─ per position folder (capped at maxDocuments):
   │      COMPOSE_prompt          ◀── observable stage 2
   │      INVOKE_agent            ◀── the only metered operation
   │      CAPTURE_agent_response  ◀── observable stage 3, verbatim
   │      PARSE + CLASSIFY        OK / SKIPPED / FAILED / UNPARSEABLE
   │      RECORD_result           ◀── observable stage 4
   │
   └─ SUMMARY + terminal status DERIVED from outcomes  ◀── observable stage 5
```

### Design decisions worth defending

**Direct children only.** The 5,000-item threshold counts items SharePoint must
*scan*, not items returned, so every recursive-by-path method is a full-library
scan wearing a disguise. A folder's direct children use that folder's own index
and always succeed — proven in the investigation on a folder with 587 immediate
subfolders, two minutes after CAML threw `SPQueryThrottledException` on the same
folder. Recursion is the flow's job.

**One diagnostic unit = the preferred source in one position folder.** The
harness filters the first logical document group and applies the skill's exact
rule: prefer PDF unless DOCX is newer. It passes one concrete file path to the
agent, never the folder path.

**The agent's reply is read.** `SKIPPED` remains visible as a distinct diagnostic
outcome, but it makes the harness run fail because no document was produced.
`UNPARSEABLE` is separate because "the conversion failed" and "the harness could
not read the reply" have different causes and fixes.

**Dry run defaults to true.** An unconfigured import cannot spend anything.

**The flow is generated, not hand-written.** The reference flow's central defect —
an `If` with two empty branches and the agent call as its sibling — is nearly
invisible in the designer and trivial for a parser to catch. Generating the JSON
and checking it mechanically is the direct response to that.

---

## Configuration

Twelve environment variables, in `config/environment-variables.json`. Set the
first four per environment; the rest have working defaults.

| Variable | Default | Notes |
|---|---|---|
| `pdh_SiteUrl` | *(blank)* | e.g. `https://nhorgau.sharepoint.com/sites/pc` |
| `pdh_LibraryUrlName` | *(blank)* | The **URL** name (`wfpp`), not the display name |
| `pdh_SourceRootPath` | *(blank)* | Server-relative path of the folder holding position folders |
| `pdh_TemplateFolderPath` | *(blank)* | A **folder**; the skill treats it as every `.docx` within |
| `pdh_ExcludedFolderNames` | `Archive,AD Documents` | **CONTRACT** — must equal `OUTPUT_FOLDERS` |
| `pdh_SourceExtensions` | `.pdf,.docx` | **CONTRACT** — must equal `CONVERTIBLE_EXT` |
| `pdh_MaxDocuments` | `1` | Hard cap on metered agent calls |
| `pdh_DryRun` | `true` | Plan only |
| `pdh_MaxFolderDepth` | `8` | Walk ceiling |
| `pdh_MaxFoldersScanned` | `500` | Walk ceiling |
| `pdh_AgentId` | `cree1_pdconversionassistant_08zNQw` | The existing agent, by schema name |
| `pdh_RunLabel` | *(blank)* | Optional correlation label |

The two **CONTRACT** rows are asserted against `pd_tools.py` in CI. They are not
style preferences: the flow decides what to enqueue and the skill decides what it
will act on, so drift means paying for a call the skill then declines.

`pdh_LibraryUrlName` is called out because the display-name/URL-name confusion has
already cost time on this project — `PD-AD Library` is a *folder*; `wfpp` is the
library.

---

## Bring-up order

Each step is designed to fail visibly and cheaply before the next one can spend
anything.

**D1 — Import.** Pack (`harness/src`) and import. Bind the two connection
references. Set the four blank environment variables. Leave `pdh_DryRun` true.

**D2 — Dry run against the known-good fixture.** Point `pdh_SourceRootPath` at the
demo tenant's `Positions` folder and run.

The investigation report documents the correct answer for that tree: under
`Positions`, after applying the extension and excluded-folder rules, **3 files**,
all inside `Medical/`. So expect:

- `positionFoldersFound: 1` — only `Medical` holds convertible files directly;
  `IT`, `Marketing`, `HR` and `Tech` are empty
- that folder's `convertibleFileCount: 3`
- `agentCallCount: 0`
- nothing from `Archive` or `AD Documents` anywhere in the plan

If `Archive` or `AD Documents` content appears, the exclusion logic is wrong and
must be fixed before D5 — that is precisely the reference flow's P1/P2 failure,
and it is cheap to catch here and expensive to catch later.

**D3 — Dry run against production.** Repoint at
`nhorgau.sharepoint.com/sites/pc`, library `wfpp`, folder
`PD-AD Library/Position Descriptions`. This is the first real test of the
enumeration strategy at scale, and it still costs nothing.

Check `walkTruncated`. If set, raise `pdh_MaxFolderDepth` or
`pdh_MaxFoldersScanned` and repeat. **`foldersScanned` and the elapsed time from
this run are the measurements that size everything else** — no estimate is needed
before it, and none should be trusted over it.

**D4 — Permissions.** All five agent tools use `authMode: Invoker`, so they act as
the identity invoking the flow. If that identity lacks write access this fails
here, unambiguously, rather than as a puzzling mid-conversion error.

**D5 — First real invocation.** `pdh_DryRun` false, `pdh_MaxDocuments` **1**.
Exactly one metered call. Inspect `CAPTURE_agent_response` in the run history and
compare with the parsed record.

If the outcome is `UNPARSEABLE`, the reply shape differs from the contract; the
raw text is attached to the result record. This is the most likely place for the
first real surprise, because the `InvokeAgent` response envelope is one of the few
things the export does not pin down.

**D6 — Verify the artefact.** Open the produced document. Check `bytesSent`
against `bytesStored` in the result record — `pd_tools.py` warns the connector
returns Success even when it stored a path instead of the file, which is what
`path-not-dereferenced` exists to catch.

**D7 — Widen deliberately.** Raise `pdh_MaxDocuments` step by step, checking
`agentCallCount` and the failed/skipped split each time. Only raise `Foreach`
concurrency after measuring; concurrency multiplies the capacity burn rate.

---

## Local checks

```bash
python3 scripts/generate_harness_flow.py            # regenerate the flow
python3 scripts/generate_harness_flow.py --check    # fail if out of date
python3 scripts/validate_harness.py                 # the regression suite
python3 scripts/check_reference_untouched.py        # read-only guard
```

Never edit the flow JSON directly — edit the generator and regenerate, or CI will
fail on the `--check`.

---

## The reference solution is read-only

`reference-solution/` is evidence: it is how we know the agent's schema name, the
connector operation that invokes it, and the skill contract. Editing it destroys
the ability to say the harness matches what is deployed, and since it is a binary
zip, a diff cannot show what changed.

Replace it only by re-exporting from the environment. CI enforces this.

---

## Relationship to `solution/`

`solution/` is the authoritative production implementation. It incorporates the
reference export's proven `shared_agentnode` / `InvokeAgent` contract and adds
paged planning, durable work, approval, finalization, delta maintenance and
rollback. The harness remains intentionally smaller so a first call is easy to
inspect.
