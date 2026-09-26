import datetime
import gspread
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components

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

    ws_w = sh.sheet1

    try:
        ws_n = sh.worksheet("Notes")
    except gspread.exceptions.WorksheetNotFound:
        ws_n = sh.add_worksheet(title="Notes", rows=100, cols=4)
        ws_n.append_row(["Date", "End Date", "Category", "Note"])
        return ws_w, ws_n

    headers = ws_n.row_values(1)
    if headers and "End Date" not in headers:
        all_rows = ws_n.get_all_values()
        if all_rows:
            new_rows = [["Date", "End Date", "Category", "Note"]]
            for r in all_rows[1:]:
                d = r[0] if len(r) > 0 else ""
                if len(r) >= 3 and "Category" in headers:
                    cat = r[1]
                    note = r[2] if len(r) > 2 else ""
                    new_rows.append([d, d, cat, note])
                elif len(r) >= 2:
                    note = r[1]
                    new_rows.append([d, d, "Note", note])
                else:
                    new_rows.append([d, d, "Note", ""])
            ws_n.clear()
            ws_n.update(range_name=f"A1:D{len(new_rows)}", values=new_rows)

    return ws_w, ws_n


@st.cache_data(ttl=60)
def load_notes_data():
    _, ws_n = get_worksheets()
    records = ws_n.get_all_records()
    if not records:
        return pd.DataFrame(columns=["Date", "End Date", "Category", "Note"])
    df_n = pd.DataFrame(records)
    df_n["Date"] = pd.to_datetime(df_n["Date"], errors="coerce")
    if "End Date" not in df_n.columns:
        df_n["End Date"] = df_n["Date"]
    else:
        df_n["End Date"] = pd.to_datetime(df_n["End Date"], errors="coerce").fillna(df_n["Date"])
    df_n = df_n.dropna(subset=["Date"]).copy()
    # Ensure End Date is at least Date
    df_n["End Date"] = df_n[["Date", "End Date"]].max(axis=1)
    if "Category" not in df_n.columns:
        df_n["Category"] = "Note"
    df_n["Category"] = df_n["Category"].astype(str).str.strip()
    df_n["Note"] = df_n["Note"].astype(str).str.strip()
    return df_n

@st.cache_data(ttl=60)
def load_weight_data():
    ws_weights, _ = get_worksheets()
    records = ws_weights.get_all_records()
    df = pd.DataFrame(records)
    df["Date"] = pd.to_datetime(df["Date"])
    df["Weight"] = pd.to_numeric(df["Weight"])
    return df.sort_values("Date").reset_index(drop=True)

def get_meals_worksheet():
    creds = dict(st.secrets["gcp_service_account"])
    if "\\n" in creds["private_key"]:
        creds["private_key"] = creds["private_key"].replace("\\n", "\n")

    gc = gspread.service_account_from_dict(creds)
    sh = gc.open_by_key(SHEET_ID)

    try:
        ws = sh.worksheet("Meals")
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.add_worksheet(title="Meals", rows=100, cols=6)
        ws.append_row(["Date", "Time", "Meal", "Source", "Items", "Notes"])
        return ws

    # Automatic migration: if existing sheet has 5 columns without 'Source', insert it
    headers = ws.row_values(1)
    if headers and "Source" not in headers:
        all_rows = ws.get_all_values()
        if all_rows:
            new_rows = [["Date", "Time", "Meal", "Source", "Items", "Notes"]]
            for r in all_rows[1:]:
                d = r[0] if len(r) > 0 else ""
                t = r[1] if len(r) > 1 else "12:00"
                m = r[2] if len(r) > 2 else ""
                items = r[3] if len(r) > 3 else ""
                old_note = r[4] if len(r) > 4 else ""
                if old_note.strip().lower() in ["im a bakri", "omw to become a dhokla"]:
                    source = "Home Cooked"
                    note = old_note.strip()
                elif old_note.strip():
                    source = old_note.strip()
                    note = ""
                else:
                    source = "Home Cooked"
                    note = ""
                new_rows.append([d, t, m, source, items, note])

            if ws.col_count < 6:
                ws.resize(cols=6)

            ws.clear()
            ws.update(
                range_name=f"A1:F{len(new_rows)}",
                values=new_rows,
            )

    return ws


@st.cache_data(ttl=60)
def load_meals_data():
    ws_meals = get_meals_worksheet()
    records = ws_meals.get_all_records()
    if not records:
        return pd.DataFrame(
            columns=["Date", "Time", "Meal", "Source", "Items", "Notes"]
        )
    df_m = pd.DataFrame(records)
    df_m["Date"] = pd.to_datetime(df_m["Date"])
    if "Time" not in df_m.columns:
        df_m["Time"] = "12:00"
    df_m["Time"] = df_m["Time"].astype(str).str.strip()
    df_m["Meal"] = df_m["Meal"].astype(str)
    if "Source" not in df_m.columns:
        df_m["Source"] = "Home Cooked"
    df_m["Source"] = df_m["Source"].astype(str).str.strip()
    df_m["Items"] = df_m["Items"].astype(str)
    if "Notes" not in df_m.columns:
        df_m["Notes"] = ""
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
    ["📊 Progress Chart", "📝 Notes", "🍽️ Food Log"]
)

# ----------------------------------------------------
# TAB 1: INTERACTIVE PLOTLY CHART
# ----------------------------------------------------
with view_tab_chart:
    # 1. Compute Full History Metrics (Preserves accurate EWMA & all-time stars)
    df["Trend"] = (
        df["Weight"]
        .ewm(
            halflife=pd.Timedelta(days=28),  # type: ignore[arg-type]
            times=df["Date"],
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
            (~df_notes["Category"].isin(["Japan", "Steps"]))
            & (df_notes["Date"] >= start_date)
            & (df_notes["Date"] <= end_date)
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
                    src_tag = (
                        f" <i>[{r['Source']}]</i>"
                        if ("Source" in r and r["Source"] and r["Source"] != "—")
                        else ""
                    )
                    note_tag = (
                        f" <i>({r['Notes']})</i>"
                        if ("Notes" in r and r["Notes"] and r["Notes"] != "—")
                        else ""
                    )
                    entry = f"• <b>{r['Meal']}</b>{src_tag}: {r['Items']}{note_tag}"
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

    # ----------------------------------------------------
    # 1. JAPAN TRACKING (Light Pink Vertical Shading across duration)
    # ----------------------------------------------------
    if not df_notes.empty:
        df_japan = (
            df_notes[df_notes["Category"] == "Japan"]
            .sort_values("Date")
            .copy()
        )
        if not df_japan.empty:
            japan_intervals = []
            for _, j_row in df_japan.iterrows():
                s = j_row["Date"].date()
                e = j_row["End Date"].date()
                if s > e:
                    s, e = e, s
                japan_intervals.append((s, e))

            if japan_intervals:
                japan_intervals.sort(key=lambda x: x[0])
                merged_ranges = [japan_intervals[0]]
                for s, e in japan_intervals[1:]:
                    prev_s, prev_e = merged_ranges[-1]
                    if s <= prev_e + datetime.timedelta(days=1):
                        merged_ranges[-1] = (prev_s, max(prev_e, e))
                    else:
                        merged_ranges.append((s, e))

                for r_start, r_end in merged_ranges:
                    # Pad edges by 12 hours so the full day/duration is shaded
                    x0_val = pd.to_datetime(r_start) - pd.Timedelta(hours=12)
                    x1_val = pd.to_datetime(r_end) + pd.Timedelta(hours=12)
                    fig.add_vrect(
                        x0=x0_val,
                        x1=x1_val,
                        fillcolor="rgba(251, 113, 133, 0.18)",  # Soft light pink
                        layer="below",
                        line_width=0,
                    )

    # ----------------------------------------------------
    # 2. STEP FOOTPRINTS ACROSS DURATION (1 Footprint per 10k Steps)
    # ----------------------------------------------------
    if not df_notes.empty and not df_visible.empty:
        import numpy as np

        df_steps_log = df_notes[
            (df_notes["Category"] == "Steps")
            & (df_notes["End Date"] >= start_date)
            & (df_notes["Date"] <= end_date)
        ].copy()

        if not df_steps_log.empty:
            ts_vis = [t.timestamp() for t in df_visible["Date"]]
            wt_vis = df_visible["Weight"].values
            first_step_trace = True

            for _, s_row in df_steps_log.iterrows():
                raw_note = s_row["Note"]
                digits = "".join(filter(str.isdigit, raw_note))
                if not digits:
                    continue
                num_steps = int(digits)
                num_footprints = max(1, round(num_steps / 10000))

                s_start = s_row["Date"]
                s_end = s_row["End Date"]
                if s_start > s_end:
                    s_start, s_end = s_end, s_start

                duration_days = (s_end.date() - s_start.date()).days + 1

                # Clean optional note description
                extra_desc = ""
                if "(" in raw_note and ")" in raw_note:
                    extra_desc = raw_note[raw_note.find("(") + 1 : raw_note.rfind(")")]

                hover_card = (
                    f"<b>👟 Steps Duration:</b> {num_steps:,} steps<br>"
                    f"<b>Period:</b> {s_start.strftime('%d %b')} — {s_end.strftime('%d %b %Y')} ({duration_days} days)<br>"
                    f"<b>Steps:</b> {num_footprints} x 10k steps"
                )
                if extra_desc:
                    hover_card += f"<br><i>\"{extra_desc}\"</i>"

                k = min(num_footprints, 8)
                if duration_days > 1 and s_start != s_end and k > 1:
                    fp_dates = [
                        s_start + (s_end - s_start) * (i / (k - 1))
                        for i in range(k)
                    ]
                    fp_texts = ["👣"] * k
                else:
                    fp_dates = [s_start + (s_end - s_start) / 2]
                    fp_texts = ["👣" * min(num_footprints, 5)]

                # Only footprints at the top of the graph space (no brackets, no step count text)
                fig.add_trace(
                    go.Scatter(
                        x=fp_dates,
                        y=[0.93] * len(fp_dates),
                        yaxis="y2",
                        mode="text",
                        text=fp_texts,
                        textposition="middle center",
                        textfont=dict(size=18),
                        name="Weekly Steps",
                        legendgroup="steps",
                        showlegend=first_step_trace,
                        customdata=[hover_card] * len(fp_dates),
                        hovertemplate="%{customdata}<extra></extra>",
                    )
                )
                first_step_trace = False

    # Add headroom to reversed y-axis so weight curve stays below the top steps track
    if not df_visible.empty:
        min_wt = float(df_visible["Weight"].min())
        max_wt = float(df_visible["Weight"].max())
        wt_span = max(max_wt - min_wt, 2.0)
        pad_top = max(1.8, wt_span * 0.25)
        pad_bottom = max(1.0, wt_span * 0.12)
        primary_y_range = [max_wt + pad_bottom, min_wt - pad_top]
    else:
        primary_y_range = None

    fig.update_layout(
        yaxis=dict(
            autorange="reversed" if primary_y_range is None else False,
            range=primary_y_range,
            title="Weight (kg)",
            gridcolor="#1e293b",
            zeroline=False,
        ),
        yaxis2=dict(
            overlaying="y",
            range=[0, 1],
            visible=False,
            fixedrange=True,
        ),
        xaxis=dict(
            title="",
            gridcolor="#1e293b",
            showgrid=True,
            range=[start_date, end_date],
        ),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=20, r=20, t=35, b=20),
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

    # Replace 'Aa' text mode icon in Plotly legend with footprints 👣
    components.html(
        """
        <script>
        (function() {
            if (window.frameElement) {
                window.frameElement.style.display = 'none';
            }
            function updateStepLegend() {
                try {
                    const p = window.parent.document;
                    if (!p) return;
                    const pointTexts = p.querySelectorAll('.legendpoints .pointtext text');
                    pointTexts.forEach(el => {
                        if (el.textContent === 'Aa' || el.innerHTML.includes('Aa')) {
                            el.textContent = '👣';
                            el.setAttribute('font-size', '15px');
                            el.style.fontSize = '15px';
                            el.setAttribute('dy', '0.35em');
                        }
                    });
                } catch (e) {}
            }
            updateStepLegend();
            try {
                const p = window.parent.document;
                if (p && p.body && !window._steps_legend_obs) {
                    window._steps_legend_obs = new MutationObserver(updateStepLegend);
                    window._steps_legend_obs.observe(p.body, { childList: true, subtree: true });
                }
            } catch (e) {}
            let count = 0;
            const timer = setInterval(() => {
                updateStepLegend();
                count++;
                if (count > 25) clearInterval(timer);
            }, 200);
        })();
        </script>
        """,
        height=0,
        width=0,
    )

# ----------------------------------------------------
# TAB 2: NOTES, JAPAN & STEP LOGS
# ----------------------------------------------------
with view_tab_notes:
    st.subheader("Lily's Notes & Milestone Tracker")
    
    # 1. ADD ENTRY FORM WITH CATEGORY-SPECIFIC CONTROLS
    with st.expander("➕ Add a note", expanded=False):
        col_cat_sel, _ = st.columns([1.2, 1.8])
        selected_cat = col_cat_sel.selectbox(
            "Category",
            ["Japan", "Steps", "Note"],
            format_func=lambda c: (
                "🇯🇵 Japan"
                if c == "Japan"
                else (
                    "👟 Weekly Steps"
                    if c == "Steps"
                    else "📝 General Note"
                )
            ),
            key="add_cat_select",
        )

        if selected_cat == "Japan":
            with st.form("form_add_japan", clear_on_submit=True):
                col_d1, col_n1 = st.columns([1.2, 1.8])
                default_j_start = datetime.date.today() - datetime.timedelta(days=4)
                default_j_end = datetime.date.today()
                japan_dates = col_d1.date_input(
                    "Duration (Click Start Date, then End Date)",
                    value=(default_j_start, default_j_end),
                    help="Select the start and end dates of the japan duration.",
                    key="add_j_dates",
                )
                japan_note = col_n1.text_input(
                    "Notes / Symptoms (optional)",
                    placeholder="e.g. Day 1 cramps, light flow, fatigue...",
                    key="add_j_note",
                )
                if st.form_submit_button("Save Japan Duration", type="primary"):
                    if isinstance(japan_dates, (tuple, list)) and len(japan_dates) == 2:
                        j_s, j_e = sorted(japan_dates)
                    elif isinstance(japan_dates, (tuple, list)) and len(japan_dates) == 1:
                        j_s = j_e = japan_dates[0]
                    else:
                        j_s = j_e = datetime.date.today()

                    j_text = (
                        japan_note.strip()
                        if japan_note.strip()
                        else "Japan logged"
                    )
                    _, ws_n = get_worksheets()
                    ws_n.append_row(
                        [
                            j_s.strftime("%Y-%m-%d"),
                            j_e.strftime("%Y-%m-%d"),
                            "Japan",
                            j_text,
                        ]
                    )
                    st.cache_data.clear()
                    st.success(
                        f"Japan duration ({j_s.strftime('%d %b')} – {j_e.strftime('%d %b %Y')}) logged with pink shading!"
                    )
                    st.rerun()

        elif selected_cat == "Steps":
            with st.form("form_add_steps", clear_on_submit=True):
                col_d2, col_s2 = st.columns([1.2, 1.0])
                default_s_start = datetime.date.today() - datetime.timedelta(days=6)
                default_s_end = datetime.date.today()
                steps_dates = col_d2.date_input(
                    "Duration (Click Start Date, then End Date)",
                    value=(default_s_start, default_s_end),
                    help="Select the week or date range for these steps.",
                    key="add_s_dates",
                )
                steps_val = col_s2.number_input(
                    "Total Steps in Duration",
                    min_value=1000,
                    max_value=300000,
                    value=50000,
                    step=1000,
                    help="1 footprint 👣 will be added on the chart for every 10,000 steps.",
                    key="add_s_val",
                )
                extra_step_note = st.text_input(
                    "Notes / Activities (optional)",
                    placeholder="e.g. 7k daily average, long Sunday trail hike...",
                    key="add_s_note",
                )
                if st.form_submit_button("Save Steps Duration", type="primary"):
                    if isinstance(steps_dates, (tuple, list)) and len(steps_dates) == 2:
                        s_s, s_e = sorted(steps_dates)
                    elif isinstance(steps_dates, (tuple, list)) and len(steps_dates) == 1:
                        s_s = s_e = steps_dates[0]
                    else:
                        s_s = s_e = datetime.date.today()

                    step_text = f"{steps_val:,} steps"
                    if extra_step_note.strip():
                        step_text += f" ({extra_step_note.strip()})"
                    _, ws_n = get_worksheets()
                    ws_n.append_row(
                        [
                            s_s.strftime("%Y-%m-%d"),
                            s_e.strftime("%Y-%m-%d"),
                            "Steps",
                            step_text,
                        ]
                    )
                    st.cache_data.clear()
                    st.success(
                        f"Steps duration ({steps_val:,} steps from {s_s.strftime('%d %b')} – {s_e.strftime('%d %b %Y')}) logged with footprints!"
                    )
                    st.rerun()

        else:
            with st.form("form_add_note", clear_on_submit=True):
                col_d3, _ = st.columns([1.2, 1.8])
                note_date = col_d3.date_input(
                    "Date", value=datetime.date.today(), key="add_n_date"
                )
                standard_note = st.text_area(
                    "Note",
                    placeholder="e.g. Swapped sugary drinks for water, started morning walks...",
                    key="add_n_text",
                )
                if st.form_submit_button("Save Note", type="primary"):
                    if standard_note.strip():
                        _, ws_n = get_worksheets()
                        d_str = note_date.strftime("%Y-%m-%d")
                        ws_n.append_row(
                            [
                                d_str,
                                d_str,
                                "Note",
                                standard_note.strip(),
                            ]
                        )
                        st.cache_data.clear()
                        st.success("Note saved!")
                        st.rerun()
                    else:
                        st.warning("Please type a note before saving.")

    # 2. INLINE TABLE WITH EDIT & DELETE POPUPS
    if df_notes.empty:
        st.info("No entries recorded yet. Add your first log above.")
    else:
        # Table Header
        h_date, h_cat, h_note, h_before, h_after, h_imp, h_edit, h_del = (
            st.columns([1.6, 1.1, 2.5, 1.6, 1.6, 1.1, 0.5, 0.5])
        )
        h_date.caption("**Date / Duration**")
        h_cat.caption("**Category**")
        h_note.caption("**Details**")
        h_before.caption("**Weight Before**")
        h_after.caption("**Weight After**")
        h_imp.caption("**Impact**")
        h_edit.caption("")
        h_del.caption("")

        sorted_notes = (
            df_notes.sort_values("Date", ascending=False)
            .reset_index(drop=True)
        )

        for idx, n_row in sorted_notes.iterrows():
            n_start = n_row["Date"]
            n_end = n_row["End Date"]
            n_start_str = n_start.strftime("%Y-%m-%d")
            n_end_str = n_end.strftime("%Y-%m-%d")
            n_cat = n_row["Category"]
            n_text = n_row["Note"]

            # Weight calculations based on duration
            weights_before = df[df["Date"] <= n_start]
            wt_before = (
                weights_before["Weight"].iloc[-1]
                if not weights_before.empty
                else None
            )
            date_before = (
                weights_before["Date"].iloc[-1].strftime("%d %b")
                if not weights_before.empty
                else ""
            )

            if n_start.date() == n_end.date():
                weights_after = df[df["Date"] > n_start]
            else:
                weights_after = df[df["Date"] >= n_end]

            wt_after = (
                weights_after["Weight"].iloc[0]
                if not weights_after.empty
                else None
            )
            date_after = (
                weights_after["Date"].iloc[0].strftime("%d %b")
                if not weights_after.empty
                else ""
            )

            if wt_before is not None and wt_after is not None:
                net_change = wt_after - wt_before
                diff_display = f"{net_change:+.2f} kg"
            else:
                diff_display = "—"

            c_date, c_cat, c_note, c_before, c_after, c_imp, c_edit, c_del = (
                st.columns(
                    [1.6, 1.1, 2.5, 1.6, 1.6, 1.1, 0.5, 0.5],
                    vertical_alignment="center",
                )
            )

            # Format Date / Duration display
            if n_start.date() == n_end.date():
                c_date.write(n_start.strftime("%d %b %Y"))
            elif n_start.year == n_end.year:
                c_date.write(
                    f"{n_start.strftime('%d %b')} – {n_end.strftime('%d %b %Y')}"
                )
            else:
                c_date.write(
                    f"{n_start.strftime('%d %b %Y')} – {n_end.strftime('%d %b %Y')}"
                )

            # Category badge styling
            if n_cat == "Japan":
                c_cat.markdown(":red-background[🇯🇵 Japan]")
            elif n_cat == "Steps":
                c_cat.markdown(":blue-background[👟 Steps]")
            else:
                c_cat.markdown("📝 Note")

            c_note.write(n_text)
            c_before.write(
                f"{wt_before:.2f} kg ({date_before})" if wt_before else "—"
            )
            c_after.write(
                f"{wt_after:.2f} kg ({date_after})" if wt_after else "—"
            )
            c_imp.write(diff_display)

            # EDIT POPOVER
            with c_edit:
                with st.popover("✏️", help="Edit entry"):
                    st.caption("**Edit Entry**")
                    if n_cat in ["Japan", "Steps"]:
                        ed_dates = st.date_input(
                            "Duration (Start — End)",
                            value=(n_start.date(), n_end.date()),
                            key=f"ed_nd_{idx}",
                        )
                    else:
                        ed_dates = st.date_input(
                            "Date",
                            value=n_start.date(),
                            key=f"ed_nd_{idx}",
                        )

                    cat_options = ["Japan", "Steps", "Note"]
                    cat_idx = (
                        cat_options.index(n_cat)
                        if n_cat in cat_options
                        else 0
                    )
                    new_cat = st.selectbox(
                        "Category",
                        cat_options,
                        index=cat_idx,
                        key=f"ed_nc_{idx}",
                    )
                    new_text = st.text_area(
                        "Details / Note", value=n_text, key=f"ed_nt_{idx}"
                    )

                    if st.button("Save Changes", key=f"save_ed_n_{idx}"):
                        if new_text.strip():
                            if isinstance(ed_dates, (tuple, list)):
                                if len(ed_dates) >= 2:
                                    ed_s, ed_e = sorted(ed_dates[:2])
                                elif len(ed_dates) == 1:
                                    ed_s = ed_e = ed_dates[0]
                                else:
                                    ed_s = ed_e = n_start.date()
                            elif isinstance(ed_dates, datetime.date):
                                ed_s = ed_e = ed_dates
                            else:
                                ed_s = ed_e = n_start.date()

                            _, ws_n = get_worksheets()
                            all_r = ws_n.get_all_values()
                            target_r = None

                            for r_i, r in enumerate(all_r[1:], start=2):
                                if len(r) >= 4:
                                    match = (
                                        r[0].strip() == n_start_str
                                        and r[1].strip() == n_end_str
                                        and r[2].strip() == n_cat.strip()
                                        and r[3].strip() == n_text.strip()
                                    )
                                elif len(r) >= 3:
                                    match = (
                                        r[0].strip() == n_start_str
                                        and r[1].strip() == n_cat.strip()
                                        and r[2].strip() == n_text.strip()
                                    )
                                else:
                                    match = False

                                if match:
                                    target_r = r_i
                                    break

                            if target_r:
                                ws_n.update(
                                    range_name=f"A{target_r}:D{target_r}",
                                    values=[
                                        [
                                            ed_s.strftime("%Y-%m-%d"),
                                            ed_e.strftime("%Y-%m-%d"),
                                            new_cat,
                                            new_text.strip(),
                                        ]
                                    ],
                                )
                                st.cache_data.clear()
                                st.rerun()

            # DELETE POPOVER
            with c_del:
                with st.popover("🗑️", help="Delete entry"):
                    st.caption(f"Delete this {n_cat.lower()} entry?")
                    if st.button(
                        "Yes, Delete",
                        type="primary",
                        key=f"del_n_{idx}",
                    ):
                        _, ws_n = get_worksheets()
                        all_r = ws_n.get_all_values()
                        target_r = None

                        for r_i, r in enumerate(all_r[1:], start=2):
                            if len(r) >= 4:
                                match = (
                                    r[0].strip() == n_start_str
                                    and r[1].strip() == n_end_str
                                    and r[2].strip() == n_cat.strip()
                                    and r[3].strip() == n_text.strip()
                                )
                            elif len(r) >= 3:
                                match = (
                                    r[0].strip() == n_start_str
                                    and r[1].strip() == n_cat.strip()
                                    and r[2].strip() == n_text.strip()
                                )
                            else:
                                match = False

                            if match:
                                target_r = r_i
                                break

                        if target_r:
                            ws_n.delete_rows(target_r)
                            st.cache_data.clear()
                            st.rerun()

# ----------------------------------------------------
# TAB 3: DAILY FOOD & WEIGHT TIMELINE (EXACT TIME SORT)
# ----------------------------------------------------
with view_tab_food:
    st.subheader("Daily Food & Weight Timeline")
    st.caption("A chronological log of morning weigh-ins and meals.")

    # Collect unique past sources for memory dropdown (most frequent first)
    existing_sources = []
    if not df_meals.empty and "Source" in df_meals.columns:
        seen = set()
        val_counts = df_meals["Source"].astype(str).str.strip().value_counts()
        for s_val in val_counts.index:
            s_clean = s_val.strip()
            if s_clean and s_clean not in ["—", "-", "None", "nan"]:
                s_key = s_clean.lower()
                if s_key not in seen:
                    seen.add(s_key)
                    existing_sources.append(s_clean)

    if not any(s.lower() == "home cooked" for s in existing_sources):
        existing_sources.insert(0, "Home Cooked")

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
                "Food / Items *",
                placeholder="e.g. Schezwan Noodles, Paneer roll, coffee...",
                key="meal_items_input",
            )

            col_s, col_n = st.columns([1.3, 1.7])
            m_source = col_s.selectbox(
                "Source * (Mandatory)",
                options=existing_sources,
                accept_new_options=True,
                help="Select from previous sources or type to search / add a new one (e.g. Home Cooked, Wow Momo).",
                key="meal_source_input",
            )
            m_notes = col_n.text_input(
                "Notes (optional)",
                placeholder="e.g. high protein, light portion, ~450 kcal...",
                key="meal_notes_input",
            )

            if st.form_submit_button("Save Meal", type="primary"):
                src_val = str(m_source).strip() if m_source else ""
                if not src_val:
                    st.warning("Please specify the Source (mandatory, e.g. Home Cooked).")
                elif not m_items.strip():
                    st.warning("Please enter what you ate.")
                else:
                    ws_m = get_meals_worksheet()
                    ws_m.append_row(
                        [
                            m_date.strftime("%Y-%m-%d"),
                            m_time.strftime("%H:%M"),
                            m_type,
                            src_val,
                            m_items.strip(),
                            m_notes.strip(),
                        ]
                    )
                    st.cache_data.clear()
                    st.success(f"Meal logged from {src_val}!")
                    st.rerun()

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
        for i, (_, w_row) in enumerate(df_sorted_w.iterrows()):
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
                    "Source": "—",
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

            m_src = (
                str(m_row["Source"]).strip()
                if ("Source" in m_row and pd.notna(m_row["Source"]))
                else "—"
            )
            m_notes_str = (
                str(m_row["Notes"]).strip()
                if ("Notes" in m_row and pd.notna(m_row["Notes"]))
                else "—"
            )

            timeline_entries.append(
                {
                    "DateTime": m_datetime,
                    "DateStr": m_date.strftime("%d %b %Y"),
                    "TimeStr": formatted_time,
                    "DisplayType": f"🍽️ {m_row['Meal']}",
                    "Source": m_src if m_src else "—",
                    "Content": m_row["Items"],
                    "Notes": m_notes_str if m_notes_str else "—",
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
        h_date, h_time, h_type, h_src, h_items, h_notes, h_edit, h_del = st.columns(
            [1.1, 0.9, 1.0, 1.4, 2.7, 1.7, 0.4, 0.4]
        )
        h_date.caption("**Date**")
        h_time.caption("**Time**")
        h_type.caption("**Type**")
        h_src.caption("**Source**")
        h_items.caption("**Details / Items**")
        h_notes.caption("**Notes**")
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
                        grid-template-columns: 1.1fr 0.9fr 1.0fr 1.4fr 2.7fr 1.7fr 0.8fr;
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
                        <div style="color: #64748b; font-size: 0.85rem;">—</div>
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
                c_date, c_time, c_type, c_src, c_items, c_notes, c_edit, c_del = (
                    st.columns(
                        [1.1, 0.9, 1.0, 1.4, 2.7, 1.7, 0.4, 0.4],
                        vertical_alignment="center",
                    )
                )

                c_date.write(row["DateStr"])
                c_time.write(row["TimeStr"])
                c_type.write(f"**{row['RawRow']['Meal']}**")

                src_val = str(row["Source"]).strip()
                if "home" in src_val.lower():
                    c_src.markdown(f":green-background[🏠 {src_val}]")
                elif src_val and src_val != "—":
                    c_src.markdown(f":orange-background[🏪 {src_val}]")
                else:
                    c_src.write("—")

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

                        curr_src = (
                            str(m_data["Source"]).strip()
                            if ("Source" in m_data and pd.notna(m_data["Source"]))
                            else ""
                        )
                        edit_src_opts = list(existing_sources)
                        if curr_src and curr_src not in edit_src_opts:
                            edit_src_opts.insert(0, curr_src)
                        curr_src_idx = (
                            edit_src_opts.index(curr_src)
                            if curr_src in edit_src_opts
                            else 0
                        )
                        edit_src = st.selectbox(
                            "Source *",
                            options=edit_src_opts,
                            index=curr_src_idx,
                            accept_new_options=True,
                            key=f"tl_esrc_{m_idx}",
                        )

                        edit_i = st.text_area(
                            "Items",
                            value=m_data["Items"],
                            key=f"tl_ei_{m_idx}",
                        )
                        edit_n = st.text_input(
                            "Notes",
                            value=(
                                str(m_data["Notes"])
                                if ("Notes" in m_data and pd.notna(m_data["Notes"]))
                                else ""
                            ),
                            key=f"tl_en_{m_idx}",
                        )

                        if st.button("Save", key=f"tl_es_{m_idx}"):
                            src_clean = str(edit_src).strip() if edit_src else ""
                            if not src_clean:
                                st.warning("Source cannot be empty.")
                            elif not edit_i.strip():
                                st.warning("Items cannot be empty.")
                            else:
                                ws_m = get_meals_worksheet()
                                all_r = ws_m.get_all_values()
                                target_r = None

                                for r_i, r in enumerate(all_r[1:], start=2):
                                    if len(r) >= 5:
                                        match = (
                                            r[0].strip() == date_iso.strip()
                                            and r[2].strip()
                                            == m_data["Meal"].strip()
                                            and r[4].strip()
                                            == m_data["Items"].strip()
                                        )
                                    elif len(r) >= 4:
                                        match = (
                                            r[0].strip() == date_iso.strip()
                                            and r[2].strip()
                                            == m_data["Meal"].strip()
                                            and r[3].strip()
                                            == m_data["Items"].strip()
                                        )
                                    else:
                                        match = False

                                    if match:
                                        target_r = r_i
                                        break

                                if target_r:
                                    ws_m.update(
                                        range_name=f"A{target_r}:F{target_r}",
                                        values=[
                                            [
                                                edit_d.strftime("%Y-%m-%d"),
                                                edit_tm.strftime("%H:%M"),
                                                edit_t,
                                                src_clean,
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
                                if len(r) >= 5:
                                    match = (
                                        r[0].strip() == date_iso.strip()
                                        and r[2].strip()
                                        == m_data["Meal"].strip()
                                        and r[4].strip()
                                        == m_data["Items"].strip()
                                    )
                                elif len(r) >= 4:
                                    match = (
                                        r[0].strip() == date_iso.strip()
                                        and r[2].strip()
                                        == m_data["Meal"].strip()
                                        and r[3].strip()
                                        == m_data["Items"].strip()
                                    )
                                else:
                                    match = False

                                if match:
                                    target_r = r_i
                                    break

                            if target_r:
                                ws_m.delete_rows(target_r)
                                st.cache_data.clear()
                                st.rerun()