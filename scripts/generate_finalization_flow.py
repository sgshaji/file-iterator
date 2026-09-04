#!/usr/bin/env python3
"""Generate the paged run-finalization flow."""

import argparse
import json
import os
import sys


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FLOW_PATH = os.path.join(
    ROOT, "solution", "src", "Workflows", "C-FinaliseRegenerationRun.json"
)

SHAREPOINT_HOST = {
    "connectionName": "shared_sharepointonline",
    "apiId": "/providers/Microsoft.PowerApps/apis/shared_sharepointonline",
}


def sharepoint(operation, parameters, run_after=None, description=None):
    host = dict(SHAREPOINT_HOST)
    host["operationId"] = operation
    action = {
        "runAfter": run_after or {},
        "type": "OpenApiConnection",
        "inputs": {
            "host": host,
            "parameters": parameters,
            "authentication": "@parameters('$authentication')",
        },
    }
    if description:
        action["description"] = description
    return action


def build():
    run_list = "@parameters('fi_RunListName (fi_RunListName)')"
    work_list = "@parameters('fi_WorkItemListName (fi_WorkItemListName)')"
    site = "@parameters('fi_SiteAddress (fi_SiteAddress)')"

    actions = {
        "Get_run_to_advance": sharepoint(
            "GetItems",
            {
                "dataset": site,
                "table": run_list,
                "$filter": "Status eq 'Running' or Status eq 'Finalizing'",
                "$orderby": "Created asc",
                "$top": 1,
            },
        ),
        "Exit_if_no_run": {
            "runAfter": {"Get_run_to_advance": ["Succeeded"]},
            "type": "If",
            "expression": {
                "equals": ["@length(body('Get_run_to_advance')?['value'])", 0]
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
        "HANDLE_running_run": {
            "runAfter": {"Exit_if_no_run": ["Succeeded"]},
            "type": "If",
            "expression": {
                "equals": [
                    "@first(body('Get_run_to_advance')?['value'])?['Status']?['Value']",
                    "Running",
                ]
            },
            "actions": {
                "Get_outstanding_item": sharepoint(
                    "GetItems",
                    {
                        "dataset": site,
                        "table": work_list,
                        "$filter": "RunId eq '@{first(body('Get_run_to_advance')?['value'])?['RunId']}' and (Status eq 'Pending' or Status eq 'InProgress')",
                        "$top": 1,
                    },
                ),
                "Begin_finalization_when_drained": {
                    "runAfter": {"Get_outstanding_item": ["Succeeded"]},
                    "type": "If",
                    "expression": {
                        "equals": [
                            "@length(body('Get_outstanding_item')?['value'])",
                            0,
                        ]
                    },
                    "actions": {
                        "Mark_run_finalizing": sharepoint(
                            "PatchItem",
                            {
                                "dataset": site,
                                "table": run_list,
                                "id": "@first(body('Get_run_to_advance')?['value'])?['ID']",
                                "item/Status/Value": "Finalizing",
                                "item/FinalizationCursorId": 0,
                                "item/SucceededCount": 0,
                                "item/FailedCount": 0,
                                "item/SkippedCount": 0,
                            },
                        )
                    },
                    "else": {"actions": {}},
                },
            },
            "else": {"actions": {}},
        },
        "HANDLE_finalizing_run": {
            "runAfter": {"HANDLE_running_run": ["Succeeded"]},
            "type": "If",
            "expression": {
                "equals": [
                    "@first(body('Get_run_to_advance')?['value'])?['Status']?['Value']",
                    "Finalizing",
                ]
            },
            "actions": {
                "Get_terminal_page": sharepoint(
                    "GetItems",
                    {
                        "dataset": site,
                        "table": work_list,
                        "$filter": "RunId eq '@{first(body('Get_run_to_advance')?['value'])?['RunId']}' and ID gt @{int(coalesce(first(body('Get_run_to_advance')?['value'])?['FinalizationCursorId'], 0))}",
                        "$orderby": "ID asc",
                        "$top": 500,
                    },
                    description=(
                        "Bounded terminal-state page. Counts are accumulated on "
                        "the run instead of loading all work items into one action."
                    ),
                ),
                "HANDLE_terminal_page": {
                    "runAfter": {"Get_terminal_page": ["Succeeded"]},
                    "type": "If",
                    "expression": {
                        "greater": [
                            "@length(body('Get_terminal_page')?['value'])",
                            0,
                        ]
                    },
                    "actions": {
                        "Filter_succeeded": {
                            "runAfter": {},
                            "type": "Query",
                            "inputs": {
                                "from": "@body('Get_terminal_page')?['value']",
                                "where": "@equals(item()?['Status']?['Value'], 'Succeeded')",
                            },
                        },
                        "Filter_failed": {
                            "runAfter": {},
                            "type": "Query",
                            "inputs": {
                                "from": "@body('Get_terminal_page')?['value']",
                                "where": "@equals(item()?['Status']?['Value'], 'Failed')",
                            },
                        },
                        "Filter_skipped": {
                            "runAfter": {},
                            "type": "Query",
                            "inputs": {
                                "from": "@body('Get_terminal_page')?['value']",
                                "where": "@equals(item()?['Status']?['Value'], 'Skipped')",
                            },
                        },
                        "Accumulate_terminal_counts": sharepoint(
                            "PatchItem",
                            {
                                "dataset": site,
                                "table": run_list,
                                "id": "@first(body('Get_run_to_advance')?['value'])?['ID']",
                                "item/FinalizationCursorId": "@last(body('Get_terminal_page')?['value'])?['ID']",
                                "item/SucceededCount": "@add(int(coalesce(first(body('Get_run_to_advance')?['value'])?['SucceededCount'], 0)), length(body('Filter_succeeded')))",
                                "item/FailedCount": "@add(int(coalesce(first(body('Get_run_to_advance')?['value'])?['FailedCount'], 0)), length(body('Filter_failed')))",
                                "item/SkippedCount": "@add(int(coalesce(first(body('Get_run_to_advance')?['value'])?['SkippedCount'], 0)), length(body('Filter_skipped')))",
                            },
                            {
                                "Filter_succeeded": ["Succeeded"],
                                "Filter_failed": ["Succeeded"],
                                "Filter_skipped": ["Succeeded"],
                            },
                        ),
                    },
                    "else": {
                        "actions": {
                            "Compose_summary": {
                                "runAfter": {},
                                "type": "Compose",
                                "inputs": "Run @{first(body('Get_run_to_advance')?['value'])?['RunId']}\nTemplate: @{first(body('Get_run_to_advance')?['value'])?['TemplateName']}\n\nPlanned: @{first(body('Get_run_to_advance')?['value'])?['PlannedCount']}\nSucceeded: @{first(body('Get_run_to_advance')?['value'])?['SucceededCount']}\nSkipped: @{first(body('Get_run_to_advance')?['value'])?['SkippedCount']}\nFailed: @{first(body('Get_run_to_advance')?['value'])?['FailedCount']}\nAgent calls: @{first(body('Get_run_to_advance')?['value'])?['AgentCallCount']}\n\n@{if(greater(int(coalesce(first(body('Get_run_to_advance')?['value'])?['FailedCount'], 0)), 0), 'Correct the cause, roll back side-effecting failed attempts where required, then publish the same template version to plan only outstanding sources.', 'No failures.')}",
                            },
                            "Close_run": sharepoint(
                                "PatchItem",
                                {
                                    "dataset": site,
                                    "table": run_list,
                                    "id": "@first(body('Get_run_to_advance')?['value'])?['ID']",
                                    "item/Status/Value": "@{if(greater(int(coalesce(first(body('Get_run_to_advance')?['value'])?['FailedCount'], 0)), 0), 'CompletedWithErrors', 'Completed')}",
                                    "item/CompletedAt": "@utcNow()",
                                    "item/SummaryMessage": "@outputs('Compose_summary')",
                                },
                                {"Compose_summary": ["Succeeded"]},
                            ),
                        }
                    },
                },
            },
            "else": {"actions": {}},
        },
    }

    return {
        "$comment": "FLOW C - Finalise Regeneration Run. Aggregates terminal work items in bounded pages and closes the run only after the queue drains.",
        "properties": {
            "connectionReferences": {
                "shared_sharepointonline": {
                    "runtimeSource": "embedded",
                    "connection": {
                        "connectionReferenceLogicalName": "fi_sharedsharepointonline"
                    },
                    "api": {"name": "shared_sharepointonline"},
                },
            },
            "definition": {
                "$schema": "https://schema.management.azure.com/providers/Microsoft.Logic/schemas/2016-06-01/workflowdefinition.json#",
                "contentVersion": "1.0.0.0",
                "parameters": {
                    "$connections": {"defaultValue": {}, "type": "Object"},
                    "$authentication": {"defaultValue": {}, "type": "SecureObject"},
                },
                "triggers": {
                    "Recurrence": {
                        "type": "Recurrence",
                        "recurrence": {"frequency": "Minute", "interval": 5},
                        "runtimeConfiguration": {"concurrency": {"runs": 1}},
                    }
                },
                "actions": actions,
                "outputs": {},
            },
            "schemaVersion": "1.0.0.0",
        },
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check", action="store_true", help="fail if generated flow differs"
    )
    args = parser.parse_args()
    generated = json.dumps(build(), indent=2, ensure_ascii=True) + "\n"

    if args.check:
        with open(FLOW_PATH, encoding="utf-8") as handle:
            if handle.read() != generated:
                print("ERROR: Flow C is out of date with generate_finalization_flow.py")
                return 1
        print("Flow C is up to date with its generator.")
        return 0

    with open(FLOW_PATH, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(generated)
    print("Generated %s" % os.path.relpath(FLOW_PATH, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
