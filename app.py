# app.py — 공급량 실적 및 계획 상세 (자동 매핑 버전)
# - 엑셀(.xlsx) 업로드만 하면 자동으로 연/월/용도 컬럼을 인식하여 표를 채움
# - 필요할 때만 사이드바에서 자동 매핑 결과를 수정 가능
# - 표(구분/세부 × 1~12월 + 합계), 소계/합계 자동 계산, 하이라이트 포함
# - 버튼(전체/용도별) + 월별 그래프, CSV 다운로드

import io
import re
import unicodedata
from collections import defaultdict

import numpy as np
import pandas as pd
import matplotlib as mpl
import matplotlib.pyplot as plt
import streamlit as st


# ---------------------- 공통 설정 ----------------------
def set_korean_font():
    try:
        mpl.rcParams["font.family"] = "NanumGothic"
        mpl.rcParams["axes.unicode_minus"] = False
    except Exception:
        pass

set_korean_font()
st.set_page_config(page_title="공급량 실적 및 계획 상세", layout="wide")
st.title("📊 공급량 실적 및 계획 상세")


# ---------------------- 표 스켈레톤 ----------------------
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
    for c in MONTH_COLS:
        df[c] = np.nan
    df["합계"] = np.nan
    return df


# ---------------------- 유틸/정규화 ----------------------
def norm(s: str) -> str:
    """소문자/공백제거/한글정규화."""
    if s is None:
        return ""
    s = str(s)
    s = unicodedata.normalize("NFKC", s)
    s = s.strip().lower()
    s = re.sub(r"\s+", "", s)
    return s


# 용도 동의어(자동 매핑)
SYN = {
    "취사용": ["취사용", "취사", "주택취사"],
    "개별난방": ["개별난방", "개난", "개별난"],
    "중앙난방": ["중앙난방", "중난", "중앙난"],
    "일반용1": ["일반용1", "일반1", "영업용1", "영업일반1"],
    # 네 파일에 맞춘 자동 매핑
    "일반용2": ["일반용2", "업무용2", "업무일반2"],
    "냉난방용": ["냉난방용", "냉난방", "냉/난방"],
    "주택미급": ["주택미급", "주택미급수"],
    "산업용": ["산업용", "산업"],
    "열병합": ["열병합", "열병", "chp"],
    "연료전지": ["연료전지", "연료 전지", "fc"],
    "자가열병합": ["자가열병합", "자가 chp", "자가열병"],
    "열전용설비용": ["열전용설비용", "열전용", "열전용설비"],
    "CNG": ["cng", "씨엔지"],
    "BIO": ["bio", "바이오", "바이오가스"],
}

YEAR_HINTS = ["연도", "년도", "year", "yr"]
MONTH_HINTS = ["월", "month", "mm", "mon"]
DATE_HINTS = ["일자", "날짜", "date", "기준일"]


def best_match(colnames, candidates):
    cn = [norm(c) for c in colnames]
    for cand in candidates:
        n = norm(cand)
        if n in cn:
            return colnames[cn.index(n)]
    # 약간의 느슨한 포함 매칭
    for i, c in enumerate(cn):
        for cand in candidates:
            if norm(cand) and norm(cand) in c:
                return colnames[i]
    return None


def auto_map_usage_columns(cols):
    """용도 컬럼 자동 매핑 결과 dict 반환."""
    result = {}
    for key, aliases in SYN.items():
        pick = best_match(cols, aliases)
        result[key] = pick  # 없으면 None
    return result


def detect_year_col(cols):
    return best_match(cols, YEAR_HINTS)


def detect_month_col(cols):
    # 정확히 '월' 같은 케이스 우선
    exact = [c for c in cols if norm(c) == "월"]
    if exact:
        return exact[0]
    return best_match(cols, MONTH_HINTS)


def detect_date_col(cols):
    return best_match(cols, DATE_HINTS)


# ---------------------- 계산/표 생성 ----------------------
def calc_subtotals(table: pd.DataFrame) -> pd.DataFrame:
    t = table.copy()

    # 가정용 소계
    m = (t["구분"] == "가정용") & (t["세부"] == "소계")
    for c in MONTH_COLS:
        t.loc[m, c] = t.loc[(t["구분"] == "가정용") &
                            (t["세부"].isin(["취사용", "개별난방", "중앙난방"])), c].sum()

    # 업무용 소계
    m = (t["구분"] == "업무용") & (t["세부"] == "소계")
    for c in MONTH_COLS:
        t.loc[m, c] = t.loc[(t["구분"] == "업무용") &
                            (t["세부"].isin(["일반용2", "냉난방용", "주택미급"])), c].sum()

    # 수송용 소계 = BIO
    m = (t["구분"] == "수송용") & (t["세부"] == "소계")
    for c in MONTH_COLS:
        t.loc[m, c] = t.loc[(t["구분"] == "수송용") &
                            (t["세부"] == "BIO"), c].sum()

    # 전체 합계(소계/합계 제외)
    body = (t["구분"] != "합계") & t["세부"].ne("소계") & t["세부"].ne("합계")
    m = (t["구분"] == "합계")
    for c in MONTH_COLS:
        t.loc[m, c] = t.loc[body, c].sum()

    t["합계"] = t[MONTH_COLS].sum(axis=1, min_count=1)
    return t


def monthly_sum(df: pd.DataFrame, year: int, value_col: str) -> pd.Series:
    sub = df.loc[df["_연도_"] == year, ["_월_", value_col]].copy()
    sub[value_col] = pd.to_numeric(sub[value_col], errors="coerce")
    s = sub.groupby("_월_")[value_col].sum(min_count=1)
    out = pd.Series(index=range(1, 13), dtype="float64")
    out.update(s)
    return out


def highlight_rows(df: pd.DataFrame):
    """Styler용: 행 전체를 조건으로 칠한다(모양 불일치 에러 방지)."""
    styles = pd.DataFrame("", index=df.index, columns=df.columns)
    styles.loc[df["세부"] == "소계", :] = "background-color:#f2f7ff"
    styles.loc[df["구분"] == "합계", :] = "background-color:#fff3e6"
    return styles


# ---------------------- 사이드바: 업로드 ----------------------
sb = st.sidebar
sb.header("데이터 불러오기")
up = sb.file_uploader("엑셀 업로드(.xlsx)", type=["xlsx"])
if not up:
    st.info("엑셀 파일을 업로드하면 자동으로 표가 채워집니다. (연/월 + 용도 열 형식)")
    st.stop()

import openpyxl  # ensure engine
xls = pd.ExcelFile(io.BytesIO(up.getvalue()), engine="openpyxl")
default_sheet = "데이터" if "데이터" in xls.sheet_names else xls.sheet_names[0]
sheet = sb.selectbox("시트 선택", options=xls.sheet_names,
                     index=xls.sheet_names.index(default_sheet))
raw0 = xls.parse(sheet, header=0)

# ---------------------- 자동 매핑 ----------------------
# 연/월/날짜 감지
year_col = detect_year_col(raw0.columns)
month_col = detect_month_col(raw0.columns)
date_col = detect_date_col(raw0.columns)

df = raw0.copy()

# 날짜에서 연/월 추출(필요 시)
if (year_col is None or month_col is None) and (date_col is not None):
    dt = pd.to_datetime(df[date_col], errors="coerce")
    if year_col is None:
        df["__연도__"] = dt.dt.year
        year_col = "__연도__"
    if month_col is None:
        df["__월__"] = dt.dt.month
        month_col = "__월__"

# 그래도 없으면 사용자가 한 번만 지정할 수 있게 보조 UI
with sb.expander("자동 매핑 결과(필요 시 수정)", expanded=False):
    year_col = st.selectbox("연도 컬럼", [year_col] + [c for c in df.columns if c != year_col]) if year_col else st.selectbox("연도 컬럼", df.columns)
    month_col = st.selectbox("월 컬럼", [month_col] + [c for c in df.columns if c != month_col]) if month_col else st.selectbox("월 컬럼", df.columns)

# 내부 전용 컬럼으로 통일
df["_연도_"] = pd.to_numeric(df[year_col], errors="coerce").astype("Int64")
df["_월_"] = pd.to_numeric(df[month_col], errors="coerce").astype("Int64")

# 용도 자동 매핑
auto_map = auto_map_usage_columns(df.columns)

with sb.expander("용도 자동 매핑 결과(필요 시 수정)", expanded=False):
    for k in SYN.keys():
        options = [auto_map[k]] + [c for c in df.columns if c != auto_map[k]] if auto_map[k] else list(df.columns)
        sel = st.selectbox(f"{k}", options=options, key=f"map_{k}")
        auto_map[k] = sel

# 연도 선택(기본 2024 우선)
years = sorted(df["_연도_"].dropna().unique().tolist())
sel_year = sb.selectbox("연도 선택", options=years,
                        index=(years.index(2024) if 2024 in years else 0))

# ---------------------- 표 채우기 ----------------------
base = blank_table()
for g, d in ROWS_SPEC:
    # d가 실제 값(‘소계’/‘합계’ 제외)일 때만 소스에서 집계
    if d in auto_map and auto_map[d] is not None and d not in ["소계", "합계", "BIO"] and g != "수송용":
        s = monthly_sum(df, sel_year, auto_map[d])
        for m in range(1, 13):
            base.loc[(base["구분"] == g) & (base["세부"] == d), f"{m}월"] = float(s[m]) if pd.notna(s[m]) else np.nan

# 수송용 BIO
if auto_map.get("BIO"):
    s = monthly_sum(df, sel_year, auto_map["BIO"])
    for m in range(1, 13):
        base.loc[(base["구분"] == "수송용") & (base["세부"] == "BIO"), f"{m}월"] = float(s[m]) if pd.notna(s[m]) else np.nan

filled = calc_subtotals(base)

# ---------------------- 표 표시(스타일) ----------------------
st.subheader(f"{sel_year}년 표")
sty = filled[ALL_COLS].style.apply(highlight_rows, axis=None).format({c: "{:,.0f}".format for c in MONTH_COLS + ["합계"]})
st.dataframe(sty, use_container_width=True)

# ---------------------- 그래프 ----------------------
st.subheader("월별 추이 그래프")
usage_list = [u for u in filled["구분"].unique().tolist() if u and u != "합계"]
selected = st.radio("보기 선택", options=["전체"] + usage_list, horizontal=True, index=0)

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
ax.set_xlabel("월"); ax.set_ylabel("공급량(㎥)")
ax.set_title(f"{sel_year}년 {selected} 월별 합계 추이")
ax.grid(True, alpha=0.3)
st.pyplot(fig, use_container_width=True)

# ---------------------- 다운로드 ----------------------
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
