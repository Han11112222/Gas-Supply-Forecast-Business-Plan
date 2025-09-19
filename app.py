# app.py — 3-2 공급량상세 (엑셀 표 구조 그대로 + 자동 정규화 + 그래프)
# - 사이드바: 데이터 소스 선택 → 레포 파일/업로드 → 시트 선택
# - 캐시 직렬화 이슈 해결: 캐시는 bytes/DataFrame만 사용

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
st.caption("엑셀 표 형태 그대로 표시 → 월/블록 자동 인식 → 정규화·요약·그래프")

# -------------------- 캐시 가능한 유틸 --------------------
@st.cache_data(show_spinner=False)
def file_bytes_digest(b: bytes) -> str:
    return hashlib.md5(b).hexdigest()

@st.cache_data(show_spinner=True)
def read_file_bytes(path_str: str) -> bytes:
    """레포 파일을 bytes로 읽어 캐시에 저장"""
    return Path(path_str).read_bytes()

@st.cache_data(show_spinner=True)
def parse_sheet_from_bytes(excel_bytes: bytes, sheet_name: str, header_rows: int, skiprows: int) -> pd.DataFrame:
    """엑셀 bytes → ExcelFile → 지정 시트 DataFrame 반환(직렬화 가능)"""
    import openpyxl  # engine
    xls = pd.ExcelFile(io.BytesIO(excel_bytes), engine="openpyxl")
    hdr = list(range(header_rows)) if header_rows > 1 else 0
    df = xls.parse(sheet_name, header=hdr, skiprows=skiprows)
    return df

# -------------------- 파싱/정규화 유틸 --------------------
def join_levels(t):
    parts = [str(x) for x in t if pd.notna(x)]
    parts = [p for p in parts if not str(p).lower().startswith("unnamed")]
    return " / ".join(parts) if parts else ""

def detect_month_cols(df: pd.DataFrame):
    month_re = re.compile(r"^(\d{1,2})(?:월)?$")
    blocks = {}
    for col in df.columns:
        labels = list(col) if isinstance(col, tuple) else [str(col)]
        last = str(labels[-1]).replace(" ", "").replace("\n", "").replace(".0", "")
        m = month_re.match(last)
        if m:
            block_label = join_levels(labels[:-1]).strip()
            if not block_label:
                block_label = join_levels(labels)
            blocks.setdefault(block_label, []).append(col)

    def month_key(c):
        last = c[-1] if isinstance(c, tuple) else c
        s = str(last).replace("월", "")
        try:
            return int(float(s))
        except:
            return 99

    for k in list(blocks.keys()):
        blocks[k] = sorted(blocks[k], key=month_key)
    return blocks

def extract_year_scenario(text: str):
    y = None
    m = re.search(r"(20\d{2})", text)
    if m:
        y = int(m.group(1))
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

def tidy_from_excel_table(df: pd.DataFrame, hierarchy_cols, month_blocks):
    hdf = df.copy()
    for c in hierarchy_cols:
        if c in hdf.columns:
            hdf[c] = hdf[c].ffill()

    out = []
    for block, cols in month_blocks.items():
        y, scn = extract_year_scenario(block)
        id_vars = [c for c in hierarchy_cols if c in hdf.columns]
        sub = hdf[id_vars + cols].copy()
        msub = sub.melt(id_vars=id_vars, value_vars=cols, var_name="월열", value_name="공급량(㎥)")

        def month_from_col(col):
            name = col[-1] if isinstance(col, tuple) else col
            s = str(name).replace("월", "").strip()
            try:
                return int(float(s))
            except:
                return None

        msub["월"] = msub["월열"].map(month_from_col).astype("Int64")
        msub.drop(columns=["월열"], inplace=True)
        msub["연도"] = y
        msub["시나리오"] = scn
        msub["용도"] = msub[id_vars[0]].astype(str) if len(id_vars) >= 1 else "미지정"
        msub["세부용도"] = msub[id_vars[-1]].astype(str) if len(id_vars) >= 2 else "합계"
        out.append(msub)

    tidy = pd.concat(out, ignore_index=True)
    tidy["공급량(㎥)"] = pd.to_numeric(tidy["공급량(㎥)"], errors="coerce")
    tidy = tidy.dropna(subset=["월", "공급량(㎥)"])
    for c in ["용도", "세부용도", "시나리오"]:
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

excel_bytes = None
csv_df = None
sheet_name = None

if src == "레포에 있는 파일 사용":
    files = [(p.name, str(p)) for p in repo_xlsx] + [(p.name, str(p)) for p in repo_csv]
    idx = sb.selectbox("📁 레포 파일", options=list(range(len(files))), format_func=lambda i: files[i][0])
    fname, fpath = files[idx]
    if fname.lower().endswith(".xlsx"):
        excel_bytes = read_file_bytes(fpath)  # bytes 캐시에 저장 OK
        # 시트 목록 얻기 위해 임시 ExcelFile
        import openpyxl
        xls_tmp = pd.ExcelFile(io.BytesIO(excel_bytes), engine="openpyxl")
        sheet_name = sb.selectbox(
            "🗂 시트",
            options=xls_tmp.sheet_names,
            index=(xls_tmp.sheet_names.index("3-2 공급량상세") if "3-2 공급량상세" in xls_tmp.sheet_names else 0),
        )
    else:
        csv_df = pd.read_csv(fpath)

elif src == "엑셀 업로드(.xlsx)":
    up = sb.file_uploader("엑셀 파일 업로드", type=["xlsx"])
    if up:
        excel_bytes = up.getvalue()
        import openpyxl
        xls_tmp = pd.ExcelFile(io.BytesIO(excel_bytes), engine="openpyxl")
        sheet_name = sb.selectbox(
            "🗂 시트",
            options=xls_tmp.sheet_names,
            index=(xls_tmp.sheet_names.index("3-2 공급량상세") if "3-2 공급량상세" in xls_tmp.sheet_names else 0),
        )

else:  # CSV 업로드
    upc = sb.file_uploader("CSV 업로드", type=["csv"])
    if upc:
        csv_df = pd.read_csv(io.BytesIO(upc.getvalue()))

if excel_bytes is None and csv_df is None:
    st.info("좌측에서 **데이터 소스 선택 → 파일/시트**를 지정하세요.")
    st.stop()

# -------------------- 엑셀 표 파싱 옵션 --------------------
if excel_bytes is not None:
    sb.markdown("---")
    sb.subheader("⚙️ 엑셀 표 파싱 옵션")
    header_rows = sb.number_input("헤더 행 수(병합 제목 포함)", min_value=1, max_value=4, value=2, step=1)
    skiprows = sb.number_input("헤더 시작 전 건너뛸 행 수", min_value=0, max_value=50, value=0, step=1)

    excel_view = parse_sheet_from_bytes(excel_bytes, sheet_name, int(header_rows), int(skiprows))
    st.subheader("엑셀 표(그대로 보기)")
    st.dataframe(excel_view, use_container_width=True)

    # 계층 후보 자동 추천
    default_hierarchy = []
    for c in excel_view.columns[:5]:
        if (isinstance(c, tuple) and any(pd.notna(x) for x in c) and not str(c[-1]).strip().endswith("월")) or (isinstance(c, str) and "월" not in c):
            default_hierarchy.append(c)

    sb.subheader("🧭 매핑(왼쪽 구분/계층 열, 월 열 자동감지)")
    hierarchy_cols = sb.multiselect(
        "계층(구분) 열 선택(상위→하위, 1~3개 추천)",
        options=list(excel_view.columns),
        default=default_hierarchy
    )

    month_blocks = detect_month_cols(excel_view)
    if not month_blocks:
        st.warning("월(1~12/1월~12월) 열을 찾지 못했습니다. 헤더 행 수/건너뛸 행을 조정하세요.")
        st.stop()

    # 정규화
    tidy = tidy_from_excel_table(excel_view, hierarchy_cols=hierarchy_cols, month_blocks=month_blocks)

else:
    # CSV 경로: 이미 롱형식이라고 가정
    st.subheader("CSV 미리보기")
    st.dataframe(csv_df.head(30), use_container_width=True)
    tidy = csv_df.rename(columns={"값": "공급량(㎥)"})
    if "공급량(㎥)" not in tidy.columns:
        st.stop()

# -------------------- 정규화 결과 --------------------
if tidy.empty:
    st.warning("정규화 결과가 비어 있습니다. 파싱 옵션을 조정하세요.")
    st.stop()

tidy["연도/시나리오"] = tidy["연도"].astype("Int64").astype(str) + "·" + tidy["시나리오"].astype(str)

st.subheader("정규화 데이터(표준형)")
st.dataframe(tidy.head(50), use_container_width=True)

# -------------------- 필터 --------------------
st.subheader("필터")
f1, f2, f3 = st.columns(3)
with f1:
    years = sorted(tidy["연도"].dropna().unique().tolist())
    sel_years = st.multiselect("연도", years, default=years)
with f2:
    scns = tidy["시나리오"].dropna().unique().tolist()
    order = ["실적","Normal","Best","Conservative","계획"]
    ordered = [s for s in order if s in scns] + [s for s in scns if s not in order]
    sel_scns = st.multiselect("시나리오/계획", ordered, default=ordered)
with f3:
    uses = tidy["용도"].dropna().unique().tolist()
    sel_use = st.selectbox("용도 선택(그래프 기준)", ["전체"] + uses, index=0)

view = tidy.query("연도 in @sel_years and 시나리오 in @sel_scns").copy()

# -------------------- 출력 --------------------
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
