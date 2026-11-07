"""Pure verifier: inspect actual artifacts and tool-owned observations; never run an LLM."""

import hashlib
import json
import re
from pathlib import Path
from contract import Tool
from .oracle import expected

ALLOWED_FILES = ["migration.py"]
RESULT_FILES = ["results/orders.sqlite"]
TASK_ID = "migrate-orders"


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def result(valid, message, details=None):
    return {"valid": bool(valid), "score": 1.0 if valid else 0.0, "message": message, "details": details or {}}


def files_of(workspace):
    root = Path(workspace).resolve()
    files = {}
    for name in ALLOWED_FILES:
        p = root / "candidate" / name
        if p.is_symlink() or not p.is_file() or not p.resolve().is_relative_to(root):
            raise ValueError("Missing or unsafe candidate " + name)
        files[name] = p.read_text()
    return files


def task_json(task):
    return {"scenario": task.scenario.value, "seed": task.seed}


def verify_input(tool, value):
    if tool in (Tool.PIN_REFERENCE.value, Tool.INSPECT_TASK.value):
        return result(0 <= value.seed <= 9999, "seed must be 0 through 9999")
    if tool == Tool.EDIT_FILES.value:
        ok = (
            bool(value.files)
            and set(value.files) <= set(ALLOWED_FILES)
            and all(len(s.encode()) <= 24000 for s in value.files.values())
        )
        return result(ok, "Only declared candidate text files may be edited")
    return result(tool == Tool.ASSESS.value, "Known controlled assessment tool")


def verify_output(tool, input_value, output_value, workspace):
    try:
        if tool == Tool.PIN_REFERENCE.value:
            raw = json.loads(output_value.fixture)
            wanted = {k: canonical(v) for k, v in expected(raw).items()}
            ok = (
                task_json(output_value.task) == task_json(input_value)
                and output_value.fixture_sha256 == hashlib.sha256(output_value.fixture.encode()).hexdigest()
                and wanted == output_value.expectations
            )
            return result(ok, "Pinned raw fixture and independently derived expectations")
        if tool == Tool.INSPECT_TASK.value:
            return result(
                output_value.files == files_of(workspace) and task_json(input_value) == task_json(output_value.task),
                "Inspection matches actual candidate files",
            )
        if tool == Tool.EDIT_FILES.value:
            files = files_of(workspace)
            ok = (
                all(files[k] == v for k, v in input_value.files.items())
                and output_value.changed == sorted(input_value.files)
                and output_value.artifact_sha256 == hashlib.sha256(canonical(files).encode()).hexdigest()
            )
            return result(ok, "Edits match the filesystem")
        if tool == Tool.ASSESS.value:
            receipt = receipt_of(output_value, workspace)
            return result(
                receipt["failures"] == output_value.failures and output_value.passed == (not output_value.failures),
                "Assessment is recorded; final correctness will be checked independently",
            )
        return result(False, "Unknown tool")
    except (OSError, ValueError, TypeError, KeyError, OverflowError):
        return result(False, "Missing, malformed, or inconsistent tool artifact")


def receipt_of(output, workspace):
    if not re.fullmatch("[0-9a-f]{24}", output.assessment_id):
        raise ValueError("invalid receipt id")
    p = Path(workspace) / "receipts" / (output.assessment_id + ".json")
    if p.is_symlink() or not p.is_file() or not p.resolve().is_relative_to(Path(workspace).resolve()):
        raise ValueError("missing receipt")
    receipt = json.loads(p.read_text())
    if not isinstance(receipt, dict) or set(receipt) != {
        "task",
        "artifact_sha256",
        "fixture_sha256",
        "measurements",
        "failures",
        "result_files",
    }:
        raise ValueError("malformed receipt")
    if not isinstance(receipt["measurements"], dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in receipt["measurements"].items()
    ):
        raise ValueError("malformed observations")
    if not isinstance(receipt["failures"], list) or not isinstance(receipt["result_files"], dict):
        raise ValueError("malformed receipt fields")
    digest = hashlib.sha256(canonical(files_of(workspace)).encode()).hexdigest()
    if output.artifact_sha256 != digest or receipt["artifact_sha256"] != digest:
        raise ValueError("candidate changed after assessment")
    return receipt


def verify_task(task, arguments, output, reference, workspace):
    try:
        if task != TASK_ID or reference is None or task_json(reference.task) != task_json(arguments):
            return result(False, "Missing reference or mismatched task input")
        if not verify_output(Tool.PIN_REFERENCE.value, arguments, reference, workspace)["valid"]:
            return result(False, "Invalid reference")
        receipt = receipt_of(output, workspace)
        if receipt["task"] != task_json(arguments) or receipt["fixture_sha256"] != reference.fixture_sha256:
            return result(False, "Receipt belongs to another task/fixture")
        required_results = [] if reference.expectations.get("published_results") == "false" else RESULT_FILES
        if set(receipt["result_files"]) != set(required_results):
            return result(False, "Required persistent result is missing")
        for name, wanted in receipt["result_files"].items():
            if name not in RESULT_FILES:
                return result(False, "Unexpected result path")
            p = Path(workspace) / name
            if p.is_symlink() or not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest() != wanted:
                return result(False, "Persistent result changed after assessment")
        actual = receipt["measurements"]
        wanted = reference.expectations
        failures = sorted(k for k in set(actual) | set(wanted) if actual.get(k) != wanted.get(k))
        if output.failures != failures or receipt["failures"] != failures or output.passed != (not failures):
            return result(False, "Submitted summary contradicts independent measurements")
        return result(
            not failures,
            "All semantic checks passed" if not failures else "Failed: " + ", ".join(failures),
            {"checks": {k: actual.get(k) == wanted.get(k) for k in sorted(set(actual) | set(wanted))}},
        )
    except (OSError, ValueError, TypeError, KeyError, OverflowError):
        return result(False, "Missing, malformed, or inconsistent task artifact")
