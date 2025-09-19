# app.py — 공급량 실적 및 계획 상세
# - 엑셀처럼 보이는 표(구분/세부 × 1~12월 + 합계)를 화면에 구성
# - 표는 편집 가능(st.data_editor); 합계/소계/전체합계 자동계산
# - 위쪽 버튼: [전체] + 각 용도(구분)별 토글 → 아래 동적 그래프 갱신
# - 선택: CSV 업로드/다운로드

import io
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib as mpl
import matplotlib.pyplot as plt
import streamlit as st

# ---------- 한글 폰트 ----------
def set_korean_font():
    try:
        mpl.rcParams["font.family"] = "NanumGothic"
        mpl.rcParams["axes.unicode_minus"] = False
    except Exception:
        pass
set_korean_font()

st.set_page_config(page_title="공급량 실적 및 계획 상세", layout="wide")
st.title("📊 공급량 실적 및 계획 상세")

# ---------- 기본 구조(행 템플릿) ----------
# 필요하면 여기서 기본 행을 더 넣거나 이름을 바꿔도 된다.
DEFAULT_ROWS = [
    # 구분, 세부
    ("가정용", "취사용"),
    ("가정용", "개별난방"),
    ("가정용", "중앙난방"),
    ("가정용", "소계"),
    ("영업용", "일반용1"),
    ("영업용", "소계"),
    ("업무용", "일반용2"),
    ("업무용", "냉난방용"),
    ("업무용", "주택미급"),   # 필요 시 변경
    ("업무용", "소계"),
    ("산업용", "합계"),        # 산업용은 단일행이면 '합계'로 두면 편함
    ("열병합", "합계"),
    ("연료전지", "합계"),
    ("자가열병합", "합계"),
    ("열전용설비용", "합계"),
    ("CNG", "합계"),
    ("수송용", "BIO"),        # 예시
    ("수송용", "소계"),
    ("합계", ""),             # 맨 아래 전체 합계(자동계산 전용)
]

MONTH_COLS = [f"{m}월" for m in range(1, 13)]
ALL_COLS = ["구분", "세부"] + MONTH_COLS + ["합계"]

# ---------- 사이드바: 데이터 불러오기 ----------
sb = st.sidebar
sb.header("데이터 불러오기")

mode = sb.radio("방식", ["빈 표로 시작", "CSV 업로드"], index=0, horizontal=True)
if mode == "CSV 업로드":
    up = sb.file_uploader("CSV 업로드(구분,세부,1월~12월 형식)", type=["csv"])
else:
    up = None

def blank_df():
    df = pd.DataFrame(DEFAULT_ROWS, columns=["구분", "세부"])
    for c in MONTH_COLS:
        df[c] = np.nan
    df["합계"] = np.nan
    return df

if up:
    raw = pd.read_csv(io.BytesIO(up.getvalue()))
    # 컬럼 보정: 1~12 숫자만 있으면 "월" 붙이기
    rename_map = {}
    for c in raw.columns:
        if str(c).isdigit() and 1 <= int(c) <= 12:
            rename_map[c] = f"{int(c)}월"
    raw = raw.rename(columns=rename_map)
    # 누락 컬럼 보정
    for c in ["구분", "세부"] + MONTH_COLS:
        if c not in raw.columns:
            raw[c] = np.nan
    df0 = raw[["구분", "세부"] + MONTH_COLS].copy()
else:
    df0 = blank_df()

st.caption("아래 표는 직접 수정/붙여넣기가 가능하다. 소계/합계는 자동 계산된다.")

# ---------- 편집 가능한 표 ----------
config = {
    "구분": st.column_config.TextColumn("구분", width="small"),
    "세부": st.column_config.TextColumn("세부", width="medium"),
}
for c in MONTH_COLS:
    config[c] = st.column_config.NumberColumn(c, min_value=0, step=1, width="small", help="㎥")

edited = st.data_editor(
    df0,
    num_rows="dynamic",            # 행 추가 가능
    column_config=config,
    hide_index=True,
    use_container_width=True,
    key="data_editor_main",
)

# ---------- 계산 로직: 소계/합계 ----------
df = edited.copy()

# 타입 정리(숫자)
for c in MONTH_COLS:
    df[c] = pd.to_numeric(df[c], errors="coerce")

# 각 행 합계
df["합계"] = df[MONTH_COLS].sum(axis=1, min_count=1)

# 그룹별 소계 자동계산: 세부 == '소계' 인 행에 같은 '구분'의 일반행을 합산
def apply_subtotals(d):
    if "소계" in d["세부"].values:
        mask_detail = d["세부"].ne("소계") & d["세부"].ne("합계")
        sums = d.loc[mask_detail, MONTH_COLS].sum(numeric_only=True)
        d.loc[d["세부"] == "소계", MONTH_COLS] = sums.values
        d.loc[d["세부"] == "소계", "합계"] = sums.sum()
    return d

df = df.groupby("구분", group_keys=False).apply(apply_subtotals)

# 맨 아래 전체 합계 행 자동계산(구분=='합계' 한 행이 있다고 가정)
if (df["구분"] == "합계").any():
    overall_mask = df["구분"].ne("합계") & df["세부"].ne("소계") & df["세부"].ne("합계")
    overall = df.loc[overall_mask, MONTH_COLS].sum(numeric_only=True)
    df.loc[df["구분"] == "합계", MONTH_COLS] = overall.values
    df.loc[df["구분"] == "합계", "합계"] = overall.sum()

# ---------- 표시용 스타일 ----------
view = df.copy()

# 보기 좋게: 소계/합계 행 강조
def styler(sdf: pd.DataFrame):
    sty = sdf.style
    # 헤더줄 배경
    sty = sty.set_table_styles([
        {"selector": "th.col_heading", "props": "background:#f6f6f6;"},
        {"selector": "thead th", "props": "text-align:center;"},
        {"selector": "tbody td", "props": "text-align:right;"},
    ])
    # 좌측 텍스트 정렬
    sty = sty.set_properties(subset=["구분","세부"], **{"text-align":"left"})
    # 소계 행
    mask_sub = sdf["세부"].eq("소계")
    sty = sty.apply(lambda r: ["background-color:#eef5ff" if m else "" for m in mask_sub], axis=1)
    # 전체 합계 행
    mask_tot = sdf["구분"].eq("합계")
    sty = sty.apply(lambda r: ["background-color:#fdebd3" if m else "" for m in mask_tot], axis=1)
    # 숫자 포맷
    sty = sty.format({c: "{:,.0f}".format for c in MONTH_COLS + ["합계"]})
    return sty

st.subheader("3-2. 공급량 실적 및 계획 상세 (표)")
st.dataframe(styler(view), use_container_width=True)

# ---------- 버튼(전체/용도별) & 동적 그래프 ----------
st.subheader("월별 추이 그래프")

# 용도(구분) 목록
usage_list = [u for u in view["구분"].dropna().unique().tolist() if u and u != "합계"]
usage_list_sorted = sorted(usage_list, key=lambda x: usage_list.index(x))  # 원래 순서 유지 느낌

# 버튼 UI (Streamlit 1.38의 segmented_control 사용)
selected = st.segmented_control("보기 선택", options=["전체"] + usage_list_sorted, default="전체")

def monthly_series_for(selection: str):
    if selection == "전체":
        mask = view["구분"].ne("합계") & view["세부"].ne("소계") & view["세부"].ne("합계")
    else:
        mask = (view["구분"] == selection) & view["세부"].ne("소계") & view["세부"].ne("합계")
    monthly = view.loc[mask, MONTH_COLS].sum(numeric_only=True)
    # x: 1..12, y: values
    xs = list(range(1, 13))
    ys = [float(monthly.get(f"{m}월", 0.0)) for m in xs]
    return xs, ys

xs, ys = monthly_series_for(selected)

# matplotlib 라인 차트(지침: 색상 지정 금지)
fig, ax = plt.subplots(figsize=(10,4))
ax.plot(xs, ys, marker="o")
ax.set_xticks(xs)
ax.set_xlabel("월")
ax.set_ylabel("공급량(㎥)")
ax.set_title(f"{selected} 월별 합계 추이")
ax.grid(True, alpha=0.3)
st.pyplot(fig, use_container_width=True)

# ---------- 다운로드 ----------
st.subheader("다운로드")
c1, c2 = st.columns(2)
with c1:
    st.download_button(
        "현재 표 CSV 다운로드",
        data=view[ALL_COLS].to_csv(index=False).encode("utf-8-sig"),
        file_name="supply_table.csv",
        mime="text/csv",
    )
with c2:
    # 그래프용 월별 시계열 CSV (선택 대상 기준)
    ts_df = pd.DataFrame({"월": xs, "공급량(㎥)": ys})
    st.download_button(
        "현재 그래프 데이터 CSV 다운로드",
        data=ts_df.to_csv(index=False).encode("utf-8-sig"),
        file_name=f"supply_timeseries_{selected}.csv",
        mime="text/csv",
    )

st.caption("Tip: 표에서 값을 붙여넣기하면 합계/소계/그래프가 즉시 갱신된다. CSV로 저장해두면 다음에 업로드해서 이어서 편집 가능.")
