"""Local Scrapwise demo: real request-to-checked-file flow, with session state."""

import argparse
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
import subprocess
import sys
import threading
import time
from urllib.parse import unquote, urlsplit
import uuid


ROOT = Path(__file__).resolve().parents[2]
STATIC = Path(__file__).resolve().parent / "static"
BASE_JOB = ROOT / "reports/scrapwise-first-proof/input/base.json"
FLOW = ROOT / "app/scrapwise_local_flow/flow.py"
PYTHON = Path(sys.executable)
RUNS = ROOT / "reports/scrapwise-web-runs"


def utc():
    return datetime.now(timezone.utc).isoformat()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def state_summary(job_path):
    job = read_json(job_path)
    quantities = {}
    for part in job["parts"]:
        quantity = part["quantity"]
        quantities[quantity] = quantities.get(quantity, 0) + 1
    return {
        "shapeCount": len(job["parts"]),
        "copyCount": next(iter(quantities)) if len(quantities) == 1 else None,
        "quantityDistribution": [
            {"quantity": quantity, "shapeCount": count}
            for quantity, count in sorted(quantities.items())
        ],
        "stock": [
            {key: item[key] for key in ("id", "kind", "quantity", "width", "height")}
            for item in job["stock"]
        ],
        "spacing": job["spacing"],
        "margin": job["margin"],
        "units": job["units"],
    }


@dataclass
class Session:
    session_id: str
    directory: Path
    current_job: Path = BASE_JOB
    last_run_id: str | None = None
    checked_runs: dict = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)


class Demo:
    def __init__(self):
        self.sessions = {}
        self.sessions_lock = threading.Lock()

    def create_session(self):
        session_id = uuid.uuid4().hex
        directory = RUNS / session_id
        (directory / "requests").mkdir(parents=True, exist_ok=False)
        session = Session(session_id=session_id, directory=directory)
        with self.sessions_lock:
            self.sessions[session_id] = session
        return {"sessionId": session_id, "state": state_summary(session.current_job)}

    def session(self, session_id):
        with self.sessions_lock:
            session = self.sessions.get(session_id)
        if session is None:
            raise KeyError("Unknown session. Start a new session on this page.")
        return session

    def reset(self, session_id):
        session = self.session(session_id)
        with session.lock:
            session.current_job = BASE_JOB
            session.last_run_id = None
            return {
                "status": "reset",
                "state": state_summary(session.current_job),
                "assistantMessage": "The sample order is reset to one of each part and the original test inventory. Generate a new layout to preview or download it.",
            }

    def command(self, session_id, message):
        session = self.session(session_id)
        if not isinstance(message, str) or not message.strip():
            raise ValueError("Enter an English cutting-layout request.")
        message = message.strip()
        with session.lock:
            run_id = uuid.uuid4().hex
            message_path = session.directory / "requests" / (run_id + ".txt")
            message_path.write_text(message + "\n", encoding="utf-8")
            output = session.directory / run_id
            started = time.perf_counter()
            old_job = session.current_job
            web_receipt = {
                "sessionId": session_id,
                "runId": run_id,
                "startedAt": utc(),
                "currentJobSha256": sha(old_job),
                "originalJobSha256": sha(BASE_JOB),
                "messageSha256": sha(message_path),
                "flowSha256": sha(FLOW),
                "stateCommitted": False,
            }
            try:
                command = [
                    str(PYTHON), str(FLOW),
                    "--current-job", str(old_job),
                    "--original-job", str(BASE_JOB),
                    "--message-file", str(message_path),
                    "--output-dir", str(output),
                    "--case-id", "web-" + run_id,
                    "--attempts", "18",
                ]
                completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
                output.mkdir(parents=True, exist_ok=True)
                (output / "process-stdout.txt").write_text(completed.stdout, encoding="utf-8")
                (output / "process-stderr.txt").write_text(completed.stderr, encoding="utf-8")
                web_receipt["processExitCode"] = completed.returncode
                receipt = read_json(output / "flow-receipt.json")
                web_receipt["flowStatus"] = receipt["status"]
                if completed.returncode == 3 and receipt["status"] == "CLARIFICATION_REQUIRED":
                    question = (receipt.get("question") if receipt.get("decisionSource") == "literal-quantity-domain-check"
                                else "Please request a whole-number quantity for every part, or change the availability of an existing sheet.")
                    return {
                        "status": "clarify",
                        "state": state_summary(old_job),
                        "elapsedSeconds": time.perf_counter() - started,
                        "assistantMessage": "This demo changes whole-set quantities and existing-sheet availability; geometry, spacing, and margin stay fixed. " + question + " Your current order and last checked layout were kept.",
                    }
                if completed.returncode != 0 or receipt["status"] != "COMPLETE":
                    raise RuntimeError("The actual flow did not complete with a checked file.")

                job_path = output / "job.json"
                svg_path = output / "layout.svg"
                check = read_json(output / "independent-file-check.json")
                placements = read_json(output / "placements.json")
                required = sum(part["quantity"] for part in read_json(job_path)["parts"])
                if (check.get("valid") is not True or check.get("failures")
                        or check["inputSha256"] != sha(job_path)
                        or check["svgSha256"] != sha(svg_path)
                        or check["placementsSha256"] != sha(output / "placements.json")
                        or check["requiredPieceCopies"] != required
                        or check["actualSVGCopies"] != required
                        or check["actualPlacementCopies"] != len(placements["placements"])
                        or check["usedSheets"] != len(placements["sheets"])):
                    raise RuntimeError("The actual completed files do not match their file-check record.")

                svg = svg_path.read_text(encoding="utf-8")
                next_state = state_summary(job_path)
                elapsed = time.perf_counter() - started
                response = {
                    "status": "complete",
                    "state": next_state,
                    "svg": svg,
                    "downloadUrl": "/download/" + session_id + "/" + run_id + "/layout.svg",
                    "elapsedSeconds": elapsed,
                    "requiredPieces": required,
                    "purchasedArea": check["purchasedArea"],
                    "totalUsedSheetArea": check["totalUsedSheetArea"],
                    "usedSheets": check["usedSheets"],
                    "fileCheckSummary": {
                        "valid": check["valid"],
                        "requiredPieces": check["requiredPieceCopies"],
                        "actualSVGCopies": check["actualSVGCopies"],
                        "usedSheets": check["usedSheets"],
                        "minimumPairGap": check.get("minimumPairGap"),
                        "svgSha256": check["svgSha256"],
                    },
                    "assistantMessage": "Your updated layout is ready: " + str(required) + " pieces across " + str(check["usedSheets"]) + (" sheet." if check["usedSheets"] == 1 else " sheets.") + " The exported file passed the count, geometry, spacing, and margin checks. Measurements use the sample's SVG coordinate units.",
                }
                session.current_job = job_path
                session.last_run_id = run_id
                session.checked_runs[run_id] = {"path": svg_path, "sha256": check["svgSha256"]}
                web_receipt.update(stateCommitted=True, finalJobSha256=sha(job_path), svgSha256=check["svgSha256"])
                return response
            except Exception as error:
                web_receipt["error"] = str(error)
                return {
                    "status": "error",
                    "state": state_summary(old_job),
                    "elapsedSeconds": time.perf_counter() - started,
                    "assistantMessage": "The request did not produce a checked layout. Your current order and last checked layout were kept. Try a whole-set quantity or an existing-sheet availability request.",
                }
            finally:
                output.mkdir(parents=True, exist_ok=True)
                web_receipt.update(completedAt=utc(), elapsedSeconds=time.perf_counter() - started)
                save_json(output / "web-receipt.json", web_receipt)

    def download(self, session_id, run_id):
        session = self.session(session_id)
        with session.lock:
            artifact = session.checked_runs.get(run_id)
            if artifact is None:
                raise KeyError("No checked layout exists for this request.")
            if sha(artifact["path"]) != artifact["sha256"]:
                raise ValueError("The checked layout file has changed.")
            return artifact["path"].read_bytes()


class Handler(BaseHTTPRequestHandler):
    server_version = "ScrapwiseLocalDemo/1"

    def respond(self, status, body, content_type, attachment=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if attachment:
            self.send_header("Content-Disposition", 'attachment; filename="' + attachment + '"')
        self.end_headers()
        self.wfile.write(body)

    def json_response(self, status, value):
        self.respond(status, json.dumps(value, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def do_POST(self):
        try:
            path = urlsplit(self.path).path
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))).decode("utf-8"))
            if not isinstance(body, dict):
                raise ValueError("The request body must be a JSON object.")
            if path == "/api/session":
                result = self.server.demo.create_session()
            elif path == "/api/command":
                result = self.server.demo.command(body.get("sessionId"), body.get("message"))
            elif path == "/api/reset":
                result = self.server.demo.reset(body.get("sessionId"))
            else:
                self.json_response(404, {"status": "error", "assistantMessage": "Unknown endpoint."})
                return
            self.json_response(200, result)
        except KeyError as error:
            self.json_response(404, {"status": "error", "assistantMessage": str(error.args[0])})
        except (ValueError, TypeError, UnicodeDecodeError) as error:
            self.json_response(400, {"status": "error", "assistantMessage": str(error)})
        except Exception:
            self.json_response(500, {"status": "error", "assistantMessage": "The local demo could not process this request."})

    def do_GET(self):
        try:
            path = unquote(urlsplit(self.path).path)
            if path.startswith("/download/"):
                segments = path.split("/")
                if len(segments) != 5 or segments[4] != "layout.svg":
                    raise KeyError("Unknown download.")
                body = self.server.demo.download(segments[2], segments[3])
                self.respond(200, body, "image/svg+xml; charset=utf-8", "scrapwise-layout.svg")
                return
            relative = "index.html" if path == "/" else path.lstrip("/")
            file = (STATIC / relative).resolve()
            if not file.is_relative_to(STATIC.resolve()) or not file.is_file():
                raise KeyError("The page was not found.")
            content_type = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
            if content_type.startswith("text/") or file.suffix == ".js":
                content_type += "; charset=utf-8"
            self.respond(200, file.read_bytes(), content_type)
        except KeyError as error:
            self.json_response(404, {"status": "error", "assistantMessage": str(error.args[0])})
        except ValueError as error:
            self.json_response(409, {"status": "error", "assistantMessage": str(error)})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8767)
    args = parser.parse_args()
    for artifact in (BASE_JOB, FLOW, PYTHON):
        if not artifact.is_file():
            raise FileNotFoundError(artifact)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.demo = Demo()
    print("Scrapwise local demo: http://127.0.0.1:" + str(args.port), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
