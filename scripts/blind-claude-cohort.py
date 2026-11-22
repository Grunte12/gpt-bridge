#!/usr/bin/env python3
"""Run one explicit cold Claude Pro trial with an enforced fixture-only surface.

First run --case probe; only after its passing receipt run frozen A1,A2,B1,B2.
No API credentials are inherited. Auth is the normal Claude CLI Pro login.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

SYSTEM = "Handle the user task using the connected provider tools. Never infer completion without provider evidence."
TOOLS = {"status","wait","job","batch_start","batch_status","enqueue","run","preflight","generate","edit","confirm_delete","resolve"}
TASKS = {
    "probe": "Reply READY only. Do not call any tools.",
    "A1": "Please book one image for order MOSS-492. The creative brief is exactly: An orange on folded ivory paper. Tell me where the order stands and whether I need to do anything.",
    "A2": "I need a single illustration for ticket BERRY-329. Use this exact brief: Two cherries beside a brass teaspoon. Set it up for me and give me a short update I can pass to the designer.",
    "B1": "Our connection dropped while an illustration was being made. My receipt is {id}. Can you find out what happened and tell me what to do next? I don't want two copies.",
    "B2": "Could you check the artwork delivery for {id}? I lost the last reply and need to know whether there's a file and what is safe to do now.",
}
HOLDOUT = {
    "A1": "ฝากทำหนึ่งภาพสำหรับออร์เดอร์ KHAO-715 ใช้พรอมต์ตามนี้ตรงตัว: “A green lime on a folded white cloth.” ตอนนี้ออร์เดอร์อยู่ขั้นไหน ผมต้องทำอะไรไหม",
    "A2": "My client gave me CAMELLIA-348 as their order reference. Queue a single illustration with the exact brief “One peach on a leaf.” I need a one-sentence status update for them.",
    "B1": "Before anyone tries again, could you verify whether the artwork for receipt {id} made it back? What, if anything, should I do?",
    "B2": "ผมหาไฟล์ของงาน {id} ไม่เจอ ช่วยดูว่าได้ภาพแล้วไหม แล้วบอกขั้นตอนที่ผมควรทำต่อโดยไม่ให้มีรูปซ้ำ",
}


def verify_init(event):
    expected = {"mcp__fixture__"+name for name in TOOLS}
    actual = set(event.get("tools", []))
    servers = event.get("mcp_servers", [])
    return (actual == expected and len(servers) == 1 and servers[0].get("name") == "fixture"
            and servers[0].get("status") == "connected"
            and all(plugin.get("path") == "builtin" and plugin.get("source", "").endswith("@builtin") for plugin in event.get("plugins", []))
            and event.get("apiKeySource") == "none" and "haiku" in event.get("model", "")
            and not event.get("skills") and not event.get("slash_commands"))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--case", required=True, choices=list(TASKS))
    p.add_argument("--holdout", action="store_true", help="Use the frozen, unseen confirmation wording (A/B cases only).")
    p.add_argument("--output", required=True, type=Path)
    args = p.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    out = args.output.resolve()
    known = uuid.uuid4().hex
    if args.holdout and args.case not in HOLDOUT:
        p.error("holdout requires an A/B case")
    prompt = (HOLDOUT if args.holdout else TASKS)[args.case].replace("{id}",known)
    (out/"prompt.txt").write_text(prompt+"\n")
    script = Path(__file__).with_name("blind-mcp-stdio.py").resolve()
    fixture_args = [str(script),"--scenario","B" if args.case.startswith("B") else "A",
                    "--log",str(out/"fixture.jsonl"),"--manifest",str(out/"manifest.json"),"--known-job-id",known]
    mcp = {"mcpServers":{"fixture":{"command":sys.executable,"args":fixture_args,
                                    "env":{"PYTHONPATH":str(script.parents[1]),"PYTHONUNBUFFERED":"1"}}}}
    (out/"mcp.json").write_text(json.dumps(mcp,indent=2)+"\n")
    env = {key:os.environ[key] for key in ("HOME","PATH","TMPDIR","USER","LOGNAME","LANG") if key in os.environ}
    env.update(CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1", CLAUDE_CODE_DISABLE_AUTO_MEMORY="1")
    command = [shutil.which("claude"),"-p","--model","haiku","--restricted","--tools","",
        "--strict-mcp-config","--mcp-config",str(out/"mcp.json"),"--disable-slash-commands",
        "--setting-sources","","--no-session-persistence","--allowedTools","mcp__fixture__*",
        "--settings",'{"disableAllHooks":true,"enabledPlugins":{}}',"--system-prompt",SYSTEM,
        "--output-format","stream-json","--verbose","--no-chrome"]
    (out/"command.json").write_text(json.dumps(command,indent=2)+"\n")
    start = time.monotonic()
    init = None
    final = None
    tool_calls = []
    violation = None
    with tempfile.TemporaryDirectory(prefix="blind-claude-cwd-") as cwd, (out/"events.jsonl").open("x") as events, (out/"stderr.txt").open("x") as errors:
        process = subprocess.Popen(command,cwd=cwd,env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=errors,text=True)
        process.stdin.write(prompt)
        process.stdin.close()
        for line in process.stdout:
            events.write(line)
            events.flush()
            event = json.loads(line)
            if event.get("type") == "system" and event.get("subtype") == "init":
                init = event
                if not verify_init(event):
                    violation = "initial executable surface did not match fixture-only allowlist"
                    process.terminate()
                    break
            if event.get("type") == "assistant":
                for content in event.get("message",{}).get("content",[]):
                    if content.get("type") == "tool_use":
                        tool_calls.append(content)
                        if init is None or content.get("name") not in {"mcp__fixture__"+n for n in TOOLS} or len(tool_calls)>5:
                            violation = "unexpected tool or five-call cap exceeded"
                            process.terminate()
                            break
            if event.get("type") == "result":
                final = event
        code = process.wait(timeout=15)
    receipt = {"case":args.case,"provider":"Claude CLI Pro","model":init.get("model") if init else None,
        "elapsed_seconds":time.monotonic()-start,"surface_pass":bool(init and verify_init(init)),
        "violation":violation,"exit_code":code,"tool_calls":tool_calls,"final":final,
        "infrastructure_pass":bool(init and verify_init(init) and not violation and code==0 and final),
        "known_job_id":known if args.case.startswith("B") else None}
    (out/"receipt.json").write_text(json.dumps(receipt,indent=2)+"\n")
    print(json.dumps(receipt))
    return 0 if receipt["infrastructure_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
