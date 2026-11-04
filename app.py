# app.py: Support Sorter dashboard in Streamlit
# Run:  python -m streamlit run app.py

import json
import os

import gspread
import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

SHEET_ID = "13ytynvOcmhLa5RzkA5zpEHwwX97kbykGwjDgUf6KV7w"
TAB = "dashboard_data"

st.set_page_config(page_title="Support Sorter", layout="wide")


def gspread_client():
    """Cloud: [gcp_service_account] in App settings → Secrets. Local: service_account.json."""
    try:
        if "gcp_service_account" in st.secrets:
            return gspread.service_account_from_dict(dict(st.secrets["gcp_service_account"]))
    except Exception:
        # No secrets file (local) or secrets not configured yet (cloud)
        pass

    if os.path.isfile("service_account.json"):
        return gspread.service_account(filename="service_account.json")

    return None


def fetch_records():
    gc = gspread_client()
    if gc is None:
        return None
    ws = gc.open_by_key(SHEET_ID).worksheet(TAB)
    return ws.get_all_records()


@st.cache_data(ttl=600)
def records_to_dataframe(records_json: str):
    """Cache sheet rows only — no st.secrets or Streamlit UI calls here."""
    df = pd.DataFrame(json.loads(records_json))
    for col in ["category_correct", "urgency_correct", "false_high"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    if "version" in df.columns:
        df["version"] = df["version"].astype(str).str.strip()
    return df


def show_bar_df(df: pd.DataFrame, ylim_max: float | None = None):
    """Matplotlib bars — avoids st.bar_chart → Altair (broken on Python 3.14)."""
    fig, ax = plt.subplots(figsize=(8, 3.2))
    df.plot(kind="bar", ax=ax, color=["#444444", "#999999"], rot=0, legend=True)
    ax.set_xlabel("")
    if ylim_max is not None:
        ax.set_ylim(0, ylim_max)
    ax.grid(axis="y", linestyle="--", alpha=0.35)
    fig.tight_layout()
    st.pyplot(fig, clear_figure=True)


def show_bar_series(series: pd.Series):
    fig, ax = plt.subplots(figsize=(8, 3.2))
    series.sort_values().plot(kind="barh", ax=ax, color="#666666")
    ax.set_xlabel("Count")
    fig.tight_layout()
    st.pyplot(fig, clear_figure=True)


st.sidebar.markdown("**Filters**")

try:
    raw = fetch_records()
except gspread.exceptions.WorksheetNotFound:
    st.error(f"Sheet tab `{TAB}` not found. Run `build_dashboard_data.py` once to create it.")
    st.stop()
except Exception as e:
    st.error(f"Could not read Google Sheet: {type(e).__name__}: {e}")
    st.stop()

if raw is None:
    st.error(
        "Google credentials not found.\n\n"
        "**Streamlit Cloud:** **Manage app → Settings → Secrets** — paste the full "
        "`[gcp_service_account]` block from your local `.streamlit/secrets.toml` "
        "(not the repo; Cloud does not read that file).\n\n"
        "**Local:** add `service_account.json` in the project root."
    )
    st.stop()

try:
    data = records_to_dataframe(json.dumps(raw, sort_keys=True))
except Exception as e:
    st.error(f"Could not load sheet tab `{TAB}`: {type(e).__name__}: {e}")
    st.stop()

st.title("Support Sorter")
st.caption(
    "An LLM sorts support tickets by category and urgency. "
    "Each version is scored against 50 hand-labeled reference tickets."
)

versions = sorted(data["version"].unique(), key=lambda v: int(str(v)[1:]))
version = st.sidebar.selectbox("Version", versions, index=len(versions) - 1)
if st.sidebar.button("Refresh data"):
    st.cache_data.clear()
    st.rerun()
view = data[data["version"] == version]

n_tickets = int(len(view))
cat_pct = float(view["category_correct"].mean()) if n_tickets else 0.0
urg_pct = float(view["urgency_correct"].mean()) if n_tickets else 0.0
n_false_high = int(view["false_high"].sum()) if n_tickets else 0

c1, c2, c3, c4 = st.columns(4)
for col, label, value in (
    (c1, "Tickets", f"{n_tickets:,}"),
    (c2, "Category accuracy", f"{cat_pct:.0%}"),
    (c3, "Urgency accuracy", f"{urg_pct:.0%}"),
    (c4, "False High", f"{n_false_high:,}"),
):
    col.markdown(
        f"<div style='padding:0.75rem 1rem;border:1px solid #ddd;border-radius:6px;"
        f"background:#fff'><div style='font-size:0.75rem;color:#666'>{label}</div>"
        f"<div style='font-size:1.6rem;font-weight:700'>{value}</div></div>",
        unsafe_allow_html=True,
    )

st.subheader("Accuracy by version")
acc = (
    data.groupby("version")[["category_correct", "urgency_correct"]]
    .mean()
    .astype(float)
)
show_bar_df(acc, ylim_max=1.0)

left, right = st.columns(2)
with left:
    st.subheader(f"Error types in {version}")
    show_bar_series(view["error_type"].value_counts().astype(float))
with right:
    st.subheader(f"Urgency: model vs answer key ({version})")
    st.dataframe(pd.crosstab(view["true_urgency"], view["pred_urgency"]))

st.subheader(f"Tickets {version} got wrong")
misses = view[view["error_type"] != "OK"]
if misses.empty:
    st.success("No misses in this version!")
else:
    st.dataframe(
        misses[
            [
                "ticket_id",
                "true_category",
                "pred_category",
                "true_urgency",
                "pred_urgency",
                "confidence",
                "error_type",
            ]
        ],
        hide_index=True,
    )

with st.expander("See all rows for this version"):
    st.dataframe(view, hide_index=True)
