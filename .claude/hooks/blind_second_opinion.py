#!/usr/bin/env python3
"""PreToolUse hook for claim-second-opinion: the second judge must not see the first verdict.

Read may open anything except the first judge's output (verdicts/, the sealed folder, the caches, the reports).
Grep and Glob may search only inside a work folder's texts/ or packets/. Exit code 2 blocks the call and shows
stderr to the agent. In settings.json, pass `--only claim-second-opinion` so it applies only to that agent's
calls (`agent_type`). Any error blocks the call (fail closed).
"""
import json
import re
import sys

FIRST_VERDICT = re.compile(r"(^|/)verdicts(/|$)|\.sealed(/|$)|verdict_cache\.json|second_cache\.json|results\.json|"
                           r"_claims\.(?:xlsx|json)|_claims_comments\.docx")
SEARCHABLE = re.compile(r"_claims/(?:texts|packets)(?:/|$)")
ONLY = sys.argv[sys.argv.index("--only") + 1].split(",") if "--only" in sys.argv[:-1] else None

try:
    call = json.load(sys.stdin)
    if ONLY is not None and call.get("agent_type") not in ONLY:
        sys.exit(0)  # the main conversation or another agent
    tool, args = call.get("tool_name", ""), call.get("tool_input") or {}
    values = [str(args.get(key) or "") for key in ("file_path", "path", "pattern", "glob")]
    blocked = any(FIRST_VERDICT.search(value) for value in values)
    if tool in ("Grep", "Glob"):
        target = str(args.get("path") or "") or (str(args.get("pattern") or "") if tool == "Glob" else "")
        blocked = blocked or not SEARCHABLE.search(target)
    if not blocked:
        sys.exit(0)
    print("A second opinion is blind: the first judge's verdicts and the reports are off limits, and searches must "
          "stay inside the work folder's texts/ or packets/ (give Grep the path of the source's text file).",
          file=sys.stderr)
except Exception as exc:  # a hook that crashes would let the call through
    print(f"refaudit hook error ({exc}); the call is blocked to be safe.", file=sys.stderr)
sys.exit(2)
