import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from harness.client import call
from harness.engine import Engine
from harness.evidence import Run
from harness.server import create_app


class ScopeTests(unittest.IsolatedAsyncioTestCase):
    async def test_worker_credentials_and_workspaces_are_separate(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, WORKER_IMAGE="worker", WORKER_NETWORK="network"),
            patch("harness.docker_backend.docker.from_env"),
        ):
            root = Path(directory)
            operator_key = root / "token"
            operator_key.write_text("operator-secret")
            engine = Engine(root, operator_key.read_text())
            first = Run.create(root, "codex", "worker", "network")
            second = Run.create(root, "codex", "worker", "network")
            engine.active.update({"first": first, "second": second})
            with patch("harness.server.Engine", return_value=engine):
                app = create_app(root, operator_key)
            self.enterContext(patch.object(engine, "recover"))
            async with (
                app.router.lifespan_context(app),
                httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app), base_url="http://harness:8000"
                ) as http,
            ):
                for endpoint, token in [
                    ("/operator/mcp", "first"),
                    ("/worker/mcp", "operator-secret"),
                    ("/worker/mcp", "unknown"),
                ]:
                    response = await http.post(
                        endpoint, headers={"Authorization": f"Bearer {token}"}
                    )
                    self.assertEqual(response.status_code, 401)

                http.headers["Authorization"] = "Bearer first"
                async with (
                    streamable_http_client(
                        "http://harness:8000/worker/mcp", http_client=http
                    ) as io,
                    ClientSession(*io[:2]) as session,
                ):
                    await session.initialize()
                    tools = await session.list_tools()
                    self.assertEqual(
                        {tool.name for tool in tools.tools}, {"read_file", "write_file"}
                    )
                    result = await call(
                        session, "write_file", path="result.txt", content="first only"
                    )
                    self.assertEqual(result, {"bytes_written": 10})
                    self.assertEqual(first.file.read_text(), "first only")
                    self.assertFalse(second.file.exists())
                    self.assertTrue((await session.call_tool("get_run", {})).isError)
                engine.active.pop("first")
                self.assertEqual((await http.post("/worker/mcp")).status_code, 401)

                http.headers["Authorization"] = "Bearer operator-secret"
                with patch.object(engine, "watch"):
                    async with (
                        streamable_http_client(
                            "http://harness:8000/operator/mcp", http_client=http
                        ) as io,
                        ClientSession(*io[:2]) as session,
                    ):
                        await session.initialize()
                        started = await call(session, "start_run")
                        record = await call(session, "get_run", run_id=started["run_id"])
                        self.assertEqual(record["run_id"], started["run_id"])
                        self.assertEqual(record["status"], "queued")
