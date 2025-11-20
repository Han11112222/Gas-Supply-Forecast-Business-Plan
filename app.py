from __future__ import annotations

import streamlit as st
import pandas as pd
import numpy as np
from pathlib import Path
import plotly.graph_objects as go

# ================= 기본 세팅 =================
st.set_page_config(
    page_title="도시가스 판매량 계획/실적 분석",
    layout="wide",
)

# ==== 색상 팔레트 (푸른색 계열) ====
COLOR_PLAN = "#1767b4"      # 진한 파란색 (계획)
COLOR_ACT = "#3fa3ff"       # 밝은 파란색 (실적)
COLOR_PREV = "#c0c8d5"      # 연한 회색/블루 (전년 실적)
COLOR_DIFF_LINE = "#0050aa" # 진한 파란색 (증감 꺾은선)
COLOR_LINE_ETC = "#6c6cff"  # 실적 분석 라인 등

# ================= 데이터 로드 =================
@st.cache_data
def load_excel(base_path: Path) -> pd.DataFrame:
    """
    엑셀 파일을 읽어서 아래 형태의 tidy 데이터로 변환해 반환.
    필수 컬럼(혹은 rename 대상):
    - 연도 (또는 '년도')
    - 월
    - 그룹 (또는 '용도')
    - 계획
    - 실적
    """
    df = pd.read_excel(base_path)

    # 컬럼명 정리 (엑셀 구조에 맞게 필요하면 수정)
    rename_map = {}
    if "년도" in df.columns and "연도" not in df.columns:
        rename_map["년도"] = "연도"
    if "용도" in df.columns and "그룹" not in df.columns:
        rename_map["용도"] = "그룹"
    df = df.rename(columns=rename_map)

    # 필수 컬럼 체크 (없으면 에러 메시지)
    required_cols = ["연도", "월", "그룹", "계획", "실적"]
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        raise ValueError(f"엑셀에 필요한 컬럼이 없습니다. 다음 컬럼을 확인하세요: {missing}")

    # 타입 정리
    df["연도"] = df["연도"].astype(int)
    df["월"] = df["월"].astype(int)

    # 단위 변환용 열량(MJ) 계산 (Nm³ → MJ, 계수는 필요시 수정)
    HEAT_FACTOR = 41.0
    df["계획_MJ"] = df["계획"] * HEAT_FACTOR
    df["실적_MJ"] = df["실적"] * HEAT_FACTOR

    # 총량(연도/월 합계) 추가
    total = (
        df.groupby(["연도", "월"], as_index=False)[["계획", "실적", "계획_MJ", "실적_MJ"]]
        .sum()
    )
    total["그룹"] = "총량"

    df_all = pd.concat([df, total], ignore_index=True)

    # 그룹 순서 고정
    group_order = [
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
    df_all["그룹"] = pd.Categorical(df_all["그룹"], categories=group_order, ordered=True)

    return df_all


BASE_PATH = Path(__file__).parent / "판매량(계획_실적).xlsx"
data = load_excel(BASE_PATH)

years_all = sorted(data["연도"].unique())
# 기본 분석 범위: 2020 ~ 2025가 있으면 그 범위, 없으면 전체
default_years_6 = [y for y in range(2020, 2026) if y in years_all]
if not default_years_6:
    default_years_6 = years_all

# ================= 공통 유틸 =================
def get_unit_columns(unit_mode: str):
    """단위 기준에 따라 사용할 컬럼명 반환"""
    if unit_mode.startswith("부피"):
        return "계획", "실적", "판매량 (Nm³)"
    else:
        return "계획_MJ", "실적_MJ", "판매량 (MJ)"


def year_multiselect(label: str, default_years: list[int]):
    options = years_all
    default = [y for y in default_years if y in options]
    if not default:
        default = [options[-1]]
    return st.multiselect(label, options=options, default=default)


def year_selectbox(label: str, default_year: int | None = None):
    options = years_all
    if default_year is None or default_year not in options:
        default_idx = len(options) - 1
    else:
        default_idx = options.index(default_year)
    return st.selectbox(label, options=options, index=default_idx)


def group_selector():
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
    return st.radio("그룹 선택", group_options, horizontal=True)


# ================= 화면 1. 실적 분석 =================
def draw_screen_actual_analysis(unit_mode: str):
    st.markdown("## 📊 실적 분석")
    st.markdown("### 📈 월별 추이 그래프")

    selected_years = year_multiselect("연도 선택(그래프)", default_years_6)
    group = group_selector()

    if not selected_years:
        st.warning("연도를 하나 이상 선택해 주세요.")
        return

    plan_col, act_col, y_label = get_unit_columns(unit_mode)

    fig = go.Figure()

    for year in selected_years:
        df_y = data[(data["연도"] == year) & (data["그룹"] == group)].sort_values("월")

        if df_y.empty:
            continue

        # 실적
        fig.add_trace(
            go.Scatter(
                x=df_y["월"],
                y=df_y[act_col],
                mode="lines+markers",
                name=f"{year}년 실적",
                line=dict(color=COLOR_LINE_ETC, width=2),
            )
        )
        # 계획 (점선)
        fig.add_trace(
            go.Scatter(
                x=df_y["월"],
                y=df_y[plan_col],
                mode="lines+markers",
                name=f"{year}년 계획",
                line=dict(color=COLOR_PREV, width=1.5, dash="dot"),
            )
        )

    fig.update_layout(
        height=550,
        margin=dict(l=40, r=40, t=30, b=40),
        xaxis=dict(title="월"),
        yaxis=dict(title=y_label),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
    )

    st.plotly_chart(fig, use_container_width=True)


# ================= 화면 2. 계획대비 분석 =================
def draw_screen_plan_vs_actual(unit_mode: str):
    st.markdown("## 📊 계획대비 분석")

    tab1, tab2 = st.tabs(
        ["📋 연간 계획대비 실적 요약 — 그룹별 분석", "📊 계획대비 월별 실적 (용도 선택)"]
    )

    plan_col, act_col, y_label = get_unit_columns(unit_mode)

    # ---------- 탭 1 : 연간 그룹별 ----------
    with tab1:
        col1, col2 = st.columns([2, 1])
        with col1:
            year = year_selectbox("연도 선택(집계)", default_year=2025)
        with col2:
            include_prev = st.toggle("(Y-1) 포함", value=True)

        view_mode = st.radio(
            "표시 기준", ["그룹별 합계", "그룹·용도 세부"], horizontal=True, index=0
        )

        df_y = data[data["연도"] == year].copy()

        if view_mode == "그룹별 합계":
            pivot = (
                df_y.groupby("그룹", as_index=False)[[plan_col, act_col]].sum()
            )
        else:
            # 이미 그룹 단위라 동일하지만 형태 유지
            pivot = df_y.groupby("그룹", as_index=False)[[plan_col, act_col]].sum()

        # 전년 실적
        prev_year = year - 1
        if include_prev and prev_year in years_all:
            df_prev = (
                data[data["연도"] == prev_year]
                .groupby("그룹", as_index=False)[act_col]
                .sum()
                .rename(columns={act_col: "전년실적"})
            )
            pivot = pivot.merge(df_prev, on="그룹", how="left")
        else:
            include_prev = False  # 실제 데이터 없으면 토글 무효

        pivot["차이"] = pivot[act_col] - pivot[plan_col]
        pivot["달성률(%)"] = np.where(
            pivot[plan_col] == 0, np.nan, pivot[act_col] / pivot[plan_col] * 100
        )

        st.markdown("### 📑 연간 요약 표")
        st.dataframe(
            pivot[["그룹", plan_col, act_col, "차이", "달성률(%)"]]
            .sort_values("그룹"),
            use_container_width=True,
            hide_index=True,
        )

        st.markdown("### 📊 선택 연도 그룹별 계획·실적 막대그래프")

        fig = go.Figure()
        x = pivot["그룹"]

        # 계획
        fig.add_trace(
            go.Bar(
                x=x,
                y=pivot[plan_col],
                name=f"{year}년 계획",
                marker_color=COLOR_PLAN,
                offsetgroup=0,
                width=0.25,
            )
        )
        # 실적
        fig.add_trace(
            go.Bar(
                x=x,
                y=pivot[act_col],
                name=f"{year}년 실적",
                marker_color=COLOR_ACT,
                offsetgroup=1,
                width=0.25,
            )
        )
        # 전년 실적 (있을 경우, 맨 오른쪽)
        if include_prev and "전년실적" in pivot.columns:
            fig.add_trace(
                go.Bar(
                    x=x,
                    y=pivot["전년실적"],
                    name=f"{prev_year}년 실적",
                    marker_color=COLOR_PREV,
                    offsetgroup=2,
                    width=0.25,
                )
            )

        fig.update_layout(
            barmode="group",
            height=550,
            margin=dict(l=40, r=40, t=30, b=40),
            xaxis=dict(title="그룹"),
            yaxis=dict(title=y_label),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        )

        st.plotly_chart(fig, use_container_width=True)

    # ---------- 탭 2 : 월별 계획대비 ----------
    with tab2:
        st.markdown("### 📊 계획대비 월별 실적 (용도 선택)")

        col1, col2, col3 = st.columns([2, 2, 1])
        with col1:
            group = group_selector()
        with col2:
            base_year = year_selectbox("기준 연도 선택", default_year=2025)
        with col3:
            include_prev = st.toggle("(Y-1) 포함", value=True, key="monthly_prev")

        period = st.radio(
            "기간",
            options=["연간", "상반기(1~6월)", "하반기(7~12월)"],
            horizontal=True,
            index=0,
        )

        df_y = data[(data["연도"] == base_year) & (data["그룹"] == group)].copy()

        # 기간 필터
        if period == "상반기(1~6월)":
            df_y = df_y[df_y["월"] <= 6]
            title_suffix = "(상반기)"
        elif period == "하반기(7~12월)":
            df_y = df_y[df_y["월"] >= 7]
            title_suffix = "(하반기)"
        else:
            title_suffix = "(연간)"

        df_y = df_y.sort_values("월")

        # 전년 실적
        prev_year = base_year - 1
        if include_prev and prev_year in years_all:
            df_prev = data[
                (data["연도"] == prev_year) & (data["그룹"] == group)
            ][["월", act_col]].rename(columns={act_col: "전년실적"})
            df_y = df_y.merge(df_prev, on="월", how="left")
        else:
            include_prev = False

        # 증감(실적-계획)
        df_y["증감"] = df_y[act_col] - df_y[plan_col]

        st.markdown(f"#### {base_year}년 {group} 판매량 및 증감 {title_suffix}")

        fig = go.Figure()
        x = df_y["월"]

        # 계획
        fig.add_trace(
            go.Bar(
                x=x,
                y=df_y[plan_col],
                name=f"{base_year}년 계획",
                marker_color=COLOR_PLAN,
                offsetgroup=0,
                width=0.25,
            )
        )
        # 실적
        fig.add_trace(
            go.Bar(
                x=x,
                y=df_y[act_col],
                name=f"{base_year}년 실적",
                marker_color=COLOR_ACT,
                offsetgroup=1,
                width=0.25,
            )
        )
        # 전년 실적 (막대 맨 오른쪽)
        if include_prev and "전년실적" in df_y.columns:
            fig.add_trace(
                go.Bar(
                    x=x,
                    y=df_y["전년실적"],
                    name=f"{prev_year}년 실적",
                    marker_color=COLOR_PREV,
                    offsetgroup=2,
                    width=0.25,
                )
            )

        # 증감 꺾은선 (보조축)
        fig.add_trace(
            go.Scatter(
                x=x,
                y=df_y["증감"],
                name="증감(실적-계획)",
                mode="lines+markers",
                line=dict(color=COLOR_DIFF_LINE, width=2),
                yaxis="y2",
            )
        )

        fig.update_layout(
            barmode="group",
            height=550,
            margin=dict(l=40, r=40, t=30, b=40),
            xaxis=dict(title="월"),
            yaxis=dict(title=y_label, side="left"),
            yaxis2=dict(
                title="증감",
                overlaying="y",
                side="right",
                showgrid=False,
            ),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        )

        st.plotly_chart(fig, use_container_width=True)

        st.markdown("#### 월별 계획·실적·전년실적·증감 표")
        show_cols = ["월", plan_col, act_col, "증감"]
        if include_prev and "전년실적" in df_y.columns:
            show_cols.insert(3, "전년실적")
        st.dataframe(
            df_y[show_cols].sort_values("월"),
            hide_index=True,
            use_container_width=True,
        )


# ================= 화면 3. 기간별 용도 누적 실적 =================
def draw_screen_period_stacked(unit_mode: str):
    st.markdown("## 🧱 기간별 용도 누적 실적 (스택형 막대 + 라인)")

    plan_col, act_col, y_label = get_unit_columns(unit_mode)

    selected_years = year_multiselect("연도 선택(스택 그래프)", default_years_6)
    period = st.radio(
        "기간",
        options=["연간", "상반기(1~6월)", "하반기(7~12월)"],
        horizontal=True,
        index=0,
    )

    if not selected_years:
        st.warning("연도를 하나 이상 선택해 주세요.")
        return

    df = data[data["연도"].isin(selected_years)].copy()

    # 기간 필터
    if period == "상반기(1~6월)":
        df = df[df["월"] <= 6]
        title_suffix = "상반기(1~6월)"
    elif period == "하반기(7~12월)":
        df = df[df["월"] >= 7]
        title_suffix = "하반기(7~12월)"
    else:
        title_suffix = "연간"

    # 그룹별 합계
    agg = (
        df.groupby(["연도", "그룹"], as_index=False)[act_col].sum()
    )

    # 가정용/합계 라인용 데이터
    total_by_year = (
        df.groupby("연도", as_index=False)[act_col].sum().rename(columns={act_col: "합계"})
    )
    home_by_year = (
        df[df["그룹"] == "가정용"]
        .groupby("연도", as_index=False)[act_col]
        .sum()
        .rename(columns={act_col: "가정용"})
    )
    join_line = total_by_year.merge(home_by_year, on="연도", how="left")

    st.markdown(f"### 연간 용도별 실적 판매량 (누적) — {title_suffix}")

    fig = go.Figure()

    groups = [
        g
        for g in data["그룹"].cat.categories
        if g in agg["그룹"].unique() and g != "총량"
    ]

    for g in groups:
        df_g = agg[agg["그룹"] == g]
        fig.add_trace(
            go.Bar(
                x=df_g["연도"],
                y=df_g[act_col],
                name=g,
            )
        )

    # 가정용 라인
    fig.add_trace(
        go.Scatter(
            x=join_line["연도"],
            y=join_line["가정용"],
            mode="lines+markers",
            name="가정용",
            line=dict(color="#9b59b6", width=2, dash="dot"),
        )
    )
    # 합계 라인
    fig.add_trace(
        go.Scatter(
            x=join_line["연도"],
            y=join_line["합계"],
            mode="lines+markers",
            name="합계",
            line=dict(color="#34495e", width=2),
        )
    )

    fig.update_layout(
        barmode="stack",
        height=600,
        margin=dict(l=40, r=40, t=30, b=40),
        xaxis=dict(title="연도"),
        yaxis=dict(title=y_label),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
    )

    st.plotly_chart(fig, use_container_width=True)


# ================= 화면 4. 연도별 총 실적 =================
def draw_screen_year_total(unit_mode: str):
    st.markdown("## 📦 연도별 총 실적")

    plan_col, act_col, y_label = get_unit_columns(unit_mode)

    # 연도별 합계
    yearly = (
        data.groupby("연도", as_index=False)[[plan_col, act_col]].sum()
    )
    yearly["차이"] = yearly[act_col] - yearly[plan_col]
    yearly["달성률(%)"] = np.where(
        yearly[plan_col] == 0, np.nan, yearly[act_col] / yearly[plan_col] * 100
    )

    st.markdown("### 📊 연도별 총 실적 막대그래프")

    fig = go.Figure()

    fig.add_trace(
        go.Bar(
            x=yearly["연도"],
            y=yearly[plan_col],
            name="계획",
            marker_color=COLOR_PLAN,
            width=0.45,
        )
    )
    fig.add_trace(
        go.Bar(
            x=yearly["연도"],
            y=yearly[act_col],
            name="실적",
            marker_color=COLOR_ACT,
            width=0.45,
        )
    )

    fig.update_layout(
        barmode="group",
        height=500,
        margin=dict(l=40, r=40, t=30, b=40),
        xaxis=dict(title="연도"),
        yaxis=dict(title=y_label),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
    )

    st.plotly_chart(fig, use_container_width=True)

    st.markdown("### 🧾 연도별 총 실적 표")
    st.dataframe(
        yearly,
        use_container_width=True,
        hide_index=True,
    )

    # 가정용/합계 요약
    home = (
        data[data["그룹"] == "가정용"]
        .groupby("연도", as_index=False)[act_col]
        .sum()
        .rename(columns={act_col: "가정용"})
    )
    total = (
        data.groupby("연도", as_index=False)[act_col]
        .sum()
        .rename(columns={act_col: "합계"})
    )
    summary = home.merge(total, on="연도", how="right")

    st.markdown("### 🔢 가정용 · 합계 요약")
    st.dataframe(
        summary.sort_values("연도"),
        use_container_width=True,
        hide_index=True,
    )


# ================= 메인 레이아웃 =================
st.markdown("# 도시가스 판매량 계획 / 실적 분석")

# 표시 기준 (부피 / 열량)
unit_mode = st.radio(
    "표시 기준",
    options=["부피 기준 (Nm³)", "열량 기준 (MJ)"],
    horizontal=True,
    index=0,
)

# 분석 화면 선택
screen = st.radio(
    "분석 화면 선택",
    options=["실적 분석", "계획대비 분석", "기간별 누적 실적", "연도별 총 실적"],
    horizontal=True,
    index=0,
)

if screen == "실적 분석":
    draw_screen_actual_analysis(unit_mode)
elif screen == "계획대비 분석":
    draw_screen_plan_vs_actual(unit_mode)
elif screen == "기간별 누적 실적":
    draw_screen_period_stacked(unit_mode)
else:
    draw_screen_year_total(unit_mode)
