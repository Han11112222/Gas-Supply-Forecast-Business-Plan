# app.py — 공급량 실적 및 계획 상세 (두 가지 입력 모드 지원)
# ① 원자료(연/월+용도 열) → 매핑 후 월별 집계
# ② 완성 표(구분/세부 × 1~12월) → 그대로 읽어 표에 채움
import io
import numpy as np
import pandas as pd
import matplotlib as mpl
import matplotlib.pyplot as plt
import streamlit as st

def set_korean_font():
    try:
        mpl.rcParams["font.family"] = "NanumGothic"
        mpl.rcParams["axes.unicode_minus"] = False
    except Exception:
        pass
set_korean_font()

st.set_page_config(page_title="공급량 실적 및 계획 상세", layout="wide")
st.title("📊 공급량 실적 및 계획 상세")

# ----------- 표 스켈레톤 -----------
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
    t["합계"] = t[MONTH_COLS].sum(axis=1, min_count=1)
    return t

def styled_dataframe(sdf: pd.DataFrame):
    sty = sdf.style
    sty = sty.set_table_styles([
        {"selector": "th.col_heading", "props": "background:#f6f6f6;"},
        {"selector": "thead th", "props": "text-align:center;"},
        {"selector": "tbody td", "props": "text-align:right;"},
    ])
    sty = sty.set_properties(subset=["구분","세부"], **{"text-align":"left"})
    mask_sub = sdf["세부"].eq("소계")
    sty = sty.apply(lambda r: ["background-color:#f2f7ff" if m else "" for m in mask_sub], axis=1)
    mask_tot = sdf["구분"].eq("합계")
    sty = sty.apply(lambda r: ["background-color:#fff3e6" if m else "" for m in mask_tot], axis=1)
    sty = sty.format({c: "{:,.0f}".format for c in MONTH_COLS + ["합계"]})
    return sty

# ----------- 업로드 -----------
sb = st.sidebar
sb.header("데이터 불러오기")
mode = sb.radio("데이터 형식", ["원자료(연/월+용도 열)", "완성 표(1~12월 열)"], horizontal=False)
up = sb.file_uploader("엑셀 업로드(.xlsx)", type=["xlsx"])
if not up:
    st.info("엑셀을 업로드하면 표가 채워집니다.")
    st.stop()

import openpyxl
xls = pd.ExcelFile(io.BytesIO(up.getvalue()), engine="openpyxl")
sheet = sb.selectbox("시트 선택", options=xls.sheet_names,
                     index=(xls.sheet_names.index("데이터") if "데이터" in xls.sheet_names else 0))

# =========================================================
# 모드 A) 원자료(연/월+용도 열)  → 월별 집계
# =========================================================
if mode == "원자료(연/월+용도 열)":
    raw0 = xls.parse(sheet, header=0)

    # 자동 추정
    def guess_year_col(cols):
        for c in cols:
            lc = str(c).lower()
            if any(w in lc for w in ["연도","년도","year","yr"]):
                return c
        return None
    def guess_month_col(cols):
        for c in cols:
            lc = str(c).lower()
            if lc == "월" or "month" in lc or lc in ["mm","mon"]:
                return c
        for c in cols:
            if "월" in str(c):
                return c
        return None

    year_col_guess = guess_year_col(raw0.columns)
    month_col_guess = guess_month_col(raw0.columns)

    # 동의어
    SYN = {
        "취사용":["취사용","취사"],
        "개별난방":["개별난방"],
        "중앙난방":["중앙난방"],
        "일반용1":["일반용1","영업용1"],
        "일반용2":["일반용2","업무용2"],
        "냉난방용":["냉난방용","냉/난방"],
        "주택미급":["주택미급"],
        "산업용":["산업용","산업"],
        "열병합":["열병합","CHP"],
        "연료전지":["연료전지","FC"],
        "자가열병합":["자가열병합","자가CHP"],
        "열전용설비용":["열전용설비용","열전용"],
        "CNG":["CNG","씨엔지"],
        "BIO":["BIO","바이오"],
    }
    def auto_pick(colnames, key):
        lc = [str(c).strip().lower() for c in colnames]
        for cand in SYN[key]:
            c = cand.lower()
            if c in lc:
                return colnames[lc.index(c)]
        return None

    sb.markdown("### 컬럼 매핑")
    year_col = sb.selectbox("연도 컬럼", [None] + raw0.columns.tolist(),
                            index=(raw0.columns.tolist().index(year_col_guess)+1) if year_col_guess in raw0.columns else 0)
    month_col = sb.selectbox("월 컬럼(또는 날짜)", [None] + raw0.columns.tolist(),
                             index=(raw0.columns.tolist().index(month_col_guess)+1) if month_col_guess in raw0.columns else 0)

    # 날짜 컬럼 옵션
    date_candidates = [c for c in raw0.columns if any(k in str(c).lower() for k in ["date","일자","날짜","기준일"])]
    date_col = sb.selectbox("날짜 컬럼(연/월 자동추출·선택사항)", [None]+date_candidates, index=0) if date_candidates else None

    mapping = {}
    for key in ["취사용","개별난방","중앙난방","일반용1","일반용2","냉난방용","주택미급",
                "산업용","열병합","연료전지","자가열병합","열전용설비용","CNG","BIO"]:
        default = auto_pick(raw0.columns.tolist(), key)
        idx = (raw0.columns.tolist().index(default)+1) if default in raw0.columns else 0
        mapping[key] = sb.selectbox(f"엑셀 열 ↔ {key}", [None]+raw0.columns.tolist(), index=idx, key=f"map_{key}")

    # 연/월 생성
    df = raw0.copy()
    if date_col:
        tmp = pd.to_datetime(df[date_col], errors="coerce")
        if year_col is None:
            df["__연도__"] = tmp.dt.year; year_col = "__연도__"
        if month_col is None:
            df["__월__"] = tmp.dt.month; month_col = "__월__"

    if year_col is None or month_col is None:
        st.error("연도/월 컬럼을 지정하거나 날짜 컬럼을 선택해 주세요.")
        st.stop()

    df["_연도_"] = pd.to_numeric(df[year_col], errors="coerce").astype("Int64")
    df["_월_"] = pd.to_numeric(df[month_col], errors="coerce").astype("Int64")
    years = sorted(df["_연도_"].dropna().unique().tolist())
    sel_year = sb.selectbox("연도 선택", years, index=(years.index(2024) if 2024 in years else 0))

    base = blank_table()
    targets = {k:v for k,v in mapping.items() if v is not None}

    def monthly_sum(col_name: str) -> pd.Series:
        sub = df.query("_연도_ == @sel_year")[["_월_", col_name]].copy()
        sub[col_name] = pd.to_numeric(sub[col_name], errors="coerce")
        s = sub.groupby("_월_")[col_name].sum(min_count=1)
        out = pd.Series(index=range(1,13), dtype="float64")
        out.update(s)
        return out

    for g,d in ROWS_SPEC:
        if d in targets:
            vals = monthly_sum(targets[d])
            for m in range(1,13):
                base.loc[(base["구분"]==g)&(base["세부"]==d), f"{m}월"] = float(vals[m]) if pd.notna(vals[m]) else np.nan

    filled = calc_subtotals(base)
    title_year = sel_year

# =========================================================
# 모드 B) 완성 표(1~12월 열)  → 그대로 채우기
# =========================================================
else:
    raw = xls.parse(sheet, header=0)
    # 컬럼 표준화: '1' '01' '1월' 모두 허용
    rename = {}
    for c in raw.columns:
        s = str(c).strip()
        s2 = s.replace(" ", "")
        # '1월' 또는 숫자
        if s2.endswith("월"):
            num = s2.replace("월","")
        else:
            num = s2
        if num.isdigit() and 1 <= int(num) <= 12:
            rename[c] = f"{int(num)}월"
        # 구분/세부 비슷한 이름 매핑
        if s in ["구분","분류","용도"]:
            rename[c] = "구분"
        if s in ["세부","세부항목","항목"]:
            rename[c] = "세부"
    raw = raw.rename(columns=rename)

    # 필요 컬럼만 추출
    need = set(["구분","세부"] + MONTH_COLS)
    cols = [c for c in raw.columns if c in need]
    table = raw[cols].copy()

    # 숫자화
    for c in MONTH_COLS:
        if c in table.columns:
            table[c] = pd.to_numeric(table[c], errors="coerce")

    # 스켈레톤에 맞춰 채우기(행 이름으로 매칭)
    base = blank_table()
    for (g,d) in ROWS_SPEC:
        mask = (table.get("구분", pd.Series(dtype=object))==g) & (table.get("세부", pd.Series(dtype=object))==d)
        if mask.any():
            row = table.loc[mask, MONTH_COLS].sum()
            for m in MONTH_COLS:
                base.loc[(base["구분"]==g)&(base["세부"]==d), m] = row.get(m, np.nan)

    filled = calc_subtotals(base)

    # 완성표에는 연도 정보가 없을 수 있으므로 제목용 연도 입력
    title_year = st.sidebar.text_input("표 제목용 연도(예: 2024)", value="2024")

# ----------- 출력 -----------
st.subheader(f"{title_year}년 표")
st.dataframe(styled_dataframe(filled[ALL_COLS]), use_container_width=True)

st.subheader("월별 추이 그래프")
usage_list = [u for u in filled["구분"].dropna().unique().tolist() if u and u != "합계"]
selected = st.segmented_control("보기 선택", options=["전체"] + usage_list, default="전체")

def monthly_series(selection: str):
    if selection == "전체":
        mask = filled["구분"].ne("합계") & filled["세부"].ne("소계") & filled["세부"].ne("합계")
    else:
        mask = (filled["구분"]==selection) & filled["세부"].ne("소계") & filled["세부"].ne("합계")
    s = filled.loc[mask, MONTH_COLS].sum(numeric_only=True)
    xs = list(range(1,13))
    ys = [float(s.get(f"{m}월",0.0)) for m in xs]
    return xs, ys

xs, ys = monthly_series(selected)
fig, ax = plt.subplots(figsize=(10,4))
ax.plot(xs, ys, marker="o")
ax.set_xticks(xs)
ax.set_xlabel("월"); ax.set_ylabel("공급량(㎥)")
ax.set_title(f"{title_year}년 {selected} 월별 합계 추이")
ax.grid(True, alpha=0.3)
st.pyplot(fig, use_container_width=True)

st.subheader("다운로드")
c1, c2 = st.columns(2)
with c1:
    st.download_button("현재 표 CSV 다운로드",
        data=filled[ALL_COLS].to_csv(index=False).encode("utf-8-sig"),
        file_name=f"supply_table_{title_year}.csv", mime="text/csv")
with c2:
    ts = pd.DataFrame({"월": xs, "공급량(㎥)": ys})
    st.download_button("현재 그래프 데이터 CSV 다운로드",
        data=ts.to_csv(index=False).encode("utf-8-sig"),
        file_name=f"supply_timeseries_{title_year}_{selected}.csv", mime="text/csv")
