# app.py
# 공급량 실적 및 계획 상세 — 시나리오/연도별 표 + 동적 그래프
# 변경 요약
#  • 표 행 순서: 엑셀 헤더 '왼→오' 등장 순서 그대로(그룹/세부)
#  • 소계/합계가 시트에 없으면 생성하지 않음(자동 소계/합계 제거)
#  • '그룹_세부' / '그룹/세부' / '그룹 세부' / '그룹-세부' / '그룹.세부' / '그룹세부' 모두 인식
#  • 그래프: 선택 그룹만 표시, 2025-11 이후(및 연>2025)는 예측(점선)

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
# 환경/상수
# ─────────────────────────────────────────────────────────
DEFAULT_XLSX = "사업계획최종.xlsx"
DATE_COL_CANDIDATES = ["일자", "날짜", "date", "Date", "일", "기준일"]
PREDICT_START = {"year": 2025, "month": 11}  # 이 시점부터 '예측'으로 표기

# 인지 가능한 그룹명(파싱에 사용)
GROUP_NAMES = [
    "가정용", "영업용", "업무용", "산업용",
    "열병합", "연료전지", "자가열전용", "열전용설비용",
    "CNG", "수송용", "합계"
]

# 열 이름 → (구분, 세부) : 정확 일치 매핑(최우선 적용)
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
    "소계": ("업무용", "소계"),   # 시트에 '소계' 단독 컬럼 대응
    "산업용": ("산업용", "합계"),
    # 기타
    "열병합": ("열병합", "합계"),
    "연료전지": ("연료전지", "합계"),
    "자가열전용": ("자가열전용", "합계"),
    "자가열병합": ("자가열전용", "합계"),
    "열전용설비용": ("열전용설비용", "합계"),
    "CNG": ("CNG", "합계"),
    # 수송용
    "BIO": ("수송용", "BIO"),
    "수송용소계": ("수송용", "소계"),
    "수송용 소계": ("수송용", "소계"),
    # 최종 합계
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
    """키 비교용 간소화(공백/구분자 제거, 소문자)."""
    s = normalize_col(s)
    return re.sub(r"[ \t/,_\-.]+", "", s).lower()

def parse_column_name(raw_name: str) -> Optional[Tuple[str, str]]:
    """
    엑셀 헤더를 (구분, 세부)로 파싱.
    1) COL_TO_GROUP 간소키 일치 → 매핑
    2) '그룹{구분자}세부' 자동 파싱(공백/슬래시/언더스코어/하이픈/점)
    3) '그룹세부' 붙은 형태: 그룹명으로 시작하면 분리
    """
    n = normalize_col(raw_name)
    key = simplify_key(n)

    # 1) 명시 매핑
    for k, (g, s) in COL_TO_GROUP.items():
        if simplify_key(k) == key:
            return (g, s)

    # 2) 패턴 파싱
    parts = re.split(r"[ \t/,_\-.]+", n)
    if len(parts) >= 2:
        g_cand = parts[0]
        s_cand = " ".join(parts[1:])
        if g_cand in GROUP_NAMES:
            return (g_cand, s_cand)

    # 3) 붙은 형태
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
    """'일자'가 있으면 연/월을 항상 일자에서 재계산하여 덮어씀(불일치 자동 교정)."""
    out = df.copy()
    mismatch_cnt = 0
    date_col = detect_date_col(out)

    if date_col and date_col in out.columns:
        out[date_col] = pd.to_datetime(out[date_col], errors="coerce")
        y = out[date_col].dt.year.astype("Int64")
        m = out[date_col].dt.month.astype("Int64")
        if "연" in out.columns:
            mismatch_cnt += int(((pd.to_numeric(out["연"], errors="coerce").astype("Int64") != y) & y.notna()).sum())
        if "월" in out.columns:
            mismatch_cnt += int(((pd.to_numeric(out["월"], errors="coerce").astype("Int64") != m) & m.notna()).sum())
        out["연"], out["월"] = y, m
    else:
        if "연" in out.columns:
            out["연"] = pd.to_numeric(out["연"], errors="coerce").astype("Int64")
        if "월" in out.columns:
            out["월"] = pd.to_numeric(out["월"], errors="coerce").astype("Int64")

    out.attrs["year_month_mismatch_fixed"] = mismatch_cnt
    return out

def sheet_column_order_pairs(raw_df: pd.DataFrame) -> List[Tuple[str, str]]:
    """엑셀 '열 등장 순서'를 (구분,세부) 쌍으로 그대로 보존."""
    order: List[Tuple[str, str]] = []
    seen = set()
    for c in raw_df.columns:
        p = parse_column_name(c)
        if p and p not in seen:
            order.append(p)  # 헤더 순서 그대로
            seen.add(p)
    return order

def to_long(df: pd.DataFrame) -> pd.DataFrame:
    df = ensure_year_month(df)
    if ("연" not in df.columns) or ("월" not in df.columns):
        return pd.DataFrame(columns=["구분","세부","연","월","값"])

    key_map: Dict[str, Tuple[str, str]] = {}
    for raw_col in df.columns:
        parsed = parse_column_name(str(raw_col))
        if parsed:
            key_map[raw_col] = parsed

    if not key_map:
        return pd.DataFrame(columns=["구분","세부","연","월","값"])

    base = df[["연","월"]].copy()
    records = []
    for raw_col, (gg, ss) in key_map.items():
        v = pd.to_numeric(df[raw_col], errors="coerce").fillna(0.0)
        tmp = base.copy()
        tmp["구분"], tmp["세부"], tmp["값"] = gg, ss, v
        records.append(tmp)

    long_df = pd.concat(records, ignore_index=True)
    long_df["연"] = pd.to_numeric(long_df["연"], errors="coerce").astype("Int64")
    long_df["월"] = pd.to_numeric(long_df["월"], errors="coerce").astype("Int64")
    long_df = long_df.dropna(subset=["연","월"])
    long_df.attrs["year_month_mismatch_fixed"] = df.attrs.get("year_month_mismatch_fixed", 0)
    return long_df

def reorder_by_sheet_columns(pv: pd.DataFrame, order_pairs: List[Tuple[str, str]]) -> pd.DataFrame:
    """
    절대 기준 = 엑셀 헤더 순서.
    1) order_pairs 순서대로(존재하는 행만) 배치
    2) order_pairs에 없지만 pivot에 존재하는 행은 뒤에 덧붙임
    (소계/합계 자동 생성하지 않음)
    """
    if pv.empty:
        return pv

    final_index: List[Tuple[str, str]] = []

    # ① 헤더 순서대로
    for pair in order_pairs:
        if pair in pv.index and pair not in final_index:
            final_index.append(pair)

    # ② 누락 보완(피벗에는 있는데 헤더 파싱에서 누락된 케이스)
    for idx in pv.index:
        if idx not in final_index:
            final_index.append(idx)

    return pv.reindex(final_index)

def make_pivot(long_df: pd.DataFrame, year: int, order_pairs: List[Tuple[str, str]]) -> pd.DataFrame:
    view = long_df[long_df["연"] == year].copy()
    if view.empty:
        idx = pd.MultiIndex.from_tuples([], names=["구분","세부"])
        pivot = pd.DataFrame(index=idx, columns=MONTHS).fillna(0.0)
        pivot["합계"] = 0.0
        return pivot

    pv = (
        view.groupby(["구분","세부","월"], as_index=False)["값"]
        .sum()
        .pivot_table(index=["구분","세부"], columns="월", values="값", aggfunc="sum")
        .reindex(columns=MONTHS)
        .fillna(0.0)
    )
    pv.columns.name = ""
    # 표 '행 합계'는 요구 없으므로 생성하지 않음. 필요하면 아래 주석 해제.
    # pv["합계"] = pv.sum(axis=1)

    # 자동 소계/합계 생성 제거 → 단순 정렬만 수행
    pv = reorder_by_sheet_columns(pv, order_pairs)
    return pv

def style_table(pivot: pd.DataFrame) -> "pd.io.formats.style.Styler":
    p = pivot.copy()
    p.index = p.index.map(lambda t: " / ".join(map(str, t)) if isinstance(t, tuple) else str(t))
    styler = p.style.format({c: "{:,.0f}" for c in p.columns}, na_rep="0")

    # 시트에 존재하는 소계/합계만 하이라이트
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

# ─────────────────────────────────────────────────────────
# 본문
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
st.caption(base_info)

# 시나리오 탭 & 엑셀 로드
scenario = st.tabs(SCENARIOS)
sheets: Dict[str, pd.DataFrame] = {}
if excel_bytes:
    sheets = read_excel_all_sheets(excel_bytes)

# 시나리오별 화면
for sn, tab in zip(SCENARIOS, scenario):
    with tab:
        st.subheader(f"시나리오: {sn}")

        cand = [sn, "데이터"] if sn == "데이터" else [sn]
        sheet_name = next((s for s in cand if s in sheets), None)
        if not sheet_name:
            st.info("해당 시나리오 시트를 찾지 못했습니다. (데이터/best/conservative)")
            continue

        raw = sheets[sheet_name]
        order_pairs = sheet_column_order_pairs(raw)  # 엑셀 헤더 순서 반영
        long_df = to_long(raw)

        fixed = int(long_df.attrs.get("year_month_mismatch_fixed", 0))
        if fixed > 0:
            st.caption(f"'일자' 기준으로 연/월 불일치 {fixed}건을 자동 교정함.")

        # 연도별 표
        ytabs = st.tabs([f"{y}년 표" for y in YEARS])
        for y, t in zip(YEARS, ytabs):
            with t:
                st.markdown(f"**{y}년 표**")
                pv = make_pivot(long_df, y, order_pairs)
                show_table(pv, key=f"{sn}_{y}")

        st.markdown("---")
        st.subheader("월별 추이 그래프")

        # 연도·그룹 선택
        sel_years = st.multiselect("연도 선택(그래프)", YEARS, default=YEARS, key=f"yrs_{sn}")
        group_options = ["총량","가정용","영업용","업무용","산업용","열병합","연료전지","자가열전용","열전용설비용","CNG","수송용"]
        sel_group = st.segmented_control("그룹", group_options, selection_mode="single",
                                         default="총량", key=f"grp_{sn}")

        # 선택 연도 + '합계' 구분 제외(이중집계 방지)
        plot_base = long_df[long_df["연"].isin(sel_years)].copy()
        plot_base = plot_base[plot_base["구분"] != "합계"]

        # 선택한 그룹만 표시
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

        # 예측/실적 라벨링
        if not plot_df.empty:
            ps_y, ps_m = PREDICT_START["year"], PREDICT_START["month"]
            plot_df["예측"] = np.where(
                (plot_df["연"] > ps_y) | ((plot_df["연"] == ps_y) & (plot_df["월"] >= ps_m)),
                "예측", "실적"
            )

        if plot_df.empty:
            st.info("선택 조건에 해당하는 데이터가 없습니다.")
        else:
            fig = px.line(
                plot_df,
                x="월",
                y="값",
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
