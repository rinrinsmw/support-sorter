# app.py: Support Sorter dashboard in Streamlit
# Run it with:  python -m streamlit run app.py
#
# Remember: Streamlit reruns this whole file from top to bottom every time
# someone changes a filter. Caching (below) keeps that fast.

import streamlit as st
import pandas as pd
import gspread

SHEET_ID = "13ytynvOcmhLa5RzkA5zpEHwwX97kbykGwjDgUf6KV7w"
TAB = "dashboard_data"   # the tab build_dashboard_data.py makes (one row per ticket per version)

# Page settings: browser-tab title and a wide layout so the charts have room.
st.set_page_config(page_title="Support Sorter", layout="wide")


# ---------- 1. Load the data ----------
# @st.cache_data remembers the result, so the sheet is read at most once
# every 600 seconds (10 min) instead of on every click.
@st.cache_data(ttl=600)
def load():
    gc = gspread.service_account(filename="service_account.json")  # same login as sorter.py
    ws = gc.open_by_key(SHEET_ID).worksheet(TAB)                     # open the tab by name
    df = pd.DataFrame(ws.get_all_records())                          # header row becomes column names
    # Make sure the 0/1 columns are numbers, so averages work.
    for col in ["category_correct", "urgency_correct", "false_high"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    return df

data = load()

# A button to force a fresh read (it clears the cache, then reruns).
if st.sidebar.button("Refresh data"):
    st.cache_data.clear()
    st.rerun()


# ---------- 2. Header ----------
st.title("Support Sorter")
st.caption("An LLM sorts support tickets by category and urgency. "
           "Each version is scored against 50 hand-labeled reference tickets.")


# ---------- 3. Sidebar filter ----------
# st.selectbox draws a dropdown, and `version` holds whatever the user picked.
versions = sorted(data["version"].unique())                  # e.g. ['v1', 'v2', 'v3']
version = st.sidebar.selectbox("Version", versions, index=len(versions) - 1)  # default: newest
view = data[data["version"] == version]                       # only that version's rows


# ---------- 4. Headline numbers for the chosen version ----------
# The mean of a 0/1 column is the share of 1s, which is the accuracy.
c1, c2, c3, c4 = st.columns(4)   # four boxes side by side
c1.metric("Tickets", len(view))
c2.metric("Category accuracy", f"{view['category_correct'].mean():.0%}")
c3.metric("Urgency accuracy", f"{view['urgency_correct'].mean():.0%}")
c4.metric("False High", int(view["false_high"].sum()),
          help="Tickets the model called High that weren't really High")


# ---------- 5. Accuracy by version (all versions) ----------
st.subheader("Accuracy by version")
acc = data.groupby("version")[["category_correct", "urgency_correct"]].mean()
st.bar_chart(acc, stack=False)   # stack=False puts the bars side by side


# ---------- 6. Error types for the chosen version ----------
left, right = st.columns(2)

with left:
    st.subheader(f"Error types in {version}")
    # value_counts() counts how many rows have each error_type (OK, WRONG_URGENCY, ...)
    errors = view["error_type"].value_counts()
    st.bar_chart(errors)

with right:
    st.subheader(f"Urgency: model vs answer key ({version})")
    # crosstab is a confusion matrix: rows = the true label, columns = what the model said.
    # The diagonal is correct, and everything else is a miss.
    matrix = pd.crosstab(view["true_urgency"], view["pred_urgency"])
    st.dataframe(matrix)


# ---------- 7. The misses, so you can review them ----------
st.subheader(f"Tickets {version} got wrong")
misses = view[view["error_type"] != "OK"]
if misses.empty:
    st.success("No misses in this version! 🎉")
else:
    st.dataframe(
        misses[["ticket_id", "true_category", "pred_category",
                "true_urgency", "pred_urgency", "confidence", "error_type"]],
        hide_index=True,
    )


# ---------- 8. Full data (folded away) ----------
with st.expander("See all rows for this version"):
    st.dataframe(view, hide_index=True)
