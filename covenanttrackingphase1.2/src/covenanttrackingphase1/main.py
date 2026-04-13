#!/usr/bin/env python
import json
import os
import sys
import tempfile
import warnings
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from covenanttrackingphase1.crew import Covenanttrackingphase1
from covenanttrackingphase1.tools.custom_tool import (
    AgenticCalculateDSCRTool,
    AgenticGenerateReportTool,
    AgenticValidateExcelTool,
    CovenantReportTool,
    DSCRCalculationTool,
    ExcelValidationTool,
    clear_agentic_run_state,
    get_agentic_run_state,
)

warnings.filterwarnings("ignore", category=SyntaxWarning, module="pysbd")

_PACKAGE_ROOT = Path(__file__).resolve().parent
_DEFAULT_WORKBOOK = _PACKAGE_ROOT / "sample_input.xlsx"
_SKILLS_FILE = _PACKAGE_ROOT / "config" / "skills.md"


def _load_metric_skills() -> str:
    try:
        return _SKILLS_FILE.read_text(encoding="utf-8")
    except OSError:
        return ""


def _default_inputs() -> dict[str, str]:
    return {
        "covenant_workbook_path": str(_DEFAULT_WORKBOOK),
        "reporting_period": "Q4 FY2025-26",
        "borrower_label": "ABC123 / FAC456 facility",
        "current_year": str(datetime.now().year),
        "metric_skills": _load_metric_skills(),
    }


def run_deterministic(workbook_path: str) -> dict[str, Any]:
    """Validate workbook/PDF -> compute DSCR -> build report using tools only (no LLM)."""
    raw_val = ExcelValidationTool()._run(workbook_path)
    validation: dict[str, Any] = json.loads(raw_val)
    if validation.get("status") != "success":
        return validation

    payload = validation["payload"]
    raw_calc = DSCRCalculationTool()._run(payload)
    calculation: dict[str, Any] = json.loads(raw_calc)
    if calculation.get("status") != "success":
        return calculation

    raw_report = CovenantReportTool()._run(calculation)
    return json.loads(raw_report)


def _ensure_run_id(inputs: dict[str, Any]) -> dict[str, Any]:
    """Ensure inputs include a run_id used by shared-state crew tools."""
    run_id = inputs.get("run_id")
    if not run_id:
        inputs["run_id"] = str(uuid4())
    return inputs


def _repair_agentic_state(run_id: str, workbook_path: str) -> dict[str, Any]:
    """Best-effort recovery when agents skip/mis-call tool steps."""
    state = get_agentic_run_state(run_id) or {}
    validation = state.get("step1_validation")

    # If step 1 never executed, run it deterministically.
    if validation is None:
        AgenticValidateExcelTool()._run(run_id=run_id, file_path=workbook_path)
        state = get_agentic_run_state(run_id) or state
        validation = state.get("step1_validation")

    if isinstance(validation, dict) and validation.get("status") != "success":
        return state

    if state.get("step2_calculation") is None:
        AgenticCalculateDSCRTool()._run(run_id=run_id)
        state = get_agentic_run_state(run_id) or state

    if state.get("step3_report") is None and state.get("step2_calculation") is not None:
        AgenticGenerateReportTool()._run(run_id=run_id)
        state = get_agentic_run_state(run_id) or state

    return state


def _deterministic_handoff_from_step1(
    state: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """
    Recompute downstream outputs strictly from step1 payload.

    This guarantees no LLM-authored text can mutate payload handoffs.
    """
    validation = state.get("step1_validation")
    if not isinstance(validation, dict) or validation.get("status") != "success":
        return None, None
    payload = validation.get("payload")
    if not isinstance(payload, dict):
        return None, None

    calc = json.loads(DSCRCalculationTool()._run(payload))
    if calc.get("status") != "success":
        return calc, None
    report = json.loads(CovenantReportTool()._run(calc))
    return calc, report


def run_agents_from_bytes(data: bytes, suffix: str = ".xlsx") -> dict[str, Any]:
    """Run CrewAI multi-agent flow with shared-state payload handoffs by run_id."""
    if not data:
        return {"status": "error", "message": "Empty file", "mode": "agentic"}
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(data)
        path = tmp.name
    run_id = str(uuid4())
    try:
        inputs = _ensure_run_id(_default_inputs())
        inputs["covenant_workbook_path"] = path
        inputs["run_id"] = run_id
        crew_output = Covenanttrackingphase1().crew().kickoff(inputs=inputs)

        state = _repair_agentic_state(run_id, path)
        validation = state.get("step1_validation")
        calculation, report = _deterministic_handoff_from_step1(state)
        tasks_output = [
            {"name": "validate_excel_input_task", "tool": "agentic_validate_excel_tool", "json_dict": validation},
            {"name": "calculate_dscr_task", "tool": "agentic_calculate_dscr_tool", "json_dict": calculation},
            {"name": "generate_decision_report_task", "tool": "agentic_generate_report_tool", "json_dict": report},
        ]
        if not isinstance(report, dict) or report.get("report_type") != "COVENANT_DECISION_REPORT":
            return {
                "status": "error",
                "mode": "agentic",
                "orchestration": "shared_state",
                "run_id": run_id,
                "message": "Crew completed but final report was not stored correctly",
                "crew_raw": getattr(crew_output, "raw", ""),
                "tasks_output": tasks_output,
                "final_task_json": report,
            }
        return {
            "status": "success",
            "mode": "agentic",
            "orchestration": "shared_state",
            "run_id": run_id,
            "crew_raw": getattr(crew_output, "raw", ""),
            "tasks_output": tasks_output,
            "final_task_json": report,
        }
    except Exception as e:
        return {
            "status": "error",
            "mode": "agentic",
            "orchestration": "shared_state",
            "run_id": run_id,
            "message": str(e),
        }
    finally:
        clear_agentic_run_state(run_id)
        try:
            os.unlink(path)
        except OSError:
            pass


def run_deterministic_from_bytes(data: bytes, suffix: str = ".xlsx") -> dict[str, Any]:
    """Run the same pipeline as ``run_deterministic`` using an uploaded file in memory."""
    if not data:
        return {"status": "error", "message": "Empty file"}
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(data)
        path = tmp.name
    try:
        return run_deterministic(path)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def run():
    """Run covenant pipeline: deterministic tools by default; agents only if COVENANT_USE_AGENTS=1."""
    inputs = _default_inputs()
    if len(sys.argv) > 1:
        candidate = Path(sys.argv[1]).expanduser()
        if candidate.is_file():
            inputs["covenant_workbook_path"] = str(candidate.resolve())
    try:
        if os.environ.get("COVENANT_USE_AGENTS", "").strip().lower() in ("1", "true", "yes"):
            _ensure_run_id(inputs)
            Covenanttrackingphase1().crew().kickoff(inputs=inputs)
            return
        result = run_deterministic(inputs["covenant_workbook_path"])
        print(json.dumps(result, indent=2, default=str))
    except Exception as e:
        raise Exception(f"An error occurred while running the crew: {e}") from e


def run_with_agents():
    """Run the multi-agent crew (LLM may hallucinate; use `run` for authoritative numbers)."""
    inputs = _default_inputs()
    if len(sys.argv) > 1:
        candidate = Path(sys.argv[1]).expanduser()
        if candidate.is_file():
            inputs["covenant_workbook_path"] = str(candidate.resolve())
    try:
        _ensure_run_id(inputs)
        Covenanttrackingphase1().crew().kickoff(inputs=inputs)
    except Exception as e:
        raise Exception(f"An error occurred while running the crew: {e}") from e


def train():
    """Train the crew for a given number of iterations."""
    inputs = _default_inputs()
    try:
        Covenanttrackingphase1().crew().train(
            n_iterations=int(sys.argv[1]),
            filename=sys.argv[2],
            inputs=inputs,
        )
    except Exception as e:
        raise Exception(f"An error occurred while training the crew: {e}") from e


def replay():
    """Replay the crew execution from a specific task."""
    try:
        Covenanttrackingphase1().crew().replay(task_id=sys.argv[1])
    except Exception as e:
        raise Exception(f"An error occurred while replaying the crew: {e}") from e


def test():
    """Test the crew execution and return the results."""
    inputs = _default_inputs()
    try:
        Covenanttrackingphase1().crew().test(
            n_iterations=int(sys.argv[1]),
            eval_llm=sys.argv[2],
            inputs=inputs,
        )
    except Exception as e:
        raise Exception(f"An error occurred while testing the crew: {e}") from e


def run_with_trigger():
    """Run the crew with trigger payload (merges into kickoff inputs)."""
    if len(sys.argv) < 2:
        raise Exception("No trigger payload provided. Please provide JSON payload as argument.")

    try:
        trigger_payload = json.loads(sys.argv[1])
    except json.JSONDecodeError as e:
        raise Exception("Invalid JSON payload provided as argument") from e

    inputs = _default_inputs()
    inputs["crewai_trigger_payload"] = trigger_payload
    if isinstance(trigger_payload, dict):
        for key in (
            "covenant_workbook_path",
            "reporting_period",
            "borrower_label",
            "current_year",
        ):
            if key in trigger_payload and trigger_payload[key]:
                inputs[key] = str(trigger_payload[key])

    try:
        if os.environ.get("COVENANT_USE_AGENTS", "").strip().lower() in ("1", "true", "yes"):
            _ensure_run_id(inputs)
            return Covenanttrackingphase1().crew().kickoff(inputs=inputs)
        result = run_deterministic(inputs["covenant_workbook_path"])
        print(json.dumps(result, indent=2, default=str))
        return result
    except Exception as e:
        raise Exception(f"An error occurred while running the crew with trigger: {e}") from e
