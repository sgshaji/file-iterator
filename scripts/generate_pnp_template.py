#!/usr/bin/env python3
"""Generate the PnP provisioning template from provisioning/lists.json.

provisioning/lists.json is the single source of truth for the four
supporting lists. This script renders it into a PnP site template so the
two can never disagree by hand-editing. CI regenerates and compares, so a
column added to lists.json without regenerating fails the build.

Usage:
    python3 scripts/generate_pnp_template.py           # write the template
    python3 scripts/generate_pnp_template.py --check   # fail if out of date
"""

import argparse
import html
import json
import os
import random
import sys
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LISTS_FILE = os.path.join(ROOT, "provisioning", "lists.json")
OUTPUT_FILE = os.path.join(ROOT, "provisioning", "pnp-provisioning-template.xml")

# Field GUIDs must be stable across regenerations, otherwise every run
# produces a spurious diff and -- worse -- reapplying the template to a site
# that already has the lists would try to create duplicate fields. A fixed
# seed makes generation deterministic.
GUID_SEED = 20260904

# The original template assigned IDs from the seeded sequence below. New
# fields must not consume that sequence or every later existing field would
# receive a different ID on regeneration. Add future fields here with a stable
# name-derived UUID before inserting them into lists.json.
ADDED_FIELD_GUIDS = {
    ("WalkFrontier", "EnumerationPhase"): "{f3547849-2446-506f-864d-fb7cf0b80533}",
    ("WalkFrontier", "NextPageUri"): "{c229a32c-8a2b-557e-881a-5561eda0107c}",
}

FIELD_TYPES = {
    "Text": "Text",
    "Note": "Note",
    "Number": "Number",
    "DateTime": "DateTime",
    "Choice": "Choice",
    "Boolean": "Boolean",
}

HEADER = """<?xml version="1.0" encoding="utf-8"?>
<pnp:Provisioning xmlns:pnp="http://schemas.dev.office.com/PnP/2022/09/ProvisioningSchema">
  <!--
    PnP provisioning template for the template regeneration solution.

    GENERATED FILE. Do not edit by hand.
    Source: provisioning/lists.json
    Regenerate: python3 scripts/generate_pnp_template.py
    See docs/Template-Regeneration-Solution-Design.md section 4.

    Apply with PnP PowerShell:
      Connect-PnPOnline -Url https://<tenant>.sharepoint.com/sites/<site> -Interactive
      Invoke-PnPSiteTemplate -Path provisioning/pnp-provisioning-template.xml

    NOT YET APPLIED TO ANY TENANT. Validate on a test site first.
  -->
  <pnp:Templates ID="TEMPLATE-REGENERATION">
    <pnp:ProvisioningTemplate ID="TEMPLATE-REGENERATION-LISTS" Version="1" BaseSiteTemplate="STS#3">
      <pnp:Lists>"""

FOOTER = """      </pnp:Lists>
    </pnp:ProvisioningTemplate>
  </pnp:Templates>
</pnp:Provisioning>"""


def render():
    with open(LISTS_FILE, encoding="utf-8") as handle:
        data = json.load(handle)

    rng = random.Random(GUID_SEED)

    def legacy_guid():
        return "{%s}" % uuid.UUID(int=rng.getrandbits(128), version=4)

    lines = [HEADER]

    for definition in data["lists"]:
        name = definition["name"]
        lines.append("        <!-- %s: %s -->" % (name, definition["description"]))
        lines.append(
            '        <pnp:ListInstance Title="%s" Description="%s" TemplateType="100" '
            'Url="Lists/%s" EnableVersioning="true" EnableAttachments="false" '
            'ContentTypesEnabled="false">'
            % (name, html.escape(definition["description"], quote=True), name)
        )
        lines.append("          <pnp:Fields>")

        for column in definition["columns"]:
            field_type = FIELD_TYPES[column["type"]]
            field_id = ADDED_FIELD_GUIDS.get((name, column["name"]))
            attributes = [
                'ID="%s"' % (field_id or legacy_guid()),
                'Name="%s"' % column["name"],
                'StaticName="%s"' % column["name"],
                'DisplayName="%s"' % column["name"],
                'Type="%s"' % field_type,
                'Required="%s"' % ("TRUE" if column.get("required") else "FALSE"),
            ]
            if column.get("indexed"):
                attributes.append('Indexed="TRUE"')
            if column.get("enforceUnique"):
                attributes.append('EnforceUniqueValues="TRUE"')
            if field_type == "Note":
                attributes.append('NumLines="4"')
                attributes.append('RichText="FALSE"')
            if column.get("description"):
                attributes.append(
                    'Description="%s"' % html.escape(column["description"], quote=True)
                )

            opening = "            <Field %s" % " ".join(attributes)
            inner = []
            if field_type == "Choice":
                inner.append("              <CHOICES>")
                for choice in column["choices"]:
                    inner.append("                <CHOICE>%s</CHOICE>" % html.escape(choice))
                inner.append("              </CHOICES>")
            if column.get("defaultValue") is not None:
                inner.append(
                    "              <Default>%s</Default>"
                    % html.escape(str(column["defaultValue"]))
                )

            if inner:
                lines.append(opening + ">")
                lines.extend(inner)
                lines.append("            </Field>")
            else:
                lines.append(opening + " />")

        lines.append("          </pnp:Fields>")
        lines.append("        </pnp:ListInstance>")

    lines.append(FOOTER)
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit non-zero if the committed template differs from freshly generated output",
    )
    args = parser.parse_args()

    generated = render()

    if args.check:
        if not os.path.exists(OUTPUT_FILE):
            print("ERROR: %s does not exist. Run scripts/generate_pnp_template.py." % OUTPUT_FILE)
            sys.exit(1)
        with open(OUTPUT_FILE, encoding="utf-8") as handle:
            current = handle.read()
        if current != generated:
            print(
                "ERROR: provisioning/pnp-provisioning-template.xml is out of date with "
                "provisioning/lists.json.\nRun: python3 scripts/generate_pnp_template.py"
            )
            sys.exit(1)
        print("Provisioning template is up to date with lists.json.")
        return

    with open(OUTPUT_FILE, "w", encoding="utf-8") as handle:
        handle.write(generated)
    print("Wrote %s" % OUTPUT_FILE)


if __name__ == "__main__":
    main()
