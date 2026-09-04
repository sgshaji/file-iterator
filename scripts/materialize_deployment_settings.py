#!/usr/bin/env python3
"""Resolve deployment settings from protected environment variables."""

import argparse
import json
import os
import sys


ENVIRONMENT_BINDINGS = {
    "fi_SiteAddress": "FI_SITE_ADDRESS",
    "fi_WebServerRelativeUrl": "FI_WEB_SERVER_RELATIVE_URL",
    "fi_LibraryUrlName": "FI_LIBRARY_URL_NAME",
    "fi_RootFolderPath": "FI_ROOT_FOLDER_PATH",
    "fi_TemplateFolderPath": "FI_TEMPLATE_FOLDER_PATH",
}

CONNECTION_BINDINGS = {
    "fi_sharedsharepointonline": "FI_SHAREPOINT_CONNECTION_ID",
    "fi_sharedagentnode": "FI_AGENT_CONNECTION_ID",
}


def required_environment(name):
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError("required environment variable %s is empty" % name)
    return value


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    with open(args.input, encoding="utf-8") as handle:
        settings = json.load(handle)

    variables = {
        item["SchemaName"]: item for item in settings.get("EnvironmentVariables", [])
    }
    connections = {
        item["LogicalName"]: item for item in settings.get("ConnectionReferences", [])
    }

    try:
        for schema_name, environment_name in ENVIRONMENT_BINDINGS.items():
            if schema_name not in variables:
                raise ValueError(
                    "deployment settings do not declare %s" % schema_name
                )
            variables[schema_name]["Value"] = required_environment(environment_name)

        for logical_name, environment_name in CONNECTION_BINDINGS.items():
            if logical_name not in connections:
                raise ValueError(
                    "deployment settings do not declare %s" % logical_name
                )
            connections[logical_name]["ConnectionId"] = required_environment(
                environment_name
            )
    except ValueError as exc:
        print("ERROR: %s" % exc)
        return 1

    # A deployment is always inert. Enabling execution is a separate reviewed
    # action after the generated plan has been inspected in the target tenant.
    if "fi_DryRun" not in variables:
        print("ERROR: deployment settings do not declare fi_DryRun")
        return 1
    variables["fi_DryRun"]["Value"] = "true"

    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(settings, handle, indent=2)
        handle.write("\n")
    print("Resolved deployment settings: %s" % args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
