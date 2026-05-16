# FraudGuard AI

Real-time financial transaction fraud detection and AI-powered forensic statement analysis dashboard.

## About the Project
FraudGuard AI is an advanced, high-fidelity web application designed to detect financial fraud using a hybrid approach of classical machine learning and generative AI. It features a cyberpunk-themed, interactive dashboard that allows users to seamlessly analyze structured transactions in real-time or upload unstructured bank statements (PDFs and Images) for forensic risk assessment. 

Key Features:
- **Real-Time Transaction Scoring:** Instantly evaluate structured transaction payloads using a pre-trained XGBoost model.
- **Statement Forensics:** Upload bank statements (PDF or Image) to automatically extract transactions and receive a concise, 5-point AI risk summary.
- **3D Knowledge Graph:** Visualize sender/receiver relationships and risk flows via an interactive 3D Force-Directed Graph.
- **Dynamic Cyberpunk UI:** A visually stunning interface with interactive dials, meters, terminal outputs, and animated visualizations built with Vanilla HTML/CSS/JS and Chart.js.

## System Architecture

- **Frontend:** Vanilla HTML5, CSS3, and JavaScript. Uses `Chart.js` for transaction volume and running balance charting. Uses `3d-force-graph` for relationship mapping.
- **Backend:** Python-based `FastAPI` server managing asynchronous REST endpoints and serving static assets.
- **Machine Learning Layer:** Pre-trained `XGBoost` classifier to run inference and calculate exact fraud probabilities.
- **AI Forensics Layer:** Utilizes `LangChain` and the `Groq` API (powering `Llama-3.3-70b-versatile` and vision models) to perform intelligent extraction, translation, and structured summarization.
- **PDF Processing:** `pypdf` integration for fast and lightweight text extraction from PDF statements, and `FPDF` for generating structured export reports.

## System Working

The application is split into two primary workflows:

### 1. Transaction Prediction (`/predict`)
A user enters structured transaction metadata (e.g. Amount, Recency, Account Balances, Transaction Type) into the side panel. 
1. The frontend constructs a JSON payload and sends it to the backend.
2. The FastAPI server processes the input, applies feature engineering, and queries the `XGBoost` model for a probability score.
3. The server then passes the transaction data and score to a `Groq` LLM to generate a natural-language "analyst summary" explaining the model's decision.
4. The frontend receives the response and dynamically updates the UI meters, terminal logs, and 3D graph.

### 2. Statement Forensics (`/analyse-statement`)
A user uploads a raw bank statement (PDF or Image) via drag-and-drop.
1. The backend parses the file. If it's a PDF, `pypdf` extracts the raw text. If it's an image, a vision-capable LLM prompt extracts the context.
2. A **Two-Call AI Pipeline** is executed:
   - *Call 1 (Extraction):* The LLM identifies and formats all transactions into a structured `DATE | DESCRIPTION | AMOUNT | BALANCE` list.
   - *Call 2 (Risk Assessment):* The raw transaction list is passed to a second LLM prompt to generate a highly structured 5-line risk assessment covering Velocity Risk, Destination Risk, Amount Risk, and Pattern Deviation.
3. The frontend displays the parsed transaction table, builds volume/balance charts, and typewrites the AI's forensic verdict on the dashboard.

## File Architecture

```text
fraudguard/
├── app/
│   ├── main.py              # FastAPI core: routing, ML inference, and LLM forensics logic
│   └── static/
│       ├── index.html       # Web UI (Cyberpunk dashboard structure and styling)
│       └── app.js           # Frontend logic, API wiring, and UI interactivity
├── models/
│   └── xboost_model.pkl     # Pre-trained XGBoost model for transaction predictions
├── preprocessing/
│   ├── prepare_data.py      # Retraining: Step 1 — CSV to Parquet conversion
│   ├── features.py          # Retraining: Step 2 — Feature engineering logic
│   └── split_by_step.py     # Retraining: Step 3 — Train/validation/test splitting
├── train.py                 # Script to retrain the XGBoost model from scratch
├── requirements.txt         # Python dependencies
├── .env.example             # Example environment variables (needs Groq API Key)
└── README.md                # Project documentation
```

## Commands to Start Working

### 1. Install Dependencies
Ensure you have Python 3.9+ installed. Set up your virtual environment, then run:
```bash
pip install -r requirements.txt
```
*(Alternatively, you can install the packages directly)*:
```bash
pip install fastapi uvicorn pydantic joblib pandas numpy scikit-learn xgboost langchain-groq python-dotenv fpdf2 pypdf
```

### 2. Configure Environment Variables
Copy the example environment file and add your Groq API key:
```bash
cp .env.example .env
```
Open `.env` and assign your key (get one for free at [console.groq.com](https://console.groq.com/keys)):
```env
GROQ_API_KEY=gsk_your_api_key_here
```

### 3. Start the Server
Launch the FastAPI development server:
```bash
uvicorn app.main:app --reload
```

### 4. Open the Dashboard
Navigate to the following address in your web browser:
```text
http://localhost:8000
```
*(You can also access the auto-generated Swagger API documentation at `http://localhost:8000/docs`)*
