from __future__ import annotations

from pathlib import Path
from typing import Dict

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# ================= 기본 세팅 =================
st.set_page_config(
    page_title="도시가스 판매량 계획·실적 분석",
    layout="wide",
)

# ======== 색상 팔레트 (푸른색 계열) ========
COLOR_PLAN = "#177bd4"   # 진한 파란색 (계획)
COLOR_ACT = "#4fa3ff"    # 밝은 파란색 (실적)
COLOR_PREV = "#d0d7e5"   # 옅은 그레이-블루 (Y-1 실적)
COLOR_DIFF = "#0050a0"   # 짙은 파란색 (증감 라인)

# 원시 엑셀 컬럼을 그룹으로 합산하는 규칙
GROUP_FORMULAS = {
    "가정용": ["취사용", "개별난방용", "중앙난방용", "자가열전용"],
    "영업용": ["일반용", "냉방용", "주한미군"],
    "업무용": ["업무난방용"],
    "산업용": ["산업용"],
    "수송용": ["수송용(CNG)", "수송용(BIO)"],
    "열병합": ["열병합용"],
    "연료전지": ["연료전지용"],
    "열전용설비용": ["열전용설비용"],
}


def segmented_single(label: str, options, default, key: str):
    """Streamlit 버전에 따라 segmented_control / radio 중 적절한 위젯 사용."""
    options = list(options)
    if hasattr(st, "segmented_control"):
        return st.segmented_control(
            label,
            options=options,
            selection_mode="single",
            default=default,
            key=key,
        )
    # fallback: radio
    default_index = options.index(default) if default in options else 0
    return st.radio(label, options, index=default_index, horizontal=True, key=key)


def _make_group_df(raw: pd.DataFrame) -> pd.DataFrame:
    base = raw[["연", "월"]].copy()
    for g, cols in GROUP_FORMULAS.items():
        base[g] = raw[cols].sum(axis=1)
    return base


def _build_tidy_from_pair(plan_raw: pd.DataFrame, act_raw: pd.DataFrame, unit_label: str) -> pd.DataFrame:
    """계획/실적 시트를 tidy 형태로 변환."""
    plan_g = _make_group_df(plan_raw)
    act_g = _make_group_df(act_raw)

    plan_g["구분"] = "계획"
    act_g["구분"] = "실적"

    long = pd.concat(
        [
            plan_g.melt(id_vars=["연", "월", "구분"], var_name="그룹", value_name="값"),
            act_g.melt(id_vars=["연", "월", "구분"], var_name="그룹", value_name="값"),
        ],
        ignore_index=True,
    )

    pivot = (
        long.pivot_table(index=["연", "월", "그룹"], columns="구분", values="값", aggfunc="sum")
        .reset_index()
        .rename_axis(None, axis=1)
    )

    pivot["단위"] = unit_label
    cols = ["연", "월", "그룹", "계획", "실적", "단위"]
    pivot = pivot[cols].sort_values(["연", "월", "그룹"]).reset_index(drop=True)
    return pivot


@st.cache_data
def load_data(xlsx_path_str: str) -> Dict[str, pd.DataFrame]:
    """엑셀에서 부피·열량 데이터를 모두 불러와 정리."""
    xlsx_path = Path(xlsx_path_str)
    if not xlsx_path.exists():
        raise FileNotFoundError(f"데이터 파일을 찾을 수 없음: {xlsx_path}")

    xls = pd.ExcelFile(xlsx_path)

    plan_v = pd.read_excel(xls, sheet_name="계획_부피")
    act_v = pd.read_excel(xls, sheet_name="실적_부피")
    plan_e = pd.read_excel(xls, sheet_name="계획_열량")
    act_e = pd.read_excel(xls, sheet_name="실적_열량")

    tidy_volume = _build_tidy_from_pair(plan_v, act_v, "부피")
    tidy_energy = _build_tidy_from_pair(plan_e, act_e, "열량")

    return {"부피": tidy_volume, "열량": tidy_energy}


def get_group_df(df: pd.DataFrame, group: str) -> pd.DataFrame:
    """선택된 그룹(또는 총량)에 대한 계획/실적."""
    if group == "총량":
        agg = df.groupby(["연", "월"], as_index=False)[["계획", "실적"]].sum()
        agg["그룹"] = "총량"
        agg["단위"] = df["단위"].iloc[0]
        return agg
    else:
        return df[df["그룹"] == group].copy()


def format_number(x: float) -> str:
    if pd.isna(x):
        return "-"
    return f"{x:,.0f}"


def main() -> None:
    base_dir = Path(__file__).parent
    # repo 루트에 있는 엑셀 파일 이름 그대로 사용
    data_file = base_dir / "판매량(계획_실적).xlsx"

    try:
        data_map = load_data(str(data_file))
    except Exception as e:  # noqa: BLE001
        st.error("데이터 파일을 불러오는 중 문제가 생겼어. 엑셀 파일 이름과 위치를 다시 확인해줘.")
        st.exception(e)
        return

    st.title("도시가스 판매량 계획 / 실적 분석")

    # ===== 단위 기준 선택 =====
    col_basis, _ = st.columns([1, 4])
    with col_basis:
        basis_label = st.radio(
            "표시 기준",
            ("부피 기준 (Nm³)", "열량 기준 (MJ)"),
            horizontal=True,
            index=0,
        )

    if "부피" in basis_label:
        unit_key = "부피"
        unit_str = "Nm³"
    else:
        unit_key = "열량"
        unit_str = "MJ"

    df_all = data_map[unit_key].copy()

    # 실적이 0이 아닌 연도만 사용 (2020~2025 기본)
    nonzero_years = sorted(df_all.loc[df_all["실적"] > 0, "연"].unique())
    default_years_2020_ = [y for y in nonzero_years if y >= 2020]

    # ===== 상단 페이지 네비게이션 =====
    page = st.radio(
        "분석 화면 선택",
        ("실적 분석", "계획대비 분석", "기간별 누적 실적", "연도별 총 실적"),
        horizontal=True,
        index=0,
    )

    # ---------------- 실적 분석 ----------------
    if page == "실적 분석":
        st.markdown("## 📊 실적 분석")
        st.markdown("### 📈 월별 추이 그래프")

        years = st.multiselect(
            "연도 선택(그래프)",
            options=nonzero_years,
            default=default_years_2020_,
            key="trend_years",
        )

        group_options = ["총량", "가정용", "영업용", "업무용", "산업용", "수송용", "열병합", "연료전지", "열전용설비용"]
        group = segmented_single(
            "그룹 선택",
            options=group_options,
            default="총량",
            key="trend_group",
        )

        if not years:
            st.info("연도를 하나 이상 선택해줘.")
            return

        trend_df = get_group_df(df_all, group)
        trend_df = trend_df[trend_df["연"].isin(years)].sort_values(["연", "월"])

        fig = go.Figure()
        color_cycle = [
            "#1768ac",
            "#1a9df0",
            "#4fa3ff",
            "#7bb6ff",
            "#9cc9ff",
            "#c0dbff",
        ]

        for idx, year in enumerate(years):
            ydf = trend_df[trend_df["연"] == year]
            color = color_cycle[idx % len(color_cycle)]
            fig.add_trace(
                go.Scatter(
                    x=ydf["월"],
                    y=ydf["계획"],
                    name=f"{year}년 계획",
                    mode="lines",
                    line=dict(color=color, dash="dot"),
                )
            )
            fig.add_trace(
                go.Scatter(
                    x=ydf["월"],
                    y=ydf["실적"],
                    name=f"{year}년 실적",
                    mode="lines+markers",
                    line=dict(color=color),
                )
            )

        fig.update_layout(
            xaxis=dict(title="월"),
            yaxis=dict(title=f"판매량 ({unit_str})"),
            legend=dict(orientation="v"),
            hovermode="x unified",
        )
        st.plotly_chart(fig, use_container_width=True)

    # ---------------- 계획대비 분석 ----------------
    elif page == "계획대비 분석":
        st.markdown("## 📌 계획대비 분석")

        # 공통 선택: 기준 연도
        year_options = nonzero_years
        default_index = year_options.index(2025) if 2025 in year_options else len(year_options) - 1

        col_y, col_dummy, col_toggle = st.columns([2, 5, 1.5])
        with col_y:
            year = st.selectbox(
                "기준 연도 선택",
                options=year_options,
                index=default_index,
                key="summary_year",
            )
        with col_toggle:
            include_prev_for_group = st.toggle("(Y-1) 포함", value=True, key="toggle_group_prev")

        prev_year = year - 1
        has_prev = prev_year in year_options

        # ----- 1) 연간 계획대비 실적 — 그룹별 -----
        st.markdown("### 🧮 연간 계획대비 실적 요약 — 그룹별 분석")

        year_df = df_all[df_all["연"] == year]
        summary = (
            year_df.groupby("그룹")[["계획", "실적"]]
            .sum()
            .reset_index()
            .sort_values("계획", ascending=False)
        )

        if has_prev:
            prev_df = (
                df_all[df_all["연"] == prev_year]
                .groupby("그룹")[["실적"]]
                .sum()
                .reset_index()
                .rename(columns={"실적": "Y-1실적"})
            )
            summary = summary.merge(prev_df, on="그룹", how="left")
        else:
            summary["Y-1실적"] = np.nan

        summary["차이(실적-계획)"] = summary["실적"] - summary["계획"]
        summary["달성률(%)"] = np.where(
            summary["계획"] > 0,
            (summary["실적"] / summary["계획"] * 100).round(1),
            np.nan,
        )

        fig1 = go.Figure()
        fig1.add_trace(
            go.Bar(
                x=summary["그룹"],
                y=summary["계획"],
                name=f"{year}년 계획",
                marker_color=COLOR_PLAN,
            )
        )
        fig1.add_trace(
            go.Bar(
                x=summary["그룹"],
                y=summary["실적"],
                name=f"{year}년 실적",
                marker_color=COLOR_ACT,
            )
        )

        if include_prev_for_group and has_prev:
            fig1.add_trace(
                go.Bar(
                    x=summary["그룹"],
                    y=summary["Y-1실적"],
                    name=f"{prev_year}년 실적",
                    marker_color=COLOR_PREV,
                )
            )

        fig1.update_layout(
            barmode="group",
            bargap=0.30,
            bargroupgap=0.10,
            xaxis=dict(title="그룹"),
            yaxis=dict(title=f"연간 판매량 ({unit_str})"),
            hovermode="x unified",
        )
        st.plotly_chart(fig1, use_container_width=True)

        # 연간 요약 표 (그래프 하단)
        display_summary = summary.copy()
        for col in ["계획", "실적", "Y-1실적", "차이(실적-계획)"]:
            display_summary[col] = display_summary[col].map(format_number)
        st.markdown("#### 📋 연간 계획·실적 요약표")
        st.dataframe(
            display_summary[["그룹", "계획", "실적", "Y-1실적", "차이(실적-계획)", "달성률(%)"]],
            use_container_width=True,
            hide_index=True,
        )

        # ----- 2) 월별 계획대비 실적 — 용도 선택 -----
        st.markdown("---")
        st.markdown("### 📆 계획대비 월별 실적 (용도 선택)")

        col_g, col_y2, col_period, col_toggle2 = st.columns([3, 2, 3, 1.5])
        with col_g:
            group_options = ["총량", "가정용", "영업용", "업무용", "산업용", "수송용", "
