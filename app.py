# app.py — 도시가스 공급량 사업계획(3-2 공급량상세) 대시보드
# - 파일: 업로드(.xlsx/.csv)만 사용 (샘플 분기 제거)
# - 시트: 엑셀은 "3-2 공급량상세"를 우선 선택(있을 경우)
# - 컬럼 매핑 UI로 정규화 → 요약표 + 동적 그래프

import os, io, hashlib
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib as mpl
import matplotlib.pyplot as plt
import streamlit as st

# ───────── 한글 폰트 ─────────
def set_korean_font():
    try:
        mpl.rcParams["font.family"] = "NanumGothic"
        mpl.rcParams["axes.unicode_minus"] = False
    except Exception:
        pass

set_korean_font()

st.set_page_config(page_title="3-2 공급량상세 대시보드", layout="wide")
st.title("📊 3-2 공급량상세 대시보드")
st.caption("연도·시나리오·용도별 요약표와 동적 그래프 · 업로드 데이터 사용")

# ───────── 유틸 ─────────
@st.cache_data(show_spinner=False)
def file_bytes_digest(b: bytes) -> str:
    return hashlib.md5(b).hexdigest()

@st.cache_data(show_spinner=True)
def load_excel(bytes_or_path) -> dict:
    """엑셀 전체 시트 로드 → dict[str, DataFrame]"""
    import openpyxl  # ensure engine
    if isinstance(bytes_or_path, (str, os.PathLike)):
        xls = pd.ExcelFile(bytes_or_path, engine="openpyxl")
    else:
        xls = pd.ExcelFile(io.BytesIO(bytes_or_path), engine="openpyxl")
    return {sn: xls.parse(sn) for sn in xls.sheet_names}

@st.cache_data(show_spinner=True)
def load_csv(bytes_or_path) -> pd.DataFrame:
    if isinstance(bytes_or_path, (str, os.PathLike)):
        return pd.read_csv(bytes_or_path)
    else:
        return pd.read_csv(io.BytesIO(bytes_or_path))

def try_autodetect_columns(df: pd.DataFrame):
    cols = df.columns.astype(str).tolist()
    guess = {"연도":None,"시나리오":None,"용도":None,"세부용도":None,"월":None,"값":None,"wide_months":[]}
    for c in cols:
        lc = c.lower()
        if guess["연도"] is None and ("연도" in c or "year" in lc):
            guess["연도"] = c
        if guess["용도"] is None and ("용도" in c or "segment" in lc or "usage" in lc):
            guess["용도"] = c
        if guess["시나리오"] is None and ("시나리오" in c or "계획" in c or "scenario" in lc):
            guess["시나리오"] = c
        if guess["세부용도"] is None and ("세부" in c or "소계" in c or "소분류" in c or "세분류" in c or "detail" in lc or "subcategory" in lc):
            guess["세부용도"] = c
        if guess["월"] is None and (c == "월" or "month" in lc):
            guess["월"] = c
        if guess["값"] is None and (c in ["공급량","공급량(㎥)","값","수량","value"] or "공급" in c):
            guess["값"] = c
    # 1~12 또는 '1월'~'12월' 와이드 형태 감지
    for c in cols:
        s = c.replace("월","")
        if s.isdigit():
            m = int(s)
            if 1 <= m <= 12:
                guess["wide_months"].append(c)
        elif c.isdigit():
            m = int(c)
            if 1 <= m <= 12:
                guess["wide_months"].append(c)
    return guess

def melt_month_wide(df, id_vars, month_cols):
    tmp = df.melt(id_vars=id_vars, value_vars=month_cols, var_name="월", value_name="공급량(㎥)")
    tmp["월"] = tmp["월"].astype(str).str.replace("월","",regex=False)
    tmp["월"] = pd.to_numeric(tmp["월"], errors="coerce").astype("Int64")
    return tmp

def normalize_df(df: pd.DataFrame, mapping: dict) -> pd.DataFrame:
    df = df.copy()
    if mapping.get("wide_months"):
        id_vars = [c for c in [mapping.get("연도"), mapping.get("시나리오"), mapping.get("용도"), mapping.get("세부용도")] if c]
        ndf = melt_month_wide(df, id_vars=id_vars, month_cols=mapping["wide_months"])
    else:
        ndf = pd.DataFrame({
            "연도": df[mapping["연도"]] if mapping.get("연도") else np.nan,
            "시나리오": df[mapping["시나리오"]] if mapping.get("시나리오") else "미지정",
            "용도": df[mapping["용도"]] if mapping.get("용도") else "미지정",
            "세부용도": df[mapping["세부용도"]] if mapping.get("세부용도") else "합계",
            "월": df[mapping["월"]] if mapping.get("월") else np.nan,
            "공급량(㎥)": df[mapping["값"]] if mapping.get("값") else np.nan,
        })
    # 타입 정리
    ndf["연도"] = pd.to_numeric(ndf["연도"], errors="coerce").astype("Int64")
    ndf["월"] = pd.to_numeric(ndf["월"], errors="coerce").astype("Int64")
    ndf["시나리오"] = ndf["시나리오"].fillna("미지정").astype(str)
    ndf["용도"] = ndf["용도"].fillna("미지정").astype(str)
    ndf["세부용도"] = ndf["세부용도"].fillna("합계").astype(str)
    ndf["공급량(㎥)"] = pd.to_numeric(ndf["공급량(㎥)"], errors="coerce")
    ndf = ndf.dropna(subset=["연도","월","공급량(㎥)"])
    return ndf

def fig_monthly_lines(df: pd.DataFrame, selected_usage: str, hue: str = "연도/시나리오"):
    fig, ax = plt.subplots(figsize=(9,4))
    for key, sub in df.groupby(hue):
        sub = sub.sort_values("월")
        ax.plot(sub["월"], sub["공급량(㎥)"], marker="o", label=str(key))
    ax.set_xlabel("월")
    ax.set_ylabel("공급량(㎥)")
    ax.set_title(f"[{selected_usage}] 월별 추이")
    ax.legend(loc="best", ncol=2, fontsize=9)
    ax.grid(True, alpha=0.3)
    return fig

def fig_yearly_stacked(df: pd.DataFrame):
    pivot = df.pivot_table(index="연도/시나리오", columns="용도", values="공급량(㎥)", aggfunc="sum").fillna(0.0)
    fig, ax = plt.subplots(figsize=(9,4))
    bottom = np.zeros(len(pivot))
    x = np.arange(len(pivot))
    for col in pivot.columns:
        ax.bar(x, pivot[col].values, bottom=bottom, label=str(col))
        bottom += pivot[col].values
    ax.set_xticks(x, pivot.index.tolist(), rotation=15, ha="right")
    ax.set_ylabel("연간 합계(㎥)")
    ax.set_title("연도/시나리오별 용도 스택 합계")
    ax.legend(ncol=3, fontsize=9)
    ax.grid(True, axis="y", alpha=0.3)
    return fig, pivot

# ───────── 파일 입력 (업로드 전용) ─────────
left, right = st.columns([1,2])
with left:
    src = st.radio("데이터 소스 선택", ["엑셀 업로드(.xlsx)", "CSV 업로드(.csv)"], index=0, horizontal=False)

raw, sheet_name = None, None

if src == "엑셀 업로드(.xlsx)":
    up = st.file_uploader("엑셀 파일 업로드", type=["xlsx"])
    if up:
        sheets = load_excel(up.getvalue())
        # 3-2 시트가 있으면 우선 선택
        names = list(sheets.keys())
        idx = names.index("3-2 공급량상세") if "3-2 공급량상세" in names else 0
        sheet_name = st.selectbox("시트 선택", options=names, index=idx)
        raw = sheets[sheet_name]

elif src == "CSV 업로드(.csv)":
    upc = st.file_uploader("CSV 업로드", type=["csv"])
    if upc:
        raw = load_csv(upc.getvalue())

if raw is None:
    st.info("파일을 업로드하면 미리보기가 나타납니다.")
    st.stop()

# ───────── 컬럼 매핑 ─────────
st.subheader("데이터 미리보기")
st.dataframe(raw.head(30), use_container_width=True)

guess = try_autodetect_columns(raw)
with st.expander("컬럼 매핑 (필요시 수정)", expanded=True):
    c1, c2 = st.columns(2)
    with c1:
        col_year = st.selectbox("연도 열", [None] + raw.columns.tolist(), index=(raw.columns.tolist().index(guess["연도"]) + 1) if guess["연도"] in raw.columns else 0)
        col_scn  = st.selectbox("시나리오/계획 구분 열", [None] + raw.columns.tolist(), index=(raw.columns.tolist().index(guess["시나리오"]) + 1) if guess["시나리오"] in raw.columns else 0)
        col_use  = st.selectbox("용도 열", [None] + raw.columns.tolist(), index=(raw.columns.tolist().index(guess["용도"]) + 1) if guess["용도"] in raw.columns else 0)
    with c2:
        col_sub   = st.selectbox("세부용도 열(선택)", [None] + raw.columns.tolist(), index=(raw.columns.tolist().index(guess["세부용도"]) + 1) if guess["세부용도"] in raw.columns else 0)
        col_month = st.selectbox("월 열(롱형식일 때)", [None] + raw.columns.tolist(), index=(raw.columns.tolist().index(guess["월"]) + 1) if guess["월"] in raw.columns else 0)
        col_val   = st.selectbox("값/공급량 열(롱형식일 때)", [None] + raw.columns.tolist(), index=(raw.columns.tolist().index(guess["값"]) + 1) if guess["값"] in raw.columns else 0)

    wide_months = st.multiselect(
        "와이드(1~12월) 열들 선택 — 열에 '1'~'12' 또는 '1월'~'12월'",
        options=raw.columns.tolist(),
        default=[c for c in (guess["wide_months"] or []) if c in raw.columns],
    )

mapping = {
    "연도": col_year,
    "시나리오": col_scn,
    "용도": col_use,
    "세부용도": col_sub,
    "월": col_month,
    "값": col_val,
    "wide_months": wide_months,
}

# 정규화
tidy = normalize_df(raw, mapping)
if tidy.empty:
    st.warning("정규화된 데이터가 비어 있습니다. 컬럼 매핑을 확인하세요.")
    st.stop()

# 합성 키
tidy["연도/시나리오"] = tidy["연도"].astype(str) + "·" + tidy["시나리오"].astype(str)

# 필터
st.subheader("필터")
f1, f2, f3 = st.columns(3)
with f1:
    years = sorted(tidy["연도"].dropna().unique().tolist())
    sel_years = st.multiselect("연도", years, default=[y for y in years if y in [2024,2025,2026,2027]] or years)
with f2:
    scns = tidy["시나리오"].dropna().unique().tolist()
    default_scns = [s for s in scns if s in ["실적","Normal","Best","Conservative","계획"]] or scns
    sel_scns = st.multiselect("시나리오/계획", scns, default=default_scns)
with f3:
    uses = tidy["용도"].dropna().unique().tolist()
    sel_use = st.selectbox("용도 선택(그래프 기준)", ["전체"] + uses, index=0)

view = tidy.query("연도 in @sel_years and 시나리오 in @sel_scns").copy()

# 요약표 — (연도/시나리오 × 용도) 연간 합계
yearly = (view.groupby(["연도/시나리오","용도"], as_index=False)["공급량(㎥)"]
          .sum()
          .sort_values(["연도/시나리오","용도"]))
st.subheader("연도/시나리오 × 용도 연간 합계(㎥)")
st.dataframe(yearly, use_container_width=True)

# 스택 바
fig1, pivot1 = fig_yearly_stacked(view)
st.pyplot(fig1, use_container_width=True)

# 월별 추이 (선택 용도)
if sel_use == "전체":
    plot_df = (view.groupby(["연도/시나리오","월"], as_index=False)["공급량(㎥)"].sum())
    fig2 = fig_monthly_lines(plot_df, "전체(용도 합계)")
else:
    plot_df = (view.query("용도 == @sel_use")
               .groupby(["연도/시나리오","월"], as_index=False)["공급량(㎥)"].sum())
    fig2 = fig_monthly_lines(plot_df, sel_use)
st.pyplot(fig2, use_container_width=True)

# 다운로드
st.subheader("다운로드")
c1, c2, c3 = st.columns(3)
with c1:
    st.download_button(
        "정규화 데이터 CSV 다운로드",
        data=tidy.to_csv(index=False).encode("utf-8-sig"),
        file_name="normalized_3-2_supply.csv",
        mime="text/csv"
    )
with c2:
    st.download_button(
        "연간합계 피벗 CSV 다운로드",
        data=pivot1.reset_index().to_csv(index=False).encode("utf-8-sig"),
        file_name="yearly_usage_pivot.csv",
        mime="text/csv"
    )
with c3:
    st.download_button(
        "현재 뷰 CSV 다운로드",
        data=view.to_csv(index=False).encode("utf-8-sig"),
        file_name="current_view.csv",
        mime="text/csv"
    )
