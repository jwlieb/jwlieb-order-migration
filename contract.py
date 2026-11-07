"""Typed MCP/task contracts. Domain behavior is defined in the task specification."""

from dataclasses import dataclass
from enum import Enum
from typing import Annotated
from slimconfig import Output


class Scenario(Enum):
    STANDARD = "standard"
    EMPTY = "empty"
    BOUNDARY = "boundary"
    INVALID = "invalid"


class Tool(Enum):
    PIN_REFERENCE = "pin_reference"
    INSPECT_TASK = "inspect_task"
    EDIT_FILES = "edit_files"
    ASSESS = "assess"


class Task(Enum):
    REPAIR = "migrate-orders"


@dataclass
class TaskInput(Output):
    scenario: Annotated[Scenario, "Pinned fixture variant: standard, empty, boundary, or invalid"]
    seed: Annotated[int, "Deterministic data variation, integer 0 through 9999"]


@dataclass
class EmptyInput(Output):
    pass


@dataclass
class ReferenceOutput(Output):
    task: TaskInput
    fixture: Annotated[str, "Canonical JSON containing pinned raw fixture data"]
    fixture_sha256: Annotated[str, "SHA-256 of the pinned fixture bytes"]
    expectations: Annotated[dict[str, str], "Named expected measurements, each encoded as canonical JSON"]


@dataclass
class InspectionOutput(Output):
    task: TaskInput
    specification: Annotated[str, "Exact public behavior, editing scope, and supported execution constraints"]
    files: Annotated[dict[str, str], "Editable candidate paths and their complete current contents"]
    fixture: Annotated[str, "Raw fixture JSON, also available to the controlled executor"]


@dataclass
class EditInput(Output):
    files: Annotated[dict[str, str], "Full replacement contents for one or more allowed candidate files"]


@dataclass
class EditOutput(Output):
    artifact_sha256: Annotated[str, "Digest of the complete allowed candidate file set"]
    changed: Annotated[list[str], "Candidate files replaced by this call"]


@dataclass
class AssessmentOutput(Output):
    assessment_id: Annotated[str, "Identifier of the controlled assessment receipt"]
    artifact_sha256: Annotated[str, "Digest of the candidate files that were actually assessed"]
    passed: Annotated[bool, "Whether independent semantic checks passed; not trusted without receipt validation"]
    failures: Annotated[list[str], "Names of checks that failed, or an empty list"]
    diagnostics: Annotated[str, "Bounded execution error or first failed-check explanation"]


TOOLS = {
    Tool.PIN_REFERENCE: (TaskInput, ReferenceOutput),
    Tool.INSPECT_TASK: (TaskInput, InspectionOutput),
    Tool.EDIT_FILES: (EditInput, EditOutput),
    Tool.ASSESS: (EmptyInput, AssessmentOutput),
}
TASKS = {Task.REPAIR: (TaskInput, AssessmentOutput)}
