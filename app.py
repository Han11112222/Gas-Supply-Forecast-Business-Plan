# app.py — 공급량 실적 및 계획 상세 (자동 매핑 + 한글 폰트 + 에폭/날짜 안전 처리)

import io
import re
import os
import unicodedata
from collections import defaultdict

import numpy as np
import pandas as pd
import matplotlib as mpl
import matplotlib.pyplot as plt
import streamlit as st
from pandas.api.types import is_datetime64_any_dtype as is_dt, is_integer_dtype


# ───────── 한글 폰트 설정 (리포: fonts/NanumGothic-Regular.ttf) ─────────
def set_korean_font():
    import matplotlib.font_manager as fm
    candidates = [
        ("fonts/NanumGothic-Regular.ttf", "NanumGothic"),
        ("fonts/NanumGothic.ttf", "NanumGothic"),
        ("/usr/share/fonts/truetype/nanum/NanumGothic.ttf", "NanumGothic"),
        ("C:/Windows/Fonts/malgun.ttf", "Malgun Gothic"),
        ("/System/Library/Fonts/AppleGothic.ttf", "AppleGothic"),
    ]
    for path, name in candidates:
        if os.path.exists(path):
            fm.fontManager.addfont(path)
            mpl.rcParams["font.family"] = name
            mpl.rcParams["axes.unicode_minus"] = False
            return
    # 폰트가 없더라도 그래프는 깨지지 않게
    mpl.rcParams["font.family"] = "DejaVu Sans"
    mpl.rcParams["axes.unicode_minus"] = False

set_korean_font()

st.set_page_config(page_title="공급량 실적 및 계획 상세", layout="wide")
st.title("📊 공급량 실적 및 계획 상세")


# ───────── 표 스켈레톤 ─────────
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

    ("합계", ""),
]
MONTH_COLS = [f"{m}월" for m in range(1, 13)]
ALL_COLS = ["구분", "세부"] + MONTH_COLS + ["합계"]

def blank_table() -> pd.DataFrame:
    df = pd.DataFrame(ROWS_SPEC, columns=["구분", "세부"])
    for c in MONTH_COLS: df[c] = np.nan
    df["합계"] = np.nan
    return df


# ───────── 자동 매핑 유틸 ─────────
def norm(s: str) -> str:
    if s is None: return ""
    s = unicodedata.normalize("NFKC", str(s)).strip().lower()
    return re.sub(r"\s+", "", s)

SYN = {
    "취사용": ["취사용", "취사", "주택취사"],
    "개별난방": ["개별난방", "개난", "개별 난방"],
    "중앙난방": ["중앙난방", "중난", "중앙 난방"],
    "일반용1": ["일반용1", "영업용1", "일반1"],
    "일반용2": ["일반용2", "업무용2", "업무일반2"],
    "냉난방용": ["냉난방용", "냉난방", "냉/난방"],
    "주택미급": ["주택미급", "주택 미급"],
    "산업용": ["산업용", "산업"],
    "열병합": ["열병합", "chp"],
    "연료전지": ["연료전지", "fc"],
    "자가열병합": ["자가열병합", "자가 chp"],
    "열전용설비용": ["열전용설비용", "열전용"],
    "CNG": ["cng", "씨엔지"],
    "BIO": ["bio", "바이오"],
}
YEAR_HINTS = ["연도", "년도", "year", "yr", "연"]
MONTH_HINTS = ["월", "month", "mm", "mon"]
DATE_HINTS = ["일자", "날짜", "date", "기준일"]

def best_match(colnames, candidates):
    cn = [norm(c) for c in colnames]
    for cand in candidates:
        nc = norm(cand)
        if nc in cn: return colnames[cn.index(nc)]
    for i,c in enumerate(cn):
        for cand in candidates:
            if norm(cand) and norm(cand) in c:
                return colnames[i]
    return None

def auto_map_usage_columns(cols):
    out = {}
    for key, aliases in SYN.items(): out[key] = best_match(cols, aliases)
    return out

def detect_year_col(cols):  return best_match(cols, YEAR_HINTS)
def detect_month_col(cols): return best_match(cols, MONTH_HINTS)
def detect_date_col(cols):  return best_match(cols, DATE_HINTS)


# ───────── 소계/합계 계산 ─────────
def calc_subtotals(table: pd.DataFrame) -> pd.DataFrame:
    t = table.copy()
    # 가정용 소계
    m = (t["구분"]=="가정용") & (t["세부"]=="소계")
    for c in MONTH_COLS:
        t.loc[m, c] = t.loc[(t["구분"]=="가정용") & (t["세부"].isin(["취사용","개별난방","중앙난방"])), c].sum()
    # 업무용 소계
    m = (t["구분"]=="업무용") & (t["세부"]=="소계")
    for c in MONTH_COLS:
        t.loc[m, c] = t.loc[(t["구분"]=="업무용") & (t["세부"].isin(["일반용2","냉난방용","주택미급"])), c].sum()
    # 수송용 소계 = BIO
    m = (t["구분"]=="수송용") & (t["세부"]=="소계")
    for c in MONTH_COLS:
        t.loc[m, c] = t.loc[(t["구분"]=="수송용") & (t["세부"]=="BIO"), c].sum()
    # 전체 합계(소계/합계 제외)
    body = (t["구분"]!="합계") & t["세부"].ne("소계") & t["세부"].ne("합계")
    m = (t["구분"]=="합계")
    for c in MONTH_COLS:
        t.loc[m, c] = t.loc[body, c].sum()
    t["합계"] = t[MONTH_COLS].sum(axis=1, min_count=1)
    return t

def highlight_rows(df: pd.DataFrame):
    styles = pd.DataFrame("", index=df.index, columns=df.columns)
    styles.loc[df["세부"]=="소계", :] = "background-color:#f2f7ff"
    styles.loc[df["구분"]=="합계", :] = "background-color:#fff3e6"
    return styles


# ───────── 사이드바 업로드 ─────────
sb = st.sidebar
sb.header("데이터 불러오기")
up = sb.file_uploader("엑셀 업로드(.xlsx)", type=["xlsx"])
if not up:
    st.info("엑셀을 업로드하면 자동으로 표가 채워집니다. (연/월 + 용도 열 형식)")
    st.stop()

import openpyxl
xls = pd.ExcelFile(io.BytesIO(up.getvalue()), engine="openpyxl")
sheet = sb.selectbox("시트 선택", options=xls.sheet_names,
                     index=(xls.sheet_names.index("데이터") if "데이터" in xls.sheet_names else 0))
raw0 = xls.parse(sheet, header=0)

# ───────── 연/월 안전 추출(에폭 ns/ms/s & datetime 모두 처리) ─────────
def _epoch_to_dt(series: pd.Series):
    s = pd.to_numeric(series, errors="coerce")
    med = s.dropna().astype("float64").abs().median()
    if med > 1e12:   # ns
        return pd.to_datetime(s, errors="coerce")
    elif med > 1e10: # ms
        return pd.to_datetime(s, unit="ms", errors="coerce")
    elif med > 1e9:  # s
        return pd.to_datetime(s, unit="s", errors="coerce")
    else:
        return None

df = raw0.copy()
year_col  = detect_year_col(df.columns)
month_col = detect_month_col(df.columns)
date_col  = detect_date_col(df.columns)

# 날짜에서 연/월 뽑기
if (year_col is None or month_col is None) and (date_col is not None):
    base_dt = pd.to_datetime(df[date_col], errors="coerce")
    if year_col is None:  df["_연도_"] = base_dt.dt.year.astype("Int64")
    if month_col is None: df["_월_"]  = base_dt.dt.month.astype("Int64")

# 지정된 연/월도 안전 처리
if "_연도_" not in df.columns:
    if year_col is None:
        st.error("연(연도) 컬럼을 못 찾았습니다. 시트의 열 이름을 확인해 주세요.")
        st.stop()
    y = df[year_col]
    if is_dt(y): y = y.dt.year
    elif is_integer_dtype(y):
        dt = _epoch_to_dt(y)
        if dt is not None: y = dt.dt.year
    else:
        y = pd.to_numeric(y, errors="coerce")
    df["_연도_"] = y.astype("Int64")

if "_월_" not in df.columns:
    if month_col is None:
        st.error("월 컬럼을 못 찾았습니다. 시트의 열 이름을 확인해 주세요.")
        st.stop()
    m = df[month_col]
    if is_dt(m): m = m.dt.month
    else:       m = pd.to_numeric(m, errors="coerce")
    df["_월_"] = m.astype("Int64")

# 용도 자동 매핑(필요시만 사이드바에서 수정)
auto_map = auto_map_usage_columns(df.columns)
with sb.expander("자동 매핑 결과(필요 시 수정)", expanded=False):
    for k in SYN.keys():
        opts = [auto_map[k]] + [c for c in df.columns if c != auto_map[k]] if auto_map[k] else list(df.columns)
        sel = st.selectbox(k, opts, key=f"map_{k}")
        auto_map[k] = sel

years = sorted(df["_연도_"].dropna().unique().tolist())
sel_year = sb.selectbox("연도 선택", years, index=(years.index(2024) if 2024 in years else 0))

# ───────── 표 채우기 ─────────
def monthly_sum(df, year, col):
    sub = df.loc[df["_연도_"]==year, ["_월_", col]].copy()
    sub[col] = pd.to_numeric(sub[col], errors="coerce")
    s = sub.groupby("_월_")[col].sum(min_count=1)
    out = pd.Series(index=range(1,13), dtype="float64"); out.update(s)
    return out

base = blank_table()

# 일반 항목
for g,d in ROWS_SPEC:
    if d in ["소계", "합계", "BIO"]:  # 소계/합계는 나중 계산, BIO는 아래 처리
        continue
    src = auto_map.get(d)
    if src:
        s = monthly_sum(df, sel_year, src)
        for m in range(1,13):
            base.loc[(base["구분"]==g)&(base["세부"]==d), f"{m}월"] = float(s[m]) if pd.notna(s[m]) else np.nan

# BIO
if auto_map.get("BIO"):
    s = monthly_sum(df, sel_year, auto_map["BIO"])
    for m in range(1,13):
        base.loc[(base["구분"]=="수송용")&(base["세부"]=="BIO"), f"{m}월"] = float(s[m]) if pd.notna(s[m]) else np.nan

filled = calc_subtotals(base)

# ───────── 표 표시 ─────────
st.subheader(f"{sel_year}년 표")
sty = filled[ALL_COLS].style.apply(highlight_rows, axis=None)\
        .format({c: "{:,.0f}".format for c in MONTH_COLS + ["합계"]})
st.dataframe(sty, use_container_width=True)

# ───────── 그래프 ─────────
st.subheader("월별 추이 그래프")
usage_list = [u for u in filled["구분"].unique().tolist() if u and u != "합계"]
selected = st.radio("보기 선택", ["전체"] + usage_list, horizontal=True, index=0)

def monthly_series(selection):
    if selection=="전체":
        mask = filled["구분"].ne("합계") & filled["세부"].ne("소계") & filled["세부"].ne("합계")
    else:
        mask = (filled["구분"]==selection) & filled["세부"].ne("소계") & filled["세부"].ne("합계")
    s = filled.loc[mask, MONTH_COLS].sum(numeric_only=True)
    xs = list(range(1,13)); ys = [float(s.get(f"{m}월",0.0)) for m in xs]
    return xs, ys

xs, ys = monthly_series(selected)
fig, ax = plt.subplots(figsize=(10,4))
ax.plot(xs, ys, marker="o")
ax.set_xticks(xs); ax.set_xlabel("월"); ax.set_ylabel("공급량(㎥)")
ax.set_title(f"{sel_year}년 {selected} 월별 합계 추이")
ax.grid(True, alpha=0.3)
st.pyplot(fig, use_container_width=True)

# ───────── 다운로드 ─────────
st.subheader("다운로드")
c1, c2 = st.columns(2)
with c1:
    st.download_button("현재 표 CSV 다운로드",
        data=filled[ALL_COLS].to_csv(index=False).encode("utf-8-sig"),
        file_name=f"supply_table_{sel_year}.csv", mime="text/csv")
with c2:
    ts = pd.DataFrame({"월": xs, "공급량(㎥)": ys})
    st.download_button("현재 그래프 데이터 CSV 다운로드",
        data=ts.to_csv(index=False).encode("utf-8-sig"),
        file_name=f"supply_timeseries_{sel_year}_{selected}.csv", mime="text/csv")
