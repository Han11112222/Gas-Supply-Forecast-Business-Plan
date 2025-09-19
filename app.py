# app.py — 공급량 실적 및 계획 상세 (2024~2027 / 시나리오: 데이터, best, conservative)
# - 기본 파일: 레포 루트의 "사업계획최종.xlsx" 자동 사용, 없으면 업로더 노출
# - 시트: 데이터 / best / conservative
# - 날짜/연 불일치 자동 보정(날짜 기준)
# - 명칭 교정: "주택미군"→"주한미군", "자가열병합"→"자가열전용"
# - 표 탭(2024~2027), 그래프(동적 선택), 한글 폰트(NanumGothic-Regular.ttf) 적용

import os
import io
import numpy as np
import pandas as pd
import streamlit as st
import matplotlib as mpl
import plotly.express as px
import plotly.graph_objects as go

# ───────────────────────────────────────────────────────────────────────────────
# 한글 폰트 설정 (Matplotlib/Plotly 공통)
# ───────────────────────────────────────────────────────────────────────────────
def set_korean_font():
    try:
        # 레포에 올려둔 폰트가 있으면 우선 적용
        font_path = "NanumGothic-Regular.ttf"
        if os.path.exists(font_path):
            mpl.font_manager.fontManager.addfont(font_path)
            mpl.rcParams["font.family"] = "NanumGothic"
        mpl.rcParams["axes.unicode_minus"] = False
    except Exception:
        pass

def plotly_font_layout(fig: go.Figure):
    # Plotly도 폰트 지정(없으면 시스템 폰트)
    fig.update_layout(
        font=dict(family="NanumGothic, Malgun Gothic, Apple SD Gothic Neo, Arial, sans-serif"),
        margin=dict(l=10, r=10, t=30, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0)
    )
    return fig

set_korean_font()

st.set_page_config(page_title="공급량 실적 및 계획 상세", layout="wide")
st.title("📊 공급량 실적 및 계획 상세")

# ───────────────────────────────────────────────────────────────────────────────
# 컬럼 감지/정규화 유틸
# ───────────────────────────────────────────────────────────────────────────────
def detect_year_col(cols):
    cands = [c for c in cols if str(c).strip() in ("연", "년도", "Year", "year")]
    if cands: return cands[0]
    return None

def detect_month_col(cols):
    # 월, month, 월번호
    for c in cols:
        s = str(c).strip().lower()
        if s in ("월","month","mon"): return c
    return None

def detect_date_col(cols):
    # 날짜/일자/기준일 등
    for c in cols:
        s = str(c).strip().lower()
        if any(k in s for k in ["일자","날짜","date"]):
            return c
    return None

def _extract_year_generic(series: pd.Series) -> pd.Series:
    s = series.copy()
    if pd.api.types.is_numeric_dtype(s):
        return pd.to_numeric(s, errors="coerce").astype("Int64")
    # 문자열은 숫자만 추출해 연도화
    return (
        s.astype(str)
         .str.extract(r"(\d{4})", expand=False)
         .astype("Int64")
    )

# 날짜-연 불일치 보정 포함
def prepare_df(df_in: pd.DataFrame) -> pd.DataFrame:
    df = df_in.copy()

    # 명칭 표준화 (오타/혼용 대응)
    rename_map = {
        "주택미군":"주한미군",
        "주 택 미 군":"주한미군",
        "자가열병합":"자가열전용",  # 사용자 요구: 명칭 통일
        "자가열 병합":"자가열전용",
    }
    df.columns = [rename_map.get(str(c).strip(), str(c).strip()) for c in df.columns]

    yc = detect_year_col(df.columns)
    mc = detect_month_col(df.columns)
    dc = detect_date_col(df.columns)

    dt = None
    if dc is not None:
        dt = pd.to_datetime(df[dc], errors="coerce")

    year_from_date = None
    if dt is not None:
        year_from_date = dt.dt.year.astype("Int64")

    if yc is not None:
        year_from_col = _extract_year_generic(df[yc]).astype("Int64")
    else:
        year_from_col = None

    # 둘 다 있을 때 불일치율 체크 → 10% 이상이면 날짜기준
    if (year_from_date is not None) and (year_from_col is not None):
        mask = year_from_col.notna() & year_from_date.notna()
        total = mask.sum()
        mismatch = ((year_from_col != year_from_date) & mask).sum() if total else 0
        rate = (mismatch / total) if total else 0.0
        if rate > 0.10:
            df["_연도_"] = year_from_date
            st.caption(f"⚠️ 연/날짜 불일치율 {rate:.1%} → 날짜 기준 연도로 대체했습니다.")
        else:
            df["_연도_"] = year_from_col
    else:
        df["_연도_"] = year_from_date if year_from_date is not None else year_from_col

    if df["_연도_"].isna().all():
        raise ValueError("연도 정보를 만들 수 없습니다. (연/날짜 열 확인)")

    # 월 만들기
    if mc is not None:
        m = df[mc]
        if pd.api.types.is_datetime64_any_dtype(m):
            df["_월_"] = m.dt.month.astype("Int64")
        else:
            df["_월_"] = pd.to_numeric(m, errors="coerce").round().astype("Int64")
    else:
        if dt is None:
            raise ValueError("월 정보를 만들 수 없습니다. (월/날짜 열 확인)")
        df["_월_"] = dt.dt.month.astype("Int64")

    return df

# 용도/세부 자동 매핑(열 이름을 읽어 그룹-세부 결정)
USAGE_MAP = {
    # 가정용
    "취사용": ("가정용","취사용"),
    "개별난방": ("가정용","개별난방"),
    "중앙난방": ("가정용","중앙난방"),
    "가정용소계": ("가정용","소계"), "소계(가정용)":("가정용","소계"),

    # 영업용
    "일반용1": ("영업용","일반용1"),
    "일반용2": ("영업용","일반용2"),

    # 업무용
    "냉난방용": ("업무용","냉난방용"),
    "주한미군": ("업무용","주한미군"),
    "업무용소계":("업무용","소계"), "소계(업무용)":("업무용","소계"),

    # 산업용
    "산업용": ("산업용","합계"),

    # 열/연료/자가/설비
    "열병합": ("열병합","합계"),
    "연료전지": ("연료전지","합계"),
    "자가열전용": ("자가열전용","합계"),
    "열전용설비용": ("열전용설비용","합계"),

    # CNG/수송
    "CNG": ("CNG","합계"),
    "BIO": ("수송용","BIO"),
    "수송용소계": ("수송용","소계"),
    "소계(수송용)":("수송용","소계"),

    # 총 소계
    "소계": ("총합","소계"),
}

def find_usage_columns(df: pd.DataFrame):
    cols = []
    for c in df.columns:
        name = str(c).split("(")[0].strip()  # 괄호표기 등 제거
        if name in USAGE_MAP:
            cols.append(c)
        # 가끔 공백 포함/변형
        elif name.replace(" ","") in USAGE_MAP:
            cols.append(c)
    return cols

def melt_usage(df: pd.DataFrame, usage_cols):
    # long화: [연/월/구분/세부/값]
    out = []
    for col in usage_cols:
        key = str(col).split("(")[0].strip()
        key_norm = key.replace(" ","")
        if key in USAGE_MAP:
            g, d = USAGE_MAP[key]
        elif key_norm in USAGE_MAP:
            g, d = USAGE_MAP[key_norm]
        else:
            # 미정 열은 스킵
            continue
        tmp = df[["_연도_","_월_", col]].copy()
        tmp.columns = ["연","월","값"]
        tmp["구분"] = g
        tmp["세부"] = d
        out.append(tmp)
    if not out:
        return pd.DataFrame(columns=["연","월","구분","세부","값"])
    long_df = pd.concat(out, axis=0, ignore_index=True)
    long_df["값"] = pd.to_numeric(long_df["값"], errors="coerce").fillna(0.0)
    long_df["연"] = long_df["연"].astype("Int64")
    long_df["월"] = long_df["월"].astype("Int64")
    return long_df

def pivot_year_table(long_df: pd.DataFrame, year: int):
    view = long_df[long_df["연"]==year].copy()
    if view.empty:
        # 빈그리드
        idx = pd.MultiIndex.from_product([[],[]], names=["구분","세부"])
        empty = pd.DataFrame(index=idx, columns=[f"{m}월" for m in range(1,13)]+["합계"])
        return empty

    p = view.pivot_table(
        index=["구분","세부"],
        columns="월",
        values="값",
        aggfunc="sum",
        fill_value=0.0
    ).reindex(columns=range(1,13), fill_value=0.0)

    p.columns = [f"{m}월" for m in range(1,13)]
    p["합계"] = p.sum(axis=1)
    p = p.sort_index(key=lambda s: s.map(lambda x:(x[0], _order_detail(x[1]))))
    return p

# 세부 정렬을 조금 보기 좋게
def _order_detail(name: str):
    order = {"취사용":1,"개별난방":2,"중앙난방":3,"소계":99,
             "일반용1":1,"일반용2":2,
             "냉난방용":1,"주한미군":2,
             "합계":1,"BIO":1}
    return order.get(str(name), 50)

def format_styler(df: pd.DataFrame):
    sty = df.style.format("{:,.0f}")
    # 소계/합계 행 연하게 하이라이트
    mask = df.index.get_level_values(1).astype(str).str.contains("소계|합계")
    if mask.any():
        sty = sty.set_properties(
            subset=pd.IndexSlice[mask, :],
            **{"background-color":"#f2f6ff"}
        )
    return sty

# ───────────────────────────────────────────────────────────────────────────────
# 데이터 입력부
# ───────────────────────────────────────────────────────────────────────────────
DEFAULT_FILE = "사업계획최종.xlsx"

left, right = st.columns([1,3])
with left:
    st.subheader("데이터 불러오기", divider="gray")
    src_mode = "리포 파일 사용" if os.path.exists(DEFAULT_FILE) else "엑셀 업로드(.xlsx)"
    st.caption(f"소스: **{DEFAULT_FILE}** 존재" if os.path.exists(DEFAULT_FILE) else "소스: 파일 업로드 필요")

    up = None
    if not os.path.exists(DEFAULT_FILE):
        up = st.file_uploader("엑셀 업로드", type=["xlsx"], label_visibility="collapsed")

# 엑셀 로드
@st.cache_data(show_spinner=True)
def load_excel_bytes(b: bytes) -> dict:
    xls = pd.ExcelFile(io.BytesIO(b))
    return {sn: xls.parse(sn) for sn in xls.sheet_names}

@st.cache_data(show_spinner=True)
def load_excel_path(path: str) -> dict:
    xls = pd.ExcelFile(path)
    return {sn: xls.parse(sn) for sn in xls.sheet_names}

if os.path.exists(DEFAULT_FILE):
    sheets = load_excel_path(DEFAULT_FILE)
elif up is not None:
    sheets = load_excel_bytes(up.getvalue())
else:
    st.stop()

# 시나리오 선택(데이터 / best / conservative 중 있는 것만)
avail_sheets = [s for s in ["데이터","best","conservative"] if s in sheets]
if not avail_sheets:
    st.error("엑셀에 '데이터' 또는 'best'/'conservative' 시트가 없습니다.")
    st.stop()

scenario = st.segmented_control(
    "시나리오", options=avail_sheets, default=avail_sheets[0]
)

# 표시는 우측
with right:
    st.caption(f"시트: **{scenario}**")

# 데이터 준비
try:
    raw = sheets[scenario]
    df_base = prepare_df(raw)
except Exception as e:
    st.exception(e)
    st.stop()

usage_cols = find_usage_columns(df_base)
if not usage_cols:
    st.warning("용도(열) 후보를 찾지 못했습니다. 열 이름을 확인해 주세요.")
    st.dataframe(df_base.head())
    st.stop()

long_all = melt_usage(df_base, usage_cols)

# 그래프 선택 옵션(좌측)
with left:
    st.subheader("보기 선택", divider="gray")
    # 연도 멀티선택(기본 2024~2027)
    years_all = sorted(long_all["연"].dropna().unique().tolist())
    years_keep = [y for y in [2024,2025,2026,2027] if y in years_all] or years_all
    pick_years = st.multiselect("연도", years_all, default=years_keep)

    # 용도 선택
    usage_groups = ["전체","가정용","영업용","업무용","산업용","열병합","연료전지","자가열전용","열전용설비용","CNG","수송용"]
    pick_usage = st.selectbox("용도", usage_groups, index=0)

# ───────────────────────────────────────────────────────────────────────────────
# 탭(연도별 표) + 동적 그래프
# ───────────────────────────────────────────────────────────────────────────────
st.subheader("시나리오: 데이터", divider="gray")

tabs = st.tabs([f"{y}년 표" for y in [2024,2025,2026,2027]])

for i, y in enumerate([2024,2025,2026,2027]):
    with tabs[i]:
        pvt = pivot_year_table(long_all, y)

        if pvt.empty:
            st.write(f"**{y}년 데이터가 없습니다.**")
        else:
            st.dataframe(format_styler(pvt), use_container_width=True)

# ───────────────────────────────────────────────────────────────────────────────
# 동적 라인 차트
# ───────────────────────────────────────────────────────────────────────────────
st.subheader("월별 추이 그래프", divider=True)

chart_df = long_all.copy()
if pick_usage != "전체":
    chart_df = chart_df[chart_df["구분"]==pick_usage]

if pick_years:
    chart_df = chart_df[chart_df["연"].isin(pick_years)]

# 월 합계 (연/월/구분)
agg = (chart_df
       .groupby(["연","월","구분"], as_index=False)["값"].sum()
       .sort_values(["연","월"]))

if agg.empty:
    st.info("선택한 조건에 해당하는 데이터가 없습니다.")
else:
    title = f"{'·'.join(map(str,pick_years))}년 / {pick_usage} 월별 추이"
    fig = px.line(
        agg, x="월", y="값", color="연",
        markers=True,
        title=title,
        labels={"월":"월","값":"공급량(㎥)"}
    )
    fig.update_xaxes(dtick=1, range=[0.9,12.1])
    fig = plotly_font_layout(fig)
    st.plotly_chart(fig, use_container_width=True)

# ───────────────────────────────────────────────────────────────────────────────
# 다운로드(원본 및 가공 데이터)
# ───────────────────────────────────────────────────────────────────────────────
with st.expander("데이터 다운로드"):
    c1, c2 = st.columns(2)
    with c1:
        # 정규화 long csv
        csv_long = long_all.to_csv(index=False).encode("utf-8-sig")
        st.download_button("정규화 데이터(CSV)", csv_long, file_name=f"normalized_{scenario}.csv", mime="text/csv")
    with c2:
        # 연도별 피벗 합본
        merged = []
        for y in [2024,2025,2026,2027]:
            p = pivot_year_table(long_all, y)
            if not p.empty:
                t = p.copy()
                t.insert(0, "연", y)
                t = t.reset_index()
                merged.append(t)
        if merged:
            out = pd.concat(merged, ignore_index=True)
            csv = out.to_csv(index=False).encode("utf-8-sig")
            st.download_button("연도별 피벗 합본(CSV)", csv, file_name=f"pivot_{scenario}.csv", mime="text/csv")
        else:
            st.caption("내려 받을 피벗 데이터가 없습니다.")
