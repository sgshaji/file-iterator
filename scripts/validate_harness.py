#!/usr/bin/env python3
"""Validate the PD Conversion Harness.

Every check here exists because the reference flow failed it. This is a
regression suite against a specific, real, shipped set of defects rather than a
generic linter - which is why each failure message names the defect it guards.

The reference flow's central failure could not have been caught by review of
intent: it contained an `If` action whose two branches were both empty objects,
with the agent call as the If's SIBLING rather than its child. The exclusion
filter was visible in the designer and did nothing. A machine check finds that
in milliseconds; a human reading the designer does not.

Usage:
    python3 scripts/validate_harness.py
"""

import json
import os
import re
import sys
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HARNESS = os.path.join(ROOT, "harness")
WORKFLOWS = os.path.join(HARNESS, "src", "Workflows")
SOLUTION_XML = os.path.join(HARNESS, "src", "Other", "Solution.xml")
CUSTOMIZATIONS_XML = os.path.join(HARNESS, "src", "Other", "Customizations.xml")
ENV_VARS_JSON = os.path.join(HARNESS, "config", "environment-variables.json")

AGENT_SCHEMA_NAME = "cree1_pdconversionassistant_08zNQw"
AGENT_CONNECTOR = "shared_agentnode"
AGENT_OPERATION = "InvokeAgent"

# From pd_tools.py lines 70-81. Harness defaults must equal these, because the
# flow decides what to enqueue and the skill decides what it will act on. Drift
# means the flow queues work the skill silently declines - after the metered
# call is already spent.
SKILL_OUTPUT_FOLDERS = ["Archive", "AD Documents"]
SKILL_CONVERTIBLE_EXT = [".pdf", ".docx"]

# Values from the reference export's demo tenant. None may appear in the
# harness: the reference flow hard-coded all of them, in four actions and
# inside the agent prompt.
DEMO_TENANT_LITERALS = [
    "m365cpi10857483",
    "DemoFiles",
    "7e12fd88-03ad-48ad-8b99-6f1c9fb7bd1d",
    "/Shared Documents/NH/",
    "hr-policies-compliance",
]

errors = []
warnings = []


def fail(defect, message):
    errors.append("[%s] %s" % (defect, message))


def warn(message):
    warnings.append(message)


def load_json(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def walk_actions(actions, path=""):
    """Yield (name, action, dotted_path) for every action at every depth.

    Nested branches live under several different keys depending on action type,
    so they are all followed. Missing any of them would let a defect hide inside
    an else branch - which is exactly where the reference flow's defect was.
    """
    for name, action in (actions or {}).items():
        here = "%s/%s" % (path, name) if path else name
        yield name, action, here
        if not isinstance(action, dict):
            continue
        for child in (action.get("actions"), action.get("else", {}).get("actions")):
            for item in walk_actions(child, here):
                yield item
        for case in (action.get("cases") or {}).values():
            for item in walk_actions(case.get("actions"), here):
                yield item
        for item in walk_actions(action.get("default", {}).get("actions"), here):
            yield item


# ---------------------------------------------------------------------------

def check_files_exist():
    for path in (SOLUTION_XML, CUSTOMIZATIONS_XML, ENV_VARS_JSON):
        if not os.path.exists(path):
            fail("STRUCTURE", "Missing required file: %s" %
                 os.path.relpath(path, ROOT))
    if not os.path.isdir(WORKFLOWS) or not os.listdir(WORKFLOWS):
        fail("STRUCTURE", "No workflow definitions in harness/src/Workflows/.")


def check_no_empty_branches(flow_name, actions):
    """P1. The defect that made the reference flow's filter decorative.

    An If, Switch or Scope in which every branch is empty is not a filter; it is
    a comment that looks like a filter. The reference flow shipped one, and
    because the agent call sat outside it, every file was converted.
    """
    for name, action, path in walk_actions(actions):
        if not isinstance(action, dict):
            continue
        kind = action.get("type")

        if kind == "If":
            then_branch = action.get("actions") or {}
            else_branch = (action.get("else") or {}).get("actions") or {}
            if not then_branch and not else_branch:
                fail("P1", "%s: If action '%s' has BOTH branches empty. This is "
                           "the exact defect that made the reference flow's "
                           "exclusion filter decorative." % (flow_name, path))
            elif not then_branch:
                # Legitimate only if the else branch carries the logic. Flag it
                # so the asymmetry is a decision rather than an accident.
                warn("%s: If action '%s' has an empty 'then' branch; all logic "
                     "is in 'else'. Confirm the condition is not inverted."
                     % (flow_name, path))

        if kind == "Switch":
            cases = action.get("cases") or {}
            default = (action.get("default") or {}).get("actions") or {}
            if not any((c.get("actions") or {}) for c in cases.values()) and not default:
                fail("P1", "%s: Switch action '%s' has no case with any actions."
                     % (flow_name, path))

        if kind in ("Scope", "Foreach", "Until") and not (action.get("actions") or {}):
            fail("P1", "%s: %s action '%s' contains no actions."
                 % (flow_name, kind, path))


def check_no_recursive_enumeration(flow_name, raw):
    """P3. The enumeration method that is already proven to throw at scale.

    RecursiveAll - whether as the connector's viewScopeOption or as CAML
    Scope='RecursiveAll' - asks SharePoint to scan the whole subtree. The
    5,000-item threshold counts items scanned, not returned, so this throws
    SPQueryThrottledException on the production library. The reference flow used
    both forms.
    """
    if "RecursiveAll" in raw:
        fail("P3", "%s: uses RecursiveAll. The 5,000-item threshold counts items "
                   "SCANNED, not returned, so recursive enumeration throws "
                   "SPQueryThrottledException on the production library. Walk "
                   "direct children instead." % flow_name)

    if re.search(r"<\s*View\b", raw) or "ViewXml" in raw:
        fail("P4", "%s: contains a CAML query. The reference flow's CAML action "
                   "was both throttling and dead - its output was never "
                   "referenced." % flow_name)


def check_agent_invocation(flow_name, flow, actions):
    """The agent must be REUSED, through the mechanism the export proves works."""
    invocations = [
        (path, a) for _, a, path in walk_actions(actions)
        if isinstance(a, dict)
        and a.get("type") == "OpenApiConnection"
        and (a.get("inputs", {}).get("host", {}) or {}).get("connectionName") == AGENT_CONNECTOR
    ]

    if not invocations:
        fail("AGENT", "%s: no agent invocation found. Expected an "
                      "OpenApiConnection on '%s'." % (flow_name, AGENT_CONNECTOR))
        return

    for path, action in invocations:
        host = action["inputs"]["host"]
        if host.get("operationId") != AGENT_OPERATION:
            fail("AGENT", "%s: agent call '%s' uses operationId '%s'; the "
                          "reference export proves the working operation is "
                          "'%s'." % (flow_name, path, host.get("operationId"),
                                     AGENT_OPERATION))

        params = action["inputs"].get("parameters", {})
        for required in ("body/agentId", "body/prompt"):
            if required not in params:
                fail("AGENT", "%s: agent call '%s' is missing '%s'."
                     % (flow_name, path, required))

    # The response must actually be consumed. The reference flow invoked the
    # agent and threw the reply away, which is what reduced it from a harness to
    # a fire-and-forget trigger.
    raw = json.dumps(flow)
    if "ParseJson" not in raw:
        fail("P5", "%s: the agent response is never parsed. The reference flow "
                   "discarded it and always reported success; the skill returns "
                   "a structured report precisely so a flow can branch on it."
             % flow_name)

    for token in ("'OK'", "'FAILED'", "'SKIPPED'"):
        if token not in raw:
            fail("P5", "%s: does not branch on agent status %s. The skill's "
                       "status values are a closed set and SKIPPED must stay "
                       "distinct from FAILED - conflating them misreports a "
                       "healthy run." % (flow_name, token))


def check_terminal_status_is_derived(flow_name, actions):
    """P5. A flow that always reports success cannot be a harness."""
    terminates = [
        (path, a) for _, a, path in walk_actions(actions)
        if isinstance(a, dict) and a.get("type") == "Terminate"
    ]
    if not terminates:
        fail("P5", "%s: no Terminate action; terminal status is not explicit."
             % flow_name)
        return

    if not any(a.get("inputs", {}).get("runStatus") == "Failed"
               for _, a in terminates):
        fail("P5", "%s: no Terminate with runStatus 'Failed'. The reference flow "
                   "terminated Succeeded unconditionally and so could not "
                   "distinguish 400 conversions from 400 failures." % flow_name)

    # A Succeeded terminate that no condition guards is the reference defect.
    for path, action in terminates:
        if action.get("inputs", {}).get("runStatus") != "Succeeded":
            continue
        if "/" not in path:
            fail("P5", "%s: Terminate '%s' reports success at top level, "
                       "unguarded by any condition." % (flow_name, path))


def check_cost_controls(flow_name, raw, actions):
    """P6/COST. The agent call is the only metered operation in the system."""
    if "maxDocuments" not in raw:
        fail("COST", "%s: no maxDocuments cap. Without a hard ceiling one "
                     "misconfiguration is a full-library conversion at full "
                     "cost." % flow_name)

    if "dryRun" not in raw:
        fail("COST", "%s: no dryRun gate. The enumeration and planning logic "
                     "must be testable without spending anything." % flow_name)

    # The agent call must sit inside the dry-run gate. If it is a sibling it
    # runs regardless - which is structurally the same mistake as P1.
    for _, action, path in walk_actions(actions):
        if (isinstance(action, dict)
                and action.get("type") == "OpenApiConnection"
                and (action.get("inputs", {}).get("host", {}) or {}).get(
                    "connectionName") == AGENT_CONNECTOR):
            if "EXECUTE_check_dry_run" not in path:
                fail("COST", "%s: agent call '%s' is NOT inside the dry-run "
                             "gate. A dry run would invoke it and incur cost."
                     % (flow_name, path))

    for _, action, path in walk_actions(actions):
        if isinstance(action, dict) and action.get("type") == "Foreach":
            concurrency = (action.get("runtimeConfiguration", {})
                           .get("concurrency", {}).get("repetitions"))
            if concurrency is None:
                warn("%s: Foreach '%s' does not pin concurrency; the default "
                     "may parallelise agent calls." % (flow_name, path))


def check_no_hardcoded_environment(flow_name, raw):
    """P8. Every environment value in the reference flow was a literal."""
    for literal in DEMO_TENANT_LITERALS:
        if literal in raw:
            fail("P8", "%s: contains demo-tenant literal '%s'. Environment "
                       "values belong in environment variables." %
                 (flow_name, literal))

    for match in re.finditer(r"https://[a-z0-9\-]+\.sharepoint\.com", raw):
        fail("P8", "%s: contains a hard-coded SharePoint URL '%s'."
             % (flow_name, match.group(0)))


def check_pagination(flow_name, raw):
    """P12. 5,000 property rows at ~8.2 KB each blows the 16 MB action cap."""
    for match in re.finditer(r'"minimumItemCount"\s*:\s*(\d+)', raw):
        count = int(match.group(1))
        if count > 2000:
            fail("P12", "%s: paginationPolicy minimumItemCount is %d. At ~8.2 KB "
                        "per property row the 16 MB action output cap is reached "
                        "near 2,000 rows." % (flow_name, count))


def check_solution_shell():
    """The agent is referenced, never owned."""
    if not os.path.exists(SOLUTION_XML):
        return

    raw = open(SOLUTION_XML, encoding="utf-8").read()
    tree = ET.parse(SOLUTION_XML)

    for component in tree.iter("RootComponent"):
        ctype = component.get("type")
        schema = component.get("schemaName", "")
        if ctype == "10056" or schema.startswith("cree1_"):
            fail("AGENT", "Solution.xml declares the agent (type=%s, "
                          "schemaName=%s) as a root component. The harness must "
                          "REFERENCE the existing agent, not take ownership of "
                          "it - that would fork its instructions, its five tools "
                          "and the pd-ad-conversion skill." % (ctype, schema))

    if "<bots>" in raw.lower():
        fail("AGENT", "Solution.xml contains a <bots> element. The harness must "
                      "not carry the agent definition.")

    workflow_ids = [c.get("id") for c in tree.iter("RootComponent")
                    if c.get("type") == "29"]
    if not workflow_ids:
        fail("STRUCTURE", "Solution.xml declares no workflow root component.")
    for wid in workflow_ids:
        if wid and "6e2ce50c" in wid.lower():
            fail("STRUCTURE", "Solution.xml reuses the reference flow's workflow "
                              "GUID. The harness is a new flow and needs a new id.")


def check_connection_references():
    if not os.path.exists(CUSTOMIZATIONS_XML):
        return

    tree = ET.parse(CUSTOMIZATIONS_XML)
    names = [c.get("connectionreferencelogicalname", "")
             for c in tree.iter("connectionreference")]

    for name in names:
        if name.startswith("cree1_"):
            fail("AGENT", "Customizations.xml declares agent-owned connection "
                          "reference '%s'. Those belong to the agent." % name)
        elif not name.startswith("pdh_"):
            fail("STRUCTURE", "Connection reference '%s' does not use the "
                              "harness prefix 'pdh_'." % name)

    if not names:
        fail("STRUCTURE", "Customizations.xml declares no connection references.")


def check_contract_constants():
    """Flow configuration must agree with the skill's own constants.

    The flow decides what to enqueue; the skill decides what it will act on. If
    those disagree the flow enqueues work the skill declines - and the metered
    call is spent before the decline is known.
    """
    if not os.path.exists(ENV_VARS_JSON):
        return

    data = load_json(ENV_VARS_JSON)
    variables = {v.get("schemaName"): v for v in data.get("environmentVariables", [])}

    checks = [
        ("pdh_ExcludedFolderNames", SKILL_OUTPUT_FOLDERS,
         "pd_tools.py OUTPUT_FOLDERS"),
        ("pdh_SourceExtensions", SKILL_CONVERTIBLE_EXT,
         "pd_tools.py CONVERTIBLE_EXT"),
    ]

    for schema_name, expected, source in checks:
        variable = variables.get(schema_name)
        if variable is None:
            fail("CONTRACT", "Environment variable '%s' is missing." % schema_name)
            continue
        actual = [p.strip() for p in
                  str(variable.get("defaultValue", "")).split(",") if p.strip()]
        if [a.lower() for a in actual] != [e.lower() for e in expected]:
            fail("CONTRACT", "%s default is %s but %s is %s. Drift here means the "
                             "flow enqueues work the skill silently declines, "
                             "after the agent call is already paid for."
                 % (schema_name, actual, source, expected))

    agent_var = variables.get("pdh_AgentId")
    if agent_var is None:
        fail("CONTRACT", "Environment variable 'pdh_AgentId' is missing.")
    elif agent_var.get("defaultValue") != AGENT_SCHEMA_NAME:
        fail("CONTRACT", "pdh_AgentId default is '%s'; the existing agent's "
                         "schema name is '%s'. Addressing the agent by schema "
                         "name rather than GUID is what makes reuse portable "
                         "across environments."
             % (agent_var.get("defaultValue"), AGENT_SCHEMA_NAME))

    dry_run = variables.get("pdh_DryRun")
    if dry_run is not None and str(dry_run.get("defaultValue")).lower() != "true":
        fail("COST", "pdh_DryRun must default to true, so an unconfigured import "
                     "cannot spend anything.")


def check_flow(path):
    flow_name = os.path.basename(path)
    flow = load_json(path)
    raw = json.dumps(flow)

    definition = flow.get("properties", {}).get("definition", {})
    actions = definition.get("actions", {})

    if not definition.get("triggers"):
        fail("STRUCTURE", "%s: no trigger." % flow_name)
    if not actions:
        fail("STRUCTURE", "%s: no actions." % flow_name)
        return

    check_no_empty_branches(flow_name, actions)
    check_no_recursive_enumeration(flow_name, raw)
    check_agent_invocation(flow_name, flow, actions)
    check_terminal_status_is_derived(flow_name, actions)
    check_cost_controls(flow_name, raw, actions)
    check_no_hardcoded_environment(flow_name, raw)
    check_pagination(flow_name, raw)

    # Every runAfter must name an action that exists as a sibling. A typo here
    # silently detaches an action, which is how a filter ends up not filtering.
    def check_run_after(scope, scope_name):
        for name, action in (scope or {}).items():
            if not isinstance(action, dict):
                continue
            for dependency in (action.get("runAfter") or {}):
                if dependency not in scope:
                    fail("STRUCTURE", "%s: action '%s' in %s runs after '%s', "
                                      "which is not a sibling. The dependency is "
                                      "silently ignored at runtime."
                         % (flow_name, name, scope_name, dependency))
            for child, child_name in (
                (action.get("actions"), "%s/%s" % (scope_name, name)),
                ((action.get("else") or {}).get("actions"),
                 "%s/%s[else]" % (scope_name, name)),
            ):
                if child:
                    check_run_after(child, child_name)

    check_run_after(actions, "root")


def main():
    print("Validating PD Conversion Harness")
    print("=" * 70)

    check_files_exist()
    check_solution_shell()
    check_connection_references()
    check_contract_constants()

    if os.path.isdir(WORKFLOWS):
        for name in sorted(os.listdir(WORKFLOWS)):
            if name.endswith(".json"):
                check_flow(os.path.join(WORKFLOWS, name))
                print("  checked %s" % name)

    print("=" * 70)

    for warning in warnings:
        print("WARNING: %s" % warning)

    if errors:
        print("\n%d error(s):" % len(errors))
        for error in errors:
            print("  %s" % error)
        sys.exit(1)

    print("All harness checks passed (%d warning(s))." % len(warnings))


if __name__ == "__main__":
    main()
