"""Behavioral and adversarial verifier tests; evidence is emitted outside this repository."""

import json

import pytest
from slimconfig import build_output
from contract import AssessmentOutput, EditInput, EmptyInput, TaskInput
from plugin import domain, runtime
import verifier
from solutions import solution

TASK_ID = "migrate-orders"


def execute(tmp_path, scenario="standard", seed=7, repair=True):
    args = build_output({"scenario": scenario, "seed": seed}, TaskInput)
    pin = runtime.pin_reference(args, tmp_path)
    runtime.inspect_task(args, tmp_path)
    if repair:
        runtime.edit_files(build_output({"files": solution(scenario, seed)}, EditInput), tmp_path)
    output = runtime.assess(EmptyInput(), tmp_path)
    verdict = verifier.verify_task(TASK_ID, args, output, pin, str(tmp_path))
    return args, pin, output, verdict


@pytest.mark.parametrize("scenario", ["standard", "empty", "boundary", "invalid"])
def test_correct_control_and_boundary_variants(tmp_path, scenario):
    args, pin, output, verdict = execute(tmp_path, scenario)
    assert verdict["valid"], (output.failures, verdict)
    assert verdict["score"] == 1
    assert verifier.verify_output("assess", EmptyInput(), output, str(tmp_path))["valid"]
    assert verifier.verify_task(TASK_ID, args, output, pin, str(tmp_path)) == verdict


def test_unrepaired_starter_does_not_pass(tmp_path):
    args, pin, output, verdict = execute(tmp_path, repair=False)
    assert not verdict["valid"]
    assert not output.passed


def test_missing_candidate_is_rejected(tmp_path):
    args, pin, output, _ = execute(tmp_path)
    (tmp_path / "candidate" / next(iter(domain.STARTER))).unlink()
    assert not verifier.verify_task(TASK_ID, args, output, pin, str(tmp_path))["valid"]


def test_missing_receipt_is_rejected(tmp_path):
    args, pin, output, _ = execute(tmp_path)
    (tmp_path / "receipts" / (output.assessment_id + ".json")).unlink()
    assert not verifier.verify_task(TASK_ID, args, output, pin, str(tmp_path))["valid"]


@pytest.mark.parametrize("malformed", ["{", "[]", "null", '{"measurements":42}'])
def test_malformed_receipt_returns_invalid_not_exception(tmp_path, malformed):
    args, pin, output, _ = execute(tmp_path)
    (tmp_path / "receipts" / (output.assessment_id + ".json")).write_text(malformed)
    assert not verifier.verify_task(TASK_ID, args, output, pin, str(tmp_path))["valid"]


def test_receipt_measurements_are_checked_not_just_passed_flag(tmp_path):
    args, pin, output, _ = execute(tmp_path)
    p = tmp_path / "receipts" / (output.assessment_id + ".json")
    receipt = json.loads(p.read_text())
    receipt["measurements"][next(iter(receipt["measurements"]))] = '"fabricated"'
    p.write_text(json.dumps(receipt))
    assert not verifier.verify_task(TASK_ID, args, output, pin, str(tmp_path))["valid"]


def test_post_assessment_edit_is_rejected(tmp_path):
    args, pin, output, _ = execute(tmp_path)
    p = tmp_path / "candidate" / next(iter(domain.STARTER))
    p.write_text(p.read_text() + "\n")
    assert not verifier.verify_task(TASK_ID, args, output, pin, str(tmp_path))["valid"]


def test_missing_reference_and_cross_task_replay_fail(tmp_path):
    args, pin, output, _ = execute(tmp_path)
    assert not verifier.verify_task(TASK_ID, args, output, None, str(tmp_path))["valid"]
    different = build_output({"scenario": "standard", "seed": 8}, TaskInput)
    assert not verifier.verify_task(TASK_ID, different, output, pin, str(tmp_path))["valid"]


def test_malformed_contract_and_invalid_seed_fail(tmp_path):
    with pytest.raises(Exception):
        build_output({"passed": "yes"}, AssessmentOutput)
    args = build_output({"scenario": "standard", "seed": -1}, TaskInput)
    assert not verifier.verify_input("inspect_task", args)["valid"]


@pytest.mark.parametrize("path", ["../verifier/__init__.py", "receipts/forged.json", "/etc/passwd", "candidate.py"])
def test_evaluator_and_arbitrary_paths_cannot_be_edited(tmp_path, path):
    value = EditInput({path: "replacement"})
    assert not verifier.verify_input("edit_files", value)["valid"]
    with pytest.raises(ValueError):
        runtime.edit_files(value, tmp_path)


def test_symlink_candidate_is_rejected(tmp_path):
    args, pin, output, _ = execute(tmp_path)
    p = tmp_path / "candidate" / next(iter(domain.STARTER))
    p.unlink()
    outside = tmp_path / "outside.txt"
    outside.write_text("unchanged")
    p.symlink_to(outside)
    assert not verifier.verify_task(TASK_ID, args, output, pin, str(tmp_path))["valid"]


def test_wrong_summary_cannot_override_measurements(tmp_path):
    args, pin, output, _ = execute(tmp_path, repair=False)
    forged = AssessmentOutput(output.assessment_id, output.artifact_sha256, True, [], "")
    assert not verifier.verify_task(TASK_ID, args, forged, pin, str(tmp_path))["valid"]


def test_persistent_result_tampering_fails(tmp_path):
    if not domain.RESULT_FILES:
        pytest.skip("this task produces source artifacts and measurements, no persistent data result")
    args, pin, output, _ = execute(tmp_path)
    p = tmp_path / domain.RESULT_FILES[0]
    p.write_bytes(p.read_bytes() + b"tampering")
    assert not verifier.verify_task(TASK_ID, args, output, pin, str(tmp_path))["valid"]


def test_distinct_seed_uses_new_data(tmp_path):
    args, pin, output, verdict = execute(tmp_path, seed=831)
    assert verdict["valid"], output.failures


def test_raw_reference_tamper_fails(tmp_path):
    args, pin, output, _ = execute(tmp_path)
    pin.fixture += " "
    assert not verifier.verify_task(TASK_ID, args, output, pin, str(tmp_path))["valid"]
