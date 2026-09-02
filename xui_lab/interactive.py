"""Browser companion for a headed xui-lab runtime."""

from __future__ import annotations

import json
import threading
import webbrowser
from dataclasses import dataclass
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .api import Lab, Window
from .domain import Capability, Viewport
from .errors import InputError, XUILabError
from .io import write_json
from .scenarios import Scenario


def recorded_python(actions: list[dict[str, Any]]) -> list[str]:
    """Render runtime actions as editable public API calls."""
    lines: list[str] = []
    for action in actions:
        path = action.get("path")
        kind = action.get("action")
        if not isinstance(path, str) or not isinstance(kind, str):
            continue
        locator = f"window.get_by_path({path!r})"
        if kind in {"click", "double_click", "right_click"}:
            lines.append(f"{locator}.{kind}()")
        elif kind in {"fill", "text"} and isinstance(action.get("text"), str):
            method = "fill" if kind == "fill" else "type_text"
            lines.append(f"{locator}.{method}({action['text']!r})")
        elif kind == "key" and isinstance(action.get("key"), str):
            lines.append(f"{locator}.press({action['key']!r})")
    return lines


@dataclass(frozen=True)
class InteractiveConfig:
    subject: str
    viewport: Viewport
    fixture: Path | None
    artifact_id: str


class InteractiveSession:
    def __init__(
        self,
        lab: Lab,
        config: InteractiveConfig,
        subjects: dict[str, frozenset[Capability]],
        fixtures: dict[str, Path],
        scenarios: dict[str, Scenario],
    ):
        self.lab = lab
        self.config = config
        self.subjects = subjects
        self.fixtures = fixtures
        self.scenarios = scenarios
        self._generation = 0
        self.window = self._open(config.subject, config.fixture)

    def _open(self, subject: str, fixture: Path | None) -> Window:
        capabilities = self.subjects.get(subject)
        if capabilities is None:
            raise InputError(f"interactive subject is not declared: {subject}")
        artifact_id = self.config.artifact_id
        if self._generation:
            artifact_id = f"{artifact_id}-{self._generation}"
        self._generation += 1
        return self.lab.open(
            artifact_id=artifact_id,
            subject=subject,
            viewport=self.config.viewport,
            capabilities=capabilities,
            fixture=fixture,
            interactive=True,
        )

    def close(self) -> None:
        self.window.close()

    def state(self) -> dict[str, Any]:
        tree = self.window.query_tree()
        diagnostics = self.window.diagnostics()
        actions = (
            diagnostics.get("recording", []) if isinstance(diagnostics, dict) else []
        )
        return {
            "tree": tree,
            "diagnostics": diagnostics,
            "recording": recorded_python(actions if isinstance(actions, list) else []),
            "artifactDir": str(self.window.artifact_dir),
            "subjects": sorted(self.subjects),
            "fixtures": sorted(self.fixtures),
            "scenarios": sorted(self.scenarios),
        }

    def action(self, request: dict[str, Any]) -> dict[str, Any]:
        action = request.get("action")
        if action == "reload":
            before = self.window.runtime.pid
            result = self.window.reload()
            return {
                "result": result,
                "processIdBefore": before,
                "processIdAfter": self.window.runtime.pid,
            }
        if action == "highlight":
            path = request.get("path")
            locator = (
                self.window.get_by_path(path)
                if isinstance(path, str) and path
                else None
            )
            return self.window.highlight(locator)
        if action == "pick":
            x = request.get("x")
            y = request.get("y")
            if (
                not isinstance(x, int)
                or isinstance(x, bool)
                or not isinstance(y, int)
                or isinstance(y, bool)
            ):
                raise InputError("pick coordinates must be integers")
            control = self.window.pick(x, y)
            self.window.highlight(self.window.locator(control.selector))
            return control.info
        if action == "resize":
            width = request.get("width")
            height = request.get("height")
            scale = request.get("uiScale")
            if not isinstance(width, int) or not isinstance(height, int):
                raise InputError("resize width and height must be integers")
            if not isinstance(scale, (int, float)):
                raise InputError("resize uiScale must be a number")
            return self.window.resize(width, height, ui_scale=float(scale))
        if action == "capture":
            stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
            return self.window.capture(f"interactive-{stamp}")
        if action == "export":
            tree = self.window.query_tree()
            path = self.window.artifact_dir / "ui-tree-export.json"
            write_json(path, tree)
            return {"path": str(path)}
        if action == "click":
            return self._locator(request).click().data
        if action == "fill":
            text = request.get("text")
            if not isinstance(text, str):
                raise InputError("fill text must be a string")
            return self._locator(request).fill(text).data
        if action == "press":
            key = request.get("key")
            if not isinstance(key, str) or not key:
                raise InputError("key must be a non-empty string")
            return self._locator(request).press(key).data
        if action == "replay":
            scenario_id = request.get("scenario")
            scenario = (
                self.scenarios.get(scenario_id)
                if isinstance(scenario_id, str)
                else None
            )
            if scenario is None:
                raise InputError(f"unknown scenario: {scenario_id}")
            return self._replay(scenario)
        if action == "switch":
            subject = request.get("subject")
            fixture_id = request.get("fixture")
            fixture = (
                self.fixtures.get(fixture_id)
                if isinstance(fixture_id, str) and fixture_id
                else None
            )
            if not isinstance(subject, str):
                raise InputError("subject must be a string")
            self.window.close()
            self.window = self._open(subject, fixture)
            return {
                "subject": subject,
                "fixture": fixture_id or "",
                "processId": self.window.runtime.pid,
            }
        raise InputError(f"unknown interactive action: {action}")

    def _locator(self, request: dict[str, Any]):
        path = request.get("path")
        if not isinstance(path, str):
            raise InputError("action path must be a string")
        return self.window.get_by_path(path)

    def _replay(self, scenario: Scenario) -> dict[str, Any]:
        diagnostics = self.window.diagnostics()
        subject = (
            diagnostics.get("subject", {}).get("id")
            if isinstance(diagnostics, dict)
            else None
        )
        if subject != scenario.subject:
            raise InputError(
                f"scenario {scenario.id} targets {scenario.subject}, headed subject is {subject}"
            )
        before = self.window.runtime.pid
        self.window.reload()
        scenario.run(self.window)
        return {
            "scenario": str(scenario.id),
            "passed": True,
            "processIdBefore": before,
            "processIdAfter": self.window.runtime.pid,
        }


def discover_fixtures(root: Path) -> dict[str, Path]:
    return {path.stem: path for path in sorted((root / "fixtures").glob("*.json"))}


class InspectorServer(HTTPServer):
    session: InteractiveSession


class InspectorHandler(BaseHTTPRequestHandler):
    server: InspectorServer

    def do_GET(self) -> None:  # noqa: N802
        if urlsplit(self.path).path == "/":
            self._write(200, HTML.encode(), "text/html; charset=utf-8")
            return
        if urlsplit(self.path).path == "/api/state":
            self._json(200, self.server.session.state())
            return
        self._json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if urlsplit(self.path).path != "/api/action":
            self._json(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            value = json.loads(self.rfile.read(length))
            if not isinstance(value, dict):
                raise InputError("request must be an object")
            result = self.server.session.action(value)
            self._json(200, {"ok": True, "result": result})
        except (ValueError, XUILabError) as error:
            self._json(400, {"ok": False, "error": str(error)})

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def _json(self, status: int, value: Any) -> None:
        self._write(status, json.dumps(value).encode(), "application/json")

    def _write(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def serve_inspector(
    session: InteractiveSession,
    *,
    host: str = "127.0.0.1",
    port: int = 0,
    open_browser: bool = True,
) -> int:
    server = InspectorServer((host, port), InspectorHandler)
    server.session = session
    url = f"http://{server.server_address[0]}:{server.server_address[1]}/"
    print(f"xui-lab inspector: {url}", flush=True)
    if open_browser:
        threading.Timer(0.2, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever(poll_interval=0.1)
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
        session.close()
    return 0


HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>xui-lab inspector</title>
<style>
:root{font:13px ui-monospace,SFMono-Regular,Menlo,monospace;color:#e9edf1;background:#11151a}*{box-sizing:border-box}body{margin:0;display:grid;grid-template-columns:42% 58%;height:100vh}aside,main{padding:12px;overflow:auto;border-right:1px solid #39414a}.bar{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px}button,input,select,textarea{font:inherit;color:inherit;background:#202731;border:1px solid #4b5968;border-radius:4px;padding:5px}button{cursor:pointer}button:hover{background:#2e3946}.node{padding:3px 5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;cursor:pointer}.node:hover,.node.selected{background:#344152}.section{margin:12px 0 5px;color:#8fc8ff}pre,textarea{width:100%;white-space:pre-wrap;word-break:break-word}textarea{min-height:160px}.status{color:#9bd39b}.error{color:#ff9d9d}</style></head>
<body><aside><div class="bar"><select id="subject"></select><select id="fixture"><option value="">no fixture</option></select><button onclick="switchSubject()">Open</button></div><div id="tree"></div></aside>
<main><div class="bar"><button onclick="act('reload')">Reload XUI</button><button onclick="act('capture')">Screenshot</button><button onclick="act('export')">Export tree</button><button onclick="copyLocator()">Copy locator</button></div>
<div class="bar"><input id="width" type="number" value="800"><input id="height" type="number" value="600"><input id="scale" type="number" step="0.1" value="1"><button onclick="resize()">Resize</button></div>
<div class="bar"><input id="pickx" type="number" placeholder="screen x"><input id="picky" type="number" placeholder="screen y"><button onclick="pick()">Pick</button><button onclick="selectedAction('click')">Click</button></div>
<div class="bar"><input id="text" placeholder="text"><button onclick="selectedAction('fill',{text:val('text')})">Fill</button><input id="key" placeholder="key" value="Enter"><button onclick="selectedAction('press',{key:val('key')})">Press</button></div>
<div class="bar"><select id="scenario"></select><button onclick="replay()">Replay scenario</button></div>
<div id="status" class="status">Starting...</div><div class="section">Selected control</div><pre id="selected"></pre><div class="section">Focus and capture</div><pre id="focus"></pre><div class="section">Recorded Python</div><textarea id="recording" spellcheck="false"></textarea></main>
<script>
let state={},selectedPath='';const $=id=>document.getElementById(id),val=id=>$(id).value;
async function request(url,options){const r=await fetch(url,options);const j=await r.json();if(!r.ok||j.ok===false)throw Error(j.error||r.statusText);return j.result??j}
function flatten(node,depth=0,out=[]){if(!node||typeof node!=='object')return out;out.push([node,depth]);for(const c of node.children||[])flatten(c,depth+1,out);return out}
function find(path){return flatten(state.tree).map(x=>x[0]).find(n=>n.path===path)}
function render(){const overlay=state.diagnostics?.overlay||{};if(overlay.path)selectedPath=overlay.path;const rows=flatten(state.tree);$('tree').innerHTML=rows.map(([n,d])=>`<div class="node ${n.path===selectedPath?'selected':''}" style="padding-left:${5+d*12}px" data-path="${encodeURIComponent(n.path||'')}">${n.name||n.label||n.path||n.class}</div>`).join('');document.querySelectorAll('.node').forEach(e=>e.onclick=()=>select(decodeURIComponent(e.dataset.path)));$('selected').textContent=JSON.stringify(find(selectedPath)||{},null,2);$('focus').textContent=JSON.stringify({focus:state.diagnostics?.focus,mouseCapture:state.diagnostics?.mouseCapture,viewport:state.diagnostics?.viewport,overlay},null,2);$('recording').value=(state.recording||[]).join('\\n');for(const [id,values] of [['subject',state.subjects],['fixture',state.fixtures],['scenario',state.scenarios]]){const old=$(id).value;const prefix=id==='fixture'?'<option value="">no fixture</option>':'';$(id).innerHTML=prefix+(values||[]).map(v=>`<option>${v}</option>`).join('');if([...$(id).options].some(o=>o.value===old))$(id).value=old;}}
async function refresh(){try{state=await request('/api/state');render();$('status').textContent=`PID ${state.diagnostics.processId} | ${state.artifactDir}`;$('status').className='status'}catch(e){$('status').textContent=e;$('status').className='error'}}
async function act(action,extra={}){try{const r=await request('/api/action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action,...extra})});$('status').textContent=JSON.stringify(r);await refresh();return r}catch(e){$('status').textContent=e;$('status').className='error'}}
async function select(path){selectedPath=path;await act('highlight',{path})}function selectedAction(action,extra={}){if(!selectedPath)return;act(action,{path:selectedPath,...extra})}function resize(){act('resize',{width:+val('width'),height:+val('height'),uiScale:+val('scale')})}function pick(){act('pick',{x:+val('pickx'),y:+val('picky')})}function replay(){act('replay',{scenario:val('scenario')})}function switchSubject(){act('switch',{subject:val('subject'),fixture:val('fixture')})}async function copyLocator(){if(selectedPath)await navigator.clipboard.writeText(`window.get_by_path(${JSON.stringify(selectedPath)})`)}
setInterval(refresh,700);refresh();
</script></body></html>"""
