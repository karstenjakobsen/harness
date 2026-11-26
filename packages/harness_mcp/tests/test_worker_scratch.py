"""Exercise the worker image's actual stdio submission adapter without a login."""

import json
import os
import select
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread


def test_submission_reads_existing_utf8_bytes(tmp_path):
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    identity = tmp_path / "identity"
    identity.write_text("unit-test-identity")
    supplied = []

    class Endpoint(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            supplied.append(body["params"]["arguments"])
            self.send_response(200)
            self.end_headers()
            self.wfile.write(
                json.dumps(
                    {"jsonrpc": "2.0", "id": body["id"], "result": {"content": []}}
                ).encode()
            )

    bridge = Path(__file__).resolve().parents[3] / "dev/worker/worker-mcp.mjs"
    with ThreadingHTTPServer(("127.0.0.1", 0), Endpoint) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        env = os.environ | {
            "HARNESS_WORKER_IDENTITY_FILE": str(identity),
            "HARNESS_WORKER_MCP_URL": f"http://127.0.0.1:{server.server_port}/mcp",
        }
        try:
            with subprocess.Popen(
                ["node", str(bridge), str(scratch)],
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                text=True,
            ) as worker:

                def rpc(name, **args):
                    request = {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "tools/call",
                        "params": {"name": name, "arguments": args},
                    }
                    worker.stdin.write(json.dumps(request) + "\n")
                    worker.stdin.flush()
                    assert select.select([worker.stdout], [], [], 5)[0], (
                        "Worker adapter did not reply."
                    )
                    return json.loads(worker.stdout.readline())

                try:
                    filename = "cities.txt"
                    assert "error" in rpc("submit_work_result", filename=filename)
                    assert "error" in rpc(
                        "submit_work_result",
                        text_file={"filename": filename, "content": "inline"},
                    )
                    assert "error" in rpc(
                        "submit_work_result", filename=filename, content="inline"
                    )
                    assert supplied == []
                    assert "result" in rpc(
                        "write_text_file", filename=filename, content="København\n"
                    )
                    assert (scratch / filename).read_bytes() == "København\n".encode()
                    exact = "\ufeffKøbenhavn\r\nOdense\n"
                    (scratch / filename).write_bytes(exact.encode())
                    assert "result" in rpc("submit_work_result", filename=filename)
                    assert supplied == [
                        {"text_file": {"filename": filename, "content": exact}}
                    ]
                    (scratch / filename).write_bytes(b"\xff")
                    assert "error" in rpc("submit_work_result", filename=filename)
                    (scratch / "link").symlink_to(identity)
                    assert "error" in rpc("submit_work_result", filename="link")
                    assert len(supplied) == 1
                    os.mkfifo(scratch / "pipe")
                    assert "error" in rpc(
                        "write_text_file", filename="pipe", content="data"
                    )
                    assert "error" in rpc(
                        "write_text_file", filename="bad", content="x", extra=True
                    )
                finally:
                    worker.stdin.close()
                    try:
                        worker.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        worker.kill()
                        worker.wait()
                        raise
        finally:
            server.shutdown()
            thread.join()
