#!/usr/bin/env python3
"""Generate the PD Conversion Harness flow definition.

The flow is a Logic Apps workflow definition: several hundred lines of deeply
nested JSON in which a single mistyped action name silently breaks a runAfter
chain. Writing it by hand invites exactly the class of defect found in the
reference flow, where an `If` action ended up with two empty branches and the
agent call ended up as its sibling rather than its child - so the exclusion
filter never ran and the agent was invoked for every file.

Generating it means the structure is expressed once, in code that can be read,
and the nesting is produced mechanically. scripts/validate_harness.py then
checks the result independently.

Usage:
    python3 scripts/generate_harness_flow.py           # write the flow
    python3 scripts/generate_harness_flow.py --check   # fail if out of date
"""

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_FILE = os.path.join(
    ROOT, "harness", "src", "Workflows",
    "PDConversionHarness-A7C41F52-8E3B-4D16-9F20-6B8E2D4C71A5.json",
)

SP = "shared_sharepointonline"
AGENT = "shared_agentnode"

# Environment variables are referenced through the parameters() function using
# Power Platform's "Display Name (schema_name)" convention.
EV = {
    "site": "@parameters('pdh_SiteUrl (pdh_SiteUrl)')",
    "library": "@parameters('pdh_LibraryUrlName (pdh_LibraryUrlName)')",
    "sourceRoot": "@parameters('pdh_SourceRootPath (pdh_SourceRootPath)')",
    "templateFolder": "@parameters('pdh_TemplateFolderPath (pdh_TemplateFolderPath)')",
    "excluded": "@parameters('pdh_ExcludedFolderNames (pdh_ExcludedFolderNames)')",
    "extensions": "@parameters('pdh_SourceExtensions (pdh_SourceExtensions)')",
    "maxDocs": "@parameters('pdh_MaxDocuments (pdh_MaxDocuments)')",
    "dryRun": "@parameters('pdh_DryRun (pdh_DryRun)')",
    "maxDepth": "@parameters('pdh_MaxFolderDepth (pdh_MaxFolderDepth)')",
    "maxFolders": "@parameters('pdh_MaxFoldersScanned (pdh_MaxFoldersScanned)')",
    "agentId": "@parameters('pdh_AgentId (pdh_AgentId)')",
    "runLabel": "@parameters('pdh_RunLabel (pdh_RunLabel)')",
}


def sp_action(operation_id, parameters, run_after, description):
    """A SharePoint connector call."""
    return {
        "type": "OpenApiConnection",
        "description": description,
        "runAfter": run_after,
        "inputs": {
            "host": {
                "apiId": "/providers/Microsoft.PowerApps/apis/" + SP,
                "connectionName": SP,
                "operationId": operation_id,
            },
            "parameters": parameters,
            "authentication": "@parameters('$authentication')",
        },
    }


def compose(value, run_after, description):
    return {
        "type": "Compose",
        "description": description,
        "runAfter": run_after,
        "inputs": value,
    }


def set_var(name, value, run_after, description):
    return {
        "type": "SetVariable",
        "description": description,
        "runAfter": run_after,
        "inputs": {"name": name, "value": value},
    }


def append_var(name, value, run_after, description):
    return {
        "type": "AppendToArrayVariable",
        "description": description,
        "runAfter": run_after,
        "inputs": {"name": name, "value": value},
    }


# ---------------------------------------------------------------------------
# Trigger
# ---------------------------------------------------------------------------

def build_trigger():
    """Explicit manual invocation with typed, overridable inputs.

    The reference flow triggered on a template file change, every minute, with
    splitOn. Touching three template files therefore produced three runs, each
    fanning out across every position - at full agent cost, with no way to
    intervene. For a harness the invocation must be deliberate and its inputs
    visible in the run history.

    Every input defaults to its environment variable, so the flow is
    configuration-driven by default and override-driven when testing. Same
    inputs produce the same plan.
    """
    return {
        "manual": {
            "type": "Request",
            "kind": "Button",
            "description": (
                "Explicit invocation. Every input defaults from an environment "
                "variable when left blank, so a normal run needs no input at all "
                "and a test run can override one value without editing the flow."
            ),
            "inputs": {
                "schema": {
                    "type": "object",
                    "properties": {
                        "sourceRootPath": {
                            "type": "string",
                            "title": "Source root path (blank = configured value)",
                            "description": "Server-relative path of the folder containing position folders.",
                        },
                        "templateFolderPath": {
                            "type": "string",
                            "title": "Template folder path (blank = configured value)",
                            "description": "Server-relative path of the template folder. A folder means every .docx in it.",
                        },
                        "maxDocuments": {
                            "type": "integer",
                            "title": "Max documents (0 = configured value)",
                            "description": "Hard cap on agent invocations for this run.",
                        },
                        "dryRun": {
                            "type": "boolean",
                            "title": "Dry run",
                            "description": "Plan only. No agent invocation, no metered cost.",
                        },
                        "runLabel": {
                            "type": "string",
                            "title": "Run label",
                            "description": "Optional. Recorded in the output for correlation.",
                        },
                    },
                }
            },
        }
    }


# ---------------------------------------------------------------------------
# Stage 1 - resolve inputs
# ---------------------------------------------------------------------------

def build_resolve_actions():
    """Coalesce each trigger input against its environment variable, once.

    Resolving in one place means every later action reads a single resolved
    value. The reference flow instead repeated literal site URLs and paths
    across four actions and inside the agent prompt, so changing environment
    meant finding every copy.
    """
    a = {}

    a["INIT_run_id"] = {
        "type": "InitializeVariable",
        "description": "Correlation id for this run. Stamped on every emitted record.",
        "runAfter": {},
        "inputs": {
            "variables": [{
                "name": "runId",
                "type": "string",
                "value": "@{utcNow('yyyyMMdd-HHmmss')}-@{substring(guid(), 0, 8)}",
            }]
        },
    }

    a["RESOLVE_config"] = compose(
        {
            "siteUrl": EV["site"],
            "libraryUrlName": EV["library"],
            "sourceRootPath": "@{coalesce(triggerBody()?['sourceRootPath'], '')}",
            "templateFolderPath": "@{coalesce(triggerBody()?['templateFolderPath'], '')}",
            "excludedFolderNames": EV["excluded"],
            "sourceExtensions": EV["extensions"],
            "maxDocuments": "@coalesce(triggerBody()?['maxDocuments'], 0)",
            "dryRun": "@coalesce(triggerBody()?['dryRun'], " + EV["dryRun"][1:] + ")",
            "maxFolderDepth": EV["maxDepth"],
            "maxFoldersScanned": EV["maxFolders"],
            "agentId": EV["agentId"],
            "runLabel": "@{coalesce(triggerBody()?['runLabel'], " + EV['runLabel'][1:] + ")}",
        },
        {"INIT_run_id": ["Succeeded"]},
        "Raw configuration: trigger input where supplied, environment variable otherwise.",
    )

    # Blank string inputs must fall back too. coalesce only catches null, so an
    # empty text box would otherwise resolve to "" and the walk would start at
    # the site root.
    a["RESOLVE_effective"] = compose(
        {
            "siteUrl": "@outputs('RESOLVE_config')['siteUrl']",
            "libraryUrlName": "@outputs('RESOLVE_config')['libraryUrlName']",
            "sourceRootPath": (
                "@if(empty(outputs('RESOLVE_config')['sourceRootPath']), "
                + EV["sourceRoot"][1:]
                + ", outputs('RESOLVE_config')['sourceRootPath'])"
            ),
            "templateFolderPath": (
                "@if(empty(outputs('RESOLVE_config')['templateFolderPath']), "
                + EV["templateFolder"][1:]
                + ", outputs('RESOLVE_config')['templateFolderPath'])"
            ),
            "excludedFolderNames": (
                "@split(outputs('RESOLVE_config')['excludedFolderNames'], ',')"
            ),
            "sourceExtensions": (
                "@split(toLower(outputs('RESOLVE_config')['sourceExtensions']), ',')"
            ),
            "maxDocuments": (
                "@if(equals(outputs('RESOLVE_config')['maxDocuments'], 0), "
                + EV["maxDocs"][1:]
                + ", outputs('RESOLVE_config')['maxDocuments'])"
            ),
            "dryRun": "@outputs('RESOLVE_config')['dryRun']",
            "maxFolderDepth": "@outputs('RESOLVE_config')['maxFolderDepth']",
            "maxFoldersScanned": "@outputs('RESOLVE_config')['maxFoldersScanned']",
            "agentId": "@outputs('RESOLVE_config')['agentId']",
            "runLabel": "@outputs('RESOLVE_config')['runLabel']",
        },
        {"RESOLVE_config": ["Succeeded"]},
        (
            "Effective configuration. An empty string is treated as 'not supplied': "
            "coalesce only catches null, so a blank text box would otherwise start "
            "the walk at the site root."
        ),
    )

    # --- Input gate --------------------------------------------------------
    # Fail loudly and specifically, before any enumeration and long before any
    # metered call.
    gate_checks = [
        ("siteUrl", "@empty(outputs('RESOLVE_effective')['siteUrl'])",
         "pdh_SiteUrl is not set."),
        ("sourceRootPath", "@empty(outputs('RESOLVE_effective')['sourceRootPath'])",
         "Source root path is not set."),
        ("templateFolderPath", "@empty(outputs('RESOLVE_effective')['templateFolderPath'])",
         "Template folder path is not set."),
        ("maxDocuments", "@lessOrEquals(outputs('RESOLVE_effective')['maxDocuments'], 0)",
         "Max documents must be greater than zero."),
    ]
    problems = ", ".join(
        "if(%s, '%s', '')" % (c[1][1:], c[2]) for c in gate_checks
    )

    a["GATE_problems"] = compose(
        "@trim(concat(" + problems + "))",
        {"RESOLVE_effective": ["Succeeded"]},
        "Collect every input problem in one pass, so a caller sees all of them at once.",
    )

    # The template folder and the source root must be disjoint. If the template
    # folder sits inside the source root, the walk enumerates templates as if
    # they were position documents and the agent is asked to convert its own
    # templates.
    a["GATE_overlap"] = compose(
        (
            "@or("
            "startsWith(concat(toLower(outputs('RESOLVE_effective')['templateFolderPath']), '/'), "
            "concat(toLower(outputs('RESOLVE_effective')['sourceRootPath']), '/')), "
            "startsWith(concat(toLower(outputs('RESOLVE_effective')['sourceRootPath']), '/'), "
            "concat(toLower(outputs('RESOLVE_effective')['templateFolderPath']), '/'))"
            ")"
        ),
        {"GATE_problems": ["Succeeded"]},
        (
            "Template folder and source root must be disjoint. If they overlap, the "
            "walk enumerates templates as sources and the agent is asked to convert "
            "its own templates."
        ),
    )

    a["GATE_check"] = {
        "type": "If",
        "description": "Stop before enumeration if configuration is unusable.",
        "runAfter": {"GATE_overlap": ["Succeeded"]},
        "expression": {
            "or": [
                {"not": {"equals": ["@outputs('GATE_problems')", ""]}},
                {"equals": ["@outputs('GATE_overlap')", True]},
            ]
        },
        "actions": {
            "GATE_fail": {
                "type": "Terminate",
                "description": "Named, actionable failure. Never a generic 'flow failed'.",
                "runAfter": {},
                "inputs": {
                    "runStatus": "Failed",
                    "runError": {
                        "code": "InvalidConfiguration",
                        "message": (
                            "@{concat('Harness configuration is invalid. ', "
                            "outputs('GATE_problems'), "
                            "if(equals(outputs('GATE_overlap'), true), "
                            "' Template folder path and source root path overlap; "
                            "they must be disjoint.', ''))}"
                        ),
                    },
                },
            }
        },
        "else": {"actions": {}},
    }

    return a


# ---------------------------------------------------------------------------
# Stage 2 - folder walk
# ---------------------------------------------------------------------------

def build_walk_actions():
    """Breadth-first walk reading only a folder's DIRECT children.

    This is the one method the investigation report verified at scale. The
    5,000-item list view threshold applies to items SharePoint must SCAN, not
    items returned, so every recursive-by-path request is a full-library scan
    in disguise: the native connector's RecursiveAll, an OData $filter on
    FileRef, and CAML Scope='RecursiveAll' all throttle identically once the
    library passes the threshold. A folder's direct children use the folder's
    own index and always succeed - proven on a folder with 587 immediate
    subfolders in a 27,000-item library, two minutes after CAML threw
    SPQueryThrottledException on that same folder.

    The reference flow used RecursiveAll. It works only because it points at a
    small demo library; against the production library it throws.

    One request per folder, using ?$expand=Folders,Files, so a folder costs one
    call rather than two.
    """
    a = {}

    a["INIT_frontier"] = {
        "type": "InitializeVariable",
        "description": "Folders still to visit. Seeded with the source root.",
        "runAfter": {"GATE_check": ["Succeeded"]},
        "inputs": {
            "variables": [{
                "name": "frontier",
                "type": "array",
                "value": [],
            }]
        },
    }

    a["INIT_next_frontier"] = {
        "type": "InitializeVariable",
        "description": "Folders discovered at the current depth, visited on the next pass.",
        "runAfter": {"INIT_frontier": ["Succeeded"]},
        "inputs": {"variables": [{"name": "nextFrontier", "type": "array", "value": []}]},
    }

    a["INIT_candidates"] = {
        "type": "InitializeVariable",
        "description": (
            "One entry per POSITION FOLDER, not per file. The skill converts one "
            "source per invocation and decides for itself which file of a "
            "pdf/docx pair to convert; iterating files would invoke the agent "
            "twice for the same position and pay for a SKIPPED reply."
        ),
        "runAfter": {"INIT_next_frontier": ["Succeeded"]},
        "inputs": {"variables": [{"name": "candidates", "type": "array", "value": []}]},
    }

    a["INIT_depth"] = {
        "type": "InitializeVariable",
        "description": "Current walk depth, against pdh_MaxFolderDepth.",
        "runAfter": {"INIT_candidates": ["Succeeded"]},
        "inputs": {"variables": [{"name": "depth", "type": "integer", "value": 0}]},
    }

    a["INIT_folders_scanned"] = {
        "type": "InitializeVariable",
        "description": "Folders enumerated so far, against pdh_MaxFoldersScanned.",
        "runAfter": {"INIT_depth": ["Succeeded"]},
        "inputs": {"variables": [{"name": "foldersScanned", "type": "integer", "value": 0}]},
    }

    a["INIT_walk_truncated"] = {
        "type": "InitializeVariable",
        "description": (
            "Set when a ceiling stopped the walk early. A truncated walk that "
            "reports itself is a bounded run; one that does not is a wrong answer "
            "presented as a complete one."
        ),
        "runAfter": {"INIT_folders_scanned": ["Succeeded"]},
        "inputs": {"variables": [{"name": "walkTruncated", "type": "string", "value": ""}]},
    }

    a["SEED_frontier"] = set_var(
        "frontier",
        "@createArray(outputs('RESOLVE_effective')['sourceRootPath'])",
        {"INIT_walk_truncated": ["Succeeded"]},
        "Seed the walk at the source root.",
    )

    # --- the walk ----------------------------------------------------------
    enumerate_folder = sp_action(
        "HttpRequest",
        {
            "dataset": "@outputs('RESOLVE_effective')['siteUrl']",
            "parameters/method": "GET",
            "parameters/uri": (
                "@{concat('_api/web/GetFolderByServerRelativePath(decodedurl=''', "
                "items('FOR_EACH_folder'), ''')?$expand=Folders,Files"
                "&$select=Folders/Name,Folders/ServerRelativeUrl,"
                "Files/Name,Files/ServerRelativeUrl,Files/TimeLastModified,Files/Length')}"
            ),
            "parameters/headers": {"Accept": "application/json;odata=nometadata"},
        },
        {},
        (
            "THE CRITICAL CALL. Direct children only, one request per folder. "
            "GetFolderByServerRelativePath(decodedurl=...) is used rather than "
            "ByServerRelativeUrl because the Url variant fails on folder names "
            "containing # or %, which are common in document libraries. "
            "$expand=Folders,Files returns subfolders and files together, halving "
            "the call count against the 600-per-minute connector limit."
        ),
    )

    # Child folders that are not excluded become the next frontier.
    queue_children = append_var(
        "nextFrontier",
        "@item()?['ServerRelativeUrl']",
        {},
        "Enqueue a non-excluded child folder for the next depth.",
    )

    filter_children = {
        "type": "If",
        "description": (
            "Exclusions applied BEFORE descending, so an excluded subtree costs "
            "nothing at all. These names are the skill's own output folders "
            "(pd_tools.py OUTPUT_FOLDERS); descending into them would feed the "
            "agent documents it previously produced."
        ),
        "runAfter": {},
        "expression": {
            "and": [
                {
                    "equals": [
                        "@contains(outputs('RESOLVE_effective')['excludedFolderNames'], item()?['Name'])",
                        False,
                    ]
                }
            ]
        },
        "actions": {"QUEUE_child_folder": queue_children},
        "else": {"actions": {}},
    }

    a["DO_UNTIL_walk"] = {
        "type": "Until",
        "description": (
            "One iteration per depth level. Bounded by pdh_MaxFolderDepth and by "
            "pdh_MaxFoldersScanned so a pathological tree cannot produce an "
            "unbounded run."
        ),
        "runAfter": {"SEED_frontier": ["Succeeded"]},
        "expression": (
            "@or(empty(variables('frontier')), "
            "greaterOrEquals(variables('depth'), outputs('RESOLVE_effective')['maxFolderDepth']), "
            "greaterOrEquals(variables('foldersScanned'), outputs('RESOLVE_effective')['maxFoldersScanned']))"
        ),
        "limit": {"count": 60, "timeout": "PT2H"},
        "actions": {
            "RESET_next_frontier": set_var(
                "nextFrontier", "@json('[]')", {},
                "Clear the next-depth accumulator at the start of each level.",
            ),
            "LIMIT_frontier": compose(
                (
                    "@take(variables('frontier'), sub("
                    "outputs('RESOLVE_effective')['maxFoldersScanned'], "
                    "variables('foldersScanned')))"
                ),
                {"RESET_next_frontier": ["Succeeded"]},
                (
                    "Enforce the remaining scan budget inside the depth level. "
                    "Checking only the Until condition would let one wide level "
                    "overshoot pdh_MaxFoldersScanned."
                ),
            ),
            "FOR_EACH_folder": {
                "type": "Foreach",
                "description": "Visit only folders that fit the remaining scan budget.",
                "runAfter": {"LIMIT_frontier": ["Succeeded"]},
                "foreach": "@outputs('LIMIT_frontier')",
                "runtimeConfiguration": {"concurrency": {"repetitions": 1}},
                "actions": {
                    "ENUMERATE_direct_children": enumerate_folder,
                    "COUNT_folder": {
                        "type": "IncrementVariable",
                        "description": "Count folders against the scan ceiling.",
                        "runAfter": {"ENUMERATE_direct_children": ["Succeeded"]},
                        "inputs": {"name": "foldersScanned", "value": 1},
                    },
                    "SELECT_convertible_files": {
                        "type": "Query",
                        "runAfter": {"COUNT_folder": ["Succeeded"]},
                        "inputs": {
                            "from": "@coalesce(body('ENUMERATE_direct_children')?['Files'], json('[]'))",
                            "where": "@contains(outputs('RESOLVE_effective')['sourceExtensions'], toLower(concat('.', last(split(item()?['Name'], '.')))))",
                        },
                        "description": (
                            "Native Filter array action selecting files supported "
                            "by the deployed skill."
                        ),
                    },
                    "IS_POSITION_FOLDER": {
                        "type": "If",
                        "description": (
                            "A folder holding at least one convertible file directly "
                            "is a position folder and becomes one unit of work."
                        ),
                        "runAfter": {"SELECT_convertible_files": ["Succeeded"]},
                        "expression": {
                            "and": [
                                {"greater": ["@length(body('SELECT_convertible_files'))", 0]}
                            ]
                        },
                        "actions": {
                            "SELECT_same_document_group": {
                                "type": "Query",
                                "runAfter": {},
                                "inputs": {
                                    "from": "@body('SELECT_convertible_files')",
                                    "where": "@equals(toLower(substring(item()?['Name'], 0, lastIndexOf(item()?['Name'], '.'))), toLower(substring(first(body('SELECT_convertible_files'))?['Name'], 0, lastIndexOf(first(body('SELECT_convertible_files'))?['Name'], '.'))))",
                                },
                            },
                            "SELECT_pdf_candidates": {
                                "type": "Query",
                                "runAfter": {
                                    "SELECT_same_document_group": ["Succeeded"]
                                },
                                "inputs": {
                                    "from": "@body('SELECT_same_document_group')",
                                    "where": "@equals(toLower(concat('.', last(split(item()?['Name'], '.')))), '.pdf')",
                                },
                            },
                            "SELECT_docx_candidates": {
                                "type": "Query",
                                "runAfter": {"SELECT_pdf_candidates": ["Succeeded"]},
                                "inputs": {
                                    "from": "@body('SELECT_same_document_group')",
                                    "where": "@equals(toLower(concat('.', last(split(item()?['Name'], '.')))), '.docx')",
                                },
                            },
                            "CHOOSE_source_file": compose(
                                (
                                    "@if(and(greater(length(body('SELECT_pdf_candidates')), 0), "
                                    "greater(length(body('SELECT_docx_candidates')), 0)), "
                                    "if(greater(ticks(coalesce(first(body('SELECT_docx_candidates'))?['TimeLastModified'], "
                                    "'1900-01-01T00:00:00Z')), ticks(coalesce(first(body('SELECT_pdf_candidates'))?['TimeLastModified'], "
                                    "'1900-01-01T00:00:00Z'))), first(body('SELECT_docx_candidates')), "
                                    "first(body('SELECT_pdf_candidates'))), "
                                    "if(greater(length(body('SELECT_pdf_candidates')), 0), "
                                    "first(body('SELECT_pdf_candidates')), first(body('SELECT_docx_candidates'))))"
                                ),
                                {"SELECT_docx_candidates": ["Succeeded"]},
                                (
                                    "Match pd_tools.py source preference: PDF unless "
                                    "the DOCX was modified later."
                                ),
                            ),
                            "ADD_candidate": append_var(
                                "candidates",
                                {
                                    "positionFolderPath": "@items('FOR_EACH_folder')",
                                    "positionFolderName": "@{last(split(items('FOR_EACH_folder'), '/'))}",
                                    "sourcePath": "@outputs('CHOOSE_source_file')?['ServerRelativeUrl']",
                                    "convertibleFileCount": "@length(body('SELECT_same_document_group'))",
                                    "depth": "@variables('depth')",
                                    "files": "@body('SELECT_same_document_group')",
                                },
                                {"CHOOSE_source_file": ["Succeeded"]},
                                (
                                    "One candidate per position folder. `files` is carried "
                                    "so the plan is inspectable and so the prompt can name "
                                    "a source without a second SharePoint call."
                                ),
                            )
                        },
                        "else": {"actions": {}},
                    },
                    "FOR_EACH_child_folder": {
                        "type": "Foreach",
                        "description": "Queue non-excluded subfolders for the next depth.",
                        "runAfter": {"IS_POSITION_FOLDER": ["Succeeded"]},
                        "foreach": "@coalesce(body('ENUMERATE_direct_children')?['Folders'], json('[]'))",
                        "runtimeConfiguration": {"concurrency": {"repetitions": 1}},
                        "actions": {"FILTER_excluded_folders": filter_children},
                    },
                },
            },
            "ADVANCE_frontier": set_var(
                "frontier",
                (
                    "@concat(skip(variables('frontier'), length(outputs('LIMIT_frontier'))), "
                    "variables('nextFrontier'))"
                ),
                {"FOR_EACH_folder": ["Succeeded"]},
                (
                    "Keep any same-level folders that did not fit the scan budget "
                    "visible so CHECK_truncation reports a partial walk."
                ),
            ),
            "ADVANCE_depth": {
                "type": "IncrementVariable",
                "description": "Track depth for the ceiling and for the plan.",
                "runAfter": {"ADVANCE_frontier": ["Succeeded"]},
                "inputs": {"name": "depth", "value": 1},
            },
        },
    }

    a["CHECK_truncation"] = {
        "type": "If",
        "description": (
            "Record whether a ceiling stopped the walk. Silence here would present "
            "a partial enumeration as a complete one."
        ),
        "runAfter": {"DO_UNTIL_walk": ["Succeeded"]},
        "expression": {
            "and": [{"not": {"equals": ["@empty(variables('frontier'))", True]}}]
        },
        "actions": {
            "SET_truncated": set_var(
                "walkTruncated",
                (
                    "@{concat('Walk stopped early: ', string(length(variables('frontier'))), "
                    "' folder(s) left unvisited at depth ', string(variables('depth')), "
                    "'. Raise pdh_MaxFolderDepth or pdh_MaxFoldersScanned.')}"
                ),
                {},
                "Name the ceiling that was hit and what to change.",
            )
        },
        "else": {"actions": {}},
    }

    return a


# ---------------------------------------------------------------------------
# Stage 3 - the plan
# ---------------------------------------------------------------------------

def build_plan_actions():
    """Emit the plan before spending anything.

    Observable stage 1. In a dry run this is the entire output, and it is
    produced at zero metered cost - which is what makes the enumeration and
    exclusion logic testable independently of the agent.
    """
    a = {}

    a["PLAN_selected"] = compose(
        "@take(variables('candidates'), outputs('RESOLVE_effective')['maxDocuments'])",
        {"CHECK_truncation": ["Succeeded"]},
        (
            "Apply the cap. Deterministic: the walk is breadth-first and ordered, "
            "so the same inputs select the same candidates."
        ),
    )

    a["PLAN"] = compose(
        {
            "runId": "@{variables('runId')}",
            "runLabel": "@outputs('RESOLVE_effective')['runLabel']",
            "plannedAt": "@{utcNow()}",
            "dryRun": "@outputs('RESOLVE_effective')['dryRun']",
            "siteUrl": "@outputs('RESOLVE_effective')['siteUrl']",
            "sourceRootPath": "@outputs('RESOLVE_effective')['sourceRootPath']",
            "templateFolderPath": "@outputs('RESOLVE_effective')['templateFolderPath']",
            "excludedFolderNames": "@outputs('RESOLVE_effective')['excludedFolderNames']",
            "sourceExtensions": "@outputs('RESOLVE_effective')['sourceExtensions']",
            "foldersScanned": "@variables('foldersScanned')",
            "depthReached": "@variables('depth')",
            "walkTruncated": "@variables('walkTruncated')",
            "positionFoldersFound": "@length(variables('candidates'))",
            "maxDocuments": "@outputs('RESOLVE_effective')['maxDocuments']",
            "plannedInvocations": "@length(outputs('PLAN_selected'))",
            "deferred": "@sub(length(variables('candidates')), length(outputs('PLAN_selected')))",
            "candidates": "@outputs('PLAN_selected')",
            "allPositionFolders": "@variables('candidates')",
        },
        {"PLAN_selected": ["Succeeded"]},
        (
            "OBSERVABLE STAGE 1. The complete plan, before any spend. "
            "`plannedInvocations` is the number of metered agent calls this run "
            "will make - the single number worth checking before enabling writes."
        ),
    )

    return a


# ---------------------------------------------------------------------------
# Stage 4 - invoke the agent and parse what it returns
# ---------------------------------------------------------------------------

def build_execution_actions():
    """Invoke the agent, then actually read the reply.

    The reference flow invoked the agent and discarded its response entirely,
    terminating Succeeded unconditionally - so it could not distinguish 400
    conversions from 400 failures. Meanwhile the skill was built to be parsed:
    it returns one JSON object with a `status` and, on failure, a `reason` drawn
    from a closed set, and pd_tools.py says of that value "The workflow branches
    on this value, so it cannot be free text."

    A consumer for that contract is precisely what did not exist. This is it.
    """
    a = {}

    a["INIT_results"] = {
        "type": "InitializeVariable",
        "description": "One outcome record per invocation.",
        "runAfter": {"PLAN": ["Succeeded"]},
        "inputs": {"variables": [{"name": "results", "type": "array", "value": []}]},
    }

    a["INIT_agent_calls"] = {
        "type": "InitializeVariable",
        "description": (
            "Count of metered agent invocations. The headline cost figure; it "
            "must never exceed maxDocuments."
        ),
        "runAfter": {"INIT_results": ["Succeeded"]},
        "inputs": {"variables": [{"name": "agentCallCount", "type": "integer", "value": 0}]},
    }

    # --- the prompt --------------------------------------------------------
    # Composed in its own action so the exact text sent is recorded in the run
    # history. Field names and shape are taken verbatim from the reference
    # flow's working prompt: SKILL.md states that when a flow invokes the agent
    # it supplies siteUrl and already-resolved server-relative paths.
    compose_prompt = compose(
        (
            "@{concat("
            "'Convert this Position Description into the PD template.', decodeUriComponent('%0A%0A'), "
            "'siteUrl: ', outputs('RESOLVE_effective')['siteUrl'], decodeUriComponent('%0A'), "
            "'templatePath: ', outputs('RESOLVE_effective')['templateFolderPath'], decodeUriComponent('%0A'), "
            "'sourcePath: ', items('FOR_EACH_candidate')['sourcePath']"
            ")}"
        ),
        {},
        (
            "OBSERVABLE STAGE 2. The exact prompt text, in its own action, so the "
            "run history answers 'what did the flow send to the agent'. "
            "templatePath is a folder by design, while sourcePath is one concrete "
            "file as required by the skill contract. Paths are already resolved "
            "and server-relative."
        ),
    )

    invoke_agent = {
        "type": "OpenApiConnection",
        "description": (
            "THE ONLY METERED OPERATION IN THIS FLOW. Invokes the existing "
            "PD Conversion Assistant agent - reused by schema name, not "
            "recreated. Mechanism (shared_agentnode / InvokeAgent / body/agentId "
            "+ body/prompt) is taken from the reference export rather than "
            "guessed."
        ),
        "runAfter": {"COMPOSE_prompt": ["Succeeded"]},
        "runtimeConfiguration": {"retryPolicy": {"type": "None"}},
        "inputs": {
            "host": {
                "apiId": "/providers/Microsoft.PowerApps/apis/" + AGENT,
                "connectionName": AGENT,
                "operationId": "InvokeAgent",
            },
            "parameters": {
                "body/agentId": "@outputs('RESOLVE_effective')['agentId']",
                "body/prompt": "@outputs('COMPOSE_prompt')",
            },
            "authentication": "@parameters('$authentication')",
        },
    }

    count_call = {
        "type": "IncrementVariable",
        "description": (
            "Count the call whether or not it succeeded. A failed invocation may "
            "still have consumed capacity, so counting only successes would "
            "under-report cost."
        ),
        "runAfter": {"INVOKE_agent": ["Succeeded", "Failed", "TimedOut"]},
        "inputs": {"name": "agentCallCount", "value": 1},
    }

    capture_raw = compose(
        "@coalesce(body('INVOKE_agent'), '')",
        {"COUNT_agent_call": ["Succeeded"]},
        (
            "OBSERVABLE STAGE 3. The agent's reply, verbatim and unparsed, before "
            "any interpretation. If parsing later fails this is still in the run "
            "history, which is the difference between a diagnosable failure and a "
            "mystery."
        ),
    )

    # The skill promises "one JSON object and nothing else - no prose before or
    # after, no code fence". Trusting that promise unconditionally would turn a
    # chatty reply into a flow crash, so parse defensively and treat a
    # non-conforming reply as a named failure.
    extract_text = compose(
        (
            "@if(empty(coalesce(body('INVOKE_agent')?['text'], "
            "body('INVOKE_agent')?['response'], body('INVOKE_agent')?['output'])), "
            "string(outputs('CAPTURE_agent_response')), "
            "string(coalesce(body('INVOKE_agent')?['text'], "
            "body('INVOKE_agent')?['response'], body('INVOKE_agent')?['output'])))"
        ),
        {"CAPTURE_agent_response": ["Succeeded"]},
        (
            "Reduce the connector envelope to the reply text. The InvokeAgent "
            "response shape is one of the few things the export does not pin "
            "down, so both a wrapped and a bare reply are handled."
        ),
    )

    parse_report = {
        "type": "ParseJson",
        "description": (
            "Parse the skill's run report. Schema mirrors cmd_report's return "
            "value in pd_tools.py; `status` and `reason` are the fields the "
            "harness branches on."
        ),
        "runAfter": {"EXTRACT_reply_text": ["Succeeded"]},
        "inputs": {
            "content": "@outputs('EXTRACT_reply_text')",
            "schema": {
                "type": "object",
                "properties": {
                    "status": {"type": "string"},
                    "reason": {"type": "string"},
                    "sourceFile": {"type": "string"},
                    "sourceChosenBecause": {"type": "string"},
                    "notes": {"type": "string"},
                    "outputs": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "template": {"type": "string"},
                                "kind": {"type": "string"},
                                "destinationFolderPath": {"type": "string"},
                                "outputFileName": {"type": "string"},
                                "bytesSent": {},
                                "bytesStored": {},
                                "verdict": {"type": "string"},
                                "verdictNote": {"type": "string"},
                                "missingFields": {"type": "array"},
                                "removed": {"type": "array"},
                                "highlightCleared": {},
                                "archivedAs": {"type": "array"},
                            },
                        },
                    },
                },
            },
        },
    }

    # Classification. SKIPPED is deliberately not folded into FAILED:
    # pd_tools.py notes that reporting a failed conversion as skipped "hides it
    # from whoever counts how many documents were actually produced" - the same
    # argument applies in reverse to the harness.
    classify = compose(
        (
            "@{if(equals(coalesce(body('PARSE_agent_report')?['status'], ''), 'OK'), 'OK', "
            "if(equals(coalesce(body('PARSE_agent_report')?['status'], ''), 'SKIPPED'), 'SKIPPED', "
            "if(equals(coalesce(body('PARSE_agent_report')?['status'], ''), 'FAILED'), 'FAILED', "
            "'UNPARSEABLE')))}"
        ),
        {},
        (
            "Classify the reply. UNPARSEABLE is its own outcome rather than being "
            "folded into FAILED: a conversion that failed and a reply the harness "
            "could not read have different causes and different fixes."
        ),
    )

    record_result = append_var(
        "results",
        {
            "positionFolderPath": "@items('FOR_EACH_candidate')['positionFolderPath']",
            "positionFolderName": "@items('FOR_EACH_candidate')['positionFolderName']",
            "outcome": "@outputs('CLASSIFY_outcome')",
            "status": "@coalesce(body('PARSE_agent_report')?['status'], '')",
            "reason": "@coalesce(body('PARSE_agent_report')?['reason'], '')",
            "sourceFile": "@coalesce(body('PARSE_agent_report')?['sourceFile'], '')",
            "sourceChosenBecause": "@coalesce(body('PARSE_agent_report')?['sourceChosenBecause'], '')",
            "notes": "@coalesce(body('PARSE_agent_report')?['notes'], '')",
            "outputs": "@coalesce(body('PARSE_agent_report')?['outputs'], json('[]'))",
            "promptSent": "@outputs('COMPOSE_prompt')",
            "completedAt": "@{utcNow()}",
        },
        {"CLASSIFY_outcome": ["Succeeded"]},
        (
            "OBSERVABLE STAGE 4. One record per document, carrying the prompt that "
            "was sent alongside what came back - so a single record answers the "
            "whole traceability question without cross-referencing actions."
        ),
    )

    record_unparseable = append_var(
        "results",
        {
            "positionFolderPath": "@items('FOR_EACH_candidate')['positionFolderPath']",
            "positionFolderName": "@items('FOR_EACH_candidate')['positionFolderName']",
            "outcome": "UNPARSEABLE",
            "status": "",
            "reason": "harness-could-not-parse-reply",
            "notes": (
                "@{concat('The agent reply was not the single JSON object the skill "
                "contract specifies. Raw reply: ', "
                "substring(string(outputs('CAPTURE_agent_response')), 0, "
                "min(2000, length(string(outputs('CAPTURE_agent_response'))))))}"
            ),
            "outputs": "@json('[]')",
            "promptSent": "@outputs('COMPOSE_prompt')",
            "completedAt": "@{utcNow()}",
        },
        {},
        (
            "A reply that does not parse is recorded as its own outcome with the "
            "raw text attached, rather than failing the run with no evidence. "
            "`reason` is deliberately outside the skill's closed set: it is the "
            "harness's own failure, not the skill's."
        ),
    )

    handle_parsed_reply = {
        "type": "Scope",
        "description": "Classify and record a successfully parsed agent report.",
        "runAfter": {"TRY_parse_agent_report": ["Succeeded"]},
        "actions": {
            "CLASSIFY_outcome": classify,
            "RECORD_result": record_result,
        },
    }
    record_unparseable["runAfter"] = {
        "TRY_parse_agent_report": ["Failed", "TimedOut"]
    }
    parse_report["runAfter"] = {}

    a["EXECUTE_check_dry_run"] = {
        "type": "If",
        "description": (
            "THE COST GATE. In a dry run nothing below this point executes and "
            "the agent is never invoked. Everything above - the walk, the "
            "exclusions, the plan - has already run and is inspectable."
        ),
        "runAfter": {"INIT_agent_calls": ["Succeeded"]},
        "expression": {
            "and": [{"equals": ["@outputs('RESOLVE_effective')['dryRun']", False]}]
        },
        "actions": {
            "FOR_EACH_candidate": {
                "type": "Foreach",
                "description": (
                    "One iteration per position folder. Sequential by default: "
                    "concurrency multiplies the capacity burn rate, and the "
                    "reference flow's own concurrency of 1 suggests this was "
                    "never measured. Raise it only after measuring."
                ),
                "runAfter": {},
                "foreach": "@outputs('PLAN_selected')",
                "runtimeConfiguration": {"concurrency": {"repetitions": 1}},
                "actions": {
                    "COMPOSE_prompt": compose_prompt,
                    "INVOKE_agent": invoke_agent,
                    "COUNT_agent_call": count_call,
                    "CAPTURE_agent_response": capture_raw,
                    "EXTRACT_reply_text": extract_text,
                    "TRY_parse_agent_report": {
                        "type": "Scope",
                        "description": (
                            "Scope status is the supported signal for whether "
                            "ParseJson succeeded."
                        ),
                        "runAfter": {"EXTRACT_reply_text": ["Succeeded"]},
                        "actions": {"PARSE_agent_report": parse_report},
                    },
                    "HANDLE_reply": handle_parsed_reply,
                    "RECORD_unparseable": record_unparseable,
                },
            }
        },
        "else": {"actions": {}},
    }

    return a


# ---------------------------------------------------------------------------
# Stage 5 - summarise and terminate honestly
# ---------------------------------------------------------------------------

def build_summary_actions():
    """Roll up outcomes and set a terminal status that reflects them.

    The reference flow ended with an unconditional Terminate: Succeeded. The
    agent's own instructions say "A conversion reported as complete when it is
    not is worse than one reported as failed" - and the flow around it did
    exactly that. Here the terminal status is derived from the outcomes.
    """
    a = {}
    filters = {
        "FILTER_succeeded": "@equals(item()?['outcome'], 'OK')",
        "FILTER_skipped": "@equals(item()?['outcome'], 'SKIPPED')",
        "FILTER_failed": "@equals(item()?['outcome'], 'FAILED')",
        "FILTER_unparseable": "@equals(item()?['outcome'], 'UNPARSEABLE')",
        "FILTER_failure_reasons": (
            "@or(equals(item()?['outcome'], 'FAILED'), "
            "equals(item()?['outcome'], 'UNPARSEABLE'))"
        ),
    }
    for name, condition in filters.items():
        a[name] = {
            "type": "Query",
            "runAfter": {"EXECUTE_check_dry_run": ["Succeeded"]},
            "inputs": {"from": "@variables('results')", "where": condition},
        }

    a["SUMMARY"] = compose(
        {
            "runId": "@{variables('runId')}",
            "runLabel": "@outputs('RESOLVE_effective')['runLabel']",
            "completedAt": "@{utcNow()}",
            "dryRun": "@outputs('RESOLVE_effective')['dryRun']",
            "agentId": "@outputs('RESOLVE_effective')['agentId']",
            "foldersScanned": "@variables('foldersScanned')",
            "walkTruncated": "@variables('walkTruncated')",
            "positionFoldersFound": "@length(variables('candidates'))",
            "planned": "@length(outputs('PLAN_selected'))",
            "agentCallCount": "@variables('agentCallCount')",
            "succeeded": "@length(body('FILTER_succeeded'))",
            "skipped": "@length(body('FILTER_skipped'))",
            "failed": "@length(body('FILTER_failed'))",
            "unparseable": "@length(body('FILTER_unparseable'))",
            "failureReasons": "@body('FILTER_failure_reasons')",
            "results": "@variables('results')",
            "plan": "@outputs('PLAN')",
        },
        {name: ["Succeeded"] for name in filters},
        (
            "OBSERVABLE STAGE 5. The run summary. `agentCallCount` is the cost "
            "figure; `skipped` is kept separate from `failed` because "
            "another-format-preferred is a normal outcome and counting it as a "
            "failure would misreport a healthy run."
        ),
    )

    a["RESPOND"] = {
        "type": "Response",
        "description": (
            "Return the whole summary to the caller, so an interactive run needs "
            "no trip to the run history."
        ),
        "runAfter": {"SUMMARY": ["Succeeded"]},
        "inputs": {"statusCode": 200, "body": "@outputs('SUMMARY')"},
    }

    a["TERMINATE_by_outcome"] = {
        "type": "If",
        "description": (
            "Terminal status derived from outcomes, never assumed. This is the "
            "single most important difference from the reference flow, which "
            "always reported success."
        ),
        "runAfter": {"RESPOND": ["Succeeded"]},
        "expression": {
            "and": [
                {
                    "greater": [
                        "@add(add(outputs('SUMMARY')['failed'], outputs('SUMMARY')['unparseable']), outputs('SUMMARY')['skipped'])",
                        0,
                    ]
                }
            ]
        },
        "actions": {
            "TERMINATE_failed": {
                "type": "Terminate",
                "description": "At least one conversion failed. Say so.",
                "runAfter": {},
                "inputs": {
                    "runStatus": "Failed",
                    "runError": {
                        "code": "ConversionFailures",
                        "message": (
                            "@{concat(string(outputs('SUMMARY')['failed']), ' conversion(s) failed, ', "
                            "string(outputs('SUMMARY')['skipped']), ' produced no document because source preference changed, and ', "
                            "string(outputs('SUMMARY')['unparseable']), ' reply/replies could not be parsed, out of ', "
                            "string(outputs('SUMMARY')['agentCallCount']), ' agent call(s). See SUMMARY.results.')}"
                        ),
                    },
                },
            }
        },
        "else": {
            "actions": {
                "TERMINATE_succeeded": {
                    "type": "Terminate",
                    "description": "Every attempted conversion produced a verified document.",
                    "runAfter": {},
                    "inputs": {"runStatus": "Succeeded"},
                }
            }
        },
    }

    return a


# ---------------------------------------------------------------------------

def build_definition():
    actions = {}
    actions.update(build_resolve_actions())
    actions.update(build_walk_actions())
    actions.update(build_plan_actions())
    actions.update(build_execution_actions())
    actions.update(build_summary_actions())

    return {
        "properties": {
            "connectionReferences": {
                SP: {
                    "api": {"name": SP},
                    "connection": {"connectionReferenceLogicalName": "pdh_sharedsharepointonline"},
                    "runtimeSource": "embedded",
                },
                AGENT: {
                    "api": {"name": AGENT},
                    "connection": {"connectionReferenceLogicalName": "pdh_sharedagentnode"},
                    "runtimeSource": "embedded",
                },
            },
            "definition": {
                "$schema": "https://schema.management.azure.com/providers/Microsoft.Logic/schemas/2016-06-01/workflowdefinition.json#",
                "contentVersion": "1.0.0.0",
                "parameters": {
                    "$authentication": {"defaultValue": {}, "type": "SecureObject"},
                    "$connections": {"defaultValue": {}, "type": "Object"},
                },
                "triggers": build_trigger(),
                "actions": actions,
                "outputs": {},
                "description": (
                    "PD Conversion Harness. Walks position folders using direct-children "
                    "enumeration only, plans the work, and invokes the existing "
                    "PD Conversion Assistant agent once per position folder - then reads "
                    "what the agent returned and reports it. Every stage is observable: "
                    "the plan, the prompt sent, the raw reply, the parsed outcome, the "
                    "summary."
                ),
            },
            "schemaVersion": "1.0.0.0",
        }
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="exit non-zero if the committed flow differs from generated output")
    args = parser.parse_args()

    generated = json.dumps(build_definition(), indent=2) + "\n"

    if args.check:
        if not os.path.exists(OUTPUT_FILE):
            print("ERROR: %s does not exist." % OUTPUT_FILE)
            sys.exit(1)
        with open(OUTPUT_FILE, encoding="utf-8") as handle:
            if handle.read() != generated:
                print("ERROR: harness flow is out of date with its generator.\n"
                      "Run: python3 scripts/generate_harness_flow.py")
                sys.exit(1)
        print("Harness flow is up to date with its generator.")
        return

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as handle:
        handle.write(generated)
    print("Wrote %s" % OUTPUT_FILE)


if __name__ == "__main__":
    main()
