# app.py — 공급량 실적 및 계획 상세
# - 엑셀 스타일 표(구분/세부 × 1~12월 + 합계)
# - '영업용 소계' 제거, 소계 행 연한 하이라이트
# - 표는 편집 가능(st.data_editor) + 자동 소계/합계 계산
# - 상단 버튼(전체/용도별) → 하단 월별 추이 그래프 갱신
# - CSV 업/다운로드 지원

import io
import numpy as np
import pandas as pd
import matplotlib as mpl
import matplotlib.pyplot as plt
import streamlit as st
from pathlib import Path

# ----- 한글 폰트 -----
def set_korean_font():
    try:
        mpl.rcParams["font.family"] = "NanumGothic"
        mpl.rcParams["axes.unicode_minus"] = False
    except Exception:
        pass
set_korean_font()

st.set_page_config(page_title="공급량 실적 및 계획 상세", layout="wide")
st.title("📊 공급량 실적 및 계획 상세")

# ----- 기본 행(스크린샷 구성과 동일 / '영업용 소계' 미포함) -----
DEFAULT_ROWS = [
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

    ("합계", ""),  # 전체 합계(자동 계산)
]

MONTH_COLS = [f"{m}월" for m in range(1, 12 + 1)]
ALL_COLS = ["구분", "세부"] + MONTH_COLS + ["합계"]

# ----- 사이드바: 데이터 불러오기 -----
sb = st.sidebar
sb.header("데이터 불러오기")
mode = sb.radio("방식", ["빈 표로 시작", "CSV 업로드"], index=0, horizontal=True)
file = sb.file_uploader("CSV 업로드(구분,세부,1월~12월)", type=["csv"]) if mode == "CSV 업로드" else None

def blank_df() -> pd.DataFrame:
    df = pd.DataFrame(DEFAULT_ROWS, columns=["구분", "세부"])
    for c in MONTH_COLS:
        df[c] = np.nan
    df["합계"] = np.nan
    return df

if file:
    raw = pd.read_csv(io.BytesIO(file.getvalue()))
    # 1~12 숫자 헤더도 허용 → '월' 접미사 붙이기
    rename_map = {}
    for c in raw.columns:
        if str(c).isdigit() and 1 <= int(c) <= 12:
            rename_map[c] = f"{int(c)}월"
    raw = raw.rename(columns=rename_map)
    for c in ["구분", "세부"] + MONTH_COLS:
        if c not in raw.columns:
            raw[c] = np.nan
    df0 = raw[["구분", "세부"] + MONTH_COLS].copy()
else:
    df0 = blank_df()

st.caption("표는 직접 수정/붙여넣기 가능. 소계/합계는 자동 계산됩니다.")

# ----- 편집 가능한 표 -----
config = {
    "구분": st.column_config.TextColumn("구분", width="small"),
    "세부": st.column_config.TextColumn("세부", width="medium"),
}
for c in MONTH_COLS:
    config[c] = st.column_config.NumberColumn(c, min_value=0, step=1, width="small", help="㎥")

edited = st.data_editor(
    df0,
    num_rows="dynamic",
    column_config=config,
    hide_index=True,
    use_container_width=True,
    key="data_editor_main",
)

# ----- 계산: 소계/합계 -----
df = edited.copy()
for c in MONTH_COLS:
    df[c] = pd.to_numeric(df[c], errors="coerce")

# 행 합계
df["합계"] = df[MONTH_COLS].sum(axis=1, min_count=1)

# 그룹 소계(그룹 내에 '소계'가 있는 경우만 계산됨; '영업용'엔 소계 행이 없으므로 건너뜀)
def apply_subtotals(group: pd.DataFrame) -> pd.DataFrame:
    if "소계" in group["세부"].values:
        mask_detail = group["세부"].ne("소계") & group["세부"].ne("합계")
        sums = group.loc[mask_detail, MONTH_COLS].sum(numeric_only=True)
        group.loc[group["세부"] == "소계", MONTH_COLS] = sums.values
        group.loc[group["세부"] == "소계", "합계"] = sums.sum()
    return group

df = df.groupby("구분", group_keys=False).apply(apply_subtotals)

# 전체 합계(맨 아래 '합계' 행)
if (df["구분"] == "합계").any():
    overall_mask = df["구분"].ne("합계") & df["세부"].ne("소계") & df["세부"].ne("합계")
    overall = df.loc[overall_mask, MONTH_COLS].sum(numeric_only=True)
    df.loc[df["구분"] == "합계", MONTH_COLS] = overall.values
    df.loc[df["구분"] == "합계", "합계"] = overall.sum()

# ----- 표시 스타일(소계 연한 하이라이트) -----
def styled_dataframe(sdf: pd.DataFrame):
    sty = sdf.style
    sty = sty.set_table_styles([
        {"selector": "th.col_heading", "props": "background:#f6f6f6;"},
        {"selector": "thead th", "props": "text-align:center;"},
        {"selector": "tbody td", "props": "text-align:right;"},
    ])
    sty = sty.set_properties(subset=["구분", "세부"], **{"text-align": "left"})
    # 소계: 아주 연한 블루 (#f2f7ff)
    mask_sub = sdf["세부"].eq("소계")
    sty = sty.apply(lambda r: ["background-color:#f2f7ff" if m else "" for m in mask_sub], axis=1)
    # 전체 합계: 연한 살구색
    mask_tot = sdf["구분"].eq("합계")
    sty = sty.apply(lambda r: ["background-color:#fff3e6" if m else "" for m in mask_tot], axis=1)
    sty = sty.format({c: "{:,.0f}".format for c in MONTH_COLS + ["합계"]})
    return sty

st.subheader("3-2. 공급량 실적 및 계획 상세 (표)")
st.dataframe(styled_dataframe(df[ALL_COLS]), use_container_width=True)

# ----- 버튼(전체/용도별) & 그래프 -----
st.subheader("월별 추이 그래프")

usage_list = [u for u in df["구분"].dropna().unique().tolist() if u and u != "합계"]
# Streamlit 1.38: segmented_control 사용
selected = st.segmented_control("보기 선택", options=["전체"] + usage_list, default="전체")

def monthly_series(selection: str):
    if selection == "전체":
        mask = df["구분"].ne("합계") & df["세부"].ne("소계") & df["세부"].ne("합계")
    else:
        mask = (df["구분"] == selection) & df["세부"].ne("소계") & df["세부"].ne("합계")
    monthly = df.loc[mask, MONTH_COLS].sum(numeric_only=True)
    xs = list(range(1, 13))
    ys = [float(monthly.get(f"{m}월", 0.0)) for m in xs]
    return xs, ys

xs, ys = monthly_series(selected)

fig, ax = plt.subplots(figsize=(10, 4))
ax.plot(xs, ys, marker="o")
ax.set_xticks(xs)
ax.set_xlabel("월")
ax.set_ylabel("공급량(㎥)")
ax.set_title(f"{selected} 월별 합계 추이")
ax.grid(True, alpha=0.3)
st.pyplot(fig, use_container_width=True)

# ----- 다운로드 -----
st.subheader("다운로드")
c1, c2 = st.columns(2)
with c1:
    st.download_button(
        "현재 표 CSV 다운로드",
        data=df[ALL_COLS].to_csv(index=False).encode("utf-8-sig"),
        file_name="supply_table.csv",
        mime="text/csv",
    )
with c2:
    ts = pd.DataFrame({"월": xs, "공급량(㎥)": ys})
    st.download_button(
        "현재 그래프 데이터 CSV 다운로드",
        data=ts.to_csv(index=False).encode("utf-8-sig"),
        file_name=f"supply_timeseries_{selected}.csv",
        mime="text/csv",
    )

st.caption("Tip) 표에 값을 붙여넣기하면 소계·합계·그래프가 즉시 갱신됩니다. CSV로 저장해두면 다음에 곧바로 불러올 수 있어요.")
