"""Fresh owner process. The goal ID is its only record identifier."""

import json
import os
import sys
from pathlib import Path
from urllib.request import Request, urlopen


def read(path):
    request = Request(os.environ["HARNESS_OWNER_URL"] + path)
    token = Path(os.environ["HARNESS_OWNER_TOKEN_FILE"]).read_text()
    request.add_unredirected_header("Authorization", "Bearer " + token)
    with urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def main(goal):
    activity = read(f"/goals/{goal}/history?view=activity")
    (item,) = activity["work_items"]
    (attempt,) = item["attempts"]
    result = attempt["result"]
    (report,) = [
        entry["observation"]
        for entry in activity["timeline"]
        if entry["kind"] == "observation"
    ]
    assert report["evidence_id"] == result["evidence_id"]
    assert report["source"] == "worker_result"
    assert report["worker_attempt_id"] == attempt["id"]
    assert report["worker_allocation_id"] == attempt["allocation_id"]
    assert report["requesting_operator_id"] == item["operator_id"]
    assert report["revision"] == item["revision"]
    assert report["submitted_by"] is None
    assert attempt["exit_code"] == 0 and attempt["state"] == "succeeded"
    assert any(
        c["tool"] == "get_work_brief" and c["outcome"] == "returned"
        for c in attempt["worker_calls"]
    )
    assert any(
        c["tool"] == "submit_work_result"
        and c["id"] == result["worker_call_id"]
        and c["evidence_id"] == result["evidence_id"]
        for c in attempt["worker_calls"]
    )
    file = result["text_file"]
    assert file["filename"] == "cities.txt"
    assert json.loads(report["evidence"]) == file
    lines = file["content"].splitlines()
    assert len(lines) == 5 and set(lines) == {
        "København",
        "Aarhus",
        "Odense",
        "Aalborg",
        "Esbjerg",
    }
    assert read(f"/goals/{goal}")["status"] == "active"
    print(
        json.dumps(
            {
                "goal": goal,
                "revision": item["revision"],
                "item": item["id"],
                "attempt": attempt["id"],
                "allocation": attempt["allocation_id"],
                "image": attempt["image"],
                "result": result,
                "status": "active",
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main(int(sys.argv[1]))
