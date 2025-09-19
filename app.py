# app.py — 공급량 실적 및 계획 상세
# - 엑셀(.xlsx) 업로드 → 연/월·용도 열 자동/수동 매핑
# - 표(구분/세부 × 1~12월 + 합계) 자동 채움, 소계/전체합계 계산
# - 소계 연한 하이라이트, 상단 [전체 | 용도별] 버튼, 하단 월별 그래프
# - CSV 다운로드

import io
import re
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib as mpl
import matplotlib.pyplot as plt
import streamlit as st

# ───────────────── 기본 설정 ─────────────────
def set_korean_font():
    try:
        mpl.rcParams["font.family"] = "NanumGothic"
        mpl.rcParams["axes.unicode_minus"] = False
    except Exception:
        pass

set_korean_font()
st.set_page_config(page_title="공급량 실적 및 계획 상세", layout="wide")
st.title("📊 공급량 실적 및 계획 상세")

# 표 스켈레톤(요구 레이아웃 고정)
ROWS_SPEC = [
    ("가정용", "취사용"),
    ("가정용", "개별난방"),
    ("가정용", "중앙난방"),
    ("가정용", "소계"),

    ("영업용", "일반용1"),

    ("업무용", "일반용2"),
    ("업무용", "냉난방용"),
    ("업무용", "주택미급"),
    ("업무용", "소계"),

    ("산업용", "합계"),
    ("열병합", "합계"),
    ("연료전지", "합계"),
    ("자가열병합", "합계"),
    ("열전용설비용", "합계"),

    ("CNG", "합계"),

    ("수송용", "BIO"),
    ("수송용", "소계"),

    ("합계", ""),  # 최종 합계
]
MONTH_COLS = [f"{m}월" for m in range(1, 13)]
ALL_COLS = ["구분", "세부"] + MONTH_COLS + ["합계"]

def blank_table() -> pd.DataFrame:
    df = pd.DataFrame(ROWS_SPEC, columns=["구분", "세부"])
    for c in MONTH_COLS:
        df[c] = np.nan
    df["합계"] = np.nan
    return df

# ───────────────── 사이드바: 업로드 & 매핑 ─────────────────
sb = st.sidebar
sb.header("데이터 불러오기")
up = sb.file_uploader("엑셀 업로드(.xlsx)", type=["xlsx"])
if not up:
    st.info("좌측에서 엑셀 파일을 업로드해 주세요. (연/월/용도 열 포함)")
    st.stop()

import openpyxl  # engine ensure
xls = pd.ExcelFile(io.BytesIO(up.getvalue()), engine="openpyxl")
sheet = sb.selectbox("시트 선택", options=xls.sheet_names,
                     index=(xls.sheet_names.index("데이터") if "데이터" in xls.sheet_names else 0))
raw0 = xls.parse(sheet, header=0)

# ── 자동 추정 헬퍼
def _lc_list(cols):
    return [str(c).strip().lower() for c in cols]

def guess_year_col(cols):
    for c in cols:
        lc = str(c).lower()
        if any(w in lc for w in ["연도", "년도", "year", "yr"]):
            return c
    return None

def guess_month_col(cols):
    for c in cols:
        lc = str(c).lower()
        if lc == "월" or "month" in lc or lc in ["mm", "mon"]:
            return c
    for c in cols:
        if "월" in str(c):
            return c
    return None

# 동의어 사전(자동 매핑 강화)
SYN = {
    "취사용": ["취사용", "취사", "주택취사"],
    "개별난방": ["개별난방", "개난", "개별 난방"],
    "중앙난방": ["중앙난방", "중난", "중앙 난방"],
    "일반용1": ["일반용1", "일반1", "영업용일반1", "영업용1"],
    "일반용2": ["일반용2", "일반2", "업무용일반2", "업무용2"],
    "냉난방용": ["냉난방용", "냉난", "냉/난방"],
    "주택미급": ["주택미급", "주택 미급", "주택미급수"],
    "산업용": ["산업용", "산업"],
    "열병합": ["열병합", "열 병합", "chp"],
    "연료전지": ["연료전지", "연료 전지", "fc"],
    "자가열병합": ["자가열병합", "자가 열병합", "자가chp"],
    "열전용설비용": ["열전용설비용", "열전용", "열전용 설비"],
    "CNG": ["cng", "씨엔지"],
    "BIO": ["bio", "바이오", "바이오가스"],
}

def auto_pick(colnames, names):
    lc = _lc_list(colnames)
    for nm in names:
        for cand in SYN[nm]:
            c = cand.lower()
            if c in lc:
                return colnames[lc.index(c)]
    return None

# 자동 추정
year_col_guess = guess_year_col(raw0.columns)
month_col_guess = guess_month_col(raw0.columns)

DEFAULT_MAP = {}
for key in SYN.keys():
    DEFAULT_MAP[key] = auto_pick(raw0.columns.tolist(), [key])

# 매핑 UI
sb.markdown("### 컬럼 매핑")
year_col = sb.selectbox("연도 컬럼", [None] + raw0.columns.tolist(),
                        index=(raw0.columns.tolist().index(year_col_guess) + 1) if year_col_guess in raw0.columns else 0)
month_col = sb.selectbox("월 컬럼(또는 날짜 컬럼에서 자동 추출)", [None] + raw0.columns.tolist(),
                         index=(raw0.columns.tolist().index(month_col_guess) + 1) if month_col_guess in raw0.columns else 0)

# 날짜 컬럼(선택 시 연/월 자동 추출)
date_candidates = [c for c in raw0.columns if any(k in str(c).lower() for k in ["date", "일자", "날짜", "기준일"])]
date_col = sb.selectbox("날짜 컬럼(옵션: 연/월 자동 추출)", [None] + date_candidates, index=0) if date_candidates else None

mapping = {}
for key in ["취사용","개별난방","중앙난방","일반용1","일반용2","냉난방용","주택미급",
            "산업용","열병합","연료전지","자가열병합","열전용설비용","CNG","BIO"]:
    default = DEFAULT_MAP.get(key)
    idx = (raw0.columns.tolist().index(default) + 1) if default in raw0.columns else 0
    mapping[key] = sb.selectbox(f"엑셀 열 ↔ {key}", [None] + raw0.columns.tolist(), index=idx, key=f"map_{key}")

# ───────────────── 연/월 생성 ─────────────────
df = raw0.copy()
if date_col:
    tmp = pd.to_datetime(df[date_col], errors="coerce")
    if year_col is None:
        df["__연도__"] = tmp.dt.year
        year_col = "__연도__"
    if month_col is None:
        df["__월__"] = tmp.dt.month
        month_col = "__월__"

if year_col is None or month_col is None:
    st.error("연도/월 컬럼을 지정하거나 날짜 컬럼을 선택해 주세요.")
    st.stop()

df["_연도_"] = pd.to_numeric(df[year_col], errors="coerce").astype("Int64")
df["_월_"] = pd.to_numeric(df[month_col], errors="coerce").astype("Int64")

years = sorted(df["_연도_"].dropna().unique().tolist())
sel_year = sb.selectbox("연도 선택", options=years,
                        index=(years.index(2024) if 2024 in years else 0))

# ───────────────── 업로드 → 월별 표 채우기 ─────────────────
base = blank_table()
targets = {k: v for k, v in mapping.items() if v is not None}

def monthly_sum(col_name: str) -> pd.Series:
    sub = df.query("_연도_ == @sel_year")[["_월_", col_name]].copy()
    sub[col_name] = pd.to_numeric(sub[col_name], errors="coerce")
    s = sub.groupby("_월_")[col_name].sum(min_count=1)
    out = pd.Series(index=range(1, 13), dtype="float64")
    out.update(s)
    return out

# 개별행 채우기
for g, d in ROWS_SPEC:
    if d in targets:  # 예: ('영업용','일반용1')에서 d='일반용1'
        vals = monthly_sum(targets[d])
        for m in range(1, 13):
            base.loc[(base["구분"] == g) & (base["세부"] == d), f"{m}월"] = float(vals[m]) if pd.notna(vals[m]) else np.nan

# 소계/합계 계산
def calc_subtotals(table: pd.DataFrame) -> pd.DataFrame:
    t = table.copy()
    # 가정용 소계 = 취사용 + 개별난방 + 중앙난방
    m = (t["구분"] == "가정용") & (t["세부"] == "소계")
    for c in MONTH_COLS:
        t.loc[m, c] = t.loc[(t["구분"]=="가정용") & (t["세부"].isin(["취사용","개별난방","중앙난방"])), c].sum()
    # 업무용 소계 = 일반용2 + 냉난방용 + 주택미급
    m = (t["구분"] == "업무용") & (t["세부"] == "소계")
    for c in MONTH_COLS:
        t.loc[m, c] = t.loc[(t["구분"]=="업무용") & (t["세부"].isin(["일반용2","냉난방용","주택미급"])), c].sum()
    # 수송용 소계 = BIO
    m = (t["구분"] == "수송용") & (t["세부"] == "소계")
    for c in MONTH_COLS:
        t.loc[m, c] = t.loc[(t["구분"]=="수송용") & (t["세부"]=="BIO"), c].sum()
    # 전체 합계(소계/합계 제외)
    body = (t["구분"] != "합계") & t["세부"].ne("소계") & t["세부"].ne("합계")
    m = (t["구분"] == "합계")
    for c in MONTH_COLS:
        t.loc[m, c] = t.loc[body, c].sum()
    # 행 합계
    t["합계"] = t[MONTH_COLS].sum(axis=1, min_count=1)
    return t

filled = calc_subtotals(base)

# ───────────────── 표 표시(소계 하이라이트) ─────────────────
def styled_dataframe(sdf: pd.DataFrame):
    sty = sdf.style
    sty = sty.set_table_styles([
        {"selector": "th.col_heading", "props": "background:#f6f6f6;"},
        {"selector": "thead th", "props": "text-align:center;"},
        {"selector": "tbody td", "props": "text-align:right;"},
    ])
    sty = sty.set_properties(subset=["구분","세부"], **{"text-align":"left"})
    # 소계(연한 블루), 최종합계(연한 살구)
    mask_sub = sdf["세부"].eq("소계")
    sty = sty.apply(lambda r: ["background-color:#f2f7ff" if m else "" for m in mask_sub], axis=1)
    mask_tot = sdf["구분"].eq("합계")
    sty = sty.apply(lambda r: ["background-color:#fff3e6" if m else "" for m in mask_tot], axis=1)
    sty = sty.format({c: "{:,.0f}".format for c in MONTH_COLS + ["합계"]})
    return sty

st.subheader(f"{sel_year}년 표")
st.dataframe(styled_dataframe(filled[ALL_COLS]), use_container_width=True)

# ───────────────── 버튼(전체/용도별) + 그래프 ─────────────────
st.subheader("월별 추이 그래프")
usage_list = [u for u in filled["구분"].dropna().unique().tolist() if u and u != "합계"]
selected = st.segmented_control("보기 선택", options=["전체"] + usage_list, default="전체")

def monthly_series(selection: str):
    if selection == "전체":
        mask = filled["구분"].ne("합계") & filled["세부"].ne("소계") & filled["세부"].ne("합계")
    else:
        mask = (filled["구분"] == selection) & filled["세부"].ne("소계") & filled["세부"].ne("합계")
    s = filled.loc[mask, MONTH_COLS].sum(numeric_only=True)
    xs = list(range(1, 13))
    ys = [float(s.get(f"{m}월", 0.0)) for m in xs]
    return xs, ys

xs, ys = monthly_series(selected)
fig, ax = plt.subplots(figsize=(10, 4))
ax.plot(xs, ys, marker="o")
ax.set_xticks(xs)
ax.set_xlabel("월")
ax.set_ylabel("공급량(㎥)")
ax.set_title(f"{sel_year}년 {selected} 월별 합계 추이")
ax.grid(True, alpha=0.3)
st.pyplot(fig, use_container_width=True)

# ───────────────── 다운로드 ─────────────────
st.subheader("다운로드")
c1, c2 = st.columns(2)
with c1:
    st.download_button(
        "현재 표 CSV 다운로드",
        data=filled[ALL_COLS].to_csv(index=False).encode("utf-8-sig"),
        file_name=f"supply_table_{sel_year}.csv",
        mime="text/csv",
    )
with c2:
    ts = pd.DataFrame({"월": xs, "공급량(㎥)": ys})
    st.download_button(
        "현재 그래프 데이터 CSV 다운로드",
        data=ts.to_csv(index=False).encode("utf-8-sig"),
        file_name=f"supply_timeseries_{sel_year}_{selected}.csv",
        mime="text/csv",
    )
