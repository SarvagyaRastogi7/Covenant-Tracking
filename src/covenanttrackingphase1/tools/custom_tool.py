from __future__ import annotations

import json
import re
from threading import Lock
from pathlib import Path
from typing import Any, Dict, Type

import pandas as pd
from crewai.tools import BaseTool
from pydantic import BaseModel, Field


REQUIRED_FINANCIAL_FIELDS = [
    "borrower_id",
    "facility_id",
    "period",
    "EBITDA",
    "Principal_Paid",
    "Interest_Paid",
]

REQUIRED_CONFIG_FIELDS = [
    "covenant_type",
    "metric",
    "threshold",
    "frequency",
    "due_date_offset",
    "definition",
    "borrower_id",
    "facility_id",
]

_RUN_STATE_LOCK = Lock()
_RUN_STATE: Dict[str, Dict[str, Any]] = {}


def get_agentic_run_state(run_id: str) -> Dict[str, Any] | None:
    """Return a copy of the in-memory state for a run_id."""
    with _RUN_STATE_LOCK:
        state = _RUN_STATE.get(run_id)
        if state is None:
            return None
        return dict(state)


def clear_agentic_run_state(run_id: str) -> None:
    """Delete in-memory state for a run_id."""
    with _RUN_STATE_LOCK:
        _RUN_STATE.pop(run_id, None)


def _set_run_value(run_id: str, key: str, value: Any) -> None:
    with _RUN_STATE_LOCK:
        if run_id not in _RUN_STATE:
            _RUN_STATE[run_id] = {}
        _RUN_STATE[run_id][key] = value


def _get_run_value(run_id: str, key: str) -> Any:
    with _RUN_STATE_LOCK:
        return _RUN_STATE.get(run_id, {}).get(key)


class ExcelInputSchema(BaseModel):
    file_path: str = Field(..., description="Path to the Excel file")


class CalculationSchema(BaseModel):
    payload: Dict[str, Any] = Field(..., description="Validated covenant payload")


class ReportSchema(BaseModel):
    payload: Dict[str, Any] = Field(..., description="Calculation result payload")


class AgenticValidateSchema(BaseModel):
    run_id: str = Field(..., description="Unique run identifier shared across tasks")
    file_path: str = Field(..., description="Path to the Excel file")


class AgenticRunSchema(BaseModel):
    run_id: str = Field(..., description="Unique run identifier shared across tasks")


class ExcelValidationTool(BaseTool):
    name: str = "excel_validation_tool"
    description: str = (
        "Validate a predefined Excel covenant file and extract normalized financial data and configuration."
    )
    args_schema: Type[BaseModel] = ExcelInputSchema

    def _run(self, file_path: str) -> str:
        path = Path(file_path)
        if not path.exists():
            return json.dumps({"status": "error", "message": f"File not found: {file_path}"})

        sheets = pd.read_excel(path, sheet_name=None)
        lower_map = {name.lower(): df for name, df in sheets.items()}

        # Do not use `df_a or df_b` — bool(DataFrame) raises in pandas.
        financial_df = (
            lower_map.get("financial_statement")
            if "financial_statement" in lower_map
            else lower_map.get("financials")
        )
        config_df = (
            lower_map.get("covenant_config")
            if "covenant_config" in lower_map
            else lower_map.get("config")
        )

        if financial_df is None or config_df is None:
            return json.dumps({
                "status": "error",
                "message": "Workbook must contain sheets named Financial_Statement and Covenant_Config"
            })

        financial_record = self._frame_to_record(financial_df)
        config_record = self._frame_to_record(config_df)

        missing_financial = [f for f in REQUIRED_FINANCIAL_FIELDS if f not in financial_record]
        missing_config = [f for f in REQUIRED_CONFIG_FIELDS if f not in config_record]

        if missing_financial or missing_config:
            return json.dumps({
                "status": "error",
                "missing_financial_fields": missing_financial,
                "missing_config_fields": missing_config,
            })

        normalized = {
            "borrower_id": str(financial_record["borrower_id"]),
            "facility_id": str(financial_record["facility_id"]),
            "period": str(financial_record["period"]),
            "financials": {
                "EBITDA": self._to_number(financial_record["EBITDA"]),
                "Principal_Paid": self._to_number(financial_record["Principal_Paid"]),
                "Interest_Paid": self._to_number(financial_record["Interest_Paid"]),
            },
            "covenant_config": {
                "covenant_type": str(config_record["covenant_type"]),
                "metric": str(config_record["metric"]).upper(),
                "threshold": str(config_record["threshold"]),
                "frequency": str(config_record["frequency"]),
                "due_date_offset": str(config_record["due_date_offset"]),
                "definition": str(config_record["definition"]),
                "borrower_id": str(config_record["borrower_id"]),
                "facility_id": str(config_record["facility_id"]),
            }
        }

        if normalized["borrower_id"] != normalized["covenant_config"]["borrower_id"]:
            return json.dumps({"status": "error", "message": "borrower_id mismatch between sheets"})
        if normalized["facility_id"] != normalized["covenant_config"]["facility_id"]:
            return json.dumps({"status": "error", "message": "facility_id mismatch between sheets"})
        if normalized["covenant_config"]["metric"] != "DSCR":
            return json.dumps({"status": "error", "message": "Phase 1 supports only DSCR"})

        return json.dumps({"status": "success", "payload": normalized}, default=str)

    def _frame_to_record(self, df: pd.DataFrame) -> Dict[str, Any]:
        df = df.dropna(how="all")
        if list(df.columns[:2]) == [0, 1] or "field" in [str(c).lower() for c in df.columns]:
            if len(df.columns) >= 2:
                key_col, val_col = df.columns[0], df.columns[1]
                return {str(k).strip(): v for k, v in zip(df[key_col], df[val_col]) if pd.notna(k)}
        if len(df) == 1:
            return df.iloc[0].dropna().to_dict()
        return df.to_dict(orient="records")[0]

    def _to_number(self, value: Any) -> float:
        if isinstance(value, (int, float)):
            return float(value)
        cleaned = re.sub(r"[^0-9.\-]", "", str(value))
        return float(cleaned)


class DSCRCalculationTool(BaseTool):
    name: str = "dscr_calculation_tool"
    description: str = (
        "Compute DSCR deterministically from the validated covenant payload dict (same shape as "
        "the `payload` from excel_validation_tool). Returns JSON with decision COMPLIANT or "
        "BREACH, actual DSCR, threshold number, comparison string, and inputs."
    )
    args_schema: Type[BaseModel] = CalculationSchema

    def _run(self, payload: Dict[str, Any]) -> str:
        financials = payload["financials"]
        config = payload["covenant_config"]

        ebitda = float(financials["EBITDA"])
        principal = float(financials["Principal_Paid"])
        interest = float(financials["Interest_Paid"])
        debt_service = principal + interest

        if debt_service <= 0:
            return json.dumps({"status": "error", "message": "Debt service must be greater than zero"})

        dscr = ebitda / debt_service
        threshold_value = self._extract_threshold(config["threshold"])
        status = "COMPLIANT" if dscr >= threshold_value else "BREACH"

        result = {
            "status": "success",
            "borrower_id": payload["borrower_id"],
            "facility_id": payload["facility_id"],
            "period": payload["period"],
            "metric": "DSCR",
            "formula": "DSCR = EBITDA / (Principal_Paid + Interest_Paid)",
            "inputs": {
                "EBITDA": ebitda,
                "Principal_Paid": principal,
                "Interest_Paid": interest,
                "Debt_Service": debt_service,
            },
            "threshold": threshold_value,
            "actual": round(dscr, 4),
            "comparison": f"{round(dscr, 4)} {'>=' if dscr >= threshold_value else '<'} {threshold_value}",
            "decision": status,
        }
        return json.dumps(result)

    def _extract_threshold(self, raw: str) -> float:
        match = re.search(r"(\d+(?:\.\d+)?)", raw)
        if not match:
            raise ValueError("Invalid threshold format")
        return float(match.group(1))


class CovenantReportTool(BaseTool):
    name: str = "covenant_report_tool"
    description: str = (
        "Build the final report JSON from the dscr_calculation_tool output dict (status success). "
        "Output includes decision COMPLIANT or BREACH and recommended_action text."
    )
    args_schema: Type[BaseModel] = ReportSchema

    def _run(self, payload: Dict[str, Any]) -> str:
        if payload.get("status") != "success":
            return json.dumps(payload)

        report = {
            "report_type": "COVENANT_DECISION_REPORT",
            "borrower_id": payload["borrower_id"],
            "facility_id": payload["facility_id"],
            "period": payload["period"],
            "metric": payload["metric"],
            "threshold": payload["threshold"],
            "actual": payload["actual"],
            "decision": payload["decision"],
            "calculation_trace": {
                "formula": payload["formula"],
                "inputs": payload["inputs"],
                "comparison": payload["comparison"],
            },
            "recommended_action": (
                "Send breach alert to RM and hold for human review"
                if payload["decision"] == "BREACH"
                else "Mark covenant as compliant"
            ),
        }
        return json.dumps(report)


class AgenticValidateExcelTool(BaseTool):
    name: str = "agentic_validate_excel_tool"
    description: str = (
        "Step 1: validate workbook and store exact payload in shared state by run_id. "
        "Returns run_id and stored key only."
    )
    args_schema: Type[BaseModel] = AgenticValidateSchema

    def _run(self, run_id: str, file_path: str) -> str:
        raw = ExcelValidationTool()._run(file_path)
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = {"status": "error", "message": "excel_validation_tool returned non-JSON", "raw": raw}
        _set_run_value(run_id, "step1_validation", parsed)
        if parsed.get("status") == "success":
            _set_run_value(run_id, "step1_payload", parsed["payload"])
            return json.dumps(
                {
                    "status": "success",
                    "run_id": run_id,
                    "stored_key": "step1_payload",
                }
            )
        return json.dumps(
            {
                "status": "error",
                "run_id": run_id,
                "stored_key": "step1_validation",
                "message": parsed.get("message", "Validation failed"),
            }
        )


class AgenticCalculateDSCRTool(BaseTool):
    name: str = "agentic_calculate_dscr_tool"
    description: str = (
        "Step 2: read validated payload from shared state by run_id, compute DSCR, "
        "store exact calculation output, and return only run_id and key."
    )
    args_schema: Type[BaseModel] = AgenticRunSchema

    def _run(self, run_id: str) -> str:
        payload = _get_run_value(run_id, "step1_payload")
        if payload is None:
            return json.dumps(
                {
                    "status": "error",
                    "run_id": run_id,
                    "message": "Missing step1_payload for run_id",
                }
            )
        raw = DSCRCalculationTool()._run(payload)
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = {"status": "error", "message": "dscr_calculation_tool returned non-JSON", "raw": raw}
        _set_run_value(run_id, "step2_calculation", parsed)
        if parsed.get("status") == "success":
            return json.dumps(
                {
                    "status": "success",
                    "run_id": run_id,
                    "stored_key": "step2_calculation",
                    "decision": parsed.get("decision"),
                }
            )
        return json.dumps(
            {
                "status": "error",
                "run_id": run_id,
                "stored_key": "step2_calculation",
                "message": parsed.get("message", "Calculation failed"),
            }
        )


class AgenticGenerateReportTool(BaseTool):
    name: str = "agentic_generate_report_tool"
    description: str = (
        "Step 3: read DSCR calculation from shared state by run_id, generate report, "
        "store exact report output, and return only run_id and key."
    )
    args_schema: Type[BaseModel] = AgenticRunSchema

    def _run(self, run_id: str) -> str:
        calculation = _get_run_value(run_id, "step2_calculation")
        if calculation is None:
            return json.dumps(
                {
                    "status": "error",
                    "run_id": run_id,
                    "message": "Missing step2_calculation for run_id",
                }
            )
        raw = CovenantReportTool()._run(calculation)
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = {"status": "error", "message": "covenant_report_tool returned non-JSON", "raw": raw}
        _set_run_value(run_id, "step3_report", parsed)
        if parsed.get("report_type") == "COVENANT_DECISION_REPORT":
            return json.dumps(
                {
                    "status": "success",
                    "run_id": run_id,
                    "stored_key": "step3_report",
                    "decision": parsed.get("decision"),
                }
            )
        return json.dumps(
            {
                "status": "error",
                "run_id": run_id,
                "stored_key": "step3_report",
                "message": parsed.get("message", "Report generation failed"),
            }
        )