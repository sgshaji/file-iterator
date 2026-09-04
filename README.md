# file-iterator

Template-triggered document regeneration in SharePoint, using a Copilot Studio
agent as a per-document worker and Power Automate as the orchestrator — built on
top of an investigation into enumerating files in a library past the 5,000-item
list view threshold.

## The requirement

A Copilot Studio agent fills templates and generates documents. When a template
changes, every document produced from that template must be regenerated in the
new format. The flow finds the affected documents and calls the agent once per
document.

Two things make this harder than it sounds:

1. The library is past the list view threshold, so no recursive-by-path method
   can enumerate it. That is what the investigation report solves.
2. The agent call is metered and the write is destructive. A naive "loop over
   everything" flow is both expensive and unrecoverable. That is what the
   solution design solves.

## Contents

### Design and investigation

| Document | What it is |
|---|---|
| [docs/Template-Regeneration-Solution-Design.md](docs/Template-Regeneration-Solution-Design.md) | **The current design.** Cost-first architecture: index, plan, queue, batch, archive, rollback. Start here. |
| [docs/SharePoint-Large-Library-File-Enumeration-Investigation.md](docs/SharePoint-Large-Library-File-Enumeration-Investigation.md) | The prior investigation. Source of every platform constraint the design obeys — the threshold behaviour, the 16 MB action cap, the 600 calls/min connector limit, and the verified folder-walk method. |
| [docs/Power Automate - SharePoint Folder Files - Customer Test Guide.docx](<docs/Power Automate - SharePoint Folder Files - Customer Test Guide.docx>) | **Superseded (v1).** Teaches a method the investigation report itself records as throttling on a large library. Kept for history only; do not hand it to a customer. |

### Implementation

| Path | What it is |
|---|---|
| [solution/](solution/) | Unpacked Power Platform solution: seven flow definitions plus configuration. **[Read solution/README.md for verification status](solution/README.md) — nothing here has been imported or executed.** |
| [provisioning/lists.json](provisioning/lists.json) | Single source of truth for the four supporting SharePoint lists. |
| [provisioning/pnp-provisioning-template.xml](provisioning/pnp-provisioning-template.xml) | Generated from `lists.json`; applied with `Invoke-PnPSiteTemplate`. |
| [scripts/](scripts/) | Generators and the static validator that CI runs. |
| [.github/workflows/](.github/workflows/) | PR validation and packing; manual, environment-gated deployment. |

## How the pieces fit

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
```

`provisioning/pnp-provisioning-template.xml` and
`solution/config/deployment-settings.*.json` are generated. Edit their sources
(`provisioning/lists.json`, `solution/config/environment-variables.json`) and
regenerate; CI fails if they drift.

## Status

The design is complete and reviewed. The artefacts are hand-authored source that
has never been imported into a tenant. The
[bring-up order in solution/README.md](solution/README.md#bring-up-order) is the
next step, and it starts small on a test site deliberately.
