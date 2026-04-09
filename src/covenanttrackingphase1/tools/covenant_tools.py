"""Tools for loading covenant workbook data and computing compliance metrics."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Type

import pandas as pd
from crewai.tools import BaseTool
from pydantic import BaseModel, Field


class ReadCovenantWorkbookInput(BaseModel):
    """Path to the covenant tracking Excel workbook."""

    file_path: str = Field(
        ...,
        description="Absolute or project-relative path to the .xlsx with sheets "
        "Financial_Statement and Covenant_Config.",
    )


class ReadCovenantWorkbookTool(BaseTool):
    name: str = "read_covenant_workbook"
    description: str = (
        "Loads covenant input data from an Excel workbook. Returns markdown tables "
        "for Financial_Statement and Covenant_Config sheets. Use this first to see "
        "periods, metrics, thresholds, and definitions."
    )
    args_schema: Type[BaseModel] = ReadCovenantWorkbookInput

    def _run(self, file_path: str) -> str:
        p = Path(file_path).expanduser()
        if not p.is_file():
            return f"Error: file not found: {p}"
        try:
            xl = pd.ExcelFile(p)
        except Exception as exc:  # noqa: BLE001
            return f"Error reading workbook: {exc}"
        parts: list[str] = [f"# Covenant workbook: `{p.name}`\n", f"Sheets: {', '.join(xl.sheet_names)}\n"]
        for sheet in xl.sheet_names:
            df = pd.read_excel(p, sheet_name=sheet)
            parts.append(f"## {sheet}\n")
            parts.append(df.fillna("").to_markdown(index=False))
            parts.append("\n")
        return "\n".join(parts)


def _parse_threshold(threshold: str) -> tuple[str, float] | tuple[None, None]:
    """Parse strings like '>= 1.25' into (operator, value)."""
    if threshold is None or (isinstance(threshold, float) and pd.isna(threshold)):
        return None, None
    s = str(threshold).strip()
    m = re.match(r"^\s*(>=|<=|>|<|=)\s*([0-9.+-eE]+)\s*$", s)
    if not m:
        return None, None
    return m.group(1), float(m.group(2))


def _cmp_ok(op: str, actual: float, limit: float) -> bool:
    if op == ">=":
        return actual >= limit
    if op == "<=":
        return actual <= limit
    if op == ">":
        return actual > limit
    if op == "<":
        return actual < limit
    if op == "=":
        return abs(actual - limit) < 1e-9
    return False


class ComputeCovenantComplianceInput(BaseModel):
    file_path: str = Field(
        ...,
        description="Path to the same .xlsx used for tracking (Financial_Statement + Covenant_Config).",
    )
    reporting_period: str = Field(
        ...,
        description="Period label to filter Financial_Statement rows (e.g. Q4 FY2025-26). "
        "Must match the period column in the sheet.",
    )


class ComputeCovenantComplianceTool(BaseTool):
    name: str = "compute_covenant_compliance"
    description: str = (
        "Computes actual covenant metrics from Financial_Statement for the given period "
        "and compares them to Covenant_Config thresholds (e.g. DSCR). "
        "Returns a plain-text summary with computed values, pass/fail, and headroom. "
        "Call this for quantitative compliance; do not invent ratios."
    )
    args_schema: Type[BaseModel] = ComputeCovenantComplianceInput

    def _run(self, file_path: str, reporting_period: str) -> str:
        p = Path(file_path).expanduser()
        if not p.is_file():
            return f"Error: file not found: {p}"
        try:
            fs = pd.read_excel(p, sheet_name="Financial_Statement")
            cc = pd.read_excel(p, sheet_name="Covenant_Config")
        except ValueError:
            return "Error: workbook must contain sheets Financial_Statement and Covenant_Config."
        except Exception as exc:  # noqa: BLE001
            return f"Error reading workbook: {exc}"

        period = str(reporting_period).strip()
        fs_period = fs[fs["period"].astype(str).str.strip() == period]
        if fs_period.empty:
            avail = fs["period"].dropna().astype(str).unique().tolist()
            return f"No Financial_Statement rows for period `{period}`. Available: {avail}"

        lines: list[str] = [
            f"# Computed compliance for period `{period}`",
            "",
        ]

        for _, crow in cc.iterrows():
            borrower = crow.get("borrower_id")
            facility = crow.get("facility_id")
            metric = str(crow.get("metric", "")).strip().upper()
            threshold_raw = crow.get("threshold")
            definition = crow.get("definition", "")

            row = fs_period[
                (fs_period["borrower_id"] == borrower) & (fs_period["facility_id"] == facility)
            ]
            if row.empty:
                lines.append(
                    f"- **{metric}** (borrower={borrower}, facility={facility}): "
                    f"no financial row for this period/facility."
                )
                continue
            r = row.iloc[0]
            ebitda = float(r["EBITDA"])
            principal = float(r["Principal_Paid"])
            interest = float(r["Interest_Paid"])
            denom = principal + interest

            if metric == "DSCR" or "dscr" in str(definition).lower():
                if denom <= 0:
                    actual = float("nan")
                    detail = "denominator (Principal_Paid + Interest_Paid) is zero or negative"
                else:
                    actual = ebitda / denom
                    detail = f"EBITDA={ebitda:,.0f}, Principal+Interest={denom:,.0f}"
            else:
                lines.append(
                    f"- **{metric}**: automatic check not implemented; "
                    f"see definition: {definition}"
                )
                continue

            op, limit = _parse_threshold(str(threshold_raw) if threshold_raw is not None else "")
            if op is None or limit is None:
                lines.append(
                    f"- **{metric}**: could not parse threshold `{threshold_raw}`. {detail}"
                )
                continue

            if actual != actual:  # NaN
                ok = False
                status = "FAIL (undefined)"
            else:
                ok = _cmp_ok(op, actual, limit)
                status = "PASS" if ok else "BREACH"

            headroom = ""
            if actual == actual and limit == limit and denom > 0 and op in (">=", ">"):
                headroom = f" headroom vs limit {op} {limit}: actual − limit = {actual - limit:+.4f}"

            lines.append(
                f"- **{metric}** {status}: actual={actual:.4f} vs threshold `{threshold_raw}` "
                f"({detail}).{headroom}"
            )

        return "\n".join(lines)
