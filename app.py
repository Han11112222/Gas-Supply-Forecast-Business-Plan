# app.py — 공급량 실적 및 계획 상세 (데이터/best/conservative 동시 지원, 2024~2027, None 제거, 동적 그래프)

import io, os, re, unicodedata
import numpy as np
import pandas as pd
import matplotlib as mpl
import streamlit as st
from pandas.api.types import is_datetime64_any_dtype as is_dt, is_integer_dtype
import altair as alt

DEFAULT_REPO_FILE = "사업계획최종.xlsx"

# ─────────────────────────────────────────────────────────
# 폰트
def set_korean_font():
    import matplotlib.font_manager as fm
    candidates = [
        ("NanumGothic-Regular.ttf", "NanumGothic"),
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

# ─────────────────────────────────────────────────────────
# 표 기본 구조(행 순서 고정)
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
MONTH_COLS = [f"{m}월" for m in range(1, 12 + 1)]
ALL_COLS = ["구분", "세부"] + MONTH_COLS + ["합계"]

def blank_table():
    df = pd.DataFrame(ROWS_SPEC, columns=["구분", "세부"])
    for c in MONTH_COLS:
        df[c] = np.nan
    df["합계"] = np.nan
    return df

def norm(s) -> str:
    if s is None:
        return ""
    s = unicodedata.normalize("NFKC", str(s)).strip().lower()
    return re.sub(r"\s+", "", s)

# 동의어(스크린샷에 보인 '업무난방' 등을 포함)
SYN = {
    "취사용": ["취사용", "취사", "주택취사"],
    "개별난방": ["개별난방", "개난", "개별 난방"],
    "중앙난방": ["중앙난방", "중난", "중앙 난방"],
    "일반용1": ["일반용1", "영업용1", "일반1"],
    "일반용2": ["일반용2", "업무용", "업무난방", "업무용난방", "업무 일반"],
    "냉난방용": ["냉난방용", "냉난방", "냉/난방", "업무냉난방"],
    "주한미군": ["주한미군", "주택미군", "주한 미군", "usfk", "주택미급"],
    "산업용": ["산업용", "산업"],
    "열병합": ["열병합", "chp"],
    "연료전지": ["연료전지", "fc"],
    "자가열병합": ["자가열병합", "자가 chp"],
    "열전용설비용": ["열전용설비용", "열전용"],
    "CNG": ["cng", "씨엔지"],
    "BIO": ["bio", "바이오"],
}

YEAR_HINTS  = ["연도", "년도", "year", "yr", "연"]
MONTH_HINTS = ["월", "month", "mm", "mon"]
DATE_HINTS  = ["일자", "날짜", "date", "기준일"]

def best_match(colnames, aliases):
    cn = [norm(c) for c in colnames]
    for al in aliases:
        nal = norm(al)
        if nal in cn:
            return colnames[cn.index(nal)]
    for i, c in enumerate(cn):
        for al in aliases:
            if norm(al) and norm(al) in c:
                return colnames[i]
    return None

def likely_numeric(series: pd.Series) -> bool:
    s = pd.to_numeric(series, errors="coerce")
    return s.notna().mean() >= 0.6

def auto_map_usage_columns(df: pd.DataFrame):
    cols = df.columns.tolist()
    out = {}
    for key, aliases in SYN.items():
        candidates = []
        for c in cols:
            if best_match([c], aliases) == c and likely_numeric(df[c]):
                candidates.append(c)
        if not candidates:
            for c in cols:
                if any(norm(al) in norm(c) for al in aliases) and likely_numeric(df[c]):
                    candidates.append(c)
        out[key] = candidates[0] if candidates else None
    return out

def detect_year_col(cols):  return best_match(cols, YEAR_HINTS)
def detect_month_col(cols): return best_match(cols, MONTH_HINTS)
def detect_date_col(cols):  return best_match(cols, DATE_HINTS)

def _epoch_to_dt(series: pd.Series):
    s = pd.to_numeric(series, errors="coerce")
    med = s.dropna().astype("float64").abs().median()
    if med > 1e12:
        return pd.to_datetime(s, errors="coerce")
    elif med > 1e10:
        return pd.to_datetime(s, unit="ms", errors="coerce")
    elif med > 1e9:
        return pd.to_datetime(s, unit="s", errors="coerce")
    else:
        return None

def calc_subtotals(table: pd.DataFrame) -> pd.DataFrame:
    t = table.copy()

    def sum_numeric(mask, col):
        return pd.to_numeric(t.loc[mask, col], errors="coerce").sum()

    # 가정용 소계
    m_sc = (t["구분"] == "가정용") & (t["세부"] == "소계")
    for c in MONTH_COLS:
        m_body = (t["구분"] == "가정용") & (t["세부"].isin(["취사용", "개별난방", "중앙난방"]))
        t.loc[m_sc, c] = sum_numeric(m_body, c)

    # 업무용 소계
    m_sc = (t["구분"] == "업무용") & (t["세부"] == "소계")
    for c in MONTH_COLS:
        m_body = (t["구분"] == "업무용") & (t["세부"].isin(["일반용2", "냉난방용", "주한미군"]))
        t.loc[m_sc, c] = sum_numeric(m_body, c)

    # 수송용 소계(BIO)
    m_sc = (t["구분"] == "수송용") & (t["세부"] == "소계")
    for c in MONTH_COLS:
        m_body = (t["구분"] == "수송용") & (t["세부"] == "BIO")
        t.loc[m_sc, c] = sum_numeric(m_body, c)

    # 전체 합계(소계/합계 라인은 제외)
    m_total = (t["구분"] == "합계")
    m_body = (t["구분"] != "합계") & t["세부"].ne("소계") & t["세부"].ne("합계")
    for c in MONTH_COLS:
        t.loc[m_total, c] = sum_numeric(m_body, c)

    t["합계"] = t[MONTH_COLS].apply(pd.to_numeric, errors="coerce").sum(axis=1, min_count=1)
    return t

def highlight_rows(df: pd.DataFrame):
    styles = pd.DataFrame("", index=df.index, columns=df.columns)
    styles.loc[df["세부"] == "소계", :] = "background-color:#f2f7ff"
    styles.loc[df["구분"] == "합계", :] = "background-color:#fff3e6"
    return styles

def coerce_numeric_inplace(df: pd.DataFrame):
    """월/합계 숫자형 강제 + NaN→0"""
    for c in MONTH_COLS + ["합계"]:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)

# ─────────────────────────────────────────────────────────
# 공통 처리: 한 시트(df) → 자동매핑 → 연도별 표/그래프 데이터 생성
def prepare_df(df_in: pd.DataFrame):
    df = df_in.copy()

    # 연/월 추출
    year_col  = detect_year_col(df.columns)
    month_col = detect_month_col(df.columns)
    date_col  = detect_date_col(df.columns)

    if (year_col is None or month_col is None) and (date_col is not None):
        base_dt = pd.to_datetime(df[date_col], errors="coerce")
        if year_col is None:
            df["_연도_"] = base_dt.dt.year.astype("Int64")
        if month_col is None:
            df["_월_"] = base_dt.dt.month.astype("Int64")

    if "_연도_" not in df.columns:
        if year_col is None:
            raise ValueError("연(연도) 컬럼을 찾을 수 없습니다.")
        y = df[year_col]
        if is_dt(y):
            y = y.dt.year
        elif is_integer_dtype(y):
            dt = _epoch_to_dt(y)
            if dt is not None:
                y = dt.dt.year
        else:
            y = pd.to_numeric(y, errors="coerce")
        df["_연도_"] = y.astype("Int64")

    if "_월_" not in df.columns:
        if month_col is None:
            raise ValueError("월 컬럼을 찾을 수 없습니다.")
        m = df[month_col]
        if is_dt(m):
            m = m.dt.month
        else:
            m = pd.to_numeric(m, errors="coerce")
        df["_월_"] = m.astype("Int64")

    # 자동매핑
    auto_map = auto_map_usage_columns(df)
    return df, auto_map

def monthly_sum(df, year, col):
    sub = df.loc[df["_연도_"] == year, ["_월_", col]].copy()
    sub[col] = pd.to_numeric(sub[col], errors="coerce")
    s = sub.groupby("_월_")[col].sum(min_count=1)
    out = pd.Series(index=range(1, 13), dtype="float64")
    out.update(s)
    return out

def build_table_for_year(df, auto_map, year: int) -> pd.DataFrame:
    base = blank_table()

    # 1) 세부 항목(취사용/개별난방/중앙난방/일반용1/일반용2/냉난방용/주한미군/BIO) 직접 채우기
    leaf_map = {
        ("가정용", "취사용"): "취사용",
        ("가정용", "개별난방"): "개별난방",
        ("가정용", "중앙난방"): "중앙난방",
        ("영업용", "일반용1"): "일반용1",
        ("업무용", "일반용2"): "일반용2",
        ("업무용", "냉난방용"): "냉난방용",
        ("업무용", "주한미군"): "주한미군",
        ("수송용", "BIO"): "BIO",
    }
    for (g, d), key in leaf_map.items():
        src = auto_map.get(key)
        if src:
            s = monthly_sum(df, year, src)
            for m in range(1, 13):
                base.loc[(base["구분"] == g) & (base["세부"] == d), f"{m}월"] = float(s[m]) if pd.notna(s[m]) else 0.0

    # 2) 합계형 라인(산업용·열병합·연료전지·자가열병합·열전용설비용·CNG) → 해당 열을 직접 매핑
    direct_groups = ["산업용", "열병합", "연료전지", "자가열병합", "열전용설비용", "CNG"]
    for g in direct_groups:
        src = auto_map.get(g)
        if src:
            s = monthly_sum(df, year, src)
            for m in range(1, 13):
                base.loc[(base["구분"] == g) & (base["세부"] == "합계"), f"{m}월"] = float(s[m]) if pd.notna(s[m]) else 0.0

    # 3) 소계/전체 합계 계산
    filled = calc_subtotals(base)
    coerce_numeric_inplace(filled)  # None → 0
    return filled

# ─────────────────────────────────────────────────────────
# 데이터 소스 선택
sb = st.sidebar
sb.header("데이터 불러오기")
src_mode = sb.radio("데이터 소스", ["리포 파일 사용", "엑셀 업로드(.xlsx)"], index=0)

if src_mode == "리포 파일 사용":
    if not os.path.exists(DEFAULT_REPO_FILE):
        st.error(f"`{DEFAULT_REPO_FILE}` 파일이 리포에 없습니다. 업로드 모드를 사용하세요.")
        st.stop()
    import openpyxl
    xls = pd.ExcelFile(DEFAULT_REPO_FILE, engine="openpyxl")
    file_name = DEFAULT_REPO_FILE
else:
    up = sb.file_uploader("엑셀 업로드(.xlsx)", type=["xlsx"])
    if not up:
        st.info("엑셀을 업로드하면 표/그래프가 표시됩니다.")
        st.stop()
    import openpyxl
    xls = pd.ExcelFile(io.BytesIO(up.getvalue()), engine="openpyxl")
    file_name = up.name

# 시트 중에서 시나리오 후보(존재하는 것만)
scenario_candidates = [s for s in ["데이터", "best", "conservative"] if s in xls.sheet_names]
if not scenario_candidates:
    scenario_candidates = [xls.sheet_names[0]]

st.caption(f"소스: {file_name}")

# 시나리오 탭(데이터 / best / conservative)
scenario_tabs = st.tabs(scenario_candidates)

for scen_idx, scen in enumerate(scenario_candidates):
    with scenario_tabs[scen_idx]:
        st.subheader(f"시나리오: {scen}")

        raw = xls.parse(scen, header=0)

        try:
            df_prepared, auto_map = prepare_df(raw)
        except Exception as e:
            st.error(f"[{scen}] 시트 처리 중 오류: {e}")
            continue

        # 자동 매핑 확인(필요 시 UI로 직접 수정 가능)
        with st.expander("자동 매핑 결과(필요시 수정)", expanded=False):
            for k in SYN.keys():
                candidates = [c for c in df_prepared.columns if likely_numeric(df_prepared[c])]
                default = auto_map.get(k)
                if default and default not in candidates:
                    candidates = [default] + candidates
                auto_map[k] = st.selectbox(k, [None] + candidates,
                                           index=(0 if default is None else ([None] + candidates).index(default)),
                                           key=f"{scen}-{k}")

        # 2024~2027 탭
        years_all = sorted(df_prepared["_연도_"].dropna().unique().tolist())
        # 4개년(2024~2027) 모두 탭으로 구성 (데이터 없으면 0으로 채워진 표)
        year_tabs = st.tabs([f"{y}년 표" for y in [2024, 2025, 2026, 2027]])
        tables = {}

        for i, y in enumerate([2024, 2025, 2026, 2027]):
            with year_tabs[i]:
                if y in years_all:
                    tbl = build_table_for_year(df_prepared, auto_map, y)
                else:
                    tbl = blank_table()
                    coerce_numeric_inplace(tbl)  # 0 채움
                    tbl = calc_subtotals(tbl)    # 형식 맞추기

                # 보기용 포맷(정수)
                view = tbl.copy()
                for c in MONTH_COLS + ["합계"]:
                    view[c] = pd.to_numeric(view[c], errors="coerce").fillna(0).round(0).astype(int)

                sty = view[ALL_COLS].style.apply(highlight_rows, axis=None)\
                    .format({c: "{:,.0f}".format for c in MONTH_COLS + ["합계"]})
                st.dataframe(sty, use_container_width=True)
                tables[y] = tbl

        # 동적 그래프
        st.subheader("월별 추이 그래프")
        groups = ["전체", "가정용", "영업용", "업무용", "산업용", "열병합", "연료전지", "자가열병합",
                  "열전용설비용", "CNG", "수송용"]
        group_sel = st.radio("보기 선택", groups, horizontal=True, index=0, key=f"grp-{scen}")

        def series_from_table(tbl: pd.DataFrame, group: str):
            if group == "전체":
                mask = tbl["구분"].ne("합계") & tbl["세부"].ne("소계") & tbl["세부"].ne("합계")
            elif group == "수송용":
                # BIO만 존재 → 소계가 총량, 그래프는 소계로 표현
                mask = (tbl["구분"] == "수송용") & tbl["세부"].eq("소계")
            else:
                # 합계 라인(산업용/열병합 등)은 '합계'를 사용
                if group in ["산업용", "열병합", "연료전지", "자가열병합", "열전용설비용", "CNG"]:
                    mask = (tbl["구분"] == group) & (tbl["세부"] == "합계")
                else:
                    mask = (tbl["구분"] == group) & tbl["세부"].ne("소계") & tbl["세부"].ne("합계")
            s = tbl.loc[mask, MONTH_COLS].apply(pd.to_numeric, errors="coerce").sum(numeric_only=True)
            return [float(s.get(f"{m}월", 0.0)) for m in range(1, 13)]

        # 그래프 데이터(선택 그룹 × 2024~2027)
        rows = []
        for y in [2024, 2025, 2026, 2027]:
            t = tables[y]
            ys = series_from_table(t, group_sel)
            for m, v in enumerate(ys, start=1):
                rows.append({"연도": str(y), "월": m, "공급량(㎥)": v})
        chart_df = pd.DataFrame(rows)

        selection = alt.selection_point(fields=["연도"], bind="legend")
        chart = (
            alt.Chart(chart_df)
            .mark_line(point=True)
            .encode(
                x=alt.X("월:O", title="월"),
                y=alt.Y("공급량(㎥):Q", title="공급량(㎥)"),
                color=alt.Color("연도:N", legend=alt.Legend(title="연도")),
                tooltip=["연도", "월", "공급량(㎥)"],
            )
            .add_params(selection)
            .transform_filter(selection)
        ).properties(width="container", height=360)
        st.altair_chart(chart, use_container_width=True)

        # 다운로드
        st.subheader("다운로드")
        c1, c2 = st.columns(2)
        with c1:
            y0 = 2024
            st.download_button(
                f"{scen} - {y0}년 표 CSV",
                data=tables[y0][ALL_COLS].to_csv(index=False).encode("utf-8-sig"),
                file_name=f"{scen}_table_{y0}.csv",
                mime="text/csv",
                key=f"csv1-{scen}",
            )
        with c2:
            st.download_button(
                f"{scen} 그래프 데이터 CSV",
                data=chart_df.to_csv(index=False).encode("utf-8-sig"),
                file_name=f"{scen}_timeseries_{group_sel}.csv",
                mime="text/csv",
                key=f"csv2-{scen}",
            )
