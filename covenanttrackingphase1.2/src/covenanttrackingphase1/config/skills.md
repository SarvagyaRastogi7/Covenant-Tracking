# Covenant Metric Skills Reference

Use this file as the canonical reference for covenant metric definitions and threshold policy.

## Supported Metrics and Formulas

- DSCR
  - Formula: `DSCR = EBITDA / (Principal_Paid + Interest_Paid)`
  - Compliance rule: higher is better
  - Hardcoded threshold: `>= 1.25`

- ICR
  - Formula: `ICR = EBITDA / Interest_Paid`
  - Compliance rule: higher is better
  - Hardcoded threshold: `>= 2.00`

- DEBT_TO_EBITDA
  - Formula: `Debt_to_EBITDA = Total_Debt / EBITDA`
  - Compliance rule: lower is better
  - Hardcoded threshold: `<= 3.50`

- DEBT_TO_NET_WORTH
  - Formula: `Debt_to_Net_Worth = Total_Debt / Net_Worth`
  - Compliance rule: lower is better
  - Hardcoded threshold: `<= 2.50`

- EBITDA_TO_EMI
  - Formula: `EBITDA_to_EMI = EBITDA / EMI_Amount`
  - Compliance rule: higher is better
  - Hardcoded threshold: `>= 1.20`

## Field Mappings Used By Parser

- Borrower ID -> borrower_id
- Loan Account No -> facility_id
- Certification Date / Reporting Period -> period
- EBITDA -> EBITDA
- Principal Paid YTD -> Principal_Paid
- Interest Paid YTD -> Interest_Paid
- Total Debt -> Total_Debt
- Net Worth -> Net_Worth
- EMI Amount -> EMI_Amount

## Enforcement Rules

- Do not infer unavailable numeric inputs.
- If required inputs for a selected metric are missing, mark as `NOT_EVALUATED` with reason.
- Deterministic calculation tools are source of truth for final decisions.
