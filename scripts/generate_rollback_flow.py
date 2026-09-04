#!/usr/bin/env python3
"""Generate Flow D from the PD Conversion Assistant result contract."""

import argparse
import json
import os
import sys


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FLOW_PATH = os.path.join(
    ROOT, "solution", "src", "Workflows", "D-RollbackRegenerationRun.json"
)
WORKER_PATH = os.path.join(
    ROOT, "solution", "src", "Workflows", "D2-ContinueRollback.json"
)

ROLLBACK_ACTIONS = json.loads(
    r"""
{
  "Require_explicit_confirmation": {
    "runAfter": {},
    "type": "If",
    "expression": {
      "not": {
        "equals": [
          "@toUpper(trim(triggerBody()?['text_1']))",
          "ROLLBACK"
        ]
      }
    },
    "actions": {
      "Terminate_not_confirmed": {
        "runAfter": {},
        "type": "Terminate",
        "inputs": {
          "runStatus": "Failed",
          "runError": {
            "code": "RollbackNotConfirmed",
            "message": "Rollback not confirmed. Type ROLLBACK to proceed."
          }
        }
      }
    },
    "else": {
      "actions": {}
    }
  },
  "Get_succeeded_items_for_run": {
    "runAfter": {
      "Require_explicit_confirmation": [
        "Succeeded"
      ]
    },
    "type": "OpenApiConnection",
    "inputs": {
      "host": {
        "connectionName": "shared_sharepointonline",
        "operationId": "GetItems",
        "apiId": "/providers/Microsoft.PowerApps/apis/shared_sharepointonline"
      },
      "parameters": {
        "dataset": "@parameters('fi_SiteAddress (fi_SiteAddress)')",
        "table": "@parameters('fi_WorkItemListName (fi_WorkItemListName)')",
        "$filter": "RunId eq '@{replace(trim(triggerBody()?['text']),'''','''''')}' and (Status eq 'Succeeded' or Status eq 'Failed') and HasAgentManifest eq 1",
        "$top": 5000
      },
      "authentication": "@parameters('$authentication')"
    },
    "description": "A succeeded work item carries the complete agent result, including every destination and archived filename."
  },
  "For_each_item_to_restore": {
    "runAfter": {
      "Get_succeeded_items_for_run": [
        "Succeeded"
      ]
    },
    "type": "Foreach",
    "foreach": "@body('Get_succeeded_items_for_run')?['value']",
    "runtimeConfiguration": {
      "concurrency": {
        "repetitions": 1
      }
    },
    "actions": {
      "PARSE_agent_result": {
        "runAfter": {},
        "type": "ParseJson",
        "inputs": {
          "content": "@items('For_each_item_to_restore')?['AgentResultJson']",
          "schema": {
            "type": "object",
            "required": [
              "status",
              "outputs"
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
              "outputs": {
                "type": "array",
                "items": {
                  "type": "object",
                  "required": [
                    "destinationFolderPath",
                    "outputFileName",
                    "archivedAs"
                  ],
                  "properties": {
                    "destinationFolderPath": {
                      "type": "string"
                    },
                    "outputFileName": {
                      "type": "string"
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
        }
      },
      "For_each_output": {
        "runAfter": {
          "PARSE_agent_result": [
            "Succeeded"
          ]
        },
        "type": "Foreach",
        "foreach": "@body('PARSE_agent_result')?['outputs']",
        "runtimeConfiguration": {
          "concurrency": {
            "repetitions": 1
          }
        },
        "actions": {
          "DELETE_generated_output": {
            "runAfter": {},
            "type": "OpenApiConnection",
            "inputs": {
              "host": {
                "connectionName": "shared_sharepointonline",
                "operationId": "HttpRequest",
                "apiId": "/providers/Microsoft.PowerApps/apis/shared_sharepointonline"
              },
              "parameters": {
                "dataset": "@parameters('fi_SiteAddress (fi_SiteAddress)')",
                "parameters/method": "DELETE",
                "parameters/uri": "@{concat('_api/web/GetFileByServerRelativePath(decodedurl=''', replace(concat(items('For_each_output')?['destinationFolderPath'], '/', items('For_each_output')?['outputFileName']), '''', ''''''), ''')')}",
                "parameters/headers": {
                  "Accept": "application/json;odata=nometadata",
                  "IF-MATCH": "*"
                }
              },
              "authentication": "@parameters('$authentication')"
            },
            "description": "Return the destination to its pre-run state before restoring every archived original. A missing output is harmless, so restoration also runs after this action fails."
          },
          "For_each_archived_file": {
            "runAfter": {
              "DELETE_generated_output": [
                "Succeeded",
                "Failed"
              ]
            },
            "type": "Foreach",
            "foreach": "@items('For_each_output')?['archivedAs']",
            "runtimeConfiguration": {
              "concurrency": {
                "repetitions": 1
              }
            },
            "actions": {
              "READ_archived_file": {
                "runAfter": {},
                "type": "OpenApiConnection",
                "inputs": {
                  "host": {
                    "connectionName": "shared_sharepointonline",
                    "operationId": "GetFileContentByPath",
                    "apiId": "/providers/Microsoft.PowerApps/apis/shared_sharepointonline"
                  },
                  "parameters": {
                    "dataset": "@parameters('fi_SiteAddress (fi_SiteAddress)')",
                    "path": "@{concat(items('For_each_output')?['destinationFolderPath'], '/', parameters('fi_ArchiveFolderName (fi_ArchiveFolderName)'), '/', items('For_each_archived_file'))}",
                    "inferContentType": false
                  },
                  "authentication": "@parameters('$authentication')"
                }
              },
              "RESTORE_archived_file": {
                "runAfter": {
                  "READ_archived_file": [
                    "Succeeded"
                  ]
                },
                "type": "OpenApiConnection",
                "inputs": {
                  "host": {
                    "connectionName": "shared_sharepointonline",
                    "operationId": "CreateFile",
                    "apiId": "/providers/Microsoft.PowerApps/apis/shared_sharepointonline"
                  },
                  "parameters": {
                    "dataset": "@parameters('fi_SiteAddress (fi_SiteAddress)')",
                    "folderPath": "@items('For_each_output')?['destinationFolderPath']",
                    "name": "@{concat(substring(items('For_each_archived_file'), 0, sub(lastIndexOf(items('For_each_archived_file'), '.'), 16)), substring(items('For_each_archived_file'), lastIndexOf(items('For_each_archived_file'), '.')))}",
                    "body": "@body('READ_archived_file')"
                  },
                  "authentication": "@parameters('$authentication')"
                },
                "description": "archive-name guarantees a final _yyyyMMdd-HHmmss suffix. Removing those 16 characters reconstructs the exact displaced filename."
              }
            }
          }
        }
      },
      "Mark_item_rolled_back": {
        "runAfter": {
          "For_each_output": [
            "Succeeded"
          ]
        },
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
            "id": "@items('For_each_item_to_restore')?['ID']",
            "item/Status/Value": "RolledBack",
            "item/RollbackResultJson": "@{concat('{\"status\":\"RolledBack\",\"outputCount\":', string(length(body('PARSE_agent_result')?['outputs'])), ',\"completedAt\":\"', utcNow(), '\"}')}",
            "item/ErrorMessage": ""
          },
          "authentication": "@parameters('$authentication')"
        }
      },
      "Record_parse_failure": {
        "runAfter": {
          "PARSE_agent_result": [
            "Failed"
          ]
        },
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
            "id": "@items('For_each_item_to_restore')?['ID']",
            "item/RollbackResultJson": "@{concat('{\"status\":\"Failed\",\"stage\":\"ParseAgentResult\",\"completedAt\":\"', utcNow(), '\"}')}",
            "item/ErrorMessage": "Rollback could not parse AgentResultJson."
          },
          "authentication": "@parameters('$authentication')"
        }
      },
      "Record_restore_failure": {
        "runAfter": {
          "For_each_output": [
            "Failed",
            "TimedOut"
          ]
        },
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
            "id": "@items('For_each_item_to_restore')?['ID']",
            "item/RollbackResultJson": "@{concat('{\"status\":\"Failed\",\"completedAt\":\"', utcNow(), '\"}')}",
            "item/ErrorMessage": "@{take(string(result('For_each_output')), 4000)}"
          },
          "authentication": "@parameters('$authentication')"
        },
        "description": "Leave the item Succeeded so another rollback attempt can retry it. Never report the run RolledBack while any item remains."
      }
    }
  },
  "Get_remaining_succeeded_items": {
    "runAfter": {
      "For_each_item_to_restore": [
        "Succeeded",
        "Failed"
      ]
    },
    "type": "OpenApiConnection",
    "inputs": {
      "host": {
        "connectionName": "shared_sharepointonline",
        "operationId": "GetItems",
        "apiId": "/providers/Microsoft.PowerApps/apis/shared_sharepointonline"
      },
      "parameters": {
        "dataset": "@parameters('fi_SiteAddress (fi_SiteAddress)')",
        "table": "@parameters('fi_WorkItemListName (fi_WorkItemListName)')",
        "$filter": "RunId eq '@{replace(trim(triggerBody()?['text']),'''','''''')}' and (Status eq 'Succeeded' or Status eq 'Failed') and HasAgentManifest eq 1",
        "$top": 1
      },
      "authentication": "@parameters('$authentication')"
    }
  },
  "Get_run_record": {
    "runAfter": {
      "Get_remaining_succeeded_items": [
        "Succeeded"
      ]
    },
    "type": "OpenApiConnection",
    "inputs": {
      "host": {
        "connectionName": "shared_sharepointonline",
        "operationId": "GetItems",
        "apiId": "/providers/Microsoft.PowerApps/apis/shared_sharepointonline"
      },
      "parameters": {
        "dataset": "@parameters('fi_SiteAddress (fi_SiteAddress)')",
        "table": "@parameters('fi_RunListName (fi_RunListName)')",
        "$filter": "RunId eq '@{replace(trim(triggerBody()?['text']),'''','''''')}'",
        "$top": 1
      },
      "authentication": "@parameters('$authentication')"
    }
  },
  "Mark_run_rolled_back": {
    "runAfter": {
      "Get_run_record": [
        "Succeeded"
      ]
    },
    "type": "If",
    "expression": {
      "and": [
        {
          "equals": [
            "@length(body('Get_remaining_succeeded_items')?['value'])",
            0
          ]
        },
        {
          "greater": [
            "@length(body('Get_run_record')?['value'])",
            0
          ]
        }
      ]
    },
    "actions": {
      "Patch_run": {
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
            "table": "@parameters('fi_RunListName (fi_RunListName)')",
            "id": "@first(body('Get_run_record')?['value'])?['ID']",
            "item/Status/Value": "RolledBack",
            "item/SummaryMessage": "All generated outputs were removed and every archived original reported by the agent was restored."
          },
          "authentication": "@parameters('$authentication')"
        }
      }
    },
    "else": {
      "actions": {
        "Terminate_incomplete_rollback": {
          "runAfter": {},
          "type": "Terminate",
          "inputs": {
            "runStatus": "Failed",
            "runError": {
              "code": "RollbackIncomplete",
              "message": "One or more work items could not be restored. Review RollbackResultJson and ErrorMessage, then retry the rollback."
            }
          }
        }
      }
    }
  }
}
"""
)

_lock_run_actions = {
    "Get_run_to_lock": {
        "runAfter": {"Require_explicit_confirmation": ["Succeeded"]},
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
                "$filter": (
                    "RunId eq '@{replace(trim(triggerBody()?['text']),'''','''''')}' "
                    "and (Status eq 'Completed' or Status eq 'CompletedWithErrors')"
                ),
                "$top": 1,
            },
            "authentication": "@parameters('$authentication')",
        },
    },
    "Validate_terminal_run": {
        "runAfter": {"Get_newer_live_run": ["Succeeded"]},
        "type": "If",
        "expression": {
            "and": [
                {"equals": ["@length(body('Get_run_to_lock')?['value'])", 1]},
                {"equals": ["@length(body('Get_newer_live_run')?['value'])", 0]},
            ]
        },
        "actions": {
            "Lock_run_for_rollback": {
                "runAfter": {},
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
                        "id": "@first(body('Get_run_to_lock')?['value'])?['ID']",
                        "item/Status/Value": "RollbackInProgress",
                        "item/RollbackCursorId": 0,
                    },
                    "authentication": "@parameters('$authentication')",
                },
            }
        },
        "else": {
            "actions": {
                "Terminate_run_not_terminal": {
                    "runAfter": {},
                    "type": "Terminate",
                    "inputs": {
                        "runStatus": "Failed",
                        "runError": {
                            "code": "RunNotRollbackEligible",
                            "message": (
                                "Only Completed or CompletedWithErrors runs can be "
                                "rolled back, and newer live runs must be rolled "
                                "back first."
                            ),
                        },
                    },
                }
            }
        },
    },
}

_ordered = {}
for _name, _action in ROLLBACK_ACTIONS.items():
    _ordered[_name] = _action
    if _name == "Require_explicit_confirmation":
        _ordered["Get_run_to_lock"] = _lock_run_actions["Get_run_to_lock"]
        _ordered["Get_newer_live_run"] = {
            "runAfter": {"Get_run_to_lock": ["Succeeded"]},
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
                    "$filter": (
                        "ID gt @{int(coalesce(first(body('Get_run_to_lock')?['value'])?['ID'], 2147483647))} "
                        "and IsDryRun eq 0 and Status ne 'Cancelled' and "
                        "Status ne 'RolledBack'"
                    ),
                    "$top": 1,
                },
                "authentication": "@parameters('$authentication')",
            },
            "description": (
                "Conservative LIFO guard. A newer live run may own the current "
                "output, so older runs must be rolled back only after it."
            ),
        }
        _ordered["Validate_terminal_run"] = _lock_run_actions[
            "Validate_terminal_run"
        ]
ROLLBACK_ACTIONS = _ordered
ROLLBACK_ACTIONS["Get_succeeded_items_for_run"]["runAfter"] = {
    "Validate_terminal_run": ["Succeeded"]
}
ROLLBACK_ACTIONS.pop("Get_run_record")
_unrecoverable = {
    "runAfter": {"Get_remaining_succeeded_items": ["Succeeded"]},
    "type": "OpenApiConnection",
    "inputs": {
        "host": {
            "connectionName": "shared_sharepointonline",
            "operationId": "GetItems",
            "apiId": "/providers/Microsoft.PowerApps/apis/shared_sharepointonline",
        },
        "parameters": {
            "dataset": "@parameters('fi_SiteAddress (fi_SiteAddress)')",
            "table": "@parameters('fi_WorkItemListName (fi_WorkItemListName)')",
            "$filter": (
                "RunId eq '@{replace(trim(triggerBody()?['text']),'''','''''')}' "
                "and Status eq 'Failed' and HasAgentManifest eq 0"
            ),
            "$top": 1,
        },
        "authentication": "@parameters('$authentication')",
    },
    "description": (
        "A failed item without a parsed archive manifest cannot be declared "
        "automatically restored."
    ),
}
_with_unrecoverable = {}
for _name, _action in ROLLBACK_ACTIONS.items():
    if _name == "Mark_run_rolled_back":
        _with_unrecoverable["Get_unrecoverable_failed_items"] = _unrecoverable
    _with_unrecoverable[_name] = _action
ROLLBACK_ACTIONS = _with_unrecoverable
_mark_run = ROLLBACK_ACTIONS["Mark_run_rolled_back"]
_mark_run["runAfter"] = {"Get_unrecoverable_failed_items": ["Succeeded"]}
_mark_run["expression"] = {
    "and": [
        {
            "equals": [
                "@length(body('Get_remaining_succeeded_items')?['value'])",
                0,
            ]
        },
        {
            "equals": [
                "@length(body('Get_unrecoverable_failed_items')?['value'])",
                0,
            ]
        }
    ]
}
_patch_run = _mark_run["actions"]["Patch_run"]
_patch_run["inputs"]["parameters"]["id"] = (
    "@first(body('Get_run_to_lock')?['value'])?['ID']"
)
_incomplete = _mark_run["else"]["actions"]["Terminate_incomplete_rollback"]
_mark_run["else"]["actions"] = {
    "Release_incomplete_rollback": {
        "runAfter": {},
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
                "id": "@first(body('Get_run_to_lock')?['value'])?['ID']",
                "item/Status/Value": "CompletedWithErrors",
                "item/SummaryMessage": (
                    "Rollback incomplete. Review work item RollbackResultJson "
                    "and ErrorMessage, perform manual recovery, then retry."
                ),
            },
            "authentication": "@parameters('$authentication')",
        },
    },
    "Terminate_incomplete_rollback": _incomplete,
}
_incomplete["runAfter"] = {"Release_incomplete_rollback": ["Succeeded"]}


def start_text():
    with open(FLOW_PATH, encoding="utf-8") as handle:
        flow = json.load(handle)
    flow["properties"]["definition"]["actions"] = {
        name: ROLLBACK_ACTIONS[name]
        for name in (
            "Require_explicit_confirmation",
            "Get_run_to_lock",
            "Get_newer_live_run",
            "Validate_terminal_run",
        )
    }
    flow["$comment"] = (
        "FLOW D1 - Start rollback. Validates LIFO eligibility and locks a "
        "terminal run; D2 restores manifests in bounded pages."
    )
    return json.dumps(flow, indent=2, ensure_ascii=True) + "\n"


def worker_text():
    restore_loop = json.loads(
        json.dumps(ROLLBACK_ACTIONS["For_each_item_to_restore"])
    )
    restore_loop["runAfter"] = {}
    restore_loop["foreach"] = "@body('Get_rollback_page')?['value']"

    actions = {
        "Get_rollback_run": {
            "runAfter": {},
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
                    "$orderby": "Created desc",
                    "$top": 1,
                },
                "authentication": "@parameters('$authentication')",
            },
        },
        "Exit_if_no_rollback": {
            "runAfter": {"Get_rollback_run": ["Succeeded"]},
            "type": "If",
            "expression": {
                "equals": ["@length(body('Get_rollback_run')?['value'])", 0]
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
        "Get_newer_live_run": {
            "runAfter": {"Exit_if_no_rollback": ["Succeeded"]},
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
                    "$filter": (
                        "ID gt @{first(body('Get_rollback_run')?['value'])?['ID']} "
                        "and IsDryRun eq 0 and Status ne 'Cancelled' and "
                        "Status ne 'RolledBack'"
                    ),
                    "$top": 1,
                },
                "authentication": "@parameters('$authentication')",
            },
        },
        "Abort_if_newer_run_exists": {
            "runAfter": {"Get_newer_live_run": ["Succeeded"]},
            "type": "If",
            "expression": {
                "greater": ["@length(body('Get_newer_live_run')?['value'])", 0]
            },
            "actions": {
                "Release_rollback_lock": {
                    "runAfter": {},
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
                            "id": "@first(body('Get_rollback_run')?['value'])?['ID']",
                            "item/Status/Value": "CompletedWithErrors",
                            "item/SummaryMessage": (
                                "Rollback stopped because a newer live run exists. "
                                "Roll back newer runs first."
                            ),
                        },
                        "authentication": "@parameters('$authentication')",
                    },
                },
                "Terminate_newer_run_exists": {
                    "runAfter": {"Release_rollback_lock": ["Succeeded"]},
                    "type": "Terminate",
                    "inputs": {
                        "runStatus": "Failed",
                        "runError": {
                            "code": "NewerRunExists",
                            "message": "Rollback stopped; roll back newer live runs first.",
                        },
                    },
                },
            },
            "else": {"actions": {}},
        },
        "Get_rollback_page": {
            "runAfter": {"Abort_if_newer_run_exists": ["Succeeded"]},
            "type": "OpenApiConnection",
            "inputs": {
                "host": {
                    "connectionName": "shared_sharepointonline",
                    "operationId": "GetItems",
                    "apiId": "/providers/Microsoft.PowerApps/apis/shared_sharepointonline",
                },
                "parameters": {
                    "dataset": "@parameters('fi_SiteAddress (fi_SiteAddress)')",
                    "table": "@parameters('fi_WorkItemListName (fi_WorkItemListName)')",
                    "$filter": (
                        "RunId eq '@{first(body('Get_rollback_run')?['value'])?['RunId']}' "
                        "and ID gt @{int(coalesce(first(body('Get_rollback_run')?['value'])?['RollbackCursorId'], 0))} "
                        "and (Status eq 'Succeeded' or Status eq 'Failed') "
                        "and HasAgentManifest eq 1"
                    ),
                    "$orderby": "ID asc",
                    "$top": "@parameters('fi_RollbackPageSize (fi_RollbackPageSize)')",
                },
                "authentication": "@parameters('$authentication')",
            },
        },
        "HANDLE_rollback_page": {
            "runAfter": {"Get_rollback_page": ["Succeeded"]},
            "type": "If",
            "expression": {
                "greater": ["@length(body('Get_rollback_page')?['value'])", 0]
            },
            "actions": {
                "For_each_item_to_restore": restore_loop,
                "Advance_rollback_cursor": {
                    "runAfter": {"For_each_item_to_restore": ["Succeeded"]},
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
                            "id": "@first(body('Get_rollback_run')?['value'])?['ID']",
                            "item/RollbackCursorId": "@last(body('Get_rollback_page')?['value'])?['ID']",
                        },
                        "authentication": "@parameters('$authentication')",
                    },
                },
            },
            "else": {
                "actions": {
                    "Get_unrecoverable_failed_items": {
                        "runAfter": {},
                        "type": "OpenApiConnection",
                        "inputs": {
                            "host": {
                                "connectionName": "shared_sharepointonline",
                                "operationId": "GetItems",
                                "apiId": "/providers/Microsoft.PowerApps/apis/shared_sharepointonline",
                            },
                            "parameters": {
                                "dataset": "@parameters('fi_SiteAddress (fi_SiteAddress)')",
                                "table": "@parameters('fi_WorkItemListName (fi_WorkItemListName)')",
                                "$filter": (
                                    "RunId eq '@{first(body('Get_rollback_run')?['value'])?['RunId']}' "
                                    "and Status eq 'Failed' and HasAgentManifest eq 0"
                                ),
                                "$top": 1,
                            },
                            "authentication": "@parameters('$authentication')",
                        },
                    },
                    "Complete_or_release_rollback": {
                        "runAfter": {
                            "Get_unrecoverable_failed_items": ["Succeeded"]
                        },
                        "type": "If",
                        "expression": {
                            "equals": [
                                "@length(body('Get_unrecoverable_failed_items')?['value'])",
                                0,
                            ]
                        },
                        "actions": {
                            "Mark_run_rolled_back": {
                                "runAfter": {},
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
                                        "id": "@first(body('Get_rollback_run')?['value'])?['ID']",
                                        "item/Status/Value": "RolledBack",
                                        "item/SummaryMessage": (
                                            "All generated outputs were removed and "
                                            "every archived original was restored."
                                        ),
                                    },
                                    "authentication": "@parameters('$authentication')",
                                },
                            }
                        },
                        "else": {
                            "actions": {
                                "Release_incomplete_rollback": {
                                    "runAfter": {},
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
                                            "id": "@first(body('Get_rollback_run')?['value'])?['ID']",
                                            "item/Status/Value": "CompletedWithErrors",
                                            "item/SummaryMessage": (
                                                "Rollback incomplete. Review work "
                                                "item manifests and recover manually."
                                            ),
                                        },
                                        "authentication": "@parameters('$authentication')",
                                    },
                                }
                            }
                        },
                    },
                }
            },
        },
    }

    worker = {
        "$comment": "FLOW D2 - Continue rollback. Restores a bounded manifest page per run.",
        "properties": {
            "connectionReferences": {
                "shared_sharepointonline": {
                    "runtimeSource": "embedded",
                    "connection": {
                        "connectionReferenceLogicalName": "fi_sharedsharepointonline"
                    },
                    "api": {"name": "shared_sharepointonline"},
                }
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
    return json.dumps(worker, indent=2, ensure_ascii=True) + "\n"


def rendered():
    return {FLOW_PATH: start_text(), WORKER_PATH: worker_text()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check", action="store_true", help="fail if the generated flow differs"
    )
    args = parser.parse_args()

    ok = True
    for path, generated in rendered().items():
        if args.check:
            if not os.path.exists(path):
                print("ERROR: generated flow is missing: %s" % os.path.relpath(path, ROOT))
                ok = False
                continue
            with open(path, encoding="utf-8") as handle:
                if handle.read() != generated:
                    print("ERROR: generated flow is out of date: %s" % os.path.relpath(path, ROOT))
                    ok = False
        else:
            with open(path, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(generated)
            print("Generated %s" % os.path.relpath(path, ROOT))
    if args.check and ok:
        print("Rollback flows are up to date.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
