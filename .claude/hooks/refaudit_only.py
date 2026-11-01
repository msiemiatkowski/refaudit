#!/usr/bin/env python3
"""PreToolUse hook for the claim judges: Bash may run only the refaudit claims helpers, one command at a time.

Claude Code passes the tool call as JSON on stdin; exit code 2 blocks the call and shows stderr to the agent.
"""
import json
import re
import sys

ALLOWED = re.compile(r"^(?:refaudit|python3? -m refaudit) claims (?:candidates|status)\b")
SHELL = re.compile(r"[;&|`<>\n]|\$\(")

call = json.load(sys.stdin)
command = (call.get("tool_input") or {}).get("command", "").strip()
if ALLOWED.match(command) and not SHELL.search(command):
    sys.exit(0)
print("Only 'refaudit claims candidates <work> <claim-id>' and 'refaudit claims status <work>' are allowed "
      "here, as single commands. Use Read, Grep and Glob for everything else.", file=sys.stderr)
sys.exit(2)
