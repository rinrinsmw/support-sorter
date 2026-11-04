# app.py: Support Sorter dashboard in Streamlit
# Run:  python -m streamlit run app.py

import os

import gspread
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
def records_to_dataframe(records: tuple[tuple[str, str], ...]):
    """Cache sheet rows only — no st.secrets or Streamlit UI calls here."""
    df = pd.DataFrame([dict(row) for row in records])
    for col in ["category_correct", "urgency_correct", "false_high"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    if "version" in df.columns:
        df["version"] = df["version"].astype(str).str.strip()
    return df


def records_cache_key(records: list) -> tuple[tuple[str, str], ...]:
    if not records:
        return ()
    keys = list(records[0].keys())
    return tuple(tuple(str(row.get(k, "")) for k in keys) for row in records)


st.sidebar.markdown("**Filters**")

raw = fetch_records()
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
    data = records_to_dataframe(records_cache_key(raw))
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

c1, c2, c3, c4 = st.columns(4)
c1.metric("Tickets", len(view))
c2.metric("Category accuracy", f"{view['category_correct'].mean():.0%}")
c3.metric("Urgency accuracy", f"{view['urgency_correct'].mean():.0%}")
c4.metric(
    "False High",
    int(view["false_high"].sum()),
    help="Tickets the model called High that weren't really High",
)

st.subheader("Accuracy by version")
acc = data.groupby("version")[["category_correct", "urgency_correct"]].mean()
st.bar_chart(acc, stack=False)

left, right = st.columns(2)
with left:
    st.subheader(f"Error types in {version}")
    st.bar_chart(view["error_type"].value_counts())
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
