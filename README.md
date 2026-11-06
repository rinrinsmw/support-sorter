# Support Sorter

A Python LLM support-ticket classifier with versioned evaluation, urgent-ticket routing, and dashboards. It assigns one of eight categories and an urgency level of `High`, `Medium`, or `Low`.

**[Live Streamlit dashboard](https://support-sorter-gg2sa6uwnmw9tkitxgyay2.streamlit.app)** · **[Tableau Public dashboard](https://public.tableau.com/app/profile/irina.putri/viz/SupportSorter/Dashboard)**

[Source repository](https://github.com/rinrinsmw/support-sorter)

## How it works

```text
Google Sheets tickets -> Mask common personal identifiers -> LLM + guidelines
                                                           |
                                              Normalize + check output
                                                           |
                       Version-specific results <----------+--> High urgency
                                |                                  |
                       Calibrated reference key           Apps Script doPost
                                |                                  |
                       Dashboard data                     urgent_queue tab
                                |
                       Streamlit + Tableau

POST /classify -> Same v3 guideline and output checks -> JSON response
```

Urgent routing belongs to the batch sorter. The API returns a classification without sending a webhook.

## What it does

- Classifies tickets as `account_app`, `damaged_item`, `delivery_problem`, `needs_human`, `order_change`, `order_tracking`, `product_question`, or `return_refund`.
- Returns `high` or `low` confidence and an `english_text` translation for non-English tickets in the same classification call.
- Uses versioned guidelines, normalizes output, and checks category, urgency, and confidence values.
- Preserves the original hand-labeled reference columns. Predictions use version-specific columns such as `v3_category` and `v3_urgency`.
- Sends High-urgency tickets to a Google Apps Script webhook that writes to `urgent_queue`. Three attempts use 2-second and 4-second waits plus jitter, then log `WEBHOOK_FAILED` on failure.
- Shows selected-version KPIs, category and urgency accuracy by version, category-level accuracy, and error-type counts.

The dashboard uses Streamlit, pandas, matplotlib, and gspread, without Altair. The API uses FastAPI and Scalar. LLM calls use the OpenAI Python SDK through OpenRouter.

## Evaluation results

Accuracy against the current round-2 calibrated reference key:

| Guideline version | Tickets | Category accuracy | Urgency accuracy |
| --- | ---: | ---: | ---: |
| v1 | 50 | 88% | 76% |
| v2 | 50 | 100% | 88% |
| v3 | 50 | 98% | 96% |

All versions use the **same 50 tickets**, not 150 distinct tickets. The reference key was calibrated while reviewing model errors, especially during v2 development. These are in-sample development results, not held-out test performance. They do not establish that v2 is objectively the best version. No holdout evaluation has been run.

Reliability depends on more than model choice: clear category boundaries, reference-label review, output checks, webhook retries, and visible error analysis all matter. A high confidence label is a model output, not a calibrated probability.

## Repository structure

```text
api.py                    FastAPI classification endpoint
app.py                    Streamlit quality dashboard
sorter.py                 Batch classification, scoring, and urgent routing
build_dashboard_data.py   Reshape sheet results and publish dashboard data
guideline_v2.md           Version 2 classification instructions
guideline_v3.md           Version 3 classification instructions
results_v1.csv            Saved version 1 results
results_v2.csv            Saved version 2 results
results_v3.csv            Saved version 3 results
dashboard_data.csv        One row per ticket per version
requirements.txt          Dashboard dependencies
requirements-dev.txt      Dashboard + classifier and API dependencies
.streamlit/config.toml    Dashboard theme
```

## Run locally

Use Python 3.12, the locally tested version. From the project directory, create an isolated environment:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
```

The activation command above is for macOS and Linux. For a dashboard-only installation, use `python -m pip install -r requirements.txt` instead.

### Configure credentials and data

For the API and sorter, create a local `.env` file:

```dotenv
OPENROUTER_API_KEY=your_openrouter_api_key
WEBHOOK_URL=your_apps_script_web_app_url
```

`WEBHOOK_URL` is needed for batch urgent-ticket routing, not for the API. Keep `guideline_v3.md` in the working directory.

For local Google Sheets access, place `service_account.json` in the project root. Share the Google Sheet with the service account's `client_email`. Grant write access if running either batch script.

For Streamlit Cloud, configure the service-account credentials privately in app secrets under `[gcp_service_account]`. The dashboard reads `st.secrets["gcp_service_account"]`, with `service_account.json` as its local fallback.

**Never commit `.env`, `service_account.json`, or `.streamlit/secrets.toml`.** Keep them ignored. Do not place credentials in the README or public dashboard data.

The sheet identifiers are code constants, not environment variables. For your own data, update `SHEET_ID` in `app.py`, `sorter.py`, and `build_dashboard_data.py`, and the source worksheet `GID` in the two batch scripts. The source CSV export must be readable by pandas.

Before starting the dashboard, prepare the `dashboard_data` sheet tab. The builder expects these source columns:

- `ticket_id`, `final_category`, and `Urgency`.
- `calibration_category_1`, `calibration_category_2`, `calibration_urgency_1`, and `calibration_urgency_2`. Keep these headers even when cells are blank.
- Paired prediction columns such as `v1_category` and `v1_urgency` for each version. Confidence and error columns are optional for the builder.

With that source sheet and service-account access configured, run:

```bash
python build_dashboard_data.py
```

This writes `dashboard_data.csv` and creates or **clears and replaces** the `dashboard_data` tab. It does not generate predictions. The dashboard reads the sheet tab, not the local CSV.

### Start the dashboard

```bash
python -m streamlit run app.py
```

Select versions for the charts and a single version for the KPIs. Sheets are read on every rerun. The 600-second cache covers JSON-to-DataFrame conversion only, not sheet reads.

### Start the API

```bash
python -m uvicorn api:app --reload
```

- `GET /health` reports service status and version information.
- `POST /classify` accepts `{"text": "I cannot access my account after resetting my password."}`.
- The response contains `category`, `urgency`, `confidence`, `english_text`, and `version`.
- Scalar documentation is available at `http://127.0.0.1:8000/scalar`.
- `422` indicates invalid caller input, including empty text, text over 5,000 characters, or invalid request JSON. `502` indicates a model-call or model-output validation failure.

### Batch sorter safety

Before running `python sorter.py`, review `GUIDELINE_FILE`, `VERSION`, `TEST_TICKET`, the sheet constants, and the webhook destination. The current source has `TEST_TICKET` set to one ticket. That mode skips main-sheet writes and result CSV output, but **can still send a webhook**.

A full run requires `TEST_TICKET = None`, the source `message_text` column, and the matching version-specific output headers in the sheet. A full run writes a results CSV and that version's prediction columns, leaving reference columns intact.
