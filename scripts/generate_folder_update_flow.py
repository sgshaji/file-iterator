#!/usr/bin/env python3
"""Generate F3 from the reviewed folder-reconciliation action in F2."""

import argparse
import copy
import json
import os
import sys


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
F2_PATH = os.path.join(
    ROOT, "solution", "src", "Workflows", "F2-IndexDelete.json"
)
F3_PATH = os.path.join(
    ROOT, "solution", "src", "Workflows", "F3-IndexFolderChange.json"
)


def generated():
    with open(F2_PATH, encoding="utf-8") as handle:
        source = json.load(handle)

    reconcile = copy.deepcopy(
        source["properties"]["definition"]["actions"]["HANDLE_deleted_folder"]
    )
    reconcile["description"] = (
        "A folder rename or move changes descendant paths without modifying each "
        "file. Queue one complete bounded walk so all descendants are refreshed."
    )

    flow = {
        "$comment": "FLOW F3 - Index Folder Change. Queues reconciliation after a folder rename or move.",
        "properties": {
            "connectionReferences": copy.deepcopy(
                source["properties"]["connectionReferences"]
            ),
            "definition": {
                "$schema": "https://schema.management.azure.com/providers/Microsoft.Logic/schemas/2016-06-01/workflowdefinition.json#",
                "contentVersion": "1.0.0.0",
                "parameters": copy.deepcopy(
                    source["properties"]["definition"]["parameters"]
                ),
                "triggers": {
                    "When_a_folder_is_created_or_modified": {
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
                                "folderPath": "@parameters('fi_RootFolderPath (fi_RootFolderPath)')",
                            },
                            "authentication": "@parameters('$authentication')",
                        },
                    }
                },
                "actions": {"HANDLE_updated_folder": reconcile},
                "outputs": {},
                "description": (
                    "Only folder events perform work. File events are handled by "
                    "F and pass through this flow without side effects."
                ),
            },
            "schemaVersion": "1.0.0.0",
        },
    }
    return json.dumps(flow, indent=2, ensure_ascii=True) + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check", action="store_true", help="fail if generated flow differs"
    )
    args = parser.parse_args()
    content = generated()

    if args.check:
        if not os.path.exists(F3_PATH):
            print("ERROR: generated folder-update flow is missing")
            return 1
        with open(F3_PATH, encoding="utf-8") as handle:
            if handle.read() != content:
                print("ERROR: F3 is out of date with generate_folder_update_flow.py")
                return 1
        print("Folder-update flow is up to date.")
        return 0

    with open(F3_PATH, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)
    print("Generated %s" % os.path.relpath(F3_PATH, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
