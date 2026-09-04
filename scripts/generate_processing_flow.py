#!/usr/bin/env python3
"""Generate the contract-sensitive processing block in Flow B."""

import argparse
import json
import os
import sys


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FLOW_PATH = os.path.join(
    ROOT, "solution", "src", "Workflows", "B-ProcessRegenerationBatch.json"
)

AGENT_CONNECTION = {
    "runtimeSource": "embedded",
    "connection": {"connectionReferenceLogicalName": "fi_sharedagentnode"},
    "api": {"name": "shared_agentnode"},
}

PROCESS_ACTIONS = json.loads(
    r'''
{
  "COMPOSE_agent_prompt": {
    "runAfter": {},
    "type": "Compose",
    "inputs": "@{concat('Convert this Position Description using the published template.', decodeUriComponent('%0A%0A'), 'siteUrl: ', parameters('fi_SiteAddress (fi_SiteAddress)'), decodeUriComponent('%0A'), 'templatePath: ', items('For_each_work_item')?['TemplateUrl'], decodeUriComponent('%0A'), 'sourcePath: ', items('For_each_work_item')?['SourceUrl'], decodeUriComponent('%0A'), 'runId: ', variables('ActiveRunId'))}",
    "description": "The deployed skill requires one concrete source PD path and one template file or folder per invocation. Flow A has already selected the preferred file of any PDF/DOCX pair."
  },
  "STEP_2_Invoke_agent": {
    "runAfter": {
      "COMPOSE_agent_prompt": [
        "Succeeded"
      ]
    },
    "runtimeConfiguration": {
      "retryPolicy": {
        "type": "None"
      }
    },
    "type": "OpenApiConnection",
    "inputs": {
      "host": {
        "connectionName": "shared_agentnode",
        "operationId": "InvokeAgent",
        "apiId": "/providers/Microsoft.PowerApps/apis/shared_agentnode"
      },
      "parameters": {
        "body/agentId": "@parameters('fi_AgentId (fi_AgentId)')",
        "body/prompt": "@outputs('COMPOSE_agent_prompt')"
      },
      "authentication": "@parameters('$authentication')"
    },
    "description": "THE ONLY METERED OPERATION. Connector, operation and parameter names are taken from the working reference export. The existing agent archives displaced files, writes outputs, verifies stored byte counts and returns one JSON report."
  },
  "Count_agent_call": {
    "runAfter": {
      "STEP_2_Invoke_agent": [
        "Succeeded",
        "Failed",
        "TimedOut"
      ]
    },
    "type": "IncrementVariable",
    "inputs": {
      "name": "AgentCallsThisBatch",
      "value": 1
    },
    "description": "Counted whether or not it succeeded because a failed call can still consume capacity."
  },
  "CAPTURE_agent_response": {
    "runAfter": {
      "Count_agent_call": [
        "Succeeded"
      ]
    },
    "type": "Compose",
    "inputs": "@coalesce(body('STEP_2_Invoke_agent'), '')",
    "description": "Verbatim connector response retained in run history before parsing."
  },
  "EXTRACT_reply_text": {
    "runAfter": {
      "CAPTURE_agent_response": [
        "Succeeded"
      ]
    },
    "type": "Compose",
    "inputs": "@if(empty(coalesce(body('STEP_2_Invoke_agent')?['text'], body('STEP_2_Invoke_agent')?['response'], body('STEP_2_Invoke_agent')?['output'])), string(outputs('CAPTURE_agent_response')), string(coalesce(body('STEP_2_Invoke_agent')?['text'], body('STEP_2_Invoke_agent')?['response'], body('STEP_2_Invoke_agent')?['output'])))",
    "description": "Accept a wrapped text/response/output property or a bare JSON object. The fallback checks emptiness before choosing, so an absent wrapper cannot suppress the raw response."
  },
  "PARSE_agent_report": {
    "runAfter": {
      "EXTRACT_reply_text": [
        "Succeeded"
      ]
    },
    "type": "ParseJson",
    "inputs": {
      "content": "@outputs('EXTRACT_reply_text')",
      "schema": {
        "type": "object",
        "required": [
          "status",
          "reason",
          "sourceFile",
          "sourceChosenBecause",
          "outputs",
          "notes"
        ],
        "properties": {
          "status": {
            "type": "string",
            "enum": [
              "OK",
              "FAILED",
              "SKIPPED"
            ]
          },
          "reason": {
            "type": "string"
          },
          "sourceFile": {
            "type": "string"
          },
          "sourceChosenBecause": {
            "type": "string"
          },
          "notes": {
            "type": "string"
          },
          "outputs": {
            "type": "array",
            "items": {
              "type": "object",
              "required": [
                "template",
                "kind",
                "destinationFolderPath",
                "outputFileName",
                "bytesSent",
                "bytesStored",
                "verdict",
                "archivedAs"
              ],
              "properties": {
                "template": {
                  "type": "string"
                },
                "kind": {
                  "type": "string",
                  "enum": [
                    "pd",
                    "ad"
                  ]
                },
                "destinationFolderPath": {
                  "type": "string"
                },
                "outputFileName": {
                  "type": "string"
                },
                "bytesSent": {
                  "type": [
                    "integer",
                    "null"
                  ]
                },
                "bytesStored": {
                  "type": [
                    "integer",
                    "null"
                  ]
                },
                "verdict": {
                  "type": "string",
                  "enum": [
                    "PASS",
                    "FAIL",
                    "CHECK"
                  ]
                },
                "verdictNote": {
                  "type": "string"
                },
                "missingFields": {
                  "type": "array"
                },
                "removed": {
                  "type": "array"
                },
                "highlightCleared": {
                  "type": "integer"
                },
                "archivedAs": {
                  "type": "array",
                  "items": {
                    "type": "string"
                  }
                }
              }
            }
          }
        }
      }
    },
    "description": "The schema mirrors pd_tools.py report output. Invalid envelopes are classified separately from agent-declared failures."
  },
  "HANDLE_parsed_report": {
    "runAfter": {
      "PARSE_agent_report": [
        "Succeeded",
        "Failed"
      ]
    },
    "type": "If",
    "expression": {
      "and": [
        {
          "equals": [
            "@result('PARSE_agent_report')[0]['status']",
            "Succeeded"
          ]
        }
      ]
    },
    "actions": {
      "HANDLE_agent_ok": {
        "runAfter": {},
        "type": "If",
        "expression": {
          "and": [
            {
              "equals": [
                "@body('PARSE_agent_report')?['status']",
                "OK"
              ]
            },
            {
              "greater": [
                "@length(body('PARSE_agent_report')?['outputs'])",
                0
              ]
            }
          ]
        },
        "actions": {
          "Mark_succeeded": {
            "runAfter": {},
            "type": "OpenApiConnection",
            "inputs": {
              "host": {
                "connectionName": "shared_sharepointonline",
                "operationId": "PatchItem",
                "apiId": "/providers/Microsoft.PowerApps/apis/shared_sharepointonline"
              },
              "parameters": {
                "dataset": "@parameters('fi_SiteAddress (fi_SiteAddress)')",
                "table": "@parameters('fi_WorkItemListName (fi_WorkItemListName)')",
                "id": "@items('For_each_work_item')?['ID']",
                "item/Status/Value": "Succeeded",
                "item/AgentResultJson": "@string(body('PARSE_agent_report'))",
                "item/HasAgentManifest": true,
                "item/ValidationResult": "Agent status OK; every reported output has verdict PASS and stored byte counts were verified by pd_tools.py.",
                "item/ErrorMessage": "",
                "item/CompletedAt": "@utcNow()"
              },
              "authentication": "@parameters('$authentication')"
            }
          }
        },
        "else": {
          "actions": {
            "HANDLE_agent_skipped": {
              "runAfter": {},
              "type": "If",
              "expression": {
                "and": [
                  {
                    "equals": [
                      "@body('PARSE_agent_report')?['status']",
                      "SKIPPED"
                    ]
                  },
                  {
                    "equals": [
                      "@body('PARSE_agent_report')?['reason']",
                      "another-format-preferred"
                    ]
                  }
                ]
              },
              "actions": {
                "Mark_skipped": {
                  "runAfter": {},
                  "type": "OpenApiConnection",
                  "inputs": {
                    "host": {
                      "connectionName": "shared_sharepointonline",
                      "operationId": "PatchItem",
                      "apiId": "/providers/Microsoft.PowerApps/apis/shared_sharepointonline"
                    },
                    "parameters": {
                      "dataset": "@parameters('fi_SiteAddress (fi_SiteAddress)')",
                      "table": "@parameters('fi_WorkItemListName (fi_WorkItemListName)')",
                      "id": "@items('For_each_work_item')?['ID']",
                      "item/Status/Value": "Failed",
                      "item/AgentResultJson": "@string(body('PARSE_agent_report'))",
                      "item/HasAgentManifest": true,
                      "item/ValidationResult": "Source preference changed after planning; no conversion was produced.",
                      "item/ErrorMessage": "Publish the same template version again to re-plan the current preferred source.",
                      "item/CompletedAt": "@utcNow()"
                    },
                    "authentication": "@parameters('$authentication')"
                  }
                }
              },
              "else": {
                "actions": {
                  "Mark_agent_failed": {
                    "runAfter": {},
                    "type": "OpenApiConnection",
                    "inputs": {
                      "host": {
                        "connectionName": "shared_sharepointonline",
                        "operationId": "PatchItem",
                        "apiId": "/providers/Microsoft.PowerApps/apis/shared_sharepointonline"
                      },
                      "parameters": {
                        "dataset": "@parameters('fi_SiteAddress (fi_SiteAddress)')",
                        "table": "@parameters('fi_WorkItemListName (fi_WorkItemListName)')",
                        "id": "@items('For_each_work_item')?['ID']",
                        "item/Status/Value": "Failed",
                        "item/AgentResultJson": "@string(body('PARSE_agent_report'))",
                        "item/HasAgentManifest": true,
                        "item/ValidationResult": "@{concat('Agent status ', body('PARSE_agent_report')?['status'], '; reason=', body('PARSE_agent_report')?['reason'])}",
                        "item/ErrorMessage": "@{take(coalesce(body('PARSE_agent_report')?['notes'], body('PARSE_agent_report')?['reason']), 4000)}",
                        "item/CompletedAt": "@utcNow()"
                      },
                      "authentication": "@parameters('$authentication')"
                    },
                    "description": "Agent-declared failures are parked immediately. A failed report can still describe uploaded or archived files, so automatically invoking the agent again would overwrite the only pre-run recovery chain."
                  }
                }
              }
            }
          }
        }
      }
    },
    "else": {
      "actions": {
        "Mark_unparseable": {
          "runAfter": {},
          "type": "OpenApiConnection",
          "inputs": {
            "host": {
              "connectionName": "shared_sharepointonline",
              "operationId": "PatchItem",
              "apiId": "/providers/Microsoft.PowerApps/apis/shared_sharepointonline"
            },
            "parameters": {
              "dataset": "@parameters('fi_SiteAddress (fi_SiteAddress)')",
              "table": "@parameters('fi_WorkItemListName (fi_WorkItemListName)')",
              "id": "@items('For_each_work_item')?['ID']",
              "item/Status/Value": "Failed",
              "item/AgentResultJson": "@string(outputs('EXTRACT_reply_text'))",
              "item/HasAgentManifest": true,
              "item/ValidationResult": "Agent reply could not be parsed as the contracted JSON report.",
              "item/ErrorMessage": "@{take(string(outputs('CAPTURE_agent_response')), 4000)}",
              "item/CompletedAt": "@utcNow()"
            },
            "authentication": "@parameters('$authentication')"
          },
          "description": "An unreadable envelope is retained verbatim and parked. Retrying could repeat side effects whose archive manifest could not be read."
        }
      }
    }
  }
}
'''
)

# ParseJson is not a scope, so result('PARSE_agent_report') is invalid WDL.
# Wrap it in a Scope and route by that scope's runAfter status instead.
_parse_action = PROCESS_ACTIONS.pop("PARSE_agent_report")
_parse_action["runAfter"] = {}
_handle = PROCESS_ACTIONS.pop("HANDLE_parsed_report")
_parsed_handler = _handle["actions"]["HANDLE_agent_ok"]
_parsed_handler["runAfter"] = {"FILTER_non_pass_outputs": ["Succeeded"]}
_parsed_handler["expression"]["and"].append(
    {"equals": ["@length(body('FILTER_non_pass_outputs'))", 0]}
)
_unparseable_handler = _handle["else"]["actions"]["Mark_unparseable"]
_unparseable_handler["runAfter"] = {"TRY_parse_agent_report": ["Failed", "TimedOut"]}
PROCESS_ACTIONS["TRY_parse_agent_report"] = {
    "runAfter": {"EXTRACT_reply_text": ["Succeeded"]},
    "type": "Scope",
    "actions": {"PARSE_agent_report": _parse_action},
    "description": "Scope status is the supported signal for whether ParseJson succeeded.",
}
PROCESS_ACTIONS["FILTER_non_pass_outputs"] = {
    "runAfter": {"TRY_parse_agent_report": ["Succeeded"]},
    "type": "Query",
    "inputs": {
        "from": "@body('PARSE_agent_report')?['outputs']",
        "where": "@not(equals(item()?['verdict'], 'PASS'))",
    },
    "description": (
        "Defence in depth: top-level OK is accepted only when every output "
        "independently reports a PASS byte-verification verdict."
    ),
}
PROCESS_ACTIONS["HANDLE_parsed_report"] = _parsed_handler
PROCESS_ACTIONS["Mark_unparseable"] = _unparseable_handler

_with_durable_count = {}
for _name, _action in PROCESS_ACTIONS.items():
    _with_durable_count[_name] = _action
    if _name == "Count_agent_call":
        _with_durable_count["Persist_agent_call_count"] = {
            "runAfter": {"Count_agent_call": ["Succeeded"]},
            "type": "OpenApiConnection",
            "inputs": {
                "host": {
                    "connectionName": "shared_sharepointonline",
                    "operationId": "PatchItem",
                    "apiId": "/providers/Microsoft.PowerApps/apis/shared_sharepointonline",
                },
                "parameters": {
                    "dataset": "@parameters('fi_SiteAddress (fi_SiteAddress)')",
                    "table": "@parameters('fi_RunListName (fi_RunListName)')",
                    "id": "@first(body('Get_active_run')?['value'])?['ID']",
                    "item/AgentCallCount": "@add(int(coalesce(first(body('Get_active_run')?['value'])?['AgentCallCount'], 0)), variables('AgentCallsThisBatch'))",
                },
                "authentication": "@parameters('$authentication')",
            },
            "description": (
                "Persist cost immediately after each metered call so a later "
                "batch crash cannot erase the count."
            ),
        }
PROCESS_ACTIONS = _with_durable_count
PROCESS_ACTIONS["CAPTURE_agent_response"]["runAfter"] = {
    "Persist_agent_call_count": ["Succeeded"]
}


def expected_text():
    with open(FLOW_PATH, encoding="utf-8") as handle:
        flow = json.load(handle)

    properties = flow["properties"]
    properties["connectionReferences"]["shared_agentnode"] = AGENT_CONNECTION
    trigger = properties["definition"]["triggers"]["Recurrence"]
    trigger["runtimeConfiguration"] = {"concurrency": {"runs": 1}}
    root = properties["definition"]["actions"]
    active = root["Get_active_run"]
    active["inputs"]["parameters"]["$filter"] = (
        "Status eq 'Running' and IsDryRun eq 0"
    )
    active["description"] = (
        "Resume an existing Running run before any Approved run. This preserves "
        "execution order and makes LIFO rollback match actual write order."
    )
    root["Get_approved_run"] = {
        "runAfter": {"Get_active_run": ["Succeeded"]},
        "type": "OpenApiConnection",
        "inputs": {
            "host": {
                "connectionName": "shared_sharepointonline",
                "operationId": "GetItems",
                "apiId": "/providers/Microsoft.PowerApps/apis/shared_sharepointonline",
            },
            "parameters": {
                "dataset": "@parameters('fi_SiteAddress (fi_SiteAddress)')",
                "table": "@parameters('fi_RunListName (fi_RunListName)')",
                "$filter": "Status eq 'Approved' and IsDryRun eq 0",
                "$orderby": "Created asc",
                "$top": 1,
            },
            "authentication": "@parameters('$authentication')",
        },
    }
    root["Get_rollback_lock"] = {
        "runAfter": {"Get_approved_run": ["Succeeded"]},
        "type": "OpenApiConnection",
        "inputs": {
            "host": {
                "connectionName": "shared_sharepointonline",
                "operationId": "GetItems",
                "apiId": "/providers/Microsoft.PowerApps/apis/shared_sharepointonline",
            },
            "parameters": {
                "dataset": "@parameters('fi_SiteAddress (fi_SiteAddress)')",
                "table": "@parameters('fi_RunListName (fi_RunListName)')",
                "$filter": "Status eq 'RollbackInProgress'",
                "$top": 1,
            },
            "authentication": "@parameters('$authentication')",
        },
    }
    exit_action = root["Exit_if_no_active_run"]
    exit_action["runAfter"] = {"Get_rollback_lock": ["Succeeded"]}
    exit_action["expression"] = {
        "or": [
            {"greater": ["@length(body('Get_rollback_lock')?['value'])", 0]},
            {
                "and": [
                    {"equals": ["@length(body('Get_active_run')?['value'])", 0]},
                    {
                        "equals": [
                            "@length(body('Get_approved_run')?['value'])",
                            0,
                        ]
                    },
                ]
            },
        ]
    }
    root["Init_ActiveRunId"]["inputs"]["variables"][0]["value"] = (
        "@{if(greater(length(body('Get_active_run')?['value']), 0), "
        "first(body('Get_active_run')?['value'])?['RunId'], "
        "first(body('Get_approved_run')?['value'])?['RunId'])}"
    )
    selected_id = (
        "@{if(greater(length(body('Get_active_run')?['value']), 0), "
        "first(body('Get_active_run')?['value'])?['ID'], "
        "first(body('Get_approved_run')?['value'])?['ID'])}"
    )
    root["Mark_run_running"]["inputs"]["parameters"]["id"] = selected_id
    selected_count = (
        "@add(int(coalesce(if(greater(length(body('Get_active_run')?['value']), 0), "
        "first(body('Get_active_run')?['value'])?['AgentCallCount'], "
        "first(body('Get_approved_run')?['value'])?['AgentCallCount']), 0)), "
        "variables('AgentCallsThisBatch'))"
    )
    root["Roll_up_agent_call_count"]["inputs"]["parameters"]["id"] = selected_id
    root["Roll_up_agent_call_count"]["inputs"]["parameters"][
        "item/AgentCallCount"
    ] = selected_count
    process = (
        properties["definition"]["actions"]["For_each_work_item"]["actions"]
        ["Skip_if_backpressure"]["else"]["actions"]["Process_document"]
    )
    process["actions"] = PROCESS_ACTIONS
    process["actions"]["Persist_agent_call_count"]["inputs"]["parameters"][
        "id"
    ] = selected_id
    process["actions"]["Persist_agent_call_count"]["inputs"]["parameters"][
        "item/AgentCallCount"
    ] = selected_count
    return json.dumps(flow, indent=2, ensure_ascii=True) + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check", action="store_true", help="fail if the generated flow differs"
    )
    args = parser.parse_args()

    generated = expected_text()
    if args.check:
        with open(FLOW_PATH, encoding="utf-8") as handle:
            current = handle.read()
        if current != generated:
            print("ERROR: Flow B is out of date with generate_processing_flow.py")
            return 1
        print("Flow B is up to date with its generator.")
        return 0

    with open(FLOW_PATH, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(generated)
    print("Generated %s" % os.path.relpath(FLOW_PATH, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
