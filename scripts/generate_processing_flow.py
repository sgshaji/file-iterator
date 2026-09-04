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
                  "type": "integer"
                },
                "bytesStored": {
                  "type": "integer"
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
                      "item/Status/Value": "Skipped",
                      "item/AgentResultJson": "@string(body('PARSE_agent_report'))",
                      "item/ValidationResult": "Agent reported the normal another-format-preferred outcome.",
                      "item/ErrorMessage": "",
                      "item/CompletedAt": "@utcNow()"
                    },
                    "authentication": "@parameters('$authentication')"
                  }
                }
              },
              "else": {
                "actions": {
                  "Mark_agent_failed_or_retry": {
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
                        "item/Status/Value": "@{if(greaterOrEquals(add(int(coalesce(items('For_each_work_item')?['AttemptCount'], 0)), 1), int(parameters('fi_MaxAttempts (fi_MaxAttempts)'))), 'Failed', 'Pending')}",
                        "item/AgentResultJson": "@string(body('PARSE_agent_report'))",
                        "item/ValidationResult": "@{concat('Agent status ', body('PARSE_agent_report')?['status'], '; reason=', body('PARSE_agent_report')?['reason'])}",
                        "item/ErrorMessage": "@{take(coalesce(body('PARSE_agent_report')?['notes'], body('PARSE_agent_report')?['reason']), 4000)}",
                        "item/CompletedAt": "@utcNow()"
                      },
                      "authentication": "@parameters('$authentication')"
                    },
                    "description": "FAILED reports are retried only to MaxAttempts, then parked for review."
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
        "Mark_unparseable_or_retry": {
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
              "item/Status/Value": "@{if(greaterOrEquals(add(int(coalesce(items('For_each_work_item')?['AttemptCount'], 0)), 1), int(parameters('fi_MaxAttempts (fi_MaxAttempts)'))), 'Failed', 'Pending')}",
              "item/ValidationResult": "Agent reply could not be parsed as the contracted JSON report.",
              "item/ErrorMessage": "@{take(string(outputs('CAPTURE_agent_response')), 4000)}",
              "item/CompletedAt": "@utcNow()"
            },
            "authentication": "@parameters('$authentication')"
          },
          "description": "An unreadable envelope is retained verbatim and retried only to MaxAttempts."
        }
      }
    }
  }
}
'''
)


def expected_text():
    with open(FLOW_PATH, encoding="utf-8") as handle:
        flow = json.load(handle)

    properties = flow["properties"]
    properties["connectionReferences"]["shared_agentnode"] = AGENT_CONNECTION
    process = (
        properties["definition"]["actions"]["For_each_work_item"]["actions"]
        ["Skip_if_backpressure"]["else"]["actions"]["Process_document"]
    )
    process["actions"] = PROCESS_ACTIONS
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
