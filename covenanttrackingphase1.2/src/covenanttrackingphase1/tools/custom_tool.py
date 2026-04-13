from __future__ import annotations

import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from threading import Lock
from pathlib import Path
from typing import Any, Dict, Type

import pandas as pd
from crewai import Agent
from pypdf import PdfReader
from crewai.tools import BaseTool
from pydantic import BaseModel, Field, model_validator


REQUIRED_FINANCIAL_FIELDS = [
    "borrower_id",
    "facility_id",
    "period",
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

FIELD_ALIASES = {
    "borrower_id": ["borrower_id", "borrower id"],
    "facility_id": ["facility_id", "facility id", "loan_account_no", "loan account no"],
    "period": ["period", "reporting_period", "reporting period", "certification_date", "certification date"],
    "EBITDA": ["ebitda"],
    "Principal_Paid": ["principal_paid", "principal paid", "principal_paid_ytd", "principal paid ytd"],
    "Interest_Paid": ["interest_paid", "interest paid", "interest_paid_ytd", "interest paid ytd"],
    "Total_Debt": ["total_debt", "total debt", "debt", "total_liabilities", "total liabilities"],
    "Net_Worth": ["net_worth", "net worth", "tangible_net_worth", "tangible net worth"],
    "EMI_Amount": ["emi_amount", "emi amount", "installment", "monthly_installment", "monthly installment"],
    "covenant_type": ["covenant_type", "covenant type"],
    "metric": ["metric", "covenant_metric", "covenant metric"],
    "threshold": ["threshold", "dscr_threshold", "dscr threshold", "covenant_threshold", "covenant threshold"],
    "frequency": ["frequency"],
    "due_date_offset": ["due_date_offset", "due date offset"],
    "definition": ["definition"],
}

SUPPORTED_METRICS = {
    "DSCR",
    "ICR",
    "DEBT_TO_EBITDA",
    "DEBT_TO_NET_WORTH",
    "EBITDA_TO_EMI",
}

METRIC_ALIASES = {
    "DSCR": ["DSCR", "DEBT_SERVICE_COVERAGE", "DEBT_SERVICE_COVERAGE_RATIO"],
    "ICR": ["ICR", "INTEREST_COVERAGE", "INTEREST_COVERAGE_RATIO"],
    "DEBT_TO_EBITDA": ["DEBT_TO_EBITDA", "TOTAL_DEBT_TO_EBITDA", "LEVERAGE"],
    "DEBT_TO_NET_WORTH": ["DEBT_TO_NET_WORTH", "DEBT_TO_NW", "TOTAL_DEBT_TO_NET_WORTH"],
    "EBITDA_TO_EMI": ["EBITDA_TO_EMI", "EBITDA_EMI_COVERAGE", "EMI_COVERAGE"],
}

METRIC_REQUIRED_INPUTS = {
    "DSCR": ["EBITDA", "Principal_Paid", "Interest_Paid"],
    "ICR": ["EBITDA", "Interest_Paid"],
    "DEBT_TO_EBITDA": ["Total_Debt", "EBITDA"],
    "DEBT_TO_NET_WORTH": ["Total_Debt", "Net_Worth"],
    "EBITDA_TO_EMI": ["EBITDA", "EMI_Amount"],
}

METRIC_DEFAULT_THRESHOLD = {
    "DSCR": ">= 1.25",
    "ICR": ">= 2.00",
    "DEBT_TO_EBITDA": "<= 3.50",
    "DEBT_TO_NET_WORTH": "<= 2.50",
    "EBITDA_TO_EMI": ">= 1.20",
}

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
    file_path: str = Field(..., description="Path to an Excel (.xlsx) or PDF file")


class CalculationSchema(BaseModel):
    payload: Dict[str, Any] = Field(..., description="Validated covenant payload")


class ReportSchema(BaseModel):
    payload: Dict[str, Any] = Field(..., description="Calculation result payload")


class AgenticValidateSchema(BaseModel):
    run_id: str = Field(..., description="Unique run identifier shared across tasks")
    file_path: str = Field(..., description="Path to the Excel file")


class AgenticRunSchema(BaseModel):
    run_id: str | None = Field(default=None, description="Unique run identifier shared across tasks")
    payload: Any | None = Field(
        default=None,
        description="Optional compatibility payload used by some LLM tool-call formats.",
    )
    object: Any | None = Field(
        default=None,
        description="Optional compatibility field for generic object args.",
    )
    status_update_frequency_seconds: int | None = Field(
        default=None,
        description="Optional progress update hint; ignored by this tool.",
    )

    @model_validator(mode="before")
    @classmethod
    def _coerce_run_id(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        if data.get("run_id"):
            return data

        payload = data.get("payload")
        # Handle payload as dict: {"run_id": "..."}
        if isinstance(payload, dict) and payload.get("run_id"):
            data["run_id"] = str(payload["run_id"])
            return data
        # Handle payload as stringified dict/json containing run_id.
        if isinstance(payload, str):
            match = re.search(r"run_id['\"]?\s*[:=]\s*['\"]([^'\"]+)['\"]", payload)
            if match:
                data["run_id"] = match.group(1)
                return data
        return data

    @model_validator(mode="after")
    def _require_run_id(self) -> "AgenticRunSchema":
        if not self.run_id:
            raise ValueError("run_id is required")
        return self


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

        if path.suffix.lower() == ".pdf":
            return self._run_pdf(path)

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
            # Fallback for borrower POC templates (single sheet with Field/Value pairs).
            combined_record: Dict[str, Any] = {}
            for sheet_df in sheets.values():
                row = self._frame_to_record(sheet_df)
                if isinstance(row, dict):
                    combined_record.update(row)
            financial_record = self._canonicalize_record(combined_record)
            config_record = self._canonicalize_record(combined_record)
        else:
            financial_record = self._canonicalize_record(self._frame_to_record(financial_df))
            config_record = self._canonicalize_record(self._frame_to_record(config_df))

        metric_name = self._normalize_metric(str(config_record.get("metric", "DSCR")))
        metric_required = METRIC_REQUIRED_INPUTS.get(metric_name, [])
        missing_financial = [f for f in REQUIRED_FINANCIAL_FIELDS if f not in financial_record] + [
            f for f in metric_required if f not in financial_record
        ]
        missing_config = [f for f in REQUIRED_CONFIG_FIELDS if f not in config_record]

        if missing_financial or missing_config:
            return json.dumps({
                "status": "error",
                "missing_financial_fields": missing_financial,
                "missing_config_fields": missing_config,
                "message": "Required covenant fields missing. Provide standard sheets or Field/Value labels.",
            })

        normalized = {
            "borrower_id": str(financial_record["borrower_id"]),
            "facility_id": str(financial_record["facility_id"]),
            "period": str(financial_record["period"]),
            "financials": {
                "EBITDA": self._to_number(financial_record["EBITDA"]) if financial_record.get("EBITDA") is not None else None,
                "Principal_Paid": self._to_number(financial_record["Principal_Paid"])
                if financial_record.get("Principal_Paid") is not None
                else None,
                "Interest_Paid": self._to_number(financial_record["Interest_Paid"])
                if financial_record.get("Interest_Paid") is not None
                else None,
                "Total_Debt": self._to_number(financial_record["Total_Debt"]) if financial_record.get("Total_Debt") is not None else None,
                "Net_Worth": self._to_number(financial_record["Net_Worth"]) if financial_record.get("Net_Worth") is not None else None,
                "EMI_Amount": self._to_number(financial_record["EMI_Amount"]) if financial_record.get("EMI_Amount") is not None else None,
            },
            "covenant_config": {
                "covenant_type": str(config_record["covenant_type"]),
                "metric": metric_name,
                "threshold": METRIC_DEFAULT_THRESHOLD.get(metric_name, ">= 1.25"),
                "frequency": str(config_record["frequency"]) if str(config_record["frequency"]).strip() else "Quarterly",
                "due_date_offset": str(config_record["due_date_offset"])
                if str(config_record["due_date_offset"]).strip()
                else "0",
                "definition": str(config_record["definition"]) if str(config_record["definition"]).strip() else self._metric_definition(metric_name),
                "borrower_id": str(config_record["borrower_id"]),
                "facility_id": str(config_record["facility_id"]),
            }
        }

        for field in metric_required:
            if field not in financial_record:
                return json.dumps(
                    {
                        "status": "error",
                        "message": f"Metric {metric_name} requires missing field: {field}",
                    }
                )

        if metric_name not in SUPPORTED_METRICS:
            return json.dumps({"status": "error", "message": f"Unsupported metric: {metric_name}"})

        if normalized["borrower_id"] != normalized["covenant_config"]["borrower_id"]:
            return json.dumps({"status": "error", "message": "borrower_id mismatch between sheets"})
        if normalized["facility_id"] != normalized["covenant_config"]["facility_id"]:
            return json.dumps({"status": "error", "message": "facility_id mismatch between sheets"})

        return json.dumps({"status": "success", "payload": normalized}, default=str)

    def _run_pdf(self, path: Path) -> str:
        raw_text = self._extract_pdf_text(path)
        if not raw_text.strip():
            return json.dumps(
                {
                    "status": "error",
                    "message": "Could not extract text from PDF. Ensure the file is readable or OCR-compatible.",
                }
            )

        financial_record = {
            "borrower_id": self._match_first(raw_text, [r"borrower[\s_-]*id\s*[:\-]\s*([^\n\r]+)"]),
            "facility_id": self._match_first(raw_text, [r"facility[\s_-]*id\s*[:\-]\s*([^\n\r]+)"]),
            "period": self._match_first(
                raw_text,
                [
                    r"reporting\s*period\s*[:\-]\s*([^\n\r]+)",
                    r"period\s*[:\-]\s*([^\n\r]+)",
                ],
            ),
            "EBITDA": self._match_first(
                raw_text,
                [r"EBITDA\s*[:\-]\s*([0-9,\.\-\(\)\s$]+)"],
            ),
            "Principal_Paid": self._match_first(
                raw_text,
                [
                    r"principal[\s_-]*paid\s*[:\-]\s*([0-9,\.\-\(\)\s$]+)",
                    r"principal\s*[:\-]\s*([0-9,\.\-\(\)\s$]+)",
                ],
            ),
            "Interest_Paid": self._match_first(
                raw_text,
                [
                    r"interest[\s_-]*paid\s*[:\-]\s*([0-9,\.\-\(\)\s$]+)",
                    r"interest\s*[:\-]\s*([0-9,\.\-\(\)\s$]+)",
                ],
            ),
            "Total_Debt": self._match_first(raw_text, [r"total[\s_-]*debt\s*[:\-]\s*([0-9,\.\-\(\)\s$]+)"]),
            "Net_Worth": self._match_first(raw_text, [r"net[\s_-]*worth\s*[:\-]\s*([0-9,\.\-\(\)\s$]+)"]),
            "EMI_Amount": self._match_first(raw_text, [r"emi[\s_-]*amount\s*[:\-]\s*([0-9,\.\-\(\)\s$]+)"]),
        }

        metric_name = self._normalize_metric(self._match_first(raw_text, [r"metric\s*[:\-]\s*([^\n\r]+)"]) or "DSCR")
        config_record = {
            "covenant_type": self._match_first(raw_text, [r"covenant[\s_-]*type\s*[:\-]\s*([^\n\r]+)"]) or "Financial",
            "metric": metric_name,
            "threshold": METRIC_DEFAULT_THRESHOLD.get(metric_name, ">= 1.25"),
            "frequency": self._match_first(raw_text, [r"frequency\s*[:\-]\s*([^\n\r]+)"]) or "Quarterly",
            "due_date_offset": self._match_first(raw_text, [r"due[\s_-]*date[\s_-]*offset\s*[:\-]\s*([^\n\r]+)"]) or "0",
            "definition": self._match_first(raw_text, [r"definition\s*[:\-]\s*([^\n\r]+)"])
            or self._metric_definition(metric_name),
            "borrower_id": financial_record["borrower_id"],
            "facility_id": financial_record["facility_id"],
        }

        metric_required = METRIC_REQUIRED_INPUTS.get(metric_name, [])
        missing_financial = [f for f in REQUIRED_FINANCIAL_FIELDS if not financial_record.get(f)] + [
            f for f in metric_required if not financial_record.get(f)
        ]
        missing_config = [f for f in REQUIRED_CONFIG_FIELDS if not config_record.get(f)]

        if missing_financial or missing_config:
            return json.dumps(
                {
                    "status": "error",
                    "missing_financial_fields": missing_financial,
                    "missing_config_fields": missing_config,
                    "message": "PDF parsed, but required fields are missing. Use key:value labels in the source PDF.",
                }
            )

        try:
            normalized = {
                "borrower_id": str(financial_record["borrower_id"]),
                "facility_id": str(financial_record["facility_id"]),
                "period": str(financial_record["period"]),
                "financials": {
                    "EBITDA": self._to_number(financial_record["EBITDA"]),
                    "Principal_Paid": self._to_number(financial_record["Principal_Paid"]),
                    "Interest_Paid": self._to_number(financial_record["Interest_Paid"]),
                    "Total_Debt": self._to_number(financial_record["Total_Debt"]) if financial_record.get("Total_Debt") else None,
                    "Net_Worth": self._to_number(financial_record["Net_Worth"]) if financial_record.get("Net_Worth") else None,
                    "EMI_Amount": self._to_number(financial_record["EMI_Amount"]) if financial_record.get("EMI_Amount") else None,
                },
                "covenant_config": {
                    "covenant_type": str(config_record["covenant_type"]),
                    "metric": metric_name,
                    "threshold": str(config_record["threshold"]),
                    "frequency": str(config_record["frequency"]),
                    "due_date_offset": str(config_record["due_date_offset"]),
                    "definition": str(config_record["definition"]),
                    "borrower_id": str(config_record["borrower_id"]),
                    "facility_id": str(config_record["facility_id"]),
                },
            }
        except ValueError as exc:
            return json.dumps({"status": "error", "message": f"Failed to parse numeric fields from PDF: {exc}"})

        if normalized["borrower_id"] != normalized["covenant_config"]["borrower_id"]:
            return json.dumps({"status": "error", "message": "borrower_id mismatch between sections"})
        if normalized["facility_id"] != normalized["covenant_config"]["facility_id"]:
            return json.dumps({"status": "error", "message": "facility_id mismatch between sections"})
        if metric_name not in SUPPORTED_METRICS:
            return json.dumps({"status": "error", "message": f"Unsupported metric: {metric_name}"})

        return json.dumps({"status": "success", "payload": normalized}, default=str)

    def _extract_pdf_text(self, path: Path) -> str:
        text_parts: list[str] = []
        try:
            reader = PdfReader(str(path))
            for page in reader.pages:
                text = page.extract_text() or ""
                if text.strip():
                    text_parts.append(text)
        except Exception:
            text_parts = []

        # OCR disabled: only native PDF text extraction is used.
        return "\n".join(text_parts).strip()

    def _match_first(self, text: str, patterns: list[str]) -> str | None:
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                value = match.group(1).strip()
                if value:
                    return value
        return None

    def _frame_to_record(self, df: pd.DataFrame) -> Dict[str, Any]:
        df = df.dropna(how="all").dropna(axis=1, how="all")
        if df.empty:
            return {}

        # Case 1: explicit Field/Value columns in headers.
        normalized_cols = [self._normalize_label(c) for c in df.columns]
        if "field" in normalized_cols:
            field_idx = normalized_cols.index("field")
            value_idx = normalized_cols.index("value") if "value" in normalized_cols else min(field_idx + 1, len(df.columns) - 1)
            key_col = df.columns[field_idx]
            val_col = df.columns[value_idx]
            pairs = {str(k).strip(): v for k, v in zip(df[key_col], df[val_col]) if pd.notna(k) and str(k).strip()}
            if pairs:
                return pairs

        # Case 2: detect a row containing 'Field' and 'Value' labels (title/blank rows above).
        row_header = self._extract_field_value_pairs(df)
        if row_header:
            return row_header

        if len(df) == 1:
            return df.iloc[0].dropna().to_dict()
        return df.to_dict(orient="records")[0]

    def _extract_field_value_pairs(self, df: pd.DataFrame) -> Dict[str, Any]:
        for row_idx in range(len(df)):
            row = df.iloc[row_idx].tolist()
            normalized = [self._normalize_label(v) for v in row]
            if "field" not in normalized:
                continue
            field_col = normalized.index("field")
            value_col = normalized.index("value") if "value" in normalized else min(field_col + 1, len(row) - 1)

            out: Dict[str, Any] = {}
            for next_idx in range(row_idx + 1, len(df)):
                r = df.iloc[next_idx].tolist()
                key = r[field_col] if field_col < len(r) else None
                val = r[value_col] if value_col < len(r) else None
                if (key is None or str(key).strip() == "") and (val is None or str(val).strip() == ""):
                    # tolerate sparse rows; continue scanning
                    continue
                if key is not None and str(key).strip():
                    out[str(key).strip()] = val
            if out:
                return out
        return {}

    def _normalize_label(self, label: Any) -> str:
        key = str(label).strip().lower()
        key = re.sub(r"[^a-z0-9]+", "_", key)
        return key.strip("_")

    def _canonicalize_record(self, record: Dict[str, Any]) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        normalized_source: Dict[str, Any] = {}
        for k, v in record.items():
            nk = self._normalize_label(k)
            normalized_source[nk] = v

        def pick(target: str, default: Any = None) -> Any:
            for alias in FIELD_ALIASES.get(target, [target]):
                na = self._normalize_label(alias)
                if na in normalized_source and pd.notna(normalized_source[na]):
                    return normalized_source[na]
            return default

        out["borrower_id"] = pick("borrower_id")
        out["facility_id"] = pick("facility_id")
        out["period"] = pick("period", "Current")
        out["EBITDA"] = pick("EBITDA")
        out["Principal_Paid"] = pick("Principal_Paid")
        out["Interest_Paid"] = pick("Interest_Paid")
        out["Total_Debt"] = pick("Total_Debt")
        out["Net_Worth"] = pick("Net_Worth")
        out["EMI_Amount"] = pick("EMI_Amount")

        out["covenant_type"] = pick("covenant_type", "Financial")
        metric_name = self._normalize_metric(str(pick("metric", "DSCR")))
        out["metric"] = metric_name
        out["threshold"] = pick("threshold", METRIC_DEFAULT_THRESHOLD.get(metric_name, ">= 1.25"))
        out["frequency"] = pick("frequency", "Quarterly")
        out["due_date_offset"] = pick("due_date_offset", "0")
        out["definition"] = pick("definition", self._metric_definition(metric_name))
        out["borrower_id"] = out["borrower_id"] if out["borrower_id"] is not None else pick("borrower_id")
        out["facility_id"] = out["facility_id"] if out["facility_id"] is not None else pick("facility_id")

        return {k: v for k, v in out.items() if v is not None and str(v).strip() != ""}

    def _to_number(self, value: Any) -> float:
        if isinstance(value, (int, float)):
            return float(value)
        raw = str(value).strip()
        # Handle accounting negatives in parentheses.
        if raw.startswith("(") and raw.endswith(")"):
            raw = f"-{raw[1:-1]}"
        cleaned = re.sub(r"[^0-9.\-]", "", raw)
        return float(cleaned)

    def _normalize_metric(self, raw_metric: str) -> str:
        normalized = self._normalize_label(raw_metric).upper()
        for canonical, aliases in METRIC_ALIASES.items():
            if normalized == canonical:
                return canonical
            for alias in aliases:
                if normalized == self._normalize_label(alias).upper():
                    return canonical
        return normalized or "DSCR"

    def _metric_definition(self, metric_name: str) -> str:
        definitions = {
            "DSCR": "DSCR = EBITDA / (Principal_Paid + Interest_Paid)",
            "ICR": "ICR = EBITDA / Interest_Paid",
            "DEBT_TO_EBITDA": "Debt_to_EBITDA = Total_Debt / EBITDA",
            "DEBT_TO_NET_WORTH": "Debt_to_Net_Worth = Total_Debt / Net_Worth",
            "EBITDA_TO_EMI": "EBITDA_to_EMI = EBITDA / EMI_Amount",
        }
        return definitions.get(metric_name, "Metric-specific definition not provided")


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
        metric = str(config.get("metric", "DSCR")).upper()
        op, threshold_value = self._extract_threshold(config.get("threshold", ">= 1.25"), metric)

        try:
            actual_value, formula, inputs = self._compute_metric(metric, financials)
        except ValueError as exc:
            return json.dumps({"status": "error", "message": str(exc)})

        status = "COMPLIANT" if self._is_compliant(op, actual_value, threshold_value) else "BREACH"
        comparison_symbol = op
        decision_relation = "meets" if status == "COMPLIANT" else "breaches"

        result = {
            "status": "success",
            "borrower_id": payload["borrower_id"],
            "facility_id": payload["facility_id"],
            "period": payload["period"],
            "metric": metric,
            "all_financials": financials,
            "formula": formula,
            "inputs": inputs,
            "threshold": threshold_value,
            "threshold_operator": comparison_symbol,
            "actual": round(actual_value, 4),
            "comparison": f"{round(actual_value, 4)} {comparison_symbol} {threshold_value} ({decision_relation})",
            "decision": status,
        }
        return json.dumps(result)

    def _extract_threshold(self, raw: str, metric: str) -> tuple[str, float]:
        text = str(raw or "").strip()
        match = re.match(r"^(>=|<=|>|<|=)?\s*([-+]?\d+(?:\.\d+)?)$", text)
        if match:
            op = match.group(1) or self._default_operator(metric)
            return op, float(match.group(2))
        raise ValueError("Invalid threshold format. Use forms like '>= 1.25' or '<= 3.5'.")

    def _default_operator(self, metric: str) -> str:
        if metric in {"DEBT_TO_EBITDA", "DEBT_TO_NET_WORTH"}:
            return "<="
        return ">="

    def _is_compliant(self, op: str, actual: float, threshold: float) -> bool:
        if op == ">=":
            return actual >= threshold
        if op == "<=":
            return actual <= threshold
        if op == ">":
            return actual > threshold
        if op == "<":
            return actual < threshold
        if op == "=":
            return abs(actual - threshold) < 1e-9
        return False

    def _compute_metric(self, metric: str, financials: Dict[str, Any]) -> tuple[float, str, Dict[str, float]]:
        def _num(key: str) -> float:
            value = financials.get(key)
            if value is None:
                raise ValueError(f"Missing required financial input: {key}")
            return float(value)

        if metric == "DSCR":
            ebitda = _num("EBITDA")
            principal = _num("Principal_Paid")
            interest = _num("Interest_Paid")
            denom = principal + interest
            if denom <= 0:
                raise ValueError("Debt service must be greater than zero")
            return (
                ebitda / denom,
                "DSCR = EBITDA / (Principal_Paid + Interest_Paid)",
                {
                    "EBITDA": ebitda,
                    "Principal_Paid": principal,
                    "Interest_Paid": interest,
                    "Debt_Service": denom,
                },
            )

        if metric == "ICR":
            ebitda = _num("EBITDA")
            interest = _num("Interest_Paid")
            if interest <= 0:
                raise ValueError("Interest_Paid must be greater than zero for ICR")
            return (
                ebitda / interest,
                "ICR = EBITDA / Interest_Paid",
                {
                    "EBITDA": ebitda,
                    "Interest_Paid": interest,
                },
            )

        if metric == "DEBT_TO_EBITDA":
            debt = _num("Total_Debt")
            ebitda = _num("EBITDA")
            if ebitda <= 0:
                raise ValueError("EBITDA must be greater than zero for Debt_to_EBITDA")
            return (
                debt / ebitda,
                "Debt_to_EBITDA = Total_Debt / EBITDA",
                {
                    "Total_Debt": debt,
                    "EBITDA": ebitda,
                },
            )

        if metric == "DEBT_TO_NET_WORTH":
            debt = _num("Total_Debt")
            net_worth = _num("Net_Worth")
            if net_worth <= 0:
                raise ValueError("Net_Worth must be greater than zero for Debt_to_Net_Worth")
            return (
                debt / net_worth,
                "Debt_to_Net_Worth = Total_Debt / Net_Worth",
                {
                    "Total_Debt": debt,
                    "Net_Worth": net_worth,
                },
            )

        if metric == "EBITDA_TO_EMI":
            ebitda = _num("EBITDA")
            emi = _num("EMI_Amount")
            if emi <= 0:
                raise ValueError("EMI_Amount must be greater than zero for EBITDA_to_EMI")
            return (
                ebitda / emi,
                "EBITDA_to_EMI = EBITDA / EMI_Amount",
                {
                    "EBITDA": ebitda,
                    "EMI_Amount": emi,
                },
            )

        raise ValueError(
            f"Unsupported metric: {metric}. Supported metrics: {sorted(SUPPORTED_METRICS)}"
        )


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

        all_metrics = self._build_all_metrics(payload)
        llm_report = self._build_llm_report(payload, all_metrics)
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
            "all_metrics": all_metrics,
            "llm_report": llm_report,
            "recommended_action": (
                "Send breach alert to RM and hold for human review"
                if payload["decision"] == "BREACH"
                else "Mark covenant as compliant"
            ),
        }
        return json.dumps(report)

    def _build_all_metrics(self, payload: Dict[str, Any]) -> list[Dict[str, Any]]:
        calc_tool = DSCRCalculationTool()
        financials = payload.get("all_financials", {})
        if not isinstance(financials, dict):
            financials = {}
        results: list[Dict[str, Any]] = []
        for metric in sorted(SUPPORTED_METRICS):
            threshold_raw = METRIC_DEFAULT_THRESHOLD.get(metric, ">= 1.25")
            op, threshold_value = calc_tool._extract_threshold(threshold_raw, metric)
            try:
                actual, formula, _ = calc_tool._compute_metric(metric, financials)
                decision = "COMPLIANT" if calc_tool._is_compliant(op, actual, threshold_value) else "BREACH"
                results.append(
                    {
                        "metric": metric,
                        "actual": round(actual, 4),
                        "threshold": threshold_value,
                        "threshold_operator": op,
                        "decision": decision,
                        "formula": formula,
                        "comparison": f"{round(actual, 4)} {op} {threshold_value}",
                    }
                )
            except ValueError as exc:
                results.append(
                    {
                        "metric": metric,
                        "decision": "NOT_EVALUATED",
                        "reason": str(exc),
                        "threshold": threshold_value,
                        "threshold_operator": op,
                    }
                )
        return results

    def _build_llm_report(self, payload: Dict[str, Any], all_metrics: list[Dict[str, Any]]) -> Dict[str, Any]:
        if os.environ.get("COVENANT_ENABLE_LLM_REPORT", "1").strip().lower() in ("0", "false", "no"):
            return self._fallback_llm_report(all_metrics)

        metric_lines = []
        for item in all_metrics:
            metric_lines.append(
                f"- {item.get('metric')}: decision={item.get('decision')}, actual={item.get('actual')}, "
                f"threshold={item.get('threshold_operator', '')} {item.get('threshold')}, reason={item.get('reason', '')}"
            )
        prompt = (
            "You are a covenant risk analyst. Based on these computed covenant results, provide a short risk summary and 3-5 "
            "actionable resolution steps. Return STRICT JSON with keys: summary (string), resolution_points (array of strings).\n\n"
            f"Borrower: {payload.get('borrower_id')}\n"
            f"Facility: {payload.get('facility_id')}\n"
            f"Period: {payload.get('period')}\n"
            f"Primary decision: {payload.get('decision')}\n"
            "Metric details:\n"
            + "\n".join(metric_lines)
        )
        try:
            model_name = os.environ.get("MODEL", "ollama/llama3.1")
            analyst = Agent(
                role="Covenant Risk Analyst",
                goal="Summarize covenant risks and recommended remediation",
                backstory="You provide concise, practical risk commentary for lending covenants.",
                llm=model_name,
                verbose=False,
                max_iter=2,
                max_execution_time=15,
            )
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(analyst.kickoff, prompt)
                result = future.result(timeout=20)
            raw = getattr(result, "raw", "") or ""
            parsed = self._parse_llm_json(raw)
            if isinstance(parsed.get("resolution_points"), list) and parsed.get("summary"):
                return parsed
        except TimeoutError:
            pass
        except Exception:
            pass
        return self._fallback_llm_report(all_metrics)

    def _parse_llm_json(self, text: str) -> Dict[str, Any]:
        raw = str(text).strip()
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
        match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group(0))
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                pass
        return {}

    def _fallback_llm_report(self, all_metrics: list[Dict[str, Any]]) -> Dict[str, Any]:
        breaches = [m for m in all_metrics if m.get("decision") == "BREACH"]
        if breaches:
            names = ", ".join(str(m.get("metric")) for m in breaches)
            return {
                "summary": f"Breach observed in: {names}. Immediate remediation is recommended.",
                "resolution_points": [
                    "Validate source financial values and recalculate impacted metrics.",
                    "Discuss a corrective operating plan with borrower management within 7 days.",
                    "Monitor cash flows and debt servicing weekly until covenant returns to compliant levels.",
                ],
            }
        return {
            "summary": "All evaluated covenants are currently compliant with configured thresholds.",
            "resolution_points": [
                "Continue periodic monitoring with the same metric set.",
                "Track early warning signals (revenue, debt, and cash flow trends).",
                "Reassess thresholds quarterly based on portfolio and borrower risk profile.",
            ],
        }


class AgenticValidateExcelTool(BaseTool):
    name: str = "agentic_validate_excel_tool"
    description: str = (
        "Step 1: validate workbook and store exact payload in shared state by run_id. "
        "Returns run_id and stored key only."
    )
    args_schema: Type[BaseModel] = AgenticValidateSchema

    def _run(
        self,
        run_id: str,
        file_path: str,
        payload: Any | None = None,
        object: Any | None = None,
        status_update_frequency_seconds: int | None = None,
    ) -> str:
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

    def _run(
        self,
        run_id: str,
        payload: Any | None = None,
        object: Any | None = None,
        status_update_frequency_seconds: int | None = None,
    ) -> str:
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

    def _run(
        self,
        run_id: str,
        payload: Any | None = None,
        object: Any | None = None,
        status_update_frequency_seconds: int | None = None,
    ) -> str:
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