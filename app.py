from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from expense_dashboard.categories import CATEGORY_MAP, CATEGORY_TYPES
from expense_dashboard.db import (
    add_transaction,
    add_obligation,
    apply_category_matches,
    connect,
    delete_obligation,
    init_db,
    ignore_transaction,
    get_setting,
    load_obligations,
    load_transactions,
    seed_obligations,
    set_setting,
    split_transaction,
    sync_debt_details,
    update_obligation,
    update_transaction,
    upsert_transactions,
)
from expense_dashboard.debt_payoff import simulate_debt_payoff
from expense_dashboard.importer import clean_transaction_file, load_transaction_folder
from expense_dashboard.logging_config import configure_logging
from expense_dashboard.matching import match_workbook_categories
from expense_dashboard.workbook import (
    MONTH_SHEETS,
    WORKBOOK_PATH,
    extract_month_transactions,
    extract_setup_obligations,
)


LOG_PATH = configure_logging()
logger = logging.getLogger(__name__)
logger.info("App script loaded")

st.set_page_config(
    page_title="Finance Dashboard",
    layout="wide",
    initial_sidebar_state="auto",
)


def apply_responsive_styles() -> None:
    st.markdown(
        """
        <style>
        .block-container {
            padding-top: 1.45rem;
            padding-bottom: 2rem;
            max-width: 1500px;
        }

        h1 {
            padding-top: 0.15rem;
        }

        div[data-testid="stMetric"] {
            border: 1px solid rgba(49, 51, 63, 0.12);
            border-radius: 8px;
            padding: 0.2rem 0.4rem;
            background: rgba(250, 250, 250, 0.65);
        }

        div[data-testid="stMetricLabel"] p {
            font-size: 0.7rem;
            line-height: 1.1;
        }

        div[data-testid="stMetricValue"] > div {
            font-size: 1.05rem;
            line-height: 1.15;
        }

        .unpaid-panel-spacer {
            height: 2.85rem;
        }

        section[data-testid="stSidebar"] .stCaptionContainer {
            font-size: 0.78rem;
        }

        div[data-testid="stForm"] {
            border-radius: 8px;
        }

        div.stButton > button,
        div[data-testid="stFormSubmitButton"] button {
            width: 100%;
        }

        @media (max-width: 760px) {
            .block-container {
                padding-left: 0.75rem;
                padding-right: 0.75rem;
                padding-top: 1.25rem;
            }

            h1, h2, h3 {
                line-height: 1.15;
            }

            div[data-testid="stMetric"] {
                padding: 0.16rem 0.34rem;
            }

            div[data-testid="stMetricValue"] > div {
                font-size: 0.92rem;
            }

            div[data-testid="stMetricLabel"] p {
                font-size: 0.64rem;
            }

            .unpaid-panel-spacer {
                height: 0.35rem;
            }

            div[data-testid="stExpander"] details {
                border-radius: 8px;
            }

            div[data-testid="stDataFrame"] {
                font-size: 0.84rem;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def month_options(df: pd.DataFrame) -> list[str]:
    if df.empty:
        return []
    months = pd.to_datetime(df["date"]).dt.to_period("M").astype(str)
    return sorted(months.unique(), reverse=True)


def display_month(month_value: str) -> str:
    return pd.Period(month_value).strftime("%B %Y")


def filter_period(df: pd.DataFrame, period_mode: str, selected_month: str) -> pd.DataFrame:
    if df.empty or period_mode == "Full year":
        return df
    dates = pd.to_datetime(df["date"])
    return df[dates.dt.to_period("M").astype(str) == selected_month]


def build_category_map(obligations: pd.DataFrame) -> dict[str, list[str]]:
    category_map = {key: list(value) for key, value in CATEGORY_MAP.items()}
    for category_type in CATEGORY_TYPES:
        names = (
            obligations[obligations["category_type"] == category_type]["name"]
            .dropna()
            .astype(str)
            .tolist()
        )
        if names:
            category_map[category_type] = list(dict.fromkeys(names))
    return category_map


def category_options(category_type: str, category_map: dict[str, list[str]]) -> list[str]:
    if category_type == "Uncategorized":
        return ["Uncategorized"]
    return category_map.get(category_type, []) or ["Uncategorized"]


def nullable_category(value: str) -> str | None:
    return None if value == "Uncategorized" else value


def label_for_transaction(row: pd.Series) -> str:
    description = str(row["description"])
    if len(description) > 70:
        description = f"{description[:67]}..."
    return f"{row['date']} | ${row['amount']:,.2f} | {description}"


def transaction_table_height(row_count: int) -> int:
    if row_count <= 0:
        return 320
    return max(360, min(1400, 38 * (row_count + 1)))


def compact_table_height(row_count: int, default_height: int = 420) -> int:
    if row_count <= 0:
        return 160
    return min(default_height, max(150, 38 * (row_count + 1)))


def clipped_text(value: object, limit: int = 90) -> str:
    text = str(value or "")
    return text if len(text) <= limit else f"{text[: limit - 3]}..."


def apply_drilldown(df: pd.DataFrame) -> pd.DataFrame:
    drilldown = st.session_state.get("drilldown")
    if not drilldown:
        return df
    category_type = drilldown.get("category_type")
    category = drilldown.get("category")
    filtered = df
    if category_type:
        filtered = filtered[filtered["category_type"] == category_type]
    if category:
        filtered = filtered[filtered["category"] == category]
    return filtered


def period_obligations(
    obligations: pd.DataFrame,
    period_mode: str,
    selected_month: str,
) -> pd.DataFrame:
    tracked_types = [
        "Income",
        "Variable Expenses",
        "Monthly Bills",
        "Debt",
        "Savings",
        "Non-Monthly Bills",
    ]
    budgeted = obligations[
        obligations["category_type"].isin(tracked_types)
        & (obligations["expected_amount"] > 0)
    ].copy()
    if budgeted.empty:
        return budgeted

    if period_mode == "Full year":
        budgeted["period_expected"] = budgeted["expected_amount"]
        recurring = budgeted["month"].eq("")
        budgeted.loc[recurring, "period_expected"] = (
            budgeted.loc[recurring, "expected_amount"] * 12
        )
        return budgeted

    selected_month_name = pd.Period(selected_month).strftime("%B")
    budgeted = budgeted[
        budgeted["month"].eq("")
        | budgeted["month"].eq(selected_month_name)
    ].copy()
    budgeted["period_expected"] = budgeted["expected_amount"]
    return budgeted


def budget_summary(
    df: pd.DataFrame,
    obligations: pd.DataFrame,
    period_mode: str,
    selected_month: str,
) -> dict[str, float]:
    budgeted = period_obligations(obligations, period_mode, selected_month)
    expense_budget = budgeted[budgeted["category_type"] != "Income"]
    income_budget = budgeted[budgeted["category_type"] == "Income"]
    total_budgeted = (
        float(expense_budget["period_expected"].sum())
        if not expense_budget.empty
        else 0.0
    )
    budgeted_income = (
        float(income_budget["period_expected"].sum())
        if not income_budget.empty
        else 0.0
    )
    income = float(df.loc[df["category_type"] == "Income", "amount"].sum())
    total_spent = float(df.loc[df["category_type"] != "Income", "amount"].sum())
    return {
        "income": income,
        "budgeted_income": budgeted_income,
        "total_budgeted": total_budgeted,
        "left_to_budget": budgeted_income - total_budgeted,
        "total_spent": total_spent,
        "left_to_spend": total_budgeted - total_spent,
    }


def budget_actuals(
    df: pd.DataFrame,
    obligations: pd.DataFrame,
    period_mode: str,
    selected_month: str,
) -> pd.DataFrame:
    budgeted = period_obligations(obligations, period_mode, selected_month)
    if budgeted.empty:
        return pd.DataFrame()

    actuals = (
        df.groupby(["category_type", "category"], as_index=False)["amount"]
        .sum()
        .rename(columns={"amount": "actual"})
    )
    display = budgeted[
        ["category_type", "name", "period_expected"]
    ].rename(columns={"name": "category", "period_expected": "budgeted"})
    display = display.merge(
        actuals,
        on=["category_type", "category"],
        how="left",
    )
    display["actual"] = display["actual"].fillna(0)
    display["remaining"] = display["budgeted"] - display["actual"]
    return display.sort_values(["category_type", "category"])


def render_budget_summary(
    df: pd.DataFrame,
    obligations: pd.DataFrame,
    period_mode: str,
    selected_month: str,
) -> None:
    summary = budget_summary(df, obligations, period_mode, selected_month)
    st.subheader("Summary")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Left to Budget", f"${summary['left_to_budget']:,.2f}")
    col2.metric("Total Budgeted", f"${summary['total_budgeted']:,.2f}")
    col3.metric("Left to Spend", f"${summary['left_to_spend']:,.2f}")
    col4.metric("Total Spent", f"${summary['total_spent']:,.2f}")


def render_budget_actual_charts(
    df: pd.DataFrame,
    obligations: pd.DataFrame,
    period_mode: str,
    selected_month: str,
) -> None:
    comparison = budget_actuals(df, obligations, period_mode, selected_month)
    if comparison.empty:
        st.info("Add setup items with expected amounts to compare budgeted vs. actual.")
        return

    st.subheader("Budgeted vs. Actual")
    chart_data = comparison.melt(
        id_vars=["category_type", "category"],
        value_vars=["budgeted", "actual"],
        var_name="Type",
        value_name="Amount",
    )
    chart = (
        alt.Chart(chart_data)
        .mark_bar()
        .encode(
            x=alt.X("Amount:Q", title="Amount"),
            y=alt.Y("category:N", sort="-x", title=None),
            color=alt.Color("Type:N", legend=alt.Legend(title=None)),
            row=alt.Row("category_type:N", title=None),
            tooltip=[
                "category_type:N",
                "category:N",
                "Type:N",
                alt.Tooltip("Amount:Q", format="$,.2f"),
            ],
        )
        .properties(height=120)
        .resolve_scale(y="independent")
    )
    st.altair_chart(chart, use_container_width=True)


def render_metrics(df: pd.DataFrame, title: str) -> None:
    st.header(title)
    income = df.loc[df["category_type"] == "Income", "amount"].sum()
    spending = df.loc[df["category_type"] != "Income", "amount"].sum()
    net = income - spending
    uncategorized = (df["category_type"] == "Uncategorized").sum()

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Income", f"${income:,.2f}")
    col2.metric("Spending", f"${spending:,.2f}")
    col3.metric("Net", f"${net:,.2f}")
    col4.metric("Uncategorized", f"{uncategorized:,}")


def render_charts(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        st.info("Import transactions to populate charts.")
        return pd.DataFrame()

    by_type = (
        df.groupby("category_type", as_index=False)["amount"]
        .sum()
        .sort_values("amount", ascending=False)
    )
    by_category = (
        df.groupby(["category_type", "category"], as_index=False)["amount"]
        .sum()
        .sort_values("amount", ascending=False)
        .head(20)
    )

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Spending Breakdown")
        chart = (
            alt.Chart(by_type)
            .mark_arc(innerRadius=55)
            .encode(
                theta=alt.Theta("amount:Q"),
                color=alt.Color("category_type:N", legend=alt.Legend(title=None)),
                tooltip=["category_type:N", alt.Tooltip("amount:Q", format="$,.2f")],
            )
            .properties(height=260)
        )
        st.altair_chart(chart, use_container_width=True)

    with col2:
        st.subheader("Top Categories")
        category_selection = alt.selection_point(
            fields=["category_type", "category"],
            name="category_select",
            empty=False,
        )
        chart = (
            alt.Chart(by_category)
            .mark_bar()
            .encode(
                x=alt.X("amount:Q", title="Amount"),
                y=alt.Y("category:N", sort="-x", title=None),
                color=alt.Color("category_type:N", legend=None),
                opacity=alt.condition(category_selection, alt.value(1), alt.value(0.45)),
                tooltip=[
                    "category_type:N",
                    "category:N",
                    alt.Tooltip("amount:Q", format="$,.2f"),
                ],
            )
            .add_params(category_selection)
            .properties(height=320)
        )
        event = st.altair_chart(
            chart,
            use_container_width=True,
            on_select="rerun",
            selection_mode="category_select",
            key="top-categories-chart",
        )
        selected = selected_chart_category(event)
        if selected:
            st.session_state["drilldown"] = selected
            st.session_state["pending_view"] = "Transactions"
            st.rerun()

    return by_category


def selected_chart_category(event) -> dict[str, str] | None:
    selection = getattr(event, "selection", None)
    if selection is None and isinstance(event, dict):
        selection = event.get("selection")
    if not selection:
        return None

    selection_values = (
        selection.values()
        if isinstance(selection, dict)
        else [selection]
    )
    for value in selection_values:
        if isinstance(value, list) and value:
            point = value[0]
        elif isinstance(value, dict):
            point = value
        else:
            continue

        category_type = point.get("category_type")
        category = point.get("category")
        if category_type and category:
            return {
                "category_type": category_type,
                "category": category,
            }
    return None


def render_category_drilldown(by_category: pd.DataFrame) -> None:
    if by_category.empty:
        return

    st.subheader("Drill Down")
    cols = st.columns(4)
    for index, row in by_category.head(12).reset_index(drop=True).iterrows():
        label = f"{row['category']} (${row['amount']:,.0f})"
        if cols[index % 4].button(label, key=f"drilldown-{index}-{row['category']}"):
            st.session_state["drilldown"] = {
                "category_type": row["category_type"],
                "category": row["category"],
            }
            st.session_state["view"] = "Transactions"
            st.rerun()

    if st.session_state.get("drilldown"):
        active = st.session_state["drilldown"]
        st.caption(
            f"Active transaction filter: {active['category_type']} / {active['category']}"
        )
        if st.button("Clear transaction filter"):
            st.session_state.pop("drilldown", None)
            st.rerun()


def render_unpaid_panel(
    conn,
    df: pd.DataFrame,
    period_mode: str,
    obligations: pd.DataFrame,
    selected_month: str,
) -> None:
    st.subheader("Unpaid")
    selected_month_name = pd.Period(selected_month).strftime("%B")
    comparison = budget_actuals(df, obligations, period_mode, selected_month)
    if comparison.empty:
        st.caption("No budgeted setup items found for this period.")
        return

    comparison = comparison[
        comparison["category_type"].isin(
            ["Monthly Bills", "Debt", "Non-Monthly Bills"]
        )
    ].copy()
    comparison = comparison[comparison["budgeted"] > comparison["actual"]].copy()
    if comparison.empty:
        st.success("All tracked budget lines are at or above expected activity.")
        return

    due_lookup = period_obligations(obligations, period_mode, selected_month)[
        ["category_type", "name", "month", "due_day"]
    ].rename(columns={"name": "category"})
    display = comparison.merge(
        due_lookup,
        on=["category_type", "category"],
        how="left",
    )
    default_month_label = "Full year" if period_mode == "Full year" else selected_month_name
    display["Month"] = display["month"].replace("", default_month_label)
    display["Difference"] = display["budgeted"] - display["actual"]
    display = display.rename(
        columns={
            "category_type": "Type",
            "category": "Name",
            "due_day": "Due",
            "budgeted": "Budgeted",
            "actual": "Actual",
        }
    ).sort_values(["Type", "Due", "Name"])
    total_unpaid = float(display["Difference"].sum())
    setting_key = f"unpaid_current_amount:{period_mode}:{selected_month}"
    saved_current_amount = float(get_setting(conn, setting_key, "0") or 0)
    widget_key = f"unpaid-current-amount-{period_mode}-{selected_month}"
    if widget_key not in st.session_state:
        st.session_state[widget_key] = saved_current_amount

    def save_current_amount() -> None:
        save_conn = connect()
        try:
            set_setting(
                save_conn,
                setting_key,
                f"{float(st.session_state[widget_key]):.2f}",
            )
        finally:
            save_conn.close()

    current_col, remaining_col = st.columns(2)
    current_amount = current_col.number_input(
        "Current amount (dollars)",
        min_value=0.0,
        step=1.0,
        format="%.2f",
        key=widget_key,
        on_change=save_current_amount,
    )
    remaining_col.metric(
        "Remaining amount",
        f"${current_amount - total_unpaid:,.2f}",
    )
    st.dataframe(
        display[["Type", "Name", "Month", "Due", "Budgeted", "Actual", "Difference"]],
        use_container_width=True,
        hide_index=True,
        height=compact_table_height(len(display), 420),
        column_config={
            "Budgeted": st.column_config.NumberColumn(format="$%.2f"),
            "Actual": st.column_config.NumberColumn(format="$%.2f"),
            "Difference": st.column_config.NumberColumn(format="$%.2f"),
        },
    )


def render_add_transaction(conn, category_map: dict[str, list[str]]) -> None:
    with st.expander("Add Transaction"):
        with st.form("add-transaction-form", clear_on_submit=True):
            col1, col2, col3 = st.columns([1, 1, 1])
            transaction_date = col1.date_input("Date", value=date.today())
            amount = col2.number_input("Amount", min_value=0.0, step=0.01, format="%.2f")
            source = col3.text_input("Source", value="Manual")
            description = st.text_area("Description")
            col4, col5 = st.columns(2)
            category_type = col4.selectbox(
                "Category type",
                ["Uncategorized"] + CATEGORY_TYPES,
            )
            category = col5.selectbox(
                "Category",
                category_options(category_type, category_map),
            )
            notes = st.text_area("Notes")
            submitted = st.form_submit_button("Add transaction")

        if submitted:
            if not description.strip():
                st.error("Description is required.")
                return
            add_transaction(
                conn,
                transaction_date.strftime("%Y-%m-%d"),
                amount,
                description.strip(),
                source.strip() or "Manual",
                nullable_category(category_type),
                nullable_category(category),
                notes.strip() or None,
            )
            logger.info("Added manual transaction amount=%s", amount)
            st.success("Transaction added.")
            st.rerun()


def render_edit_transaction(
    conn,
    df: pd.DataFrame,
    category_map: dict[str, list[str]],
) -> None:
    with st.expander("Edit Transaction"):
        if df.empty:
            st.info("No transactions available to edit.")
            return

        labels = {label_for_transaction(row): row["id"] for _, row in df.iterrows()}
        selected_label = st.selectbox("Transaction", list(labels.keys()))
        selected_id = labels[selected_label]
        row = df[df["id"] == selected_id].iloc[0]

        with st.form("edit-transaction-form"):
            col1, col2, col3 = st.columns([1, 1, 1])
            transaction_date = col1.date_input(
                "Date",
                value=pd.to_datetime(row["date"]).date(),
                key="edit-date",
            )
            amount = col2.number_input(
                "Amount",
                min_value=0.0,
                step=0.01,
                format="%.2f",
                value=float(row["amount"]),
                key="edit-amount",
            )
            source = col3.text_input("Source", value=row["source"], key="edit-source")
            description = st.text_area(
                "Description",
                value=row["description"],
                key="edit-description",
            )
            current_type = (
                row["category_type"]
                if row["category_type"] in CATEGORY_TYPES
                else "Uncategorized"
            )
            col4, col5 = st.columns(2)
            category_type = col4.selectbox(
                "Category type",
                ["Uncategorized"] + CATEGORY_TYPES,
                index=(["Uncategorized"] + CATEGORY_TYPES).index(current_type),
                key="edit-category-type",
            )
            options = category_options(category_type, category_map)
            current_category = row["category"] if row["category"] in options else options[0]
            category = col5.selectbox(
                "Category",
                options,
                index=options.index(current_category),
                key="edit-category",
            )
            notes = st.text_area(
                "Notes",
                value=row["notes"] or "",
                key="edit-notes",
            )
            submitted = st.form_submit_button("Save changes")

        if submitted:
            update_transaction(
                conn,
                selected_id,
                transaction_date.strftime("%Y-%m-%d"),
                amount,
                description.strip(),
                source.strip() or "Manual",
                nullable_category(category_type),
                nullable_category(category),
                notes.strip() or None,
            )
            logger.info("Updated transaction id=%s", selected_id)
            st.success("Transaction updated.")
            st.rerun()

        if st.button("Ignore transaction", key=f"ignore-edit-{selected_id}"):
            ignore_transaction(conn, selected_id)
            logger.info("Ignored transaction id=%s", selected_id)
            st.success("Transaction ignored.")
            st.rerun()


def render_split_transaction(
    conn,
    df: pd.DataFrame,
    category_map: dict[str, list[str]],
) -> None:
    with st.expander("Split Transaction"):
        if df.empty:
            st.info("No transactions available to split.")
            return

        labels = {label_for_transaction(row): row["id"] for _, row in df.iterrows()}
        selected_label = st.selectbox("Transaction to split", list(labels.keys()))
        selected_id = labels[selected_label]
        row = df[df["id"] == selected_id].iloc[0]
        render_split_editor(conn, row, category_map, f"split-{selected_id}")


def render_selected_transaction_editor(
    conn,
    row: pd.Series,
    category_map: dict[str, list[str]],
) -> None:
    selected_id = row["id"]
    with st.expander("Edit selected transaction", expanded=True):
        with st.form(f"table-edit-transaction-{selected_id}"):
            col1, col2, col3 = st.columns([1, 1, 1])
            transaction_date = col1.date_input(
                "Date",
                value=pd.to_datetime(row["date"]).date(),
                key=f"table-edit-date-{selected_id}",
            )
            amount = col2.number_input(
                "Amount",
                min_value=0.0,
                step=0.01,
                format="%.2f",
                value=float(row["amount"]),
                key=f"table-edit-amount-{selected_id}",
            )
            source = col3.text_input(
                "Source",
                value=row["source"],
                key=f"table-edit-source-{selected_id}",
            )
            description = st.text_area(
                "Description",
                value=row["description"],
                key=f"table-edit-description-{selected_id}",
            )
            current_type = (
                row["category_type"]
                if row["category_type"] in CATEGORY_TYPES
                else "Uncategorized"
            )
            col4, col5 = st.columns(2)
            category_type = col4.selectbox(
                "Category type",
                ["Uncategorized"] + CATEGORY_TYPES,
                index=(["Uncategorized"] + CATEGORY_TYPES).index(current_type),
                key=f"table-edit-category-type-{selected_id}",
            )
            options = category_options(category_type, category_map)
            current_category = row["category"] if row["category"] in options else options[0]
            category = col5.selectbox(
                "Category",
                options,
                index=options.index(current_category),
                key=f"table-edit-category-{selected_id}-{category_type}",
            )
            notes = st.text_area(
                "Notes",
                value=row["notes"] or "",
                key=f"table-edit-notes-{selected_id}",
            )
            submitted = st.form_submit_button("Save changes")

        col_save, col_ignore = st.columns(2)
        if submitted:
            update_transaction(
                conn,
                selected_id,
                transaction_date.strftime("%Y-%m-%d"),
                amount,
                description.strip(),
                source.strip() or "Manual",
                nullable_category(category_type),
                nullable_category(category),
                notes.strip() or None,
            )
            logger.info("Updated transaction id=%s from table selection", selected_id)
            st.success("Transaction updated.")
            st.rerun()

        if col_ignore.button("Ignore transaction", key=f"table-ignore-{selected_id}"):
            ignore_transaction(conn, selected_id)
            logger.info("Ignored transaction id=%s from table selection", selected_id)
            st.success("Transaction ignored.")
            st.rerun()


def render_split_editor(
    conn,
    row: pd.Series,
    category_map: dict[str, list[str]],
    key_prefix: str,
) -> None:
    selected_id = row["id"]
    original_amount = float(row["amount"])

    col1, col2, col3 = st.columns([1, 1, 2])
    split_count = col1.number_input(
        "Split lines",
        min_value=2,
        max_value=12,
        value=2,
        step=1,
        key=f"{key_prefix}-count",
    )
    col2.metric("Original", f"${original_amount:,.2f}")

    split_rows = []
    running_total = 0.0
    for index in range(int(split_count)):
        st.markdown(f"**Split {index + 1}**")
        amount_col, type_col, category_col = st.columns([1, 1, 1])
        default_amount = (
            round(original_amount / float(split_count), 2)
            if index < int(split_count) - 1
            else round(original_amount - running_total, 2)
        )
        amount = amount_col.number_input(
            "Amount",
            min_value=0.0,
            step=0.01,
            format="%.2f",
            value=max(default_amount, 0.0),
            key=f"{key_prefix}-amount-{index}",
        )
        category_type = type_col.selectbox(
            "Category type",
            [""] + CATEGORY_TYPES,
            key=f"{key_prefix}-type-{index}",
        )
        category_values = [""] if not category_type else category_options(category_type, category_map)
        category = category_col.selectbox(
            "Category",
            category_values,
            key=f"{key_prefix}-category-{index}-{category_type}",
        )
        description = st.text_input(
            "Description",
            value=f"{row['description']} - split {index + 1}",
            key=f"{key_prefix}-description-{index}",
        )
        notes = st.text_input(
            "Notes",
            value="",
            key=f"{key_prefix}-notes-{index}",
        )
        running_total += float(amount)
        split_rows.append(
            {
                "date": row["date"],
                "amount": float(amount),
                "description": description.strip(),
                "source": row["source"],
                "category_type": category_type,
                "category": category,
                "notes": notes.strip() or None,
            }
        )

    difference = round(original_amount - running_total, 2)
    col3.metric("Remaining", f"${difference:,.2f}")
    if abs(difference) >= 0.01:
        st.warning("Split amounts must add up to the original transaction amount.")

    if st.button(
        "Save split",
        disabled=abs(difference) >= 0.01,
        key=f"{key_prefix}-save",
    ):
        invalid_description = any(not split["description"] for split in split_rows)
        invalid_amount = any(float(split["amount"]) <= 0 for split in split_rows)
        invalid_category = any(
            not split["category_type"] or not split["category"]
            for split in split_rows
        )
        if invalid_description:
            st.error("Each split line needs a description.")
            return
        if invalid_amount:
            st.error("Each split line needs an amount above $0.")
            return
        if invalid_category:
            st.error("Each split line needs a category type and category.")
            return
        changed = split_transaction(conn, selected_id, split_rows)
        logger.info(
            "Split transaction id=%s into %s child rows",
            selected_id,
            len(split_rows),
        )
        st.success(f"Created {len(split_rows):,} split transactions.")
        if changed:
            st.rerun()


def render_setup(
    conn,
    obligations: pd.DataFrame,
    df: pd.DataFrame,
    period_mode: str,
    selected_month: str,
) -> None:
    st.header("Setup")
    st.caption(
        "Manage bills, debt, savings, and non-monthly bills. Items with an "
        "expected amount of $0 stay configured but do not appear in the unpaid panel."
    )
    summary = budget_summary(df, obligations, period_mode, selected_month)
    col1, col2 = st.columns(2)
    col1.metric("Left to Budget", f"${summary['left_to_budget']:,.2f}")
    col2.metric("Total Budgeted", f"${summary['total_budgeted']:,.2f}")

    tabs = st.tabs(
        [
            "Income",
            "Variable Expenses",
            "Monthly Bills",
            "Debt",
            "Savings",
            "Non-Monthly Bills",
        ]
    )
    tab_config = [
        (tabs[0], "Income"),
        (tabs[1], "Variable Expenses"),
        (tabs[2], "Monthly Bills"),
        (tabs[3], "Debt"),
        (tabs[4], "Savings"),
        (tabs[5], "Non-Monthly Bills"),
    ]
    for tab, category_type in tab_config:
        with tab:
            current = obligations[obligations["category_type"] == category_type].copy()
            st.subheader(category_type)

            if not current.empty:
                display_columns = ["name", "month", "due_day", "expected_amount"]
                if category_type != "Non-Monthly Bills":
                    display_columns = ["name", "due_day", "expected_amount"]
                if category_type in {"Income", "Variable Expenses", "Savings"}:
                    display_columns = ["name", "expected_amount"]
                if category_type == "Debt":
                    display_columns = [
                        "name",
                        "due_day",
                        "expected_amount",
                        "balance",
                        "minimum_payment",
                        "interest_rate",
                    ]
                st.dataframe(
                    current[display_columns],
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "name": "Name",
                        "month": "Month",
                        "due_day": "Due Day",
                        "expected_amount": st.column_config.NumberColumn(
                            "Expected",
                            format="$%.2f",
                        ),
                        "balance": st.column_config.NumberColumn(
                            "Balance",
                            format="$%.2f",
                        ),
                        "minimum_payment": st.column_config.NumberColumn(
                            "Minimum",
                            format="$%.2f",
                        ),
                        "interest_rate": st.column_config.NumberColumn(
                            "Interest Rate",
                            format="%.2%",
                        ),
                    },
                )

            with st.expander(f"Add {category_type[:-1] if category_type.endswith('s') else category_type}"):
                with st.form(f"add-obligation-{category_type}"):
                    name = st.text_input("Name", key=f"add-name-{category_type}")
                    col1, col2, col3 = st.columns(3)
                    month = None
                    if category_type == "Non-Monthly Bills":
                        month = col1.selectbox(
                            "Month",
                            MONTH_SHEETS,
                            key=f"add-month-{category_type}",
                        )
                    due_day = col1.number_input(
                        "Due day",
                        min_value=0,
                        max_value=31,
                        value=0,
                        step=1,
                        key=f"add-due-{category_type}",
                        disabled=category_type in {"Income", "Variable Expenses", "Savings"},
                    )
                    expected_amount = col2.number_input(
                        "Expected amount",
                        min_value=0.0,
                        step=1.0,
                        format="%.2f",
                        key=f"add-amount-{category_type}",
                    )
                    balance = 0.0
                    minimum_payment = 0.0
                    interest_rate = 0.0
                    if category_type == "Debt":
                        balance = col3.number_input(
                            "Balance",
                            min_value=0.0,
                            step=100.0,
                            format="%.2f",
                            key=f"add-balance-{category_type}",
                        )
                        minimum_payment = col2.number_input(
                            "Minimum payment",
                            min_value=0.0,
                            step=10.0,
                            format="%.2f",
                            key=f"add-minimum-{category_type}",
                        )
                        interest_rate_percent = col3.number_input(
                            "Interest rate %",
                            min_value=0.0,
                            step=0.1,
                            format="%.3f",
                            key=f"add-rate-{category_type}",
                        )
                        interest_rate = interest_rate_percent / 100
                    submitted = st.form_submit_button("Add")

                if submitted:
                    if not name.strip():
                        st.error("Name is required.")
                    else:
                        add_obligation(
                            conn,
                            category_type,
                            name.strip(),
                            month,
                            int(due_day) if due_day else None,
                            expected_amount,
                            balance,
                            minimum_payment,
                            interest_rate,
                        )
                        logger.info("Added obligation type=%s name=%s", category_type, name)
                        st.success("Setup item added.")
                        st.rerun()

            if current.empty:
                continue

            with st.expander(f"Edit or remove {category_type}"):
                choices = {
                    (
                        f"{row['name']} "
                        f"{'[' + str(row['month']) + '] ' if row['month'] else ''}"
                        f"(${float(row['expected_amount']):,.2f})"
                    ): int(row["id"])
                    for _, row in current.iterrows()
                }
                selected = st.selectbox(
                    "Item",
                    list(choices.keys()),
                    key=f"edit-obligation-select-{category_type}",
                )
                selected_id = choices[selected]
                row = current[current["id"] == selected_id].iloc[0]

                with st.form(f"edit-obligation-{category_type}"):
                    name = st.text_input(
                        "Name",
                        value=row["name"],
                        key=f"edit-name-{category_type}",
                    )
                    col1, col2, col3 = st.columns(3)
                    month = None
                    if category_type == "Non-Monthly Bills":
                        current_month = (
                            row["month"]
                            if row["month"] and row["month"] in MONTH_SHEETS
                            else MONTH_SHEETS[0]
                        )
                        month = col1.selectbox(
                            "Month",
                            MONTH_SHEETS,
                            index=MONTH_SHEETS.index(current_month),
                            key=f"edit-month-{category_type}",
                        )
                    due_day = col1.number_input(
                        "Due day",
                        min_value=0,
                        max_value=31,
                        value=(
                            int(row["due_day"])
                            if pd.notna(row["due_day"])
                            else 0
                        ),
                        step=1,
                        key=f"edit-due-{category_type}",
                        disabled=category_type in {"Income", "Variable Expenses", "Savings"},
                    )
                    expected_amount = col2.number_input(
                        "Expected amount",
                        min_value=0.0,
                        value=float(row["expected_amount"]),
                        step=1.0,
                        format="%.2f",
                        key=f"edit-amount-{category_type}",
                    )
                    balance = float(row.get("balance", 0) or 0)
                    minimum_payment = float(row.get("minimum_payment", 0) or 0)
                    interest_rate = float(row.get("interest_rate", 0) or 0)
                    if category_type == "Debt":
                        balance = col3.number_input(
                            "Balance",
                            min_value=0.0,
                            value=balance,
                            step=100.0,
                            format="%.2f",
                            key=f"edit-balance-{category_type}",
                        )
                        minimum_payment = col2.number_input(
                            "Minimum payment",
                            min_value=0.0,
                            value=minimum_payment,
                            step=10.0,
                            format="%.2f",
                            key=f"edit-minimum-{category_type}",
                        )
                        interest_rate_percent = col3.number_input(
                            "Interest rate %",
                            min_value=0.0,
                            value=interest_rate * 100,
                            step=0.1,
                            format="%.3f",
                            key=f"edit-rate-{category_type}",
                        )
                        interest_rate = interest_rate_percent / 100
                    col_save, col_delete = st.columns(2)
                    saved = col_save.form_submit_button("Save changes")
                    deleted = col_delete.form_submit_button("Remove")

                if saved:
                    update_obligation(
                        conn,
                        selected_id,
                        category_type,
                        name.strip(),
                        month,
                        int(due_day) if due_day else None,
                        expected_amount,
                        balance,
                        minimum_payment,
                        interest_rate,
                    )
                    logger.info("Updated obligation id=%s", selected_id)
                    st.success("Setup item updated.")
                    st.rerun()
                if deleted:
                    delete_obligation(conn, selected_id)
                    logger.info("Deleted obligation id=%s", selected_id)
                    st.success("Setup item removed.")
                    st.rerun()


def render_debt_paydown(obligations: pd.DataFrame) -> None:
    st.header("Debt Paydown")
    debt_rows = obligations[
        obligations["category_type"].eq("Debt")
        & (obligations["balance"] > 0)
    ].copy()

    if debt_rows.empty:
        st.info("Add debt balances in Setup to calculate payoff dates.")
        return

    summary, schedule = simulate_debt_payoff(debt_rows)
    total_balance = summary["balance"].sum()
    total_budgeted_payment = summary["budgeted_payment"].sum()
    projected = summary[summary["months_to_payoff"].notna()]
    total_interest = projected["total_interest"].sum()

    col1, col2, col3 = st.columns(3)
    col1.metric("Debt Balance", f"${total_balance:,.2f}")
    col2.metric("Monthly Debt Budget", f"${total_budgeted_payment:,.2f}")
    col3.metric("Projected Interest", f"${total_interest:,.2f}")

    st.subheader("Payoff Projection")
    display = summary.copy()
    display["payoff_date"] = pd.to_datetime(display["payoff_date"]).dt.strftime("%Y-%m")
    st.dataframe(
        display[
            [
                "name",
                "balance",
                "budgeted_payment",
                "minimum_payment",
                "interest_rate",
                "months_to_payoff",
                "payoff_date",
                "total_interest",
                "status",
            ]
        ],
        use_container_width=True,
        hide_index=True,
        column_config={
            "name": "Debt",
            "balance": st.column_config.NumberColumn("Balance", format="$%.2f"),
            "budgeted_payment": st.column_config.NumberColumn(
                "Budgeted Payment",
                format="$%.2f",
            ),
            "minimum_payment": st.column_config.NumberColumn(
                "Minimum",
                format="$%.2f",
            ),
            "interest_rate": st.column_config.NumberColumn(
                "Interest Rate",
                format="%.2%",
            ),
            "months_to_payoff": "Months",
            "payoff_date": "Payoff Month",
            "total_interest": st.column_config.NumberColumn(
                "Interest",
                format="$%.2f",
            ),
            "status": "Status",
        },
    )

    if schedule.empty:
        return

    st.subheader("Balance Over Time")
    chart_data = schedule.copy()
    chart_data["month"] = pd.to_datetime(chart_data["month"])
    chart = (
        alt.Chart(chart_data)
        .mark_line(point=False)
        .encode(
            x=alt.X("month:T", title="Month"),
            y=alt.Y("ending_balance:Q", title="Balance"),
            color=alt.Color("name:N", legend=alt.Legend(title=None)),
            tooltip=[
                "name:N",
                alt.Tooltip("month:T", title="Month"),
                alt.Tooltip("ending_balance:Q", title="Balance", format="$,.2f"),
                alt.Tooltip("interest:Q", title="Interest", format="$,.2f"),
                alt.Tooltip("principal:Q", title="Principal", format="$,.2f"),
            ],
        )
    )
    st.altair_chart(chart, use_container_width=True)

def render_import(conn) -> None:
    st.header("Import")
    uploaded_files = st.file_uploader(
        "Upload bank CSV files",
        type=["csv"],
        accept_multiple_files=True,
    )

    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("Import CSV files", disabled=not uploaded_files):
            imported = 0
            for uploaded in uploaded_files:
                try:
                    logger.info("Importing uploaded CSV: %s", uploaded.name)
                    cleaned = clean_transaction_file(uploaded, uploaded.name)
                    imported += upsert_transactions(conn, cleaned)
                except Exception:
                    logger.exception("Failed importing uploaded CSV: %s", uploaded.name)
                    raise
            logger.info("Imported %s new transactions from uploaded CSV files", imported)
            st.success(f"Imported {imported:,} new transactions.")

    with col2:
        if st.button("Import files from transactions folder"):
            try:
                logger.info("Importing CSV files from transactions folder")
                cleaned = load_transaction_folder(Path("transactions"))
                imported = upsert_transactions(conn, cleaned)
                logger.info(
                    "Imported %s new transactions from transactions folder",
                    imported,
                )
            except Exception:
                logger.exception("Failed importing transactions folder")
                raise
            st.success(f"Imported {imported:,} new transactions from transactions/.")

    st.divider()
    st.subheader("Workbook Categories")
    st.caption(
        "Match uncategorized transactions to categorized rows from the Excel workbook "
        "using exact date and amount, plus description similarity."
    )
    if st.button("Apply categories from workbook"):
        try:
            logger.info("Extracting workbook transactions from %s", WORKBOOK_PATH)
            current_transactions = load_transactions(conn)
            workbook_transactions = extract_month_transactions(WORKBOOK_PATH)
            matches = match_workbook_categories(
                current_transactions,
                workbook_transactions,
            )
            applied = apply_category_matches(conn, matches)
            logger.info(
                "Applied workbook categories: matches=%s applied=%s",
                len(matches),
                applied,
            )
        except Exception:
            logger.exception("Failed applying categories from workbook")
            raise
        st.success(
            f"Applied categories to {applied:,} transactions "
            f"from {len(matches):,} confident workbook matches."
        )


def render_categorization(
    conn,
    df: pd.DataFrame,
    category_map: dict[str, list[str]],
) -> None:
    st.header("Categorize")
    if df.empty:
        st.info("Import transactions before categorizing.")
        return

    uncategorized_all = df[df["category_type"] == "Uncategorized"]
    uncategorized_count = len(uncategorized_all)
    st.metric("Uncategorized Transactions", f"{uncategorized_count:,}")

    uncategorized = uncategorized_all.head(25)
    if uncategorized.empty:
        st.success("No uncategorized transactions.")
        return

    for _, row in uncategorized.iterrows():
        with st.container(border=True):
            st.caption(f"{row['date']} | {row['source']} | ${row['amount']:,.2f}")
            col4, col5 = st.columns(2)
            category_type = col4.selectbox(
                "Category type",
                [""] + CATEGORY_TYPES,
                key=f"categorize-type-{row['id']}",
            )
            category_values = [""] if not category_type else category_options(category_type, category_map)
            category = col5.selectbox(
                "Category",
                category_values,
                key=f"categorize-cat-{row['id']}-{category_type}",
            )
            with st.form(f"categorize-edit-{row['id']}"):
                col1, col2, col3 = st.columns([1, 1, 1])
                transaction_date = col1.date_input(
                    "Date",
                    value=pd.to_datetime(row["date"]).date(),
                    key=f"categorize-date-{row['id']}",
                )
                amount = col2.number_input(
                    "Amount",
                    min_value=0.0,
                    step=0.01,
                    format="%.2f",
                    value=float(row["amount"]),
                    key=f"categorize-amount-{row['id']}",
                )
                source = col3.text_input(
                    "Source",
                    value=row["source"],
                    key=f"categorize-source-{row['id']}",
                )
                description = st.text_area(
                    "Description",
                    value=row["description"],
                    key=f"categorize-description-{row['id']}",
                )
                notes = st.text_area(
                    "Notes",
                    value=row["notes"] or "",
                    key=f"categorize-notes-{row['id']}",
                )
                submitted = st.form_submit_button("Save transaction")
            ignored = st.button(
                "Ignore transaction",
                key=f"ignore-categorize-{row['id']}",
            )

            if submitted:
                if not category_type or not category:
                    st.error("Choose a category type and category before saving.")
                    return
                update_transaction(
                    conn,
                    row["id"],
                    transaction_date.strftime("%Y-%m-%d"),
                    amount,
                    description.strip(),
                    source.strip() or "Manual",
                    category_type,
                    category,
                    notes.strip() or None,
                )
                logger.info("Categorized and edited transaction id=%s", row["id"])
                st.success("Transaction saved.")
                st.rerun()
            if ignored:
                ignore_transaction(conn, row["id"])
                logger.info("Ignored transaction id=%s from categorization", row["id"])
                st.success("Transaction ignored.")
                st.rerun()

            with st.expander("Split this transaction"):
                render_split_editor(
                    conn,
                    row,
                    category_map,
                    f"categorize-split-{row['id']}",
                )


def render_transactions(
    conn,
    df: pd.DataFrame,
    category_map: dict[str, list[str]],
) -> None:
    st.header("Transactions")
    drilldown = st.session_state.get("drilldown")
    if drilldown:
        st.caption(f"Filtered to {drilldown['category_type']} / {drilldown['category']}")
        if st.button("Clear filter"):
            st.session_state.pop("drilldown", None)
            st.rerun()
        df = apply_drilldown(df)

    render_add_transaction(conn, category_map)
    render_split_transaction(conn, df, category_map)

    if df.empty:
        st.info("No transactions imported yet.")
        return
    st.caption(f"Showing {len(df):,} transactions for the selected period.")
    visible = df.reset_index(drop=True).copy()
    table_df = visible[
        [
            "date",
            "amount",
            "category_type",
            "category",
            "description",
            "source",
        ]
    ].copy()
    table_df["description"] = table_df["description"].map(clipped_text)
    table_event = st.dataframe(
        table_df,
        use_container_width=True,
        hide_index=True,
        height=transaction_table_height(len(visible)),
        row_height=36,
        on_select="rerun",
        selection_mode="single-row",
        key="transactions-table",
        column_config={
            "amount": st.column_config.NumberColumn("Amount", format="$%.2f"),
            "date": "Date",
            "category_type": "Type",
            "category": "Category",
            "description": "Description",
            "source": "Source",
        },
    )
    selected_rows = table_event.selection.rows if table_event.selection else []
    if selected_rows:
        selected_row = visible.iloc[selected_rows[0]]
        render_selected_transaction_editor(conn, selected_row, category_map)
        st.caption("Full selected transaction")
        st.dataframe(
            pd.DataFrame([selected_row])[
            [
                "date",
                "amount",
                "category_type",
                "category",
                "description",
                "source",
                "notes",
            ]
            ],
            use_container_width=True,
            hide_index=True,
            row_height=36,
            column_config={
                "amount": st.column_config.NumberColumn("Amount", format="$%.2f"),
            },
        )


def main() -> None:
    logger.info("Handling Streamlit rerun")
    apply_responsive_styles()
    if st.session_state.get("pending_view"):
        st.session_state["view"] = st.session_state.pop("pending_view")

    conn = connect()
    init_db(conn)
    setup_obligations = extract_setup_obligations(WORKBOOK_PATH)
    seeded = seed_obligations(conn, setup_obligations)
    if seeded:
        logger.info("Seeded setup obligations from workbook: count=%s", seeded)
    obligations = load_obligations(conn)
    debt_details_missing = (
        not obligations[obligations["category_type"].eq("Debt")].empty
        and obligations.loc[
            obligations["category_type"].eq("Debt"),
            ["balance", "minimum_payment", "interest_rate"],
        ].fillna(0).sum().sum()
        == 0
    )
    if debt_details_missing:
        synced = sync_debt_details(conn, setup_obligations)
        logger.info("Synced debt details from workbook: count=%s", synced)
        obligations = load_obligations(conn)
    category_map = build_category_map(obligations)

    with st.sidebar:
        st.title("Finance Dashboard")
        st.caption("Local SQLite app")
        view = st.radio(
            "View",
            [
                "Dashboard",
                "Setup",
                "Debt Paydown",
                "Import",
                "Categorize",
                "Transactions",
            ],
            key="view",
        )

    df = load_transactions(conn)
    months = month_options(df)
    period_mode = st.sidebar.segmented_control(
        "Period",
        ["Monthly", "Full year"],
        default="Monthly",
    )
    selected_month = st.sidebar.selectbox(
        "Month",
        months or ["No transactions"],
        format_func=lambda value: (
            display_month(value) if value != "No transactions" else value
        ),
        disabled=period_mode == "Full year" or not months,
    )
    filtered = filter_period(df, period_mode, selected_month)
    dashboard_title = (
        f"Monthly Dashboard - {display_month(selected_month)}"
        if period_mode == "Monthly"
        else "Full Year Dashboard"
    )

    if view == "Dashboard":
        render_metrics(filtered, dashboard_title)
        render_budget_summary(filtered, obligations, period_mode, selected_month)
        render_unpaid_panel(conn, filtered, period_mode, obligations, selected_month)
        render_charts(filtered)
        render_budget_actual_charts(filtered, obligations, period_mode, selected_month)
    elif view == "Setup":
        render_setup(conn, obligations, filtered, period_mode, selected_month)
    elif view == "Debt Paydown":
        render_debt_paydown(obligations)
    elif view == "Import":
        render_import(conn)
    elif view == "Categorize":
        render_categorization(conn, df, category_map)
    else:
        render_transactions(conn, filtered, category_map)


if __name__ == "__main__":
    main()
