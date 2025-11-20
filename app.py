from __future__ import annotations

import streamlit as st
import pandas as pd
import numpy as np
from pathlib import Path
import plotly.graph_objects as go

# ========= 기본 세팅 =========
st.set_page_config(page_title="도시가스 판매량 계획·실적 분석", layout="wide")

# 색상 팔레트 (푸른색 계열)
COLOR_PLAN = "#1f77b4"      # 짙은 파란색 (계획)
COLOR_ACT = "#4fa3ff"       # 밝은 파란색 (실적)
COLOR_PREV = "#d0d7e5"      # 연한 그레이-블루 (전년 실적)
COLOR_DIFF = "#0050a0"      # 짙은 파란색 (증감 라인)


# ========= 데이터 불러오기 =========
@st.cache_data
def load_excel(path: Path) -> pd.DataFrame:
    df = pd.read_excel(path, sheet_name=0)
    df.columns = [str(c).strip() for c in df.columns]

    # 연/월/그룹/계획/실적 컬럼 자동 탐색
    def find_col(substrs):
        for s in substrs:
            cand = [c for c in df.columns if s in c]
            if cand:
                return cand[0]
        return None

    year_col = find_col(["연", "year", "년도"])
    month_col = find_col(["월", "month"])
    group_col = find_col(["그룹", "용도", "구분"])
    plan_col = find_col(["계획"])
    act_col = None
    # "실적" 중에 "계획"이 같이 들어간 경우를 피하기 위해
    for c in df.columns:
        if "실적" in c and "계획" not in c:
            act_col = c
            break

    if not all([year_col, month_col, group_col, plan_col, act_col]):
        raise ValueError(
            f"필수 컬럼(연/월/그룹/계획/실적)을 찾을 수 없습니다. 현재 컬럼: {df.columns.tolist()}"
        )

    tidy = df[[year_col, month_col, group_col, plan_col, act_col]].copy()
    tidy.rename(
        columns={
            year_col: "연",
            month_col: "월",
            group_col: "그룹",
            plan_col: "계획",
            act_col: "실적",
        },
        inplace=True,
    )

    # 월은 1~12 정수로 정리
    tidy["월"] = tidy["월"].astype(int)

    # 롱포맷 (타입: 계획/실적)
    long_df = tidy.melt(
        id_vars=["연", "월", "그룹"],
        value_vars=["계획", "실적"],
        var_name="타입",
        value_name="값",
    )

    return tidy, long_df


def get_default_years(all_years: list[int]) -> list[int]:
    cand = [y for y in all_years if 2020 <= y <= 2025]
    if cand:
        return cand
    # 없으면 최근 6개
    all_years_sorted = sorted(all_years)
    return all_years_sorted[-6:]


# ========= 사이드바 =========
st.sidebar.header("데이터 불러오기")
data_source = st.sidebar.radio(
    "데이터 소스",
    ["레포 파일 사용", "엑셀 업로드(.xlsx)"],
    index=0,
)

if data_source == "엑셀 업로드(.xlsx)":
    uploaded = st.sidebar.file_uploader("판매량(계획·실적) 파일 업로드", type=["xlsx"])
    if uploaded is None:
        st.stop()
    temp_path = Path("uploaded_판매량_계획실적.xlsx")
    with temp_path.open("wb") as f:
        f.write(uploaded.read())
    base_path = temp_path
else:
    # 레포에 있는 기본 파일 경로
    base_path = Path("판매량(계획_실적).xlsx")

tidy_df, long_df = load_excel(base_path)

all_years = sorted(tidy_df["연"].unique())
default_years = get_default_years(all_years)

groups = tidy_df["그룹"].unique().tolist()
groups_sorted = sorted(groups)
group_for_segment = ["총량"] + groups_sorted

# ========= 공통 유틸 =========
def filter_period(df: pd.DataFrame, period: str) -> pd.DataFrame:
    if period == "상반기(1~6월)":
        return df[df["월"].between(1, 6)]
    if period == "하반기(7~12월)":
        return df[df["월"].between(7, 12)]
    return df  # 연간


def fmt(num):
    if pd.isna(num):
        return ""
    return f"{num:,.0f}"


# ========= 레이아웃 시작 =========
st.title("도시가스 판매량 계획·실적 분석")

tab_actual, tab_plan_vs, tab_stack, tab_total = st.tabs(
    ["📊 실적 분석", "📑 계획대비 분석", "🧱 기간별 누적 실적", "📦 연도별 총 실적"]
)

# -----------------------------------------------------------------------------
# 1) 실적 분석 탭
# -----------------------------------------------------------------------------
with tab_actual:
    st.subheader("📊 실적 분석")
    st.markdown("##### 📈 월별 추이 그래프")

    sel_years = st.multiselect(
        "연도 선택(그래프)",
        options=all_years,
        default=default_years,
    )

    group_choice = st.segmented_control(
        "그룹 선택",
        options=group_for_segment,
        default="총량",
    )

    df_plot = long_df[(long_df["타입"] == "실적") & (long_df["연"].isin(sel_years))].copy()
    if group_choice != "총량":
        df_plot = df_plot[df_plot["그룹"] == group_choice]

    fig = go.Figure()
    for y in sorted(sel_years):
        d = df_plot[df_plot["연"] == y]
        if d.empty:
            continue
        fig.add_trace(
            go.Scatter(
                x=d["월"],
                y=d["값"],
                mode="lines+markers",
                name=f"{y}년 실적",
            )
        )

    fig.update_layout(
        height=500,
        xaxis_title="월",
        yaxis_title="판매량 (Nm³)",
        hovermode="x unified",
    )
    st.plotly_chart(fig, use_container_width=True)

# -----------------------------------------------------------------------------
# 2) 계획대비 분석 탭
# -----------------------------------------------------------------------------
with tab_plan_vs:
    st.subheader("📑 연간 계획대비 실적 요약 — 그룹별 분석")

    col_year, col_toggle = st.columns([3, 1])
    with col_year:
        base_year = col_year.selectbox("연도 선택(집계)", options=all_years, index=len(all_years) - 1)
    with col_toggle:
        include_prev = col_toggle.toggle("(Y-1) 포함", value=True)

    # 연간 집계
    yearly = (
        long_df.groupby(["연", "그룹", "타입"], as_index=False)["값"].sum()
    )

    # 집계용 현재년도 / 전년도 추출
    cur_plan = yearly[(yearly["연"] == base_year) & (yearly["타입"] == "계획")][
        ["그룹", "값"]
    ].set_index("그룹")["값"]
    cur_act = yearly[(yearly["연"] == base_year) & (yearly["타입"] == "실적")][
        ["그룹", "값"]
    ].set_index("그룹")["값"]
    prev_act = yearly[(yearly["연"] == base_year - 1) & (yearly["타입"] == "실적")][
        ["그룹", "값"]
    ].set_index("그룹")["값"]

    summary = pd.DataFrame(index=sorted(set(cur_plan.index) | set(cur_act.index) | set(prev_act.index)))
    summary["계획"] = cur_plan
    summary["실적"] = cur_act
    if include_prev:
        summary["전년실적"] = prev_act
    summary["차이(실적-계획)"] = summary["실적"] - summary["계획"]
    summary["달성률(%)"] = (summary["실적"] / summary["계획"] * 100).round(1)

    summary_display = summary.copy()
    for col in ["계획", "실적", "전년실적", "차이(실적-계획)"]:
        if col in summary_display.columns:
            summary_display[col] = summary_display[col].apply(fmt)

    # 막대그래프용 데이터
    bar_df = summary.reset_index().rename(columns={"index": "그룹"})
    fig2 = go.Figure()
    x = bar_df["그룹"]

    # 계획
    fig2.add_trace(
        go.Bar(
            x=x,
            y=bar_df["계획"],
            name=f"{base_year}년 계획",
            marker_color=COLOR_PLAN,
        )
    )
    # 실적
    fig2.add_trace(
        go.Bar(
            x=x,
            y=bar_df["실적"],
            name=f"{base_year}년 실적",
            marker_color=COLOR_ACT,
        )
    )
    # 전년 실적 (항상 오른쪽에 보이도록 마지막에 추가)
    if include_prev and "전년실적" in bar_df.columns:
        fig2.add_trace(
            go.Bar(
                x=x,
                y=bar_df["전년실적"],
                name=f"{base_year-1}년 실적",
                marker_color=COLOR_PREV,
            )
        )

    fig2.update_layout(
        barmode="group",
        bargap=0.25,
        height=500,
        xaxis_title="그룹",
        yaxis_title="연간 판매량 (Nm³)",
        hovermode="x unified",
        legend_title="구분",
    )
    st.plotly_chart(fig2, use_container_width=True)

    st.markdown("###### 📋 연간 계획대비 실적 요약표")
    st.dataframe(
        summary_display.reset_index().rename(columns={"index": "그룹"}),
        use_container_width=True,
        hide_index=True,
    )

    st.markdown("---")
    st.subheader("📊 계획대비 월별 실적 (용도 선택)")

    c1, c2, c3 = st.columns([3, 2, 2])
    with c1:
        group_sel = st.segmented_control(
            "용도(그룹) 선택",
            options=group_for_segment,
            default="가정용" if "가정용" in group_for_segment else group_for_segment[0],
        )
    with c2:
        base_year_m = st.selectbox("기준 연도 선택", options=all_years, index=len(all_years) - 1)
    with c3:
        period = st.radio("기간", ["연간", "상반기(1~6월)", "하반기(7~12월)"], index=0, horizontal=True)

    include_prev_month = st.toggle("월별 (Y-1) 포함", value=True, key="monthly_prev")

    df_month = tidy_df.copy()
    if group_sel != "총량":
        df_month = df_month[df_month["그룹"] == group_sel]

    df_month = filter_period(df_month, period)

    this_year = df_month[df_month["연"] == base_year_m]
    prev_year = df_month[df_month["연"] == base_year_m - 1]

    # 월별 계획/실적/전년실적 집계
    month_plan = (
        this_year.groupby("월")["계획"].sum()
        if not this_year.empty
        else pd.Series(dtype=float)
    )
    month_act = (
        this_year.groupby("월")["실적"].sum()
        if not this_year.empty
        else pd.Series(dtype=float)
    )
    prev_act_m = (
        prev_year.groupby("월")["실적"].sum()
        if include_prev_month and not prev_year.empty
        else pd.Series(dtype=float)
    )

    months = sorted(set(month_plan.index) | set(month_act.index) | set(prev_act_m.index))
    month_tbl = pd.DataFrame(index=months)
    month_tbl["계획"] = month_plan
    month_tbl["실적"] = month_act
    if include_prev_month:
        month_tbl["전년실적"] = prev_act_m
    month_tbl["차이(실적-계획)"] = month_tbl["실적"] - month_tbl["계획"]
    month_tbl["달성률(%)"] = (month_tbl["실적"] / month_tbl["계획"] * 100).round(1)

    # 그래프
    fig3 = go.Figure()
    x_m = month_tbl.index.tolist()

    fig3.add_trace(
        go.Bar(
            x=x_m,
            y=month_tbl["계획"],
            name=f"{base_year_m}년 계획",
            marker_color=COLOR_PLAN,
        )
    )
    fig3.add_trace(
        go.Bar(
            x=x_m,
            y=month_tbl["실적"],
            name=f"{base_year_m}년 실적",
            marker_color=COLOR_ACT,
        )
    )
    if include_prev_month and "전년실적" in month_tbl.columns:
        fig3.add_trace(
            go.Bar(
                x=x_m,
                y=month_tbl["전년실적"],
                name=f"{base_year_m-1}년 실적",
                marker_color=COLOR_PREV,
            )
        )

    # 증감 라인 (보조축)
    fig3.add_trace(
        go.Scatter(
            x=x_m,
            y=month_tbl["차이(실적-계획)"],
            name="증감(실적-계획)",
            mode="lines+markers",
            marker_color=COLOR_DIFF,
            yaxis="y2",
        )
    )

    fig3.update_layout(
        barmode="group",
        bargap=0.25,
        height=550,
        xaxis_title="월",
        yaxis_title="판매량 (Nm³)",
        hovermode="x unified",
        yaxis2=dict(
            title="증감 (Nm³)",
            overlaying="y",
            side="right",
            showgrid=False,
        ),
    )
    st.plotly_chart(fig3, use_container_width=True)

    # 요약표 (그래프 하단)
    month_tbl_display = month_tbl.copy()
    for col in ["계획", "실적", "전년실적", "차이(실적-계획)"]:
        if col in month_tbl_display.columns:
            month_tbl_display[col] = month_tbl_display[col].apply(fmt)

    st.markdown("###### 📋 월별 계획·실적·전년실적 요약표")
    st.dataframe(
        month_tbl_display.reset_index().rename(columns={"index": "월"}),
        use_container_width=True,
        hide_index=True,
    )

# -----------------------------------------------------------------------------
# 3) 기간별 누적 실적 (스택형 막대 + 라인)
# -----------------------------------------------------------------------------
with tab_stack:
    st.subheader("🧱 기간별 용도 누적 실적 (스택형 막대 + 라인)")

    sel_years_stack = st.multiselect(
        "연도 선택(스택 그래프)",
        options=all_years,
        default=default_years,
    )

    period_stack = st.radio(
        "기간",
        ["연간", "상반기(1~6월)", "하반기(7~12월)"],
        index=0,
        horizontal=True,
    )

    df_s = filter_period(tidy_df, period_stack)
    df_s = df_s[df_s["연"].isin(sel_years_stack)]

    grouped = (
        df_s.groupby(["연", "그룹"], as_index=False)[["실적"]].sum()
    )

    fig_s = go.Figure()

    # 스택 막대 (그룹별)
    for g in groups_sorted:
        g_df = grouped[grouped["그룹"] == g]
        if g_df.empty:
            continue
        fig_s.add_trace(
            go.Bar(
                x=g_df["연"],
                y=g_df["실적"],
                name=g,
            )
        )

    # 가정용 / 합계 라인
    total_by_year = grouped.groupby("연")["실적"].sum()
    home_by_year = grouped[grouped["그룹"] == "가정용"].groupby("연")["실적"].sum()

    fig_s.add_trace(
        go.Scatter(
            x=total_by_year.index,
            y=total_by_year.values,
            mode="lines+markers",
            name="합계",
            marker=dict(symbol="circle-open"),
            line=dict(dash="dash"),
            yaxis="y2",
        )
    )

    if not home_by_year.empty:
        fig_s.add_trace(
            go.Scatter(
                x=home_by_year.index,
                y=home_by_year.values,
                mode="lines+markers",
                name="가정용",
                marker=dict(symbol="square-open"),
                line=dict(dash="dot"),
                yaxis="y2",
            )
        )

    fig_s.update_layout(
        barmode="stack",
        bargap=0.2,
        height=600,
        xaxis_title="연도",
        yaxis_title="판매량 (Nm³)",
        yaxis2=dict(
            title="합계 / 가정용 (Nm³)",
            overlaying="y",
            side="right",
            showgrid=False,
        ),
        hovermode="x unified",
    )

    st.plotly_chart(fig_s, use_container_width=True)

# -----------------------------------------------------------------------------
# 4) 연도별 총 실적
# -----------------------------------------------------------------------------
with tab_total:
    st.subheader("📦 연도별 총 실적")

    yearly_total = (
        tidy_df.groupby(["연", "그룹"], as_index=False)["실적"].sum()
    )
    total_all = yearly_total.groupby("연")["실적"].sum()
    home_all = yearly_total[yearly_total["그룹"] == "가정용"].groupby("연")["실적"].sum()

    fig_t = go.Figure()
    fig_t.add_trace(
        go.Bar(
            x=total_all.index,
            y=total_all.values,
            name="총 실적 합계",
            marker_color=COLOR_ACT,
        )
    )

    fig_t.update_layout(
        height=500,
        xaxis_title="연도",
        yaxis_title="총 실적 (Nm³)",
        hovermode="x unified",
    )

    st.plotly_chart(fig_t, use_container_width=True)

    # 가정용·합계 요약표
    summary_year = pd.DataFrame({"연": total_all.index})
    summary_year["가정용"] = summary_year["연"].map(home_all).fillna(0)
    summary_year["합계"] = summary_year["연"].map(total_all).fillna(0)

    summary_year_display = summary_year.copy()
    summary_year_display["가정용"] = summary_year_display["가정용"].apply(fmt)
    summary_year_display["합계"] = summary_year_display["합계"].apply(fmt)

    st.markdown("###### 📋 가정용·합계 연도별 실적 요약")
    st.dataframe(summary_year_display, use_container_width=True, hide_index=True)
