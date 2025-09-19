# app.py — 공급량 실적 및 계획 상세 (엑셀 업로드 → 표 자동 채움 + 용도별 그래프)
# - 엑셀(.xlsx) 업로드 후 시트/연도 선택
# - 열 자동매핑(연/월/각 용도) + 수동 수정 UI
# - 표(구분/세부 × 1~12월 + 합계) 자동 채움: 소계/전체합계 계산, 소계 연한 하이라이트
# - 상단 버튼(전체·용도별) → 하단 월별 추이 그래프

import io
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib as mpl
import matplotlib.pyplot as plt
import streamlit as st

# ─────────────────────────────────────────────────────────
# 스타일/폰트
# ─────────────────────────────────────────────────────────
def set_korean_font():
    try:
        mpl.rcParams["font.family"] = "NanumGothic"
        mpl.rcParams["axes.unicode_minus"] = False
    except Exception:
        pass
set_korean_font()

st.set_page_config(page_title="공급량 실적 및 계획 상세", layout="wide")
st.title("📊 공급량 실적 및 계획 상세")

# ─────────────────────────────────────────────────────────
# 표 스켈레톤(두 번째 스크린샷 레이아웃)
# ─────────────────────────────────────────────────────────
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

    ("합계", ""),  # 맨 아래 전체 합계
]
MONTH_COLS = [f"{m}월" for m in range(1, 13)]
ALL_COLS = ["구분", "세부"] + MONTH_COLS + ["합계"]

def blank_table() -> pd.DataFrame:
    df = pd.DataFrame(ROWS_SPEC, columns=["구분", "세부"])
    for c in MONTH_COLS:
        df[c] = np.nan
    df["합계"] = np.nan
    return df

# ─────────────────────────────────────────────────────────
# 사이드바: 업로드 + 시트/연도 + 컬럼 매핑
# ─────────────────────────────────────────────────────────
sb = st.sidebar
sb.header("데이터 불러오기")

up = sb.file_uploader("엑셀 업로드(.xlsx)", type=["xlsx"])
if not up:
    st.info("좌측에서 엑셀 파일을 업로드해 주세요. (예: 데이터 시트에 연/월/용도 열이 있는 형식)")
    st.stop()

# 엑셀 로드
import openpyxl  # engine 보장
xls = pd.ExcelFile(io.BytesIO(up.getvalue()), engine="openpyxl")
sheet = sb.selectbox("시트 선택", options=xls.sheet_names, index=(xls.sheet_names.index("데이터") if "데이터" in xls.sheet_names else 0))

# 우선 1행 헤더 가정으로 읽기
raw0 = xls.parse(sheet, header=0)

# 연/월 후보 자동 인식
def guess_year_col(cols):
    for c in cols:
        lc = str(c).lower()
        if ("연도" in str(c)) or ("year" in lc):
            return c
    # 날짜 열에서 연도 추출할 수 있도록 date/일자 같은 이름도 후보
    for c in cols:
        lc = str(c).lower()
        if any(k in lc for k in ["date", "일자", "날짜", "기준일"]):
            return c
    return None

def guess_month_col(cols):
    for c in cols:
        if str(c).strip() == "월":
            return c
        lc = str(c).lower()
        if "month" in lc:
            return c
    return None

year_col_guess = guess_year_col(raw0.columns)
month_col_guess = guess_month_col(raw0.columns)

# 카테고리 매핑 기본값(엑셀 열명이 동일할 때 자동 인식)
# {표의 세부항목 → 엑셀의 컬럼명}
DEFAULT_MAP = {
    "취사용": "취사용",
    "개별난방": "개별난방",
    "중앙난방": "중앙난방",
    "일반용1": "일반용1",
    "일반용2": "일반용2",
    "냉난방용": "냉난방용",
    "주택미급": "주택미급",
    "산업용": "산업용",
    "열병합": "열병합",
    "연료전지": "연료전지",
    "자가열병합": "자가열병합",
    "열전용설비용": "열전용설비용",
    "CNG": "CNG",
    "BIO": "BIO",
}

sb.markdown("### 컬럼 매핑")
year_col = sb.selectbox("연도 컬럼", [None] + raw0.columns.tolist(),
                        index=(raw0.columns.tolist().index(year_col_guess) + 1) if year_col_guess in raw0.columns else 0)
month_col = sb.selectbox("월 컬럼(또는 날짜 컬럼에서 자동 추출)", [None] + raw0.columns.tolist(),
                         index=(raw0.columns.tolist().index(month_col_guess) + 1) if month_col_guess in raw0.columns else 0)

# 날짜 컬럼에서 연/월 추출(선택 시)
date_col = None
if year_col is None or month_col is None:
    # 날짜 성격 컬럼이 있으면 선택 가능하게
    date_candidates = [c for c in raw0.columns if any(k in str(c).lower() for k in ["date", "일자", "날짜", "기준일"])]
    if date_candidates:
        date_col = sb.selectbox("날짜 컬럼(연/월 자동추출)", [None] + date_candidates, index=1)
    else:
        date_col = None

# 세부항목별 매핑 UI
mapping = {}
for key in ["취사용","개별난방","중앙난방","일반용1","일반용2","냉난방용","주택미급",
            "산업용","열병합","연료전지","자가열병합","열전용설비용","CNG","BIO"]:
    default = DEFAULT_MAP.get(key)
    idx = (raw0.columns.tolist().index(default) + 1) if default in raw0.columns else 0
    mapping[key] = sb.selectbox(f"엑셀 열 ↔ {key}", [None] + raw0.columns.tolist(), index=idx, key=f"map_{key}")

# 연/월 열 생성
df = raw0.copy()
if date_col:
    # 날짜에서 연/월 뽑기
    tmp = pd.to_datetime(df[date_col], errors="coerce")
    if year_col is None:
        df["__연도__"] = tmp.dt.year
        year_col = "__연도__"
    if month_col is None:
        df["__월__"] = tmp.dt.month
        month_col = "__월__"

if year_col is None or month_col is None:
    st.error("연도/월 컬럼을 지정하거나, 날짜 컬럼을 지정해야 합니다.")
    st.stop()

df["_연도_"] = pd.to_numeric(df[year_col], errors="coerce").astype("Int64")
df["_월_"] = pd.to_numeric(df[month_col], errors="coerce").astype("Int64")

# 연도 선택
years = sorted(df["_연도_"].dropna().unique().tolist())
if not years:
    st.error("연도 값이 비어 있습니다. 매핑을 확인하세요.")
    st.stop()
sel_year = sb.selectbox("연도 선택", options=years, index=max(0, years.index(2024)) if 2024 in years else 0)

# ─────────────────────────────────────────────────────────
# 업로드 데이터 → 표(월별)로 채우기
# ─────────────────────────────────────────────────────────
base_table = blank_table()

# Excel에서 가져올 대상 세부항목 집합(실제 매핑된 것만)
targets = {k: v for k, v in mapping.items() if v is not None}

# 월별 합계 계산 함수
def monthly_sum(col_name: str) -> pd.Series:
    sub = df.query("_연도_ == @sel_year")[["_월_", col_name]].copy()
    sub[col_name] = pd.to_numeric(sub[col_name], errors="coerce")
    s = sub.groupby("_월_")[col_name].sum(min_count=1)
    # 1~12 보정
    out = pd.Series(index=range(1,13), dtype="float64")
    out.update(s)
    return out

# 1) 개별행 채우기
for (g, d) in ROWS_SPEC:
    if d in targets:  # 예: ('영업용','일반용1') → mapping['일반용1']
        vals = monthly_sum(targets[d])
        for m in range(1, 13):
            base_table.loc[(base_table["구분"] == g) & (base_table["세부"] == d), f"{m}월"] = float(vals[m]) if pd.notna(vals[m]) else np.nan

# 2) 소계/합계 계산
def calc_subtotals(table: pd.DataFrame) -> pd.DataFrame:
    t = table.copy()
    # 가정용 소계 = 취사용 + 개별난방 + 중앙난방
    mask = (t["구분"] == "가정용") & (t["세부"] == "소계")
    for m in MONTH_COLS:
        t.loc[mask, m] = t.loc[(t["구분"]=="가정용") & (t["세부"].isin(["취사용","개별난방","중앙난방"])), m].sum()
    # 업무용 소계 = 일반용2 + 냉난방용 + 주택미급
    mask = (t["구분"] == "업무용") & (t["세부"] == "소계")
    for m in MONTH_COLS:
        t.loc[mask, m] = t.loc[(t["구분"]=="업무용") & (t["세부"].isin(["일반용2","냉난방용","주택미급"])), m].sum()
    # 수송용 소계 = BIO (요구안 기준 CNG는 별도 카테고리)
    mask = (t["구분"] == "수송용") & (t["세부"] == "소계")
    for m in MONTH_COLS:
        t.loc[mask, m] = t.loc[(t["구분"]=="수송용") & (t["세부"].isin(["BIO"])), m].sum()
    # 전체 합계(맨 아래 '합계' 행) = 소계/합계를 제외한 전 행의 월별 합
    mask_total = (t["구분"] == "합계")
    body_mask = (t["구분"] != "합계") & (t["세부"].ne("소계")) & (t["세부"].ne("합계"))
    for m in MONTH_COLS:
        t.loc[mask_total, m] = t.loc[body_mask, m].sum()
    # 각 행 합계 열
    t["합계"] = t[MONTH_COLS].sum(axis=1, min_count=1)
    return t

filled = calc_subtotals(base_table)

# ─────────────────────────────────────────────────────────
# 표 표시(소계 연한 하이라이트)
# ─────────────────────────────────────────────────────────
def styled_dataframe(sdf: pd.DataFrame):
    sty = sdf.style
    sty = sty.set_table_styles([
        {"selector": "th.col_heading", "props": "background:#f6f6f6;"},
        {"selector": "thead th", "props": "text-align:center;"},
        {"selector": "tbody td", "props": "text-align:right;"},
    ])
    sty = sty.set_properties(subset=["구분","세부"], **{"text-align":"left"})
    # 소계 연하게(#f2f7ff), 전체 합계(#fff3e6)
    mask_sub = sdf["세부"].eq("소계")
    sty = sty.apply(lambda r: ["background-color:#f2f7ff" if m else "" for m in mask_sub], axis=1)
    mask_tot = sdf["구분"].eq("합계")
    sty = sty.apply(lambda r: ["background-color:#fff3e6" if m else "" for m in mask_tot], axis=1)
    # 숫자 포맷
    sty = sty.format({c: "{:,.0f}".format for c in MONTH_COLS + ["합계"]})
    return sty

st.subheader(f"{sel_year}년 표")
st.dataframe(styled_dataframe(filled[ALL_COLS]), use_container_width=True)

# ─────────────────────────────────────────────────────────
# 버튼(전체/용도별) + 월별 그래프
# ─────────────────────────────────────────────────────────
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

fig, ax = plt.subplots(figsize=(10,4))
ax.plot(xs, ys, marker="o")
ax.set_xticks(xs)
ax.set_xlabel("월")
ax.set_ylabel("공급량(㎥)")
ax.set_title(f"{sel_year}년 {selected} 월별 합계 추이")
ax.grid(True, alpha=0.3)
st.pyplot(fig, use_container_width=True)

# ─────────────────────────────────────────────────────────
# 다운로드
# ─────────────────────────────────────────────────────────
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
