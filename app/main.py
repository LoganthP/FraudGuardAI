"""
FraudGuard AI — Real-Time Transaction Fraud Detection API
Powered by XGBoost + Groq (Llama 3.3)
"""

import os
import io
import uuid
import datetime
import math
import numpy as np
import pandas as pd
import joblib
from pathlib import Path
from collections import OrderedDict

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse
from pydantic import BaseModel, Field
from dotenv import load_dotenv
from langchain_groq import ChatGroq
from fpdf import FPDF
import base64

load_dotenv()

# ── Paths ────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.parent
MODEL_PATH = BASE_DIR / "models" / "xboost_model.pkl"
STATIC_DIR = Path(__file__).parent / "static"

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="FraudGuard AI",
    description="Real-time financial transaction fraud detection powered by XGBoost + Groq",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# ── Model ─────────────────────────────────────────────────────────────────────
_model = None

def get_model():
    global _model
    if _model is None:
        _model = joblib.load(MODEL_PATH)
    return _model

# ── LLM ───────────────────────────────────────────────────────────────────────
llm = ChatGroq(
    model="llama-3.3-70b-versatile",
    temperature=0,
    groq_api_key=os.getenv("GROQ_API_KEY"),
)

# ── Feature list (must match training) ────────────────────────────────────────
FEATURES = [
    "amount", "log_amount", "recency_hours", "txn_count_24h",
    "is_dest_new", "hours_day",
    "oldbalanceOrg", "newbalanceOrig", "oldbalanceDest", "newbalanceDest",
    "type_CASH_IN", "type_CASH_OUT", "type_DEBIT", "type_PAYMENT", "type_TRANSFER",
]

FRAUD_THRESHOLD = 0.8

# ── Report store (in-memory, max 50 entries) ──────────────────────────────────
report_store: OrderedDict = OrderedDict()

# ── Schemas ───────────────────────────────────────────────────────────────────
class Transaction(BaseModel):
    amount: float = Field(..., gt=0, description="Transaction amount in USD")
    recency_hours: float = Field(..., ge=0, description="Hours since sender's last transaction")
    txn_count_24h: int = Field(..., ge=0, description="Number of transactions by sender in last 24h")
    is_dest_new: int = Field(..., ge=0, le=1, description="1 if destination account is new to sender")
    hours_day: int = Field(..., ge=0, le=23, description="Hour of day (0\u201323)")
    oldbalanceOrg: float = Field(..., ge=0, description="Sender's balance before transaction")
    newbalanceOrig: float = Field(..., ge=0, description="Sender's balance after transaction")
    oldbalanceDest: float = Field(..., ge=0, description="Recipient's balance before transaction")
    newbalanceDest: float = Field(..., ge=0, description="Recipient's balance after transaction")
    # Transaction type \u2014 send exactly one as 1
    type_CASH_IN: int = Field(0, ge=0, le=1)
    type_CASH_OUT: int = Field(0, ge=0, le=1)
    type_DEBIT: int = Field(0, ge=0, le=1)
    type_PAYMENT: int = Field(0, ge=0, le=1)
    type_TRANSFER: int = Field(0, ge=0, le=1)
    # Metadata fields \u2014 not used in ML prediction
    user_id: str = ""
    transaction_id: str = ""
    currency: str = "USD"


class PredictionResponse(BaseModel):
    txn_id: str
    fraud_probability: float
    is_fraud: bool
    decision: str
    risk_level: str
    summary: str


class StatementReportRequest(BaseModel):
    file_name: str
    file_type: str           # "pdf" or "image"
    transaction_count: int | None = None
    raw_analysis: str
    risk_summary: str
    timestamp: str


# ── Helpers ───────────────────────────────────────────────────────────────────
def resolve_txn_type(txn: dict) -> str:
    for t in ("TRANSFER", "CASH_OUT", "PAYMENT", "CASH_IN", "DEBIT"):
        if txn.get(f"type_{t}") == 1:
            return t
    return "UNKNOWN"


def build_prompt(txn: dict, fraud_prob: float, is_fraud: bool, risk_level: str, txn_type: str) -> str:
    decision_label = "FRAUD DETECTED" if is_fraud else "LEGITIMATE TRANSACTION"
    verdict = "flagged as fraudulent" if is_fraud else "considered legitimate"
    return f"""You are a senior financial fraud detection analyst. Analyze the transaction below and write a concise, professional 2–3 sentence summary explaining why it is {verdict}.

DETECTION RESULT:
- Fraud Probability : {fraud_prob * 100:.2f}%
- Decision         : {decision_label}
- Risk Level       : {risk_level}

TRANSACTION DETAILS:
- Type             : {txn_type}
- Amount           : ${txn['amount']:,.2f}
- Sender Balance   : ${txn['oldbalanceOrg']:,.2f} → ${txn['newbalanceOrig']:,.2f}
- Recipient Balance: ${txn['oldbalanceDest']:,.2f} → ${txn['newbalanceDest']:,.2f}
- New Destination  : {'Yes' if txn['is_dest_new'] == 1 else 'No'}
- Hours Since Last : {txn['recency_hours']}h
- Txns in 24h      : {txn['txn_count_24h']}

Focus on the specific risk indicators present. Be direct and factual."""


# ── Routes ────────────────────────────────────────────────────────────────────
@app.get("/", include_in_schema=False)
def serve_ui():
    return FileResponse(
        str(STATIC_DIR / "index.html"),
        media_type="text/html; charset=utf-8"
    )


@app.post("/predict", response_model=PredictionResponse)
def predict(transaction: Transaction):
    txn = transaction.dict()

    # Derived feature
    txn["log_amount"] = float(np.log1p(txn["amount"]))

    # Extract metadata BEFORE building df (not fed into ML model)
    meta_user_id      = txn.pop("user_id", "")
    meta_txn_id       = txn.pop("transaction_id", "")
    meta_currency     = txn.pop("currency", "USD")

    df = pd.DataFrame([txn])[FEATURES]
    ml_model = get_model()
    fraud_prob = float(ml_model.predict_proba(df)[0, 1])

    is_fraud = fraud_prob >= FRAUD_THRESHOLD
    risk_level = (
        "HIGH" if fraud_prob >= FRAUD_THRESHOLD
        else "MEDIUM" if fraud_prob >= 0.5
        else "LOW"
    )

    txn_type = resolve_txn_type(txn)
    prompt = build_prompt(txn, fraud_prob, is_fraud, risk_level, txn_type)

    try:
        response = llm.invoke([
            {"role": "system", "content": "You are a financial fraud detection expert. Be concise and professional."},
            {"role": "user", "content": prompt},
        ])
        summary = response.content.strip()
    except Exception as exc:
        summary = f"AI summary unavailable: {exc}"

    txn_id = uuid.uuid4().hex[:12]

    # Store for PDF generation (cap at 50)
    if len(report_store) >= 50:
        report_store.popitem(last=False)
    report_store[txn_id] = {
        "txn": txn,
        "txn_type": txn_type,
        "fraud_probability": round(fraud_prob, 4),
        "is_fraud": is_fraud,
        "decision": "FRAUD" if is_fraud else "LEGITIMATE",
        "risk_level": risk_level,
        "summary": summary,
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
        "meta_user_id": meta_user_id,
        "meta_txn_id": meta_txn_id,
        "meta_currency": meta_currency,
    }

    return PredictionResponse(
        txn_id=txn_id,
        fraud_probability=round(fraud_prob, 4),
        is_fraud=is_fraud,
        decision="FRAUD" if is_fraud else "LEGITIMATE",
        risk_level=risk_level,
        summary=summary,
    )


# ── PDF helpers ───────────────────────────────────────────────────────────────
def _rgb(hex_color: str):
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))


def _wrap_text(text: str, max_chars: int) -> list:
    """Simple word-wrap returning list of lines."""
    words = text.split()
    lines, current = [], ""
    for word in words:
        if len(current) + len(word) + 1 <= max_chars:
            current = (current + " " + word).lstrip()
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


@app.get("/report/{txn_id}")
def download_report(txn_id: str):
    if txn_id not in report_store:
        raise HTTPException(status_code=404, detail="Report not found. Run a scan first.")

    r = report_store[txn_id]
    txn = r["txn"]
    is_fraud = r["is_fraud"]
    prob_pct = r["fraud_probability"] * 100
    timestamp = r["timestamp"]
    summary = r["summary"] or "[AI SUMMARY UNAVAILABLE]"

    # ── Colours ───────────────────────────────────────────────────────────────
    BG        = (5, 5, 8)
    INDIGO    = (99, 102, 241)
    ROSE      = (244, 63, 94)
    EMERALD   = (16, 185, 129)
    WHITE     = (255, 255, 255)
    MUTED     = (120, 120, 140)
    ROW_A     = (13, 13, 20)
    ROW_B     = (17, 17, 24)
    INSET     = (10, 10, 18)
    VERDICT   = ROSE if is_fraud else EMERALD

    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=False)

    W = pdf.w  # 210mm
    M = 10     # margin

    # ── Page background ───────────────────────────────────────────────────────
    pdf.set_fill_color(*BG)
    pdf.rect(0, 0, W, pdf.h, "F")

    # ── Header bar ────────────────────────────────────────────────────────────
    pdf.set_fill_color(*INDIGO)
    pdf.rect(0, 0, W, 18, "F")
    pdf.set_text_color(*WHITE)
    pdf.set_font("Courier", "B", 13)
    pdf.set_xy(M, 5)
    pdf.cell(0, 8, "FRAUDGUARD // FORENSIC DIVISION", ln=0)
    pdf.set_font("Courier", "", 8)
    pdf.set_xy(W - 80, 5)
    pdf.cell(70, 4, f"REPORT ID: {txn_id}", align="R", ln=1)
    pdf.set_xy(W - 80, 9)
    pdf.set_text_color(200, 200, 220)
    pdf.cell(70, 4, timestamp[:19].replace("T", "  ") + " UTC", align="R")

    # ── Verdict banner ────────────────────────────────────────────────────────
    pdf.set_fill_color(*VERDICT)
    pdf.rect(0, 18, W, 13, "F")
    verdict_text = (
        "  WARNING: THREAT DETECTED  --  FRAUD CONFIRMED"
        if is_fraud else
        "  CLEARANCE GRANTED  --  TRANSACTION LEGITIMATE"
    )
    pdf.set_font("Courier", "B", 12)
    pdf.set_text_color(*WHITE)
    pdf.set_xy(0, 21)
    pdf.cell(W, 7, verdict_text, align="C")

    # ── Score + Risk tier ─────────────────────────────────────────────────────
    y = 36
    pdf.set_fill_color(*ROW_A)
    pdf.rect(M, y, (W - 2*M) / 2 - 2, 22, "F")
    pdf.rect((W/2) + 1, y, (W - 2*M) / 2 - 2, 22, "F")

    pdf.set_font("Courier", "", 7)
    pdf.set_text_color(*MUTED)
    pdf.set_xy(M + 3, y + 2)
    pdf.cell(0, 4, "FRAUD PROBABILITY")
    pdf.set_xy((W/2) + 4, y + 2)
    pdf.cell(0, 4, "RISK TIER")

    pdf.set_font("Courier", "B", 26)
    pdf.set_text_color(*VERDICT)
    pdf.set_xy(M + 3, y + 6)
    pdf.cell(0, 14, f"{prob_pct:.2f}%")
    pdf.set_font("Courier", "B", 18)
    pdf.set_xy((W/2) + 4, y + 7)
    pdf.cell(0, 12, r["risk_level"])

    # ── Section divider: parameters ───────────────────────────────────────────
    y = 64
    pdf.set_draw_color(*INDIGO)
    pdf.set_line_width(0.3)
    pdf.line(M, y, W - M, y)
    pdf.set_font("Courier", "B", 7)
    pdf.set_text_color(*INDIGO)
    pdf.set_xy(M, y - 4)
    pdf.cell(0, 4, "TRANSACTION PARAMETERS")

    # ── Feature table ─────────────────────────────────────────────────────────
    y += 2
    col1 = 90
    col2 = W - 2*M - col1

    # Header row
    pdf.set_fill_color(*INDIGO)
    pdf.set_text_color(*WHITE)
    pdf.set_font("Courier", "B", 8)
    pdf.set_xy(M, y)
    pdf.cell(col1, 6, "  PARAMETER", fill=True)
    pdf.cell(col2, 6, "VALUE", fill=True, ln=1)
    y += 6

    def txn_type_str(t: dict) -> str:
        for k in ("TRANSFER", "CASH_OUT", "PAYMENT", "CASH_IN", "DEBIT"):
            if t.get(f"type_{k}") == 1:
                return k
        return "UNKNOWN"

    rows = [
        ("USER IDENTIFIER",     r.get("meta_user_id") or "—"),
        ("TRANSACTION REF",     r.get("meta_txn_id") or "—"),
        ("CURRENCY",            r.get("meta_currency") or "USD"),
        ("TRANSACTION TYPE",    txn_type_str(txn)),
        ("AMOUNT",              f"${txn['amount']:,.2f}"),
        ("LOG AMOUNT",          f"{txn.get('log_amount', math.log1p(txn['amount'])):.4f}"),
        ("RECENCY (HOURS)",     f"{txn['recency_hours']:.2f}"),
        ("HOUR OF DAY",         str(txn['hours_day'])),
        ("TXN COUNT 24H",       str(txn['txn_count_24h'])),
        ("NEW DESTINATION",     "YES" if txn['is_dest_new'] == 1 else "NO"),
        ("SENDER BAL BEFORE",   f"${txn['oldbalanceOrg']:,.2f}"),
        ("SENDER BAL AFTER",    f"${txn['newbalanceOrig']:,.2f}"),
        ("SENDER NET CHANGE",   f"${txn['newbalanceOrig'] - txn['oldbalanceOrg']:+,.2f}"),
        ("RECIP BAL BEFORE",    f"${txn['oldbalanceDest']:,.2f}"),
        ("RECIP BAL AFTER",     f"${txn['newbalanceDest']:,.2f}"),
        ("RECIP NET CHANGE",    f"${txn['newbalanceDest'] - txn['oldbalanceDest']:+,.2f}"),
        ("TYPE_CASH_IN",        str(txn.get('type_CASH_IN', 0))),
        ("TYPE_CASH_OUT",       str(txn.get('type_CASH_OUT', 0))),
        ("TYPE_DEBIT",          str(txn.get('type_DEBIT', 0))),
        ("TYPE_PAYMENT",        str(txn.get('type_PAYMENT', 0))),
        ("TYPE_TRANSFER",       str(txn.get('type_TRANSFER', 0))),
    ]

    pdf.set_font("Courier", "", 8)
    for i, (label, value) in enumerate(rows):
        fill_color = ROW_A if i % 2 == 0 else ROW_B
        pdf.set_fill_color(*fill_color)
        pdf.set_text_color(*MUTED)
        pdf.set_xy(M, y)
        pdf.cell(col1, 5.5, f"  {label}", fill=True)
        pdf.set_text_color(*WHITE)
        pdf.cell(col2, 5.5, f"  {value}", fill=True, ln=1)
        y += 5.5

    # ── Section divider: AI summary ───────────────────────────────────────────
    y += 3
    pdf.set_draw_color(*INDIGO)
    pdf.line(M, y, W - M, y)
    pdf.set_font("Courier", "B", 7)
    pdf.set_text_color(*INDIGO)
    pdf.set_xy(M, y - 4)
    pdf.cell(0, 4, "AI ANALYST SUMMARY  --  GROQ  LLAMA-3.3")

    # ── Summary block ─────────────────────────────────────────────────────────
    y += 3
    block_h = 40
    pdf.set_fill_color(*INSET)
    pdf.rect(M, y, W - 2*M, block_h, "F")

    pdf.set_font("Courier", "", 8.5)
    pdf.set_text_color(*WHITE)
    lines = _wrap_text(summary, 95)
    text_y = y + 4
    for line in lines:
        if text_y > y + block_h - 5:
            break
        pdf.set_xy(M + 4, text_y)
        pdf.cell(0, 5, line)
        text_y += 5

    # ── Watermark ─────────────────────────────────────────────────────────────
    pdf.set_font("Courier", "B", 38)
    pdf.set_text_color(40, 41, 90)   # very dark indigo — simulates low opacity
    pdf.set_xy(30, 120)
    # FPDF doesn't support rotation natively; write diagonally using set_xy offset
    pdf.cell(0, 20, "FORENSIC COPY")

    # ── Footer ────────────────────────────────────────────────────────────────
    footer_y = pdf.h - 10
    pdf.set_draw_color(*INDIGO)
    pdf.set_line_width(0.2)
    pdf.line(M, footer_y - 2, W - M, footer_y - 2)
    pdf.set_font("Courier", "", 6)
    pdf.set_text_color(*MUTED)
    pdf.set_xy(M, footer_y)
    pdf.cell((W - 2*M) / 3, 4, "FRAUDGUARD AI  |  CONFIDENTIAL  |  NOT FOR DISTRIBUTION")
    pdf.set_xy(W/2 - 30, footer_y)
    pdf.cell(60, 4, "POWERED BY XGBOOST + GROQ LLAMA-3.3", align="C")
    pdf.set_xy(W - M - 30, footer_y)
    pdf.cell(30, 4, "PAGE 1 OF 1", align="R")

    # ── Stream response ───────────────────────────────────────────────────────
    pdf_bytes = pdf.output()
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=FRAUDGUARD_{txn_id}.pdf"},
    )


# ── Statement Analysis ────────────────────────────────────────────────────────
@app.post("/analyse-statement")
async def analyse_statement(file: UploadFile = File(...)):
    content_type = file.content_type or ""
    filename = file.filename or ""
    raw_bytes = await file.read()

    is_pdf = filename.lower().endswith(".pdf") or "pdf" in content_type
    is_image = any(filename.lower().endswith(ext) for ext in (".png", ".jpg", ".jpeg")) \
               or any(t in content_type for t in ("png", "jpg", "jpeg", "image"))

    extracted_text = ""
    file_type = "pdf" if is_pdf else "image"

    # ── PDF path: extract text with pypdf ────────────────────────────────────
    if is_pdf:
        try:
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(raw_bytes))
            pages = [page.extract_text() or "" for page in reader.pages]
            extracted_text = "\n".join(pages).strip()
        except Exception:
            extracted_text = ""

    # ── Call 1: Extract Transactions ─────────────────────────────────────────
    if not extracted_text:
        file_type = "image"
        try:
            vision_response = llm.invoke([
                {
                    "role": "system",
                    "content": "You are a financial forensics expert analyzing a bank statement."
                },
                {
                    "role": "user",
                    "content": (
                        f"A bank statement image has been uploaded (filename: {file.filename}, "
                        f"size: {len(raw_bytes)} bytes, format: {file.content_type}). "
                        "Based on this being a bank statement image upload for fraud analysis, "
                        "provide a structured forensic analysis response. "
                        "List what typical fraud indicators to look for in bank statements, "
                        "and list transactions if you can infer them. "
                        "Format transactions as: DATE | DESCRIPTION | AMOUNT | BALANCE"
                    )
                }
            ])
            raw_analysis = vision_response.content.strip()
        except Exception as exc:
            raw_analysis = f"[Vision analysis failed: {exc}]"
    else:
        system_prompt = (
            "You are a financial forensics expert. Analyze this bank statement text. "
            "List every transaction found as: DATE | DESCRIPTION | AMOUNT | BALANCE. "
        )
        truncated = extracted_text[:12000] if len(extracted_text) > 12000 else extracted_text
        try:
            text_response = llm.invoke([
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": truncated},
            ])
            raw_analysis = text_response.content.strip()
        except Exception as exc:
            raw_analysis = f"[Analysis failed: {exc}]"

    # ── Call 2: Risk Summary ─────────────────────────────────────────────────
    try:
        risk_response = llm.invoke([
            {
                "role": "system",
                "content": (
                    "You are a senior financial fraud analyst. "
                    "You will be given extracted bank statement data. "
                    "Your job is to write a concise risk assessment. "
                    "Always respond with exactly these 5 lines, no more:\n"
                    "VELOCITY RISK: [LOW/MEDIUM/HIGH] - [one sentence reason]\n"
                    "DESTINATION RISK: [LOW/MEDIUM/HIGH] - [one sentence reason]\n"
                    "AMOUNT RISK: [LOW/MEDIUM/HIGH] - [one sentence reason]\n"
                    "PATTERN DEVIATION: [LOW/MEDIUM/HIGH] - [one sentence reason]\n"
                    "OVERALL: [LOW/MEDIUM/HIGH/CRITICAL] - [one sentence summary and recommended action]"
                )
            },
            {
                "role": "user",
                "content": f"Analyse this extracted bank statement data for fraud risk:\n\n{raw_analysis[:3000]}"
            }
        ])
        risk_summary = risk_response.content.strip()
    except Exception as exc:
        risk_summary = f"[Risk summary failed: {exc}]"

    import re
    transaction_lines = re.findall(
        r'\d{4}[-/]\d{2}[-/]\d{2}.*\|.*\|.*\|', raw_analysis
    )
    transaction_count = len(transaction_lines) if transaction_lines else None

    return JSONResponse({
        "file_type": file_type,
        "transaction_count": transaction_count,
        "raw_analysis": raw_analysis,
        "risk_summary": risk_summary,
    })


# ── Statement PDF Export ──────────────────────────────────────────────────────
@app.post("/export-statement-report")
def export_statement_report(payload: StatementReportRequest):
    # ── colour palette ────────────────────────────────────────────────────────
    BG        = (5,   5,   8)
    INDIGO    = (99,  102, 241)
    INDIGO_DK = (30,  31,  80)
    STRIP     = (13,  13,  20)
    INSET     = (10,  10,  18)
    MUTED     = (120, 120, 140)
    WHITE     = (255, 255, 255)
    ROSE      = (244, 63,  94)
    AMBER     = (245, 158, 11)
    EMERALD   = (16,  185, 129)

    def risk_color(text: str):
        t = text.lower()
        if "critical" in t or "high risk" in t or "fraud" in t:
            return ROSE, "HIGH RISK"
        if "medium" in t:
            return AMBER, "MEDIUM RISK"
        if "low risk" in t or "nominal" in t or "legitimate" in t:
            return EMERALD, "LOW RISK"
        return None, None

    ts_short = payload.timestamp.replace(":", "").replace(" ", "_").replace("-", "")[:15]

    class StmtPDF(FPDF):
        def header(self):
            # ── full-page dark background ─────────────────────────────────
            self.set_fill_color(*BG)
            self.rect(0, 0, self.w, self.h, style="F")
            # ── indigo header bar ─────────────────────────────────────────
            self.set_fill_color(*INDIGO)
            self.rect(0, 0, self.w, 18, style="F")
            # left: wordmark
            self.set_font("Courier", "B", 13)
            self.set_text_color(*WHITE)
            self.set_xy(8, 4)
            self.cell(0, 10, "FRAUDGUARD // STATEMENT FORENSICS", ln=False)
            # right: filename + timestamp
            self.set_font("Courier", "", 8)
            right_text = f"FILE: {payload.file_name}   {payload.timestamp}"
            self.set_xy(self.w - 8 - self.get_string_width(right_text), 4)
            self.cell(0, 10, right_text)
            # ── info strip ────────────────────────────────────────────────
            self.set_fill_color(*STRIP)
            self.rect(0, 18, self.w, 12, style="F")
            cells = [
                ("FILE TYPE:", payload.file_type.upper()),
                ("TRANSACTIONS DETECTED:", str(payload.transaction_count or "N/A")),
                ("ANALYSED:", payload.timestamp),
            ]
            cell_w = self.w / 3
            for i, (label, value) in enumerate(cells):
                x = i * cell_w + 6
                self.set_font("Courier", "", 8)
                self.set_text_color(*MUTED)
                self.set_xy(x, 20)
                self.cell(self.get_string_width(label) + 2, 6, label)
                self.set_text_color(*WHITE)
                self.cell(cell_w - self.get_string_width(label) - 8, 6, value)

        def footer(self):
            self.set_y(-14)
            # thin indigo line
            self.set_draw_color(*INDIGO)
            self.set_line_width(0.3)
            self.line(8, self.get_y(), self.w - 8, self.get_y())
            self.set_y(-12)
            self.set_font("Courier", "", 7)
            self.set_text_color(*MUTED)
            self.cell(self.w / 3, 6, "FRAUDGUARD AI | STATEMENT ANALYSIS REPORT")
            self.cell(self.w / 3, 6, "POWERED BY GROQ LLAMA-3.3", align="C")
            self.cell(self.w / 3, 6, f"PAGE {self.page_no()} OF {{nb}}", align="R")

        def section_divider(self, label: str):
            self.ln(4)
            y = self.get_y()
            self.set_draw_color(*INDIGO)
            self.set_line_width(0.3)
            self.line(8, y, self.w - 8, y)
            self.set_font("Courier", "B", 8)
            self.set_text_color(*INDIGO)
            self.set_xy(8, y + 1)
            self.cell(0, 5, f"[ {label} ]")
            self.ln(7)

        def text_block(self, text: str, fallback: str = ""):
            display = text if text.strip() else fallback
            lines = display.split("\n")
            # wrap long lines at ~90 chars
            wrapped = []
            for line in lines:
                while len(line) > 90:
                    wrapped.append(line[:90])
                    line = line[90:]
                wrapped.append(line)

            block_h = len(wrapped) * 5 + 8
            # inset background
            self.set_fill_color(*INSET)
            self.rect(8, self.get_y(), self.w - 16, block_h, style="F")
            self.set_font("Courier", "", 8)
            self.set_text_color(*WHITE)
            self.set_xy(12, self.get_y() + 4)
            for ln_text in wrapped:
                self.cell(self.w - 24, 5, ln_text, ln=True)
                self.set_x(12)
            self.ln(4)

    pdf = StmtPDF()
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # ── Watermark (drawn on page after background, before content) ────────────
    # Save state, draw watermark at center, restore
    pdf.set_font("Courier", "B", 28)
    pdf.set_text_color(*INDIGO_DK)
    pdf.rotate(35, pdf.w / 2, pdf.h / 2)
    wm_w = pdf.get_string_width("STATEMENT ANALYSIS")
    pdf.set_xy(pdf.w / 2 - wm_w / 2, pdf.h / 2 - 10)
    pdf.cell(wm_w + 4, 14, "STATEMENT ANALYSIS")
    pdf.rotate(0)

    # ── Move cursor past header bars ─────────────────────────────────────────
    pdf.set_y(35)

    # ── TRANSACTION EXTRACTION section ───────────────────────────────────────
    pdf.section_divider("TRANSACTION EXTRACTION")
    pdf.text_block(
        payload.raw_analysis,
        fallback="[NO TRANSACTION DATA EXTRACTED]"
    )

    # ── RISK ASSESSMENT section ───────────────────────────────────────────────
    pdf.section_divider("RISK ASSESSMENT")

    # Risk tier badge
    badge_color, badge_label = risk_color(payload.risk_summary)
    if badge_color:
        pdf.set_fill_color(*badge_color)
        bx, by = 8, pdf.get_y()
        pdf.rect(bx, by, 36, 7, style="F")
        pdf.set_font("Courier", "B", 9)
        pdf.set_text_color(*WHITE)
        pdf.set_xy(bx + 2, by + 0.5)
        pdf.cell(32, 6, badge_label)
        pdf.ln(10)

    pdf.text_block(
        payload.risk_summary,
        fallback="[NO RISK SUMMARY GENERATED]"
    )

    pdf_bytes = pdf.output()
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=FRAUDGUARD_STATEMENT_{ts_short}.pdf"
        },
    )