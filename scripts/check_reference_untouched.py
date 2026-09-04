#!/usr/bin/env python3
"""Guard the read-only reference solution.

`reference-solution/` holds the exported Power Platform solution that is the
source of truth for how the working system actually behaves: the agent's schema
name, the connector operation that invokes it, and the pd-ad-conversion skill
contract the harness must satisfy.

It is evidence, not source. Reformatting it, regenerating it or "tidying" it
destroys the ability to say "the harness matches what is deployed" - and because
it is a binary zip, a diff cannot show what changed. So the rule is enforced
mechanically rather than left as a note in a README.

Usage:
    python3 scripts/check_reference_untouched.py [base_ref]

`base_ref` defaults to the pull-request base, the pre-push commit, or HEAD^.
"""

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROTECTED_PREFIX = "reference-solution/"


def git(*args):
    result = subprocess.run(
        ["git"] + list(args), cwd=ROOT,
        capture_output=True, text=True, check=False,
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def resolve_base(preferred):
    """Find a base ref that exists locally.

    The CI checkout may be shallow, so the obvious ref is not guaranteed to be
    present. Falling back keeps the check advisory rather than turning a missing
    ref into a spurious failure - the check's job is to catch modification, not
    to police clone shape.
    """
    for candidate in (preferred, "origin/main", "origin/master", "main", "master"):
        if not candidate:
            continue
        code, _, _ = git("rev-parse", "--verify", "--quiet", candidate)
        if code == 0:
            return candidate
    return None


def default_base():
    event = os.environ.get("GITHUB_EVENT_NAME", "")
    if event == "push":
        before = os.environ.get("GITHUB_EVENT_BEFORE", "")
        if before and set(before) != {"0"}:
            return before

    base_ref = os.environ.get("GITHUB_BASE_REF", "")
    if base_ref:
        return "origin/" + base_ref

    return "HEAD^"


def main():
    preferred = sys.argv[1] if len(sys.argv) > 1 else default_base()
    base = resolve_base(preferred)

    if base is None:
        print("SKIPPED: no base ref available to diff against "
              "(shallow clone without origin/main).")
        print("The working-tree check below still applies.")
    else:
        code, out, err = git("diff", "--name-only", base + "...HEAD")
        if code != 0:
            print("SKIPPED: could not diff against %s: %s" % (base, err))
        else:
            touched = [p for p in out.splitlines()
                       if p.startswith(PROTECTED_PREFIX)]
            if touched:
                print("ERROR: %s is read-only, but this branch modifies it:"
                      % PROTECTED_PREFIX)
                for path in touched:
                    print("  %s" % path)
                print("\nThe reference export is the evidence that the harness is "
                      "built from what is actually deployed. It must be replaced "
                      "only by re-exporting from the environment, never edited "
                      "in place.")
                sys.exit(1)
            print("OK: no changes to %s against %s." % (PROTECTED_PREFIX, base))

    # Uncommitted modifications are caught regardless of ref availability.
    code, out, _ = git("status", "--porcelain", "--", PROTECTED_PREFIX.rstrip("/"))
    if code == 0 and out:
        print("ERROR: uncommitted changes under %s:" % PROTECTED_PREFIX)
        for line in out.splitlines():
            print("  %s" % line)
        sys.exit(1)

    print("OK: reference solution is untouched.")


if __name__ == "__main__":
    main()
