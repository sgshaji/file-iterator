#!/usr/bin/env python3
"""Generate the publish trigger (A1) and paged planner (A2)."""

import argparse
import json
import os
import sys


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKFLOW_DIR = os.path.join(ROOT, "solution", "src", "Workflows")
A1_PATH = os.path.join(WORKFLOW_DIR, "A-PlanRegenerationRun.json")
A2_PATH = os.path.join(WORKFLOW_DIR, "A2-ContinueRegenerationPlan.json")
A3_PATH = os.path.join(WORKFLOW_DIR, "A3-ApproveRegenerationPlan.json")

SHAREPOINT = {
    "runtimeSource": "embedded",
    "connection": {"connectionReferenceLogicalName": "fi_sharedsharepointonline"},
    "api": {"name": "shared_sharepointonline"},
}
def sharepoint(operation, parameters, run_after=None, description=None):
    action = {
        "runAfter": run_after or {},
        "type": "OpenApiConnection",
        "inputs": {
            "host": {
                "connectionName": "shared_sharepointonline",
                "operationId": operation,
                "apiId": "/providers/Microsoft.PowerApps/apis/shared_sharepointonline",
            },
            "parameters": parameters,
            "authentication": "@parameters('$authentication')",
        },
    }
    if description:
        action["description"] = description
    return action


def patch_run(parameters, run_after=None, description=None):
    return sharepoint("PatchItem", parameters, run_after, description)


def base_properties(connections, trigger, actions, description):
    return {
        "properties": {
            "connectionReferences": connections,
            "definition": {
                "$schema": "https://schema.management.azure.com/providers/Microsoft.Logic/schemas/2016-06-01/workflowdefinition.json#",
                "contentVersion": "1.0.0.0",
                "parameters": {
                    "$connections": {"defaultValue": {}, "type": "Object"},
                    "$authentication": {"defaultValue": {}, "type": "SecureObject"},
                },
                "triggers": trigger,
                "actions": actions,
                "outputs": {},
                "description": description,
            },
            "schemaVersion": "1.0.0.0",
        }
    }


def build_a1():
    trigger = {
        "When_a_template_is_created_or_modified": {
            "type": "OpenApiConnection",
            "recurrence": {"frequency": "Minute", "interval": 5},
            "splitOn": "@triggerOutputs()?['body/value']",
            "runtimeConfiguration": {"concurrency": {"runs": 1}},
            "inputs": {
                "host": {
                    "connectionName": "shared_sharepointonline",
                    "operationId": "GetOnUpdatedFileItems",
                    "apiId": "/providers/Microsoft.PowerApps/apis/shared_sharepointonline",
                },
                "parameters": {
                    "dataset": "@parameters('fi_SiteAddress (fi_SiteAddress)')",
                    "table": "@parameters('fi_LibraryUrlName (fi_LibraryUrlName)')",
                    "folderPath": "@parameters('fi_TemplateFolderPath (fi_TemplateFolderPath)')",
                },
                "authentication": "@parameters('$authentication')",
            },
            "description": (
                "Scoped to the template folder. Trigger concurrency is one so "
                "duplicate deliveries cannot race the active-run check."
            ),
        }
    }

    create_run = sharepoint(
        "PostItem",
        {
            "dataset": "@parameters('fi_SiteAddress (fi_SiteAddress)')",
            "table": "@parameters('fi_RunListName (fi_RunListName)')",
            "item/Title": "@variables('RunId')",
            "item/RunId": "@variables('RunId')",
            "item/RunKey": "@outputs('Compose_run_key')",
            "item/TemplateName": "@variables('TemplateName')",
            "item/TemplateFingerprint": "@outputs('Compose_template_fingerprint')",
            "item/TemplateUrl": "@outputs('Compose_template_url')",
            "item/TemplateVersion": "@{triggerOutputs()?['body/{VersionNumber}']}",
            "item/Status/Value": "Planning",
            "item/PlannedCount": 0,
            "item/SucceededCount": 0,
            "item/FailedCount": 0,
            "item/SkippedCount": 0,
            "item/AgentCallCount": 0,
            "item/IsDryRun": "@parameters('fi_DryRun (fi_DryRun)')",
            "item/RequiresSecondConfirmation": False,
            "item/PlanningCursorId": 0,
            "item/IndexSnapshotRunId": "@first(body('Get_latest_completed_index_walk')?['value'])?['WalkRunId']",
            "item/IndexSnapshotItemId": "@first(body('Get_latest_completed_index_walk')?['value'])?['ID']",
            "item/RequestedBy": "@triggerOutputs()?['body/Editor/Email']",
        },
        description=(
            "Creates only the durable planning header. A2 pages the index and "
            "writes work items, so this trigger never accumulates an unbounded "
            "action output."
        ),
    )

    actions = {
        "GATE_explicit_publish": {
            "runAfter": {},
            "type": "If",
            "expression": {
                "equals": [
                    "@toLower(coalesce(triggerOutputs()?['body/Status']?['Value'], ''))",
                    "published",
                ]
            },
            "actions": {
                "Init_TemplateName": {
                    "runAfter": {},
                    "type": "InitializeVariable",
                    "inputs": {
                        "variables": [
                            {
                                "name": "TemplateName",
                                "type": "string",
                                "value": "@{triggerOutputs()?['body/{FilenameWithExtension}']}",
                            }
                        ]
                    },
                },
                "Init_RunId": {
                    "runAfter": {"Init_TemplateName": ["Succeeded"]},
                    "type": "InitializeVariable",
                    "inputs": {
                        "variables": [
                            {"name": "RunId", "type": "string", "value": "@{guid()}"}
                        ]
                    },
                },
                "Compose_template_url": {
                    "runAfter": {"Init_RunId": ["Succeeded"]},
                    "type": "Compose",
                    "inputs": "@{concat(parameters('fi_TemplateFolderPath (fi_TemplateFolderPath)'), '/', triggerOutputs()?['body/{FilenameWithExtension}'])}",
                },
                "Compose_template_fingerprint": {
                    "runAfter": {"Compose_template_url": ["Succeeded"]},
                    "type": "Compose",
                    "inputs": "@{concat(coalesce(triggerOutputs()?['body/{UniqueId}'], string(triggerOutputs()?['body/ID'])), ':', coalesce(triggerOutputs()?['body/{VersionNumber}'], ''))}",
                    "description": (
                        "Identity of an explicitly published template version. "
                        "It is stable across duplicate trigger deliveries."
                    ),
                },
                "Compose_run_key": {
                    "runAfter": {"Compose_template_fingerprint": ["Succeeded"]},
                    "type": "Compose",
                    "inputs": "@{concat(outputs('Compose_template_fingerprint'), ':', if(parameters('fi_DryRun (fi_DryRun)'), 'dry', 'live'))}",
                },
                "Get_latest_completed_index_walk": sharepoint(
                    "GetItems",
                    {
                        "dataset": "@parameters('fi_SiteAddress (fi_SiteAddress)')",
                        "table": "@parameters('fi_IndexWalkRunListName (fi_IndexWalkRunListName)')",
                        "$filter": "Status eq 'Completed'",
                        "$orderby": "CompletedAt desc",
                        "$top": 1,
                    },
                    {"Compose_run_key": ["Succeeded"]},
                    "Planning cannot begin until one complete, reconciled index snapshot exists.",
                ),
                "GATE_index_ready": {
                    "runAfter": {"Get_latest_completed_index_walk": ["Succeeded"]},
                    "type": "If",
                    "expression": {
                        "equals": [
                            "@length(body('Get_latest_completed_index_walk')?['value'])",
                            0,
                        ]
                    },
                    "actions": {
                        "Terminate_index_not_ready": {
                            "runAfter": {},
                            "type": "Terminate",
                            "inputs": {
                                "runStatus": "Failed",
                                "runError": {
                                    "code": "IndexNotReady",
                                    "message": (
                                        "No completed index backfill exists. Run E1 "
                                        "and wait for E2 reconciliation to complete."
                                    ),
                                },
                            },
                        }
                    },
                    "else": {
                        "actions": {
                            "Get_active_duplicate": sharepoint(
                                "GetItems",
                                {
                                    "dataset": "@parameters('fi_SiteAddress (fi_SiteAddress)')",
                                    "table": "@parameters('fi_RunListName (fi_RunListName)')",
                                    "$filter": (
                                        "RunKey eq '@{replace(outputs('Compose_run_key'),'''','''''')}' "
                                        "and Status ne 'Cancelled' and Status ne "
                                        "'RolledBack' and Status ne 'CompletedWithErrors'"
                                    ),
                                    "$top": 1,
                                },
                            ),
                            "GATE_duplicate_delivery": {
                                "runAfter": {"Get_active_duplicate": ["Succeeded"]},
                                "type": "If",
                                "expression": {
                                    "greater": [
                                        "@length(body('Get_active_duplicate')?['value'])",
                                        0,
                                    ]
                                },
                                "actions": {
                                    "Terminate_duplicate": {
                                        "runAfter": {},
                                        "type": "Terminate",
                                        "inputs": {"runStatus": "Succeeded"},
                                    }
                                },
                                "else": {"actions": {"Create_planning_run": create_run}},
                            },
                        }
                    },
                },
            },
            "else": {"actions": {}},
            "description": "Only an explicit Published value creates a planning run.",
        }
    }
    ready_actions = (
        actions["GATE_explicit_publish"]["actions"]["GATE_index_ready"]
        ["else"]["actions"]
    )
    duplicate_lookup = ready_actions.pop("Get_active_duplicate")
    duplicate_gate = ready_actions.pop("GATE_duplicate_delivery")
    duplicate_lookup["runAfter"] = {"Get_active_rollback": ["Succeeded"]}
    ready_actions["Get_newer_index_walk"] = sharepoint(
        "GetItems",
        {
            "dataset": "@parameters('fi_SiteAddress (fi_SiteAddress)')",
            "table": "@parameters('fi_IndexWalkRunListName (fi_IndexWalkRunListName)')",
            "$filter": (
                "ID gt @{first(body('Get_latest_completed_index_walk')?['value'])?['ID']}"
            ),
            "$top": 1,
        },
    )
    ready_actions["GATE_latest_index_is_complete"] = {
        "runAfter": {"Get_newer_index_walk": ["Succeeded"]},
        "type": "If",
        "expression": {
            "greater": ["@length(body('Get_newer_index_walk')?['value'])", 0]
        },
        "actions": {
            "Terminate_newer_index_walk": {
                "runAfter": {},
                "type": "Terminate",
                "inputs": {
                    "runStatus": "Failed",
                    "runError": {
                        "code": "IndexSnapshotNotCurrent",
                        "message": (
                            "A newer index walk is queued, active or failed. "
                            "Planning waits for a newer Completed snapshot."
                        ),
                    },
                },
            }
        },
        "else": {"actions": {}},
    }
    ready_actions["Get_active_rollback"] = sharepoint(
        "GetItems",
        {
            "dataset": "@parameters('fi_SiteAddress (fi_SiteAddress)')",
            "table": "@parameters('fi_RunListName (fi_RunListName)')",
            "$filter": "Status eq 'RollbackInProgress'",
            "$top": 1,
        },
        run_after={"GATE_no_unresolved_side_effects": ["Succeeded"]},
    )
    ready_actions["Get_unresolved_side_effects"] = sharepoint(
        "GetItems",
        {
            "dataset": "@parameters('fi_SiteAddress (fi_SiteAddress)')",
            "table": "@parameters('fi_WorkItemListName (fi_WorkItemListName)')",
            "$filter": (
                "TemplateName eq '@{replace(variables('TemplateName'),'''','''''')}' "
                "and TemplateFingerprint eq '@{outputs('Compose_template_fingerprint')}' "
                "and Status eq 'Failed' and (AgentEffectState eq 'ParsedManifest' or AgentEffectState eq 'UnknownSideEffects')"
            ),
            "$top": 1,
        },
        run_after={"GATE_latest_index_is_complete": ["Succeeded"]},
    )
    ready_actions["GATE_no_unresolved_side_effects"] = {
        "runAfter": {"Get_unresolved_side_effects": ["Succeeded"]},
        "type": "If",
        "expression": {
            "greater": [
                "@length(body('Get_unresolved_side_effects')?['value'])",
                0,
            ]
        },
        "actions": {
            "Terminate_unresolved_side_effects": {
                "runAfter": {},
                "type": "Terminate",
                "inputs": {
                    "runStatus": "Failed",
                    "runError": {
                        "code": "PriorFailedAttemptNeedsRollback",
                        "message": (
                            "A prior failed attempt for this template version has "
                            "an agent manifest. Roll it back before planning again."
                        ),
                    },
                },
            }
        },
        "else": {"actions": {}},
    }
    ready_actions["GATE_no_active_rollback"] = {
        "runAfter": {"Get_active_rollback": ["Succeeded"]},
        "type": "If",
        "expression": {
            "greater": ["@length(body('Get_active_rollback')?['value'])", 0]
        },
        "actions": {
            "Terminate_rollback_in_progress": {
                "runAfter": {},
                "type": "Terminate",
                "inputs": {
                    "runStatus": "Failed",
                    "runError": {
                        "code": "RollbackInProgress",
                        "message": "No regeneration plan can start while rollback is active.",
                    },
                },
            }
        },
        "else": {
            "actions": {
                "Get_active_duplicate": duplicate_lookup,
                "GATE_duplicate_delivery": duplicate_gate,
            }
        },
    }
    duplicate_lookup["runAfter"] = {}

    return base_properties(
        {"shared_sharepointonline": SHAREPOINT},
        trigger,
        actions,
        "A1 creates one durable planning run for an explicitly published template.",
    )


def build_a2():
    trigger = {
        "Recurrence": {
            "type": "Recurrence",
            "recurrence": {"frequency": "Minute", "interval": 2},
            "runtimeConfiguration": {"concurrency": {"runs": 1}},
            "description": "Consumes one bounded DocumentIndex page per run.",
        }
    }

    actions = {
        "Get_planning_run": sharepoint(
            "GetItems",
            {
                "dataset": "@parameters('fi_SiteAddress (fi_SiteAddress)')",
                "table": "@parameters('fi_RunListName (fi_RunListName)')",
                "$filter": "Status eq 'Planning'",
                "$orderby": "Created asc",
                "$top": 1,
            },
        ),
        "Exit_if_no_planning_run": {
            "runAfter": {"Get_planning_run": ["Succeeded"]},
            "type": "If",
            "expression": {
                "equals": ["@length(body('Get_planning_run')?['value'])", 0]
            },
            "actions": {
                "Terminate_idle": {
                    "runAfter": {},
                    "type": "Terminate",
                    "inputs": {"runStatus": "Succeeded"},
                }
            },
            "else": {"actions": {}},
        },
        "Init_PagePlannedCount": {
            "runAfter": {"Exit_if_no_planning_run": ["Succeeded"]},
            "type": "InitializeVariable",
            "inputs": {
                "variables": [
                    {"name": "PagePlannedCount", "type": "integer", "value": 0}
                ]
            },
        },
        "Get_source_page": sharepoint(
            "GetItems",
            {
                "dataset": "@parameters('fi_SiteAddress (fi_SiteAddress)')",
                "table": "@parameters('fi_IndexListName (fi_IndexListName)')",
                "$filter": "ID gt @{int(coalesce(first(body('Get_planning_run')?['value'])?['PlanningCursorId'], 0))} and DocumentRole eq 'Source' and IsExcluded eq 0",
                "$orderby": "ID asc",
                "$top": "@parameters('fi_PlanningPageSize (fi_PlanningPageSize)')",
            },
            {"Init_PagePlannedCount": ["Succeeded"]},
            "Bounded page; work items are persisted before the next page is read.",
        ),
        "HANDLE_page": {
            "runAfter": {"Get_source_page": ["Succeeded"]},
            "type": "If",
            "expression": {
                "greater": ["@length(body('Get_source_page')?['value'])", 0]
            },
            "actions": {
                "For_each_candidate": {
                    "runAfter": {},
                    "type": "Foreach",
                    "foreach": "@body('Get_source_page')?['value']",
                    "runtimeConfiguration": {"concurrency": {"repetitions": 1}},
                    "actions": {
                        "Get_document_group": sharepoint(
                            "GetItems",
                            {
                                "dataset": "@parameters('fi_SiteAddress (fi_SiteAddress)')",
                                "table": "@parameters('fi_IndexListName (fi_IndexListName)')",
                                "$filter": (
                                    "ParentFolderUniqueId eq "
                                    "'@{items('For_each_candidate')?['ParentFolderUniqueId']}' "
                                    "and DocumentStem eq "
                                    "'@{replace(items('For_each_candidate')?['DocumentStem'],'''','''''')}' "
                                    "and DocumentRole eq 'Source' and IsExcluded eq 0"
                                ),
                                "$top": 10,
                            },
                            description=(
                                "Indexed folder GUID plus stem identifies all formats "
                                "of one real document without filtering on a long path."
                            ),
                        ),
                        "Filter_preferred_competitors": {
                            "runAfter": {"Get_document_group": ["Succeeded"]},
                            "type": "Query",
                            "inputs": {
                                "from": "@body('Get_document_group')?['value']",
                                "where": "@and(not(equals(item()?['UniqueId'], items('For_each_candidate')?['UniqueId'])), or(and(equals(items('For_each_candidate')?['Extension'], '.pdf'), equals(item()?['Extension'], '.docx'), greater(ticks(coalesce(item()?['TimeLastModified'], '1900-01-01T00:00:00Z')), ticks(coalesce(items('For_each_candidate')?['TimeLastModified'], '1900-01-01T00:00:00Z')))), and(equals(items('For_each_candidate')?['Extension'], '.docx'), equals(item()?['Extension'], '.pdf'), greaterOrEquals(ticks(coalesce(item()?['TimeLastModified'], '1900-01-01T00:00:00Z')), ticks(coalesce(items('For_each_candidate')?['TimeLastModified'], '1900-01-01T00:00:00Z'))))))",
                            },
                            "description": (
                                "Native Filter array action implementing the skill's "
                                "preference: PDF wins unless DOCX is newer."
                            ),
                        },
                        "GATE_preferred_source": {
                            "runAfter": {
                                "Filter_preferred_competitors": ["Succeeded"]
                            },
                            "type": "If",
                            "expression": {
                                "equals": [
                                    "@length(body('Filter_preferred_competitors'))",
                                    0,
                                ]
                            },
                            "actions": {
                                "Get_existing_or_prior_success": sharepoint(
                                    "GetItems",
                                    {
                                        "dataset": "@parameters('fi_SiteAddress (fi_SiteAddress)')",
                                        "table": "@parameters('fi_WorkItemListName (fi_WorkItemListName)')",
                                        "$filter": (
                                            "SourceUniqueId eq "
                                            "'@{items('For_each_candidate')?['UniqueId']}' and "
                                            "((RunId eq '@{first(body('Get_planning_run')?['value'])?['RunId']}') "
                                            "or (TemplateName eq "
                                            "'@{replace(first(body('Get_planning_run')?['value'])?['TemplateName'],'''','''''')}' "
                                            "and TemplateFingerprint eq "
                                            "'@{first(body('Get_planning_run')?['value'])?['TemplateFingerprint']}' "
                                            "and Status eq 'Succeeded'))"
                                        ),
                                        "$top": 1,
                                    },
                                ),
                                "GATE_not_already_current": {
                                    "runAfter": {
                                        "Get_existing_or_prior_success": ["Succeeded"]
                                    },
                                    "type": "If",
                                    "expression": {
                                        "equals": [
                                            "@length(body('Get_existing_or_prior_success')?['value'])",
                                            0,
                                        ]
                                    },
                                    "actions": {
                                        "Create_work_item": sharepoint(
                                            "PostItem",
                                            {
                                                "dataset": "@parameters('fi_SiteAddress (fi_SiteAddress)')",
                                                "table": "@parameters('fi_WorkItemListName (fi_WorkItemListName)')",
                                                "item/Title": "@items('For_each_candidate')?['UniqueId']",
                                                "item/RunId": "@first(body('Get_planning_run')?['value'])?['RunId']",
                                                "item/SourceUniqueId": "@items('For_each_candidate')?['UniqueId']",
                                                "item/SourceDocumentKey": "@items('For_each_candidate')?['DocumentKey']",
                                                "item/SourceUrl": "@items('For_each_candidate')?['ServerRelativeUrl']",
                                                "item/SourceSizeBytes": "@int(coalesce(items('For_each_candidate')?['SizeBytes'], 0))",
                                                "item/TemplateName": "@first(body('Get_planning_run')?['value'])?['TemplateName']",
                                                "item/TemplateFingerprint": "@first(body('Get_planning_run')?['value'])?['TemplateFingerprint']",
                                                "item/TemplateUrl": "@first(body('Get_planning_run')?['value'])?['TemplateUrl']",
                                                "item/Status/Value": "Pending",
                                                "item/AttemptCount": 0,
                                            },
                                        ),
                                        "Increment_page_planned": {
                                            "runAfter": {
                                                "Create_work_item": ["Succeeded"]
                                            },
                                            "type": "IncrementVariable",
                                            "inputs": {
                                                "name": "PagePlannedCount",
                                                "value": 1,
                                            },
                                        },
                                    },
                                    "else": {"actions": {}},
                                },
                            },
                            "else": {"actions": {}},
                        },
                    },
                },
                "Advance_planning_cursor": patch_run(
                    {
                        "dataset": "@parameters('fi_SiteAddress (fi_SiteAddress)')",
                        "table": "@parameters('fi_RunListName (fi_RunListName)')",
                        "id": "@first(body('Get_planning_run')?['value'])?['ID']",
                        "item/PlanningCursorId": "@last(body('Get_source_page')?['value'])?['ID']",
                        "item/PlannedCount": "@add(int(coalesce(first(body('Get_planning_run')?['value'])?['PlannedCount'], 0)), variables('PagePlannedCount'))",
                    },
                    {"For_each_candidate": ["Succeeded"]},
                ),
            },
            "else": {
                "actions": {
                    "FINALISE_planning": {
                        "runAfter": {},
                        "type": "If",
                        "expression": {
                            "or": [
                                {
                                    "equals": [
                                        "@first(body('Get_planning_run')?['value'])?['IsDryRun']",
                                        True,
                                    ]
                                },
                                {
                                    "equals": [
                                        "@int(coalesce(first(body('Get_planning_run')?['value'])?['PlannedCount'], 0))",
                                        0,
                                    ]
                                },
                            ]
                        },
                        "actions": {
                            "Complete_plan_without_execution": patch_run(
                                {
                                    "dataset": "@parameters('fi_SiteAddress (fi_SiteAddress)')",
                                    "table": "@parameters('fi_RunListName (fi_RunListName)')",
                                    "id": "@first(body('Get_planning_run')?['value'])?['ID']",
                                    "item/Status/Value": "Completed",
                                    "item/CompletedAt": "@utcNow()",
                                    "item/SummaryMessage": "@{if(first(body('Get_planning_run')?['value'])?['IsDryRun'], 'Dry-run plan completed; no agent calls were made.', 'No outstanding documents matched this template version.')}",
                                }
                            )
                        },
                        "else": {
                            "actions": {
                                "Queue_for_approval": patch_run(
                                    {
                                        "dataset": "@parameters('fi_SiteAddress (fi_SiteAddress)')",
                                        "table": "@parameters('fi_RunListName (fi_RunListName)')",
                                        "id": "@first(body('Get_planning_run')?['value'])?['ID']",
                                        "item/Status/Value": "AwaitingApproval",
                                        "item/ApprovalDecision/Value": "Pending",
                                        "item/SecondConfirmation/Value": "@{if(greater(int(first(body('Get_planning_run')?['value'])?['PlannedCount']), int(parameters('fi_MaxDocumentsPerRun (fi_MaxDocumentsPerRun)'))), 'Pending', 'NotRequired')}",
                                        "item/RequiresSecondConfirmation": "@greater(int(first(body('Get_planning_run')?['value'])?['PlannedCount']), int(parameters('fi_MaxDocumentsPerRun (fi_MaxDocumentsPerRun)')))",
                                    },
                                    description=(
                                        "Approval is handled by A3 so a human wait "
                                        "does not block the single-concurrency pager."
                                    ),
                                )
                            }
                        },
                    }
                }
            },
        },
    }
    actions["Get_newer_index_walk"] = sharepoint(
        "GetItems",
        {
            "dataset": "@parameters('fi_SiteAddress (fi_SiteAddress)')",
            "table": "@parameters('fi_IndexWalkRunListName (fi_IndexWalkRunListName)')",
            "$filter": (
                "ID gt @{int(coalesce(first(body('Get_planning_run')?['value'])?"
                "['IndexSnapshotItemId'], 2147483647))}"
            ),
            "$top": 1,
        },
        {"Get_planning_run": ["Succeeded"]},
    )
    exit_action = actions["Exit_if_no_planning_run"]
    exit_action["runAfter"] = {"Get_newer_index_walk": ["Succeeded"]}
    exit_action["expression"] = {
        "or": [
            {"equals": ["@length(body('Get_planning_run')?['value'])", 0]},
            {"greater": ["@length(body('Get_newer_index_walk')?['value'])", 0]},
        ]
    }
    cancel_stale = patch_run(
        {
            "dataset": "@parameters('fi_SiteAddress (fi_SiteAddress)')",
            "table": "@parameters('fi_RunListName (fi_RunListName)')",
            "id": "@first(body('Get_planning_run')?['value'])?['ID']",
            "item/Status/Value": "Cancelled",
            "item/SummaryMessage": (
                "Planning cancelled because a newer index walk exists. "
                "Publish again after the newest walk completes."
            ),
        }
    )
    exit_action["actions"] = {
        "Cancel_if_snapshot_changed": {
            "runAfter": {},
            "type": "If",
            "expression": {
                "greater": ["@length(body('Get_newer_index_walk')?['value'])", 0]
            },
            "actions": {"Cancel_stale_plan": cancel_stale},
            "else": {"actions": {}},
        },
        "Terminate_idle": {
            "runAfter": {"Cancel_if_snapshot_changed": ["Succeeded"]},
            "type": "Terminate",
            "inputs": {"runStatus": "Succeeded"},
        },
    }

    candidate_actions = (
        actions["HANDLE_page"]["actions"]["For_each_candidate"]["actions"]
        ["GATE_preferred_source"]["actions"]
    )
    old_gate = candidate_actions.pop("GATE_not_already_current")
    candidate_actions.pop("Get_existing_or_prior_success")
    create_actions = old_gate["actions"]
    candidate_actions["Get_existing_current_work_item"] = sharepoint(
        "GetItems",
        {
            "dataset": "@parameters('fi_SiteAddress (fi_SiteAddress)')",
            "table": "@parameters('fi_WorkItemListName (fi_WorkItemListName)')",
            "$filter": (
                "RunId eq '@{first(body('Get_planning_run')?['value'])?['RunId']}' "
                "and SourceDocumentKey eq '@{replace(items('For_each_candidate')?['DocumentKey'],'''','''''')}'"
            ),
            "$top": 1,
        },
    )
    candidate_actions["GATE_current_work_missing"] = {
        "runAfter": {"Get_existing_current_work_item": ["Succeeded"]},
        "type": "If",
        "expression": {
            "equals": [
                "@length(body('Get_existing_current_work_item')?['value'])",
                0,
            ]
        },
        "actions": {
            "Get_prior_success": sharepoint(
                "GetItems",
                {
                    "dataset": "@parameters('fi_SiteAddress (fi_SiteAddress)')",
                    "table": "@parameters('fi_WorkItemListName (fi_WorkItemListName)')",
                    "$filter": (
                        "SourceDocumentKey eq '@{replace(items('For_each_candidate')?['DocumentKey'],'''','''''')}' "
                        "and TemplateName eq "
                        "'@{replace(first(body('Get_planning_run')?['value'])?['TemplateName'],'''','''''')}' "
                        "and TemplateFingerprint eq "
                        "'@{first(body('Get_planning_run')?['value'])?['TemplateFingerprint']}' "
                        "and Status eq 'Succeeded'"
                    ),
                    "$top": 1,
                },
            ),
            "GATE_no_prior_success": {
                "runAfter": {"Get_prior_success": ["Succeeded"]},
                "type": "If",
                "expression": {
                    "equals": [
                        "@length(body('Get_prior_success')?['value'])",
                        0,
                    ]
                },
                "actions": create_actions,
                "else": {"actions": {}},
            },
        },
        "else": {
            "actions": {
                "Count_existing_page_work": {
                    "runAfter": {},
                    "type": "IncrementVariable",
                    "inputs": {"name": "PagePlannedCount", "value": 1},
                    "description": (
                        "Crash-safe recovery: work already persisted by a prior "
                        "attempt of this page still contributes to PlannedCount."
                    ),
                }
            }
        },
    }

    return base_properties(
        {"shared_sharepointonline": SHAREPOINT},
        trigger,
        actions,
        "A2 consumes the complete DocumentIndex in bounded pages and queues a complete plan for approval.",
    )


def build_a3():
    trigger = {
        "When_a_run_approval_changes": {
            "type": "OpenApiConnection",
            "recurrence": {"frequency": "Minute", "interval": 5},
            "splitOn": "@triggerOutputs()?['body/value']",
            "runtimeConfiguration": {"concurrency": {"runs": 1}},
            "inputs": {
                "host": {
                    "connectionName": "shared_sharepointonline",
                    "operationId": "GetOnUpdatedItems",
                    "apiId": "/providers/Microsoft.PowerApps/apis/shared_sharepointonline",
                },
                "parameters": {
                    "dataset": "@parameters('fi_SiteAddress (fi_SiteAddress)')",
                    "table": "@parameters('fi_RunListName (fi_RunListName)')",
                },
                "authentication": "@parameters('$authentication')",
            },
            "description": (
                "A human approves or rejects by setting ApprovalDecision on the "
                "SharePoint run item. No Approvals or Outlook connector is required."
            ),
        }
    }
    actions = {
        "Get_newer_index_walk": sharepoint(
            "GetItems",
            {
                "dataset": "@parameters('fi_SiteAddress (fi_SiteAddress)')",
                "table": "@parameters('fi_IndexWalkRunListName (fi_IndexWalkRunListName)')",
                "$filter": (
                    "ID gt @{int(coalesce(triggerOutputs()?['body/IndexSnapshotItemId'], "
                    "2147483647))}"
                ),
                "$top": 1,
            },
        ),
        "Apply_approval_decision": {
            "runAfter": {"Get_newer_index_walk": ["Succeeded"]},
            "type": "If",
            "expression": {
                "and": [
                    {
                        "equals": [
                            "@triggerOutputs()?['body/Status']?['Value']",
                            "AwaitingApproval",
                        ]
                    },
                    {
                        "equals": [
                            "@length(body('Get_newer_index_walk')?['value'])",
                            0,
                        ]
                    },
                    {
                        "or": [
                            {
                                "equals": [
                                    "@triggerOutputs()?['body/ApprovalDecision']?['Value']",
                                    "Rejected",
                                ]
                            },
                            {
                                "and": [
                                    {
                                        "equals": [
                                            "@triggerOutputs()?['body/ApprovalDecision']?['Value']",
                                            "Approved",
                                        ]
                                    },
                                    {
                                        "or": [
                                            {
                                                "equals": [
                                                    "@triggerOutputs()?['body/RequiresSecondConfirmation']",
                                                    False,
                                                ]
                                            },
                                            {
                                                "equals": [
                                                    "@triggerOutputs()?['body/SecondConfirmation']?['Value']",
                                                    "Confirmed",
                                                ]
                                            },
                                        ]
                                    },
                                ]
                            },
                        ]
                    },
                ]
            },
            "actions": {
                "Patch_approval_outcome": patch_run(
                    {
                        "dataset": "@parameters('fi_SiteAddress (fi_SiteAddress)')",
                        "table": "@parameters('fi_RunListName (fi_RunListName)')",
                        "id": "@triggerOutputs()?['body/ID']",
                        "item/Status/Value": "@{if(equals(triggerOutputs()?['body/ApprovalDecision']?['Value'], 'Approved'), 'Approved', 'Cancelled')}",
                        "item/ApprovedBy": "@{if(equals(triggerOutputs()?['body/ApprovalDecision']?['Value'], 'Approved'), triggerOutputs()?['body/Editor/Email'], '')}",
                    }
                )
            },
            "else": {
                "actions": {
                    "Cancel_if_snapshot_changed": {
                        "runAfter": {},
                        "type": "If",
                        "expression": {
                            "and": [
                                {
                                    "equals": [
                                        "@triggerOutputs()?['body/Status']?['Value']",
                                        "AwaitingApproval",
                                    ]
                                },
                                {
                                    "greater": [
                                        "@length(body('Get_newer_index_walk')?['value'])",
                                        0,
                                    ]
                                },
                            ]
                        },
                        "actions": {
                            "Cancel_stale_plan": patch_run(
                                {
                                    "dataset": "@parameters('fi_SiteAddress (fi_SiteAddress)')",
                                    "table": "@parameters('fi_RunListName (fi_RunListName)')",
                                    "id": "@triggerOutputs()?['body/ID']",
                                    "item/Status/Value": "Cancelled",
                                    "item/SummaryMessage": (
                                        "Approval cancelled because a newer index "
                                        "walk exists. Publish again after it completes."
                                    ),
                                }
                            )
                        },
                        "else": {"actions": {}},
                    }
                }
            },
        },
    }
    return base_properties(
        {"shared_sharepointonline": SHAREPOINT},
        trigger,
        actions,
        "A3 applies an audited SharePoint-list approval decision to a complete plan.",
    )


def rendered():
    return {
        A1_PATH: json.dumps(build_a1(), indent=2, ensure_ascii=True) + "\n",
        A2_PATH: json.dumps(build_a2(), indent=2, ensure_ascii=True) + "\n",
        A3_PATH: json.dumps(build_a3(), indent=2, ensure_ascii=True) + "\n",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check", action="store_true", help="fail if generated flows differ"
    )
    args = parser.parse_args()

    ok = True
    for path, content in rendered().items():
        if args.check:
            if not os.path.exists(path):
                print("ERROR: generated flow is missing: %s" % os.path.relpath(path, ROOT))
                ok = False
                continue
            with open(path, encoding="utf-8") as handle:
                if handle.read() != content:
                    print("ERROR: generated flow is out of date: %s" % os.path.relpath(path, ROOT))
                    ok = False
        else:
            with open(path, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(content)
            print("Generated %s" % os.path.relpath(path, ROOT))

    if args.check and ok:
        print("Planning flows are up to date.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
