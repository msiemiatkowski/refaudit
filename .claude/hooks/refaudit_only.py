#!/usr/bin/env python3
"""PreToolUse hook for the claim judges: Bash may run only the refaudit claims helpers, one command at a time.

Claude Code passes the tool call as JSON on stdin; exit code 2 blocks the call and shows stderr to the agent.
In an agent's frontmatter it applies to that agent. In settings.json, pass `--only claim-judge,claim-second-opinion`
so it applies only to tool calls whose `agent_type` is one of those. Any error blocks the call (fail closed).
"""
import json
import re
import sys

ALLOWED = re.compile(r"^(?:refaudit|python3? -m refaudit) claims (?:candidates|status)\b")
SHELL = re.compile(r"[;&|`<>\n]|\$\(")
ONLY = sys.argv[sys.argv.index("--only") + 1].split(",") if "--only" in sys.argv[:-1] else None

try:
    call = json.load(sys.stdin)
    if ONLY is not None and call.get("agent_type") not in ONLY:
        sys.exit(0)  # the main conversation or another agent
    command = (call.get("tool_input") or {}).get("command", "").strip()
    if ALLOWED.match(command) and not SHELL.search(command):
        sys.exit(0)
    print("Only 'refaudit claims candidates <work> <claim-id>' and 'refaudit claims status <work>' are allowed "
          "here, as single commands. Use Read, Grep and Glob for everything else.", file=sys.stderr)
except Exception as exc:  # a hook that crashes would let the call through
    print(f"refaudit hook error ({exc}); the call is blocked to be safe.", file=sys.stderr)
sys.exit(2)
