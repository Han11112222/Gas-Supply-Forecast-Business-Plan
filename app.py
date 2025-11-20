import io
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# ===================== 기본 세팅 =====================
st.set_page_config(
    page_title="도시가스 판매량 계획 / 실적 분석",
    layout="wide",
)

st.title("도시가스 판매량 계획 / 실적 분석")

DATA_PATH = Path("판매량(계획_실적).xlsx")

# ===================== 데이터 준비 함수 =====================

GROUP_FORMULAS = {
    "가정용": ["취사용", "개별난방용", "중앙난방용", "자가열전용"],
    "산업용": ["산업용"],
    "수송용": ["수송용(CNG)", "수송용(BIO)"],
    "업무용": ["업무난방용", "냉방용", "주한미군"],
    "영업용": ["일반용"],
    "열병합": ["열병합용", "열병합용1", "열병합용2"],
    "연료전지": ["연료전지용"],
    "열전용설비용": ["열전용설비용"],
}


def _clean_number_cols(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for col in df.columns:
        if df[col].dtype == "O":
            try:
                df[col] = (
                    df[col]
                    .astype(str)
                    .str.replace(",", "", regex=False)
                    .str.strip()
                )
                df[col] = pd.to_numeric(df[col], errors="ignore")
            except Exception:
                # 변환 안 되는 텍스트 컬럼은 그대로 둠
                pass
    return df


@st.cache_data
def load_raw_data(file_bytes: bytes | None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """엑셀에서 계획/실적 시트 로드"""
    if file_bytes is None:
        xls = pd.ExcelFile(DATA_PATH)
    else:
        xls = pd.ExcelFile(io.BytesIO(file_bytes))

    plan = xls.parse("계획_부피")
    actual = xls.parse("실적_부피")

    plan = _clean_number_cols(plan)
    actual = _clean_number_cols(actual)

    return plan, actual


def build_group_long(plan: pd.DataFrame, actual: pd.DataFrame) -> pd.DataFrame:
    """계획/실적 데이터를 그룹(용도) 단위 Long 포맷으로 변환"""
    dfp = plan.copy()
    dfa = actual.copy()

    records = []

    # 개별 그룹
    for grp, cols in GROUP_FORMULAS.items():
        cols_existing = [c for c in cols if c in dfp.columns]
        if not cols_existing:
            continue

        tmp = dfp[["연", "월"]].copy()
        tmp["그룹"] = grp
        tmp["계획"] = dfp[cols_existing].sum(axis=1, min_count=1)
        tmp["실적"] = dfa[cols_existing].sum(axis=1, min_count=1)
        records.append(tmp)

    # 총량
    all_cols = sorted(
        {c for cols in GROUP_FORMULAS.values() for c in cols if c in dfp.columns}
    )
    tmp_tot = dfp[["연", "월"]].copy()
    tmp_tot["그룹"] = "총량"
    tmp_tot["계획"] = dfp[all_cols].sum(axis=1, min_count=1)
    tmp_tot["실적"] = dfa[all_cols].sum(axis=1, min_count=1)
    records.append(tmp_tot)

    long = pd.concat(records, ignore_index=True)
    long["연"] = long["연"].astype(int)
    long["월"] = long["월"].astype(int)

    return long


def year_defaults(years: list[int], start: int = 2020, end: int = 2025) -> list[int]:
    base = [y for y in years if start <= y <= end]
    if not base:
        base = [years[-1]]
    return base


# ===================== 시각화 유틸 =====================


def format_number(x):
    return f"{x:,.0f}"


def make_annual_group_summary(long_df: pd.DataFrame, year: int) -> pd.DataFrame:
    this_year = (
        long_df[long_df["연"] == year]
        .groupby("그룹")[["계획", "실적"]]
        .sum()
        .reset_index()
    )

    prev_year = year - 1
    prev = (
        long_df[long_df["연"] == prev_year]
        .groupby("그룹")[["실적"]]
        .sum()
        .rename(columns={"실적": "Y-1 실적"})
        .reset_index()
    )

    summary = this_year.merge(prev, on="그룹", how="left")
    summary["차이(실적-계획)"] = summary["실적"] - summary["계획"]
    summary["달성률(%)"] = np.where(
        summary["계획"] > 0,
        (summary["실적"] / summary["계획"]) * 100,
        np.nan,
    )
    return summary


def fig_annual_group_summary(summary: pd.DataFrame, year: int, include_prev: bool) -> go.Figure:
    value_cols = ["계획", "실적"]
    if include_prev and "Y-1 실적" in summary.columns:
        value_cols.append("Y-1 실적")

    bar_df = summary.melt(
        id_vars="그룹", value_vars=value_cols, var_name="항목", value_name="값"
    )

    cat_order = {"항목": ["계획", "실적", "Y-1 실적"]}
    color_map = {
        "계획": "#1f77b4",
        "실적": "#1f99ff",
        "Y-1 실적": "#d3d3d3",
    }

    fig = px.bar(
        bar_df,
        x="그룹",
        y="값",
        color="항목",
        barmode="group",
        category_orders=cat_order,
        color_discrete_map=color_map,
    )
    fig.update_layout(
        title=f"{year}년 그룹별 계획·실적 비교",
        yaxis_title="연간 판매량 (Nm³)",
        bargap=0.30,      # 그룹 사이 간격
        bargroupgap=0.15, # 그룹 내 막대 간격
    )
    fig.update_yaxes(ticksuffix=" ")
    return fig


def fig_monthly_plan_vs_actual(
    long_df: pd.DataFrame,
    group: str,
    year: int,
    period_label: str,
    include_prev: bool,
) -> tuple[go.Figure, pd.DataFrame]:
    df = long_df[long_df["그룹"] == group]

    if period_label == "상반기(1~6월)":
        mask = df["월"].between(1, 6)
        period_title = "상반기(1~6월)"
    elif period_label == "하반기(7~12월)":
        mask = df["월"].between(7, 12)
        period_title = "하반기(7~12월)"
    else:
        mask = df["월"].between(1, 12)
        period_title = "연간"

    cur = df[(df["연"] == year) & mask].sort_values("월")
    prev = df[(df["연"] == year - 1) & mask].sort_values("월")

    months = cur["월"].tolist()
    plan = cur["계획"].tolist()
    actual = cur["실적"].tolist()
    diff = np.array(actual) - np.array(plan)

    fig = go.Figure()

    # 막대 순서를 offsetgroup으로 고정 (계획 -> 실적 -> Y-1 실적)
    fig.add_bar(
        name=f"{year}년 계획",
        x=months,
        y=plan,
        offsetgroup="0",
        marker_color="#1f77b4",
    )
    fig.add_bar(
        name=f"{year}년 실적",
        x=months,
        y=actual,
        offsetgroup="1",
        marker_color="#1f99ff",
    )

    if include_prev and not prev.empty:
        prev_vals = prev["실적"].tolist()
        fig.add_bar(
            name=f"{year-1}년 실적",
            x=months,
            y=prev_vals,
            offsetgroup="2",  # 항상 오른쪽
            marker_color="#d3d3d3",
        )
    else:
        prev_vals = [np.nan] * len(months)

    fig.add_scatter(
        name="증감(실적-계획)",
        x=months,
        y=diff,
        mode="lines+markers",
        yaxis="y2",
        marker=dict(size=6),
        line=dict(width=2),
    )

    fig.update_layout(
        title=f"{year}년 {group} 판매량 및 증감 ({period_title})",
        xaxis=dict(title="월", dtick=1),
        yaxis=dict(title="판매량 (Nm³)", ticksuffix=" "),
        yaxis2=dict(
            title="증감 (Nm³)",
            overlaying="y",
            side="right",
            showgrid=False,
        ),
        barmode="group",
        bargap=0.30,
        bargroupgap=0.10,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )

    # 요약 테이블
    table = pd.DataFrame(
        {
            "월": months,
            "계획": plan,
            "실적": actual,
            f"{year-1}년 실적": prev_vals,
            "차이(실적-계획)": diff,
        }
    )
    table["달성률(%)"] = np.where(
        table["계획"] > 0, (table["실적"] / table["계획"]) * 100, np.nan
    )

    return fig, table


def fig_monthly_trend(long_df: pd.DataFrame, groupsel: str, years: list[int]) -> go.Figure:
    base = long_df[(long_df["그룹"] == groupsel) & (long_df["연"].isin(years))].copy()

    # 계획/실적 둘 다 라인으로
    melted = base.melt(
        id_vars=["연", "월", "그룹"],
        value_vars=["계획", "실적"],
        var_name="구분",
        value_name="값",
    )
    melted["라벨"] = (
        melted["연"].astype(str) + "년 " + melted["구분"].map({"실적": "실적", "계획": "계획"})
    )

    fig = px.line(
        melted,
        x="월",
        y="값",
        color="라벨",
        line_dash="구분",
        markers=True,
    )
    fig.update_layout(
        title=f"{groupsel} 월별 계획/실적 추이",
        xaxis=dict(title="월", dtick=1),
        yaxis=dict(title="판매량 (Nm³)", ticksuffix=" "),
    )
    return fig


def fig_period_stack(long_df: pd.DataFrame, years: list[int], period_label: str) -> go.Figure:
    df = long_df[long_df["연"].isin(years)].copy()

    if period_label == "상반기(1~6월)":
        mask = df["월"].between(1, 6)
        period_title = "상반기(1~6월)"
    elif period_label == "하반기(7~12월)":
        mask = df["월"].between(7, 12)
        period_title = "하반기(7~12월)"
    else:
        mask = df["월"].between(1, 12)
        period_title = "연간"

    df = df[mask]

    agg = (
        df.groupby(["연", "그룹"])[["실적"]]
        .sum()
        .reset_index()
        .pivot(index="연", columns="그룹", values="실적")
        .fillna(0)
    )

    years_sorted = sorted(agg.index.tolist())
    groups = [c for c in agg.columns if c != "총량"]

    fig = go.Figure()

    # 스택 막대
    for grp in groups:
        fig.add_bar(
            name=grp,
            x=years_sorted,
            y=agg[grp].tolist(),
        )

    # 가정용 / 합계 라인
    home_series = agg.get("가정용", pd.Series(index=agg.index, data=np.nan))
    total_series = agg.sum(axis=1)

    fig.add_scatter(
        name="가정용",
        x=years_sorted,
        y=home_series.tolist(),
        mode="lines+markers",
        line=dict(dash="dot", width=2),
        marker=dict(size=6),
    )
    fig.add_scatter(
        name="합계",
        x=years_sorted,
        y=total_series.tolist(),
        mode="lines+markers",
        line=dict(dash="dash", width=2),
        marker=dict(size=6),
    )

    fig.update_layout(
        title=f"기간별 용도 누적 실적 판매량 (스택형 막대 + 라인) - {period_title}",
        xaxis=dict(title="연도", dtick=1),
        yaxis=dict(title="판매량 (Nm³)", ticksuffix=" "),
        barmode="stack",
        bargap=0.25,
    )

    return fig


def fig_total_by_year(long_df: pd.DataFrame) -> tuple[go.Figure, pd.DataFrame]:
    annual = (
        long_df.groupby(["연", "그룹"])[["실적"]]
        .sum()
        .reset_index()
        .pivot(index="연", columns="그룹", values="실적")
        .fillna(0)
    )

    total = annual.sum(axis=1)
    home = annual.get("가정용", pd.Series(index=annual.index, data=np.nan))

    df_table = pd.DataFrame(
        {
            "연": annual.index,
            "가정용": home.values,
            "합계": total.values,
        }
    )

    fig = go.Figure()
    fig.add_bar(
        name="총 실적 공급량",
        x=annual.index.tolist(),
        y=total.tolist(),
        marker_color="#1f77b4",
    )
    fig.update_layout(
        title="연도별 총 실적 공급량",
        xaxis=dict(title="연도", dtick=1),
        yaxis=dict(title="판매량 (Nm³)", ticksuffix=" "),
    )

    return fig, df_table


# ===================== 데이터 로딩 UI =====================

with st.sidebar:
    st.header("데이터 불러오기")
    src = st.radio("데이터 소스", ["레포 파일 사용", "엑셀 업로드(.xlsx)"], index=0)

    if src == "엑셀 업로드(.xlsx)":
        up = st.file_uploader("판매량(계획_실적).xlsx 업로드", type=["xlsx"])
        if up is not None:
            plan_raw, actual_raw = load_raw_data(up.getvalue())
        else:
            st.stop()
    else:
        if not DATA_PATH.exists():
            st.error("레포에 기본 엑셀 파일(판매량(계획_실적).xlsx)이 없습니다.")
            st.stop()
        plan_raw, actual_raw = load_raw_data(None)

long_df = build_group_long(plan_raw, actual_raw)

years_all = sorted(long_df["연"].unique())
default_2020_2025 = year_defaults(years_all, 2020, 2025)
latest_year = max(years_all)

# ===================== 레이아웃 탭 =====================

tab1, tab2, tab3, tab4 = st.tabs(
    ["📊 실적 분석", "📈 계획대비 분석", "🧱 기간별 누적 실적", "📦 연도별 총 실적"]
)

# -------------------------------------------------------
# 1) 실적 분석
# -------------------------------------------------------
with tab1:
    st.subheader("📊 실적 분석")

    st.markdown("#### 📉 월별 추이 그래프")

    sel_years = st.multiselect(
        "연도 선택(그래프)",
        years_all,
        default=default_2020_2025,  # 👉 2020~2025 디폴트
        key="trend_years",
    )

    group_options = [
        "총량",
        "가정용",
        "영업용",
        "업무용",
        "산업용",
        "수송용",
        "열병합",
        "연료전지",
        "열전용설비용",
    ]
    sel_group = st.segmented_control(
        "그룹 선택",
        group_options,
        default="총량",
        key="trend_group",
    )

    fig_trend = fig_monthly_trend(long_df, sel_group, sel_years)
    st.plotly_chart(fig_trend, use_container_width=True)

# -------------------------------------------------------
# 2) 계획대비 분석
# -------------------------------------------------------
with tab2:
    st.subheader("📈 계획대비 분석")

    # ---- (1) 연간 계획대비 실적 요약 — 그룹별 분석 ----
    st.markdown("### 📊 연간 계획대비 실적 요약 — 그룹별 분석")

    col_y, col_view, col_prev = st.columns([2, 2, 1])
    with col_y:
        sel_year_summary = st.selectbox(
            "연도 선택(집계)",
            years_all,
            index=years_all.index(latest_year),
            key="annual_summary_year",
        )
    with col_view:
        view_mode = st.radio(
            "표시 기준",
            ["그룹별 합계"],
            index=0,
            horizontal=True,
        )
    with col_prev:
        include_prev_annual = st.toggle("(Y-1) 포함", value=True, key="annual_prev_toggle")

    summary_df = make_annual_group_summary(long_df, sel_year_summary)

    fig_annual = fig_annual_group_summary(
        summary_df, sel_year_summary, include_prev_annual
    )
    st.plotly_chart(fig_annual, use_container_width=True)

    st.markdown("#### 📋 연간 요약 표")
    st.dataframe(
        summary_df.assign(
            계획=lambda d: d["계획"].map(format_number),
            실적=lambda d: d["실적"].map(format_number),
            **(
                {"Y-1 실적": summary_df["Y-1 실적"].map(format_number)}
                if "Y-1 실적" in summary_df.columns
                else {}
            ),
            차이_실적_계획=lambda d: d["차이(실적-계획)"].map(format_number),
            달성률_퍼센트=lambda d: d["달성률(%)"].round(1),
        ),
        use_container_width=True,
        hide_index=True,
    )

    st.markdown("---")

    # ---- (2) 계획대비 월별 실적 (용도 선택) ----
    st.markdown("### 📊 계획대비 월별 실적 (용도 선택)")

    c1, c2, c3 = st.columns([3, 2, 1])

    with c1:
        grp_sel = st.segmented_control(
            "용도(그룹) 선택",
            [
                "가정용",
                "영업용",
                "업무용",
                "산업용",
                "수송용",
                "열병합",
                "연료전지",
                "열전용설비용",
                "총량",  # 👉 총량 버튼 추가
            ],
            default="가정용",
            key="plan_group_sel",
        )
    with c2:
        base_year = st.selectbox(
            "기준 연도 선택",
            years_all,
            index=years_all.index(latest_year),
            key="plan_year_sel",
        )
    with c3:
        include_prev_monthly = st.toggle("(Y-1) 포함", value=True, key="monthly_prev_toggle")

    period = st.radio(
        "기간",
        ["연간", "상반기(1~6월)", "하반기(7~12월)"],
        index=0,
        horizontal=True,
        key="plan_period",
    )

    fig_plan_month, table_plan_month = fig_monthly_plan_vs_actual(
        long_df,
        group=grp_sel,
        year=base_year,
        period_label=period,
        include_prev=include_prev_monthly,
    )

    st.plotly_chart(fig_plan_month, use_container_width=True)

    st.markdown("#### 📋 월별 계획·실적·증감 요약")
    table_display = table_plan_month.copy()
    for col in ["계획", "실적", f"{base_year-1}년 실적", "차이(실적-계획)"]:
        if col in table_display.columns:
            table_display[col] = table_display[col].map(
                lambda v: "" if pd.isna(v) else format_number(v)
            )
    if "달성률(%)" in table_display.columns:
        table_display["달성률(%)"] = table_display["달성률(%)"].round(1)

    st.dataframe(
        table_display,
        use_container_width=True,
        hide_index=True,
    )

# -------------------------------------------------------
# 3) 기간별 누적 실적 (스택형 막대 + 라인)
# -------------------------------------------------------
with tab3:
    st.subheader("🧱 기간별 용도 누적 실적 (스택형 막대 + 라인)")

    sel_years_stack = st.multiselect(
        "연도 선택(스택 그래프)",
        years_all,
        default=default_2020_2025,  # 👉 2020~2025 디폴트
        key="stack_years",
    )

    period_stack = st.radio(
        "기간",
        ["연간", "상반기(1~6월)", "하반기(7~12월)"],
        index=0,
        horizontal=True,
        key="stack_period",
    )

    if sel_years_stack:
        fig_stack = fig_period_stack(long_df, sel_years_stack, period_stack)
        st.plotly_chart(fig_stack, use_container_width=True)
    else:
        st.info("연도를 하나 이상 선택해 주세요.")

# -------------------------------------------------------
# 4) 연도별 총 실적
# -------------------------------------------------------
with tab4:
    st.subheader("📦 연도별 총 실적")

    fig_total, table_total = fig_total_by_year(long_df)
    st.plotly_chart(fig_total, use_container_width=True)

    st.markdown("#### 📋 가정용 · 합계 요약")
    table_disp = table_total.copy()
    table_disp["가정용"] = table_disp["가정용"].map(format_number)
    table_disp["합계"] = table_disp["합계"].map(format_number)
    st.dataframe(table_disp, use_container_width=True, hide_index=True)
