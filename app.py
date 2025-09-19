# app.py — 공급량 실적 및 계획 상세 (멀티연도 + 동적그래프 + 안전매핑)
# - 기본 소스: 리포 파일(사업계획최종.xlsx), 필요시 업로드
# - 자동 매핑: 연/월/용도, 숫자형 컬럼만 후보로 사용 → 잘못된 에폭/날짜 매핑 방지
# - 명칭 표준화: "주한미군"(이전 "주택미급")
# - 표: 구분/세부 × 1~12월 + 합계, 소계/합계 계산
# - 연도 선택: "전체, 2024, 2025" 멀티 선택 → 표는 탭, 그래프는 연도별 라인 동시 표시
# - 그래프: Altair 인터랙티브(툴팁/범례 토글/줌&팬)

import io, os, re, unicodedata
import numpy as np
import pandas as pd
import matplotlib as mpl
import streamlit as st
from pandas.api.types import is_datetime64_any_dtype as is_dt, is_integer_dtype
import altair as alt

# ───────── 설정 ─────────
DEFAULT_REPO_FILE = "사업계획최종.xlsx"  # 리포 루트 기본 파일

# ───────── 폰트 ─────────
def set_korean_font():
    import matplotlib.pyplot as plt
    import matplotlib.font_manager as fm
    candidates = [
        ("NanumGothic-Regular.ttf", "NanumGothic"),                  # 리포 루트
        ("fonts/NanumGothic-Regular.ttf", "NanumGothic"),            # /fonts
        ("fonts/NanumGothic.ttf", "NanumGothic"),
        ("/usr/share/fonts/truetype/nanum/NanumGothic.ttf", "NanumGothic"),
        ("C:/Windows/Fonts/malgun.ttf", "Malgun Gothic"),
        ("/System/Library/Fonts/AppleGothic.ttf", "AppleGothic"),
    ]
    for path, name in candidates:
        if os.path.exists(path):
            try:
                fm.fontManager.addfont(path)
            except Exception:
                pass
            mpl.rcParams["font.family"] = name
            mpl.rcParams["axes.unicode_minus"] = False
            return
    mpl.rcParams["font.family"] = "DejaVu Sans"
    mpl.rcParams["axes.unicode_minus"] = False
set_korean_font()

st.set_page_config(page_title="공급량 실적 및 계획 상세", layout="wide")
st.title("📊 공급량 실적 및 계획 상세")

# ───────── 표 스켈레톤 ─────────
# 주의: "주한미군" 사용(이전 "주택미급")
ROWS_SPEC = [
    ("가정용", "취사용"),
    ("가정용", "개별난방"),
    ("가정용", "중앙난방"),
    ("가정용", "소계"),

    ("영업용", "일반용1"),

    ("업무용", "일반용2"),
    ("업무용", "냉난방용"),
    ("업무용", "주한미군"),
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
ALL_COLS = ["구분","세부"] + MONTH_COLS + ["합계"]

def blank_table():
    df = pd.DataFrame(ROWS_SPEC, columns=["구분","세부"])
    for c in MONTH_COLS: df[c] = np.nan
    df["합계"] = np.nan
    return df

# ───────── 매핑/정규화 유틸 ─────────
def norm(s: str) -> str:
    if s is None: return ""
    s = unicodedata.normalize("NFKC", str(s)).strip().lower()
    return re.sub(r"\s+", "", s)

# 용도 동의어 (숫자형 컬럼만 후보로 사용)
SYN = {
    "취사용": ["취사용","취사","주택취사"],
    "개별난방": ["개별난방","개난","개별 난방"],
    "중앙난방": ["중앙난방","중난","중앙 난방"],
    "일반용1": ["일반용1","영업용1","일반1"],
    "일반용2": ["일반용2","업무용2","업무일반2"],
    "냉난방용": ["냉난방용","냉난방","냉/난방"],
    "주한미군": ["주한미군","주택미군","주한 미군","usfk"],   # ← 핵심 변경
    "산업용": ["산업용","산업"],
    "열병합": ["열병합","chp"],
    "연료전지": ["연료전지","fc"],
    "자가열병합": ["자가열병합","자가 chp"],
    "열전용설비용": ["열전용설비용","열전용"],
    "CNG": ["cng","씨엔지"],
    "BIO": ["bio","바이오"],
}
YEAR_HINTS  = ["연도","년도","year","yr","연"]
MONTH_HINTS = ["월","month","mm","mon"]
DATE_HINTS  = ["일자","날짜","date","기준일"]

def best_match(colnames, aliases):
    cn = [norm(c) for c in colnames]
    for al in aliases:
        nal = norm(al)
        if nal in cn: return colnames[cn.index(nal)]
    for i, c in enumerate(cn):
        for al in aliases:
            if norm(al) and norm(al) in c:
                return colnames[i]
    return None

def likely_numeric(series: pd.Series) -> bool:
    s = pd.to_numeric(series, errors="coerce")
    return s.notna().mean() >= 0.6  # 60% 이상 숫자면 숫자형으로 간주

def auto_map_usage_columns(df: pd.DataFrame):
    cols = df.columns.tolist()
    out = {}
    for key, aliases in SYN.items():
        # 1) 동의어 이름이 들어간 컬럼 중 숫자형인 것만 후보
        candidates = []
        for c in cols:
            if best_match([c], aliases) == c and likely_numeric(df[c]):
                candidates.append(c)
        # 2) 없다면 이름 포함 & 숫자형으로 보이는 것 중에서 선택
        if not candidates:
            for c in cols:
                if any(norm(al) in norm(c) for al in aliases) and likely_numeric(df[c]):
                    candidates.append(c)
        out[key] = candidates[0] if candidates else None
    return out

def detect_year_col(cols):  return best_match(cols, YEAR_HINTS)
def detect_month_col(cols): return best_match(cols, MONTH_HINTS)
def detect_date_col(cols):  return best_match(cols, DATE_HINTS)

# ───────── 합계 계산 ─────────
def calc_subtotals(table: pd.DataFrame) -> pd.DataFrame:
    t = table.copy()

    def sum_numeric(mask, col):
        return pd.to_numeric(t.loc[mask, col], errors="coerce").sum()

    # 가정용 소계
    m_sc = (t["구분"]=="가정용") & (t["세부"]=="소계")
    for c in MONTH_COLS:
        m_body = (t["구분"]=="가정용") & (t["세부"].isin(["취사용","개별난방","중앙난방"]))
        t.loc[m_sc, c] = sum_numeric(m_body, c)

    # 업무용 소계 (일반용2/냉난방용/주한미군)
    m_sc = (t["구분"]=="업무용") & (t["세부"]=="소계")
    for c in MONTH_COLS:
        m_body = (t["구분"]=="업무용") & (t["세부"].isin(["일반용2","냉난방용","주한미군"]))
        t.loc[m_sc, c] = sum_numeric(m_body, c)

    # 수송용 소계 = BIO
    m_sc = (t["구분"]=="수송용") & (t["세부"]=="소계")
    for c in MONTH_COLS:
        m_body = (t["구분"]=="수송용") & (t["세부"]=="BIO")
        t.loc[m_sc, c] = sum_numeric(m_body, c)

    # 전체 합계 (소계/합계 제외)
    m_total = (t["구분"]=="합계")
    m_body  = (t["구분"]!="합계") & t["세부"].ne("소계") & t["세부"].ne("합계")
    for c in MONTH_COLS:
        t.loc[m_total, c] = sum_numeric(m_body, c)

    t["합계"] = t[MONTH_COLS].apply(pd.to_numeric, errors="coerce").sum(axis=1, min_count=1)
    return t

def highlight_rows(df: pd.DataFrame):
    styles = pd.DataFrame("", index=df.index, columns=df.columns)
    styles.loc[df["세부"]=="소계", :] = "background-color:#f2f7ff"
    styles.loc[df["구분"]=="합계", :] = "background-color:#fff3e6"
    return styles

# ───────── 데이터 소스 ─────────
sb = st.sidebar
sb.header("데이터 불러오기")
source = sb.radio("데이터 소스", ["리포 파일 사용", "엑셀 업로드(.xlsx)"], index=0)

if source == "리포 파일 사용":
    if not os.path.exists(DEFAULT_REPO_FILE):
        st.error(f"리포에 `{DEFAULT_REPO_FILE}` 파일이 없습니다. 업로드 모드를 사용하세요.")
        st.stop()
    import openpyxl
    xls = pd.ExcelFile(DEFAULT_REPO_FILE, engine="openpyxl")
    current_source_name = DEFAULT_REPO_FILE
else:
    up = sb.file_uploader("엑셀 업로드(.xlsx)", type=["xlsx"])
    if not up:
        st.info("엑셀을 업로드하면 표가 채워집니다.")
        st.stop()
    import openpyxl
    xls = pd.ExcelFile(io.BytesIO(up.getvalue()), engine="openpyxl")
    current_source_name = up.name

sheet = sb.selectbox("시트 선택", options=xls.sheet_names,
                     index=(xls.sheet_names.index("데이터") if "데이터" in xls.sheet_names else 0))
raw0 = xls.parse(sheet, header=0)

# ───────── 연/월 추출 (에폭 ns/ms/s & datetime 안전 처리) ─────────
def _epoch_to_dt(series: pd.Series):
    s = pd.to_numeric(series, errors="coerce")
    med = s.dropna().astype("float64").abs().median()
    if med > 1e12:   return pd.to_datetime(s, errors="coerce")             # ns
    elif med > 1e10: return pd.to_datetime(s, unit="ms", errors="coerce")  # ms
    elif med > 1e9:  return pd.to_datetime(s, unit="s", errors="coerce")   # s
    else:            return None

df = raw0.copy()
year_col  = detect_year_col(df.columns)
month_col = detect_month_col(df.columns)
date_col  = detect_date_col(df.columns)

if (year_col is None or month_col is None) and (date_col is not None):
    base_dt = pd.to_datetime(df[date_col], errors="coerce")
    if year_col is None:  df["_연도_"] = base_dt.dt.year.astype("Int64")
    if month_col is None: df["_월_"]  = base_dt.dt.month.astype("Int64")

if "_연도_" not in df.columns:
    if year_col is None:
        st.error("연(연도) 컬럼을 못 찾았습니다. 시트 열 이름을 확인하세요.")
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
        st.error("월 컬럼을 못 찾았습니다. 시트 열 이름을 확인하세요.")
        st.stop()
    m = df[month_col]
    if is_dt(m): m = m.dt.month
    else:       m = pd.to_numeric(m, errors="coerce")
    df["_월_"] = m.astype("Int64")

# ───────── 자동 매핑(숫자형 컬럼만 후보) ─────────
auto_map = auto_map_usage_columns(df)
with sb.expander("자동 매핑 결과(필요 시 수정)", expanded=False):
    for k in SYN.keys():
        candidates = [c for c in df.columns if likely_numeric(df[c])]
        default = auto_map.get(k)
        if default and default not in candidates:
            candidates = [default] + candidates
        auto_map[k] = st.selectbox(k, [None] + candidates, index=(0 if default is None else ([None]+candidates).index(default)))

years_avail = sorted(df["_연도_"].dropna().unique().tolist())
# 상단 멀티 선택: 전체 + 연도들
year_labels = ["전체"] + [str(y) for y in years_avail]
st.subheader("연도 선택")
year_selected = st.multiselect("", year_labels, default=["전체"], label_visibility="collapsed", help="여러 연도를 동시에 볼 수 있습니다.")

if not year_selected:
    st.warning("연도를 1개 이상 선택하세요.")
    st.stop()
if "전체" in year_selected:
    sel_years = years_avail
else:
    sel_years = sorted([int(y) for y in year_selected if y != "전체"])

# ───────── 집계 함수 ─────────
def monthly_sum(df, year, col):
    sub = df.loc[df["_연도_"]==year, ["_월_", col]].copy()
    # datetime 열이거나 숫자형이 아니면 제외
    if is_dt(sub[col]):
        sub[col] = pd.NA
    sub[col] = pd.to_numeric(sub[col], errors="coerce")
    s = sub.groupby("_월_")[col].sum(min_count=1)
    out = pd.Series(index=range(1,13), dtype="float64"); out.update(s)
    return out

def build_table_for_year(year:int) -> pd.DataFrame:
    base = blank_table()

    # 용도 값 채우기
    for g,d in ROWS_SPEC:
        if d in ["소계","합계","BIO"]:  # 소계/합계는 나중에, BIO는 별도
            continue
        src = auto_map.get(d)
        if src:
            s = monthly_sum(df, year, src)
            for m in range(1,13):
                base.loc[(base["구분"]==g)&(base["세부"]==d), f"{m}월"] = float(s[m]) if pd.notna(s[m]) else np.nan

    # BIO
    if auto_map.get("BIO"):
        s = monthly_sum(df, year, auto_map["BIO"])
        for m in range(1,13):
            base.loc[(base["구분"]=="수송용")&(base["세부"]=="BIO"), f"{m}월"] = float(s[m]) if pd.notna(s[m]) else np.nan

    filled = calc_subtotals(base)
    return filled

# ───────── 표(연도별 탭) ─────────
st.caption(f"소스: {current_source_name} · 시트: {sheet}")
tabs = st.tabs([f"{y}년 표" for y in sel_years])
tables_per_year = {}

for i, y in enumerate(sel_years):
    with tabs[i]:
        tbl = build_table_for_year(y)
        tables_per_year[y] = tbl
        sty = tbl[ALL_COLS].style.apply(highlight_rows, axis=None)\
                .format({c: "{:,.0f}".format for c in MONTH_COLS + ["합계"]})
        st.dataframe(sty, use_container_width=True)

# ───────── 그래프(동적, 연도별 색상) ─────────
st.subheader("월별 추이 그래프")

# 보기 선택(구분)
all_groups = ["전체","가정용","영업용","업무용","산업용","열병합","연료전지","자가열병합","열전용설비용","CNG","수송용"]
group_sel = st.radio("보기 선택", all_groups, horizontal=True, index=0)

def series_for_year(tbl: pd.DataFrame, group: str):
    if group=="전체":
        mask = tbl["구분"].ne("합계") & tbl["세부"].ne("소계") & tbl["세부"].ne("합계")
    else:
        mask = (tbl["구분"]==group) & tbl["세부"].ne("소계") & tbl["세부"].ne("합계")
    s = tbl.loc[mask, MONTH_COLS].apply(pd.to_numeric, errors="coerce").sum(numeric_only=True)
    return [float(s.get(f"{m}월",0.0)) for m in range(1,13)]

# 통합 데이터프레임(연도 × 월 × 값)
chart_rows = []
for y in sel_years:
    tbl = tables_per_year[y]
    ys = series_for_year(tbl, group_sel)
    for m, v in enumerate(ys, start=1):
        chart_rows.append({"연도": str(y), "월": m, "공급량(㎥)": v})
chart_df = pd.DataFrame(chart_rows)

# Altair 동적 라인 차트
selection = alt.selection_point(fields=["연도"], bind="legend")
line = (
    alt.Chart(chart_df)
    .mark_line(point=True)
    .encode(
        x=alt.X("월:O", title="월"),
        y=alt.Y("공급량(㎥):Q", title="공급량(㎥)"),
        color=alt.Color("연도:N", legend=alt.Legend(title="연도")),
        tooltip=["연도","월","공급량(㎥)"]
    )
    .add_params(selection)
    .transform_filter(selection)
).properties(width="container", height=350)

st.altair_chart(line, use_container_width=True)

# ───────── 다운로드 ─────────
st.subheader("다운로드")
c1, c2 = st.columns(2)
with c1:
    # 마지막 탭(또는 첫 탭) 기준으로 예시 다운로드
    y0 = sel_years[0]
    st.download_button(
        f"{y0}년 표 CSV 다운로드",
        data=tables_per_year[y0][ALL_COLS].to_csv(index=False).encode("utf-8-sig"),
        file_name=f"supply_table_{y0}.csv",
        mime="text/csv"
    )
with c2:
    st.download_button(
        "그래프 데이터 CSV 다운로드",
        data=chart_df.to_csv(index=False).encode("utf-8-sig"),
        file_name=f"supply_timeseries_{group_sel}_{'-'.join(map(str,sel_years))}.csv",
        mime="text/csv"
    )
