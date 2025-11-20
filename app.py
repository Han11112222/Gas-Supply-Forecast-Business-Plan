# app.py — 도시가스 판매량 계획 / 실적 분석 (부피·열량)

import io
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd
import streamlit as st
import matplotlib as mpl
import plotly.express as px


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
            # 폰트 설정 실패해도 앱 동작에는 지장 없도록
            pass


set_korean_font()
st.set_page_config(page_title="도시가스 판매량 계획/실적 분석", layout="wide")


# ─────────────────────────────────────────────────────────
# 상수 · 기본 설정
# ─────────────────────────────────────────────────────────
DEFAULT_XLSX = "판매량(계획_실적).xlsx"

# 용도(컬럼) → 그룹(가정용/영업용/업무용/산업용/수송용/열병합/연료전지/열전용설비용) 매핑
USE_COL_TO_GROUP: Dict[str, str] = {
    "취사용": "가정용",
    "개별난방용": "가정용",
    "중앙난방용": "가정용",
    "자가열전용": "가정용",
    # "소 계" 는 위 네 개의 합계라서 총량 계산에서 중복 방지를 위해 제외
    "일반용": "영업용",
    "업무난방용": "업무용",
    "냉방용": "업무용",
    "주한미군": "업무용",
    "산업용": "산업용",
    "수송용(CNG)": "수송용",
    "수송용(BIO)": "수송용",
    "열병합용1": "열병합",
    "열병합용2": "열병합",
    # "열병합용" 역시 1,2 합계라서 제외
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
    # 날짜 인덱스 성격의 첫 컬럼(예: Unnamed: 0)은 버림
    if "Unnamed: 0" in out.columns:
        out = out.drop(columns=["Unnamed: 0"])
    out["연"] = pd.to_numeric(out["연"], errors="coerce").astype("Int64")
    out["월"] = pd.to_numeric(out["월"], errors="coerce").astype("Int64")
    return out


def make_long(plan_df: pd.DataFrame, actual_df: pd.DataFrame) -> pd.DataFrame:
    """
    계획_부피 / 실적_부피 와 같은 wide 형식을
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
# 시각화 유틸
# ─────────────────────────────────────────────────────────
def monthly_trend_section(long_df: pd.DataFrame, unit_label: str, key_prefix: str = ""):
    st.markdown("### 월별 추이 그래프")

    if long_df.empty:
        st.info("데이터가 없습니다.")
        return

    years = sorted(long_df["연"].unique().tolist())
    default_years = years[-5:] if len(years) > 5 else years

    sel_years = st.multiselect(
        "연도 선택(그래프)",
        options=years,
        default=default_years,
        key=f"{key_prefix}yrs",
    )

    if not sel_years:
        st.info("표시할 연도를 한 개 이상 선택해 주세요.")
        return

    # 그룹 선택 UI (segmented_control 있으면 사용, 없으면 radio로 대체)
    try:
        sel_group = st.segmented_control(
            "그룹",
            GROUP_OPTIONS,
            selection_mode="single",
            default="총량",
            key=f"{key_prefix}grp",
        )
    except Exception:
        sel_group = st.radio(
            "그룹",
            GROUP_OPTIONS,
            index=0,
            horizontal=True,
            key=f"{key_prefix}grp_radio",
        )

    base = long_df[long_df["연"].isin(sel_years)].copy()

    if sel_group == "총량":
        plot_df = (
            base.groupby(["연", "월", "계획/실적"], as_index=False)["값"]
            .sum()
            .sort_values(["연", "월", "계획/실적"])
        )
        plot_df["라벨"] = (
            plot_df["연"].astype(str) + "년 · " + plot_df["계획/실적"]
        )
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
        st.info("선택 조건에 해당하는 데이터가 없습니다.")
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
        yaxis_title=f"공급량 ({unit_label})",
        legend_title="연도 / 구분",
        margin=dict(l=10, r=10, t=10, b=10),
    )
    st.plotly_chart(fig, use_container_width=True)


def yearly_summary_section(long_df: pd.DataFrame, unit_label: str, key_prefix: str = ""):
    st.markdown("### 연간 계획대비 실적 요약 — 그룹별 분석")

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
        # 집계는 항상 그룹별로 보는 것이 목적이므로 별도 그룹 선택은 생략
        view_mode = st.radio(
            "표시 기준",
            ["그룹별 합계", "그룹·용도 세부"],
            index=0,
            horizontal=True,
            key=f"{key_prefix}summary_mode",
        )

    base = long_df[long_df["연"] == sel_year].copy()
    if base.empty:
        st.info("선택한 연도에 데이터가 없습니다.")
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

    # 계획·실적·차이·달성률 계산
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

    # 표 표시
    styled = pivot.style.format(
        {
            "계획": "{:,.0f}",
            "실적": "{:,.0f}",
            "차이(실적-계획)": "{:,.0f}",
            "달성률(%)": "{:,.1f}",
        }
    )
    st.dataframe(styled, use_container_width=True)

    # 막대그래프 (그룹별 계획 vs 실적)
    st.markdown("#### 선택 연도 그룹별 계획·실적 막대그래프")

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
    fig_bar.update_layout(
        xaxis_title=x_col,
        yaxis_title=f"연간 합계 ({unit_label})",
        margin=dict(l=10, r=10, t=10, b=10),
    )
    st.plotly_chart(fig_bar, use_container_width=True)


def total_volume_by_year_section(long_df: pd.DataFrame, unit_label: str, key_prefix: str = ""):
    st.markdown("### 전체 총 공급량 막대그래프 (연도별 · 계획/실적)")

    if long_df.empty:
        st.info("데이터가 없습니다.")
        return

    year_tot = (
        long_df.groupby(["연", "계획/실적"], as_index=False)["값"]
        .sum()
        .sort_values(["연", "계획/실적"])
    )

    fig = px.bar(
        year_tot,
        x="연",
        y="값",
        color="계획/실적",
        barmode="group",
    )
    fig.update_layout(
        xaxis_title="연도",
        yaxis_title=f"총 공급량 ({unit_label})",
        margin=dict(l=10, r=10, t=10, b=10),
    )
    st.plotly_chart(fig, use_container_width=True)


# ─────────────────────────────────────────────────────────
# 본문
# ─────────────────────────────────────────────────────────
st.title("도시가스 판매량 계획 / 실적 분석")

with st.sidebar:
    st.header("데이터 불러오기")
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
    st.info("유효한 시트를 찾지 못했습니다. 파일에 '계획_부피', '실적_부피' (또는 '계획_열량', '실적_열량') 시트가 있는지 확인해 주세요.")
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

            monthly_trend_section(df_long, unit_label=unit, key_prefix=prefix + "trend_")
            st.markdown("---")
            yearly_summary_section(df_long, unit_label=unit, key_prefix=prefix + "summary_")
            st.markdown("---")
            total_volume_by_year_section(df_long, unit_label=unit, key_prefix=prefix + "total_")
