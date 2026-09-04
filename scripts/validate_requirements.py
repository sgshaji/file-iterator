#!/usr/bin/env python3
"""Validate the static implementation contract for requirements R1-R7."""

import json
import os
import sys
import xml.etree.ElementTree as ET


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FLOW_DIR = os.path.join(ROOT, "solution", "src", "Workflows")
CONFIG_PATH = os.path.join(
    ROOT, "solution", "config", "environment-variables.json"
)
LISTS_PATH = os.path.join(ROOT, "provisioning", "lists.json")
SOLUTION_XML = os.path.join(ROOT, "solution", "src", "Other", "Solution.xml")
CUSTOMIZATIONS_XML = os.path.join(
    ROOT, "solution", "src", "Other", "Customizations.xml"
)

FLOW_FILES = {
    "A": "A-PlanRegenerationRun.json",
    "B": "B-ProcessRegenerationBatch.json",
    "C": "C-FinaliseRegenerationRun.json",
    "D": "D-RollbackRegenerationRun.json",
    "E1": "E1-StartIndexBackfill.json",
    "E2": "E2-IndexBackfillWorker.json",
    "F": "F-IndexDelta.json",
}

AGENT_ID = "cree1_pdconversionassistant_08zNQw"
AGENT_CONNECTOR = "shared_agentnode"
AGENT_OPERATION = "InvokeAgent"
SUPPORTED_EXTENSIONS = [".pdf", ".docx"]
EXCLUDED_FOLDERS = ["Archive", "AD Documents"]
ALLOWED_CONNECTORS = {
    "shared_sharepointonline",
    "shared_approvals",
    "shared_office365",
    "shared_agentnode",
}

errors = []


def load_json(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def require(condition, requirement, message):
    if not condition:
        errors.append("[%s] %s" % (requirement, message))


def actions(flow):
    return flow["properties"]["definition"]["actions"]


def triggers(flow):
    return flow["properties"]["definition"]["triggers"]


def walk_actions(scope, prefix=""):
    for name, action in (scope or {}).items():
        path = "%s/%s" % (prefix, name) if prefix else name
        yield path, action
        for child in (
            action.get("actions"),
            (action.get("else") or {}).get("actions"),
        ):
            for nested in walk_actions(child, path):
                yield nested
        for case in (action.get("cases") or {}).values():
            for nested in walk_actions(case.get("actions"), path):
                yield nested
        for nested in walk_actions(
            (action.get("default") or {}).get("actions"), path
        ):
            yield nested


def find_action(flow, name):
    matches = [
        action
        for path, action in walk_actions(actions(flow))
        if path.split("/")[-1] == name
    ]
    require(len(matches) == 1, "STRUCTURE", "expected one action named %s" % name)
    return matches[0] if len(matches) == 1 else {}


def raw(flow):
    return json.dumps(flow, separators=(",", ":"))


def config_map(config):
    return {
        variable["schemaName"]: variable
        for variable in config["environmentVariables"]
    }


def validate_r1(flows):
    plan = flows["A"]
    trigger_values = list(triggers(plan).values())
    require(len(trigger_values) == 1, "R1", "Flow A must have exactly one trigger")
    trigger = trigger_values[0] if trigger_values else {}
    require(
        trigger.get("inputs", {}).get("host", {}).get("operationId")
        == "GetOnUpdatedFileItems",
        "R1",
        "Flow A must use the proven SharePoint file-change trigger operation",
    )
    require(
        "fi_TemplateFolderPath" in json.dumps(trigger),
        "R1",
        "Flow A trigger must be scoped to the configured template folder",
    )
    gate = find_action(plan, "GATE_1_Is_this_an_explicit_publish")
    require(
        "published" in json.dumps(gate).lower(),
        "R1",
        "Flow A must require the explicit Published signal",
    )
    require(
        bool(find_action(plan, "Get_existing_run_for_this_template_fingerprint")),
        "R1",
        "Flow A must suppress duplicate active runs for the same fingerprint",
    )
    require(
        bool(find_action(plan, "Create_work_item")),
        "R1",
        "Flow A must persist one work item per selected source",
    )
    require(
        bool(find_action(plan, "GATE_5_Request_approval")),
        "R1",
        "Flow A must obtain approval before execution",
    )
    require(
        list(triggers(flows["B"]).values())[0].get("type") == "Recurrence",
        "R1",
        "Flow B must drain approved work on a schedule",
    )
    require(
        list(triggers(flows["C"]).values())[0].get("type") == "Recurrence",
        "R1",
        "Flow C must finalise drained runs on a schedule",
    )


def validate_r2(flows):
    worker_raw = raw(flows["E2"])
    require(
        "RecursiveAll" not in worker_raw and "ViewXml" not in worker_raw,
        "R2/C1",
        "index backfill must never use recursive SharePoint enumeration",
    )
    enumerate_action = find_action(flows["E2"], "Enumerate_direct_children")
    uri = enumerate_action.get("inputs", {}).get("parameters", {}).get(
        "parameters/uri", ""
    )
    require(
        "GetFolderByServerRelativePath" in uri
        and "$expand=Folders,Files" in uri,
        "R2/C1",
        "Flow E2 must enumerate only direct folders/files in one request",
    )
    frontier = find_action(flows["E2"], "Get_pending_frontier_chunk")
    require(
        "fi_WalkFolderChunkSize"
        in str(frontier.get("inputs", {}).get("parameters", {}).get("$top", "")),
        "R2/C2",
        "Flow E2 must claim a bounded persisted frontier chunk",
    )
    require(
        "WalkFrontierListName" in worker_raw,
        "R2/C2",
        "the folder frontier must be persisted in SharePoint",
    )
    delta_trigger = list(triggers(flows["F"]).values())[0]
    require(
        delta_trigger.get("inputs", {}).get("host", {}).get("operationId")
        == "GetOnUpdatedFileItems",
        "R2",
        "Flow F must maintain the index with the proven file-change trigger",
    )


def validate_r3_r4(config, flows):
    variables = config_map(config)
    extensions = json.loads(variables["fi_SourceExtensions"]["defaultValue"])
    exclusions = json.loads(variables["fi_ExcludedFolderNames"]["defaultValue"])
    require(
        extensions == SUPPORTED_EXTENSIONS,
        "R3",
        "source extensions must exactly match the deployed agent contract: %s"
        % SUPPORTED_EXTENSIONS,
    )
    require(
        exclusions == EXCLUDED_FOLDERS,
        "R4",
        "excluded folders must exactly match the agent output folders: %s"
        % EXCLUDED_FOLDERS,
    )
    child_filter = find_action(flows["E2"], "Filter_child_folders")
    child_text = json.dumps(child_filter).lower()
    require(
        "excludedfolders" in child_text and "enqueue_child_folder" not in child_text,
        "R4",
        "Flow E2 must filter excluded folders before enqueueing descendants",
    )
    delta_role = find_action(flows["F"], "Compose_document_role")
    role_text = json.dumps(delta_role).lower()
    require(
        "archivefoldername" in role_text and "outputfoldername" in role_text,
        "R4",
        "Flow F must classify output/archive descendants as non-source rows",
    )


def validate_r5(config, flows):
    variables = config_map(config)
    require(
        variables.get("fi_AgentId", {}).get("defaultValue") == AGENT_ID,
        "R5",
        "fi_AgentId must default to the deployed agent schema name",
    )
    agent_calls = [
        action
        for _, action in walk_actions(actions(flows["B"]))
        if action.get("type") == "OpenApiConnection"
        and action.get("inputs", {}).get("host", {}).get("connectionName")
        == AGENT_CONNECTOR
    ]
    require(
        len(agent_calls) == 1,
        "R5",
        "Flow B must contain exactly one metered agent action",
    )
    if agent_calls:
        call = agent_calls[0]
        host = call["inputs"]["host"]
        params = call["inputs"].get("parameters", {})
        require(
            host.get("operationId") == AGENT_OPERATION,
            "R5",
            "Flow B must use shared_agentnode/InvokeAgent",
        )
        require(
            set(params) == {"body/agentId", "body/prompt"},
            "R5",
            "InvokeAgent must use exactly body/agentId and body/prompt",
        )
    prompt = find_action(flows["B"], "COMPOSE_agent_prompt")
    prompt_text = str(prompt.get("inputs", ""))
    require(
        "['SourceUrl']" in prompt_text and "['TemplateUrl']" in prompt_text,
        "R5",
        "agent prompt must receive one concrete source file and exact template path",
    )
    require(
        "positionFolderPath" not in prompt_text,
        "R5",
        "agent prompt must not use a folder as sourcePath",
    )
    require(
        bool(find_action(flows["A"], "Find_preferred_competitor")),
        "R5/C4",
        "Flow A must suppress the non-preferred member of PDF/DOCX pairs",
    )
    processing_raw = raw(flows["B"])
    require(
        '"type":"Workflow"' not in processing_raw
        and "generatedContent" not in processing_raw,
        "R5",
        "the guessed child-flow/base64 response contract must not return",
    )
    require(
        all(token in processing_raw for token in ("OK", "FAILED", "SKIPPED")),
        "R5",
        "Flow B must classify all agent report statuses",
    )
    require(
        "AgentResultJson" in processing_raw,
        "R5",
        "Flow B must persist the complete parsed agent report",
    )


def validate_r6(config, flows):
    configured = {
        connection["connectorId"].rsplit("/", 1)[-1]
        for connection in config["connectionReferences"]
    }
    require(
        configured <= ALLOWED_CONNECTORS,
        "R6",
        "only approved Microsoft connectors may be configured; found %s"
        % sorted(configured - ALLOWED_CONNECTORS),
    )
    used = set()
    for flow in flows.values():
        used |= set(flow["properties"].get("connectionReferences", {}))
    require(
        used <= ALLOWED_CONNECTORS,
        "R6",
        "flows use an unapproved connector: %s"
        % sorted(used - ALLOWED_CONNECTORS),
    )
    all_text = "".join(raw(flow) for flow in flows.values())
    require(
        "client-secret" not in all_text.lower()
        and "clientid" not in all_text.lower()
        and "tenantid" not in all_text.lower(),
        "R6",
        "flow definitions must not require an Entra application credential",
    )


def validate_r7(flows, lists):
    rollback = flows["D"]
    require(
        bool(find_action(rollback, "PARSE_agent_result")),
        "R7",
        "rollback must parse the persisted agent result",
    )
    require(
        bool(find_action(rollback, "DELETE_generated_output")),
        "R7",
        "rollback must remove generated outputs, including first-time outputs",
    )
    require(
        bool(find_action(rollback, "For_each_archived_file"))
        and bool(find_action(rollback, "RESTORE_archived_file")),
        "R7",
        "rollback must restore every archived displaced file",
    )
    require(
        bool(find_action(rollback, "Mark_item_rolled_back"))
        and bool(find_action(rollback, "Mark_run_rolled_back")),
        "R7",
        "rollback status must be derived from complete item restoration",
    )
    work_item = next(
        definition
        for definition in lists["lists"]
        if definition["name"] == "RegenerationWorkItem"
    )
    columns = {column["name"]: column for column in work_item["columns"]}
    require(
        "AgentResultJson" in columns and "RollbackResultJson" in columns,
        "R7",
        "work items must persist forward and rollback manifests",
    )
    require(
        "RolledBack" in columns["Status"].get("choices", []),
        "R7",
        "work item status choices must include RolledBack",
    )


def validate_delivery(config, flows):
    require(
        os.path.exists(SOLUTION_XML) and os.path.exists(CUSTOMIZATIONS_XML),
        "DELIVERY",
        "full solution metadata must be generated",
    )
    if os.path.exists(SOLUTION_XML):
        roots = [
            element
            for element in ET.parse(SOLUTION_XML).iter("RootComponent")
            if element.get("type") == "29"
        ]
        require(
            len(roots) == len(FLOW_FILES),
            "DELIVERY",
            "Solution.xml must declare all seven workflow roots",
        )
    customizations = ET.parse(CUSTOMIZATIONS_XML)
    declared_workflows = list(customizations.iter("Workflow"))
    require(
        len(declared_workflows) == len(FLOW_FILES),
        "DELIVERY",
        "Customizations.xml must declare all seven workflows",
    )

    with open(
        os.path.join(ROOT, ".github", "workflows", "validate.yml"),
        encoding="utf-8",
    ) as handle:
        validate_workflow = handle.read()
    with open(
        os.path.join(ROOT, ".github", "workflows", "deploy.yml"),
        encoding="utf-8",
    ) as handle:
        deploy_workflow = handle.read()
    for generator in (
        "generate_solution_shell.py --check",
        "generate_processing_flow.py --check",
        "generate_rollback_flow.py --check",
        "validate_requirements.py",
    ):
        require(
            generator in validate_workflow,
            "DELIVERY",
            "validation workflow must run %s" % generator,
        )
    require(
        "solution-folder: solution/src" in deploy_workflow,
        "DELIVERY",
        "deployment must pack the authoritative full solution",
    )
    require(
        "solution-folder: harness/src" not in deploy_workflow,
        "DELIVERY",
        "deployment must not deploy the diagnostic harness",
    )


def main():
    flows = {
        key: load_json(os.path.join(FLOW_DIR, filename))
        for key, filename in FLOW_FILES.items()
    }
    config = load_json(CONFIG_PATH)
    lists = load_json(LISTS_PATH)

    validate_r1(flows)
    validate_r2(flows)
    validate_r3_r4(config, flows)
    validate_r5(config, flows)
    validate_r6(config, flows)
    validate_r7(flows, lists)
    validate_delivery(config, flows)

    if errors:
        for error in errors:
            print("ERROR: %s" % error)
        print("\n%d requirement error(s)." % len(errors))
        return 1

    print("Requirements R1-R7 are statically covered.")
    print("Tenant import and live acceptance remain the separate D1-D7 gate.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
