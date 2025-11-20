from __future__ import annotations

import io
from pathlib import Path
from typing import Dict, Any, List

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# ================= 기본 세팅 =================
st.set_page_config(page_title="도시가스 판매량 계획·실적 분석", layout="wide")

# 색상 팔레트 (푸른색 계열)
COLOR_PLAN = "#1f77b4"   # 진한 파란색 (계획)
COLOR_ACT = "#4fa3ff"    # 밝은 파란색 (실적)
COLOR_PREV = "#c2ccd8"   # 연한 그레이-블루 (Y-1 실적)
COLOR_DIFF = "#0050a0"   # 진한 파란색 (증감 라인)

DEFAULT_FILE_NAME = "판매량(계획_실적).xlsx"

# 용도 → 그룹 맵핑
COL_TO_GROUP: Dict[str, str] = {
    # 가정용
    "취사용": "가정용",
    "개별난방용": "가정용",
    "중앙난방용": "가정용",
    "자가열전용": "가정용",
    "소 계": "가정용",
    # 영업/업무/산업
    "일반용": "영업용",
    "영업용": "영업용",
    "업무난방용": "업무용",
    "냉방용": "업무용",
    "산업용": "산업용",
    # 수송용
    "수송용(CNG)": "수송용",
    "수송용(BIO)": "수송용",
    # 열병합/연료전지/열전용설비
    "열병합용": "열병합",
    "열병합용1": "열병합",
    "열병합용2": "열병합",
    "연료전지용": "연료전지",
    "열전용설비용": "열전용설비용",
    # 기타
    "주한미군": "업무용",
}

GROUP_ORDER: List[str] = [
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

STACK_GROUP_ORDER: List[str] = [
    "가정용",
    "영업용",
    "업무용",
    "산업용",
    "수송용",
    "열병합",
    "연료전지",
    "열전용설비용",
]


def segmented_control(label: str, options: List[str], default: str, key: str) -> str:
    """Streamlit 버전에 따라 segmented_control / radio 둘 다 대응."""
    if hasattr(st, "segmented_control"):
        return st.segmented_control(label, options, default=default, key=key)
    # fallback
    index = options.index(default) if default in options else 0
    return st.radio(label, options, index=index, horizontal=True, key=key)


# =============== 데이터 로딩 ===============

@st.cache_data(show_spinner=False)
def load_excel_bytes(content: bytes) -> Dict[str, Dict[str, Any]]:
    """엑셀 바이트에서 부피/열량 데이터를 한 번에 로딩."""
    xls = pd.ExcelFile(io.BytesIO(content))

    def tidy(df: pd.DataFrame, 기준: str) -> pd.DataFrame:
        df = df.copy()
        # 날짜 컬럼 제거
        drop_cols = [c for c in df.columns if str(c).startswith("Unnamed")]
        df.drop(columns=drop_cols, inplace=True, errors="ignore")

        # 기본 컬럼 확인
        if "연" not in df.columns or "월" not in df.columns:
            raise ValueError("엑셀에 '연', '월' 컬럼이 없습니다. 템플릿을 확인하세요.")

        value_cols = [c for c in df.columns if c not in ("연", "월")]
        long = df.melt(
            id_vars=["연", "월"],
            value_vars=value_cols,
            var_name="용도",
            value_name="값",
        )
        long["그룹"] = long["용도"].map(COL_TO_GROUP).fillna("기타")
        long["기준"] = 기준
        # 정수형 보정
        long["연"] = long["연"].astype(int)
        long["월"] = long["월"].astype(int)
        long["값"] = pd.to_numeric(long["값"], errors="coerce").fillna(0.0)
        return long

    data: Dict[str, Dict[str, Any]] = {}
    sheet_map = {
        "부피": ("계획_부피", "실적_부피"),
        "열량": ("계획_열량", "실적_열량"),
    }

    for unit_key, (plan_sheet, act_sheet) in sheet_map.items():
        plan_df = xls.parse(plan_sheet)
        act_df = xls.parse(act_sheet)

        plan_long = tidy(plan_df, "계획")
        act_long = tidy(act_df, "실적")
        long = pd.concat([plan_long, act_long], ignore_index=True)

        years = sorted(long["연"].unique())
        data[unit_key] = {
            "plan": plan_df,
            "act": act_df,
            "long": long,
            "years": years,
        }

    return data


# ========= 공통 유틸 =========

def get_default_years(years: List[int]) -> List[int]:
    target = [y for y in years if 2020 <= y <= 2025]
    return target or years[-6:]


def filter_by_period(df: pd.DataFrame, period_label: str) -> pd.DataFrame:
    if "상반기" in period_label:
        return df[df["월"].between(1, 6)]
    if "하반기" in period_label:
        return df[df["월"].between(7, 12)]
    return df


# ========= 사이드바: 데이터 소스 =========

st.sidebar.header("데이터 불러오기")
src = st.sidebar.radio("데이터 소스", ("레포 파일 사용", "엑셀 업로드(.xlsx)"))

content: bytes
if src == "엑셀 업로드(.xlsx)":
    uploaded = st.sidebar.file_uploader("판매량(계획_실적).xlsx 파일을 선택하세요", type=["xlsx"])
    if uploaded is None:
        st.sidebar.info("엑셀 파일을 업로드하면 분석이 시작됩니다.")
        st.stop()
    content = uploaded.read()
    st.sidebar.success(f"업로드 파일: {uploaded.name}")
else:
    base_path = Path(__file__).parent / DEFAULT_FILE_NAME
    if not base_path.exists():
        st.error(f"레포지토리에 기본 파일({DEFAULT_FILE_NAME})이 없습니다.")
        st.stop()
    content = base_path.read_bytes()
    st.sidebar.caption(f"레포 파일 사용: {DEFAULT_FILE_NAME}")

data_all = load_excel_bytes(content)

# ========= 단위 선택 (부피 / 열량) =========

unit_choice = st.radio(
    "표시 기준",
    ["부피 기준 (Nm³)", "열량 기준 (MJ)"],
    horizontal=True,
    index=0,
)
if unit_choice.startswith("부피"):
    unit_key = "부피"
    y_label = "판매량 (Nm³)"
else:
    unit_key = "열량"
    y_label = "판매량 (MJ)"

unit_data = data_all[unit_key]
long_all: pd.DataFrame = unit_data["long"]
years_all: List[int] = unit_data["years"]

# ========= 상단 탭 =========
tab1, tab2, tab3, tab4 = st.tabs(
    ["📈 실적 분석", "📊 계획대비 분석", "🏗 기간별 누적 실적", "📦 연도별 총 실적"]
)

# =========================================
# 1. 실적 분석 탭
# =========================================
with tab1:
    st.subheader("📊 실적 분석")
    st.markdown("### 📉 월별 추이 그래프")

    default_years = get_default_years(years_all)
    sel_years = st.multiselect(
        "연도 선택(그래프)",
        options=years_all,
        default=default_years,
        key=f"trend_years_{unit_key}",
    )

    if not sel_years:
        st.info("연도를 하나 이상 선택해주세요.")
    else:
        group_sel = segmented_control(
            "그룹 선택",
            GROUP_ORDER,
            default="총량",
            key=f"trend_group_{unit_key}",
        )

        df = long_all[long_all["연"].isin(sel_years)].copy()
        if group_sel != "총량":
            df = df[df["그룹"] == group_sel]

        df = (
            df.groupby(["연", "월", "기준"], as_index=False)["값"]
            .sum()
            .sort_values(["연", "기준", "월"])
        )
        if df.empty:
            st.warning("선택한 조건에 해당하는 데이터가 없습니다.")
        else:
            fig = go.Figure()
            for (year, 기준), sub in df.groupby(["연", "기준"]):
                name = f"{year}년 {기준}"
                line_dash = "solid" if 기준 == "실적" else "dot"
                fig.add_trace(
                    go.Scatter(
                        x=sub["월"],
                        y=sub["값"],
                        mode="lines+markers",
                        name=name,
                        line=dict(dash=line_dash),
                    )
                )
            fig.update_layout(
                height=520,
                margin=dict(l=40, r=20, t=60, b=40),
                xaxis=dict(title="월", dtick=1),
                yaxis=dict(title=y_label),
                template="plotly_white",
            )
            st.plotly_chart(fig, use_container_width=True)

# =========================================
# 2. 계획대비 분석 탭
# =========================================
with tab2:
    st.subheader("📊 계획대비 분석")

    # ----- (1) 연간 계획대비 실적 요약 -----
    st.markdown("### 📘 연간 계획대비 실적 요약 — 그룹별 분석")

    col_year, col_view, col_y1 = st.columns([2, 2, 1.5])

    with col_year:
        base_year = st.selectbox(
            "연도 선택(집계)",
            options=sorted(years_all),
            index=sorted(years_all).index(2025) if 2025 in years_all else len(years_all) - 1,
            key=f"annual_year_{unit_key}",
        )
    with col_view:
        view_mode = st.radio(
            "표시 기준",
            ["그룹별 합계", "그룹·용도 세부"],
            horizontal=True,
            key=f"annual_view_{unit_key}",
        )
    with col_y1:
        include_y1_annual = st.toggle(
            "(Y-1) 포함",
            value=True,
            key=f"annual_y1_{unit_key}",
        )

    df_year = long_all[long_all["연"] == base_year].copy()
    if df_year.empty:
        st.warning("선택한 연도에 데이터가 없습니다.")
    else:
        if view_mode.startswith("그룹별"):
            group_cols = ["그룹"]
        else:
            group_cols = ["그룹", "용도"]

        g = df_year.groupby(group_cols + ["기준"], as_index=False)["값"].sum()
        pivot = g.pivot(index=group_cols, columns="기준", values="값").fillna(0.0)
        # 총량 행 추가 (그룹 기준일 때만)
        if group_cols == ["그룹"]:
            total = pivot.sum(axis=0)
            pivot.loc["총량"] = total

        # 표용 데이터
        tbl = pivot.copy()
        if "계획" not in tbl.columns:
            tbl["계획"] = 0.0
        if "실적" not in tbl.columns:
            tbl["실적"] = 0.0
        tbl["차이(실적-계획)"] = tbl["실적"] - tbl["계획"]
        tbl["달성률(%)"] = np.where(
            tbl["계획"] != 0, np.round(tbl["실적"] / tbl["계획"] * 100, 1), np.nan
        )

        tbl = tbl.reset_index().rename(
            columns={
                "계획": "계획",
                "실적": "실적",
            }
        )
        st.markdown("#### 📋 연간 요약표")
        st.dataframe(
            tbl.style.format(
                {
                    "계획": "{:,.0f}",
                    "실적": "{:,.0f}",
                    "차이(실적-계획)": "{:,.0f}",
                    "달성률(%)": "{:,.1f}",
                }
            ),
            use_container_width=True,
            hide_index=True,
        )

        # ----- 연간 그룹별 계획·실적 막대그래프 -----
        st.markdown("#### 📊 선택 연도 그룹별 계획·실적 막대그래프")

        # 그래프는 그룹 기준으로만 (시각화 단순화)
        g_graph = (
            df_year.groupby(["그룹", "기준"], as_index=False)["값"].sum()
        )
        pivot_graph = g_graph.pivot(
            index="그룹", columns="기준", values="값"
        ).fillna(0.0)

        # 총량 추가
        total_graph = pivot_graph.sum(axis=0)
        pivot_graph.loc["총량"] = total_graph

        prev_year = base_year - 1
        prev_act = (
            long_all[
                (long_all["연"] == prev_year) & (long_all["기준"] == "실적")
            ]
            .groupby("그룹")["값"]
            .sum()
        )
        prev_total = prev_act.sum()
        prev_act = prev_act.reindex(pivot_graph.index, fill_value=0.0)
        if "총량" in pivot_graph.index:
            prev_act.loc["총량"] = prev_total

        x_order = [g for g in GROUP_ORDER if g in pivot_graph.index]
        pivot_graph = pivot_graph.reindex(x_order)

        fig2 = go.Figure()
        fig2.add_bar(
            name=f"{base_year}년 계획",
            x=x_order,
            y=pivot_graph.get("계획", pd.Series(0, index=x_order)),
            marker_color=COLOR_PLAN,
        )
        fig2.add_bar(
            name=f"{base_year}년 실적",
            x=x_order,
            y=pivot_graph.get("실적", pd.Series(0, index=x_order)),
            marker_color=COLOR_ACT,
        )
        if include_y1_annual:
            fig2.add_bar(
                name=f"{prev_year}년 실적",
                x=x_order,
                y=prev_act.reindex(x_order),
                marker_color=COLOR_PREV,
            )

        fig2.update_layout(
            barmode="group",
            bargap=0.25,
            bargroupgap=0.1,
            height=520,
            margin=dict(l=40, r=20, t=50, b=40),
            yaxis=dict(title=y_label),
            template="plotly_white",
        )
        st.plotly_chart(fig2, use_container_width=True)

    # ----- (2) 계획대비 월별 실적 (용도 선택) -----
    st.markdown("---")
    st.markdown("### 📊 계획대비 월별 실적 (용도 선택)")

    col1, col2, col3 = st.columns([2.5, 2, 1.5])
    with col1:
        group_month = segmented_control(
            "용도(그룹) 선택",
            GROUP_ORDER,
            default="가정용",
            key=f"plan_month_group_{unit_key}",
        )
    with col2:
        base_year_month = st.selectbox(
            "기준 연도 선택",
            options=sorted(years_all),
            index=sorted(years_all).index(2025) if 2025 in years_all else len(years_all) - 1,
            key=f"plan_month_year_{unit_key}",
        )
    with col3:
        include_y1_month = st.toggle(
            "(Y-1) 포함",
            value=True,
            key=f"plan_month_y1_{unit_key}",
        )

    period_label = st.radio(
        "기간",
        ["연간", "상반기(1~6월)", "하반기(7~12월)"],
        horizontal=True,
        key=f"plan_month_period_{unit_key}",
    )

    months = np.arange(1, 13)

    df_cur = long_all[long_all["연"] == base_year_month].copy()
    df_prev = long_all[long_all["연"] == base_year_month - 1].copy()

    if group_month != "총량":
        df_cur = df_cur[df_cur["그룹"] == group_month]
        df_prev = df_prev[df_prev["그룹"] == group_month]

    cur_plan = (
        df_cur[df_cur["기준"] == "계획"].groupby("월")["값"].sum().reindex(months, fill_value=0.0)
    )
    cur_act = (
        df_cur[df_cur["기준"] == "실적"].groupby("월")["값"].sum().reindex(months, fill_value=0.0)
    )
    prev_act = (
        df_prev[df_prev["기준"] == "실적"].groupby("월")["값"].sum().reindex(months, fill_value=0.0)
    )

    month_df = pd.DataFrame(
        {
            "월": months,
            "계획": cur_plan.values,
            "실적": cur_act.values,
            "Y-1 실적": prev_act.values,
        }
    )
    month_df["증감(실적-계획)"] = month_df["실적"] - month_df["계획"]

    month_df = filter_by_period(month_df, period_label)

    fig3 = go.Figure()
    fig3.add_bar(
        name=f"{base_year_month}년 계획",
        x=month_df["월"],
        y=month_df["계획"],
        marker_color=COLOR_PLAN,
    )
    fig3.add_bar(
        name=f"{base_year_month}년 실적",
        x=month_df["월"],
        y=month_df["실적"],
        marker_color=COLOR_ACT,
    )
    if include_y1_month:
        fig3.add_bar(
            name=f"{base_year_month-1}년 실적",
            x=month_df["월"],
            y=month_df["Y-1 실적"],
            marker_color=COLOR_PREV,
        )

    fig3.add_trace(
        go.Scatter(
            name="증감(실적-계획)",
            x=month_df["월"],
            y=month_df["증감(실적-계획)"],
            mode="lines+markers",
            yaxis="y2",
            line=dict(color=COLOR_DIFF),
        )
    )

    fig3.update_layout(
        barmode="group",
        bargap=0.25,
        bargroupgap=0.1,
        height=520,
        margin=dict(l=40, r=50, t=60, b=40),
        xaxis=dict(title="월", dtick=1),
        yaxis=dict(title=y_label),
        yaxis2=dict(
            title="증감(실적-계획)",
            overlaying="y",
            side="right",
            showgrid=False,
            zeroline=True,
        ),
        template="plotly_white",
    )
    st.plotly_chart(fig3, use_container_width=True)

# =========================================
# 3. 기간별 누적 실적 탭
# =========================================
with tab3:
    st.subheader("🏗 기간별 용도 누적 실적 (스택형 막대 + 라인)")

    default_years_stack = get_default_years(years_all)
    sel_years_stack = st.multiselect(
        "연도 선택(스택 그래프)",
        options=years_all,
        default=default_years_stack,
        key=f"stack_years_{unit_key}",
    )

    period_stack = st.radio(
        "기간",
        ["연간", "상반기(1~6월)", "하반기(7~12월)"],
        horizontal=True,
        key=f"stack_period_{unit_key}",
    )

    if not sel_years_stack:
        st.info("연도를 하나 이상 선택해주세요.")
    else:
        df_stack = long_all[
            (long_all["연"].isin(sel_years_stack))
            & (long_all["기준"] == "실적")
        ].copy()
        df_stack = filter_by_period(df_stack, period_stack)

        if df_stack.empty:
            st.warning("선택한 조건에 해당하는 데이터가 없습니다.")
        else:
            g_stack = (
                df_stack.groupby(["연", "그룹"], as_index=False)["값"].sum()
            )
            pivot_stack = g_stack.pivot(
                index="연", columns="그룹", values="값"
            ).fillna(0.0)

            # 스택 순서 맞추기
            cols_order = [c for c in STACK_GROUP_ORDER if c in pivot_stack.columns]
            pivot_stack = pivot_stack.reindex(columns=cols_order)
            x_years = pivot_stack.index.tolist()

            fig4 = go.Figure()
            for col in cols_order:
                fig4.add_bar(
                    name=col,
                    x=x_years,
                    y=pivot_stack[col],
                )

            # 가정용 / 합계 라인 (보조축)
            home = (
                g_stack[g_stack["그룹"] == "가정용"]
                .groupby("연")["값"]
                .sum()
                .reindex(x_years, fill_value=0.0)
            )
            total = (
                g_stack.groupby("연")["값"]
                .sum()
                .reindex(x_years, fill_value=0.0)
            )

            fig4.add_trace(
                go.Scatter(
                    name="가정용",
                    x=x_years,
                    y=home,
                    mode="lines+markers",
                    yaxis="y2",
                    line=dict(dash="dot"),
                )
            )
            fig4.add_trace(
                go.Scatter(
                    name="합계",
                    x=x_years,
                    y=total,
                    mode="lines+markers",
                    yaxis="y2",
                    line=dict(dash="dash"),
                )
            )

            fig4.update_layout(
                barmode="stack",
                bargap=0.25,
                height=550,
                margin=dict(l=40, r=40, t=60, b=40),
                xaxis=dict(title="연도", dtick=1),
                yaxis=dict(title=y_label),
                yaxis2=dict(
                    title="가정용·합계",
                    overlaying="y",
                    side="right",
                    showgrid=False,
                ),
                template="plotly_white",
            )
            st.plotly_chart(fig4, use_container_width=True)

# =========================================
# 4. 연도별 총 실적 탭
# =========================================
with tab4:
    st.subheader("📦 연도별 총 실적")

    df_year_sum = (
        long_all[long_all["기준"] == "실적"]
        .groupby("연")["값"]
        .sum()
        .sort_index()
    )

    fig5 = go.Figure()
    fig5.add_bar(
        name="총 실적",
        x=df_year_sum.index.astype(int),
        y=df_year_sum.values,
        marker_color=COLOR_ACT,
    )
    fig5.update_layout(
        height=520,
        margin=dict(l=40, r=20, t=60, b=40),
        xaxis=dict(title="연도", dtick=1),
        yaxis=dict(title=y_label),
        template="plotly_white",
        showlegend=False,
    )
    st.plotly_chart(fig5, use_container_width=True)

    # 가정용·합계 요약 표
    home_sum = (
        long_all[
            (long_all["기준"] == "실적") & (long_all["그룹"] == "가정용")
        ]
        .groupby("연")["값"]
        .sum()
    )
    tbl_year = pd.DataFrame(
        {
            "연": df_year_sum.index.astype(int),
            "가정용": home_sum.reindex(df_year_sum.index, fill_value=0.0),
            "합계": df_year_sum.values,
        }
    )
    st.markdown("### 🔢 가정용·합계 요약")
    st.dataframe(
        tbl_year.style.format({"가정용": "{:,.0f}", "합계": "{:,.0f}"}),
        use_container_width=True,
        hide_index=True,
    )
