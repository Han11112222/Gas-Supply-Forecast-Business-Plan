# app.py — 공급량 실적 및 계획 상세 (2024~2027 / 시나리오: 데이터, best, conservative)
# - 기본 파일: 레포의 '사업계획최종.xlsx'
# - 업로드 파일(.xlsx)로 덮어쓰기 지원
# - 시나리오 탭 + 연도 탭 + 요약 표 + 동적 그래프
# - NanumGothic 폰트 적용(Plotly/Matplotlib)

from __future__ import annotations

import os
import io
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

# plotly는 선택(설치되어 있지 않아도 동작)
try:
    import plotly.express as px
    import plotly.graph_objects as go
    HAS_PLOTLY = True
except Exception:
    HAS_PLOTLY = False

# ─────────────────────────────────────────────────────────────────────────────
# 환경/폰트
# ─────────────────────────────────────────────────────────────────────────────
APP_DIR = Path(__file__).parent
DEFAULT_REPO_FILE = APP_DIR / "사업계획최종.xlsx"
NANUM_TTF = APP_DIR / "NanumGothic-Regular.ttf"

def plotly_font_layout(fig):
    """Plotly 한글 폰트 통일."""
    family = "NanumGothic" if NANUM_TTF.exists() else None
    fig.update_layout(
        font=dict(family=family, size=14),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )
    return fig

# ─────────────────────────────────────────────────────────────────────────────
# 데이터 로드/정규화
# ─────────────────────────────────────────────────────────────────────────────
@st.cache_data(show_spinner=False)
def load_excel_bytes(b: bytes) -> dict[str, pd.DataFrame]:
    """업로드 바이트 → 모든 시트 dict."""
    import openpyxl  # noqa: F401
    xls = pd.ExcelFile(io.BytesIO(b), engine="openpyxl")
    return {sn: xls.parse(sn) for sn in xls.sheet_names}

@st.cache_data(show_spinner=False)
def load_excel_path(path: str | os.PathLike) -> dict[str, pd.DataFrame]:
    """경로 → 모든 시트 dict."""
    import openpyxl  # noqa: F401
    xls = pd.ExcelFile(path, engine="openpyxl")
    return {sn: xls.parse(sn) for sn in xls.sheet_names}

def normalize_sheet(df: pd.DataFrame) -> pd.DataFrame:
    """
    시트 → (연,월,항목,값) tidy.
    기대형식:
      - 연/월 칼럼이 있거나, '날짜' 칼럼에서 파생 가능
      - 나머지 열은 각 용도(일반용1, 일반용2, 산업용 등)
    """
    raw = df.copy()

    # 칼럼 표준화(공백 제거)
    raw.columns = [str(c).strip() for c in raw.columns]

    # '날짜'에서 연/월 파생 (있으면)
    if "연" not in raw.columns or "월" not in raw.columns:
        date_col = None
        for cand in ["날짜", "date", "Date", "일자"]:
            if cand in raw.columns:
                date_col = cand
                break
        if date_col is not None:
            # 날짜 파싱
            raw[date_col] = pd.to_datetime(raw[date_col], errors="coerce")
            raw["연"] = raw[date_col].dt.year.astype("Int64")
            raw["월"] = raw[date_col].dt.month.astype("Int64")

    # 연/월 없으면 실패
    if "연" not in raw.columns or "월" not in raw.columns:
        raise ValueError("시트에 '연'과 '월' 또는 '날짜' 칼럼이 필요합니다.")

    # 용도/항목 후보: 연/월/날짜/기타 메타를 제외한 숫자열
    meta_cols = {"연", "월", "날짜", "date", "Date", "일자"}
    value_cols = [c for c in raw.columns if c not in meta_cols]

    # 숫자 변환 + NaN→0
    for c in value_cols:
        raw[c] = pd.to_numeric(raw[c], errors="coerce").fillna(0)

    # 김칫국: 표기 교정 (오타/표준화)
    rename_map = {
        "주택미군": "주한미군",
        "자가열병합": "자가열전용",
        "자가열병합발전": "자가열전용",
        "열전용설비": "열전용설비용",
    }
    value_cols = [rename_map.get(c, c) for c in value_cols]
    raw.columns = [rename_map.get(c, c) for c in raw.columns]

    # melt
    tidy = raw.melt(id_vars=["연", "월"], value_vars=value_cols,
                    var_name="항목", value_name="값")

    # 월은 1~12만
    tidy = tidy[(tidy["월"] >= 1) & (tidy["월"] <= 12)]
    tidy["연"] = tidy["연"].astype("Int64")
    tidy["월"] = tidy["월"].astype("Int64")
    tidy["값"] = pd.to_numeric(tidy["값"], errors="coerce").fillna(0.0)

    # 항목 공백/None → 제외
    tidy = tidy[tidy["항목"].astype(str).str.strip().ne("")]
    return tidy

def make_pivot_table(tidy: pd.DataFrame,
                     item_order: list[str] | None = None) -> pd.DataFrame:
    """
    (연,월,항목,값) → 월별 표(행=항목, 열=1~12, 합계).
    """
    pivot = tidy.pivot_table(index="항목", columns="월", values="값", aggfunc="sum").fillna(0.0)
    # 1~12 컬럼 강제 정렬/보장
    cols = [m for m in range(1, 13)]
    for c in cols:
        if c not in pivot.columns:
            pivot[c] = 0.0
    pivot = pivot[cols]
    pivot["합계"] = pivot.sum(axis=1)

    # 항목 정렬 (있으면)
    if item_order:
        exist = [r for r in item_order if r in pivot.index]
        remain = [r for r in pivot.index if r not in exist]
        pivot = pivot.reindex(exist + remain)

    # 전체 합계 행 추가
    total = pd.DataFrame(pivot.sum(axis=0)).T
    total.index = ["합계"]
    pivot = pd.concat([pivot, total], axis=0)

    # 숫자 포맷용
    return pivot

def style_table(pivot: pd.DataFrame) -> "pd.io.formats.style.Styler":
    fmt = {c: "{:,.0f}" for c in pivot.columns}
    styler = pivot.style.format(fmt, na_rep="0")
    # 소계/합계 하이라이트
    def highlight(row):
        name = str(row.name)
        if ("소계" in name) or (name == "합계"):
            return ["background-color: rgba(0,0,0,0.06)"] * len(row)
        return ["" for _ in row]
    styler = styler.apply(highlight, axis=1)
    return styler

# ─────────────────────────────────────────────────────────────────────────────
# UI
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(page_title="공급량 실적 및 계획 상세", layout="wide")
st.title("📊 공급량 실적 및 계획 상세")

# 데이터 소스
with st.sidebar:
    st.header("데이터 불러오기")
    src = st.radio("데이터 소스", ["레포 파일 사용", "엑셀 업로드(.xlsx)"], index=0)

    upload_bytes = None
    if src == "엑셀 업로드(.xlsx)":
        up = st.file_uploader("엑셀 업로드", type=["xlsx"])
        if up:
            upload_bytes = up.read()

# 로드
if upload_bytes:
    sheets = load_excel_bytes(upload_bytes)
    source_label = "업로드 파일"
else:
    # 레포 파일 없으면 안내
    if not DEFAULT_REPO_FILE.exists():
        st.error("레포에 '사업계획최종.xlsx'가 없습니다. 좌측에서 엑셀을 업로드 해주세요.")
        st.stop()
    sheets = load_excel_path(str(DEFAULT_REPO_FILE))
    source_label = "레포 파일: 사업계획최종.xlsx"

# 시나리오(시트) 선택: 존재하는 것만
scenario_names = [n for n in ["데이터", "best", "conservative"] if n in sheets]
if not scenario_names:
    scenario_names = list(sheets.keys())  # 백업: 전부
scenario = st.tabs(scenario_names)

# 공통: 카테고리 정렬(표시 우선순위)
preferred_order = [
    # 가정/업무/산업 등 대표 용례 — 파일에 없으면 자동 스킵
    "취사용", "개별난방", "중앙난방", "소계",
    "일반용1", "일반용2", "냉난방용", "주한미군", "소계",
    "산업용", "열병합", "연료전지", "자가열전용", "열전용설비용",
    "CNG", "BIO", "소계"
]

st.caption(f"소스: {source_label}")

for tab, sn in zip(scenario, scenario_names):
    with tab:
        st.subheader(f"시나리오: {sn}")

        try:
            tidy = normalize_sheet(sheets[sn])
        except Exception as e:
            st.error(f"시트 '{sn}' 읽기 오류: {e}")
            continue

        # 사용 가능한 연도
        years = sorted(tidy["연"].dropna().unique().astype(int).tolist())
        years_disp = [y for y in [2024, 2025, 2026, 2027] if y in years]
        if not years_disp:
            years_disp = years

        # 연도 탭 구성
        year_tabs = st.tabs([f"{y}년 표" for y in years_disp])

        for yt, year in zip(year_tabs, years_disp):
            with yt:
                sub = tidy.query("연 == @year")
                pivot = make_pivot_table(sub, item_order=preferred_order)
                st.dataframe(style_table(pivot), use_container_width=True)

        st.markdown("---")
        st.subheader("월별 추이 그래프")

        # 그래프 필터
        years_pick = st.multiselect(
            "연도 선택", options=years_disp, default=years_disp, key=f"ysel_{sn}"
        )
        # 항목 목록
        items_all = sorted(tidy["항목"].unique().tolist())
        # 교정된 표기(보이기)
        show_items = st.multiselect(
            "항목 선택 (미선택 시 전체)",
            options=items_all, default=[], key=f"isel_{sn}"
        )

        view = tidy.query("연 in @years_pick").copy()
        if show_items:
            view = view.query("항목 in @show_items")

        # 월합(연/항목별)
        agg = (
            view.groupby(["연", "월"], as_index=False)["값"].sum()
            .sort_values(["연", "월"])
        )

        if agg.empty:
            st.info("선택한 조건에 해당하는 데이터가 없습니다.")
        else:
            title = f"{'·'.join(map(str, years_pick))}년 / {'전체' if not show_items else '·'.join(show_items)}"
            if HAS_PLOTLY:
                fig = px.line(
                    agg, x="월", y="값", color="연",
                    markers=True, title=title,
                    labels={"월": "월", "값": "공급량(㎥)"}
                )
                fig.update_xaxes(dtick=1, range=[0.9, 12.1])
                fig = plotly_font_layout(fig)
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.warning("plotly가 설치되어 있지 않아 기본 라인차트로 표시합니다. requirements.txt에 plotly를 추가하세요.")
                pivot_chart = agg.pivot_table(index="월", columns="연", values="값", aggfunc="sum").sort_index()
                st.line_chart(pivot_chart, height=420)

        st.caption("· 값이 비는 칸은 0으로 채워집니다. · '자가열병합' 표기는 자동으로 '자가열전용'으로 교정됩니다.")
