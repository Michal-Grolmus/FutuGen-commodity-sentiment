"""Simple web terminal for controlling Claude Code remotely.

Usage:
    python scripts/web_terminal.py
    Then open the URL in browser (localhost or ngrok tunnel).
"""
from __future__ import annotations

import asyncio
import html
import os
import subprocess

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from starlette.requests import Request
from starlette.websockets import WebSocket, WebSocketDisconnect
import uvicorn

app = FastAPI(title="Claude Code Remote Terminal")

PROJECT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

HTML_PAGE = """
<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Claude Code Remote</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { background: #1a1a2e; color: #e0e0e0; font-family: monospace; height: 100vh; display: flex; flex-direction: column; }
#header { background: #16213e; padding: 10px 16px; font-size: 14px; color: #0f9; border-bottom: 1px solid #333; }
#output { flex: 1; overflow-y: auto; padding: 12px; font-size: 13px; line-height: 1.5; white-space: pre-wrap; word-break: break-word; }
#input-row { display: flex; padding: 8px; background: #16213e; border-top: 1px solid #333; }
#cmd { flex: 1; background: #0d1117; color: #e0e0e0; border: 1px solid #444; padding: 10px; font-size: 15px; font-family: monospace; border-radius: 6px; }
#send { background: #0f9; color: #000; border: none; padding: 10px 20px; font-size: 15px; font-weight: bold; cursor: pointer; border-radius: 6px; margin-left: 8px; }
.cmd-line { color: #0f9; }
.err-line { color: #f66; }
</style>
</head>
<body>
<div id="header">Claude Code Remote Terminal &mdash; PROJECT_DIR</div>
<div id="output" class="output"></div>
<div id="input-row">
  <input id="cmd" type="text" placeholder="command..." autocomplete="off" autofocus />
  <button id="send" onclick="run()">Run</button>
</div>
<script>
const output = document.getElementById('output');
const cmd = document.getElementById('cmd');

cmd.addEventListener('keydown', e => { if (e.key === 'Enter') run(); });

function addLine(text, cls) {
  const div = document.createElement('div');
  div.className = cls || '';
  div.textContent = text;
  output.appendChild(div);
  output.scrollTop = output.scrollHeight;
}

async function run() {
  const command = cmd.value.trim();
  if (!command) return;
  addLine('$ ' + command, 'cmd-line');
  cmd.value = '';

  try {
    const res = await fetch('/run', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({command})
    });
    const data = await res.json();
    if (data.stdout) addLine(data.stdout);
    if (data.stderr) addLine(data.stderr, 'err-line');
    addLine('[exit: ' + data.returncode + ']', data.returncode === 0 ? '' : 'err-line');
  } catch (e) {
    addLine('Error: ' + e.message, 'err-line');
  }
}

addLine('Connected to: PROJECT_DIR');
addLine('Type commands to run in project directory.');
addLine('Tip: "claude --continue" to resume last Claude Code session.\\n');
</script>
</body>
</html>
""".replace("PROJECT_DIR", PROJECT_DIR)


@app.get("/", response_class=HTMLResponse)
async def index():
    return HTMLResponse(content=HTML_PAGE)


@app.post("/run")
async def run_command(request: Request):
    data = await request.json()
    command = data.get("command", "")

    # Basic safety: block destructive commands
    blocked = ["rm -rf /", "format ", "del /s /q", "shutdown", "reboot"]
    for b in blocked:
        if b in command.lower():
            return {"stdout": "", "stderr": f"Blocked: '{b}' not allowed", "returncode": 1}

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=120,
            cwd=PROJECT_DIR,
            encoding="utf-8",
            errors="replace",
        )
        return {
            "stdout": result.stdout[-5000:] if result.stdout else "",
            "stderr": result.stderr[-2000:] if result.stderr else "",
            "returncode": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"stdout": "", "stderr": "Command timed out (120s)", "returncode": -1}
    except Exception as e:
        return {"stdout": "", "stderr": str(e), "returncode": -1}


if __name__ == "__main__":
    print(f"Starting web terminal for: {PROJECT_DIR}")
    print(f"Open http://localhost:7681 in browser")
    print(f"To expose remotely: /tmp/ngrok.exe http 7681")
    uvicorn.run(app, host="0.0.0.0", port=7681)
