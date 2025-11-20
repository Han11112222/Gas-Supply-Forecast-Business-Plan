# app.py — 도시가스 판매량 계획 / 실적 분석 (부피·열량)

import io
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd
import streamlit as st
import matplotlib as mpl
import plotly.express as px
import plotly.graph_objects as go


# ─────────────────────────────────────────────────────────
# 폰트 설정
# ─────────────────────────────────────────────────────────
def set_korean_font():
    ttf = Path(__file__).parent / "NanumGothic-Regular.ttf"
    if ttf.exists():
        try:
            mpl.font_manager.fontManager.addfont(str(ttf))
            mpl.rcParams["font.family"] = "NanumGothic"
            mpl.rcParams["axes.unicode_minus"] = False
        except Exception:
            # 폰트 적용 실패해도 앱은 계속 동작
            pass


set_korean_font()
st.set_page_config(page_title="도시가스 판매량 계획/실적 분석", layout="wide")


# ─────────────────────────────────────────────────────────
# 상수 · 기본 설정
# ─────────────────────────────────────────────────────────
DEFAULT_XLSX = "판매량(계획_실적).xlsx"

# 엑셀 컬럼(용도) → 분석용 그룹 매핑
USE_COL_TO_GROUP: Dict[str, str] = {
    "취사용": "가정용",
    "개별난방용": "가정용",
    "중앙난방용": "가정용",
    "자가열전용": "가정용",  # 필요하면 별도 그룹으로 분리 가능
    # "소 계" 는 위 네 개 합계라서 제외
    "일반용": "영업용",
    "업무난방용": "업무용",
    "냉방용": "업무용",
    "주한미군": "업무용",
    "산업용": "산업용",
    "수송용(CNG)": "수송용",
    "수송용(BIO)": "수송용",
    "열병합용1": "열병합",
    "열병합용2": "열병합",
    # "열병합용" 은 1,2 합계라서 제외
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


# ─────────────────────────────────────────────────────────
# 데이터 유틸
# ─────────────────────────────────────────────────────────
def _clean_base(df: pd.DataFrame) -> pd.DataFrame:
    """공통 컬럼 정리(연·월 숫자 변환, 불필요 컬럼 제거)."""
    out = df.copy()
    if "Unnamed: 0" in out.columns:
        out = out.drop(columns=["Unnamed: 0"])
    out["연"] = pd.to_numeric(out["연"], errors="coerce").astype("Int64")
    out["월"] = pd.to_numeric(out["월"], errors="coerce").astype("Int64")
    return out


def make_long(plan_df: pd.DataFrame, actual_df: pd.DataFrame) -> pd.DataFrame:
    """
    wide 형식(계획_부피 / 실적_부피 등)을
    연·월·그룹·용도·계획/실적·값 long 포맷으로 변환.
    """
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
    """부피 / 열량 각각에 대해 long 데이터프레임 생성."""
    long_dict: Dict[str, pd.DataFrame] = {}
    if ("계획_부피" in sheets) and ("실적_부피" in sheets):
        long_dict["부피"] = make_long(sheets["계획_부피"], sheets["실적_부피"])
    if ("계획_열량" in sheets) and ("실적_열량" in sheets):
        long_dict["열량"] = make_long(sheets["계획_열량"], sheets["실적_열량"])
    return long_dict


# ─────────────────────────────────────────────────────────
# 계획대비 연간 요약
# ─────────────────────────────────────────────────────────
def yearly_summary_section(long_df: pd.DataFrame, unit_label: str, key_prefix: str = ""):
    st.markdown("### 📊 연간 계획대비 실적 요약 — 그룹별 분석")

    if long_df.empty:
        st.info("데이터가 없습니다.")
        return

    years = sorted(long_df["연"].unique().tolist())

    col1, col2 = st.columns(2)
    with col1:
        sel_year = st.selectbox(
            "연도 선택(집계)",
            options=years,
            index=len(years) - 1,
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

    base = long_df[long_df["연"] == sel_year].copy()
    if base.empty:
        st.info("선택한 연도에 데이터가 없어.")
        return

    if view_mode == "그룹별 합계":
        grp = (
            base.groupby(["그룹", "계획/실적"], as_index=False)["값"]
            .sum()
            .sort_values(["그룹", "계획/실적"])
        )
        pivot = (
            grp.pivot(index="그룹", columns="계획/실적", values="값")
            .fillna(0.0)
            .rename_axis(None, axis=1)
        )
    else:
        grp = (
            base.groupby(["그룹", "용도", "계획/실적"], as_index=False)["값"]
            .sum()
            .sort_values(["그룹", "용도", "계획/실적"])
        )
        grp["그룹/용도"] = grp["그룹"] + " / " + grp["용도"]
        pivot = (
            grp.pivot(index="그룹/용도", columns="계획/실적", values="값")
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

    st.markdown("#### 📊 선택 연도 그룹별 계획·실적 막대그래프")

    if view_mode == "그룹별 합계":
        bar_df = grp.copy()
        x_col = "그룹"
    else:
        bar_df = grp.copy()
        bar_df["그룹/용도"] = bar_df["그룹"] + " / " + bar_df["용도"]
        x_col = "그룹/용도"

    fig_bar = px.bar(
        bar_df,
        x=x_col,
        y="값",
        color="계획/실적",
        barmode="group",
    )
    fig_bar.update_traces(width=0.4, selector=dict(type="bar"))
    fig_bar.update_layout(
        xaxis_title=x_col,
        yaxis_title=f"연간 합계 ({unit_label})",
        margin=dict(l=10, r=10, t=10, b=10),
    )
    st.plotly_chart(fig_bar, use_container_width=True)

    # 숫자 박스 (전체 합계 메트릭)
    st.markdown("##### 🔢 전체 합계 박스")
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
# 계획대비 월별 (꺾은선 = 증감)
# ─────────────────────────────────────────────────────────
def plan_vs_actual_usage_section(long_df: pd.DataFrame, unit_label: str, key_prefix: str = ""):
    """특정 그룹 선택해서 월별 계획/실적 + 증감(실적-계획) 라인."""
    st.markdown("### 🧮 계획대비 월별 실적 (용도 선택)")

    if long_df.empty:
        st.info("데이터가 없습니다.")
        return

    groups = sorted(g for g in long_df["그룹"].unique() if g is not None)
    years = sorted(long_df["연"].unique().tolist())

    col1, col2, col3 = st.columns(3)
    with col1:
        sel_group = st.selectbox(
            "용도(그룹) 선택",
            options=groups,
            index=groups.index("가정용") if "가정용" in groups else 0,
            key=f"{key_prefix}pv_group",
        )
    with col2:
        sel_year = st.selectbox(
            "기준 연도 선택",
            options=years,
            index=len(years) - 1,
            key=f"{key_prefix}pv_year",
        )
    with col3:
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

    df_year = base[base["연"] == sel_year]

    # 막대: 기준 연도 계획/실적
    bars = (
        df_year.groupby(["월", "계획/실적"], as_index=False)["값"]
        .sum()
        .sort_values(["월", "계획/실적"])
    )

    if bars.empty:
        st.info("선택한 연도의 데이터가 없어.")
        return

    # 계획/실적 시리즈
    plan_series = (
        bars[bars["계획/실적"] == "계획"].set_index("월")["값"].sort_index()
    )
    actual_series = (
        bars[bars["계획/실적"] == "실적"].set_index("월")["값"].sort_index()
    )
    months_all = sorted(set(plan_series.index) | set(actual_series.index))
    plan_aligned = plan_series.reindex(months_all).fillna(0.0)
    actual_aligned = actual_series.reindex(months_all).fillna(0.0)
    diff_series = actual_aligned - plan_aligned  # 증감

    fig = go.Figure()

    # 계획 / 실적 막대 (폭 절반)
    for status, name in [("계획", f"{sel_year}년 계획"), ("실적", f"{sel_year}년 실적")]:
        sub = bars[bars["계획/실적"] == status]
        if sub.empty:
            continue
        fig.add_bar(
            x=sub["월"],
            y=sub["값"],
            name=name,
            width=0.4,
        )

    # 증감 꺾은선
    if not diff_series.empty:
        fig.add_scatter(
            x=diff_series.index,
            y=diff_series.values,
            mode="lines+markers",
            name="증감(실적-계획)",
            line=dict(color="crimson"),
        )

    fig.update_layout(
        title=f"{sel_year}년 {sel_group} 판매량 및 증감 ({period_label})",
        xaxis_title="월",
        yaxis_title=f"판매량 / 증감 ({unit_label})",
        xaxis=dict(dtick=1),
        margin=dict(l=10, r=10, t=40, b=10),
        barmode="group",
    )
    st.plotly_chart(fig, use_container_width=True)

    # 숫자 박스 (월별 계획/실적/증감 표)
    st.markdown("##### 🔢 월별 계획·실적·증감 수치")
    table = (
        bars.pivot(index="월", columns="계획/실적", values="값")
        .sort_index()
        .fillna(0.0)
    )
    table["증감(실적-계획)"] = (
        table.get("실적", 0.0) - table.get("계획", 0.0)
    )
    st.dataframe(
        table.style.format("{:,.0f}"),
        use_container_width=True,
    )


# ─────────────────────────────────────────────────────────
# 실적 중심: 기간별 용도 누적 (스택) + 가정용/합계 라인
# ─────────────────────────────────────────────────────────
def half_year_stacked_section(long_df: pd.DataFrame, unit_label: str, key_prefix: str = ""):
    """1H/2H/연간 용도별 '실적' 스택 + 가정용/합계 라인."""
    st.markdown("### 🧱 기간별 용도 누적 실적 (스택형 막대 + 라인)")

    if long_df.empty:
        st.info("데이터가 없습니다.")
        return

    years = sorted(long_df["연"].unique().tolist())
    default_years = years[-5:] if len(years) > 5 else years

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
        index=1,
        horizontal=True,
        key=f"{key_prefix}period",
    )

    # 실적만 사용 (계획 선택 제거)
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

    # 연·그룹별 합계 → 스택형 막대
    grp = base.groupby(["연", "그룹"], as_index=False)["값"].sum()

    fig = px.bar(
        grp,
        x="연",
        y="값",
        color="그룹",
        barmode="stack",
    )
    # 막대 폭 절반 정도로
    fig.update_traces(width=0.4, selector=dict(type="bar"))

    # 라인용 데이터: 전체 합계, 가정용 합계
    total = grp.groupby("연", as_index=False)["값"].sum()
    total.rename(columns={"값": "합계"}, inplace=True)

    home = grp[grp["그룹"] == "가정용"].groupby("연", as_index=False)["값"].sum()
    home.rename(columns={"값": "가정용"}, inplace=True)

    if not home.empty:
        fig.add_scatter(
            x=home["연"],
            y=home["가정용"],
            mode="lines+markers",
            name="가정용",
            line=dict(dash="dot"),
        )

    fig.add_scatter(
        x=total["연"],
        y=total["합계"],
        mode="lines+markers",
        name="합계",
        line=dict(dash="dash"),
    )

    fig.update_layout(
        title=f"{period_label} 용도별 실적 판매량 (누적)",
        xaxis_title="연도",
        yaxis_title=f"판매량 ({unit_label})",
        margin=dict(l=10, r=10, t=40, b=10),
    )

    st.plotly_chart(fig, use_container_width=True)

    # 숫자 박스 (연도·그룹별 누적 수치표)
    st.markdown("##### 🔢 연도·그룹별 누적 실적 수치")
    summary = (
        grp.pivot(index="연", columns="그룹", values="값")
        .sort_index()
        .fillna(0.0)
    )
    summary["합계"] = summary.sum(axis=1)
    st.dataframe(
        summary.style.format("{:,.0f}"),
        use_container_width=True,
    )


# ─────────────────────────────────────────────────────────
# 실적 중심: 연도별 총 공급량 (실적만)
# ─────────────────────────────────────────────────────────
def total_volume_by_year_section(long_df: pd.DataFrame, unit_label: str, key_prefix: str = ""):
    st.markdown("### 📦 연도별 총 실적 공급량")

    if long_df.empty:
        st.info("데이터가 없습니다.")
        return

    year_tot = (
        long_df[long_df["계획/실적"] == "실적"]
        .groupby("연", as_index=False)["값"]
        .sum()
        .sort_values(["연"])
    )

    fig = px.bar(
        year_tot,
        x="연",
        y="값",
    )
    fig.update_traces(width=0.4, selector=dict(type="bar"))
    fig.update_layout(
        xaxis_title="연도",
        yaxis_title=f"총 실적 공급량 ({unit_label})",
        margin=dict(l=10, r=10, t=10, b=10),
    )
    st.plotly_chart(fig, use_container_width=True)

    # 숫자 박스 (연도별 실적 표)
    st.markdown("##### 🔢 연도별 총 실적 표")
    table = (
        year_tot.set_index("연")[["값"]]
        .rename(columns={"값": "실적"})
        .sort_index()
    )
    st.dataframe(
        table.style.format("{:,.0f}"),
        use_container_width=True,
    )


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

tab_labels = []
if "부피" in long_dict:
    tab_labels.append("부피 기준 (Nm³)")
if "열량" in long_dict:
    tab_labels.append("열량 기준 (MJ)")

if not tab_labels:
    st.info(
        "유효한 시트를 찾지 못했어. 파일에 '계획_부피', '실적_부피' (또는 '계획_열량', '실적_열량') 시트가 있는지 한 번만 체크해 줘."
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

            # ── 상단: 실적 중심 분석 ──
            st.markdown("## 📊 실적 분석")
            half_year_stacked_section(df_long, unit_label=unit, key_prefix=prefix + "stack_")
            total_volume_by_year_section(df_long, unit_label=unit, key_prefix=prefix + "total_")

            st.markdown("---")

            # ── 하단: 계획대비 분석 ──
            st.markdown("## 📏 계획대비 분석")
            yearly_summary_section(df_long, unit_label=unit, key_prefix=prefix + "summary_")
            plan_vs_actual_usage_section(df_long, unit_label=unit, key_prefix=prefix + "pv_")
