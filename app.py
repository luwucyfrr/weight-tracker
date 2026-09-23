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

def get_meals_worksheet():
    creds = dict(st.secrets["gcp_service_account"])
    if "\\n" in creds["private_key"]:
        creds["private_key"] = creds["private_key"].replace("\\n", "\n")

    gc = gspread.service_account_from_dict(creds)
    sh = gc.open_by_key(SHEET_ID)

    try:
        ws = sh.worksheet("Meals")
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.add_worksheet(title="Meals", rows=100, cols=5)
        ws.append_row(["Date", "Time", "Meal", "Items", "Notes"])
        return ws

    # Automatic migration: if existing sheet has 4 columns without 'Time', insert it
    headers = ws.row_values(1)
    if headers and "Time" not in headers:
        all_rows = ws.get_all_values()
        if all_rows:
            new_rows = [["Date", "Time", "Meal", "Items", "Notes"]]
            fallback_times = {
                "Breakfast": "09:00",
                "Lunch": "13:30",
                "Snack": "17:00",
                "Dinner": "20:30",
                "Drinks / Dessert": "21:30",
            }
            for r in all_rows[1:]:
                d = r[0] if len(r) > 0 else ""
                m = r[1] if len(r) > 1 else ""
                items = r[2] if len(r) > 2 else ""
                notes = r[3] if len(r) > 3 else ""
                t = fallback_times.get(m, "12:00")
                new_rows.append([d, t, m, items, notes])
            ws.clear()
            ws.update(
                range_name=f"A1:E{len(new_rows)}",
                values=new_rows,
            )

    return ws


@st.cache_data(ttl=60)
def load_meals_data():
    ws_meals = get_meals_worksheet()
    records = ws_meals.get_all_records()
    if not records:
        return pd.DataFrame(columns=["Date", "Time", "Meal", "Items", "Notes"])
    df_m = pd.DataFrame(records)
    df_m["Date"] = pd.to_datetime(df_m["Date"])
    if "Time" not in df_m.columns:
        df_m["Time"] = "12:00"
    df_m["Time"] = df_m["Time"].astype(str).str.strip()
    df_m["Meal"] = df_m["Meal"].astype(str)
    df_m["Items"] = df_m["Items"].astype(str)
    df_m["Notes"] = df_m["Notes"].astype(str)
    return df_m

try:
    df = load_weight_data()
    df_notes = load_notes_data()
    df_meals = load_meals_data()
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
view_tab_chart, view_tab_notes, view_tab_food = st.tabs(
    ["📊 Progress Chart", "📝 Notes & Impact", "🍽️ Food Log"]
)

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

    # Meals Markers on Chart (Filtered by active date window)
    if not df_meals.empty:
        df_meals_visible = df_meals[
            (df_meals["Date"] >= start_date) & (df_meals["Date"] <= end_date)
        ].copy()

        if not df_meals_visible.empty and not df_visible.empty:
            # Group multiple meals on the same date into a single hover card
            meal_tooltips = {}
            for d, grp in df_meals_visible.groupby("Date"):
                lines = []
                for _, r in grp.iterrows():
                    entry = f"• <b>{r['Meal']}</b>: {r['Items']}"
                    if r["Notes"]:
                        entry += f" <i>({r['Notes']})</i>"
                    lines.append(entry)
                meal_tooltips[d] = "<br>".join(lines)

            df_meals_summary = pd.DataFrame(
                list(meal_tooltips.items()), columns=["Date", "MealSummary"]
            )

            # Pin meal icons to the closest weigh-in point
            meals_merged = pd.merge_asof(
                df_meals_summary.sort_values("Date"),
                df[["Date", "Weight"]].sort_values("Date"),
                on="Date",
                direction="nearest",
            )

            fig.add_trace(
                go.Scatter(
                    x=meals_merged["Date"],
                    y=meals_merged["Weight"],
                    mode="markers",
                    name="Meals 🍽️",
                    legendgroup="meals",
                    customdata=meals_merged["MealSummary"],
                    marker=dict(
                        symbol="circle",
                        size=11,
                        color="#f97316",
                        line=dict(color="#c2410c", width=1.5),
                    ),
                    hovertemplate="<b>🍽️ Logged Meals (%{x|%d %b %Y})</b><br>%{customdata}<extra></extra>",
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

    # 1. ADD NOTE FORM
    with st.expander("📝 Add a New Note / Milestone", expanded=False):
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

    # 2. INLINE TABLE WITH EDIT & DELETE POPUPS
    if df_notes.empty:
        st.info("No notes recorded yet. Add your first note above.")
    else:
        # Table Header
        h_date, h_note, h_before, h_after, h_imp, h_edit, h_del = st.columns(
            [1.4, 3.4, 2.0, 2.0, 1.4, 0.6, 0.6]
        )
        h_date.caption("**Date**")
        h_note.caption("**Note**")
        h_before.caption("**Weight Before**")
        h_after.caption("**Weight After**")
        h_imp.caption("**Net Impact**")
        h_edit.caption("")
        h_del.caption("")

        sorted_notes = (
            df_notes.sort_values("Date", ascending=False)
            .reset_index(drop=True)
        )

        for idx, n_row in sorted_notes.iterrows():
            note_date = n_row["Date"]
            note_str_date = note_date.strftime("%Y-%m-%d")
            note_text = n_row["Note"]

            # Weight before note
            weights_before = df[df["Date"] <= note_date]
            wt_before = (
                weights_before["Weight"].iloc[-1]
                if not weights_before.empty
                else None
            )
            date_before = (
                weights_before["Date"].iloc[-1].strftime("%d %b %Y")
                if not weights_before.empty
                else "N/A"
            )

            # Weight after note
            weights_after = df[df["Date"] > note_date]
            wt_after = (
                weights_after["Weight"].iloc[0]
                if not weights_after.empty
                else None
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
                diff_display = "Awaiting weigh-in"

            c_date, c_note, c_before, c_after, c_imp, c_edit, c_del = st.columns(
                [1.4, 3.4, 2.0, 2.0, 1.4, 0.6, 0.6], vertical_alignment="center"
            )

            c_date.write(note_date.strftime("%d %b %Y"))
            c_note.write(note_text)
            c_before.write(
                f"{wt_before:.2f} kg ({date_before})"
                if wt_before
                else "N/A"
            )
            c_after.write(
                f"{wt_after:.2f} kg ({date_after})"
                if wt_after
                else "Pending"
            )
            c_imp.write(diff_display)

            # EDIT POPOVER
            with c_edit:
                with st.popover("✏️", help="Edit note"):
                    st.caption("**Edit Entry**")
                    new_date_val = st.date_input(
                        "Change Date",
                        value=note_date.date(),
                        key=f"edit_date_{idx}_{note_str_date}",
                    )
                    new_text_val = st.text_area(
                        "Change Note",
                        value=note_text,
                        key=f"edit_text_{idx}_{note_str_date}",
                    )
                    if st.button("Save Changes", key=f"save_edit_{idx}_{note_str_date}"):
                        if new_text_val.strip():
                            _, ws_n = get_worksheets()
                            all_rows = ws_n.get_all_values()
                            row_idx_to_edit = None

                            for r_idx, row in enumerate(all_rows[1:], start=2):
                                if (
                                    len(row) >= 2
                                    and row[0].strip() == note_str_date.strip()
                                    and row[1].strip() == note_text.strip()
                                ):
                                    row_idx_to_edit = r_idx
                                    break

                            if row_idx_to_edit:
                                ws_n.update(
                                    range_name=f"A{row_idx_to_edit}:B{row_idx_to_edit}",
                                    values=[
                                        [
                                            new_date_val.strftime("%Y-%m-%d"),
                                            new_text_val.strip(),
                                        ]
                                    ],
                                )
                                st.cache_data.clear()
                                st.success("Updated!")
                                st.rerun()

            # DELETE POPOVER
            with c_del:
                with st.popover("🗑️", help="Delete note"):
                    st.caption("Permanently delete this note?")
                    if st.button(
                        "Yes, Delete",
                        type="primary",
                        key=f"confirm_del_{idx}_{note_str_date}",
                    ):
                        _, ws_n = get_worksheets()
                        all_rows = ws_n.get_all_values()
                        row_idx_to_del = None

                        for r_idx, row in enumerate(all_rows[1:], start=2):
                            if (
                                len(row) >= 2
                                and row[0].strip() == note_str_date.strip()
                                and row[1].strip() == note_text.strip()
                            ):
                                row_idx_to_del = r_idx
                                break

                        if row_idx_to_del:
                            ws_n.delete_rows(row_idx_to_del)
                            st.cache_data.clear()
                            st.rerun()

# ----------------------------------------------------
# TAB 3: DAILY FOOD & WEIGHT TIMELINE (EXACT TIME SORT)
# ----------------------------------------------------
with view_tab_food:
    st.subheader("Daily Food & Weight Timeline")
    st.caption("A chronological log of morning weigh-ins and meals.")

    # 1. ADD MEAL FORM
    with st.expander("🍽️ Log a Meal", expanded=False):
        with st.form("meal_form", clear_on_submit=True):
            col_m1, col_m2, col_m3 = st.columns([1.2, 1.0, 1.2])
            m_date = col_m1.date_input(
                "Date", value=datetime.date.today(), key="meal_date_input"
            )
            m_time = col_m2.time_input(
                "Time",
                value=datetime.datetime.now().time(),
                key="meal_time_input",
            )
            m_type = col_m3.selectbox(
                "Meal",
                ["Breakfast", "Lunch", "Dinner", "Snack", "Drinks / Dessert"],
                key="meal_type_input",
            )
            m_items = st.text_area(
                "Food / Items",
                placeholder="e.g. Schezwan Noodles, Paneer roll, coffee...",
                key="meal_items_input",
            )
            m_notes = st.text_input(
                "Notes / Restaurant (optional)",
                placeholder="e.g. Home cooked, A Cup of Joy, ~450 kcal...",
                key="meal_notes_input",
            )

            if st.form_submit_button("Save Meal"):
                if m_items.strip():
                    ws_m = get_meals_worksheet()
                    ws_m.append_row(
                        [
                            m_date.strftime("%Y-%m-%d"),
                            m_time.strftime("%H:%M"),
                            m_type,
                            m_items.strip(),
                            m_notes.strip(),
                        ]
                    )
                    st.cache_data.clear()
                    st.success("Meal logged!")
                    st.rerun()
                else:
                    st.warning("Please enter what you ate.")

    # 2. VIEW CONTROLS
    show_weigh_ins = st.toggle(
        "Show weigh-in rows in timeline",
        value=True,
        key="toggle_show_weigh_ins",
    )

    # 3. MERGE WEIGHTS AND MEALS WITH EXACT TIMESTAMPS
    timeline_entries = []

    # Weigh-ins: Morning check-in time (07:30 AM) with distinct styling data
    if show_weigh_ins and not df.empty:
        df_sorted_w = df.sort_values("Date").reset_index(drop=True)
        for i, w_row in df_sorted_w.iterrows():
            w_val = float(w_row["Weight"])
            w_date = w_row["Date"]
            w_datetime = datetime.datetime.combine(
                w_date.date(), datetime.time(7, 30)
            )

            if i > 0:
                prev_val = float(df_sorted_w["Weight"].iloc[i - 1])
                diff = w_val - prev_val
                if diff < 0:
                    notes_clean = f"▼ {abs(diff):.2f} kg"
                    delta_color = "#4ade80"  # Vibrant green
                elif diff > 0:
                    notes_clean = f"▲ +{diff:.2f} kg"
                    delta_color = "#f87171"  # Vibrant red
                else:
                    notes_clean = "— 0.00 kg"
                    delta_color = "#94a3b8"  # Slate gray
            else:
                notes_clean = "Baseline weigh-in"
                delta_color = "#94a3b8"

            timeline_entries.append(
                {
                    "DateTime": w_datetime,
                    "DateStr": w_date.strftime("%d %b %Y"),
                    "TimeStr": "07:30 AM",
                    "DisplayType": "⚖️ Weigh-in",
                    "Content": f"{w_val:.2f} kg",
                    "Notes": notes_clean,
                    "DeltaColor": delta_color,
                    "IsWeight": True,
                    "RawRow": None,
                    "Idx": i,
                }
            )

    # Meals: Use logged time
    if not df_meals.empty:
        for j, m_row in df_meals.iterrows():
            m_date = m_row["Date"]
            t_str = m_row["Time"] if m_row["Time"] else "12:00"

            try:
                t_parts = [int(p) for p in t_str.split(":")[:2]]
                t_obj = datetime.time(t_parts[0], t_parts[1])
            except Exception:
                t_obj = datetime.time(12, 0)

            m_datetime = datetime.datetime.combine(m_date.date(), t_obj)
            formatted_time = t_obj.strftime("%I:%M %p")

            timeline_entries.append(
                {
                    "DateTime": m_datetime,
                    "DateStr": m_date.strftime("%d %b %Y"),
                    "TimeStr": formatted_time,
                    "DisplayType": f"🍽️ {m_row['Meal']}",
                    "Content": m_row["Items"],
                    "Notes": m_row["Notes"] if m_row["Notes"] else "—",
                    "DeltaColor": "#94a3b8",
                    "IsWeight": False,
                    "RawRow": m_row,
                    "Idx": j,
                }
            )

    if not timeline_entries:
        st.info("No entries to display. Use the form above to log a meal.")
    else:
        # Strictly reverse-chronological by exact timestamp
        df_timeline = pd.DataFrame(timeline_entries).sort_values(
            by="DateTime", ascending=False
        )

        # Table Header
        h_date, h_time, h_type, h_items, h_notes, h_edit, h_del = st.columns(
            [1.2, 0.9, 1.2, 3.0, 2.1, 0.5, 0.5]
        )
        h_date.caption("**Date**")
        h_time.caption("**Time**")
        h_type.caption("**Type**")
        h_items.caption("**Details / Items**")
        h_notes.caption("**Net Impact / Notes**")
        h_edit.caption("")
        h_del.caption("")

        last_date = None

        for _, row in df_timeline.iterrows():
            entry_dt = row["DateTime"]
            entry_date_obj = entry_dt.date()
            date_iso = entry_dt.strftime("%Y-%m-%d")

            # 1. VISUAL SEPARATOR BETWEEN DIFFERENT DATES
            if last_date is not None and entry_date_obj != last_date:
                st.divider()

            last_date = entry_date_obj

            # 2. ACCENTED WEIGH-IN CARD (DISTINCT BACKGROUND)
            if row["IsWeight"]:
                st.markdown(
                    f"""
                    <div style="
                        display: grid;
                        grid-template-columns: 1.2fr 0.9fr 1.2fr 3.0fr 2.1fr 1.0fr;
                        align-items: center;
                        background: linear-gradient(90deg, rgba(30, 58, 138, 0.38) 0%, rgba(15, 23, 42, 0.55) 100%);
                        border: 1px solid rgba(59, 130, 246, 0.35);
                        border-left: 4px solid #38bdf8;
                        border-radius: 8px;
                        padding: 8px 12px;
                        margin: 4px 0 6px 0;
                        font-size: 0.95rem;
                    ">
                        <div style="color: #f1f5f9; font-weight: 500;">{row['DateStr']}</div>
                        <div style="color: #94a3b8; font-size: 0.88rem;">{row['TimeStr']}</div>
                        <div>
                            <span style="
                                background: rgba(56, 189, 248, 0.15);
                                color: #38bdf8;
                                border: 1px solid rgba(56, 189, 248, 0.4);
                                padding: 2px 8px;
                                border-radius: 6px;
                                font-size: 0.82rem;
                                font-weight: 600;
                            ">⚖️ Weigh-in</span>
                        </div>
                        <div style="color: #ffffff; font-weight: 700; font-size: 1.05rem;">
                            {row['Content']}
                        </div>
                        <div style="color: {row['DeltaColor']}; font-weight: 600; font-size: 0.92rem;">
                            {row['Notes']}
                        </div>
                        <div></div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
            else:
                # 3. REGULAR MEAL ROW (WITH INLINE EDIT & DELETE)
                c_date, c_time, c_type, c_items, c_notes, c_edit, c_del = (
                    st.columns(
                        [1.2, 0.9, 1.2, 3.0, 2.1, 0.5, 0.5],
                        vertical_alignment="center",
                    )
                )

                c_date.write(row["DateStr"])
                c_time.write(row["TimeStr"])
                c_type.write(f"**{row['RawRow']['Meal']}**")
                c_items.write(row["Content"])
                c_notes.write(row["Notes"])

                m_data = row["RawRow"]
                m_idx = row["Idx"]

                with c_edit:
                    with st.popover("✏️", help="Edit meal"):
                        st.caption("**Edit Meal**")
                        edit_d = st.date_input(
                            "Date",
                            value=entry_dt.date(),
                            key=f"tl_ed_{m_idx}",
                        )
                        edit_tm = st.time_input(
                            "Time",
                            value=entry_dt.time(),
                            key=f"tl_etm_{m_idx}",
                        )
                        meal_opts = [
                            "Breakfast",
                            "Lunch",
                            "Dinner",
                            "Snack",
                            "Drinks / Dessert",
                        ]
                        curr_opt_idx = (
                            meal_opts.index(m_data["Meal"])
                            if m_data["Meal"] in meal_opts
                            else 0
                        )
                        edit_t = st.selectbox(
                            "Meal",
                            meal_opts,
                            index=curr_opt_idx,
                            key=f"tl_et_{m_idx}",
                        )
                        edit_i = st.text_area(
                            "Items",
                            value=m_data["Items"],
                            key=f"tl_ei_{m_idx}",
                        )
                        edit_n = st.text_input(
                            "Notes",
                            value=m_data["Notes"],
                            key=f"tl_en_{m_idx}",
                        )

                        if st.button("Save", key=f"tl_es_{m_idx}"):
                            if edit_i.strip():
                                ws_m = get_meals_worksheet()
                                all_r = ws_m.get_all_values()
                                target_r = None

                                for r_i, r in enumerate(all_r[1:], start=2):
                                    if (
                                        len(r) >= 4
                                        and r[0].strip() == date_iso.strip()
                                        and r[2].strip()
                                        == m_data["Meal"].strip()
                                        and r[3].strip()
                                        == m_data["Items"].strip()
                                    ):
                                        target_r = r_i
                                        break

                                if target_r:
                                    ws_m.update(
                                        range_name=f"A{target_r}:E{target_r}",
                                        values=[
                                            [
                                                edit_d.strftime("%Y-%m-%d"),
                                                edit_tm.strftime("%H:%M"),
                                                edit_t,
                                                edit_i.strip(),
                                                edit_n.strip(),
                                            ]
                                        ],
                                    )
                                    st.cache_data.clear()
                                    st.rerun()

                with c_del:
                    with st.popover("🗑️", help="Delete meal"):
                        st.caption("Delete this meal?")
                        if st.button(
                            "Yes, Delete",
                            type="primary",
                            key=f"tl_del_{m_idx}",
                        ):
                            ws_m = get_meals_worksheet()
                            all_r = ws_m.get_all_values()
                            target_r = None

                            for r_i, r in enumerate(all_r[1:], start=2):
                                if (
                                    len(r) >= 4
                                    and r[0].strip() == date_iso.strip()
                                    and r[2].strip() == m_data["Meal"].strip()
                                    and r[3].strip() == m_data["Items"].strip()
                                ):
                                    target_r = r_i
                                    break

                            if target_r:
                                ws_m.delete_rows(target_r)
                                st.cache_data.clear()
                                st.rerun()