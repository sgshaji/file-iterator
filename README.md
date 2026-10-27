# SharePoint Document Regeneration

Template-triggered document regeneration in SharePoint, using a Copilot Studio
agent as a per-document worker and Power Automate as the orchestrator — built on
top of an investigation into enumerating files in a library past the 5,000-item
list view threshold.

> **Status:** implementation and investigation with offline static validation. Tenant
> import and end-to-end execution of the new flows have not been verified. The
> repository name remains `file-iterator` to preserve existing links.

## Engineering focus

| Delivery constraint | Design response |
|---|---|
| Large-library enumeration can hit SharePoint thresholds | Investigate the observed failure path and use bounded direct-children traversal |
| Agent calls are metered | Plan first, default to dry run, and gate the number of invocations |
| Regeneration can overwrite useful documents | Separate planning from writes and document archive/rollback in the scale-out design |
| A successful flow is not necessarily a successful conversion | Derive outcomes from the agent's response, including skipped and unparseable results |
| Hand-authored flow definitions can hide structural defects | Generate the current harness and validate it against explicit invariants |

**Start here:** [current harness and verification limits](harness/README.md),
[solution design](docs/Template-Regeneration-Solution-Design.md), and
[offline checks](#working-on-this-repository).

## The requirement

A Copilot Studio agent fills templates and generates documents. When a template
changes, every document produced from that template must be regenerated in the
new format. The flow finds the affected documents and calls the agent once per
document.

Two things make this harder than it sounds:

1. In the investigated library, recursive-by-path enumeration encountered the
   list view threshold. The investigation documents the failure and the
   direct-children approach used in the design.
2. The agent call is metered and the write is destructive. A naive "loop over
   everything" flow is both expensive and unrecoverable. That is what the
   solution design solves.

## Contents

### Design and investigation

| Document | What it is |
|---|---|
| [docs/Template-Regeneration-Solution-Design.md](docs/Template-Regeneration-Solution-Design.md) | **The current design.** Cost-first architecture: index, plan, queue, batch, archive, rollback. Start here. |
| [docs/Reference-Solution-Analysis.md](docs/Reference-Solution-Analysis.md) | What the deployed solution actually contains, reverse-engineered from the export: the agent is an *environment resource the flow references*, not a component it owns; plus the eleven confirmed defects the harness is built to avoid — and one I withdrew after the skill contract proved me wrong. |
| [docs/SharePoint-Large-Library-File-Enumeration-Investigation.md](docs/SharePoint-Large-Library-File-Enumeration-Investigation.md) | The prior investigation. Source of every platform constraint the design obeys — the threshold behaviour, the 16 MB action cap, the 600 calls/min connector limit, and the verified folder-walk method. |
| [docs/Power Automate - SharePoint Folder Files - Customer Test Guide.docx](<docs/Power Automate - SharePoint Folder Files - Customer Test Guide.docx>) | **Superseded (v1).** Teaches a method the investigation report itself records as throttling on a large library. Kept for history only; do not hand it to a customer. |

### Implementation

| Path | What it is |
|---|---|
| [harness/](harness/) | **The current implementation.** A harness for the existing PD Conversion Assistant agent: direct-children folder walk, an explicit plan, a dry-run cost gate, one agent call per position folder, and a terminal status derived from what the agent actually returned. **[Read harness/README.md](harness/README.md) for verification status and bring-up order.** |
| [reference-solution/](reference-solution/) | **Read-only.** The exported Power Platform solution for the deployed agent. The source of truth for the agent's schema name, its invocation mechanism and the `pd-ad-conversion` skill contract. Replaced only by re-exporting; CI enforces this. |
| [solution/](solution/) | **Superseded.** Earlier seven-flow design, built before the reference export existed. Retained as the scale-out design. [Verification status](solution/README.md). |
| [provisioning/lists.json](provisioning/lists.json) | Single source of truth for the four supporting SharePoint lists. |
| [provisioning/pnp-provisioning-template.xml](provisioning/pnp-provisioning-template.xml) | Generated from `lists.json`; applied with `Invoke-PnPSiteTemplate`. |
| [scripts/](scripts/) | Generators and the static validator that CI runs. |
| [.github/workflows/](.github/workflows/) | PR validation and packing; manual, environment-gated deployment. |

## How the pieces fit

The diagram below describes the **scale-out design** in `solution/`. The current
`harness/` implementation uses its own resolve, gate, walk, plan, invoke, and
summary stages; see [the harness walkthrough](harness/README.md#what-it-does).

```
template changed
      │
      ▼
   Flow A ── plans the run, applies the cost filters, asks for approval
      │       (makes zero agent calls)
      ▼
  work queue
      │
      ▼
   Flow B ── per document: read → agent → validate → archive → write
      │       (the only flow that spends money or changes documents)
      ▼
   Flow C ── closes the run, reports what it cost

   Flows E1/E2 build the document index by walking folders;
   Flow F keeps it current. Flow D rolls a run back from the archive.
```

The governing principle: **the agent call is the only expensive operation, so
never invoke the agent for a document that does not need it, and never invoke it
twice.** Everything else in the design exists to serve that.

## Working on this repository

```bash
python3 scripts/validate_solution.py              # flows, columns, config
python3 scripts/generate_pnp_template.py --check  # provisioning drift
python3 scripts/generate_deployment_settings.py --check
python3 scripts/check_reference_untouched.py origin/main
python3 scripts/generate_harness_flow.py --check
python3 scripts/validate_harness.py
```

`provisioning/pnp-provisioning-template.xml` and
`solution/config/deployment-settings.*.json` are generated. Edit their sources
(`provisioning/lists.json`, `solution/config/environment-variables.json`) and
regenerate; CI fails if they drift.

## Status

All six offline checks above passed on Windows with Python 3.14.7 on 27 October
2026. The solution validator reported two expected design-time-only environment
variables that are declared but not referenced by a flow; the harness validator
reported zero warnings.

These are static and consistency checks, not a tenant execution. The source has
not been imported into a tenant or used for an end-to-end conversion from this
harness. Follow the [current harness bring-up guidance](harness/README.md) on a
test site before making runtime or scale claims. The earlier scale-out design
has its own [verification status](solution/README.md).
