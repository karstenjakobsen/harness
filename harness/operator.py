import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import get_args

from harness.client import call, connect
from harness.evidence import ACTIVE, TASK, Worker


async def main() -> int:
    parser = argparse.ArgumentParser(description="Run and inspect the hello-file harness")
    commands = parser.add_subparsers(dest="action", required=True)
    run = commands.add_parser("run")
    run.add_argument("--worker", choices=get_args(Worker), default="codex")
    commands.add_parser("get").add_argument("run_id")
    args = parser.parse_args()
    key = Path("/operator/token").read_text().strip()
    async with connect(os.getenv("OPERATOR_MCP_URL", "http://harness:8000/operator/mcp"), key) as s:
        if args.action == "get":
            print(json.dumps(await call(s, "get_run", run_id=args.run_id), indent=2))
            return 0
        run_id = (await call(s, "start_run", task=TASK, worker=args.worker))["run_id"]
        print(f"run_id={run_id}", flush=True)
        while True:
            data = await call(s, "get_run", run_id=run_id, include_trace=False)
            if data["status"] not in ACTIVE:
                print(data["summary"], flush=True)
                if error := data.get("error"):
                    print(error, file=sys.stderr)
                return 0 if data["status"] == "passed" else 1
            await asyncio.sleep(1)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
