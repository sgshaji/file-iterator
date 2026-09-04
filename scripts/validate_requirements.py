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
    "A2": "A2-ContinueRegenerationPlan.json",
    "A3": "A3-ApproveRegenerationPlan.json",
    "B": "B-ProcessRegenerationBatch.json",
    "C": "C-FinaliseRegenerationRun.json",
    "D": "D-RollbackRegenerationRun.json",
    "D2": "D2-ContinueRollback.json",
    "E1": "E1-StartIndexBackfill.json",
    "E2": "E2-IndexBackfillWorker.json",
    "F": "F-IndexDelta.json",
    "F2": "F2-IndexDelete.json",
    "F3": "F3-IndexFolderChange.json",
}

AGENT_ID = "cree1_pdconversionassistant_08zNQw"
AGENT_CONNECTOR = "shared_agentnode"
AGENT_OPERATION = "InvokeAgent"
SUPPORTED_EXTENSIONS = [".pdf", ".docx"]
EXCLUDED_FOLDERS = ["Archive", "AD Documents"]
ALLOWED_CONNECTORS = {
    "shared_sharepointonline",
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
    require(
        trigger.get("runtimeConfiguration", {})
        .get("concurrency", {})
        .get("runs")
        == 1,
        "R1",
        "Flow A trigger must serialize duplicate publish deliveries",
    )
    fingerprint = find_action(plan, "Compose_template_fingerprint")
    require(
        "VersionNumber" in str(fingerprint.get("inputs", ""))
        and "Modified" not in str(fingerprint.get("inputs", "")),
        "R1/C4",
        "publication identity must be stable across metadata-only trigger deliveries",
    )
    gate = find_action(plan, "GATE_explicit_publish")
    require(
        "published" in json.dumps(gate).lower(),
        "R1",
        "Flow A must require the explicit Published signal",
    )
    require(
        bool(find_action(plan, "Get_active_duplicate")),
        "R1",
        "Flow A must suppress duplicate active runs for the same fingerprint",
    )
    require(
        bool(find_action(plan, "GATE_latest_index_is_complete"))
        and bool(find_action(flows["A2"], "Get_newer_index_walk"))
        and bool(find_action(flows["A3"], "Get_newer_index_walk")),
        "R1/R2",
        "planning and approval must be invalidated by any newer index walk",
    )
    duplicate_filter = str(
        find_action(plan, "Get_active_duplicate")
        .get("inputs", {})
        .get("parameters", {})
        .get("$filter", "")
    )
    require(
        "RunKey eq" in duplicate_filter
        and "CompletedWithErrors" in duplicate_filter
        and "Status ne" in duplicate_filter,
        "R1",
        "duplicate delivery suppression must preserve live-after-dry promotion and errored-run retry",
    )
    require(
        bool(find_action(flows["A2"], "Create_work_item")),
        "R1",
        "Flow A must persist one work item per selected source",
    )
    require(
        bool(find_action(flows["A3"], "Patch_approval_outcome")),
        "R1",
        "A3 must apply an audited SharePoint approval decision before execution",
    )
    approval_raw = raw(flows["A3"])
    require(
        "SecondConfirmation" in approval_raw
        and "RequiresSecondConfirmation" in approval_raw
        and "Confirmed" in approval_raw,
        "R1/C5",
        "large plans must require a second explicit confirmation",
    )
    require(
        list(triggers(flows["B"]).values())[0].get("type") == "Recurrence",
        "R1",
        "Flow B must drain approved work on a schedule",
    )
    require(
        list(triggers(flows["B"]).values())[0]
        .get("runtimeConfiguration", {})
        .get("concurrency", {})
        .get("runs")
        == 1,
        "R1/C4",
        "Flow B trigger concurrency must be one to prevent duplicate claims",
    )
    require(
        bool(find_action(flows["B"], "Get_approved_run"))
        and bool(find_action(flows["B"], "Get_rollback_lock")),
        "R1/R7",
        "Flow B must resume Running before Approved and stop during rollback",
    )
    planner_trigger = list(triggers(flows["A2"]).values())[0]
    require(
        planner_trigger.get("type") == "Recurrence"
        and planner_trigger.get("runtimeConfiguration", {})
        .get("concurrency", {})
        .get("runs")
        == 1,
        "R1/C2",
        "A2 must page the index through a single-concurrency recurrence",
    )
    page = find_action(flows["A2"], "Get_source_page")
    require(
        "PlanningPageSize"
        in str(page.get("inputs", {}).get("parameters", {}).get("$top", ""))
        and "PlanningCursorId"
        in str(page.get("inputs", {}).get("parameters", {}).get("$filter", "")),
        "R1/C2",
        "A2 must read bounded pages after a persisted cursor",
    )
    require(
        '"$top":5000' not in raw(flows["A2"]).replace(" ", ""),
        "R1/C2",
        "the planner must not aggregate a 5,000-row action output",
    )
    existing = find_action(flows["A2"], "Get_existing_current_work_item")
    require(
        "RunId eq" in str(existing.get("inputs", {}).get("parameters", {}).get("$filter", "")),
        "R1",
        "a resumed planning page must skip work items already written by the same run",
    )
    for action_name in ("Get_existing_current_work_item", "Get_prior_success"):
        filter_text = str(
            find_action(flows["A2"], action_name)
            .get("inputs", {})
            .get("parameters", {})
            .get("$filter", "")
        )
        require(
            "replace(items('For_each_candidate')?['DocumentKey']" in filter_text,
            "R1",
            "%s must escape apostrophes in DocumentKey" % action_name,
        )
    require(
        int(config_map(load_json(CONFIG_PATH))["fi_PlanningPageSize"]["defaultValue"])
        <= 1000,
        "R1/C2",
        "planning pages must remain small enough to avoid the 16 MB action cap",
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
    require(
        bool(find_action(flows["E2"], "Record_enumeration_failure")),
        "R2",
        "direct enumeration failures must leave no frontier row stranded InProgress",
    )
    require(
        bool(find_action(flows["E2"], "Get_unfinished_frontier_row")),
        "R2",
        "reconciliation must prove no fresh InProgress frontier row remains",
    )
    require(
        bool(find_action(flows["E1"], "Mark_walk_running"))
        and "Seeding" in raw(flows["E1"]),
        "R2",
        "a walk must not become consumable until its root frontier is seeded",
    )
    require(
        bool(find_action(flows["E2"], "Get_stale_index_chunk"))
        and bool(find_action(flows["E2"], "Advance_or_complete_reconciliation")),
        "R2",
        "a successful full walk must reconcile files that disappeared",
    )
    stale_query = find_action(flows["E2"], "Get_stale_index_chunk")
    stale_filter = str(
        stale_query.get("inputs", {}).get("parameters", {}).get("$filter", "")
    )
    require(
        "LastSeenRunId" not in stale_filter
        and "IndexedAt" not in stale_filter
        and bool(find_action(flows["E2"], "Filter_stale_index_rows")),
        "R2/C1",
        "stale reconciliation must page by indexed ID and filter locally",
    )
    require(
        "IndexWalkRunListName" in worker_raw
        and "CompletedWithErrors" in worker_raw,
        "R2",
        "the backfill must expose an explicit completed or failed snapshot state",
    )
    delta_trigger = list(triggers(flows["F"]).values())[0]
    require(
        delta_trigger.get("inputs", {}).get("host", {}).get("operationId")
        == "GetOnUpdatedFileItems",
        "R2",
        "Flow F must maintain the index with the proven file-change trigger",
    )
    delete_trigger = list(triggers(flows["F2"]).values())[0]
    require(
        delete_trigger.get("inputs", {}).get("host", {}).get("operationId")
        == "GetOnDeletedFileItems",
        "R2",
        "file deletions must disable index rows without waiting for a backfill",
    )
    require(
        bool(find_action(flows["F2"], "HANDLE_deleted_folder"))
        and bool(find_action(flows["F3"], "HANDLE_updated_folder")),
        "R2",
        "folder delete, rename and move events must queue full reconciliation",
    )
    require(
        "{IsFolder}" in raw(flows["F3"]),
        "R2",
        "folder-update reconciliation must use the updated-file trigger token {IsFolder}",
    )
    delta_raw = raw(flows["F"])
    require(
        all(
            token in delta_raw
            for token in (
                "fi_WebServerRelativeUrl",
                "item/FileName",
                "item/Extension",
                "Disable_existing_out_of_scope_row",
                "ListItemId",
                "ParentFolderUniqueId",
                "DocumentStem",
            )
        ),
        "R2",
        "delta indexing must normalize trigger paths and refresh rename metadata",
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
    with open(
        os.path.join(ROOT, "docs", "Template-Regeneration-Solution-Design.md"),
        encoding="utf-8",
    ) as handle:
        design = handle.read()
    require(
        "Legacy `.doc` files must be migrated to `.docx` before indexing" in design,
        "R3",
        "the unsupported legacy .doc boundary must be explicit in the requirement",
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
        require(
            call.get("runtimeConfiguration", {})
            .get("retryPolicy", {})
            .get("type")
            == "None",
            "R5/R7",
            "InvokeAgent connector retries must be explicitly disabled",
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
        bool(find_action(flows["A2"], "GATE_preferred_source")),
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
    require(
        "Persist_agent_call_count" in processing_raw,
        "R5/C4",
        "agent cost must be persisted immediately after each metered call",
    )
    require(
        "AgentEffectState" in processing_raw
        and "ParsedManifest" in processing_raw
        and "UnknownSideEffects" in processing_raw,
        "R5/R7",
        "agent effects must distinguish parsed manifests from unknown side effects",
    )
    require(
        '"type":["integer","null"]' in processing_raw.replace(" ", ""),
        "R5",
        "contract-valid failed reports must allow missing byte counts",
    )
    require(
        "result('PARSE_agent_report')" not in processing_raw
        and bool(find_action(flows["B"], "TRY_parse_agent_report")),
        "R5",
        "ParseJson status must be routed through a scope, not result(ParseJson)",
    )
    require(
        "fi_MaxAttempts" not in processing_raw
        and "Mark_agent_failed_or_retry" not in processing_raw,
        "R5/R7",
        "side-effecting agent attempts must not be retried automatically",
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
    require(
        configured == ALLOWED_CONNECTORS,
        "R6",
        "the solution must declare only SharePoint and the required agent connector",
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
    worker = flows["D2"]
    require(
        bool(find_action(worker, "PARSE_agent_result")),
        "R7",
        "rollback must parse the persisted agent result",
    )
    require(
        bool(find_action(rollback, "Lock_run_for_rollback"))
        and "RollbackInProgress" in raw(rollback),
        "R7",
        "rollback must lock a terminal run before restoring files",
    )
    require(
        bool(find_action(worker, "DELETE_generated_output")),
        "R7",
        "rollback must remove generated outputs, including first-time outputs",
    )
    require(
        bool(find_action(worker, "For_each_archived_file"))
        and bool(find_action(worker, "RESTORE_archived_file")),
        "R7",
        "rollback must restore every archived displaced file",
    )
    require(
        bool(find_action(worker, "Mark_item_rolled_back"))
        and bool(find_action(worker, "Mark_run_rolled_back")),
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
    require(
        "Status eq 'Failed'" in raw(worker)
        and "Get_unrecoverable_failed_items" in raw(worker),
        "R7",
        "rollback must include failed attempts with manifests and reject unknown side effects",
    )
    rollback_page = find_action(worker, "Get_rollback_page")
    require(
        "RollbackPageSize"
        in str(
            rollback_page.get("inputs", {})
            .get("parameters", {})
            .get("$top", "")
        ),
        "R7/C2",
        "rollback must consume manifests through a bounded persisted cursor",
    )
    terminal_page = find_action(flows["C"], "Get_terminal_page")
    require(
        terminal_page.get("inputs", {})
        .get("parameters", {})
        .get("$select")
        == "ID,Status",
        "R7/C2",
        "paged finalization must not retrieve large manifest Note fields",
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
        "generate_planning_flows.py --check",
        "generate_processing_flow.py --check",
        "generate_rollback_flow.py --check",
        "generate_finalization_flow.py --check",
        "generate_folder_update_flow.py --check",
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
    require(
        "materialize_deployment_settings.py" in deploy_workflow
        and "deployment-settings.resolved.json" in deploy_workflow,
        "DELIVERY",
        "deployment must resolve protected environment bindings and import only the resolved settings",
    )
    require(
        "use-deployment-settings-file: true" in deploy_workflow,
        "DELIVERY",
        "Power Platform import must explicitly enable the resolved settings file",
    )
    for binding in (
        "FI_SITE_ADDRESS",
        "FI_WEB_SERVER_RELATIVE_URL",
        "FI_LIBRARY_URL_NAME",
        "FI_ROOT_FOLDER_PATH",
        "FI_TEMPLATE_FOLDER_PATH",
        "FI_SHAREPOINT_CONNECTION_ID",
        "FI_AGENT_CONNECTION_ID",
    ):
        require(
            binding in deploy_workflow,
            "DELIVERY",
            "deployment workflow is missing protected binding %s" % binding,
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
