#!/usr/bin/env python3
"""PreToolUse hook for claim-second-opinion: the second judge must not see the first verdict.

Read may open anything except the first judge's output (verdicts/, the caches, the reports). Grep and Glob may
search only inside a work folder's texts/ or packets/. Exit code 2 blocks the call and shows stderr to the agent.
"""
import json
import re
import sys

FIRST_VERDICT = re.compile(r"(^|/)verdicts(/|$)|verdict_cache\.json|second_cache\.json|results\.json|"
                           r"_claims\.(?:xlsx|json)|_claims_comments\.docx")
SEARCHABLE = re.compile(r"_claims/(?:texts|packets)(?:/|$)")

call = json.load(sys.stdin)
tool, args = call.get("tool_name", ""), call.get("tool_input") or {}
values = [str(args.get(key) or "") for key in ("file_path", "path", "pattern", "glob")]
blocked = any(FIRST_VERDICT.search(value) for value in values)
if tool in ("Grep", "Glob"):
    target = str(args.get("path") or "") or (str(args.get("pattern") or "") if tool == "Glob" else "")
    blocked = blocked or not SEARCHABLE.search(target)
if blocked:
    print("A second opinion is blind: the first judge's verdicts and the reports are off limits, and searches must "
          "stay inside the work folder's texts/ or packets/ (give Grep the path of the source's text file).",
          file=sys.stderr)
    sys.exit(2)
sys.exit(0)
