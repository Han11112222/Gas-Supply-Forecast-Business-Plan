# app.py — 3-2 공급량상세 (엑셀 표 구조 그대로 읽기 + 자동 정규화 + 그래프)
# - 엑셀 다중헤더/병합 셀/왼쪽 구분영역을 그대로 표시
# - 시나리오 블록(2024 실적, 2025 계획 Normal/Best/Conservative, 2026/2027 계획) 자동 인식
# - 레포 파일/업로드 모두 지원, 사이드바에서 헤더/계층/월 열 선택 → 정규화 → 요약표/그래프

import os, io, re, hashlib
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib as mpl
import matplotlib.pyplot as plt
import streamlit as st

# -------------------- 폰트 --------------------
def set_korean_font():
    try:
        mpl.rcParams["font.family"] = "NanumGothic"
        mpl.rcParams["axes.unicode_minus"] = False
    except Exception:
        pass
set_korean_font()

st.set_page_config(page_title="3-2 공급량상세 대시보드", layout="wide")
st.title("📊 3-2 공급량상세 대시보드")
st.caption("엑셀 표 형태를 그대로 보여주고, 블록/월을 자동 인식해 정규화·요약·그래프까지 생성")

# -------------------- 로더 --------------------
@st.cache_data(show_spinner=True)
def load_excel_bytes(bytes_or_path):
    import openpyxl
    if isinstance(bytes_or_path, (str, os.PathLike)):
        xls = pd.ExcelFile(bytes_or_path, engine="openpyxl")
    else:
        xls = pd.ExcelFile(io.BytesIO(bytes_or_path), engine="openpyxl")
    return xls  # ExcelFile 그대로 반환(다양한 header로 재파싱 가능)

@st.cache_data(show_spinner=True)
def parse_sheet(xls, sheet_name: str, header_rows: int, skiprows: int):
    """
    header_rows: 1~4 범위 권장. 다중 헤더는 MultiIndex로 읽힘.
    skiprows: 헤더 이전에 건너뛸 행 수(0이면 첫 행부터 헤더 시작).
    """
    hdr = list(range(header_rows)) if header_rows > 1 else 0
    df = xls.parse(sheet_name, header=hdr, skiprows=skiprows)
    return df

# -------------------- 유틸 --------------------
def join_levels(t):
    """MultiIndex tuple에서 None/Unnamed 제거하고 ' / '로 결합"""
    parts = [str(x) for x in t if pd.notna(x)]
    parts = [p for p in parts if not str(p).lower().startswith("unnamed")]
    return " / ".join(parts) if parts else ""

def detect_month_cols(df):
    """
    열 이름(또는 MultiIndex)을 문자열로 만든 뒤 1~12 또는 '1월'~'12월'이 포함된 컬럼을 찾아
    블록별로 그룹화: {block_label: [month_cols...]}
    block_label은 상위 헤더(연도/시나리오 추정) 문자열.
    """
    month_re = re.compile(r"^(\d{1,2})(?:월)?$")
    blocks = {}
    for col in df.columns:
        # col 은 str 또는 tuple(MultiIndex)
        if isinstance(col, tuple):
            labels = [str(x) for x in col]
        else:
            labels = [str(col)]
        # 맨 마지막 레벨에서 '월' 판단
        last = labels[-1].replace(" ", "").replace("\n", "")
        last = last.replace(".0","")
        m = month_re.match(last)
        if m:
            # 상위 레벨들을 block 라벨로 사용
            block_label = join_levels(labels[:-1]).strip()
            if not block_label:
                # 상위가 비어있으면 전체 헤더 문자열을 block으로
                block_label = join_levels(labels)
            blocks.setdefault(block_label, []).append(col)
    # 월 순서 정렬(1~12)
    def month_key(c):
        last = (c[-1] if isinstance(c, tuple) else c)
        s = str(last).replace("월", "")
        try:
            return int(float(s))
        except:
            return 99
    for k in list(blocks.keys()):
        blocks[k] = sorted(blocks[k], key=month_key)
    return blocks

def extract_year_scenario(text: str):
    """
    '2024년 실적', '2025년 계획 Normal', '2025 계획 Best', '2026 계획' 등에서
    (연도, 시나리오) 추정.
    """
    y = None
    m = re.search(r"(20\d{2})", text)
    if m:
        y = int(m.group(1))
    # 시나리오 키워드
    scn = "계획"
    if "실적" in text:
        scn = "실적"
    elif re.search(r"best", text, re.I):
        scn = "Best"
    elif re.search(r"conservative", text, re.I):
        scn = "Conservative"
    elif re.search(r"normal", text, re.I):
        scn = "Normal"
    elif "계획" in text:
        scn = "계획"
    return y, scn

def tidy_from_excel_table(df, hierarchy_cols, month_blocks):
    """
    df: 표 그대로 읽은 DataFrame(MultiIndex columns 가능)
    hierarchy_cols: 왼쪽 구분/계층 열들(상위→하위 순서)
    month_blocks: {block_label: [month_cols...]} from detect_month_cols
    -> columns: 연도, 시나리오, 용도, 세부용도, 월, 공급량(㎥)
    """
    # 계층열 forward-fill
    hdf = df.copy()
    for c in hierarchy_cols:
        if c in hdf.columns:
            hdf[c] = hdf[c].ffill()
    # '삭제 대상' 행 제거 옵션: 모두 NaN이거나 '합계' 전용 행은 유지(피벗에서 유용)
    # melt 후 '소계/합계' 여부는 라벨로 사용 가능하게 둠
    out_list = []
    for block, cols in month_blocks.items():
        y, scn = extract_year_scenario(block)
        # 데이터 id_vars
        id_vars = [c for c in hierarchy_cols if c in hdf.columns]
        sub = hdf[id_vars + cols].copy()
        # 와이드 → 롱
        msub = sub.melt(id_vars=id_vars, value_vars=cols, var_name="월열", value_name="공급량(㎥)")
        # 월 변환
        def month_from_col(col):
            name = col[-1] if isinstance(col, tuple) else col
            s = str(name)
            s = s.replace("월", "").strip()
            try:
                return int(float(s))
            except:
                return None
        msub["월"] = msub["월열"].map(month_from_col).astype("Int64")
        msub.drop(columns=["월열"], inplace=True)
        # 기본 컬럼 생성
        msub["연도"] = y
        msub["시나리오"] = scn
        # 용도 / 세부용도 추출: 가장 왼쪽=대분류, 가장 오른쪽=세부
        if len(id_vars) >= 1:
            msub["용도"] = msub[id_vars[0]].astype(str)
        else:
            msub["용도"] = "미지정"
        if len(id_vars) >= 2:
            msub["세부용도"] = msub[id_vars[-1]].astype(str)
        else:
            msub["세부용도"] = "합계"
        out_list.append(msub)
    tidy = pd.concat(out_list, ignore_index=True)
    # 타입 및 정리
    tidy["공급량(㎥)"] = pd.to_numeric(tidy["공급량(㎥)"], errors="coerce")
    tidy = tidy.dropna(subset=["월","공급량(㎥)"])
    # 문자열 트리밍
    for c in ["용도","세부용도","시나리오"]:
        tidy[c] = tidy[c].astype(str).str.strip()
    return tidy

def fig_monthly_lines(df: pd.DataFrame, selected_usage: str, hue: str = "연도/시나리오"):
    fig, ax = plt.subplots(figsize=(9,4))
    for key, sub in df.groupby(hue):
        sub = sub.sort_values("월")
        ax.plot(sub["월"], sub["공급량(㎥)"], marker="o", label=str(key))
    ax.set_xlabel("월"); ax.set_ylabel("공급량(㎥)")
    ax.set_title(f"[{selected_usage}] 월별 추이")
    ax.legend(loc="best", ncol=2, fontsize=9); ax.grid(True, alpha=0.3)
    return fig

def fig_yearly_stacked(df: pd.DataFrame):
    pivot = df.pivot_table(index="연도/시나리오", columns="용도", values="공급량(㎥)", aggfunc="sum").fillna(0.0)
    fig, ax = plt.subplots(figsize=(9,4))
    bottom = np.zeros(len(pivot)); x = np.arange(len(pivot))
    for col in pivot.columns:
        ax.bar(x, pivot[col].values, bottom=bottom, label=str(col))
        bottom += pivot[col].values
    ax.set_xticks(x, pivot.index.tolist(), rotation=15, ha="right")
    ax.set_ylabel("연간 합계(㎥)"); ax.set_title("연도/시나리오별 용도 스택 합계")
    ax.legend(ncol=3, fontsize=9); ax.grid(True, axis="y", alpha=0.3)
    return fig, pivot

# -------------------- 사이드바: 데이터 불러오기 --------------------
sb = st.sidebar
sb.title("🔌 데이터 불러오기")

repo_dir = Path(__file__).parent
repo_xlsx = sorted(repo_dir.glob("*.xlsx"))
repo_csv  = sorted(repo_dir.glob("*.csv"))
has_repo_files = len(repo_xlsx) + len(repo_csv) > 0

source_options = []
if has_repo_files:
    source_options.append("레포에 있는 파일 사용")
source_options += ["엑셀 업로드(.xlsx)", "CSV 업로드(.csv)"]
src = sb.radio("데이터 소스 선택", source_options, index=0)

excelfile_obj = None
raw_df = None
sheet_name = None

if src == "레포에 있는 파일 사용":
    # 파일 선택
    files = [(p.name, p) for p in repo_xlsx] + [(p.name, p) for p in repo_csv]
    idx = sb.selectbox("📁 레포 파일", options=list(range(len(files))), format_func=lambda i: files[i][0])
    fname, fpath = files[idx]
    if str(fpath).lower().endswith(".xlsx"):
        excelfile_obj = load_excel_bytes(str(fpath))
        # 시트 선택
        sheet_name = sb.selectbox("🗂 시트", options=excelfile_obj.sheet_names,
                                  index=(excelfile_obj.sheet_names.index("3-2 공급량상세") if "3-2 공급량상세" in excelfile_obj.sheet_names else 0))
    else:
        # CSV는 바로 로드
        raw_df = pd.read_csv(str(fpath))
elif src == "엑셀 업로드(.xlsx)":
    up = sb.file_uploader("엑셀 파일 업로드", type=["xlsx"])
    if up:
        excelfile_obj = load_excel_bytes(up.getvalue())
        sheet_name = sb.selectbox("🗂 시트", options=excelfile_obj.sheet_names,
                                  index=(excelfile_obj.sheet_names.index("3-2 공급량상세") if "3-2 공급량상세" in excelfile_obj.sheet_names else 0))
else:  # CSV
    upc = sb.file_uploader("CSV 업로드", type=["csv"])
    if upc:
        raw_df = pd.read_csv(io.BytesIO(upc.getvalue()))

if excelfile_obj is None and raw_df is None:
    st.info("좌측에서 파일/시트를 선택하면 미리보기가 표시됩니다.")
    st.stop()

# -------------------- 엑셀 표 파싱 옵션 --------------------
if excelfile_obj is not None:
    sb.markdown("---")
    sb.subheader("⚙️ 엑셀 표 파싱 옵션")
    header_rows = sb.number_input("헤더 행 수(병합 제목 포함)", min_value=1, max_value=4, value=2, step=1)
    skiprows = sb.number_input("헤더 시작 전 건너뛸 행 수", min_value=0, max_value=50, value=0, step=1)
    excel_view = parse_sheet(excelfile_obj, sheet_name, header_rows=int(header_rows), skiprows=int(skiprows))
    st.subheader("엑셀 표(그대로 보기)")
    st.dataframe(excel_view, use_container_width=True)

    # 계층(구분) 열·월 블록 자동 탐지 & 선택
    # 후보: 문자열/Unnamed가 아닌 왼쪽 몇 열
    col_candidates = [c for c in excel_view.columns if (isinstance(c, tuple) and not str(c[0]).lower().startswith("unnamed")) or (isinstance(c, str) and not c.lower().startswith("unnamed"))]
    # 왼쪽 일부만 기본 선택
    default_hierarchy = []
    for c in excel_view.columns[:5]:
        if (isinstance(c, tuple) and any(pd.notna(x) for x in c) and not str(c[-1]).strip().endswith("월")) or (isinstance(c, str) and "월" not in c):
            default_hierarchy.append(c)
    sb.subheader("🧭 매핑(왼쪽 구분/계층 열, 월 열)")
    hierarchy_cols = sb.multiselect("계층(구분) 열 선택(상위→하위, 1~3개 추천)", options=list(excel_view.columns), default=default_hierarchy)
    month_blocks = detect_month_cols(excel_view)

    # 월 블록 미리보기
    if month_blocks:
        sb.caption("인식된 시나리오 블록:")
        for k, v in month_blocks.items():
            sb.write(f"- **{k}** → {len(v)}개월")
    else:
        st.warning("월(1~12/1월~12월) 열을 찾지 못했습니다. 헤더 행 수/건너뛸 행을 조정하세요.")
        st.stop()

    # 정규화
    tidy = tidy_from_excel_table(excel_view, hierarchy_cols=hierarchy_cols, month_blocks=month_blocks)

else:
    # CSV는 기존 방식 매핑으로 처리(롱형식 가정)
    st.subheader("CSV 미리보기")
    st.dataframe(raw_df.head(30), use_container_width=True)
    guess_cols = raw_df.columns.tolist()
    st.info("CSV는 연도/시나리오/용도/세부용도/월/공급량(㎥) 컬럼을 포함하는 롱형식을 권장합니다.")
    tidy = raw_df.rename(columns={"값":"공급량(㎥)"})
    if "공급량(㎥)" not in tidy.columns:
        st.stop()

# -------------------- 정규화 결과 확인 --------------------
if tidy.empty:
    st.warning("정규화 결과가 비어 있습니다. 파싱 옵션과 매핑을 조정하세요.")
    st.stop()

# 합성 키
tidy["연도/시나리오"] = tidy["연도"].astype("Int64").astype(str) + "·" + tidy["시나리오"].astype(str)

st.subheader("정규화 데이터(요약용)")
st.dataframe(tidy.head(50), use_container_width=True)

# -------------------- 필터 --------------------
st.subheader("필터")
f1, f2, f3 = st.columns(3)
with f1:
    years = sorted(tidy["연도"].dropna().unique().tolist())
    sel_years = st.multiselect("연도", years, default=years)
with f2:
    scns = tidy["시나리오"].dropna().unique().tolist()
    # 시나리오 표시 순서 고정
    order = ["실적","Normal","Best","Conservative","계획"]
    ordered = [s for s in order if s in scns] + [s for s in scns if s not in order]
    sel_scns = st.multiselect("시나리오/계획", ordered, default=ordered)
with f3:
    uses = tidy["용도"].dropna().unique().tolist()
    sel_use = st.selectbox("용도 선택(그래프 기준)", ["전체"] + uses, index=0)

view = tidy.query("연도 in @sel_years and 시나리오 in @sel_scns").copy()

# -------------------- 출력: 요약표 + 그래프 --------------------
yearly = (view.groupby(["연도/시나리오","용도"], as_index=False)["공급량(㎥)"]
          .sum()
          .sort_values(["연도/시나리오","용도"]))
st.subheader("연도/시나리오 × 용도 연간 합계(㎥)")
st.dataframe(yearly, use_container_width=True)

fig1, pivot1 = fig_yearly_stacked(view)
st.pyplot(fig1, use_container_width=True)

if sel_use == "전체":
    plot_df = (view.groupby(["연도/시나리오","월"], as_index=False)["공급량(㎥)"].sum())
    fig2 = fig_monthly_lines(plot_df, "전체(용도 합계)")
else:
    plot_df = (view.query("용도 == @sel_use")
               .groupby(["연도/시나리오","월"], as_index=False)["공급량(㎥)"].sum())
    fig2 = fig_monthly_lines(plot_df, sel_use)
st.pyplot(fig2, use_container_width=True)

# -------------------- 다운로드 --------------------
st.subheader("다운로드")
c1, c2, c3 = st.columns(3)
with c1:
    st.download_button("정규화 데이터 CSV", data=tidy.to_csv(index=False).encode("utf-8-sig"),
                       file_name="normalized_3-2_supply.csv", mime="text/csv")
with c2:
    st.download_button("연간합계 피벗 CSV", data=pivot1.reset_index().to_csv(index=False).encode("utf-8-sig"),
                       file_name="yearly_usage_pivot.csv", mime="text/csv")
with c3:
    st.download_button("현재 뷰 CSV", data=view.to_csv(index=False).encode("utf-8-sig"),
                       file_name="current_view.csv", mime="text/csv")
