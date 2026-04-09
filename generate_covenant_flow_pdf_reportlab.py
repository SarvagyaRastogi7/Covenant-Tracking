from __future__ import annotations

from textwrap import wrap

from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape
from reportlab.pdfgen import canvas


PAGE_W, PAGE_H = landscape((842, 595))


def draw_box(c: canvas.Canvas, x, y, w, h, title, lines, fill_color, stroke_color):
    c.setStrokeColor(stroke_color)
    c.setFillColor(fill_color)
    c.roundRect(x, y, w, h, 10, stroke=1, fill=1)

    c.setFillColor(colors.HexColor("#0f2940"))
    c.setFont("Helvetica-Bold", 10)
    c.drawCentredString(x + w / 2, y + h - 16, title)

    c.setFillColor(colors.HexColor("#1f3d5a"))
    c.setFont("Helvetica", 8.2)
    ty = y + h - 30
    for line in lines:
        c.drawCentredString(x + w / 2, ty, line)
        ty -= 10


def draw_arrow(c: canvas.Canvas, x1, y1, x2, y2, label=""):
    c.setStrokeColor(colors.HexColor("#1f4e79"))
    c.setFillColor(colors.HexColor("#1f4e79"))
    c.setLineWidth(1.2)
    c.line(x1, y1, x2, y2)

    # Simple triangular arrow head
    if x2 >= x1:
        c.line(x2, y2, x2 - 6, y2 + 3)
        c.line(x2, y2, x2 - 6, y2 - 3)
    else:
        c.line(x2, y2, x2 + 6, y2 + 3)
        c.line(x2, y2, x2 + 6, y2 - 3)

    if label:
        c.setFont("Helvetica-Bold", 8)
        c.setFillColor(colors.HexColor("#0f2940"))
        c.drawCentredString((x1 + x2) / 2, (y1 + y2) / 2 + 8, label)


def to_lines(text: str, width: int = 42) -> list[str]:
    out: list[str] = []
    for part in text.split("\n"):
        out.extend(wrap(part, width=width) or [""])
    return out


def main():
    c = canvas.Canvas("Covenant_Flow_Diagram.pdf", pagesize=(PAGE_W, PAGE_H))

    c.setFont("Helvetica-Bold", 16)
    c.setFillColor(colors.HexColor("#102a43"))
    c.drawCentredString(
        PAGE_W / 2,
        PAGE_H - 30,
        "Configurable Covenant Tracking Workflow (Deterministic + Agentic)",
    )

    draw_box(
        c,
        25,
        450,
        145,
        90,
        "User Interface",
        to_lines("Upload covenant workbook (.xlsx) via web page or CLI input path."),
        colors.HexColor("#edf6ff"),
        colors.HexColor("#1f4e79"),
    )
    draw_box(
        c,
        190,
        450,
        165,
        90,
        "API + Main Router",
        to_lines("Reads bytes/args, applies defaults, and checks selected execution mode."),
        colors.HexColor("#edf6ff"),
        colors.HexColor("#1f4e79"),
    )
    draw_box(
        c,
        375,
        450,
        140,
        90,
        "Mode Decision",
        to_lines("use_agents=true or COVENANT_USE_AGENTS=1 ?"),
        colors.HexColor("#fff7e6"),
        colors.HexColor("#a66a00"),
    )

    draw_box(
        c,
        55,
        315,
        220,
        95,
        "Deterministic Validation",
        to_lines("ExcelValidationTool: required sheet/field checks, payload normalization, DSCR-only gate."),
        colors.HexColor("#f6fbff"),
        colors.HexColor("#1f4e79"),
    )
    draw_box(
        c,
        55,
        195,
        220,
        95,
        "Deterministic Calculation",
        to_lines("DSCRCalculationTool: DSCR=EBITDA/(Principal+Interest), threshold compare, COMPLIANT/BREACH."),
        colors.HexColor("#f6fbff"),
        colors.HexColor("#1f4e79"),
    )
    draw_box(
        c,
        55,
        75,
        220,
        95,
        "Deterministic Report",
        to_lines("CovenantReportTool: final COVENANT_DECISION_REPORT with calculation trace and action."),
        colors.HexColor("#f6fbff"),
        colors.HexColor("#1f4e79"),
    )

    draw_box(
        c,
        540,
        340,
        270,
        78,
        "Agentic Task 1: Validate",
        to_lines("excel_ingestion_agent uses agentic_validate_excel_tool; stores step1 state by run_id."),
        colors.HexColor("#f0fff4"),
        colors.HexColor("#1f7a4d"),
    )
    draw_box(
        c,
        540,
        245,
        270,
        78,
        "Agentic Task 2: Calculate DSCR",
        to_lines("calculation_agent uses agentic_calculate_dscr_tool; reads step1 payload, stores step2."),
        colors.HexColor("#f0fff4"),
        colors.HexColor("#1f7a4d"),
    )
    draw_box(
        c,
        540,
        150,
        270,
        78,
        "Agentic Task 3: Generate Report",
        to_lines("reporting_agent uses agentic_generate_report_tool; reads step2, stores step3 report."),
        colors.HexColor("#f0fff4"),
        colors.HexColor("#1f7a4d"),
    )
    draw_box(
        c,
        540,
        55,
        270,
        78,
        "Agentic Aggregation + Cleanup",
        to_lines("Builds tasks_output/final_task_json; clears shared state and deletes temp file."),
        colors.HexColor("#e8fff5"),
        colors.HexColor("#1f7a4d"),
    )

    draw_box(
        c,
        315,
        100,
        180,
        115,
        "Output",
        to_lines("JSON response\nHTTP 200 on success\nHTTP 422 on errors"),
        colors.HexColor("#f5f3ff"),
        colors.HexColor("#5b4abf"),
    )

    draw_arrow(c, 170, 495, 190, 495)
    draw_arrow(c, 355, 495, 375, 495)
    draw_arrow(c, 445, 450, 200, 410, "No")
    draw_arrow(c, 470, 450, 675, 418, "Yes")

    draw_arrow(c, 165, 315, 165, 290)
    draw_arrow(c, 165, 195, 165, 170)
    draw_arrow(c, 275, 120, 315, 150)

    draw_arrow(c, 675, 340, 675, 323)
    draw_arrow(c, 675, 245, 675, 228)
    draw_arrow(c, 675, 150, 675, 133)
    draw_arrow(c, 540, 85, 495, 145)

    c.setFont("Helvetica", 8.5)
    c.setFillColor(colors.HexColor("#486581"))
    c.drawCentredString(PAGE_W / 2, 20, "Covenant Tracking Phase 1.2 - Flow Diagram")

    c.save()


if __name__ == "__main__":
    main()
