# app.py: Support Sorter — Quality by Version (Streamlit)
# Run:  python -m streamlit run app.py
# Theme: copy config.toml → .streamlit/config.toml (never secrets.toml)
#
# What changed vs the purple “card chrome” draft (for learning):
# - Dropped dark charcoal banner / decorative metric chrome that fought dark-mode
#   inherited text (white-on-light = unreadable). Theme now comes from config.toml
#   base="light" + near-charcoal textColor, with only light CSS backups.
# - Views match the Tableau essentials: KPI pair for one version, two accuracy
#   bar charts by version, accuracy-by-category grouped bars, stacked error types.
# - Version colours are stable Tableau-like (blue/orange/red), not purple fills.
# - Removed ticket table, confusion matrix, expander, False High / Tickets cards.

import html
import json
import os

import gspread
import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

SHEET_ID = "13ytynvOcmhLa5RzkA5zpEHwwX97kbykGwjDgUf6KV7w"
TAB = "dashboard_data"

# Stable version colours (Tableau screenshot). Extra versions cycle neutrals.
VERSION_COLORS = {
    "v1": "#4E79A7",
    "v2": "#F28E2B",
    "v3": "#E15759",
}
FALLBACK_COLORS = ["#76B7B2", "#59A14F", "#EDC948", "#B07AA1", "#FF9DA7", "#9C755F"]
CHARCOAL = "#1F2937"
GRID = "#D1D5DB"
FACE = "#FFFFFF"

st.set_page_config(page_title="Support Sorter: Quality by Version", layout="wide")

# Modest CSS backup if config.toml is missing. Forces dark text on light surfaces
# so Streamlit widgets / dataframe labels stay readable even under OS dark mode.
st.markdown(
    """
    <style>
      /* Prefer explicit light surfaces + dark text (high contrast). */
      [data-testid="stAppViewContainer"] {
        background: #FFFFFF;
        color: #1F2937;
      }
      [data-testid="stHeader"] { background: transparent; }
      [data-testid="stSidebar"] {
        background: #F5F5F7;
        color: #1F2937;
      }
      [data-testid="stSidebar"] label,
      [data-testid="stSidebar"] p,
      [data-testid="stMarkdownContainer"],
      [data-testid="stWidgetLabel"] p {
        color: #1F2937 !important;
      }
      /* Metric / caption text */
      [data-testid="stMetricValue"],
      [data-testid="stMetricLabel"] {
        color: #1F2937 !important;
      }
      div[data-testid="stVerticalBlockBorderWrapper"] {
        background: #FFFFFF;
        border: 1px solid #E5E7EB !important;
        border-radius: 8px !important;
      }
    </style>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# Google Sheets — same auth + cache boundary as before
# ---------------------------------------------------------------------------
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
    """Read every row from the dashboard sheet tab. Not cached — IO stays live."""
    gc = gspread_client()
    if gc is None:
        return None
    ws = gc.open_by_key(SHEET_ID).worksheet(TAB)
    return ws.get_all_records()


@st.cache_data(ttl=600)
def records_to_dataframe(records_json: str):
    """Cache dataframe *conversion* only — not sheet IO or secrets access.

    Callers pass json.dumps(...) of the raw records. The cache key is that JSON
    string, so a *new payload* is a cache miss and converts immediately (you do
    not wait for ttl). ttl only reuses the *same* payload for up to 600s.
    Sheet re-reads still happen on every run via fetch_records(); use Refresh
    data to clear any stale conversion entries after editing the sheet.
    """
    df = pd.DataFrame(json.loads(records_json))
    for col in ["category_correct", "urgency_correct", "false_high"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    if "version" in df.columns:
        df["version"] = df["version"].astype(str).str.strip()
    return df


def version_sort_key(v: str) -> int:
    """Sort v1, v2, v10 numerically by the digits after the leading letter."""
    try:
        return int(str(v).lstrip("vV"))
    except ValueError:
        return 10**9


def color_for_version(v: str) -> str:
    if v in VERSION_COLORS:
        return VERSION_COLORS[v]
    # Deterministic fallback for v4+ (avoid hash() randomization across runs).
    idx = sum(ord(c) for c in str(v)) % len(FALLBACK_COLORS)
    return FALLBACK_COLORS[idx]


def style_axes(ax, fig) -> None:
    """Readable matplotlib on a white face — charcoal ticks, light grid."""
    fig.patch.set_facecolor(FACE)
    ax.set_facecolor(FACE)
    ax.tick_params(colors=CHARCOAL, labelsize=9)
    ax.xaxis.label.set_color(CHARCOAL)
    ax.yaxis.label.set_color(CHARCOAL)
    for spine in ax.spines.values():
        spine.set_color("#E5E7EB")
    ax.grid(axis="y", linestyle="-", alpha=0.45, color=GRID)
    ax.set_axisbelow(True)


def annotate_bars_vertical(ax, pct: bool = True) -> None:
    """Write percent (or raw) labels above each vertical bar."""
    for patch in ax.patches:
        h = patch.get_height()
        if pd.isna(h):
            continue
        label = f"{h:.0%}" if pct else f"{h:.0f}"
        ax.annotate(
            label,
            (patch.get_x() + patch.get_width() / 2, h),
            ha="center",
            va="bottom",
            fontsize=8,
            color=CHARCOAL,
            xytext=(0, 2),
            textcoords="offset points",
        )


def plot_accuracy_by_version(means: pd.Series, ylabel: str) -> None:
    """One vertical bar per version; height = mean correctness (0..1)."""
    fig, ax = plt.subplots(figsize=(4.8, 3.2))
    style_axes(ax, fig)
    versions = list(means.index)
    vals = means.astype(float).tolist()
    colors = [color_for_version(v) for v in versions]
    ax.bar(versions, vals, color=colors, width=0.65, edgecolor="none")
    ax.set_ylim(0, 1.05)
    ax.set_yticks([0, 0.25, 0.5, 0.75, 1.0])
    ax.set_yticklabels(["0%", "25%", "50%", "75%", "100%"])
    ax.set_ylabel(ylabel)
    ax.set_xlabel("")
    annotate_bars_vertical(ax, pct=True)
    fig.tight_layout()
    st.pyplot(fig, clear_figure=True)
    plt.close(fig)


def plot_accuracy_by_category(df: pd.DataFrame, versions: list[str]) -> None:
    """Horizontal grouped bars: true_category × version → mean category_correct."""
    if df.empty or "true_category" not in df.columns:
        st.info("No category rows to chart for the selected versions.")
        return

    # mean category_correct per (true_category, version)
    pivot = (
        df.groupby(["true_category", "version"], dropna=False)["category_correct"]
        .mean()
        .unstack("version")
    )
    # Keep only selected versions that actually appear; order as sidebar sort.
    cols = [v for v in versions if v in pivot.columns]
    if not cols:
        st.info("No category accuracy to show for the selected versions.")
        return
    pivot = pivot[cols].sort_index(ascending=False)  # top-to-bottom alphabetical-ish

    n_cat = len(pivot.index)
    height = max(3.5, 0.35 * n_cat + 1.2)
    fig, ax = plt.subplots(figsize=(7.2, height))
    style_axes(ax, fig)
    ax.grid(axis="x", linestyle="-", alpha=0.45, color=GRID)
    ax.grid(axis="y", visible=False)

    y = range(n_cat)
    n_ver = len(cols)
    bar_h = min(0.8 / max(n_ver, 1), 0.28)
    # Offset versions around each category centre.
    offsets = [(i - (n_ver - 1) / 2) * bar_h for i in range(n_ver)]

    for i, ver in enumerate(cols):
        vals = pivot[ver].astype(float).fillna(0.0).tolist()
        ypos = [yi + offsets[i] for yi in y]
        bars = ax.barh(
            ypos,
            vals,
            height=bar_h * 0.92,
            color=color_for_version(ver),
            label=ver,
            edgecolor="none",
        )
        for bar, val in zip(bars, vals):
            if pd.isna(val):
                continue
            ax.annotate(
                f"{val:.0%}",
                (val, bar.get_y() + bar.get_height() / 2),
                va="center",
                ha="left",
                fontsize=7,
                color=CHARCOAL,
                xytext=(3, 0),
                textcoords="offset points",
            )

    ax.set_yticks(list(y))
    ax.set_yticklabels([str(i) for i in pivot.index], fontsize=8)
    ax.set_xlim(0, 1.12)
    ax.set_xticks([0, 0.25, 0.5, 0.75, 1.0])
    ax.set_xticklabels(["0%", "25%", "50%", "75%", "100%"])
    ax.set_xlabel("Avg. Category Correct")
    ax.set_ylabel("True Category")
    ax.legend(frameon=False, fontsize=8, loc="lower right")
    fig.tight_layout()
    st.pyplot(fig, clear_figure=True)
    plt.close(fig)


def plot_errors_stacked(df: pd.DataFrame, versions: list[str]) -> None:
    """Stacked horizontal bars: error_type × version counts. OK excluded.

    Counts are grouped as they appear in the data — we do not assume error
    types are mutually exclusive beyond whatever the sheet already encodes.
    Labels are the literal error_type strings (e.g. WRONG_URGENCY).
    """
    if df.empty or "error_type" not in df.columns:
        st.info("No error_type column to chart.")
        return

    errs = df[df["error_type"].astype(str) != "OK"].copy()
    if errs.empty:
        st.success("No non-OK errors in the selected versions.")
        return

    # Count tickets per (error_type, version)
    counts = (
        errs.groupby(["error_type", "version"], dropna=False)
        .size()
        .unstack("version", fill_value=0)
    )
    cols = [v for v in versions if v in counts.columns]
    if not cols:
        st.info("No errors to show for the selected versions.")
        return
    counts = counts[cols]
    # Largest total first (top of barh after invert-like ordering)
    counts["_total"] = counts.sum(axis=1)
    counts = counts.sort_values("_total", ascending=True).drop(columns="_total")

    fig, ax = plt.subplots(figsize=(7.2, max(2.8, 0.55 * len(counts) + 1.0)))
    style_axes(ax, fig)
    ax.grid(axis="x", linestyle="-", alpha=0.45, color=GRID)
    ax.grid(axis="y", visible=False)

    y_pos = range(len(counts.index))
    left = [0.0] * len(counts.index)
    for ver in cols:
        vals = counts[ver].astype(float).tolist()
        bars = ax.barh(
            list(y_pos),
            vals,
            left=left,
            color=color_for_version(ver),
            label=ver,
            edgecolor="none",
            height=0.65,
        )
        # Integer labels inside segments that are wide enough
        for bar, val, base in zip(bars, vals, left):
            if val <= 0:
                continue
            ax.annotate(
                f"{int(val)}",
                (base + val / 2, bar.get_y() + bar.get_height() / 2),
                ha="center",
                va="center",
                fontsize=8,
                color="#FFFFFF" if val >= 1 else CHARCOAL,
                fontweight="bold",
            )
        left = [b + v for b, v in zip(left, vals)]

    ax.set_yticks(list(y_pos))
    ax.set_yticklabels([str(i) for i in counts.index], fontsize=9)
    ax.set_xlabel("Number of tickets")
    ax.set_ylabel("")
    xmax = max(left) if left else 1
    ax.set_xlim(0, xmax * 1.08 + 0.5)
    ax.legend(frameon=False, fontsize=8, loc="lower right")
    fig.tight_layout()
    st.pyplot(fig, clear_figure=True)
    plt.close(fig)


def kpi_block(label: str, value: str) -> None:
    """Large high-contrast KPI; escape dynamic strings (sheet-derived)."""
    safe_label = html.escape(label)
    safe_value = html.escape(value)
    st.markdown(
        f"""
        <div style="padding:0.35rem 0.15rem 0.75rem 0.15rem;">
          <div style="font-size:0.95rem;font-weight:600;color:#1F2937;">{safe_label}</div>
          <div style="font-size:2.6rem;font-weight:700;color:#111827;line-height:1.15;margin-top:0.2rem;">
            {safe_value}
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Data load
# ---------------------------------------------------------------------------
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

# ---------------------------------------------------------------------------
# Sidebar: version multiselect (default all) + KPI version (default latest)
# ---------------------------------------------------------------------------
all_versions = sorted(data["version"].unique(), key=version_sort_key)

selected_versions = st.sidebar.multiselect(
    "Versions",
    options=all_versions,
    default=all_versions,
    help="Charts compare these versions. Colours: v1 blue, v2 orange, v3 red.",
)

if st.sidebar.button("Refresh data"):
    st.cache_data.clear()
    st.rerun()

if not selected_versions:
    st.info("Select at least one version in the sidebar to see quality charts.")
    st.stop()

# Keep sidebar order stable (numeric), not multiselect click order.
selected_versions = sorted(selected_versions, key=version_sort_key)

kpi_default_index = len(selected_versions) - 1  # newest among selected
kpi_version = st.sidebar.selectbox(
    "KPI version",
    options=selected_versions,
    index=kpi_default_index,
    help="The two big accuracy numbers refer to this version only.",
)

filtered = data[data["version"].isin(selected_versions)].copy()
kpi_view = filtered[filtered["version"] == kpi_version]
n_kpi = int(len(kpi_view))
cat_pct = float(kpi_view["category_correct"].mean()) if n_kpi else 0.0
urg_pct = float(kpi_view["urgency_correct"].mean()) if n_kpi else 0.0

# ---------------------------------------------------------------------------
# Title + KPIs + top accuracy charts (Tableau layout)
# ---------------------------------------------------------------------------
st.title("Support Sorter: Quality by Version")
st.caption(
    "An LLM sorts support tickets by category and urgency. "
    "Each version is scored against hand-labeled reference tickets."
)

top_left, top_mid, top_right = st.columns([1.1, 1.2, 1.2])

with top_left:
    # Labels explicitly include the selected KPI version (screenshot pattern).
    kpi_block(f"Urgency Accuracy ({kpi_version})", f"{urg_pct:.0%}")
    kpi_block(f"Category Accuracy ({kpi_version})", f"{cat_pct:.0%}")

# Means across *selected* versions only (still computed from real rows).
by_ver = (
    filtered.groupby("version")[["category_correct", "urgency_correct"]]
    .mean()
    .reindex(selected_versions)
)

with top_mid:
    st.markdown("**Category Accuracy**")
    plot_accuracy_by_version(by_ver["category_correct"], "Category Correct")

with top_right:
    st.markdown("**Urgency Accuracy**")
    plot_accuracy_by_version(by_ver["urgency_correct"], "Urgency Correct")

st.divider()

# ---------------------------------------------------------------------------
# Bottom row: by-category grouped + stacked errors
# ---------------------------------------------------------------------------
bot_left, bot_right = st.columns(2)

with bot_left:
    st.markdown("**Accuracy by Category**")
    plot_accuracy_by_category(filtered, selected_versions)

with bot_right:
    st.markdown("**Errors by Type**")
    plot_errors_stacked(filtered, selected_versions)

st.caption(
    "Note: the reference key was calibrated while reviewing model errors, "
    "so these scores are not held-out test performance."
)
