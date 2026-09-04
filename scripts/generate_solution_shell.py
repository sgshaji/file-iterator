#!/usr/bin/env python3
"""Generate the Power Platform solution shell for the full solution source."""

import argparse
import json
import os
import sys
from xml.sax.saxutils import escape


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(
    ROOT, "solution", "config", "environment-variables.json"
)
WORKFLOW_DIR = os.path.join(ROOT, "solution", "src", "Workflows")
OTHER_DIR = os.path.join(ROOT, "solution", "src", "Other")
SOLUTION_PATH = os.path.join(OTHER_DIR, "Solution.xml")
CUSTOMIZATIONS_PATH = os.path.join(OTHER_DIR, "Customizations.xml")

SOLUTION_NAME = "fileiteratortemplateregeneration"
SOLUTION_DISPLAY_NAME = "File Iterator Template Regeneration"
SOLUTION_VERSION = "1.0.0.0"
PUBLISHER_NAME = "fileiterator"
PUBLISHER_DISPLAY_NAME = "File Iterator"
PUBLISHER_PREFIX = "fi"
PUBLISHER_OPTION_PREFIX = "72411"
AGENT_SCHEMA_NAME = "cree1_pdconversionassistant_08zNQw"

WORKFLOWS = [
    (
        "A-PlanRegenerationRun.json",
        "a1000000-0000-4000-8000-000000000001",
        "A - Plan Regeneration Run",
    ),
    (
        "B-ProcessRegenerationBatch.json",
        "b2000000-0000-4000-8000-000000000002",
        "B - Process Regeneration Batch",
    ),
    (
        "C-FinaliseRegenerationRun.json",
        "c3000000-0000-4000-8000-000000000003",
        "C - Finalise Regeneration Run",
    ),
    (
        "D-RollbackRegenerationRun.json",
        "d4000000-0000-4000-8000-000000000004",
        "D - Rollback Regeneration Run",
    ),
    (
        "E1-StartIndexBackfill.json",
        "e5100000-0000-4000-8000-000000000005",
        "E1 - Start Index Backfill",
    ),
    (
        "E2-IndexBackfillWorker.json",
        "e5200000-0000-4000-8000-000000000006",
        "E2 - Index Backfill Worker",
    ),
    (
        "F-IndexDelta.json",
        "f6000000-0000-4000-8000-000000000007",
        "F - Index Delta",
    ),
]

TYPE_CODES = {
    "String": "100000000",
    "Number": "100000001",
    "Boolean": "100000002",
}


def load_config():
    with open(CONFIG_PATH, encoding="utf-8") as handle:
        return json.load(handle)


def xml(value):
    return escape(str(value), {'"': "&quot;"})


def default_value(value):
    if isinstance(value, bool):
        return "1" if value else "0"
    return str(value)


def render_solution(config):
    workflow_roots = "\n".join(
        '      <RootComponent type="29" id="{%s}" behavior="0" />' % workflow_id
        for _, workflow_id, _ in WORKFLOWS
    )
    variable_roots = "\n".join(
        '      <RootComponent type="380" schemaName="%s" behavior="0" />'
        % xml(variable["schemaName"])
        for variable in config["environmentVariables"]
    )
    connection_roots = "\n".join(
        '      <RootComponent type="10099" schemaName="%s" behavior="0" />'
        % xml(connection["schemaName"])
        for connection in config["connectionReferences"]
    )

    return f"""<?xml version="1.0" encoding="utf-8"?>
<ImportExportXml version="9.2" SolutionPackageVersion="9.2" languagecode="1033" generatedBy="generate_solution_shell.py" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <SolutionManifest>
    <UniqueName>{SOLUTION_NAME}</UniqueName>
    <LocalizedNames>
      <LocalizedName description="{SOLUTION_DISPLAY_NAME}" languagecode="1033" />
    </LocalizedNames>
    <Descriptions>
      <Description description="Template-triggered, resumable SharePoint document regeneration using the existing PD Conversion Assistant agent." languagecode="1033" />
    </Descriptions>
    <Version>{SOLUTION_VERSION}</Version>
    <Managed>2</Managed>
    <Publisher>
      <UniqueName>{PUBLISHER_NAME}</UniqueName>
      <LocalizedNames>
        <LocalizedName description="{PUBLISHER_DISPLAY_NAME}" languagecode="1033" />
      </LocalizedNames>
      <Descriptions>
        <Description description="Publisher for the File Iterator template regeneration solution." languagecode="1033" />
      </Descriptions>
      <EMailAddress xsi:nil="true"></EMailAddress>
      <SupportingWebsiteUrl xsi:nil="true"></SupportingWebsiteUrl>
      <CustomizationPrefix>{PUBLISHER_PREFIX}</CustomizationPrefix>
      <CustomizationOptionValuePrefix>{PUBLISHER_OPTION_PREFIX}</CustomizationOptionValuePrefix>
      <Addresses></Addresses>
    </Publisher>
    <RootComponents>
{workflow_roots}
{variable_roots}
{connection_roots}
    </RootComponents>
    <MissingDependencies>
      <MissingDependency>
        <Required type="10056" schemaName="{AGENT_SCHEMA_NAME}" displayName="PD Conversion Assistant" solution="pdconversionassistant" />
        <Dependent type="29" displayName="B - Process Regeneration Batch" />
      </MissingDependency>
    </MissingDependencies>
  </SolutionManifest>
</ImportExportXml>
"""


def render_workflow(filename, workflow_id, display_name):
    return f"""    <Workflow WorkflowId="{{{workflow_id}}}" Name="{xml(display_name)}">
      <JsonFileName>/Workflows/{xml(filename)}</JsonFileName>
      <Type>1</Type>
      <Subprocess>0</Subprocess>
      <Category>5</Category>
      <Mode>0</Mode>
      <Scope>4</Scope>
      <OnDemand>0</OnDemand>
      <TriggerOnCreate>0</TriggerOnCreate>
      <TriggerOnDelete>0</TriggerOnDelete>
      <AsyncAutodelete>0</AsyncAutodelete>
      <SyncWorkflowLogOnFailure>0</SyncWorkflowLogOnFailure>
      <StateCode>0</StateCode>
      <StatusCode>1</StatusCode>
      <RunAs>1</RunAs>
      <IsTransacted>1</IsTransacted>
      <IntroducedVersion>1.0.0.0</IntroducedVersion>
      <IsCustomizable>1</IsCustomizable>
      <IsCustomProcessingStepAllowedForOtherPublishers>1</IsCustomProcessingStepAllowedForOtherPublishers>
      <ModernFlowType>1</ModernFlowType>
      <PrimaryEntity>none</PrimaryEntity>
      <LocalizedNames>
        <LocalizedName languagecode="1033" description="{xml(display_name)}" />
      </LocalizedNames>
    </Workflow>"""


def render_connection(connection):
    return f"""    <connectionreference connectionreferencelogicalname="{xml(connection['schemaName'])}">
      <connectionreferencedisplayname>{xml(connection['displayName'])}</connectionreferencedisplayname>
      <connectorid>{xml(connection['connectorId'])}</connectorid>
      <iscustomizable>1</iscustomizable>
      <promptingbehavior>0</promptingbehavior>
      <statecode>0</statecode>
      <statuscode>1</statuscode>
    </connectionreference>"""


def render_variable(variable):
    type_code = TYPE_CODES.get(variable["type"])
    if type_code is None:
        raise ValueError("Unsupported environment variable type: %s" % variable["type"])

    default = variable.get("defaultValue")
    default_element = ""
    if default not in (None, ""):
        default_element = "\n      <defaultvalue>%s</defaultvalue>" % xml(
            default_value(default)
        )

    return f"""    <environmentvariabledefinition schemaname="{xml(variable['schemaName'])}">
      <displayname>{xml(variable['displayName'])}</displayname>
      <type>{type_code}</type>
      <isrequired>{1 if variable.get('required') else 0}</isrequired>{default_element}
      <introducedversion>1.0.0.0</introducedversion>
      <description>{xml(variable.get('description', ''))}</description>
    </environmentvariabledefinition>"""


def render_customizations(config):
    workflows = "\n".join(render_workflow(*workflow) for workflow in WORKFLOWS)
    connections = "\n".join(
        render_connection(connection) for connection in config["connectionReferences"]
    )
    variables = "\n".join(
        render_variable(variable) for variable in config["environmentVariables"]
    )

    return f"""<?xml version="1.0" encoding="utf-8"?>
<ImportExportXml xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" OrganizationVersion="9.2" OrganizationSchemaType="Standard">
  <Entities></Entities>
  <Roles></Roles>
  <Workflows>
{workflows}
  </Workflows>
  <FieldSecurityProfiles></FieldSecurityProfiles>
  <Templates />
  <EntityMaps />
  <EntityRelationships />
  <OrganizationSettings />
  <optionsets />
  <CustomControls />
  <EntityDataProviders />
  <connectionreferences>
{connections}
  </connectionreferences>
  <environmentvariabledefinitions>
{variables}
  </environmentvariabledefinitions>
</ImportExportXml>
"""


def write_or_check(path, content, check):
    if check:
        if not os.path.exists(path):
            print("ERROR: generated file is missing: %s" % os.path.relpath(path, ROOT))
            return False
        with open(path, encoding="utf-8") as handle:
            current = handle.read()
        if current != content:
            print("ERROR: generated file is out of date: %s" % os.path.relpath(path, ROOT))
            return False
        return True

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)
    print("Generated %s" % os.path.relpath(path, ROOT))
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check", action="store_true", help="fail if generated files differ"
    )
    args = parser.parse_args()

    for filename, _, _ in WORKFLOWS:
        workflow_path = os.path.join(WORKFLOW_DIR, filename)
        if not os.path.exists(workflow_path):
            print("ERROR: workflow is missing: %s" % os.path.relpath(workflow_path, ROOT))
            return 1

    config = load_config()
    try:
        solution = render_solution(config)
        customizations = render_customizations(config)
    except (KeyError, ValueError) as exc:
        print("ERROR: %s" % exc)
        return 1

    ok = write_or_check(SOLUTION_PATH, solution, args.check)
    ok = write_or_check(CUSTOMIZATIONS_PATH, customizations, args.check) and ok
    if args.check and ok:
        print("Solution shell is up to date.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
