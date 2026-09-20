import datetime
import gspread
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="Weight Tracker", layout="wide")

# --- CONFIGURATION ---
SHEET_ID = "1uMLem4JckvHOEvSVlSakFcxv9xxa8WkUR2wg9gjm83k"
ADMIN_PIN = str(st.secrets.get("ADMIN_PIN", "1234"))


# --- DATA ENGINE (GSPREAD + STREAMLIT SECRETS) ---
@st.cache_resource
def get_worksheets():
    creds = dict(st.secrets["gcp_service_account"])
    if "\\n" in creds["private_key"]:
        creds["private_key"] = creds["private_key"].replace("\\n", "\n")

    gc = gspread.service_account_from_dict(creds)
    sh = gc.open_by_key(SHEET_ID)

    ws_weights = sh.sheet1

    # Auto-create 'Notes' worksheet if it doesn't already exist
    try:
        ws_notes = sh.worksheet("Notes")
    except gspread.exceptions.WorksheetNotFound:
        ws_notes = sh.add_worksheet(title="Notes", rows=100, cols=2)
        ws_notes.append_row(["Date", "Note"])

    return ws_weights, ws_notes


@st.cache_data(ttl=60)
def load_weight_data():
    ws_weights, _ = get_worksheets()
    records = ws_weights.get_all_records()
    df = pd.DataFrame(records)
    df["Date"] = pd.to_datetime(df["Date"])
    df["Weight"] = pd.to_numeric(df["Weight"])
    return df.sort_values("Date").reset_index(drop=True)


@st.cache_data(ttl=60)
def load_notes_data():
    _, ws_notes = get_worksheets()
    records = ws_notes.get_all_records()
    if not records:
        return pd.DataFrame(columns=["Date", "Note"])
    df_n = pd.DataFrame(records)
    df_n["Date"] = pd.to_datetime(df_n["Date"])
    df_n["Note"] = df_n["Note"].astype(str)
    return df_n.sort_values("Date").reset_index(drop=True)


try:
    df = load_weight_data()
    df_notes = load_notes_data()
except Exception as e:
    st.error(f"Failed to connect to private Google Sheet: {e}")
    st.stop()

# ----------------------------------------------------
# 1. ADMIN CONTROLS (PIN REQUIRED IN SIDEBAR)
# ----------------------------------------------------
with st.sidebar:
    st.header("Admin Access")
    entered_pin = st.text_input("Enter PIN to modify weight log", type="password")

    if entered_pin == ADMIN_PIN:
        st.success("Authorized: Admin Mode Active")
        tab_add, tab_edit, tab_del = st.tabs(["Add", "Edit", "Delete"])

        ws_weights, _ = get_worksheets()

        with tab_add:
            with st.form("add_form", clear_on_submit=True):
                entry_date = st.date_input("Date", value=datetime.date.today())
                entry_weight = st.number_input(
                    "Weight (kg)",
                    min_value=30.0,
                    max_value=200.0,
                    value=float(df["Weight"].iloc[-1]),
                    step=0.1,
                    format="%.2f",
                )
                if st.form_submit_button("Save New Entry"):
                    try:
                        next_id = int(df["ID"].max()) + 1 if not df.empty else 1
                        date_str = entry_date.strftime("%Y-%m-%d")
                        ws_weights.append_row([next_id, date_str, float(entry_weight)])
                        st.cache_data.clear()
                        st.success(f"Added {entry_weight} kg for {date_str}!")
                        st.rerun()
                    except Exception as err:
                        st.error(f"Error: {err}")

        with tab_edit:
            edit_options = {
                f"{r['Date'].strftime('%d %b %Y')} — {r['Weight']:.2f} kg (ID: {r['ID']})": r[
                    "ID"
                ]
                for _, r in df.sort_values("Date", ascending=False).iterrows()
            }
            if edit_options:
                selected_edit_label = st.selectbox(
                    "Select entry to edit", list(edit_options.keys())
                )
                selected_edit_id = edit_options[selected_edit_label]
                row_data = df[df["ID"] == selected_edit_id].iloc[0]

                with st.form("edit_form"):
                    new_date = st.date_input(
                        "Change Date", value=row_data["Date"].date()
                    )
                    new_weight = st.number_input(
                        "Change Weight (kg)",
                        min_value=30.0,
                        max_value=200.0,
                        value=float(row_data["Weight"]),
                        step=0.1,
                        format="%.2f",
                    )
                    if st.form_submit_button("Update Entry"):
                        try:
                            cell = ws_weights.find(str(selected_edit_id), in_column=1)
                            if cell:
                                ws_weights.update(
                                    range_name=f"B{cell.row}:C{cell.row}",
                                    values=[
                                        [
                                            new_date.strftime("%Y-%m-%d"),
                                            float(new_weight),
                                        ]
                                    ],
                                )
                                st.cache_data.clear()
                                st.success("Updated!")
                                st.rerun()
                        except Exception as err:
                            st.error(f"Error: {err}")

        with tab_del:
            del_options = {
                f"{r['Date'].strftime('%d %b %Y')} — {r['Weight']:.2f} kg (ID: {r['ID']})": r[
                    "ID"
                ]
                for _, r in df.sort_values("Date", ascending=False).iterrows()
            }
            if del_options:
                selected_del_label = st.selectbox(
                    "Select entry to delete", list(del_options.keys())
                )
                selected_del_id = del_options[selected_del_label]
                if st.button("Delete Entry", type="primary"):
                    try:
                        cell = ws_weights.find(str(selected_del_id), in_column=1)
                        if cell:
                            ws_weights.delete_rows(cell.row)
                            st.cache_data.clear()
                            st.success("Deleted!")
                            st.rerun()
                    except Exception as err:
                        st.error(f"Error: {err}")
    elif entered_pin:
        st.error("Incorrect PIN")
    else:
        st.info("Weights log is read-only. Enter PIN to modify.")

# ----------------------------------------------------
# 2. MAIN HEADER & SUMMARY METRICS
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
    "Current", f"{curr_wt:.1f} kg", delta=f"{delta_last:+.2f} kg", delta_color="inverse"
)
col2.metric("Lightest", f"{lightest:.1f} kg")
col3.metric("Heaviest", f"{heaviest:.1f} kg")
col4.metric("Loss Rate (/mo)", f"{monthly_rate:.2f} kg")

st.divider()

# ----------------------------------------------------
# 3. TOP NAVIGATION TABS (CHART vs NOTES & IMPACT)
# ----------------------------------------------------
view_tab_chart, view_tab_notes = st.tabs(["📊 Progress Chart", "📝 Notes & Impact"])

# ----------------------------------------------------
# TAB 1: INTERACTIVE PLOTLY CHART
# ----------------------------------------------------
with view_tab_chart:
    # 1. Compute Full History Metrics (Preserves accurate EWMA & all-time stars)
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

    running_min = df["Weight"].cummin()
    good_jobs = df["Weight"] == running_min

    # 2. Duration Toggles
    duration_col, custom_col = st.columns([2, 2])
    with duration_col:
        duration_choice = st.radio(
            "Timeframe",
            options=["1 Month", "3 Months", "1 Year", "All Time", "Custom"],
            index=3,  # Default to All Time
            horizontal=True,
            label_visibility="collapsed",
        )

    max_date = df["Date"].max()
    min_date = df["Date"].min()

    # Determine date window
    if duration_choice == "1 Month":
        start_date = max_date - pd.DateOffset(months=1)
        end_date = max_date
    elif duration_choice == "3 Months":
        start_date = max_date - pd.DateOffset(months=3)
        end_date = max_date
    elif duration_choice == "1 Year":
        start_date = max_date - pd.DateOffset(years=1)
        end_date = max_date
    elif duration_choice == "Custom":
        with custom_col:
            date_range = st.date_input(
                "Custom Date Range",
                value=(min_date.date(), max_date.date()),
                min_value=min_date.date(),
                max_value=datetime.date.today(),
                key="custom_range_picker",
            )
            if isinstance(date_range, tuple) and len(date_range) == 2:
                start_date = pd.to_datetime(date_range[0])
                end_date = pd.to_datetime(date_range[1])
            else:
                start_date = min_date
                end_date = max_date
    else:  # All Time
        start_date = min_date
        end_date = max_date

    # 3. Filter data for the visual range
    mask = (df["Date"] >= start_date) & (df["Date"] <= end_date)
    df_visible = df[mask].copy()
    good_jobs_visible = good_jobs[mask]

    # Segmented trend line within selected window
    trend_green_x, trend_green_y = [], []
    trend_red_x, trend_red_y = [], []
    for i in range(1, len(df)):
        d0, d1 = df["Date"].iloc[i - 1], df["Date"].iloc[i]
        t0, t1 = df["Trend"].iloc[i - 1], df["Trend"].iloc[i]

        # Only draw segments that fall within or touch the active window
        if d1 >= start_date and d0 <= end_date:
            if t1 <= t0:
                trend_green_x.extend([d0, d1, None])
                trend_green_y.extend([t0, t1, None])
            else:
                trend_red_x.extend([d0, d1, None])
                trend_red_y.extend([t0, t1, None])

    # 4. Build Figure
    fig = go.Figure()

    # Actual weight trace
    fig.add_trace(
        go.Scatter(
            x=df_visible["Date"],
            y=df_visible["Weight"],
            mode="lines+markers",
            name="Actual Weight",
            legendgroup="actual",
            line=dict(color="#38bdf8", width=2),
            marker=dict(size=6, color="#0284c7"),
            hovertemplate="<b>Date</b>: %{x|%d %b %Y}<br><b>Weight</b>: %{y:.2f} kg<extra></extra>",
        )
    )

    # Record Low stars
    df_stars = df_visible[good_jobs_visible]
    fig.add_trace(
        go.Scatter(
            x=df_stars["Date"],
            y=df_stars["Weight"],
            mode="markers",
            name="Good Job! ⭐",
            legendgroup="stars",
            marker=dict(
                symbol="star",
                size=14,
                color="#eab308",
                line=dict(color="#ca8a04", width=1),
            ),
            hovertemplate="<b>⭐ Record Low!</b><br><b>Date</b>: %{x|%d %b %Y}<br><b>Weight</b>: %{y:.2f} kg<extra></extra>",
        )
    )

    # Trend lines
    fig.add_trace(
        go.Scatter(
            x=trend_green_x,
            y=trend_green_y,
            mode="lines",
            name="Trend Line",
            legendgroup="trend",
            line=dict(color="#22c55e", width=2.5, dash="dash"),
            hoverinfo="skip",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=trend_red_x,
            y=trend_red_y,
            mode="lines",
            name="Trend Line",
            legendgroup="trend",
            showlegend=False,
            line=dict(color="#ef4444", width=2.5, dash="dash"),
            hoverinfo="skip",
        )
    )

    # Notes Markers on Chart (Filtered by active date window)
    if not df_notes.empty:
        df_notes_visible = df_notes[
            (df_notes["Date"] >= start_date) & (df_notes["Date"] <= end_date)
        ].copy()

        if not df_notes_visible.empty and not df_visible.empty:
            notes_merged = pd.merge_asof(
                df_notes_visible.sort_values("Date"),
                df[["Date", "Weight"]].sort_values("Date"),
                on="Date",
                direction="nearest",
            )
            fig.add_trace(
                go.Scatter(
                    x=notes_merged["Date"],
                    y=notes_merged["Weight"],
                    mode="markers",
                    name="Notes 📝",
                    legendgroup="notes",
                    customdata=notes_merged["Note"],
                    marker=dict(
                        symbol="diamond",
                        size=13,
                        color="#c084fc",
                        line=dict(color="#7e22ce", width=1.5),
                    ),
                    hovertemplate="<b>📝 Note (%{x|%d %b %Y})</b><br>%{customdata}<extra></extra>",
                )
            )

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
            range=[start_date, end_date],
        ),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=20, r=20, t=10, b=20),
        hovermode="closest",
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="left",
            x=0,
            itemclick="toggle",
            itemdoubleclick="toggleothers",
        ),
    )

    st.plotly_chart(fig, width="stretch")

# ----------------------------------------------------
# TAB 2: NOTES & PROGRESS IMPACT VIEW
# ----------------------------------------------------
with view_tab_notes:
    st.subheader("Action Notes & Weight Impact")
    st.caption(
        "Log habits, breakdowns, or changes and track their weight impact over time."
    )

    with st.expander("📝 Add a New Note / Milestone", expanded=True):
        with st.form("note_form", clear_on_submit=True):
            tab_n_date = st.date_input(
                "Date", value=datetime.date.today(), key="tab_note_date"
            )
            tab_n_text = st.text_area(
                "What did you do or what happened?",
                placeholder="e.g. Swapped sugary drinks for water, started evening walks, intermittent fasting...",
            )
            if st.form_submit_button("Save Note"):
                if tab_n_text.strip():
                    _, ws_n = get_worksheets()
                    ws_n.append_row(
                        [tab_n_date.strftime("%Y-%m-%d"), tab_n_text.strip()]
                    )
                    st.cache_data.clear()
                    st.success("Note saved and pinned to chart!")
                    st.rerun()
                else:
                    st.warning("Please type a note first.")

    if df_notes.empty:
        st.info("No notes recorded yet. Add your first note above.")
    else:
        impact_rows = []
        for _, n_row in df_notes.sort_values("Date", ascending=False).iterrows():
            note_date = n_row["Date"]

            weights_before = df[df["Date"] <= note_date]
            wt_before = (
                weights_before["Weight"].iloc[-1] if not weights_before.empty else None
            )
            date_before = (
                weights_before["Date"].iloc[-1].strftime("%d %b %Y")
                if not weights_before.empty
                else "N/A"
            )

            weights_after = df[df["Date"] > note_date]
            wt_after = (
                weights_after["Weight"].iloc[0] if not weights_after.empty else None
            )
            date_after = (
                weights_after["Date"].iloc[0].strftime("%d %b %Y")
                if not weights_after.empty
                else "Pending"
            )

            if wt_before is not None and wt_after is not None:
                net_change = wt_after - wt_before
                diff_display = f"{net_change:+.2f} kg"
            else:
                diff_display = "Awaiting subsequent weigh-in"

            impact_rows.append(
                {
                    "Date": note_date.strftime("%d %b %Y"),
                    "Note": n_row["Note"],
                    "Weight Before": (
                        f"{wt_before:.2f} kg ({date_before})" if wt_before else "N/A"
                    ),
                    "Weight After": (
                        f"{wt_after:.2f} kg ({date_after})" if wt_after else "Pending"
                    ),
                    "Net Impact": diff_display,
                }
            )

        st.dataframe(pd.DataFrame(impact_rows), width="stretch", hide_index=True)
