import datetime
import gspread
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="Weight Tracker", layout="centered")

# --- CONFIGURATION ---
SHEET_ID = "1uMLem4JckvHOEvSVlSakFcxv9xxa8WkUR2wg9gjm83k"
ADMIN_PIN = str(st.secrets.get("ADMIN_PIN", "1234"))


# --- DATA ENGINE (GSPREAD + STREAMLIT SECRETS) ---
@st.cache_resource
def get_worksheet():
    # Convert secrets to a mutable dictionary
    creds = dict(st.secrets["gcp_service_account"])

    # Fix literal \n escape sequences from secrets.toml
    if "\\n" in creds["private_key"]:
        creds["private_key"] = creds["private_key"].replace("\\n", "\n")

    gc = gspread.service_account_from_dict(creds)
    sh = gc.open_by_key(SHEET_ID)
    return sh.sheet1


@st.cache_data(ttl=60)
def load_data():
    ws = get_worksheet()
    records = ws.get_all_records()
    df = pd.DataFrame(records)
    df["Date"] = pd.to_datetime(df["Date"])
    df["Weight"] = pd.to_numeric(df["Weight"])
    return df.sort_values("Date").reset_index(drop=True)


try:
    df = load_data()
except Exception as e:
    st.error(f"Failed to connect to private Google Sheet: {e}")
    st.stop()

# ----------------------------------------------------
# 1. HEADER & SUMMARY METRIC CARDS
# ----------------------------------------------------
st.title("Weight Tracker")

curr_wt = df["Weight"].iloc[-1]
prev_wt = df["Weight"].iloc[-2] if len(df) > 1 else curr_wt
delta_last = curr_wt - prev_wt

heaviest = df["Weight"].max()
lightest = df["Weight"].min()

total_days = (df["Date"].iloc[-1] - df["Date"].iloc[0]).days
elapsed_months = total_days / 30.0 if total_days > 0 else 1.0
monthly_rate = (df["Weight"].iloc[0] - df["Weight"].iloc[-1]) / elapsed_months

col1, col2, col3, col4 = st.columns(4)
col1.metric(
    "Current",
    f"{curr_wt:.1f} kg",
    delta=f"{delta_last:+.2f} kg",
    delta_color="inverse",
)
col2.metric("Lightest", f"{lightest:.1f} kg")
col3.metric("Heaviest", f"{heaviest:.1f} kg")
col4.metric("Loss Rate", f"{monthly_rate:.2f} kg/mo")

st.divider()

# # ----------------------------------------------------
# 2. ADMIN CONTROLS (ADD, EDIT, DELETE)
# ----------------------------------------------------
with st.sidebar:
    st.header("Admin Access")
    entered_pin = st.text_input("Enter PIN to manage data", type="password")

    if entered_pin == ADMIN_PIN:
        st.success("Authorized: Admin Mode Active")

        tab_add, tab_edit, tab_del = st.tabs(["Add", "Edit", "Delete"])

        # ---------------- ADD TAB ----------------
        with tab_add:
            with st.form("add_form", clear_on_submit=True):
                entry_date = st.date_input("Date", value=datetime.date.today())
                entry_weight = st.number_input(
                    "Weight (kg)",
                    min_value=30.0,
                    max_value=200.0,
                    value=float(curr_wt),
                    step=0.1,
                    format="%.2f",
                    key="add_wt",
                )
                if st.form_submit_button("Save New Entry"):
                    try:
                        ws = get_worksheet()
                        next_id = int(df["ID"].max()) + 1 if not df.empty else 1
                        date_str = entry_date.strftime("%Y-%m-%d")

                        ws.append_row([next_id, date_str, float(entry_weight)])

                        st.cache_data.clear()
                        st.success(f"Added {entry_weight} kg for {date_str}!")
                        st.rerun()
                    except Exception as err:
                        st.error(f"Error adding entry: {err}")

        # ---------------- EDIT TAB ----------------
        with tab_edit:
            # Dropdown sorted newest to oldest
            edit_options = {
                f"{r['Date'].strftime('%d %b %Y')} — {r['Weight']:.2f} kg (ID: {r['ID']})": r[
                    "ID"
                ]
                for _, r in df.sort_values("Date", ascending=False).iterrows()
            }

            if edit_options:
                selected_edit_label = st.selectbox(
                    "Select entry to edit",
                    list(edit_options.keys()),
                    key="edit_select",
                )
                selected_edit_id = edit_options[selected_edit_label]
                row_data = df[df["ID"] == selected_edit_id].iloc[0]

                with st.form("edit_form"):
                    new_date = st.date_input(
                        "Change Date",
                        value=row_data["Date"].date(),
                        key="edit_date",
                    )
                    new_weight = st.number_input(
                        "Change Weight (kg)",
                        min_value=30.0,
                        max_value=200.0,
                        value=float(row_data["Weight"]),
                        step=0.1,
                        format="%.2f",
                        key="edit_wt",
                    )

                    if st.form_submit_button("Update Entry"):
                        try:
                            ws = get_worksheet()
                            cell = ws.find(str(selected_edit_id), in_column=1)
                            if cell:
                                date_str = new_date.strftime("%Y-%m-%d")
                                ws.update(
                                    range_name=f"B{cell.row}:C{cell.row}",
                                    values=[[date_str, float(new_weight)]],
                                )
                                st.cache_data.clear()
                                st.success("Entry updated successfully!")
                                st.rerun()
                            else:
                                st.error("Entry not found in Google Sheet.")
                        except Exception as err:
                            st.error(f"Error updating entry: {err}")
            else:
                st.info("No entries available to edit.")

        # ---------------- DELETE TAB ----------------
        with tab_del:
            del_options = {
                f"{r['Date'].strftime('%d %b %Y')} — {r['Weight']:.2f} kg (ID: {r['ID']})": r[
                    "ID"
                ]
                for _, r in df.sort_values("Date", ascending=False).iterrows()
            }

            if del_options:
                selected_del_label = st.selectbox(
                    "Select entry to remove",
                    list(del_options.keys()),
                    key="del_select",
                )
                selected_del_id = del_options[selected_del_label]

                st.warning("This will permanently delete this row.")
                if st.button("Delete Entry", type="primary"):
                    try:
                        ws = get_worksheet()
                        cell = ws.find(str(selected_del_id), in_column=1)
                        if cell:
                            ws.delete_rows(cell.row)
                            st.cache_data.clear()
                            st.success("Entry deleted!")
                            st.rerun()
                        else:
                            st.error("Entry not found in Google Sheet.")
                    except Exception as err:
                        st.error(f"Error deleting entry: {err}")
            else:
                st.info("No entries available to delete.")

    elif entered_pin:
        st.error("Incorrect PIN")
    else:
        st.info("Read-only view active. Enter PIN above to manage entries.")
        
# ----------------------------------------------------
# 3. CALCULATIONS & DATA MODEL
# ----------------------------------------------------
# 28-day EWMA trend
df["Trend"] = (
    df.set_index("Date")["Weight"]
    .ewm(
        halflife=pd.Timedelta(days=28),
        times=df.set_index("Date").index,
        adjust=True,
    )
    .mean()
    .values
)

# Cumulative minimum markers
running_min = df["Weight"].cummin()
good_jobs = df["Weight"] == running_min

# Build segmented trend traces (Green = losing, Red = gaining)
trend_green_x, trend_green_y = [], []
trend_red_x, trend_red_y = [], []

for i in range(1, len(df)):
    d0, d1 = df["Date"].iloc[i - 1], df["Date"].iloc[i]
    t0, t1 = df["Trend"].iloc[i - 1], df["Trend"].iloc[i]
    if t1 <= t0:
        trend_green_x.extend([d0, d1, None])
        trend_green_y.extend([t0, t1, None])
    else:
        trend_red_x.extend([d0, d1, None])
        trend_red_y.extend([t0, t1, None])

# ----------------------------------------------------
# 4. INTERACTIVE PLOTLY CHART
# ----------------------------------------------------
fig = go.Figure()

# Actual weight line
fig.add_trace(
    go.Scatter(
        x=df["Date"],
        y=df["Weight"],
        mode="lines+markers",
        name="Actual Weight",
        line=dict(color="#38bdf8", width=2),
        marker=dict(size=6, color="#0284c7"),
        hovertemplate="<b>Date</b>: %{x|%d %b %Y}<br><b>Weight</b>: %{y:.2f} kg<extra></extra>",
    )
)

# Milestone stars (Record Lows)
df_stars = df[good_jobs]
fig.add_trace(
    go.Scatter(
        x=df_stars["Date"],
        y=df_stars["Weight"],
        mode="markers",
        name="Good Job! ⭐",
        marker=dict(
            symbol="star",
            size=14,
            color="#eab308",
            line=dict(color="#ca8a04", width=1),
        ),
        hovertemplate="<b>⭐ Record Low!</b><br><b>Date</b>: %{x|%d %b %Y}<br><b>Weight</b>: %{y:.2f} kg<extra></extra>",
    )
)

# Green trend segments (Losing weight)
fig.add_trace(
    go.Scatter(
        x=trend_green_x,
        y=trend_green_y,
        mode="lines",
        name="Trend (Improving)",
        line=dict(color="#22c55e", width=2.5, dash="dash"),
        hoverinfo="skip",
    )
)

# Red trend segments (Gaining weight)
fig.add_trace(
    go.Scatter(
        x=trend_red_x,
        y=trend_red_y,
        mode="lines",
        name="Trend (Increasing)",
        line=dict(color="#ef4444", width=2.5, dash="dash"),
        hoverinfo="skip",
    )
)

# Layout: Inverted Y-axis, custom dark styling, legend above
fig.update_layout(
    yaxis=dict(
        autorange="reversed",
        title="Weight (kg)",
        gridcolor="#1e293b",
        zeroline=False,
    ),
    xaxis=dict(
        title="",
        gridcolor="#1e293b",
        showgrid=True,
    ),
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    margin=dict(l=20, r=20, t=10, b=20),
    hovermode="closest",
    legend=dict(
        orientation="h",
        yanchor="bottom",
        y=1.02,
        xanchor="right",
        x=1,
    ),
)

st.plotly_chart(fig, use_container_width=True)