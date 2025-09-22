# app.py
# 공급량 실적 및 계획 상세 — 시나리오/연도별 표 + 동적 그래프 (전체→총량, 총량 라인 항상 표시)

import io
import os
import unicodedata
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd
import numpy as np
import streamlit as st
import matplotlib as mpl
import matplotlib.pyplot as plt
import plotly.express as px


# ─────────────────────────────────────────────────────────
# 환경 설정: 한글 폰트
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
st.set_page_config(page_title="공급량 실적 및 계획 상세", layout="wide")


# ─────────────────────────────────────────────────────────
# 사용자 정의
# ─────────────────────────────────────────────────────────
DEFAULT_XLSX = "사업계획최종.xlsx"  # 레포 안 기본 파일
DATE_COL_CANDIDATES = ["일자", "날짜", "date", "Date", "일", "기준일"]
# 열 이름 → (구분, 세부)
COL_TO_GROUP: Dict[str, Tuple[str, str]] = {
    # 가정용
    "취사용": ("가정용", "취사용"),
    "개별난방": ("가정용", "개별난방"),
    "중앙난방": ("가정용", "중앙난방"),
    "가정용소계": ("가정용", "소계"),
    "가정용소계(합계)": ("가정용", "소계"),
    "가정용 소계": ("가정용", "소계"),
    "소계(가정용)": ("가정용", "소계"),
    # 영업/업무/산업 등
    "일반용": ("영업용", "일반용"),
    "일반용1": ("영업용", "일반용1"),
    "일반용2": ("영업용", "일반용2"),
    "업무난방": ("업무용", "업무난방"),
    "냉난방": ("업무용", "냉난방용"),
    "냉난방용": ("업무용", "냉난방용"),
    "주한미군": ("업무용", "주한미군"),
    "소계": ("업무용", "소계"),  # (중복 허용)
    "산업용": ("산업용", "합계"),
    # 기타 에너지
    "열병합": ("열병합", "합계"),
    "연료전지": ("연료전지", "합계"),
    "자가열전용": ("자가열전용", "합계"),
    "자가열병합": ("자가열전용", "합계"),   # 잘못 표기도 수용
    "열전용설비용": ("열전용설비용", "합계"),
    "CNG": ("CNG", "합계"),
    # 수송용
    "BIO": ("수송용", "BIO"),
    "수송용소계": ("수송용", "소계"),
    "수송용 소계": ("수송용", "소계"),
    # 최종 합계
    "합계": ("합계", "합계"),
}

# 그래프/표에서 월 순서
MONTHS = list(range(1, 13))
YEARS = [2024, 2025, 2026, 2027]
SCENARIOS = ["데이터", "best", "conservative"]


# ─────────────────────────────────────────────────────────
# 유틸
# ─────────────────────────────────────────────────────────
def normalize_col(s: str) -> str:
    """띄어쓰기·NFC 정규화한 키 생성."""
    if not isinstance(s, str):
        return s
    s = unicodedata.normalize("NFC", s)
    s = s.strip()
    s = s.replace(" ", "")
    return s


@st.cache_data(show_spinner=False)
def read_excel_all_sheets(content: bytes) -> Dict[str, pd.DataFrame]:
    xls = pd.ExcelFile(io.BytesIO(content), engine="openpyxl")
    out: Dict[str, pd.DataFrame] = {}
    for sn in xls.sheet_names:
        df = xls.parse(sn)
        df.columns = [normalize_col(str(c)) for c in df.columns]
        out[sn] = df
    return out


def detect_date_col(df: pd.DataFrame) -> str | None:
    cols = [normalize_col(str(c)) for c in df.columns]
    for c in DATE_COL_CANDIDATES:
        if normalize_col(c) in cols:
            return normalize_col(c)
    # 날짜형 첫 번째 컬럼 자동 감지
    for c in df.columns:
        if np.issubdtype(df[c].dtype, np.datetime64):
            return normalize_col(str(c))
    return None


def _ensure_year_month(df: pd.DataFrame) -> pd.DataFrame:
    """연/월 열이 없으면 일자에서 파생."""
    out = df.copy()
    cols = [normalize_col(str(c)) for c in out.columns]
    colmap = {c: normalize_col(str(c)) for c in out.columns}
    out.rename(columns=colmap, inplace=True)

    if "연" not in out.columns or "월" not in out.columns:
        date_col = detect_date_col(out)
        if date_col and date_col in out.columns:
            out[date_col] = pd.to_datetime(out[date_col], errors="coerce")
            out["연"] = out[date_col].dt.year
            out["월"] = out[date_col].dt.month
    # 숫자화
    if "연" in out.columns:
        out["연"] = pd.to_numeric(out["연"], errors="coerce").astype("Int64")
    if "월" in out.columns:
        out["월"] = pd.to_numeric(out["월"], errors="coerce").astype("Int64")

    return out


def to_long(df: pd.DataFrame) -> pd.DataFrame:
    """wide → long (구분, 세부, 연, 월, 값). COL_TO_GROUP에 정의된 컬럼만 추출."""
    df = _ensure_year_month(df)

    if ("연" not in df.columns) or ("월" not in df.columns):
        return pd.DataFrame(columns=["구분", "세부", "연", "월", "값"])

    # 열 이름 정규화(공백 제거) 버전으로 매핑 키 찾기
    key_map = {}  # 실제 df 열명 -> (구분,세부)
    for raw_col in df.columns:
        n = normalize_col(str(raw_col))
        if n in COL_TO_GROUP:
            key_map[raw_col] = COL_TO_GROUP[n]

    if not key_map:
        return pd.DataFrame(columns=["구분", "세부", "연", "월", "값"])

    records = []
    base = df[["연", "월"]].copy()
    for raw_col, (gg, ss) in key_map.items():
        v = pd.to_numeric(df[raw_col], errors="coerce").fillna(0.0)
        tmp = base.copy()
        tmp["구분"] = gg
        tmp["세부"] = ss
        tmp["값"] = v
        records.append(tmp)

    long_df = pd.concat(records, ignore_index=True)
    long_df["연"] = pd.to_numeric(long_df["연"], errors="coerce").astype("Int64")
    long_df["월"] = pd.to_numeric(long_df["월"], errors="coerce").astype("Int64")
    long_df = long_df.dropna(subset=["연", "월"])
    return long_df


def make_pivot(long_df: pd.DataFrame, year: int) -> pd.DataFrame:
    view = long_df[long_df["연"] == year].copy()
    if view.empty:
        idx = pd.MultiIndex.from_tuples([], names=["구분", "세부"])
        pivot = pd.DataFrame(index=idx, columns=MONTHS).fillna(0.0)
        pivot["합계"] = 0.0
        return pivot

    pv = (
        view.groupby(["구분", "세부", "월"], as_index=False)["값"]
        .sum()
        .pivot_table(index=["구분", "세부"], columns="월", values="값", aggfunc="sum")
        .reindex(columns=MONTHS)
        .fillna(0.0)
    )
    pv.columns.name = ""
    pv["합계"] = pv.sum(axis=1)

    # 보기 순서
    group_order = [
        "가정용",
        "영업용",
        "업무용",
        "산업용",
        "열병합",
        "연료전지",
        "자가열전용",
        "열전용설비용",
        "CNG",
        "수송용",
        "합계",
    ]
    pv = pv.sort_index(level=[0, 1])
    pv = pv.reindex(
        pd.MultiIndex.from_tuples(
            sorted(pv.index, key=lambda t: (group_order.index(t[0]) if t[0] in group_order else 999, t[1]))
        )
    )
    return pv


def style_table(pivot: pd.DataFrame) -> "pd.io.formats.style.Styler":
    # Styler 쪽 버그 회피: 인덱스를 문자열로 강제
    p = pivot.copy()
    p.index = p.index.map(lambda t: " / ".join([str(t) for t in t]) if isinstance(t, tuple) else str(t))

    # 포맷
    fmt = {c: "{:,.0f}" for c in p.columns}
    styler = p.style.format(fmt, na_rep="0")

    # 소계/합계 연하게
    def highlight(row):
        name = str(row.name)
        if ("소계" in name) or (name.endswith("합계")) or (name == "합계"):
            return ["background-color: rgba(0,0,0,0.06)"] * len(row)
        return ["" for _ in row]

    styler = styler.apply(highlight, axis=1)
    return styler


def _safe_show_table(df: pd.DataFrame, *, key: str = ""):
    """Styler가 실패하면 문자열 포맷 DF로 폴백."""
    try:
        st.dataframe(style_table(df), use_container_width=True, key=f"sty_{key}")
    except Exception:
        df_str = df.copy()
        for c in df_str.columns:
            df_str[c] = pd.to_numeric(df_str[c], errors="coerce").fillna(0).round(0).astype(int)
            df_str[c] = df_str[c].map(lambda x: format(x, ","))
        st.dataframe(df_str, use_container_width=True, key=f"plain_{key}")


# ─────────────────────────────────────────────────────────
# 앱 본문
# ─────────────────────────────────────────────────────────
st.title("공급량 실적 및 계획 상세")

# 데이터 소스
with st.sidebar:
    st.header("데이터 불러오기")
    src = st.radio("데이터 소스", ["레포 파일 사용", "엑셀 업로드(.xlsx)"], index=0)
    excel_bytes: bytes | None = None
    base_info = f"소스: 레포 파일: {DEFAULT_XLSX}"
    if src == "엑셀 업로드(.xlsx)":
        up = st.file_uploader("엑셀 업로드", type=["xlsx"])
        if up:
            excel_bytes = up.getvalue()
            base_info = f"소스: 업로드 파일: {up.name}"
    if excel_bytes is None:
        path = Path(__file__).parent / DEFAULT_XLSX
        if path.exists():
            excel_bytes = path.read_bytes()

# 시나리오 탭 선택 (상단)
scenario = st.tabs(SCENARIOS)

# 엑셀 전 시트 읽기 (없으면 빈 dict)
sheets: Dict[str, pd.DataFrame] = {}
if excel_bytes:
    sheets = read_excel_all_sheets(excel_bytes)

st.caption(base_info)

# 시나리오별 화면 구성
for sn, tab in zip(SCENARIOS, scenario):
    with tab:
        st.subheader(f"시나리오: {sn}")

        # 시나리오에 해당하는 시트 찾기
        cand = [sn, "데이터"] if sn == "데이터" else [sn]
        sheet_name = None
        for s in cand:
            if s in sheets:
                sheet_name = s
                break

        if not sheet_name:
            st.info("해당 시나리오에 대응하는 시트를 찾지 못했습니다. (데이터/best/conservative)")
            continue

        raw = sheets[sheet_name]
        long_df = to_long(raw)

        # 연도 탭들
        ytabs = st.tabs([f"{y}년 표" for y in YEARS])

        for y, t in zip(YEARS, ytabs):
            with t:
                st.markdown(f"**{y}년 표**")
                pv = make_pivot(long_df, y)
                _safe_show_table(pv, key=f"{sn}_{y}")

        st.markdown("---")
        st.subheader("월별 추이 그래프")

        # 연도 선택(다중) + 그룹 선택 + 합계 포함 토글
        sel_years = st.multiselect("연도 선택(그래프)", YEARS, default=YEARS, key=f"yrs_{sn}")

        # ▶ ‘전체’ → ‘총량’으로 명확화
        group_options = ["총량", "가정용", "영업용", "업무용", "산업용",
                         "열병합", "연료전지", "자가열전용", "열전용설비용", "CNG", "수송용"]
        sel_group = st.segmented_control("그룹", group_options, selection_mode="single",
                                         default="총량", key=f"grp_{sn}")

        include_sum = st.toggle("합계 포함(시트 내 소계/합계 라인 포함)", value=False, key=f"sum_{sn}")

        # 기본 베이스(선택 연도)
        plot_base = long_df[long_df["연"].isin(sel_years)].copy()

        # 기본값에서는 시트 내 '합계' 구분 제거(이중집계 방지)
        if not include_sum:
            plot_base = plot_base[plot_base["구분"] != "합계"]

        # 선택 그룹 필터(총량은 별도 계산)
        group_df = plot_base.copy()
        if sel_group != "총량":
            group_df = group_df[group_df["구분"] == sel_group]

        # 그래프용: (1) 선택 그룹 월별 합, (2) 총량(전체소계량) 월별 합
        frames = []

        # (1) 선택 그룹
        if not group_df.empty and sel_group != "총량":
            g1 = (
                group_df.groupby(["연", "구분", "월"], as_index=False)["값"]
                .sum()
                .sort_values(["연", "구분", "월"])
            )
            g1["라벨"] = g1["연"].astype(str) + "년 · " + g1["구분"].astype(str)
            frames.append(g1)

        # (2) 총량: 구분 전체 합(항상 추가) — 사용자가 ‘총량’을 선택하면 이것만 보임
        total_df = (
            plot_base.groupby(["연", "월"], as_index=False)["값"].sum()
            .sort_values(["연", "월"])
        )
        total_df["구분"] = "총량"
        total_df["라벨"] = total_df["연"].astype(str) + "년 · 총량"

        if sel_group == "총량":
            frames = [total_df]
        else:
            frames.append(total_df)

        plot_df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

        if plot_df.empty:
            st.info("선택 조건에 해당하는 데이터가 없습니다.")
        else:
            fig = px.line(
                plot_df,
                x="월",
                y="값",
                color="라벨",
                markers=True,
            )
            fig.update_layout(
                xaxis=dict(dtick=1),
                yaxis_title="공급량",
                legend_title="연도/그룹",
                margin=dict(l=10, r=10, t=10, b=10),
            )
            st.plotly_chart(fig, use_container_width=True)
