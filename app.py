import io
import json
import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import matplotlib as mpl
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from github import Github

# ─────────────────────────────────────────────────────────
# 기본 설정
# ─────────────────────────────────────────────────────────
def set_korean_font():
    ttf = Path(__file__).parent / "NanumGothic-Regular.ttf"
    if ttf.exists():
        try:
            mpl.font_manager.fontManager.addfont(str(ttf))
            mpl.rcParams["font.family"] = "NanumGothic"
            mpl.rcParams["axes.unicode_minus"] = False
        except Exception:
            pass

set_korean_font()
st.set_page_config(page_title="도시가스 판매량 분석 보고서", layout="wide")

DEFAULT_SALES_XLSX = "판매량(계획_실적).xlsx"
DEFAULT_CSV = "가정용외_202601.csv"

# ─────────────────────────────────────────────────────────
# 코멘트 DB 저장/불러오기
# ─────────────────────────────────────────────────────────
COMMENT_DB_FILE = "report_comments_db.json"
REPO_NAME = "Han11112222/quarterly-sales-report"


def load_comments_db():
    try:
        if "GITHUB_TOKEN" in st.secrets:
            token = st.secrets["GITHUB_TOKEN"]
            g = Github(token)
            repo = g.get_repo(REPO_NAME)
            try:
                contents = repo.get_contents(COMMENT_DB_FILE)
                data = json.loads(contents.decoded_content.decode("utf-8"))
                with open(COMMENT_DB_FILE, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=4)
                return data
            except Exception:
                pass
    except Exception:
        pass

    if os.path.exists(COMMENT_DB_FILE):
        try:
            with open(COMMENT_DB_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_comments_db(db_data):
    try:
        with open(COMMENT_DB_FILE, "w", encoding="utf-8") as f:
            json.dump(db_data, f, ensure_ascii=False, indent=4)
    except Exception as e:
        st.warning(f"⚠️ 로컬 저장 실패: {e}")

    if "GITHUB_TOKEN" not in st.secrets:
        st.warning("⚠️ GITHUB_TOKEN이 설정되지 않아 영구 저장이 불가합니다. Streamlit Secrets에 추가하세요.")
        return

    try:
        token = st.secrets["GITHUB_TOKEN"]
        g = Github(token)
        repo = g.get_repo(REPO_NAME)
        content_string = json.dumps(db_data, ensure_ascii=False, indent=4)

        try:
            contents = repo.get_contents(COMMENT_DB_FILE)
            repo.update_file(
                contents.path,
                "Update comments via Streamlit App",
                content_string,
                contents.sha
            )
        except Exception:
            repo.create_file(
                COMMENT_DB_FILE,
                "Create comments db via Streamlit App",
                content_string
            )
    except Exception as e:
        st.error(f"❌ GitHub 저장 실패: {e}")


# ─────────────────────────────────────────────────────────
# 코멘트 UI 렌더링 (PW: 1234)
# ─────────────────────────────────────────────────────────
def render_comment_section(title, db_key, curr_db, comments_db, height, placeholder, widget_key):
    st.markdown(f"**{title}**")
    saved_text = curr_db.get(db_key, None)

    if saved_text is not None:
        url_pattern = re.compile(r'(https?://[^\s]+)')
        linked_text = url_pattern.sub(r'<a href="\1" target="_blank" style="color: #2563eb; text-decoration: underline; font-weight: bold;">\1</a>', saved_text)
        formatted_text = linked_text.replace('\n', '<br>')
        st.markdown(
            f"""
            <div style="background-color: #f8f9fa; border: 1px solid #e9ecef; border-left: 4px solid #1f77b4; padding: 15px; border-radius: 4px; color: #1e40af; font-size: 14.5px; line-height: 1.6; margin-bottom: 10px;">
                {formatted_text}
            </div>
            """, unsafe_allow_html=True
        )
        with st.expander("🔒 코멘트 수정/삭제 (비밀번호 필요)"):
            pw = st.text_input("비밀번호(PW) 입력", type="password", key=f"pw_{widget_key}")
            if pw == "1234":
                new_text = st.text_area("내용 수정", value=saved_text, height=height, key=f"edit_ta_{widget_key}", label_visibility="collapsed")
                col1, col2 = st.columns(2)
                with col1:
                    if st.button("💾 수정 내용 저장", key=f"edit_save_{widget_key}", use_container_width=True):
                        curr_db[db_key] = new_text
                        save_comments_db(comments_db)
                        st.rerun()
                with col2:
                    if st.button("🗑️ 코멘트 삭제", key=f"del_{widget_key}", use_container_width=True):
                        curr_db.pop(db_key, None)
                        save_comments_db(comments_db)
                        st.rerun()
            elif pw != "":
                st.error("❌ 비밀번호가 일치하지 않습니다.")
    else:
        input_text = st.text_area("내용 입력", height=height, placeholder=placeholder, key=f"ta_{widget_key}", label_visibility="collapsed")
        if st.button("💾 이 코멘트 저장", key=f"save_{widget_key}"):
            curr_db[db_key] = input_text
            save_comments_db(comments_db)
            st.rerun()


USE_COL_TO_GROUP: Dict[str, str] = {
    "취사용": "가정용", "개별난방용": "가정용", "중앙난방용": "가정용", "자가열전용": "가정용",
    "일반용": "영업용",
    "업무난방용": "업무용", "냉방용": "업무용", "주한미군": "업무용",
    "산업용": "산업용",
    "수송용(CNG)": "수송용", "수송용(BIO)": "수송용",
    "열병합용": "열병합", "열병합용1": "열병합", "열병합용2": "열병합",
    "연료전지용": "연료전지", "열전용설비용": "열전용설비용",
}

COLOR_PLAN = "rgba(0, 90, 200, 1)"
COLOR_ACT  = "rgba(0, 150, 255, 1)"
COLOR_PREV = "rgba(190, 190, 190, 1)"

# ─────────────────────────────────────────────────────────
# 공통 유틸
# ─────────────────────────────────────────────────────────
def clean_korean_finance_number(val):
    if pd.isna(val): return 0.0
    s = str(val).replace(",", "").strip()
    if not s: return 0.0
    if s.endswith("-"): s = "-" + s[:-1]
    elif s.startswith("(") and s.endswith(")"): s = "-" + s[1:-1]
    s = re.sub(r"[^\d\.-]", "", s)
    try: return float(s)
    except: return 0.0

def fmt_num_safe(v) -> str:
    if pd.isna(v): return "-"
    try: return f"{float(v):,.0f}"
    except: return "-"

def center_style(styler):
    styler = styler.set_properties(**{"text-align": "center"})
    styler = styler.set_table_styles([
        dict(selector="th", props=[("text-align", "center"), ("vertical-align", "middle"), ("background-color", "#1e3a8a"), ("color", "#ffffff"), ("font-weight", "bold")]),
        dict(selector="thead th", props=[("background-color", "#1e3a8a"), ("color", "#ffffff"), ("font-weight", "bold")]),
        dict(selector="tbody tr th", props=[("background-color", "#1e3a8a"), ("color", "#ffffff"), ("font-weight", "bold")])
    ])
    return styler

def highlight_subtotal(s):
    is_subtotal = s.astype(str).str.contains('💡 소계|💡 총계|💡 합계')
    return ['background-color: #1e3a8a; color: #ffffff; font-weight: bold;' if is_subtotal.any() else '' for _ in s]

def _clean_base(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "Unnamed: 0" in out.columns: out = out.drop(columns=["Unnamed: 0"])
    out["연"] = pd.to_numeric(out["연"], errors="coerce").astype("Int64")
    out["월"] = pd.to_numeric(out["월"], errors="coerce").astype("Int64")
    return out

def keyword_group(col: str) -> Optional[str]:
    c = str(col)
    if "열병합" in c: return "열병합"
    if "연료전지" in c: return "연료전지"
    if "수송용" in c: return "수송용"
    if "열전용" in c: return "열전용설비용"
    if c in ["산업용"]: return "산업용"
    if c in ["일반용"]: return "영업용"
    if any(k in c for k in ["취사용", "난방용", "자가열"]): return "가정용"
    if any(k in c for k in ["업무", "냉방", "주한미군"]): return "업무용"
    return None

def make_long(plan_df: pd.DataFrame, actual_df: pd.DataFrame) -> pd.DataFrame:
    plan_df = _clean_base(plan_df)
    actual_df = _clean_base(actual_df)
    records = []
    for label, df in [("계획", plan_df), ("실적", actual_df)]:
        for col in df.columns:
            if col in ["연", "월"]: continue
            group = USE_COL_TO_GROUP.get(col)
            if group is None: group = keyword_group(col)
            if group is None: continue
            base = df[["연", "월"]].copy()
            base["그룹"] = group
            base["용도"] = col
            base["계획/실적"] = label
            base["값"] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
            records.append(base)
    if not records: return pd.DataFrame(columns=["연", "월", "그룹", "용도", "계획/실적", "값"])
    long_df = pd.concat(records, ignore_index=True).dropna(subset=["연", "월"])
    long_df["연"] = long_df["연"].astype(int)
    long_df["월"] = long_df["월"].astype(int)
    return long_df

def load_all_sheets(excel_bytes: bytes) -> Dict[str, pd.DataFrame]:
    xls = pd.ExcelFile(io.BytesIO(excel_bytes), engine="openpyxl")
    needed = ["계획_부피", "실적_부피", "계획_열량", "실적_열량"]
    out: Dict[str, pd.DataFrame] = {}
    for name in needed:
        if name in xls.sheet_names:
            out[name] = xls.parse(name)
    return out

def build_long_dict(sheets: Dict[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:
    long_dict: Dict[str, pd.DataFrame] = {}
    if ("계획_부피" in sheets) and ("실적_부피" in sheets):
        long_dict["부피"] = make_long(sheets["계획_부피"], sheets["실적_부피"])
    if ("계획_열량" in sheets) and ("실적_열량" in sheets):
        long_dict["열량"] = make_long(sheets["계획_열량"], sheets["실적_열량"])
    return long_dict


# ─────────────────────────────────────────────────────────
# ★ render_metric_card — 2번째 코드 스타일 (이모지 아이콘)
# ─────────────────────────────────────────────────────────
def render_metric_card(icon: str, title: str, main: str, sub: str = "", color: str = "#1f77b4"):
    html = f"""
    <div style="
        background-color:#ffffff;
        border-radius:16px;
        padding:24px 26px 20px 26px;
        box-shadow:0 2px 12px rgba(0,0,0,0.07);
        height:100%;
        display:flex;
        flex-direction:column;
        justify-content:flex-start;
    ">
        <div style="font-size:42px; line-height:1; margin-bottom:12px;">{icon}</div>
        <div style="font-size:17px; font-weight:600; color:#333; margin-bottom:8px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">{title}</div>
        <div style="font-size:30px; font-weight:800; color:{color}; margin-bottom:8px; white-space:nowrap; letter-spacing:-0.5px;">{main}</div>
        <div style="font-size:13px; color:#555; min-height:18px; font-weight:400; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">{sub}</div>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────
# ★ render_rate_donut — 2번째 코드 스타일 (파랑+회색, 크기 확대)
# ─────────────────────────────────────────────────────────
def render_rate_donut(rate: float, color: str, title: str = ""):
    if pd.isna(rate) or np.isnan(rate):
        st.markdown("<div style='font-size:14px;color:#999;text-align:center;'>데이터 없음</div>", unsafe_allow_html=True)
        return
    filled = max(min(float(rate), 200.0), 0.0)
    empty  = max(100.0 - filled, 0.0)
    fig = go.Figure(
        data=[go.Pie(
            values=[filled, empty],
            hole=0.72,
            sort=False,
            direction="clockwise",
            marker=dict(colors=[color, "#e5e7eb"]),
            textinfo="none",
        )]
    )
    fig.update_layout(
        showlegend=False,
        width=240,
        height=270,
        margin=dict(l=0, r=0, t=40, b=0),
        title=dict(text=title, font=dict(size=14, color="#666"), x=0.5, xanchor='center', y=0.97) if title else None,
        annotations=[dict(
            text=f"{rate:.1f}%",
            x=0.5, y=0.5,
            showarrow=False,
            font=dict(size=26, color=color, family="NanumGothic"),
        )],
    )
    st.plotly_chart(fig, use_container_width=False)


# ─────────────────────────────────────────────────────────
# ★ 공통 헬퍼: 스택바 차트에 전체합계 꺾은선 추가
# ─────────────────────────────────────────────────────────
def add_total_line_to_stack(fig, years_list, pivot_df, unit_str):
    years_str = [str(y) for y in years_list]
    totals = [pivot_df.loc[y, "합계"] if y in pivot_df.index else 0 for y in years_list]
    fig.add_trace(go.Scatter(
        x=years_str,
        y=totals,
        mode="lines+markers",
        name="전체 합계 추이",
        line=dict(color="rgba(255, 160, 0, 0.85)", width=2.5, dash="solid"),
        marker=dict(size=9, color="rgba(255, 160, 0, 0.95)", symbol="circle",
                    line=dict(color="white", width=1.5)),
        showlegend=True,
    ))
    return fig


# ─────────────────────────────────────────────────────────
# 메인 레이아웃 (사이드바)
# ─────────────────────────────────────────────────────────
st.title("📊 판매량 분석 보고서")

with st.sidebar:
    st.header("🏢 보고서 모드 설정")
    app_mode = st.radio("조회 모드 선택", ["for Executive", "for Sharing", "for summary"])
    st.markdown("---")

    st.header("📂 데이터 불러오기")
    st.subheader("1. 판매량 데이터 (필수)")
    src_sales = st.radio("판매량 데이터 소스", ["레포 파일 사용", "엑셀 업로드(.xlsx)"], index=0, key="rpt_sales_src")
    excel_bytes = None
    rpt_base_info = ""
    if src_sales == "엑셀 업로드(.xlsx)":
        up_sales = st.file_uploader("판매량(계획_실적).xlsx 형식", type=["xlsx"], key="rpt_sales_uploader")
        if up_sales is not None:
            excel_bytes = up_sales.getvalue()
            rpt_base_info = f"소스: 업로드 파일 — {up_sales.name}"
    else:
        path_sales = Path(__file__).parent / DEFAULT_SALES_XLSX
        if path_sales.exists():
            excel_bytes = path_sales.read_bytes()
            rpt_base_info = f"소스: 레포 파일 — {DEFAULT_SALES_XLSX}"
        else:
            rpt_base_info = f"레포 경로에 {DEFAULT_SALES_XLSX} 파일이 없습니다."
    st.caption(rpt_base_info)
    st.markdown("---")

    st.subheader("2. 업종별 상세 (별첨용)")
    src_csv = st.radio("업종별 데이터 소스", ["레포 파일 사용", "CSV 업로드(.csv)"], index=0, key="csv_src")
    csv_bytes = None
    csv_info = ""
    if src_csv == "CSV 업로드(.csv)":
        up_csvs = st.file_uploader("가정용외_*.csv 형식 (다중 업로드 가능)", type=["csv"], accept_multiple_files=True, key="csv_uploader")
        if up_csvs:
            df_list = []
            for f in up_csvs:
                try: df_list.append(pd.read_csv(io.BytesIO(f.getvalue()), encoding="utf-8-sig", thousands=','))
                except:
                    try: df_list.append(pd.read_csv(io.BytesIO(f.getvalue()), encoding="cp949", thousands=','))
                    except: pass
            if df_list:
                st.session_state['merged_csv_df'] = pd.concat(df_list, ignore_index=True)
            csv_info = f"소스: 업로드 파일 {len(up_csvs)}개 병합 완료"
        else:
            if 'merged_csv_df' in st.session_state: del st.session_state['merged_csv_df']
    else:
        path_csv = Path(__file__).parent / DEFAULT_CSV
        if path_csv.exists():
            csv_info = f"소스: 레포 파일 전체 자동 스캔 중..."
        else:
            csv_info = f"레포 경로에 {DEFAULT_CSV} 파일이 없습니다."
    st.caption(csv_info)

    st.markdown("---")
    st.subheader("3. 단위 선택")
    unit_choice = st.radio("단위", ["열량 기준 (GJ)", "부피 기준 (천m³)"], index=0, key="unit_radio")

# ─────────────────────────────────────────────────────────
# 본문 로직
# ─────────────────────────────────────────────────────────
if app_mode == "for Sharing":
    st.info("🔒 'for Sharing' 모드입니다. 내용을 확인하려면 비밀번호를 입력해주세요.")
    share_pw = st.text_input("접근 비밀번호 (PW)", type="password")
    if share_pw != "1234":
        if share_pw != "": st.error("❌ 비밀번호가 일치하지 않습니다.")
        st.stop()
    else:
        st.success("🔓 인증되었습니다. 공유용 화면을 표시합니다.")

if app_mode == "for summary":
    st.info("🔒 'for summary' 모드입니다. 내용을 확인하려면 비밀번호를 입력해주세요.")
    summary_pw = st.text_input("접근 비밀번호 (PW)", type="password", key="summary_pw_input")
    if summary_pw != "1234":
        if summary_pw != "": st.error("❌ 비밀번호가 일치하지 않습니다.")
        st.stop()
    else:
        st.success("🔓 인증되었습니다. 요약 화면을 표시합니다.")

import random
_loading_msgs = [
    ("⛽", "도시가스 배관을 점검하는 중입니다", "잠시만 기다려 주세요!"),
    ("📊", "숫자들이 줄을 서고 있습니다", "곧 멋진 그래프가 펼쳐집니다"),
    ("🔥", "데이터를 가열하는 중입니다", "이 웹앱을 만드신 분은 정말 센스가 넘치시네요 😎"),
    ("🧮", "엑셀보다 빠르게 계산 중입니다", "엑셀은 이제 안녕~"),
    ("📈", "그래프가 그려질 준비를 하고 있습니다", "기대해 주세요!"),
    ("🗂️", "파일들을 열심히 정리하는 중입니다", "담당자분의 노고에 박수를 👏"),
    ("💡", "인사이트를 발굴하는 중입니다", "데이터 속에 보물이 숨어 있어요"),
    ("🏗️", "보고서를 건설 중입니다", "완성까지 조금만 기다려 주세요"),
    ("☕", "데이터를 끓이는 중입니다", "커피 한 잔 하고 오셔도 됩니다"),
    ("🐢", "빠른 달팽이가 데이터를 나르는 중", "달팽이도 최선을 다하고 있습니다 🐌"),
]

def show_loading_banner(icon, title, subtitle):
    placeholder = st.empty()
    placeholder.markdown(f"""
    <div style="
        background: linear-gradient(135deg, #1e3a8a 0%, #2563eb 100%);
        border-radius: 16px;
        padding: 32px 40px;
        margin: 20px 0;
        display: flex;
        align-items: center;
        gap: 24px;
        box-shadow: 0 8px 32px rgba(30,58,138,0.18);
    ">
        <div style="font-size: 56px; line-height:1;">{icon}</div>
        <div>
            <div style="font-size: 22px; font-weight: 800; color: #ffffff; margin-bottom: 6px; letter-spacing: -0.3px;">
                {title}...
            </div>
            <div style="font-size: 15px; color: #bfdbfe; font-weight: 500;">
                {subtitle}
            </div>
        </div>
        <div style="margin-left:auto;">
            <div style="
                width: 36px; height: 36px;
                border: 4px solid rgba(255,255,255,0.3);
                border-top-color: #ffffff;
                border-radius: 50%;
                animation: spin 0.9s linear infinite;
            "></div>
        </div>
    </div>
    <style>
    @keyframes spin {{
        to {{ transform: rotate(360deg); }}
    }}
    </style>
    """, unsafe_allow_html=True)
    return placeholder

long_dict_rpt: Dict[str, pd.DataFrame] = {}
if 'excel_bytes' in locals() and excel_bytes is not None:
    _ic, _tt, _st = random.choice(_loading_msgs)
    _ph = show_loading_banner(_ic, _tt, _st)
    sheets_rpt = load_all_sheets(excel_bytes)
    long_dict_rpt = build_long_dict(sheets_rpt)
    _ph.empty()

df_csv = pd.DataFrame()
if src_csv == "레포 파일 사용":
    repo_dir = Path(__file__).parent
    all_csvs = list(repo_dir.glob("*가정용외*.csv")) + list(repo_dir.glob("가정용외*.csv"))
    all_csvs = list(set(all_csvs))
    if all_csvs:
        _ph2 = show_loading_banner("📂", "업종별 상세 데이터를 스캔하는 중입니다", "파일이 많을수록 더 풍성한 분석이 가능합니다 📁")
        csv_list = []
        for p in all_csvs:
            try: csv_list.append(pd.read_csv(p, encoding="utf-8-sig", thousands=','))
            except:
                try: csv_list.append(pd.read_csv(p, encoding="cp949", thousands=','))
                except: pass
        if csv_list: df_csv = pd.concat(csv_list, ignore_index=True)
        _ph2.empty()

if df_csv.empty and 'merged_csv_df' in st.session_state:
    df_csv = st.session_state['merged_csv_df'].copy()

if not df_csv.empty:
    _ph3 = show_loading_banner("🧹", "데이터를 깔끔하게 다듬는 중입니다", "숫자 하나하나 꼼꼼히 확인하고 있어요")
    if "사용량(mj)" in df_csv.columns: df_csv["사용량(mj)"] = df_csv["사용량(mj)"].apply(clean_korean_finance_number)
    if "사용량(m3)" in df_csv.columns: df_csv["사용량(m3)"] = df_csv["사용량(m3)"].apply(clean_korean_finance_number)
    _ph3.empty()

comments_db = load_comments_db()

if unit_choice == "열량 기준 (GJ)":
    df_long_rpt = long_dict_rpt.get("열량", pd.DataFrame())
    unit_str = "GJ"
    val_col = "사용량(mj)"
    key_sfx = "_gj"
else:
    df_long_rpt = long_dict_rpt.get("부피", pd.DataFrame())
    unit_str = "천m³"
    val_col = "사용량(m3)"
    key_sfx = "_vol"

st.markdown(f"**📐 현재 단위: {unit_str}**")
st.markdown("<hr style='margin: 4px 0 16px 0;'>", unsafe_allow_html=True)

years_available = [2024, 2025, 2026]
default_y_index = len(years_available) - 1
default_q_index = 3

if not df_long_rpt.empty:
    years_available = sorted(df_long_rpt["연"].unique().tolist())
    actual_data = df_long_rpt[(df_long_rpt["계획/실적"] == "실적") & (df_long_rpt["값"] > 0)]
    if not actual_data.empty:
        max_year = actual_data["연"].max()
        max_month = actual_data[actual_data["연"] == max_year]["월"].max()
        default_y_index = years_available.index(max_year) if max_year in years_available else len(years_available) - 1
        default_q_index = int((max_month - 1) // 3)
        if default_q_index < 0: default_q_index = 0
        if default_q_index > 3: default_q_index = 3

df_csv_tab = df_csv.copy()

if not df_csv_tab.empty:
    if unit_str == "GJ" and "사용량(mj)" in df_csv_tab.columns:
        df_csv_tab["사용량(mj)"] = df_csv_tab["사용량(mj)"] / 1000.0
    elif unit_str == "천m³" and "사용량(m3)" in df_csv_tab.columns:
        df_csv_tab["사용량(m3)"] = df_csv_tab["사용량(m3)"] / 1000.0

    df_csv_tab["날짜_파싱"] = pd.NaT
    date_col = None
    for c in ["청구년월", "매출년월", "년월", "기준년월"]:
        if c in df_csv_tab.columns:
            date_col = c
            break

    if date_col:
        mask1 = df_csv_tab["날짜_파싱"].isna()
        df_csv_tab.loc[mask1, "날짜_파싱"] = pd.to_datetime(df_csv_tab.loc[mask1, date_col], format="%b-%y", errors="coerce")
        mask2 = df_csv_tab["날짜_파싱"].isna()
        if mask2.any(): df_csv_tab.loc[mask2, "날짜_파싱"] = pd.to_datetime(df_csv_tab.loc[mask2, date_col], format="%Y%m", errors="coerce")
        mask3 = df_csv_tab["날짜_파싱"].isna()
        if mask3.any(): df_csv_tab.loc[mask3, "날짜_파싱"] = pd.to_datetime(df_csv_tab.loc[mask3, date_col], errors="coerce")

    df_csv_tab["연_csv"] = df_csv_tab["날짜_파싱"].dt.year
    df_csv_tab["월_csv"] = df_csv_tab["날짜_파싱"].dt.month

if app_mode != "for summary":
    c_y, c_q, c_empty = st.columns([1, 1, 2])
    with c_y: sel_year_rpt = st.selectbox("기준 연도", years_available, index=default_y_index, key=f"rpt_yr{key_sfx}")
    with c_q: sel_quarter = st.selectbox("기준 분기", ["1Q (1~3월)", "2Q (1~6월 누적)", "3Q (1~9월 누적)", "4Q (1~12월 누적)"], index=default_q_index, key=f"rpt_qt{key_sfx}")
    max_month = int(sel_quarter[0]) * 3
else:
    sel_year_rpt = years_available[-1] if years_available else 2025
    sel_quarter = "4Q (1~12월 누적)"
    max_month = 12

mode_suffix = "_sharing" if app_mode == "for Sharing" else ("_mayor" if app_mode == "for summary" else "_executive")
report_db_key = f"{sel_year_rpt}_{sel_quarter[:2]}_{unit_str}{mode_suffix}"

if report_db_key not in comments_db: comments_db[report_db_key] = {}
curr_db = comments_db[report_db_key]
st.markdown("<hr style='margin: 10px 0 30px 0;'>", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────
# for summary 모드
# ─────────────────────────────────────────────────────────
if app_mode == "for summary":
    st.markdown(f"### 🏢 요약 대시보드 (for summary)")

    available_years_rpt = df_long_rpt["연"].dropna().unique().tolist() if not df_long_rpt.empty else []
    available_years_csv = df_csv_tab["연_csv"].dropna().unique().tolist() if not df_csv_tab.empty else []
    all_available_years = sorted(list(set(available_years_rpt + available_years_csv + [2021, 2022, 2023, 2024, 2025])))
    target_defaults = [2021, 2022, 2023, 2024, 2025]

    selected_years = st.multiselect(
        "📅 조회할 연도 선택 (다중 선택 가능)",
        options=all_available_years,
        default=target_defaults,
        key=f"mayor_year_filter_{key_sfx}"
    )

    if not selected_years:
        st.info("선택된 연도가 없습니다. 연도를 선택해주세요.")
        st.stop()

    st.markdown("---")

    # 1. 연도별 전체 판매량 추이
    st.markdown("#### 1. 연도별 전체 판매량 추이")
    df_stack = df_long_rpt[(df_long_rpt["계획/실적"] == "실적") & (df_long_rpt["연"].isin(selected_years))]

    target_groups = ["가정용", "산업용", "기타"]

    stack_data_list = []
    for yr in selected_years:
        yr_df = df_stack[df_stack["연"] == yr]
        row_dict = {"연": yr}
        for grp in target_groups:
            if grp == "기타":
                val = yr_df[~yr_df["그룹"].isin(["가정용", "산업용"])]["값"].sum() if not yr_df.empty else 0
            else:
                val = yr_df[yr_df["그룹"] == grp]["값"].sum() if not yr_df.empty else 0
            row_dict[grp] = val
        stack_data_list.append(row_dict)

    stack_pivot_table = pd.DataFrame(stack_data_list).set_index("연")
    stack_pivot_table["합계"] = stack_pivot_table.sum(axis=1)

    stack_grp_full = pd.DataFrame()
    if not stack_pivot_table.empty:
        melted = stack_pivot_table.drop(columns=["합계"]).reset_index()
        stack_grp_full = melted.melt(id_vars=["연"], var_name="그룹", value_name="값")
        yearly_totals = stack_grp_full.groupby("연")["값"].transform("sum")
        stack_grp_full["비율(%)"] = np.where(yearly_totals > 0, (stack_grp_full["값"] / yearly_totals * 100).round(1), 0)
        stack_grp_full["텍스트"] = stack_grp_full.apply(lambda x: f"{x['값']:,.0f}<br>({x['비율(%)']}%)" if x['값'] > 0 else "", axis=1)
        stack_grp_full["연_str"] = stack_grp_full["연"].astype(str)

        color_map = {
            "가정용": "#1B3A6B",
            "산업용": "#2E86AB",
            "기타":   "#8DA9C4",
        }
        fig_stack = px.bar(
            stack_grp_full, x="연_str", y="값", color="그룹",
            title=f"그룹별 판매량 추이 ({unit_str})",
            text="텍스트",
            color_discrete_map=color_map,
            category_orders={"그룹": ["가정용", "산업용", "기타"]}
        )
        fig_stack.update_layout(
            xaxis_title="연도", yaxis_title=f"판매량 ({unit_str})",
            barmode="stack", margin=dict(t=40, b=20, l=20, r=20),
            plot_bgcolor="white", paper_bgcolor="white",
            font=dict(color="#333333"),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            yaxis=dict(gridcolor="#EEEEEE", gridwidth=1),
            xaxis=dict(linecolor="#DDDDDD"),
        )
        fig_stack.update_traces(
            textposition='inside', insidetextanchor='middle',
            textfont=dict(size=12, color="white"),
            marker_line_width=0,
        )

        for yr in selected_years:
            val = stack_pivot_table.loc[yr, "합계"]
            fig_stack.add_annotation(x=str(yr), y=val, text=f"<b>[{val:,.0f} {unit_str}]</b>", showarrow=False, yshift=20, font=dict(size=16, color="black"))

        fig_stack = add_total_line_to_stack(fig_stack, selected_years, stack_pivot_table, unit_str)

        st.plotly_chart(fig_stack, use_container_width=True)

    st.markdown(f"**📊 연도별 그룹 판매량 상세 표 ({unit_str})**")
    stack_table = stack_pivot_table.reset_index().rename(columns={"연": "연도"})
    format_dict = {col: "{:,.0f}" for col in stack_table.columns if col != "연도"}
    st.dataframe(center_style(stack_table.style.format(format_dict)), use_container_width=True, hide_index=True)

    latest_year_overall = max(selected_years) if selected_years else 2025
    total_latest_overall = stack_pivot_table.loc[latest_year_overall, "합계"] if latest_year_overall in stack_pivot_table.index else 0

    st.markdown(f"""
    <div style="background-color: #f8f9fa; border-left: 4px solid #1f77b4; padding: 15px; border-radius: 4px; margin-bottom: 40px; color: #1e40af; font-size: 15px;">
        <strong>💡 [최근 동향 요약]</strong> {latest_year_overall}년 전체 총 판매량은 <strong>{total_latest_overall:,.0f} {unit_str}</strong> 입니다.
    </div>
    """, unsafe_allow_html=True)

    # 2. 연도별 산업용 세부 업종 추이
    st.markdown("#### 2. 연도별 산업용 세부 업종 추이")
    df_ind = df_csv_tab[df_csv_tab["상품명"].astype(str).str.contains("산업용")].copy() if not df_csv_tab.empty and "상품명" in df_csv_tab.columns else pd.DataFrame()

    if "업종분류" in df_ind.columns and "업종" not in df_ind.columns:
        df_ind["업종"] = df_ind["업종분류"]

    ind_target_cols = ["섬유업종", "펄프업종", "1차금속", "식료품", "기타"]

    if not df_ind.empty and "업종" in df_ind.columns:
        def map_industry_name(name):
            name = str(name)
            if "섬유" in name: return "섬유업종"
            if "펄프" in name or "종이" in name: return "펄프업종"
            if "1차" in name and "금속" in name: return "1차금속"
            if "식료품" in name: return "식료품"
            return "기타"
        df_ind["단순업종"] = df_ind["업종"].apply(map_industry_name)
        df_ind_filtered = df_ind[df_ind["연_csv"].isin(selected_years)].copy()
    else:
        df_ind_filtered = pd.DataFrame(columns=["연_csv", "단순업종", val_col])

    historical_ind_gj = {
        2021: {"섬유업종": 3420283, "펄프업종": 2296957, "1차금속": 1706564, "식료품": 932079, "기타": 3278497},
        2022: {"섬유업종": 3191900, "펄프업종": 2050939, "1차금속": 1589989, "식료품": 925398, "기타": 3255788},
        2023: {"섬유업종": 2731789, "펄프업종": 1923913, "1차금속": 1562081, "식료품": 901739, "기타": 2847261},
        2024: {"섬유업종": 2548101, "펄프업종": 1985362, "1차금속": 1501112, "식료품": 881977, "기타": 2816094},
    }

    ind_data_list = []
    for yr in selected_years:
        row_dict = {"연_csv": yr}
        if yr in historical_ind_gj and unit_str == "GJ":
            for tc in ind_target_cols:
                row_dict[tc] = historical_ind_gj[yr].get(tc, 0)
        else:
            yr_df = df_ind_filtered[df_ind_filtered["연_csv"] == yr] if not df_ind_filtered.empty else pd.DataFrame()
            for tc in ind_target_cols:
                val = yr_df[yr_df["단순업종"] == tc][val_col].sum() if not yr_df.empty else 0
                row_dict[tc] = val
        ind_data_list.append(row_dict)

    ind_pivot = pd.DataFrame(ind_data_list).set_index("연_csv")
    ind_pivot = ind_pivot[ind_target_cols]

    ind_stack_full = ind_pivot.reset_index().melt(id_vars=["연_csv"], var_name="단순업종", value_name=val_col)
    yearly_ind_totals = ind_stack_full.groupby("연_csv")[val_col].transform("sum")
    ind_stack_full["비율(%)"] = np.where(yearly_ind_totals > 0, (ind_stack_full[val_col] / yearly_ind_totals * 100).round(1), 0)
    ind_stack_full["텍스트"] = ind_stack_full.apply(lambda x: f"{x[val_col]:,.0f}<br>({x['비율(%)']}%)" if x[val_col] > 0 else "", axis=1)

    ind_color_map = {
        "섬유업종": "#1B3A6B",
        "펄프업종": "#2E6FAB",
        "1차금속":  "#4A9CC7",
        "식료품":   "#7BBDD4",
        "기타":     "#B0CFE0",
    }
    fig_ind_stack = px.bar(
        ind_stack_full, x="연_csv", y=val_col, color="단순업종",
        title=f"연도별 산업용 세부 업종 판매량 추이",
        text="텍스트",
        color_discrete_map=ind_color_map,
        category_orders={"단순업종": ["섬유업종", "펄프업종", "1차금속", "식료품", "기타"]}
    )
    fig_ind_stack.update_layout(
        xaxis_title="연도", yaxis_title=f"판매량 ({unit_str})",
        barmode="stack", margin=dict(t=40, b=20, l=20, r=20),
        xaxis=dict(type='category', linecolor="#DDDDDD"),
        plot_bgcolor="white", paper_bgcolor="white",
        font=dict(color="#333333"),
        legend=dict(orientation="v", yanchor="middle", y=0.5, xanchor="left", x=1.01, traceorder="normal"),
        yaxis=dict(gridcolor="#EEEEEE", gridwidth=1),
    )
    fig_ind_stack.update_traces(
        textposition='inside', insidetextanchor='middle',
        textfont=dict(size=12, color="white"),
        marker_line_width=0,
    )
    fig_ind_stack.for_each_trace(
        lambda t: t.update(textfont=dict(size=12, color="black")) if t.name == "기타" else None
    )
    st.plotly_chart(fig_ind_stack, use_container_width=True)

    st.markdown(f"**📊 연도별 산업용 구성비 상세 표 ({unit_str})**")
    ind_table = ind_pivot.copy()
    ind_table["💡 총계"] = ind_table.sum(axis=1)
    for col in ind_target_cols:
        ind_table[col] = ind_table.apply(
            lambda row: f"{row[col]:,.0f} ({(row[col] / row['💡 총계'] * 100):.1f}%)" if row['💡 총계'] > 0 else f"{row[col]:,.0f} (0.0%)", axis=1
        )
    ind_table["💡 총계"] = ind_table["💡 총계"].apply(lambda x: f"{x:,.0f}")
    ind_table = ind_table.reset_index().rename(columns={"연_csv": "연도"})
    st.dataframe(center_style(ind_table.style), use_container_width=True, hide_index=True)

    latest_year_ind = max(selected_years) if selected_years else 2025
    total_latest_ind = ind_pivot.loc[latest_year_ind].sum() if latest_year_ind in ind_pivot.index else 0
    top4_val = sum(ind_pivot.loc[latest_year_ind, tc] for tc in ["섬유업종", "펄프업종", "1차금속", "식료품"] if latest_year_ind in ind_pivot.index and tc in ind_pivot.columns)
    top4_ratio = (top4_val / total_latest_ind * 100) if total_latest_ind > 0 else 0

    st.markdown(f"""
    <div style="background-color: #f8f9fa; border-left: 4px solid #1f77b4; padding: 15px; border-radius: 4px; margin-bottom: 40px; color: #1e40af; font-size: 15px;">
        <strong>💡 [산업용 구성 요약]</strong> {latest_year_ind}년 산업용 전체 판매량은 <strong>{total_latest_ind:,.0f} {unit_str}</strong>이며, 주요 4대 업종(섬유, 펄프, 1차금속, 식료품)이 전체의 <strong>{top4_ratio:.1f}%</strong> ({top4_val:,.0f} {unit_str})를 점유하고 있습니다.
    </div>
    """, unsafe_allow_html=True)

    # 3. 도시가스 보급률 현황
    st.markdown("#### 3. 도시가스 보급률 현황")
    st.markdown("<span style='font-size:13px; color:#888; font-weight:500;'>&#91;2025.12 기준&#93;</span>", unsafe_allow_html=True)
    col1, col2, col3, col4 = st.columns(4)
    with col1: render_metric_card("📊", "전체 보급률", "96.8%", "", "#1f77b4")
    with col2: render_metric_card("🏙️", "대구시",     "97.5%", "", "#2ca02c")
    with col3: render_metric_card("🏘️", "경산시",     "101.3%", "", "#ff7f0e")
    with col4: render_metric_card("⛰️", "고령군",     "38.0%", "", "#d62728")

    st.markdown("<br>", unsafe_allow_html=True)
    show_gu_rate = st.toggle("🔍 대구시내 구청별 보급률 상세 보기 (전체 96.8%)", key=f"toggle_gu_rate_{key_sfx}")
    if show_gu_rate:
        try:
            repo_dir = Path(__file__).parent
            rate_files = list(repo_dir.glob("*보급률*.csv")) + list(repo_dir.glob("*보급률*.xlsx"))
            if rate_files:
                if str(rate_files[0]).endswith('.csv'):
                    df_rate = pd.read_csv(rate_files[0], encoding='utf-8-sig')
                else:
                    df_rate = pd.read_excel(rate_files[0])
                districts_order = ["중구", "동구", "서구", "남구", "북구", "수성구", "달서구", "달성군", "대구시 계", "전체"]
                rates_dict = {}
                if "중구" in df_rate.columns:
                    st.dataframe(center_style(df_rate.style), use_container_width=True, hide_index=True)
                else:
                    for i in range(len(df_rate)):
                        val0 = str(df_rate.iloc[i, 0]).strip()
                        if val0 in districts_order:
                            try:
                                rate_val = float(df_rate.iloc[i, -1])
                                rates_dict[val0] = f"{rate_val * 100:.1f}%"
                            except: pass
                    if rates_dict:
                        clean_df = pd.DataFrame([{"구분": "보급률", **{d: rates_dict.get(d, "-") for d in districts_order}}])
                        st.dataframe(center_style(clean_df.style), use_container_width=True, hide_index=True)
                    else:
                        st.dataframe(center_style(df_rate.style), use_container_width=True)
            else:
                st.info("💡 GitHub 레포지토리에 '보급률 현황' 파일이 인식되면 구청별 상세 내역이 표출됩니다.")
        except Exception as e:
            st.info("💡 GitHub 레포지토리에 '보급률 현황' 파일이 인식되면 구청별 상세 내역이 표출됩니다.")
    st.markdown("<br><br>", unsafe_allow_html=True)
    st.stop()

# ─────────────────────────────────────────────────────────
# for Executive / for Sharing 모드 — At a Glance
# ─────────────────────────────────────────────────────────
st.markdown("#### 💡 1. At a Glance")

if not df_long_rpt.empty:
    df_base = df_long_rpt[(df_long_rpt["연"].isin([sel_year_rpt, sel_year_rpt-1])) & (df_long_rpt["월"] <= max_month)]
    total_curr_plan = df_base[(df_base["연"] == sel_year_rpt) & (df_base["계획/실적"] == "계획")]["값"].sum()
    total_curr_act  = df_base[(df_base["연"] == sel_year_rpt) & (df_base["계획/실적"] == "실적")]["값"].sum()
    total_prev_act  = df_base[(df_base["연"] == sel_year_rpt-1) & (df_base["계획/실적"] == "실적")]["값"].sum()
    achieve_rate_plan = (total_curr_act / total_curr_plan * 100) if total_curr_plan else 0
    achieve_rate_prev = (total_curr_act / total_prev_act * 100) if total_prev_act else 0

    # ★ 수정: 2번째 코드 스타일 — 이모지 아이콘, {연도}년 타이틀, 파랑+회색 도넛
    col_m1, col_m2, col_m3, col_d1, col_d2 = st.columns([1.1, 1.25, 1.25, 0.7, 0.7])
    with col_m1:
        render_metric_card(
            "🎯",
            f"{sel_year_rpt}년 계획",
            f"{fmt_num_safe(total_curr_plan)} {unit_str}",
            "",
            "#2563eb"
        )
    with col_m2:
        sign_plan = "+" if total_curr_act - total_curr_plan > 0 else ""
        render_metric_card(
            "🔥",
            f"{sel_year_rpt}년 실적",
            f"{fmt_num_safe(total_curr_act)} {unit_str}",
            f"차이: {sign_plan}{fmt_num_safe(total_curr_act - total_curr_plan)} {unit_str} ({achieve_rate_plan:.1f}%, 계획대비)",
            "#2563eb"
        )
    with col_m3:
        sign_prev = "+" if total_curr_act - total_prev_act > 0 else ""
        render_metric_card(
            "🔄",
            f"{sel_year_rpt-1}년 실적",
            f"{fmt_num_safe(total_prev_act)} {unit_str}",
            f"차이: {sign_prev}{fmt_num_safe(total_curr_act - total_prev_act)} {unit_str} ({achieve_rate_prev:.1f}%, 전년대비)",
            "#9ca3af"
        )
    with col_d1:
        render_rate_donut(achieve_rate_plan, "#2563eb", "계획대비 달성률")
    with col_d2:
        render_rate_donut(achieve_rate_prev, "#9ca3af", "전년대비 증감률")

st.markdown("<hr style='margin: 30px 0;'>", unsafe_allow_html=True)

# 전체 판매량 요약
st.markdown("#### 📊 2. 전체 판매량 요약 및 주요 증감 원인 (One Page Review)")
if not df_long_rpt.empty:
    curr_plan = df_base[(df_base["연"] == sel_year_rpt) & (df_base["계획/실적"] == "계획")].groupby("그룹")["값"].sum()
    curr_act  = df_base[(df_base["연"] == sel_year_rpt) & (df_base["계획/실적"] == "실적")].groupby("그룹")["값"].sum()
    prev_act  = df_base[(df_base["연"] == sel_year_rpt-1) & (df_base["계획/실적"] == "실적")].groupby("그룹")["값"].sum()

    summary_df = pd.DataFrame({"계획": curr_plan, "실적": curr_act, "전년실적": prev_act}).fillna(0)
    summary_df["계획대비 증감"] = summary_df["실적"] - summary_df["계획"]
    summary_df["계획대비 달성률(%)"] = np.where(summary_df["계획"] > 0, (summary_df["실적"] / summary_df["계획"]) * 100, 0)
    summary_df["YoY 증감"] = summary_df["실적"] - summary_df["전년실적"]
    summary_df["YoY 대비(%)"] = np.where(summary_df["전년실적"] > 0, (summary_df["실적"] / summary_df["전년실적"]) * 100, 0)

    total_row = summary_df.sum(numeric_only=True)
    total_row["계획대비 달성률(%)"] = (total_row["실적"] / total_row["계획"]) * 100 if total_row["계획"] else 0
    total_row["YoY 대비(%)"] = (total_row["실적"] / total_row["전년실적"]) * 100 if total_row["전년실적"] else 0
    summary_df.loc["💡 합계"] = total_row
    summary_df = summary_df[["계획", "실적", "계획대비 증감", "계획대비 달성률(%)", "전년실적", "YoY 증감", "YoY 대비(%)"]]
    summary_df.columns = pd.MultiIndex.from_tuples([
        ("계획대비", "계획"), ("계획대비", "실적"), ("계획대비", "증감"), ("계획대비", "대비(%)"),
        ("YoY", "전년실적"), ("YoY", "증감"), ("YoY", "대비(%)")
    ])
    summary_df = summary_df.reset_index()
    summary_df.rename(columns={("그룹", ""): ("구분", "그룹"), ("index", ""): ("구분", "그룹")}, inplace=True)

    st.dataframe(
        center_style(summary_df.style.format({
            ("계획대비", "계획"): "{:,.0f}", ("계획대비", "실적"): "{:,.0f}",
            ("계획대비", "증감"): "{:,.0f}", ("계획대비", "대비(%)"): "{:,.1f}",
            ("YoY", "전년실적"): "{:,.0f}", ("YoY", "증감"): "{:,.0f}", ("YoY", "대비(%)"): "{:,.1f}"
        }).apply(highlight_subtotal, axis=1)),
        use_container_width=True, hide_index=True
    )
else:
    st.warning("👈 좌측 사이드바에서 판매량(.xlsx) 파일을 업로드하거나 레포 파일을 사용해 주세요.")

render_comment_section("📝 주요 증감 원인 작성 (One Page Review)", "review", curr_db, comments_db, 150,
                       "표를 바탕으로 전체적인 실적 증감 원인을 종합적으로 분석해 주세요.",
                       f"review_{key_sfx}{mode_suffix}")
st.markdown("<hr style='margin: 30px 0;'>", unsafe_allow_html=True)

# 용도별 판매량 분석
def render_usage_trend_report(usage_name, section_num, key_sfx, db_key, m_suffix):
    if df_long_rpt.empty:
        st.markdown(f"#### 📈 {section_num}. 용도별 판매량 분析 : {usage_name}")
        st.info("판매량 데이터가 없습니다.")
        return

    df_u = df_long_rpt[(df_long_rpt["그룹"] == usage_name) & (df_long_rpt["월"] <= max_month)]
    p_curr_plan = df_u[(df_u["연"] == sel_year_rpt) & (df_u["계획/실적"] == "계획")].groupby("월")["값"].sum()
    p_curr_act  = df_u[(df_u["연"] == sel_year_rpt) & (df_u["계획/실적"] == "실적")].groupby("월")["값"].sum()
    p_prev_act  = df_u[(df_u["연"] == sel_year_rpt-1) & (df_u["계획/실적"] == "실적")].groupby("월")["값"].sum()

    sum_plan = p_curr_plan.sum()
    sum_act  = p_curr_act.sum()
    sum_prev = p_prev_act.sum()
    diff_prev = sum_act - sum_prev
    rate_prev = (sum_act / sum_prev * 100) if sum_prev > 0 else 0
    sign_prev = "+" if diff_prev > 0 else ""

    st.markdown(f"""<div style="display:flex;align-items:center;gap:15px;margin-bottom:10px;"><h4 style="margin:0;">📈 {section_num}. 용도별 판매량 분析 : {usage_name}</h4></div>""", unsafe_allow_html=True)

    months_list = list(range(1, max_month + 1))
    col_c, col_m = st.columns([1, 2.5])

    with col_c:
        st.markdown(f"**■ 누적 실적 비교 ({sel_quarter[:2]})**")
        st.markdown(f"""<div style="background-color:#e2e8f0;border-left:5px solid #1e3a8a;padding:10px;margin-bottom:0;border-radius:4px;"><div style="font-size:14.5px;color:#1e3a8a;font-weight:700;line-height:1.5;">판매량: {sum_act:,.0f} {unit_str}<br>전년대비: {sign_prev}{diff_prev:,.0f} ({rate_prev:.1f}%)</div></div>""", unsafe_allow_html=True)
        fig_c = go.Figure()
        fig_c.add_trace(go.Bar(
            x=[f"{sel_year_rpt}년<br>계획", f"{sel_year_rpt}년<br>실적", f"{sel_year_rpt-1}년<br>실적"],
            y=[sum_plan, sum_act, sum_prev],
            marker_color=[COLOR_PLAN, COLOR_ACT, COLOR_PREV],
            text=[f"{sum_plan:,.0f}", f"{sum_act:,.0f}", f"{sum_prev:,.0f}"],
            textposition='auto', textfont=dict(size=14)
        ))
        fig_c.update_layout(margin=dict(t=25, b=10, l=10, r=10), height=420, showlegend=False)
        st.plotly_chart(fig_c, use_container_width=True)

    with col_m:
        st.markdown("**■ 월별 실적 비교**")
        st.markdown("<div style='padding:1px;margin-bottom:27px;line-height:1.5;'>&nbsp;<br>&nbsp;</div>", unsafe_allow_html=True)
        fig_m = go.Figure()
        vals_plan = [p_curr_plan.get(m, 0) for m in months_list]
        vals_act  = [p_curr_act.get(m, 0) for m in months_list]
        vals_prev = [p_prev_act.get(m, 0) for m in months_list]
        fig_m.add_trace(go.Bar(x=months_list, y=vals_plan, name=f'{sel_year_rpt}년 계획', marker_color=COLOR_PLAN, text=[f"{v:,.0f}" if v>0 else "" for v in vals_plan], textposition='auto', textfont=dict(size=11)))
        fig_m.add_trace(go.Bar(x=months_list, y=vals_act,  name=f'{sel_year_rpt}년 실적', marker_color=COLOR_ACT,  text=[f"{v:,.0f}" if v>0 else "" for v in vals_act],  textposition='auto', textfont=dict(size=11)))
        fig_m.add_trace(go.Bar(x=months_list, y=vals_prev, name=f'{sel_year_rpt-1}년 실적', marker_color=COLOR_PREV, text=[f"{v:,.0f}" if v>0 else "" for v in vals_prev], textposition='auto', textfont=dict(size=11)))
        fig_m.update_layout(
            barmode='group', xaxis=dict(tickmode='linear', tick0=1, dtick=1),
            xaxis_title="월", yaxis_title=f"판매량({unit_str})",
            margin=dict(t=10, b=10, l=10, r=10), height=420,
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
        )
        st.plotly_chart(fig_m, use_container_width=True)

    if usage_name in ["산업용", "업무용"] and not df_csv_tab.empty and val_col in df_csv_tab.columns:
        st.markdown(f"**■ 세부 업종별 판매량 비교 (당해연도 vs 전년도)**")
        csv_products = df_csv_tab["상품명"].astype(str).str.replace(r"\s+", "", regex=True)

        if usage_name == "산업용":
            df_sub_filtered = df_csv_tab[(csv_products == "산업용") & (df_csv_tab["월_csv"] <= max_month)].copy()
            grp_col = "업종"
        else:
            valid_biz_nospaces = ["냉난방용(업무)", "업무난방용", "주한미군"]
            df_sub_filtered = df_csv_tab[(csv_products.isin(valid_biz_nospaces)) & (df_csv_tab["월_csv"] <= max_month)].copy()
            if "업종분류" in df_sub_filtered.columns: df_sub_filtered["업종"] = df_sub_filtered["업종분류"]
            grp_col = "업종"

        if not df_sub_filtered.empty and grp_col in df_sub_filtered.columns:
            curr_ind_grp = df_sub_filtered[df_sub_filtered["연_csv"] == sel_year_rpt].groupby(grp_col, as_index=False)[val_col].sum().rename(columns={val_col: f"{sel_year_rpt}년"})
            prev_ind_grp = df_sub_filtered[df_sub_filtered["연_csv"] == sel_year_rpt-1].groupby(grp_col, as_index=False)[val_col].sum().rename(columns={val_col: f"{sel_year_rpt-1}년"})
            ind_comp = pd.merge(curr_ind_grp, prev_ind_grp, on=grp_col, how="outer").fillna(0)
            ind_comp = ind_comp.sort_values(f"{sel_year_rpt}년", ascending=False).reset_index(drop=True)

            if len(ind_comp) > 10:
                top10_df  = ind_comp.iloc[:10].copy()
                others_df = ind_comp.iloc[10:].copy()
                o_c = others_df[f"{sel_year_rpt}년"].sum()
                o_p = others_df[f"{sel_year_rpt-1}년"].sum()
                others_row = pd.DataFrame([{grp_col: "기타", f"{sel_year_rpt}년": o_c, f"{sel_year_rpt-1}년": o_p}])
                ind_comp_plot = pd.concat([top10_df, others_row], ignore_index=True)
            else:
                ind_comp_plot = ind_comp.copy()

            ind_comp_plot["증감절대값"] = abs(ind_comp_plot[f"{sel_year_rpt}년"] - ind_comp_plot[f"{sel_year_rpt-1}년"])
            max_diff_idx = ind_comp_plot["증감절대값"].idxmax()
            colors_act = [COLOR_ACT] * len(ind_comp_plot)
            if pd.notna(max_diff_idx): colors_act[max_diff_idx] = "#d32f2f"

            fig_ind = go.Figure()
            fig_ind.add_trace(go.Bar(x=ind_comp_plot[grp_col], y=ind_comp_plot[f"{sel_year_rpt}년"],   name=f'{sel_year_rpt}년',   marker_color=colors_act, text=[f"{v:,.0f}" if v>0 else "" for v in ind_comp_plot[f"{sel_year_rpt}년"]],   textposition='auto', textfont=dict(size=11)))
            fig_ind.add_trace(go.Bar(x=ind_comp_plot[grp_col], y=ind_comp_plot[f"{sel_year_rpt-1}년"], name=f'{sel_year_rpt-1}년', marker_color=COLOR_PREV,  text=[f"{v:,.0f}" if v>0 else "" for v in ind_comp_plot[f"{sel_year_rpt-1}년"]], textposition='auto', textfont=dict(size=11)))
            fig_ind.update_layout(
                barmode='group', xaxis_title="", yaxis_title=f"판매량({unit_str})",
                margin=dict(t=10, b=10, l=10, r=10), height=420,
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
            )
            st.plotly_chart(fig_ind, use_container_width=True)
        else:
            st.info("해당 용도의 세부 업종 데이터가 없습니다.")

    render_comment_section(f"📝 {usage_name} 세부 코멘트 작성", db_key, curr_db, comments_db, 100,
                           f"{usage_name}의 월별 편차 원인 및 특이사항을 기록하세요.",
                           f"{usage_name}_{key_sfx}{m_suffix}")
    st.markdown("<br>", unsafe_allow_html=True)

render_usage_trend_report("가정용", 3, key_sfx, "home", mode_suffix)
render_usage_trend_report("산업용", 4, key_sfx, "ind",  mode_suffix)
render_usage_trend_report("업무용", 5, key_sfx, "biz",  mode_suffix)
st.markdown("<hr style='margin: 30px 0;'>", unsafe_allow_html=True)

# 별첨 (for Sharing 전용)
def render_attachment_report(usage_label, section_num, key_sfx):
    st.markdown(f"##### 🏭 {section_num}. 별첨 ({usage_label})")
    csv_products_att = df_csv_tab["상품명"].astype(str).str.replace(r"\s+", "", regex=True)

    if usage_label == "산업용":
        df_sub = df_csv_tab[csv_products_att == "산업용"].copy()
    else:
        valid_biz_att = ["냉난방용(업무)", "업무난방용", "주한미군"]
        df_sub = df_csv_tab[csv_products_att.isin(valid_biz_att)].copy()
        if "업종분류" in df_sub.columns: df_sub["업종"] = df_sub["업종분류"]

    if df_sub.empty:
        st.info(f"업로드된 CSV 내에 '{usage_label}' 용도 데이터가 존재하지 않습니다.")
        return

    df_sub_filtered = df_sub[df_sub["월_csv"] <= max_month]
    df_u_target = df_long_rpt[(df_long_rpt["그룹"] == usage_label) & (df_long_rpt["월"] <= max_month)]
    tgt_c = df_u_target[(df_u_target["연"] == sel_year_rpt) & (df_u_target["계획/실적"] == "실적")]["값"].sum()

    st.markdown(f"**■ 🏢 {usage_label} 세부 업종별 비교표**")
    if "업종" in df_sub_filtered.columns:
        curr_ind_grp = df_sub_filtered[df_sub_filtered["연_csv"] == sel_year_rpt].groupby("업종", as_index=False)[val_col].sum().rename(columns={val_col: f"{sel_year_rpt}년"})
        prev_ind_grp = df_sub_filtered[df_sub_filtered["연_csv"] == sel_year_rpt-1].groupby("업종", as_index=False)[val_col].sum().rename(columns={val_col: f"{sel_year_rpt-1}년"})
        ind_comp = pd.merge(curr_ind_grp, prev_ind_grp, on="업종", how="outer").fillna(0)

        sort_option = st.radio("표 정렬 기준", ["당해연도 판매량 순", "전년대비 증감량 순"], horizontal=True, key=f"sort_{usage_label}{key_sfx}")
        if sort_option == "당해연도 판매량 순":
            ind_comp = ind_comp.sort_values(f"{sel_year_rpt}년", ascending=False).reset_index(drop=True)
        else:
            ind_comp["temp_diff"] = ind_comp[f"{sel_year_rpt}년"] - ind_comp[f"{sel_year_rpt-1}년"]
            ind_comp = ind_comp.sort_values("temp_diff", ascending=False).reset_index(drop=True)
            ind_comp = ind_comp.drop(columns=["temp_diff"])

        if len(ind_comp) > 10:
            top10_df  = ind_comp.iloc[:10].copy()
            others_df = ind_comp.iloc[10:].copy()
            o_c = others_df[f"{sel_year_rpt}년"].sum()
            o_p = others_df[f"{sel_year_rpt-1}년"].sum()
            o_diff = o_c - o_p
            o_rate = (o_c / o_p * 100) if o_p > 0 else 0
            others_row = pd.DataFrame([{"업종": "기타", f"{sel_year_rpt}년": o_c, f"{sel_year_rpt-1}년": o_p, "증감": o_diff, "대비(%)": o_rate}])
            ind_comp = pd.concat([top10_df, others_row], ignore_index=True)

        ind_comp["증감"] = ind_comp[f"{sel_year_rpt}년"] - ind_comp[f"{sel_year_rpt-1}년"]
        ind_comp["대비(%)"] = np.where(ind_comp[f"{sel_year_rpt-1}년"] > 0, (ind_comp[f"{sel_year_rpt}년"] / ind_comp[f"{sel_year_rpt-1}년"]) * 100, 0)

        sum_curr = ind_comp[f"{sel_year_rpt}년"].sum()
        sum_prev = ind_comp[f"{sel_year_rpt-1}년"].sum()
        sum_diff = sum_curr - sum_prev
        sum_rate = (sum_curr / sum_prev * 100) if sum_prev > 0 else 0
        sub_ind_row = pd.DataFrame([{"업종": "💡 총계", f"{sel_year_rpt}년": sum_curr, f"{sel_year_rpt-1}년": sum_prev, "증감": sum_diff, "대비(%)": sum_rate}])
        ind_comp = pd.concat([ind_comp, sub_ind_row], ignore_index=True)

        st.dataframe(center_style(ind_comp.style.format({
            f"{sel_year_rpt}년": "{:,.0f}", f"{sel_year_rpt-1}년": "{:,.0f}", "증감": "{:,.0f}", "대비(%)": "{:,.1f}"
        }).apply(highlight_subtotal, axis=1)), use_container_width=True, hide_index=True)
    else:
        st.error("데이터에 '업종' 컬럼이 없습니다.")
        return

    st.markdown("<br>", unsafe_allow_html=True)

    show_details = st.toggle(f"🔍 {usage_label} 세부 분析 및 고객(Top 30) 보기", value=False, key=f"toggle_{usage_label}{key_sfx}")
    if show_details:
        st.markdown("<hr style='border-top:1px dashed #ccc;margin:10px 0 20px 0;'>", unsafe_allow_html=True)
        st.markdown(f"**■ 🔍 {usage_label} 업종 내 고객 상세 분析**")
        available_industries = [ind for ind in ind_comp["업종"].tolist() if ind not in ["💡 총계", "기타"]]
        sel_ind = st.selectbox(f"상세 조회할 업종을 선택하세요 ({usage_label})", ["선택 안함"] + available_industries, key=f"sel_ind_{usage_label}{key_sfx}")

        if sel_ind != "선택 안함":
            ind_data = df_sub_filtered[df_sub_filtered["업종"] == sel_ind]
            c_curr = ind_data[ind_data["연_csv"] == sel_year_rpt].groupby("고객명", as_index=False)[val_col].sum().rename(columns={val_col: f"{sel_year_rpt}년"})
            c_prev = ind_data[ind_data["연_csv"] == sel_year_rpt-1].groupby("고객명", as_index=False)[val_col].sum().rename(columns={val_col: f"{sel_year_rpt-1}년"})
            cust_comp = pd.merge(c_curr, c_prev, on="고객명", how="outer").fillna(0)
            cust_comp["증감"] = cust_comp[f"{sel_year_rpt}년"] - cust_comp[f"{sel_year_rpt-1}년"]
            cust_comp["대비(%)"] = np.where(cust_comp[f"{sel_year_rpt-1}년"] > 0, (cust_comp[f"{sel_year_rpt}년"] / cust_comp[f"{sel_year_rpt-1}년"]) * 100, 0)

            if sort_option == "당해연도 판매량 순":
                cust_comp = cust_comp.sort_values(f"{sel_year_rpt}년", ascending=False).reset_index(drop=True)
            else:
                cust_comp = cust_comp.sort_values("증감", ascending=False).reset_index(drop=True)

            sum_curr = cust_comp[f"{sel_year_rpt}년"].sum()
            sum_prev = cust_comp[f"{sel_year_rpt-1}년"].sum()
            sub_cust_row = pd.DataFrame([{"고객명": "💡 소계", f"{sel_year_rpt}년": sum_curr, f"{sel_year_rpt-1}년": sum_prev, "증감": sum_curr-sum_prev, "대비(%)": (sum_curr/sum_prev*100) if sum_prev>0 else 0}])
            cust_comp = pd.concat([cust_comp, sub_cust_row], ignore_index=True)
            st.dataframe(center_style(cust_comp.style.format({
                f"{sel_year_rpt}년": "{:,.0f}", f"{sel_year_rpt-1}년": "{:,.0f}", "증감": "{:,.0f}", "대비(%)": "{:,.1f}"
            }).apply(highlight_subtotal, axis=1)), use_container_width=True, hide_index=True)

        st.markdown("<hr style='border-top:1px dashed #ccc;margin:30px 0;'>", unsafe_allow_html=True)
        st.markdown(f"**■ 🏆 {usage_label} Top 30 업체 List (당해연도 판매량 기준)**")

        if "고객명" in df_sub_filtered.columns and "업종" in df_sub_filtered.columns:
            c_curr_all = df_sub_filtered[df_sub_filtered["연_csv"] == sel_year_rpt].groupby(["고객명", "업종"], as_index=False)[val_col].sum().rename(columns={val_col: f"{sel_year_rpt}년"})
            c_prev_all = df_sub_filtered[df_sub_filtered["연_csv"] == sel_year_rpt-1].groupby(["고객명", "업종"], as_index=False)[val_col].sum().rename(columns={val_col: f"{sel_year_rpt-1}년"})
            grp_top = pd.merge(c_curr_all, c_prev_all, on=["고객명", "업종"], how="outer").fillna(0)
            grp_top = grp_top.sort_values(f"{sel_year_rpt}년", ascending=False).reset_index(drop=True)
            grp_top = grp_top[(grp_top[f"{sel_year_rpt}년"] > 0) | (grp_top[f"{sel_year_rpt-1}년"] > 0)].reset_index(drop=True)
            grp_top_30 = grp_top.head(30).copy()
            grp_top_30["증감"] = grp_top_30[f"{sel_year_rpt}년"] - grp_top_30[f"{sel_year_rpt-1}년"]
            grp_top_30["대비(%)"] = np.where(grp_top_30[f"{sel_year_rpt-1}년"] > 0, (grp_top_30[f"{sel_year_rpt}년"] / grp_top_30[f"{sel_year_rpt-1}년"]) * 100, 0)

            top30_sum_curr = grp_top_30[f"{sel_year_rpt}년"].sum()
            top30_sum_prev = grp_top_30[f"{sel_year_rpt-1}년"].sum()
            top30_ratio = (top30_sum_curr / tgt_c * 100) if tgt_c > 0 else 0
            subtotal_row = pd.DataFrame([{
                "고객명": "💡 소계 (Top 30)", "업종": f"전체대비 {top30_ratio:.1f}%",
                f"{sel_year_rpt}년": top30_sum_curr, f"{sel_year_rpt-1}년": top30_sum_prev,
                "증감": top30_sum_curr - top30_sum_prev,
                "대비(%)": (top30_sum_curr / top30_sum_prev * 100) if top30_sum_prev > 0 else 0
            }])
            grp_top_show = pd.concat([grp_top_30, subtotal_row], ignore_index=True)
            grp_top_show.insert(0, "순위", list(range(1, len(grp_top_30)+1)) + ["-"])
            st.dataframe(center_style(grp_top_show.style.format({
                f"{sel_year_rpt}년": "{:,.0f}", f"{sel_year_rpt-1}년": "{:,.0f}", "증감": "{:,.0f}", "대비(%)": "{:,.1f}"
            }).apply(highlight_subtotal, axis=1)), use_container_width=True, hide_index=True)

            st.markdown("<br>", unsafe_allow_html=True)
            st.markdown(f"**🔍 {usage_label} 개별 고객 상세 차트**")
            top_customers = [c for c in grp_top["고객명"] if "💡" not in c]
            sel_cust = st.selectbox(f"상세 분析할 고객명을 선택하세요 ({usage_label})", ["선택 안함"] + top_customers, key=f"sel_cust_{usage_label}{key_sfx}")

            if sel_cust != "선택 안함":
                c_data = df_sub[df_sub["고객명"] == sel_cust]
                c_grp  = c_data.groupby(["연_csv", "월_csv"], as_index=False)[val_col].sum()
                y_cur  = c_grp[(c_grp["연_csv"] == sel_year_rpt) & (c_grp["월_csv"] <= max_month)]
                y_prev = c_grp[(c_grp["연_csv"] == sel_year_rpt-1) & (c_grp["월_csv"] <= max_month)]
                sum_cur_c  = y_cur[val_col].sum()
                sum_prev_c = y_prev[val_col].sum()
                diff_val = sum_cur_c - sum_prev_c
                rate_val = (sum_cur_c / sum_prev_c * 100) if sum_prev_c > 0 else 0
                sign_str = "+" if diff_val > 0 else ""
                yoy_text = f"전년대비 증감: {sign_str}{diff_val:,.0f} ({rate_val:.1f}%)"

                cc1, cc2 = st.columns([1, 2])
                with cc1:
                    fig_cust_cum = go.Figure()
                    fig_cust_cum.add_trace(go.Bar(
                        x=[f"{sel_year_rpt}년", f"{sel_year_rpt-1}년"],
                        y=[sum_cur_c, sum_prev_c],
                        marker_color=[COLOR_ACT, COLOR_PREV],
                        text=[f"{sum_cur_c:,.0f}", f"{sum_prev_c:,.0f}"],
                        textposition='auto'
                    ))
                    fig_cust_cum.add_annotation(x=0.5, y=1.05, xref="paper", yref="paper", text=f"<b>{yoy_text}</b>", showarrow=False, font=dict(size=13, color="#d32f2f" if diff_val < 0 else "#1f77b4"), bgcolor="#f8f9fa", bordercolor="#d0d7e5", borderwidth=1, borderpad=4)
                    fig_cust_cum.update_layout(title=f"'{sel_cust}' 누적 사용량 ({sel_quarter[:2]})", yaxis_title=f"판매량({unit_str})", margin=dict(t=50, b=10, l=10, r=10), height=350)
                    st.plotly_chart(fig_cust_cum, use_container_width=True)
                with cc2:
                    fig_cust_mon = go.Figure()
                    months_c  = list(range(1, max_month+1))
                    cur_vals  = [y_cur[y_cur['월_csv']==m][val_col].sum() for m in months_c]
                    prev_vals = [y_prev[y_prev['월_csv']==m][val_col].sum() for m in months_c]
                    fig_cust_mon.add_trace(go.Bar(x=months_c, y=cur_vals,  name=f"{sel_year_rpt}년",   marker_color=COLOR_ACT,  text=[f"{v:,.0f}" if v>0 else "" for v in cur_vals],  textposition='auto', textfont=dict(size=11)))
                    fig_cust_mon.add_trace(go.Bar(x=months_c, y=prev_vals, name=f"{sel_year_rpt-1}년", marker_color=COLOR_PREV, text=[f"{v:,.0f}" if v>0 else "" for v in prev_vals], textposition='auto', textfont=dict(size=11)))
                    fig_cust_mon.update_layout(
                        title=f"'{sel_cust}' 월별 사용량 추이", barmode='group',
                        xaxis=dict(tickmode='linear', tick0=1, dtick=1),
                        xaxis_title="월", yaxis_title=f"판매량({unit_str})",
                        margin=dict(t=50, b=10, l=10, r=10), height=350,
                        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
                    )
                    st.plotly_chart(fig_cust_mon, use_container_width=True)
        else:
            st.error("데이터에 '고객명' 또는 '업종' 컬럼이 없습니다.")
        st.markdown("<br><br>", unsafe_allow_html=True)

if app_mode == "for Sharing":
    st.markdown("#### 📎 6~7. 별첨 (업종별 상세 현황)")
    if df_csv_tab.empty or val_col not in df_csv_tab.columns:
        st.warning(f"⚠️ 업종별 상세 데이터를 보려면 '{unit_str}' 단위에 맞는 데이터({val_col} 컬럼 포함)를 CSV로 다중 업로드해주세요.")
    else:
        render_attachment_report("산업용", 6, key_sfx)
        render_attachment_report("업무용", 7, key_sfx)

    # ── 8. 연도별 전체 판매량 추이 (for Sharing) ──
    st.markdown("<hr style='margin: 30px 0;'>", unsafe_allow_html=True)
    st.markdown("#### 📊 8. 연도별 전체 판매량 추이")
    if not df_long_rpt.empty:
        actual_by_year_sh = df_long_rpt[df_long_rpt["계획/실적"] == "실적"].groupby("연")["값"].sum()
        all_years_sh = sorted([y for y in actual_by_year_sh[actual_by_year_sh > 0].index.tolist() if y >= 2020])
        df_stack_sh = df_long_rpt[
            (df_long_rpt["계획/실적"] == "실적") &
            (df_long_rpt["월"] <= max_month) &
            (df_long_rpt["연"].isin(all_years_sh))
        ]
        sh_target_groups = ["가정용", "산업용", "기타"]
        sh_stack_data = []
        for yr in all_years_sh:
            yr_df = df_stack_sh[df_stack_sh["연"] == yr]
            row_dict = {"연": yr}
            for grp in sh_target_groups:
                if grp == "기타":
                    v = yr_df[~yr_df["그룹"].isin(["가정용", "산업용"])]["값"].sum() if not yr_df.empty else 0
                else:
                    v = yr_df[yr_df["그룹"] == grp]["값"].sum() if not yr_df.empty else 0
                row_dict[grp] = v
            sh_stack_data.append(row_dict)

        sh_pivot = pd.DataFrame(sh_stack_data).set_index("연")
        sh_pivot["합계"] = sh_pivot[sh_target_groups].sum(axis=1)

        sh_melted = sh_pivot.drop(columns=["합계"]).reset_index()
        sh_melted = sh_melted.melt(id_vars=["연"], var_name="그룹", value_name="값")
        sh_yearly_totals = sh_melted.groupby("연")["값"].transform("sum")
        sh_melted["비율(%)"] = np.where(sh_yearly_totals > 0, (sh_melted["값"] / sh_yearly_totals * 100).round(1), 0)
        sh_melted["텍스트"] = sh_melted.apply(
            lambda x: f"{x['값']:,.0f}<br>({x['비율(%)']}%)" if x['값'] > 0 else "", axis=1
        )
        sh_melted["연_str"] = sh_melted["연"].astype(str)

        sh_color_map = {"가정용": "#1B3A6B", "산업용": "#2E86AB", "기타": "#8DA9C4"}
        fig_sh_stack = px.bar(
            sh_melted, x="연_str", y="값", color="그룹",
            title=f"그룹별 판매량 추이 ({unit_str}) — {sel_quarter[:2]} 누적",
            text="텍스트",
            color_discrete_map=sh_color_map,
            category_orders={"그룹": ["가정용", "산업용", "기타"]}
        )
        fig_sh_stack.update_layout(
            xaxis_title="연도", yaxis_title=f"판매량 ({unit_str})",
            barmode="stack", margin=dict(t=40, b=20, l=20, r=20),
            plot_bgcolor="white", paper_bgcolor="white",
            font=dict(color="#333333"),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            yaxis=dict(gridcolor="#EEEEEE", gridwidth=1),
            xaxis=dict(linecolor="#DDDDDD"),
        )
        fig_sh_stack.update_traces(
            textposition='inside', insidetextanchor='middle',
            textfont=dict(size=12, color="white"),
            marker_line_width=0,
        )

        for yr in all_years_sh:
            val_tot = sh_pivot.loc[yr, "합계"]
            fig_sh_stack.add_annotation(x=str(yr), y=val_tot, text=f"<b>[{val_tot:,.0f} {unit_str}]</b>", showarrow=False, yshift=20, font=dict(size=16, color="black"))

        fig_sh_stack = add_total_line_to_stack(fig_sh_stack, all_years_sh, sh_pivot, unit_str)

        st.plotly_chart(fig_sh_stack, use_container_width=True)

        st.markdown(f"**📊 연도별 그룹 판매량 상세 표 ({unit_str}) — {sel_quarter[:2]} 누적**")
        sh_table = sh_pivot.reset_index().rename(columns={"연": "연도"})
        sh_fmt = {col: "{:,.0f}" for col in sh_table.columns if col != "연도"}
        st.dataframe(center_style(sh_table.style.format(sh_fmt)), use_container_width=True, hide_index=True)

        sh_latest = max(all_years_sh) if all_years_sh else 2025
        sh_total_latest = sh_pivot.loc[sh_latest, "합계"] if sh_latest in sh_pivot.index else 0
        st.markdown(f"""
        <div style="background-color: #f8f9fa; border-left: 4px solid #1f77b4; padding: 15px; border-radius: 4px; margin-bottom: 40px; color: #1e40af; font-size: 15px;">
            <strong>💡 [최근 동향 요약]</strong> {sh_latest}년 ({sel_quarter[:2]} 누적) 전체 총 판매량은 <strong>{sh_total_latest:,.0f} {unit_str}</strong>입니다.
        </div>
        """, unsafe_allow_html=True)
    else:
        st.info("판매량 데이터가 없습니다.")

# ─────────────────────────────────────────────────────────
# 연도별 전체 판매량 추이 (for Executive 전용)
# ─────────────────────────────────────────────────────────
if app_mode == "for Executive":
    st.markdown("<hr style='margin: 30px 0;'>", unsafe_allow_html=True)
    st.markdown("#### 📊 6. 연도별 전체 판매량 추이")

if app_mode == "for Executive" and not df_long_rpt.empty:
    actual_by_year = df_long_rpt[df_long_rpt["계획/실적"] == "실적"].groupby("연")["값"].sum()
    all_years_exec = sorted([y for y in actual_by_year[actual_by_year > 0].index.tolist() if y >= 2020])
    df_stack_exec = df_long_rpt[
        (df_long_rpt["계획/실적"] == "실적") &
        (df_long_rpt["월"] <= max_month) &
        (df_long_rpt["연"].isin(all_years_exec))
    ]

    exec_target_groups = ["가정용", "산업용", "기타"]
    exec_stack_data = []
    for yr in all_years_exec:
        yr_df = df_stack_exec[df_stack_exec["연"] == yr]
        row_dict = {"연": yr}
        for grp in exec_target_groups:
            if grp == "기타":
                v = yr_df[~yr_df["그룹"].isin(["가정용", "산업용"])]["값"].sum() if not yr_df.empty else 0
            else:
                v = yr_df[yr_df["그룹"] == grp]["값"].sum() if not yr_df.empty else 0
            row_dict[grp] = v
        exec_stack_data.append(row_dict)

    exec_pivot = pd.DataFrame(exec_stack_data).set_index("연")
    exec_pivot["합계"] = exec_pivot[exec_target_groups].sum(axis=1)

    exec_melted = exec_pivot.drop(columns=["합계"]).reset_index()
    exec_melted = exec_melted.melt(id_vars=["연"], var_name="그룹", value_name="값")
    exec_yearly_totals = exec_melted.groupby("연")["값"].transform("sum")
    exec_melted["비율(%)"] = np.where(exec_yearly_totals > 0, (exec_melted["값"] / exec_yearly_totals * 100).round(1), 0)
    exec_melted["텍스트"] = exec_melted.apply(
        lambda x: f"{x['값']:,.0f}<br>({x['비율(%)']}%)" if x['값'] > 0 else "", axis=1
    )
    exec_melted["연_str"] = exec_melted["연"].astype(str)

    exec_color_map = {"가정용": "#1B3A6B", "산업용": "#2E86AB", "기타": "#8DA9C4"}
    fig_exec_stack = px.bar(
        exec_melted, x="연_str", y="값", color="그룹",
        title=f"그룹별 판매량 추이 ({unit_str}) — {sel_quarter[:2]} 누적",
        text="텍스트",
        color_discrete_map=exec_color_map,
        category_orders={"그룹": ["가정용", "산업용", "기타"]}
    )
    fig_exec_stack.update_layout(
        xaxis_title="연도", yaxis_title=f"판매량 ({unit_str})",
        barmode="stack", margin=dict(t=40, b=20, l=20, r=20),
        plot_bgcolor="white", paper_bgcolor="white",
        font=dict(color="#333333"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        yaxis=dict(gridcolor="#EEEEEE", gridwidth=1),
        xaxis=dict(linecolor="#DDDDDD"),
    )
    fig_exec_stack.update_traces(
        textposition='inside', insidetextanchor='middle',
        textfont=dict(size=12, color="white"),
        marker_line_width=0,
    )

    for yr in all_years_exec:
        val = exec_pivot.loc[yr, "합계"]
        fig_exec_stack.add_annotation(x=str(yr), y=val, text=f"<b>[{val:,.0f} {unit_str}]</b>", showarrow=False, yshift=20, font=dict(size=16, color="black"))

    fig_exec_stack = add_total_line_to_stack(fig_exec_stack, all_years_exec, exec_pivot, unit_str)

    st.plotly_chart(fig_exec_stack, use_container_width=True)

    st.markdown(f"**📊 연도별 그룹 판매량 상세 표 ({unit_str}) — {sel_quarter[:2]} 누적**")
    exec_table = exec_pivot.reset_index().rename(columns={"연": "연도"})
    exec_fmt = {col: "{:,.0f}" for col in exec_table.columns if col != "연도"}
    st.dataframe(center_style(exec_table.style.format(exec_fmt)), use_container_width=True, hide_index=True)

# PDF 인쇄
st.markdown("<hr style='border-top:2px solid #bbb;margin:40px 0 20px 0;'>", unsafe_allow_html=True)
st.markdown("### 🖨️ 보고서 출력")
st.markdown("""
    <style>
    @media print {
        header[data-testid="stHeader"] { display: none !important; }
        section[data-testid="stSidebar"] { display: none !important; }
        div[data-testid="stToolbar"] { display: none !important; }
        iframe[title="st.iframe"] { display: none !important; }
    }
    </style>
""", unsafe_allow_html=True)
st.components.v1.html("""
    <button onclick="window.parent.print()" style="padding:12px 20px;font-size:16px;border-radius:8px;background-color:#1e3a8a;color:white;border:none;cursor:pointer;width:100%;font-weight:bold;box-shadow:0 4px 6px rgba(0,0,0,0.1);margin:2px;">
        🖨️ 현재 화면 전체를 PDF로 다운로드 (인쇄)
    </button>
""", height=70)
