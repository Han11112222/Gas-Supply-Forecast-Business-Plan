import io
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd
import matplotlib as mpl
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st


# ─────────────────────────────────────────────────────────
# 기본 설정
# ─────────────────────────────────────────────────────────
def set_korean_font():
    ttf = Path(__file__).parent / "NanumGothic-Regular.ttf"
    if ttf.exists():
        try:
            mpl.font_manager.fontManager.addfont(str(ttf))
            mpl.rcParams["font.family"] = "NanumGothic"
            mpl.rcParams["axes.unicode_minus"] = False
        except Exception:
            pass


set_korean_font()
st.set_page_config(page_title="도시가스 판매량 계획/실적 분석", layout="wide")

DEFAULT_XLSX = "판매량(계획_실적).xlsx"

# 엑셀 헤더 → 분석 그룹 매핑
USE_COL_TO_GROUP: Dict[str, str] = {
    "취사용": "가정용",
    "개별난방용": "가정용",
    "중앙난방용": "가정용",
    "자가열전용": "가정용",
    "일반용": "영업용",
    "업무난방용": "업무용",
    "냉방용": "업무용",
    "주한미군": "업무용",
    "산업용": "산업용",
    "수송용(CNG)": "수송용",
    "수송용(BIO)": "수송용",
    "열병합용1": "열병합",
    "열병합용2": "열병합",
    "연료전지용": "연료전지",
    "열전용설비용": "열전용설비용",
}

GROUP_OPTIONS: List[str] = [
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

# 계획대비 월별 그래프용 색상 (모두 푸른 계열 + 전년은 연회색)
COLOR_PLAN = "rgba(0, 90, 200, 1)"       # 기준연도 계획
COLOR_ACT = "rgba(0, 150, 255, 1)"      # 기준연도 실적
COLOR_PREV = "rgba(190, 190, 190, 1)"   # 전년 실적 (연회색)
COLOR_DIFF = "rgba(0, 80, 160, 1)"      # 증감 선


# ─────────────────────────────────────────────────────────
# 데이터 유틸
# ─────────────────────────────────────────────────────────
def _clean_base(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "Unnamed: 0" in out.columns:
        out = out.drop(columns=["Unnamed: 0"])
    out["연"] = pd.to_numeric(out["연"], errors="coerce").astype("Int64")
    out["월"] = pd.to_numeric(out["월"], errors="coerce").astype("Int64")
    return out


def make_long(plan_df: pd.DataFrame, actual_df: pd.DataFrame) -> pd.DataFrame:
    """wide → long (연·월·그룹·용도·계획/실적·값)."""
    plan_df = _clean_base(plan_df)
    actual_df = _clean_base(actual_df)

    records = []
    for label, df in [("계획", plan_df), ("실적", actual_df)]:
        for col, group in USE_COL_TO_GROUP.items():
            if col not in df.columns:
                continue
            base = df[["연", "월"]].copy()
            base["그룹"] = group
            base["용도"] = col
            base["계획/실적"] = label
            base["값"] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
            records.append(base)

    if not records:
        return pd.DataFrame(columns=["연", "월", "그룹", "용도", "계획/실적", "값"])

    long_df = pd.concat(records, ignore_index=True)
    long_df = long_df.dropna(subset=["연", "월"])
    long_df["연"] = long_df["연"].astype(int)
    long_df["월"] = long_df["월"].astype(int)
    return long_df


def load_all_sheets(excel_bytes: bytes) -> Dict[str, pd.DataFrame]:
    xls = pd.ExcelFile(io.BytesIO(excel_bytes), engine="openpyxl")
    needed = ["계획_부피", "실적_부피", "계획_열량", "실적_열량"]
    out: Dict[str, pd.DataFrame] = {}
    for name in needed:
        if name in xls.sheet_names:
            out[name] = xls.parse(name)
    return out


def build_long_dict(sheets: Dict[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:
    long_dict: Dict[str, pd.DataFrame] = {}
    if ("계획_부피" in sheets) and ("실적_부피" in sheets):
        long_dict["부피"] = make_long(sheets["계획_부피"], sheets["실적_부피"])
    if ("계획_열량" in sheets) and ("실적_열량" in sheets):
        long_dict["열량"] = make_long(sheets["계획_열량"], sheets["실적_열량"])
    return long_dict


# ─────────────────────────────────────────────────────────
# 1. 월별 추이
# ─────────────────────────────────────────────────────────
def monthly_trend_section(long_df: pd.DataFrame, unit_label: str, key_prefix: str = ""):
    st.markdown("### 📈 월별 추이 그래프")

    if long_df.empty:
        st.info("데이터가 없습니다.")
        return

    years = sorted(long_df["연"].unique().tolist())
    if not years:
        st.info("연도 정보가 없습니다.")
        return

    # 디폴트는 2025년, 없으면 마지막 연도
    if 2025 in years:
        default_years = [2025]
    else:
        default_years = [years[-1]]

    sel_years = st.multiselect(
        "연도 선택(그래프)",
        options=years,
        default=default_years,
        key=f"{key_prefix}trend_years",
    )
    if not sel_years:
        st.info("표시할 연도를 한 개 이상 선택해 줘.")
        return

    try:
        sel_group = st.segmented_control(
            "그룹 선택",
            GROUP_OPTIONS,
            selection_mode="single",
            default="총량",
            key=f"{key_prefix}trend_group",
        )
    except Exception:
        sel_group = st.radio(
            "그룹 선택",
            GROUP_OPTIONS,
            index=0,
            horizontal=True,
            key=f"{key_prefix}trend_group_radio",
        )

    base = long_df[long_df["연"].isin(sel_years)].copy()

    if sel_group == "총량":
        plot_df = (
            base.groupby(["연", "월", "계획/실적"], as_index=False)["값"]
            .sum()
            .sort_values(["연", "월", "계획/실적"])
        )
        plot_df["라벨"] = plot_df["연"].astype(str) + "년 · " + plot_df["계획/실적"]
    else:
        base = base[base["그룹"] == sel_group]
        plot_df = (
            base.groupby(["연", "월", "계획/실적"], as_index=False)["값"]
            .sum()
            .sort_values(["연", "월", "계획/실적"])
        )
        plot_df["라벨"] = (
            plot_df["연"].astype(str)
            + "년 · "
            + sel_group
            + " · "
            + plot_df["계획/실적"]
        )

    if plot_df.empty:
        st.info("선택 조건에 해당하는 데이터가 없어.")
        return

    fig = px.line(
        plot_df,
        x="월",
        y="값",
        color="라벨",
        line_dash="계획/실적",
        category_orders={"계획/실적": ["실적", "계획"]},
        line_dash_map={"실적": "solid", "계획": "dash"},
        markers=True,
    )
    fig.update_layout(
        xaxis=dict(dtick=1),
        yaxis_title=f"판매량 ({unit_label})",
        legend_title="연도 / 구분",
        margin=dict(l=10, r=10, t=10, b=10),
    )
    st.plotly_chart(fig, use_container_width=True)

    # 그래프 하단 요약표
    st.markdown("##### 🔢 월별 수치표")
    table = (
        plot_df.pivot_table(index="월", columns="라벨", values="값", aggfunc="sum")
        .sort_index()
        .fillna(0.0)
    )
    st.dataframe(table.style.format("{:,.0f}"), use_container_width=True)


# ─────────────────────────────────────────────────────────
# 2. 연간 계획대비 요약 (그래프 → 표, Y-1 토글)
# ─────────────────────────────────────────────────────────
def yearly_summary_section(long_df: pd.DataFrame, unit_label: str, key_prefix: str = ""):
    st.markdown("### 📊 연간 계획대비 실적 요약 — 그룹별 분석")

    if long_df.empty:
        st.info("데이터가 없습니다.")
        return

    years = sorted(long_df["연"].unique().tolist())
    if not years:
        st.info("연도 정보가 없습니다.")
        return

    if 2025 in years:
        default_index = years.index(2025)
    else:
        default_index = len(years) - 1

    col1, col2, col3 = st.columns([2, 2, 1.5])
    with col1:
        sel_year = st.selectbox(
            "연도 선택(집계)",
            options=years,
            index=default_index,
            key=f"{key_prefix}summary_year",
        )
    with col2:
        view_mode = st.radio(
            "표시 기준",
            ["그룹별 합계", "그룹·용도 세부"],
            index=0,
            horizontal=True,
            key=f"{key_prefix}summary_mode",
        )
    with col3:
        include_prev = st.toggle(
            "(Y-1) 포함", value=False, key=f"{key_prefix}summary_prev"
        )

    base_this = long_df[long_df["연"] == sel_year].copy()
    if base_this.empty:
        st.info("선택한 연도에 데이터가 없어.")
        return

    prev_year = sel_year - 1
    if include_prev:
        base_prev = long_df[
            (long_df["연"] == prev_year) & (long_df["계획/실적"] == "실적")
        ].copy()
    else:
        base_prev = pd.DataFrame([])

    # ── 집계: 올 해(grp_this) + 전년(grp_prev)
    if view_mode == "그룹별 합계":
        grp_this = (
            base_this.groupby(["그룹", "계획/실적"], as_index=False)["값"]
            .sum()
            .sort_values(["그룹", "계획/실적"])
        )
        idx_col = "그룹"

        if not base_prev.empty:
            grp_prev = (
                base_prev.groupby("그룹", as_index=False)["값"]
                .sum()
                .rename(columns={"값": "전년실적"})
            )
        else:
            grp_prev = pd.DataFrame([])

    else:  # 그룹·용도 세부
        base_this2 = base_this.copy()
        base_this2["그룹/용도"] = base_this2["그룹"] + " / " + base_this2["용도"]
        grp_this = (
            base_this2.groupby(["그룹/용도", "계획/실적"], as_index=False)["값"]
            .sum()
            .sort_values(["그룹/용도", "계획/실적"])
        )
        idx_col = "그룹/용도"

        if not base_prev.empty:
            base_prev2 = base_prev.copy()
            base_prev2["그룹/용도"] = (
                base_prev2["그룹"] + " / " + base_prev2["용도"]
            )
            grp_prev = (
                base_prev2.groupby("그룹/용도", as_index=False)["값"]
                .sum()
                .rename(columns={"값": "전년실적"})
            )
        else:
            grp_prev = pd.DataFrame([])

    # ── 요약표용 피벗 (올 해만)
    pivot = (
        grp_this.pivot(index=idx_col, columns="계획/실적", values="값")
        .fillna(0.0)
        .rename_axis(None, axis=1)
    )

    for c in ["계획", "실적"]:
        if c not in pivot.columns:
            pivot[c] = 0.0

    pivot["차이(실적-계획)"] = pivot["실적"] - pivot["계획"]
    with np.errstate(divide="ignore", invalid="ignore"):
        pivot["달성률(%)"] = np.where(
            pivot["계획"] != 0,
            (pivot["실적"] / pivot["계획"]) * 100.0,
            np.nan,
        )
    pivot = pivot[["계획", "실적", "차이(실적-계획)", "달성률(%)"]]

    # ── 그래프용 시리즈 (계획 / 실적 / 전년실적)
    plan_series = (
        grp_this[grp_this["계획/실적"] == "계획"].set_index(idx_col)["값"]
        if "계획" in grp_this["계획/실적"].values
        else pd.Series(dtype=float)
    )
    act_series = (
        grp_this[grp_this["계획/실적"] == "실적"].set_index(idx_col)["값"]
        if "실적" in grp_this["계획/실적"].values
        else pd.Series(dtype=float)
    )
    if not grp_prev.empty:
        prev_series = grp_prev.set_index(idx_col)["전년실적"]
    else:
        prev_series = pd.Series(dtype=float)

    cats = sorted(
        set(plan_series.index) | set(act_series.index) | set(prev_series.index)
    )
    if not cats:
        cats = list(pivot.index.astype(str))

    y_plan = [plan_series.get(c, 0.0) for c in cats]
    y_act = [act_series.get(c, 0.0) for c in cats]
    y_prev = [prev_series.get(c, 0.0) for c in cats] if not prev_series.empty else None

    # (1) 그래프
    st.markdown("#### 📊 선택 연도 그룹별 계획·실적 막대그래프")

    fig_bar = go.Figure()
    fig_bar.add_bar(
        x=cats,
        y=y_plan,
        name=f"{sel_year} 계획",
        marker_color=COLOR_PLAN,
    )
    fig_bar.add_bar(
        x=cats,
        y=y_act,
        name=f"{sel_year} 실적",
        marker_color=COLOR_ACT,
    )
    if include_prev and y_prev is not None:
        fig_bar.add_bar(
            x=cats,
            y=y_prev,
            name=f"{prev_year} 실적",
            marker_color=COLOR_PREV,  # Y-1은 연회색, 항상 맨 오른쪽
        )

    fig_bar.update_traces(width=0.35, selector=dict(type="bar"))
    fig_bar.update_layout(
        barmode="group",
        xaxis_title=idx_col,
        yaxis_title=f"연간 합계 ({unit_label})",
        margin=dict(l=10, r=10, t=10, b=10),
    )
    st.plotly_chart(fig_bar, use_container_width=True)

    # (2) 그래프 하단 연간 요약표
    st.markdown("##### 🔢 연간 요약 표")
    styled = pivot.style.format(
        {
            "계획": "{:,.0f}",
            "실적": "{:,.0f}",
            "차이(실적-계획)": "{:,.0f}",
            "달성률(%)": "{:,.1f}",
        }
    )
    st.dataframe(styled, use_container_width=True)

    # (3) 전체 메트릭
    tot_plan = float(pivot["계획"].sum())
    tot_act = float(pivot["실적"].sum())
    diff = tot_act - tot_plan
    rate = (tot_act / tot_plan * 100.0) if tot_plan != 0 else np.nan

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("계획 합계", f"{tot_plan:,.0f}")
    c2.metric("실적 합계", f"{tot_act:,.0f}")
    c3.metric("차이(실적-계획)", f"{diff:,.0f}")
    c4.metric("달성률(%)", f"{rate:,.1f}" if not np.isnan(rate) else "-")


# ─────────────────────────────────────────────────────────
# 3. 계획대비 월별 (Y계획, Y실적, 옵션 Y-1실적 + 증감 라인)
# ─────────────────────────────────────────────────────────
def plan_vs_actual_usage_section(
    long_df: pd.DataFrame, unit_label: str, key_prefix: str = ""
):
    st.markdown("### 🧮 계획대비 월별 실적 (용도 선택)")

    if long_df.empty:
        st.info("데이터가 없습니다.")
        return

    # 사용할 그룹 리스트 (총량 제외, 실제 존재하는 그룹만)
    groups_all = sorted(g for g in long_df["그룹"].unique() if g is not None)
    available_groups = [
        g for g in GROUP_OPTIONS if g != "총량" and g in groups_all
    ]
    if not available_groups:
        st.info("선택 가능한 그룹이 없습니다.")
        return

    years = sorted(long_df["연"].unique().tolist())
    if not years:
        st.info("연도 정보가 없습니다.")
        return

    if 2025 in years:
        default_year_index = years.index(2025)
    else:
        default_year_index = len(years) - 1

    col1, col2, col3 = st.columns([2, 2, 1.5])
    with col1:
        # 세그먼트 버튼 형태의 용도(그룹) 선택
        try:
            sel_group = st.segmented_control(
                "용도(그룹) 선택",
                available_groups,
                selection_mode="single",
                default="가정용"
                if "가정용" in available_groups
                else available_groups[0],
                key=f"{key_prefix}pv_group",
            )
        except Exception:
            sel_group = st.radio(
                "용도(그룹) 선택",
                available_groups,
                index=available_groups.index("가정용")
                if "가정용" in available_groups
                else 0,
                horizontal=True,
                key=f"{key_prefix}pv_group_radio",
            )

    with col2:
        sel_year = st.selectbox(
            "기준 연도 선택",
            options=years,
            index=default_year_index,
            key=f"{key_prefix}pv_year",
        )

    with col3:
        include_prev = st.toggle(
            "(Y-1) 포함", value=False, key=f"{key_prefix}pv_prev"
        )

    period = st.radio(
        "기간",
        ["연간", "상반기(1~6월)", "하반기(7~12월)"],
        index=0,
        horizontal=False,
        key=f"{key_prefix}pv_period",
    )

    base = long_df[long_df["그룹"] == sel_group].copy()

    if period == "상반기(1~6월)":
        month_mask = (base["월"] >= 1) & (base["월"] <= 6)
        period_label = "상반기"
    elif period == "하반기(7~12월)":
        month_mask = (base["월"] >= 7) & (base["월"] <= 12)
        period_label = "하반기"
    else:
        month_mask = base["월"] >= 1
        period_label = "연간"

    base = base[month_mask]
    if base.empty:
        st.info("선택 조건에 해당하는 데이터가 없어.")
        return

    # 기준 연도 데이터
    df_year = base[base["연"] == sel_year]
    if df_year.empty:
        st.info("선택한 연도의 데이터가 없어.")
        return

    prev_year = sel_year - 1
    if include_prev:
        df_prev = base[
            (base["연"] == prev_year) & (base["계획/실적"] == "실적")
        ]
    else:
        df_prev = pd.DataFrame([])

    bars = (
        df_year.groupby(["월", "계획/실적"], as_index=False)["값"]
        .sum()
        .sort_values(["월", "계획/실적"])
    )

    # 증감 계산(기준연도 실적-계획)
    plan_series = (
        bars[bars["계획/실적"] == "계획"].set_index("월")["값"].sort_index()
    )
    actual_series = (
        bars[bars["계획/실적"] == "실적"].set_index("월")["값"].sort_index()
    )
    months_all = sorted(set(plan_series.index) | set(actual_series.index))
    plan_aligned = plan_series.reindex(months_all).fillna(0.0)
    actual_aligned = actual_series.reindex(months_all).fillna(0.0)
    diff_series = actual_aligned - plan_aligned

    fig = go.Figure()

    # ① 기준연도 계획/실적 막대 (푸른 계열)
    for status, name, color in [
        ("계획", f"{sel_year}년 계획", COLOR_PLAN),
        ("실적", f"{sel_year}년 실적", COLOR_ACT),
    ]:
        sub = bars[bars["계획/실적"] == status]
        if sub.empty:
            continue
        fig.add_bar(
            x=sub["월"],
            y=sub["값"],
            name=name,
            width=0.25,
            marker_color=color,
        )

    # ② (옵션) 전년 실적 막대 — 항상 마지막 trace, 연회색
    if include_prev and not df_prev.empty:
        prev_group = (
            df_prev.groupby("월", as_index=False)["값"]
            .sum()
            .sort_values("월")
        )
        fig.add_bar(
            x=prev_group["월"],
            y=prev_group["값"],
            name=f"{prev_year}년 실적",
            width=0.25,
            marker_color=COLOR_PREV,
        )

    # ③ 증감(실적-계획) 꺾은선 — 우측 보조축
    if len(diff_series) > 0:
        fig.add_scatter(
            x=months_all,
            y=diff_series.values,
            mode="lines+markers",
            name="증감(실적-계획)",
            yaxis="y2",
            line=dict(color=COLOR_DIFF, width=2),
            marker=dict(color=COLOR_DIFF),
        )

    fig.update_layout(
        title=f"{sel_year}년 {sel_group} 판매량 및 증감 ({period_label})",
        xaxis_title="월",
        yaxis_title=f"판매량 ({unit_label})",
        xaxis=dict(dtick=1),
        margin=dict(l=10, r=10, t=40, b=10),
        barmode="group",
        yaxis2=dict(
            title="증감(실적-계획)",
            overlaying="y",
            side="right",
            showgrid=False,
        ),
    )
    st.plotly_chart(fig, use_container_width=True)

    # ④ 그래프 하단 요약표
    st.markdown("##### 🔢 월별 계획·실적·전년실적·증감 수치")
    table = (
        bars.pivot(index="월", columns="계획/실적", values="값")
        .sort_index()
        .fillna(0.0)
    )

    # (옵션) 전년 실적 컬럼
    if include_prev and not df_prev.empty:
        prev_tbl = (
            df_prev.groupby("월", as_index=False)["값"]
            .sum()
            .set_index("월")["값"]
        )
        table["전년실적"] = prev_tbl
    else:
        if "전년실적" in table.columns:
            table = table.drop(columns=["전년실적"])

    table["증감(실적-계획)"] = table.get("실적", 0.0) - table.get("계획", 0.0)
    st.dataframe(table.style.format("{:,.0f}"), use_container_width=True)


# ─────────────────────────────────────────────────────────
# 4. 기간별 스택 + 가정용/합계 라인 (실적 기준)
# ─────────────────────────────────────────────────────────
def half_year_stacked_section(
    long_df: pd.DataFrame, unit_label: str, key_prefix: str = ""
):
    st.markdown("### 🧱 기간별 용도 누적 실적 (스택형 막대 + 라인)")

    if long_df.empty:
        st.info("데이터가 없습니다.")
        return

    years = sorted(long_df["연"].unique().tolist())
    if not years:
        st.info("연도 정보가 없습니다.")
        return

    if 2025 in years:
        default_years = [2025]
    else:
        default_years = [years[-1]]

    sel_years = st.multiselect(
        "연도 선택(스택 그래프)",
        options=years,
        default=default_years,
        key=f"{key_prefix}stack_years",
    )
    if not sel_years:
        st.info("연도를 한 개 이상 선택해 줘.")
        return

    period = st.radio(
        "기간",
        ["연간", "상반기(1~6월)", "하반기(7~12월)"],
        index=0,
        horizontal=True,
        key=f"{key_prefix}period",
    )

    base = long_df[
        (long_df["연"].isin(sel_years)) & (long_df["계획/실적"] == "실적")
    ].copy()

    if period == "상반기(1~6월)":
        base = base[(base["월"] >= 1) & (base["월"] <= 6)]
        period_label = "상반기(1~6월)"
    elif period == "하반기(7~12월)":
        base = base[(base["월"] >= 7) & (base["월"] <= 12)]
        period_label = "하반기(7~12월)"
    else:
        period_label = "연간"

    if base.empty:
        st.info("선택 조건에 해당하는 데이터가 없어.")
        return

    grp = base.groupby(["연", "그룹"], as_index=False)["값"].sum()

    fig = px.bar(
        grp,
        x="연",
        y="값",
        color="그룹",
        barmode="stack",
    )
    fig.update_traces(width=0.4, selector=dict(type="bar"))

    # 합계 / 가정용 라인 + 숫자라벨
    total = grp.groupby("연", as_index=False)["값"].sum().rename(columns={"값": "합계"})
    home = (
        grp[grp["그룹"] == "가정용"]
        .groupby("연", as_index=False)["값"]
        .sum()
        .rename(columns={"값": "가정용"})
    )

    if not total.empty:
        total_text = total["합계"].apply(lambda v: f"{v:,.0f}")
        fig.add_scatter(
            x=total["연"],
            y=total["합계"],
            mode="lines+markers+text",
            name="합계",
            line=dict(dash="dash"),
            text=total_text,
            textposition="top center",
            textfont=dict(size=11),
        )

    if not home.empty:
        home_text = home["가정용"].apply(lambda v: f"{v:,.0f}")
        fig.add_scatter(
            x=home["연"],
            y=home["가정용"],
            mode="lines+markers+text",
            name="가정용",
            line=dict(dash="dot"),
            text=home_text,
            textposition="top center",
            textfont=dict(size=11),
        )

    fig.update_layout(
        title=f"{period_label} 용도별 실적 판매량 (누적)",
        xaxis_title="연도",
        yaxis_title=f"판매량 ({unit_label})",
        margin=dict(l=10, r=10, t=40, b=10),
    )
    st.plotly_chart(fig, use_container_width=True)

    # 그래프 하단 요약표
    st.markdown("##### 🔢 연도·그룹별 누적 실적 수치")
    summary = (
        grp.pivot(index="연", columns="그룹", values="값")
        .sort_index()
        .fillna(0.0)
    )
    summary["합계"] = summary.sum(axis=1)
    st.dataframe(summary.style.format("{:,.0f}"), use_container_width=True)


# ─────────────────────────────────────────────────────────
# 본문
# ─────────────────────────────────────────────────────────
st.title("도시가스 판매량 계획 / 실적 분석")

with st.sidebar:
    st.header("📂 데이터 불러오기")
    src = st.radio("데이터 소스", ["레포 파일 사용", "엑셀 업로드(.xlsx)"], index=0)
    excel_bytes = None
    base_info = ""
    if src == "엑셀 업로드(.xlsx)":
        up = st.file_uploader("판매량(계획_실적).xlsx 형식", type=["xlsx"])
        if up is not None:
            excel_bytes = up.getvalue()
            base_info = f"소스: 업로드 파일 — {up.name}"
    else:
        path = Path(__file__).parent / DEFAULT_XLSX
        if path.exists():
            excel_bytes = path.read_bytes()
            base_info = f"소스: 레포 파일 — {DEFAULT_XLSX}"
        else:
            base_info = f"레포 경로에 {DEFAULT_XLSX} 파일이 없습니다."

st.caption(base_info)

long_dict: Dict[str, pd.DataFrame] = {}
if excel_bytes is not None:
    sheets = load_all_sheets(excel_bytes)
    long_dict = build_long_dict(sheets)

tab_labels: List[str] = []
if "부피" in long_dict:
    tab_labels.append("부피 기준 (Nm³)")
if "열량" in long_dict:
    tab_labels.append("열량 기준 (MJ)")

if not tab_labels:
    st.info(
        "유효한 시트를 찾지 못했어. 파일에 '계획_부피', '실적_부피' (또는 '계획_열량', '실적_열량') 시트가 있는지 한 번 체크해 줘."
    )
else:
    tabs = st.tabs(tab_labels)
    for tab_label, tab in zip(tab_labels, tabs):
        with tab:
            if tab_label.startswith("부피"):
                df_long = long_dict.get("부피", pd.DataFrame())
                unit = "Nm³"
                prefix = "vol_"
            else:
                df_long = long_dict.get("열량", pd.DataFrame())
                unit = "MJ"
                prefix = "mj_"

            # 상단: 실적 중심
            st.markdown("## 📊 실적 분석")
            monthly_trend_section(df_long, unit_label=unit, key_prefix=prefix)
            half_year_stacked_section(
                df_long, unit_label=unit, key_prefix=prefix + "stack_"
            )

            st.markdown("---")

            # 하단: 계획대비 분석
            st.markdown("## 📏 계획대비 분석")
            yearly_summary_section(
                df_long, unit_label=unit, key_prefix=prefix + "summary_"
            )
            plan_vs_actual_usage_section(
                df_long, unit_label=unit, key_prefix=prefix + "pv_"
            )
