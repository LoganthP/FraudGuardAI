import re
import os

main_py_path = 'c:/Users/logan/Downloads/fraudguard/app/main.py'
index_html_path = 'c:/Users/logan/Downloads/fraudguard/app/static/index.html'

# ==========================================
# FIX app/main.py
# ==========================================
with open(main_py_path, 'r', encoding='utf-8') as f:
    main_text = f.read()

# Replace the analyse_statement function
start_marker = '@app.post("/analyse-statement")'
end_marker = '# ── Statement PDF Export ──────────────────────────────────────────────────────'

start_idx = main_text.find(start_marker)
end_idx = main_text.find(end_marker)

new_analyse_statement = """@app.post("/analyse-statement")
async def analyse_statement(file: UploadFile = File(...)):
    content_type = file.content_type or ""
    filename = file.filename or ""
    raw_bytes = await file.read()

    is_pdf = filename.lower().endswith(".pdf") or "pdf" in content_type
    is_image = any(filename.lower().endswith(ext) for ext in (".png", ".jpg", ".jpeg")) \\
               or any(t in content_type for t in ("png", "jpg", "jpeg", "image"))

    extracted_text = ""
    file_type = "pdf" if is_pdf else "image"

    # ── PDF path: extract text with pypdf ────────────────────────────────────
    if is_pdf:
        try:
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(raw_bytes))
            pages = [page.extract_text() or "" for page in reader.pages]
            extracted_text = "\\n".join(pages).strip()
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
                    "Always respond with exactly these 5 lines, no more:\\n"
                    "VELOCITY RISK: [LOW/MEDIUM/HIGH] - [one sentence reason]\\n"
                    "DESTINATION RISK: [LOW/MEDIUM/HIGH] - [one sentence reason]\\n"
                    "AMOUNT RISK: [LOW/MEDIUM/HIGH] - [one sentence reason]\\n"
                    "PATTERN DEVIATION: [LOW/MEDIUM/HIGH] - [one sentence reason]\\n"
                    "OVERALL: [LOW/MEDIUM/HIGH/CRITICAL] - [one sentence summary and recommended action]"
                )
            },
            {
                "role": "user",
                "content": f"Analyse this extracted bank statement data for fraud risk:\\n\\n{raw_analysis[:3000]}"
            }
        ])
        risk_summary = risk_response.content.strip()
    except Exception as exc:
        risk_summary = f"[Risk summary failed: {exc}]"

    import re
    transaction_lines = re.findall(
        r'\\d{4}[-/]\\d{2}[-/]\\d{2}.*\\|.*\\|.*\\|', raw_analysis
    )
    transaction_count = len(transaction_lines) if transaction_lines else None

    return JSONResponse({
        "file_type": file_type,
        "transaction_count": transaction_count,
        "raw_analysis": raw_analysis,
        "risk_summary": risk_summary,
    })


"""

main_text = main_text[:start_idx] + new_analyse_statement + main_text[end_idx:]

with open(main_py_path, 'w', encoding='utf-8') as f:
    f.write(main_text)


# ==========================================
# FIX index.html
# ==========================================
with open(index_html_path, 'r', encoding='utf-8') as f:
    html_text = f.read()

# Replace buildAiCard completely
start_marker_ai = '// Card 7 &mdash; AI summary (typewriter)'
end_marker_ai = '// â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€'

start_idx_ai = html_text.find(start_marker_ai)
end_idx_ai = html_text.find(end_marker_ai, start_idx_ai)

new_build_ai_card = """// Card 7 &mdash; AI summary (typewriter)
function buildAiCard(risk) {
  const wrap = document.createElement('div');
  wrap.innerHTML = `<div class="stmt-card">
    <div class="stmt-ai-header">GROQ &middot; LLAMA-3.3 &middot; STATEMENT FORENSICS</div>
    <div class="stmt-ai-body" id="stmtAiBody"></div>
  </div>`;
  // typewriter after DOM insert
  requestAnimationFrame(() => {
    const el = document.getElementById('stmtAiBody');
    if (!el) return;
    
    const summary = (risk && risk.trim().length > 0) 
        ? risk.trim() 
        : '[RISK SUMMARY UNAVAILABLE — MODEL DID NOT RETURN ASSESSMENT]';
        
    if (summary === '[RISK SUMMARY UNAVAILABLE — MODEL DID NOT RETURN ASSESSMENT]') {
        el.className = 'stmt-ai-body risk-summary-fallback';
    } else {
        el.className = 'stmt-ai-body';
    }
    
    function typewriter(element, text, speed = 14) {
        element.textContent = '';
        let i = 0;
        const cursor = '\\u258C'; // blinking block cursor
        const interval = setInterval(() => {
            if (i < text.length) {
                element.textContent = text.slice(0, i + 1) + cursor;
                i++;
            } else {
                element.textContent = text; // final state, no cursor
                clearInterval(interval);
            }
        }, speed);
    }
    
    typewriter(el, summary);
  });
  return wrap;
}

"""

html_text = html_text[:start_idx_ai] + new_build_ai_card + html_text[end_idx_ai:]

# Add CSS class
css_marker = '</style>'
css_injection = """
    .risk-summary-fallback {
        color: rgba(255, 255, 255, 0.35);
        font-size: 13px;
        font-family: 'Inter', sans-serif;
        font-weight: 300;
        background: none !important;
        border: none !important;
        outline: none !important;
        padding: 0;
    }
</style>"""
if '.risk-summary-fallback' not in html_text:
    html_text = html_text.replace(css_marker, css_injection)

with open(index_html_path, 'w', encoding='utf-8') as f:
    f.write(html_text)

print("Done index.html and main.py.")
