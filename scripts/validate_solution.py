#!/usr/bin/env python3
"""Static validation for the template regeneration solution source.

Runs in CI on every pull request. Catches the classes of defect that are
otherwise only discovered after importing the solution into an environment
and running a flow -- which, for this solution, means discovering them
during a job that spends metered agent capacity and overwrites documents.

Checks:
  1. Every JSON artefact parses.
  2. Every flow has exactly one trigger and a non-empty action set.
  3. Every runAfter reference resolves to an action in the same scope.
  4. Every environment variable referenced by a flow is declared.
  5. Every connection reference used by a flow is declared.
  6. Every SharePoint list column read or written by a flow is defined
     in provisioning/lists.json.
  7. Columns that flows query or sort on are marked indexed.
  8. The PnP provisioning template is well-formed and covers every list.

Exit code 0 on success, 1 on any failure.
"""

import json
import os
import re
import sys
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKFLOW_DIR = os.path.join(ROOT, "solution", "src", "Workflows")
LISTS_FILE = os.path.join(ROOT, "provisioning", "lists.json")
PNP_FILE = os.path.join(ROOT, "provisioning", "pnp-provisioning-template.xml")
CONFIG_FILE = os.path.join(ROOT, "solution", "config", "environment-variables.json")

# Fields supplied by SharePoint, the connectors or the agent contract rather
# than by our own list definitions.
BUILTIN_FIELDS = {
    "ID", "Id", "Title", "Created", "Modified", "Editor", "Author",
    "Length", "Name", "UniqueId", "ServerRelativeUrl", "TimeLastModified",
    "Folders", "Files", "ListItemAllFields", "d", "value", "body",
    "status", "reason", "generatedContent", "outcome", "responses",
    "responder", "email", "template", "kind", "destinationFolderPath",
    "outputFileName", "bytesSent", "bytesStored", "verdict", "verdictNote",
    "missingFields", "removed", "highlightCleared", "archivedAs",
}

# Columns these flows filter or sort on. SharePoint degrades on unindexed
# columns as a list grows -- exactly the threshold problem this solution
# exists to work around, so it must not be reintroduced in our own lists.
REQUIRED_INDEXES = {
    "DocumentIndex": {
        "UniqueId", "ListItemId", "ParentFolderUniqueId", "DocumentStem", "DocumentKey",
        "DocumentRole", "IsExcluded"
    },
    "RegenerationRun": {"RunId", "RunKey", "Status", "TemplateName", "StartedAt"},
    "RegenerationWorkItem": {
        "RunId", "SourceUniqueId", "SourceDocumentKey", "TemplateName",
        "TemplateFingerprint", "Status", "AgentEffectState"
    },
    "WalkFrontier": {"WalkRunId", "Status"},
    "IndexWalkRun": {"WalkRunId", "Status"},
}

errors = []
warnings = []


def load_json(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def check_run_after(actions, scope, filename):
    """Every runAfter must name an action declared in the same scope."""
    names = set(actions)
    for name, action in actions.items():
        for dependency in (action.get("runAfter") or {}):
            if dependency not in names:
                errors.append(
                    "%s: action '%s%s' has runAfter on unknown action '%s'"
                    % (filename, scope, name, dependency)
                )
        nested = action.get("actions")
        if isinstance(nested, dict):
            check_run_after(nested, scope + name + "/", filename)
        else_branch = action.get("else")
        if isinstance(else_branch, dict) and isinstance(else_branch.get("actions"), dict):
            check_run_after(else_branch["actions"], scope + name + "/else/", filename)
        for case in (action.get("cases") or {}).values():
            if isinstance(case.get("actions"), dict):
                check_run_after(case["actions"], scope + name + "/case/", filename)


def walk_actions(actions):
    for name, action in (actions or {}).items():
        yield name, action
        for nested in (
            action.get("actions"),
            (action.get("else") or {}).get("actions"),
        ):
            for item in walk_actions(nested):
                yield item
        for case in (action.get("cases") or {}).values():
            for item in walk_actions(case.get("actions")):
                yield item


def main():
    if not os.path.isdir(WORKFLOW_DIR):
        errors.append("workflow directory not found: %s" % WORKFLOW_DIR)
        report()
        return

    lists = load_json(LISTS_FILE)["lists"]
    defined_columns = set()
    note_columns = set()
    for definition in lists:
        for column in definition["columns"]:
            defined_columns.add(column["name"])
            if column["type"] == "Note":
                note_columns.add(column["name"])

    # Check 7 -- required indexes.
    for definition in lists:
        for column in definition["columns"]:
            if column.get("indexed") and column.get("type") == "Note":
                errors.append(
                    "provisioning/lists.json: %s.%s is a multi-line Note column "
                    "and cannot be indexed in SharePoint"
                    % (definition["name"], column["name"])
                )
        indexed = {c["name"] for c in definition["columns"] if c.get("indexed")}
        for required in REQUIRED_INDEXES.get(definition["name"], set()):
            if required not in indexed:
                errors.append(
                    "provisioning/lists.json: %s.%s is queried by a flow but is not "
                    "marked indexed; this list will degrade as it grows"
                    % (definition["name"], required)
                )

    config = load_json(CONFIG_FILE)
    declared_vars = {v["schemaName"] for v in config["environmentVariables"]}
    declared_connections = {c["schemaName"] for c in config["connectionReferences"]}

    used_vars = set()
    used_connections = set()
    known_fields = defined_columns | BUILTIN_FIELDS

    workflow_files = sorted(
        f for f in os.listdir(WORKFLOW_DIR) if f.endswith(".json")
    )
    if not workflow_files:
        errors.append("no workflow definitions found")

    for filename in workflow_files:
        path = os.path.join(WORKFLOW_DIR, filename)
        try:
            document = load_json(path)
        except ValueError as exc:
            errors.append("%s: invalid JSON: %s" % (filename, exc))
            continue

        definition = document.get("properties", {}).get("definition")
        if not definition:
            errors.append("%s: missing properties.definition" % filename)
            continue

        triggers = definition.get("triggers") or {}
        actions = definition.get("actions") or {}
        if len(triggers) != 1:
            errors.append(
                "%s: expected exactly one trigger, found %d" % (filename, len(triggers))
            )
        if not actions:
            errors.append("%s: definition has no actions" % filename)

        check_run_after(actions, "", filename)

        with open(path, encoding="utf-8") as handle:
            text = handle.read()

        if "filter(" in text:
            errors.append(
                "%s: uses unsupported expression function filter(); use a "
                "Query/Filter array action instead" % filename
            )

        action_types = {name: action.get("type") for name, action in walk_actions(actions)}
        for reference in re.findall(r"result\('([^']+)'\)", text):
            if action_types.get(reference) not in {"Scope", "Foreach", "Until"}:
                errors.append(
                    "%s: result('%s') targets %s; result() only accepts a "
                    "scoped action" % (filename, reference, action_types.get(reference))
                )

        for filter_expression in re.findall(
            r'"\$filter"\s*:\s*"([^"]*)"', text
        ):
            for field in note_columns:
                if re.search(r"\b%s\b" % re.escape(field), filter_expression):
                    errors.append(
                        "%s: OData filter references Note column '%s', which "
                        "SharePoint does not support filtering"
                        % (filename, field)
                    )

        used_vars |= set(
            re.findall(r"parameters\('(fi_[A-Za-z]+) \(fi_[A-Za-z]+\)'\)", text)
        )
        used_connections |= set(
            re.findall(r'"connectionReferenceLogicalName":\s*"(fi_[a-z0-9]+)"', text)
        )

        written = set(re.findall(r'"item/([A-Za-z]+)(?:/Value)?"', text))
        read = set(re.findall(r"items\('[A-Za-z_]+'\)\?\['([A-Za-z]+)'\]", text))
        read |= set(re.findall(r"\)\)\?\['value'\]\)\?\['([A-Za-z]+)'\]", text))

        for field in sorted(written | read):
            if field not in known_fields:
                errors.append(
                    "%s: references column '%s' which is not defined in "
                    "provisioning/lists.json" % (filename, field)
                )

    for name in sorted(used_vars - declared_vars):
        errors.append("environment variable '%s' is used by a flow but not declared" % name)
    for name in sorted(used_connections - declared_connections):
        errors.append("connection reference '%s' is used by a flow but not declared" % name)
    for name in sorted(declared_vars - used_vars):
        warnings.append(
            "environment variable '%s' is declared but not referenced by any flow "
            "(expected for design-time-only settings)" % name
        )

    # Check 8 -- PnP template covers every list.
    try:
        tree = ET.parse(PNP_FILE)
    except ET.ParseError as exc:
        errors.append("provisioning/pnp-provisioning-template.xml is not well-formed: %s" % exc)
    else:
        provisioned = {
            element.get("Title")
            for element in tree.iter()
            if element.tag.endswith("ListInstance")
        }
        for definition in lists:
            if definition["name"] not in provisioned:
                errors.append(
                    "provisioning template does not create list '%s'" % definition["name"]
                )

    report()


def report():
    for warning in warnings:
        print("WARNING: %s" % warning)
    if errors:
        for error in errors:
            print("ERROR: %s" % error)
        print("\n%d error(s)." % len(errors))
        sys.exit(1)
    print("\nSolution source validation passed.")


if __name__ == "__main__":
    main()
