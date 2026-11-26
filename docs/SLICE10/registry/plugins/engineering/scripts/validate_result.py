"""Validate the structure of a test-case result for the example plugin."""

import argparse
import json
from pathlib import Path

from jsonschema import Draft202012Validator


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("result", type=Path)
    result_path = parser.parse_args().result
    schema_path = Path(__file__).resolve().parents[1] / "schemas/test-cases.schema.json"

    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        result = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        parser.exit(1, f"Could not read the example: {error}\n")

    error = next(Draft202012Validator(schema).iter_errors(result), None)
    if error is not None:
        parser.exit(1, f"{error.json_path} {error.message}\n")
    print("Test-case result matches the schema.")


if __name__ == "__main__":
    main()
