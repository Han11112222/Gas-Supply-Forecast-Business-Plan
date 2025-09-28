# app.py
# 공급량 실적 및 계획 상세 — 표는 엑셀 헤더 순서 1:1 반영, 소계/합계는 시트에 있는 것만 표시
# 변경점:
#  - 월별 추이 그래프 하단에 "선택 그룹의 세부 구성 그래프" 추가
#  - 가정용 선택 시 (취사용, 개별난방, 중앙난방) 라인 동시 표시
#  - 소계/합계 포함 여부 체크박스 제공(기본 제외)

import io
import re
import unicodedata
from pathlib import Path
from typing import Dict, Tuple, List, Optional

import numpy as np
import pandas as pd
import streamlit as st
import matplotlib as mpl
import plotly.express as px

# ─────────────────────────────────────────────────────────
# 폰트
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
# 상수
# ─────────────────────────────────────────────────────────
DEFAULT_XLSX = "사업계획최종.xlsx"
DATE_COL_CANDIDATES = ["일자", "날짜", "date", "Date", "일", "기준일"]
PREDICT_START = {"year": 2025, "month": 11}  # 이 시점부터 예측(점선)

GROUP_NAMES = [
    "가정용", "영업용", "업무용", "산업용",
    "열병합", "연료전지", "자가열전용", "열전용설비용",
    "CNG", "수송용", "합계"
]

# 명시 매핑(정확히 일치할 때만)
COL_TO_GROUP: Dict[str, Tuple[str, str]] = {
    # 가정용
    "취사용": ("가정용", "취사용"),
    "개별난방": ("가정용", "개별난방"),
    "중앙난방": ("가정용", "중앙난방"),
    "가정용소계": ("가정용", "소계"),
    "가정용 소계": ("가정용", "소계"),
    "소계(가정용)": ("가정용", "소계"),
    # 영업/업무/산업
    "일반용": ("영업용", "일반용"),
    "일반용1": ("영업용", "일반용1"),
    "일반용2": ("영업용", "일반용2"),
    "업무난방": ("업무용", "업무난방"),
    "냉난방": ("업무용", "냉난방용"),
    "냉난방용": ("업무용", "냉난방용"),
    "주한미군": ("업무용", "주한미군"),
    "업무용소계": ("업무용", "소계"),
    "업무용 소계": ("업무용", "소계"),
    "산업용": ("산업용", "합계"),
    # 기타
    "열병합": ("열병합", "합계"),
    "열병합용": ("열병합", "용"),
    "연료전지": ("연료전지", "합계"),
    "자가열전용": ("자가열전용", "합계"),
    "자가열병합": ("자가열전용", "합계"),
    "열전용설비용": ("열전용설비용", "합계"),
    "CNG": ("CNG", "합계"),
    # 수송용
    "BIO": ("수송용", "BIO"),
    "수송용소계": ("수송용", "소계"),
    "수송용 소계": ("수송용", "소계"),
    # 전체
    "합계": ("합계", "합계"),
}

MONTHS = list(range(1, 13))
YEARS  = [2024, 2025, 2026, 2027, 2028]
SCENARIOS = ["데이터", "best", "conservative"]

# ─────────────────────────────────────────────────────────
# 유틸
# ─────────────────────────────────────────────────────────
def normalize_col(s: str) -> str:
    if not isinstance(s, str):
        return s
    return unicodedata.normalize("NFC", s).strip()

def simplify_key(s: str) -> str:
    """비교용 키(구분자 제거/소문자)."""
    s = normalize_col(s)
    return re.sub(r"[ \t/,_\-.]+", "", s).lower()

def try_parse_explicit(raw_name: str) -> Optional[Tuple[str, str]]:
    """명시 매핑 또는 '그룹{구분자}세부'/'그룹세부'를 파싱."""
    n = normalize_col(raw_name)
    key = simplify_key(n)

    # 1) 정확 매핑
    for k, (g, s) in COL_TO_GROUP.items():
        if simplify_key(k) == key:
            return (g, s)

    # 2) '그룹{구분자}세부'
    parts = re.split(r"[ \t/,_\-.]+", n)
    if len(parts) >= 2:
        g_cand = parts[0]
        s_cand = " ".join(parts[1:])
        if g_cand in GROUP_NAMES:
            return (g_cand, s_cand)

    # 3) '그룹세부'
    for g in GROUP_NAMES:
        if n.startswith(g):
            rest = n[len(g):].strip()
            if rest:
                return (g, rest)
    return None

@st.cache_data(show_spinner=False)
def read_excel_all_sheets(content: bytes) -> Dict[str, pd.DataFrame]:
    xls = pd.ExcelFile(io.BytesIO(content), engine="openpyxl")
    out: Dict[str, pd.DataFrame] = {}
    for sn in xls.sheet_names:
        df = xls.parse(sn)
        df.columns = [normalize_col(str(c)) for c in df.columns]
        out[sn] = df
    return out

def detect_date_col(df: pd.DataFrame) -> Optional[str]:
    cols = [normalize_col(str(c)) for c in df.columns]
    for c in DATE_COL_CANDIDATES:
        if normalize_col(c) in cols:
            return normalize_col(c)
    for c in df.columns:
        if np.issubdtype(df[c].dtype, np.datetime64):
            return normalize_col(str(c))
    return None

def ensure_year_month(df: pd.DataFrame) -> pd.DataFrame:
    """'일자'가 있으면 연/월을 일자에서 재계산(불일치 자동 교정)."""
    out = df.copy()
    date_col = detect_date_col(out)
    if date_col and date_col in out.columns:
        out[date_col] = pd.to_datetime(out[date_col], errors="coerce")
        out["연"] = out[date_col].dt.year.astype("Int64")
        out["월"] = out[date_col].dt.month.astype("Int64")
    else:
        if "연" in out.columns:
            out["연"] = pd.to_numeric(out["연"], errors="coerce").astype("Int64")
        if "월" in out.columns:
            out["월"] = pd.to_numeric(out["월"], errors="coerce").astype("Int64")
    return out

def sheet_column_order_pairs(raw_df: pd.DataFrame) -> List[Tuple[str, str]]:
    """
    엑셀 '열 등장 순서'를 (구분,세부)로 **컨텍스트 보존**하여 반환.
    - '소계'처럼 그룹이 생략된 헤더는 직전에 인식된 그룹으로 귀속.
    - '합계'는 ('합계','합계').
    """
    order: List[Tuple[str, str]] = []
    seen = set()
    current_group: Optional[str] = None

    skip_keys = {simplify_key(c) for c in ["연", "월"] + DATE_COL_CANDIDATES}

    for raw in raw_df.columns:
        n = normalize_col(str(raw))
        key = simplify_key(n)

        # 날짜/연/월 컬럼 스킵
        if key in skip_keys:
            continue

        parsed = try_parse_explicit(n)

        # 컨텍스트 소계 처리
        if parsed is None:
            if simplify_key(n) == simplify_key("소계") and current_group:
                parsed = (current_group, "소계")
            elif simplify_key(n) == simplify_key("합계"):
                parsed = ("합계", "합계")

        if parsed:
            g, s = parsed
            current_group = g  # 컨텍스트 갱신
            if (g, s) not in seen:
                order.append((g, s))
                seen.add((g, s))

    return order

def to_long(df: pd.DataFrame) -> pd.DataFrame:
    df = ensure_year_month(df)
    if ("연" not in df.columns) or ("월" not in df.columns):
        return pd.DataFrame(columns=["구분","세부","연","월","값"])

    base = df[["연","월"]].copy()
    records = []

    # 열 순서대로 읽어 같은 방식으로 매핑(컨텍스트 사용)
    order_pairs = sheet_column_order_pairs(df)
    # 역매핑: (구분,세부) -> 해당하는 실제 컬럼들
    rev: Dict[Tuple[str,str], List[str]] = {}
    for c in df.columns:
        n = normalize_col(str(c))
        parsed = try_parse_explicit(n)
        if parsed is None:
            if simplify_key(n) == simplify_key("소계"):
                pass
        if parsed:
            rev.setdefault(parsed, []).append(n)

    # order_pairs 기준으로 값 적재(동일 (구분,세부)로 매핑되는 여러 열이 있으면 모두 합산)
    for g, s in order_pairs:
        cols = rev.get((g, s), [])
        if not cols:
            continue
        v_sum = sum([pd.to_numeric(df[c], errors="coerce").fillna(0.0) for c in cols])
        tmp = base.copy()
        tmp["구분"], tmp["세부"], tmp["값"] = g, s, v_sum
        records.append(tmp)

    if not records:
        return pd.DataFrame(columns=["구분","세부","연","월","값"])

    long_df = pd.concat(records, ignore_index=True)
    long_df["연"] = pd.to_numeric(long_df["연"], errors="coerce").astype("Int64")
    long_df["월"] = pd.to_numeric(long_df["월"], errors="coerce").astype("Int64")
    long_df = long_df.dropna(subset=["연","월"])
    return long_df

def reorder_by_sheet_columns(pv: pd.DataFrame, order_pairs: List[Tuple[str, str]]) -> pd.DataFrame:
    """그대로 재배열: 헤더에서 얻은 order_pairs 순서 → 나머지(존재하지만 헤더 매핑 안된 것)."""
    if pv.empty:
        return pv
    final_index: List[Tuple[str, str]] = []
    for pair in order_pairs:
        if pair in pv.index:
            final_index.append(pair)
    for idx in pv.index:
        if idx not in final_index:
            final_index.append(idx)
    return pv.reindex(final_index)

def make_pivot(long_df: pd.DataFrame, year: int, order_pairs: List[Tuple[str, str]]) -> pd.DataFrame:
    view = long_df[long_df["연"] == year].copy()
    if view.empty:
        idx = pd.MultiIndex.from_tuples([], names=["구분","세부"])
        return pd.DataFrame(index=idx, columns=MONTHS).fillna(0.0)

    pv = (
        view.groupby(["구분","세부","월"], as_index=False)["값"]
        .sum()
        .pivot_table(index=["구분","세부"], columns="월", values="값", aggfunc="sum")
        .reindex(columns=MONTHS)
        .fillna(0.0)
    )
    pv.columns.name = ""
    pv = reorder_by_sheet_columns(pv, order_pairs)
    return pv

def style_table(pivot: pd.DataFrame) -> "pd.io.formats.style.Styler":
    p = pivot.copy()
    p.index = p.index.map(lambda t: " / ".join(map(str, t)) if isinstance(t, tuple) else str(t))
    styler = p.style.format({c: "{:,.0f}" for c in p.columns}, na_rep="0")
    def highlight(row):
        name = str(row.name)
        if name.endswith(" / 소계") or name.endswith("합계"):
            return ["background-color: rgba(0,0,0,0.10)"] * len(row)
        return ["" for _ in row]
    return styler.apply(highlight, axis=1)

def show_table(df: pd.DataFrame, key: str):
    try:
        st.dataframe(style_table(df), use_container_width=True, key=f"sty_{key}")
    except Exception:
        s = df.copy()
        for c in s.columns:
            s[c] = pd.to_numeric(s[c], errors="coerce").fillna(0).round(0).astype(int)
            s[c] = s[c].map(lambda x: format(x, ","))
        st.dataframe(s, use_container_width=True, key=f"plain_{key}")

def _apply_predict_flag(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    ps_y, ps_m = PREDICT_START["year"], PREDICT_START["month"]
    df = df.copy()
    df["예측"] = np.where(
        (df["연"] > ps_y) | ((df["연"] == ps_y) & (df["월"] >= ps_m)),
        "예측", "실적"
    )
    return df

# ─────────────────────────────────────────────────────────
# 본문
# ─────────────────────────────────────────────────────────
st.title("공급량 실적 및 계획 상세")

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
st.caption(base_info)

scenario = st.tabs(SCENARIOS)
sheets: Dict[str, pd.DataFrame] = {}
if excel_bytes:
    sheets = read_excel_all_sheets(excel_bytes)

for sn, tab in zip(SCENARIOS, scenario):
    with tab:
        st.subheader(f"시나리오: {sn}")

        cand = [sn, "데이터"] if sn == "데이터" else [sn]
        sheet_name = next((s for s in cand if s in sheets), None)
        if not sheet_name:
            st.info("해당 시나리오 시트를 찾지 못했습니다. (데이터/best/conservative)")
            continue

        raw = sheets[sheet_name]
        order_pairs = sheet_column_order_pairs(raw)     # 엑셀 헤더 순서(컨텍스트 포함)
        long_df = to_long(raw)

        # 연도별 표
        ytabs = st.tabs([f"{y}년 표" for y in YEARS])
        for y, t in zip(YEARS, ytabs):
            with t:
                st.markdown(f"**{y}년 표**")
                pv = make_pivot(long_df, y, order_pairs)
                show_table(pv, key=f"{sn}_{y}")

        st.markdown("---")
        st.subheader("월별 추이 그래프")

        sel_years = st.multiselect("연도 선택(그래프)", YEARS, default=YEARS, key=f"yrs_{sn}")
        group_options = ["총량","가정용","영업용","업무용","산업용","열병합","연료전지","자가열전용","열전용설비용","CNG","수송용"]
        sel_group = st.segmented_control("그룹", group_options, selection_mode="single",
                                         default="총량", key=f"grp_{sn}")

        plot_base = long_df[long_df["연"].isin(sel_years)].copy()
        plot_base = plot_base[plot_base["구분"] != "합계"]

        # ── 상단: 그룹별 총량 추이
        if sel_group == "총량":
            plot_df = (
                plot_base.groupby(["연","월"], as_index=False)["값"].sum()
                .sort_values(["연","월"])
            )
            plot_df["라벨"] = plot_df["연"].astype(str) + "년 · 총량"
        else:
            plot_df = (
                plot_base[plot_base["구분"] == sel_group]
                .groupby(["연","구분","월"], as_index=False)["값"].sum()
                .sort_values(["연","구분","월"])
            )
            plot_df["라벨"] = plot_df["연"].astype(str) + "년 · " + plot_df["구분"].astype(str)

        if not plot_df.empty:
            plot_df = _apply_predict_flag(plot_df)

        if plot_df.empty:
            st.info("선택 조건에 해당하는 데이터가 없습니다.")
        else:
            fig = px.line(
                plot_df,
                x="월", y="값",
                color="라벨",
                line_dash="예측",
                category_orders={"예측": ["실적","예측"]},
                line_dash_map={"실적": "solid", "예측": "dash"},
                markers=True,
            )
            fig.update_layout(
                xaxis=dict(dtick=1),
                yaxis_title="공급량",
                legend_title="연도/그룹",
                margin=dict(l=10, r=10, t=10, b=10),
            )
            st.plotly_chart(fig, use_container_width=True)

        # ──────────────────────────────────────────────
        # 하단: 선택 그룹의 세부 구성 그래프(가정용=취/개/중 3개 동시)
        # ──────────────────────────────────────────────
        st.markdown("#### 선택 그룹의 세부 구성 그래프")
        if sel_group == "총량":
            st.info("세부 그래프는 특정 그룹을 선택하면 표시돼. 예: ‘가정용’을 선택하면 취사용·개별난방·중앙난방 구성 라인이 보여.")
        else:
            include_total = st.checkbox("소계/합계도 함께 표시", value=False, key=f"inc_total_{sn}")
            detail_base = long_df[(long_df["연"].isin(sel_years)) & (long_df["구분"] == sel_group)].copy()
            if not include_total:
                # 소계/합계 제외
                detail_base = detail_base[~detail_base["세부"].isin(["소계","합계"])]

            if detail_base.empty:
                st.info("해당 그룹의 세부 항목이 없습니다.")
            else:
                detail_df = (
                    detail_base.groupby(["연","세부","월"], as_index=False)["값"]
                    .sum()
                    .sort_values(["연","세부","월"])
                )
                detail_df["라벨"] = detail_df["연"].astype(str) + "년 · " + detail_df["세부"].astype(str)
                detail_df = _apply_predict_flag(detail_df)

                fig2 = px.line(
                    detail_df,
                    x="월", y="값",
                    color="라벨",
                    line_dash="예측",
                    category_orders={"예측": ["실적","예측"]},
                    line_dash_map={"실적": "solid", "예측": "dash"},
                    markers=True,
                )
                fig2.update_layout(
                    xaxis=dict(dtick=1),
                    yaxis_title="공급량",
                    legend_title="연도/세부",
                    margin=dict(l=10, r=10, t=10, b=10),
                )
                st.plotly_chart(fig2, use_container_width=True)
