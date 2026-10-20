#!/usr/bin/env python3
"""Tiny stand-in for `dsh --profile headless --json` used by tests."""
import json
import sys
import time

args = sys.argv[1:]
task = args[-1] if args else ""
session = "session-fake"
if "--session-id" in args:
    session = args[args.index("--session-id") + 1]

print(json.dumps({"type": "session", "sessionId": session}), flush=True)
print(json.dumps({"type": "status", "turn": 1, "step": 1}), flush=True)
print(json.dumps({"type": "tool_call", "callId": "c1", "tool": "read", "input": {"path": "README.md"}}), flush=True)
print(json.dumps({"type": "tool_result", "callId": "c1", "status": "completed"}), flush=True)

if "sleep" in task:
    time.sleep(30)

if "fail" in task:
    print(json.dumps({"type": "error", "message": "fake failure"}), flush=True)
    sys.exit(1)

print(json.dumps({"type": "text", "text": "intermediate"}), flush=True)
print(json.dumps({"type": "final", "text": f"FAKE RESULT: {task}"}), flush=True)
