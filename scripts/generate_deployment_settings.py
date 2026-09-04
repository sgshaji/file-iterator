#!/usr/bin/env python3
"""Generate per-environment Power Platform deployment settings files.

Environment variable values and connection identifiers differ between test
and production. Baking them into the solution is how a test deployment ends
up pointed at the production document library and regenerates real documents.
This script renders a settings template per environment from the single
declaration in solution/config/environment-variables.json.

Values are left empty and must be filled in per environment. Placeholders are
intentional: no tenant URL, connection GUID or recipient address belongs in
version control.

Usage:
    python3 scripts/generate_deployment_settings.py           # write templates
    python3 scripts/generate_deployment_settings.py --check   # fail if stale
"""

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE = os.path.join(ROOT, "solution", "config", "environment-variables.json")
CONFIG_DIR = os.path.join(ROOT, "solution", "config")

ENVIRONMENTS = ("test", "prod")

# Safety overrides applied regardless of the declared default. A fresh
# deployment must not be able to regenerate documents before a human has
# looked at a plan, and must not aim at a large batch on its first run.
SAFE_DEPLOY_VALUES = {
    "fi_DryRun": "true",
    "fi_EnableConcurrency": "false",
}


def render(environment, config):
    settings = []
    for variable in config["environmentVariables"]:
        schema = variable["schemaName"]
        value = SAFE_DEPLOY_VALUES.get(schema, variable.get("defaultValue", ""))
        settings.append(
            {
                "SchemaName": schema,
                "Value": "" if value is None else str(value),
                "//": variable["description"],
            }
        )

    connections = [
        {
            "LogicalName": reference["schemaName"],
            "ConnectionId": "",
            "ConnectorId": reference["connectorId"],
            "//": "Fill in the %s connection id from the %s environment."
            % (reference["displayName"], environment),
        }
        for reference in config["connectionReferences"]
    ]

    document = {
        "//": (
            "Deployment settings for the %s environment. GENERATED FILE. "
            "Regenerate with scripts/generate_deployment_settings.py. Empty "
            "values must be supplied before import; do not commit tenant URLs, "
            "connection ids or recipient addresses." % environment
        ),
        "EnvironmentVariables": settings,
        "ConnectionReferences": connections,
    }
    return json.dumps(document, indent=2) + "\n"


def path_for(environment):
    return os.path.join(CONFIG_DIR, "deployment-settings.%s.json" % environment)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if files are stale")
    args = parser.parse_args()

    with open(CONFIG_FILE, encoding="utf-8") as handle:
        config = json.load(handle)

    stale = []
    for environment in ENVIRONMENTS:
        generated = render(environment, config)
        target = path_for(environment)

        if args.check:
            if not os.path.exists(target):
                stale.append(target)
                continue
            with open(target, encoding="utf-8") as handle:
                if handle.read() != generated:
                    stale.append(target)
            continue

        with open(target, "w", encoding="utf-8") as handle:
            handle.write(generated)
        print("Wrote %s" % target)

    if args.check:
        if stale:
            print(
                "ERROR: deployment settings are out of date with "
                "environment-variables.json:\n  %s\nRun: python3 "
                "scripts/generate_deployment_settings.py" % "\n  ".join(stale)
            )
            sys.exit(1)
        print("Deployment settings are up to date.")


if __name__ == "__main__":
    main()
