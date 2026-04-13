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
st.set_page_config(page_title="도시가스 계획/실적 분석", layout="wide")

DEFAULT_SALES_XLSX = "판매량(계획_실적).xlsx"
DEFAULT_SUPPLY_XLSX = "공급량(계획_실적).xlsx"
DEFAULT_CSV = "가정용외_202601.csv"

# ─────────────────────────────────────────────────────────
# 코멘트 DB 저장 및 UI 유틸 (PW: 1234)
# ─────────────────────────────────────────────────────────
COMMENT_DB_FILE = "report_comments_db.json"

def load_comments_db():
    if os.path.exists(COMMENT_DB_FILE):
        try:
            with open(COMMENT_DB_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_comments_db(db_data):
    with open(COMMENT_DB_FILE, "w", encoding="utf-8") as f:
        json.dump(db_data, f, ensure_ascii=False, indent=4)

def render_comment_section(title, db_key, curr_db, comments_db, height, placeholder, widget_key):
    """개별 코멘트 저장 및 PW(1234) 보안 수정/삭제 UI 생성 함수"""
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


# 엑셀 헤더 → 분석 그룹 매핑 (판매량용)
USE_COL_TO_GROUP: Dict[str, str] = {
    "취사용": "가정용",
    "개별난방용": "가정용",
    "중앙난방용": "가정용",
    "자가열전용": "가정용",

    "일반용": "영업용",

    "업무난방용": "업무용",
    "냉방용": "업무용",
    "주한미군": "업무용",

    "산업용": "산업용",

    "수송용(CNG)": "수송용",
    "수송용(BIO)": "수송용",

    "열병합용": "열병합",
    "열병합용1": "열병합",
    "열병합용2": "열병합",

    "연료전지용": "연료전지",
    "열전용설비용": "열전용설비용",
}

GROUP_OPTIONS: List[str] = [
    "총량",
    "가정용",
    "영업용",
    "업무용",
    "산업용",
    "수송용",
    "열병합",
    "연료전지",
    "열전용설비용",
]

# 색상
COLOR_PLAN = "rgba(0, 90, 200, 1)"
COLOR_ACT = "rgba(0, 150, 255, 1)"
COLOR_PREV = "rgba(190, 190, 190, 1)"
COLOR_DIFF = "rgba(0, 80, 160, 1)"


# ─────────────────────────────────────────────────────────
# 공통 유틸
# ─────────────────────────────────────────────────────────
def fmt_num_safe(v) -> str:
    if pd.isna(v):
        return "-"
    try:
        return f"{float(v):,.0f}"
    except Exception:
        return "-"


def fmt_rate(v: float) -> str:
    if pd.isna(v) or np.isnan(v):
        return "-"
    return f"{float(v):,.1f}%"


def center_style(styler):
    """모든 표 숫자 가운데 정렬용 공통 스타일."""
    styler = styler.set_properties(**{"text-align": "center"})
    styler = styler.set_table_styles(
        [dict(selector="th", props=[("text-align", "center")])]
    )
    return styler

def highlight_subtotal(s):
    """표의 '💡 소계', '💡 총계', '💡 합계' 행을 연한 회색으로 하이라이트."""
    is_subtotal = s.astype(str).str.contains('💡 소계|💡 총계|💡 합계')
    return ['background-color: #f8f9fa; font-weight: bold;' if is_subtotal.any() else '' for _ in s]


def _clean_base(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "Unnamed: 0" in out.columns:
        out = out.drop(columns=["Unnamed: 0"])
    out["연"] = pd.to_numeric(out["연"], errors="coerce").astype("Int64")
    out["월"] = pd.to_numeric(out["월"], errors="coerce").astype("Int64")
    return out


def keyword_group(col: str) -> Optional[str]:
    """판매량 컬럼명이 약간 달라도 잡히도록 키워드 기반 보정."""
    c = str(col)

    if "열병합" in c:
        return "열병합"
    if "연료전지" in c:
        return "연료전지"
    if "수송용" in c:
        return "수송용"
    if "열전용" in c:
        return "열전용설비용"
    if c in ["산업용"]:
        return "산업용"
    if c in ["일반용"]:
        return "영업용"
    if any(k in c for k in ["취사용", "난방용", "자가열"]):
        return "가정용"
    if any(k in c for k in ["업무", "냉방", "주한미군"]):
        return "업무용"

    return None


def make_long(plan_df: pd.DataFrame, actual_df: pd.DataFrame) -> pd.DataFrame:
    """판매량 wide → long (연·월·그룹·용도·계획/실적·값)."""
    plan_df = _clean_base(plan_df)
    actual_df = _clean_base(actual_df)

    records = []
    for label, df in [("계획", plan_df), ("실적", actual_df)]:
        for col in df.columns:
            if col in ["연", "월"]:
                continue

            group = USE_COL_TO_GROUP.get(col)
            if group is None:
                group = keyword_group(col)
            if group is None:
                continue

            base = df[["연", "월"]].copy()
            base["그룹"] = group
            base["용도"] = col
            base["계획/실적"] = label
            base["값"] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
            records.append(base)

    if not records:
        return pd.DataFrame(columns=["연", "월", "그룹", "용도", "계획/실적", "값"])

    long_df = pd.concat(records, ignore_index=True)
    long_df = long_df.dropna(subset=["연", "월"])
    long_df["연"] = long_df["연"].astype(int)
    long_df["월"] = long_df["월"].astype(int)
    return long_df


def load_all_sheets(excel_bytes: bytes) -> Dict[str, pd.DataFrame]:
    """판매량 파일 시트 로드"""
    xls = pd.ExcelFile(io.BytesIO(excel_bytes), engine="openpyxl")
    needed = ["계획_부피", "실적_부피", "계획_열량", "실적_열량"]
    out: Dict[str, pd.DataFrame] = {}
    for name in needed:
        if name in xls.sheet_names:
            out[name] = xls.parse(name)
    return out


def build_long_dict(sheets: Dict[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:
    """판매량 long dict"""
    long_dict: Dict[str, pd.DataFrame] = {}
    if ("계획_부피" in sheets) and ("실적_부피" in sheets):
        long_dict["부피"] = make_long(sheets["계획_부피"], sheets["실적_부피"])
    if ("계획_열량" in sheets) and ("실적_열량" in sheets):
        long_dict["열량"] = make_long(sheets["계획_열량"], sheets["실적_열량"])
    return long_dict


def pick_default_year(years: List[int]) -> int:
    return years[-1] if years else 2025


def apply_period_filter(
    df: pd.DataFrame, sel_year: int, sel_month: int, agg_mode: str
) -> pd.DataFrame:
    """기준 연/월 + 당월/연누적 공통 필터."""
    if df.empty:
        return df

    base = df[df["연"] == sel_year].copy()
    if agg_mode == "당월":
        base = base[base["월"] == sel_month]
    else:  # "연 누적"
        base = base[base["월"] <= sel_month]
    return base


def apply_period_filter_multi_years(
    df: pd.DataFrame, sel_month: int, agg_mode: str, years: List[int]
) -> pd.DataFrame:
    """여러 연도 비교 차트용: 기준월/모드로 각 연도 동일 기간만 남김."""
    if df.empty:
        return df

    base = df[df["연"].isin(years)].copy()
    if agg_mode == "당월":
        base = base[base["월"] == sel_month]
    else:
        base = base[base["월"] <= sel_month]
    return base


def render_section_selector(
    long_df: pd.DataFrame,
    title: str,
    key_prefix: str,
    fixed_mode: Optional[str] = None,
    show_mode: bool = True
) -> Tuple[int, int, str, List[int]]:
    """각 섹션별 기준선택 UI."""
    st.markdown(f"#### ✅ {title} 기준 선택")

    if long_df.empty:
        st.info("연도 정보가 없습니다.")
        return 0, 1, "연 누적", []

    years_all = sorted(long_df["연"].unique().tolist())

    df_for_default = long_df.copy()
    if {"계획/실적", "값"}.issubset(df_for_default.columns):
        mask = (
            (df_for_default["계획/실적"] == "실적")
            & df_for_default["값"].notna()
            & (df_for_default["값"] != 0)
        )
        if mask.any():
            df_for_default = df_for_default[mask]

    if not df_for_default.empty:
        default_year = int(df_for_default["연"].max())
    else:
        default_year = years_all[-1] if years_all else 2025

    months_for_default_year = sorted(
        df_for_default[df_for_default["연"] == default_year]["월"].unique().tolist()
    )
    if not months_for_default_year:
        months_for_default_year = sorted(
            long_df[long_df["연"] == default_year]["월"].unique().tolist()
        )
    default_month_global = months_for_default_year[-1] if months_for_default_year else 1

    c1, c2, c3 = st.columns([1.2, 1.2, 1.6])

    with c1:
        sel_year = st.selectbox(
            "기준 연도",
            options=years_all,
            index=years_all.index(default_year) if default_year in years_all else 0,
            key=f"{key_prefix}year",
        )

    months_options = list(range(1, 13))
    
    df_sel = long_df[long_df["연"] == sel_year].copy()
    months_actual: List[int] = []
    
    if {"계획/실적", "값"}.issubset(df_sel.columns):
        m = (
            (df_sel["계획/실적"] == "실적")
            & df_sel["값"].notna()
            & (df_sel["값"] != 0)
        )
        months_actual = sorted(df_sel[m]["월"].unique().tolist())

    if months_actual:
        default_month_for_sel_year = months_actual[-1]
    else:
        default_month_for_sel_year = default_month_global

    if default_month_for_sel_year < 1: default_month_for_sel_year = 1
    if default_month_for_sel_year > 12: default_month_for_sel_year = 12

    with c2:
        sel_month = st.selectbox(
            "기준 월",
            options=months_options,
            index=months_options.index(default_month_for_sel_year),
            key=f"{key_prefix}month",
        )

    if fixed_mode in ["당월", "연 누적"]:
        agg_mode = fixed_mode
        with c3:
            st.markdown(
                "<div style='padding-top:28px;font-size:14px;color:#666;'>집계 기준: <b>연 누적</b></div>"
                if fixed_mode == "연 누적"
                else "<div style='padding-top:28px;font-size:14px;color:#666;'>집계 기준: <b>당월</b></div>",
                unsafe_allow_html=True,
            )
    else:
        if show_mode:
            with c3:
                agg_mode = st.radio(
                    "집계 기준",
                    ["당월", "연 누적"],
                    index=0,
                    horizontal=True,
                    key=f"{key_prefix}mode",
                )
        else:
            agg_mode = "연 누적"
            with c3:
                st.markdown(
                    "<div style='padding-top:28px;font-size:14px;color:#666;'>집계 기준: <b>연 누적</b></div>",
                    unsafe_allow_html=True,
                )

    st.markdown(
        f"<div style='margin-top:-4px;font-size:13px;color:#666;'>"
        f"선택 기준: <b>{sel_year}년 {sel_month}월</b> · {agg_mode}"
        f"</div>",
        unsafe_allow_html=True,
    )

    return sel_year, sel_month, agg_mode, years_all


# ─────────────────────────────────────────────────────────
# 판매량 공용 시각 카드/도넛
# ─────────────────────────────────────────────────────────
def render_metric_card(icon: str, title: str, main: str, sub: str = "", color: str = "#1f77b4"):
    html = f"""
    <div style="
        background-color:#ffffff;
        border-radius:22px;
        padding:24px 26px 20px 26px;
        box-shadow:0 4px 18px rgba(0,0,0,0.06);
        height:100%;
        display:flex;
        flex-direction:column;
        justify-content:flex-start;
    ">
        <div style="font-size:44px; line-height:1; margin-bottom:8px;">{icon}</div>
        <div style="font-size:18px; font-weight:650; color:#444; margin-bottom:6px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">{title}</div>
        <div style="font-size:28px; font-weight:750; color:{color}; margin-bottom:8px; white-space: nowrap; letter-spacing:-0.5px;">{main}</div>
        <div style="font-size:14px; color:#444; min-height:20px; font-weight:500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">{sub}</div>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)


def render_rate_donut(rate: float, color: str, title: str = ""):
    if pd.isna(rate) or np.isnan(rate):
        st.markdown("<div style='font-size:14px;color:#999;text-align:center;'>데이터 없음</div>",
                    unsafe_allow_html=True)
        return

    filled = max(min(float(rate), 200.0), 0.0)
    empty = max(100.0 - filled, 0.0)

    fig = go.Figure(
        data=[go.Pie(
            values=[filled, empty],
            hole=0.7,
            sort=False,
            direction="clockwise",
            marker=dict(colors=[color, "#e5e7eb"]),
            textinfo="none",
        )]
    )

    fig.update_layout(
        showlegend=False,
        width=200,
        height=230,
        margin=dict(l=0, r=0, t=40, b=0),
        title=dict(text=title, font=dict(size=14, color="#666"), x=0.5, xanchor='center', y=0.98) if title else None,
        annotations=[dict(
            text=f"{rate:.1f}%",
            x=0.5, y=0.5,
            showarrow=False,
            font=dict(size=22, color=color, family="NanumGothic"),
        )],
    )
    st.plotly_chart(fig, use_container_width=False)


# ─────────────────────────────────────────────────────────
# 0. (판매량) 월간 핵심 대시보드
# ─────────────────────────────────────────────────────────
def monthly_core_dashboard(long_df: pd.DataFrame, unit_label: str, key_prefix: str = ""):
    st.markdown("## 📌 월간 핵심 대시보드")

    if long_df.empty:
        st.info("데이터가 없습니다.")
        return

    sel_year, sel_month, agg_mode, years_all = render_section_selector(
        long_df, "월간 핵심 대시보드", key_prefix + "dash_base_"
    )
    mode_tag = "당월" if agg_mode == "당월" else "연도누적(연 누적)"

    base_this = apply_period_filter(long_df, sel_year, sel_month, agg_mode)
    plan_total = base_this[base_this["계획/실적"] == "계획"]["값"].sum()
    act_total = base_this[base_this["계획/실적"] == "실적"]["값"].sum()

    prev_year = sel_year - 1
    has_prev = prev_year in years_all
    if has_prev:
        base_prev = apply_period_filter(long_df, prev_year, sel_month, agg_mode)
        prev_total = base_prev[base_prev["계획/실적"] == "실적"]["값"].sum()
    else:
        base_prev = pd.DataFrame([])
        prev_total = np.nan

    plan_diff = act_total - plan_total if not pd.isna(plan_total) else np.nan
    plan_rate = (act_total / plan_total * 100.0) if (plan_total and plan_total > 0) else np.nan

    prev_diff = act_total - prev_total if not pd.isna(prev_total) else np.nan
    prev_rate = (act_total / prev_total * 100.0) if (prev_total and prev_total > 0) else np.nan

    st.markdown("<br>", unsafe_allow_html=True)
    k1, k2, k3 = st.columns(3)

    with k1:
        render_metric_card("📘", f"계획 합계 ({unit_label})", fmt_num_safe(plan_total), "", color="#2563eb")

    with k2:
        sub2 = f"계획대비 차이 {fmt_num_safe(plan_diff)} · 달성률({mode_tag}) {fmt_rate(plan_rate)}"
        render_metric_card("📗", f"실적 합계 ({unit_label})", fmt_num_safe(act_total), sub2, color="#16a34a")

    with k3:
        if pd.isna(prev_total):
            main_prev = "-"
            sub3 = "전년 데이터 없음"
        else:
            main_prev = fmt_num_safe(prev_total)
            sub3 = f"전년대비 차이 {fmt_num_safe(prev_diff)} · 증감률({mode_tag}) {fmt_rate(prev_rate)}"
        render_metric_card("📙", f"전년 동월{' 누적' if agg_mode=='연 누적' else ''} 실적 ({unit_label})",
                           main_prev, sub3, color="#f97316")

    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("#### 🎯 달성률 요약")

    d1, d2, d3, d4, d5 = st.columns([1, 2, 1, 2, 1])
    with d2:
        render_rate_donut(plan_rate, "#16a34a", "계획 달성률")
        st.caption(f"({mode_tag})")
    with d4:
        render_rate_donut(prev_rate, "#f97316", "전년대비 증감률")
        st.caption(f"({mode_tag})")

    st.markdown("<br>", unsafe_allow_html=True)

    st.markdown("#### ⚠️ 특이사항 (계획·전년 대비 편차 핵심 이슈)")

    if base_this.empty:
        st.info("선택 기준에 해당하는 데이터가 없습니다.")
        return

    try:
        det = base_this.copy()
        det["그룹/용도"] = det["그룹"] + " / " + det["용도"]

        pivot = (
            det.pivot_table(
                index="그룹/용도",
                columns="계획/실적",
                values="값",
                aggfunc="sum"
            )
            .fillna(0.0)
            .rename_axis(None, axis=1)
            .reset_index()
        )

        for c in ["계획", "실적"]:
            if c not in pivot.columns:
                pivot[c] = 0.0

        pivot["계획대비차이"] = pivot["실적"] - pivot["계획"]
        pivot["계획달성률(%)"] = np.where(
            pivot["계획"] != 0,
            (pivot["실적"] / pivot["계획"]) * 100.0,
            np.nan
        )

        if has_prev:
            prev_only = apply_period_filter(long_df, prev_year, sel_month, agg_mode)
            prev_only = prev_only[prev_only["계획/실적"] == "실적"].copy()
            prev_only["그룹/용도"] = prev_only["그룹"] + " / " + prev_only["용도"]
            prev_grp = (
                prev_only.groupby("그룹/용도", as_index=False)["값"]
                .sum()
                .rename(columns={"값": "전년실적"})
            )
            pivot = pivot.merge(prev_grp, on="그룹/용도", how="left")
        else:
            pivot["전년실적"] = np.nan

        pivot["전년대비차이"] = pivot["실적"] - pivot["전년실적"]
        pivot["전년대비증감률(%)"] = np.where(
            pivot["전년실적"] != 0,
            (pivot["실적"] / pivot["전년실적"]) * 100.0,
            np.nan
        )

        if pivot.empty:
            st.markdown("<div style='font-size:14px;color:#666;'>표시할 특이사항이 없습니다.</div>",
                        unsafe_allow_html=True)
            return

        plan_rank = pivot.copy()
        plan_rank["_abs_plan"] = plan_rank["계획대비차이"].abs()
        plan_rank = plan_rank.sort_values("_abs_plan", ascending=False)

        prev_rank = pivot.copy()
        prev_rank = prev_rank[~prev_rank["전년실적"].isna()]
        prev_rank["_abs_prev"] = prev_rank["전년대비차이"].abs()
        prev_rank = prev_rank.sort_values("_abs_prev", ascending=False)

        picked_rows = []
        if len(plan_rank) >= 1:
            picked_rows.append(plan_rank.iloc[0])
        if len(prev_rank) >= 1:
            picked_rows.append(prev_rank.iloc[0])
        else:
            if len(plan_rank) >= 2:
                picked_rows.append(plan_rank.iloc[1])

        core_issues = pd.DataFrame(picked_rows).drop_duplicates(subset=["그룹/용도"])
        if len(core_issues) < 2:
            for _, row in plan_rank.iterrows():
                if row["그룹/용도"] not in core_issues["그룹/용도"].values:
                    core_issues = pd.concat([core_issues, row.to_frame().T], ignore_index=True)
                if len(core_issues) >= 2:
                    break
        core_issues = core_issues.head(2)

        show_cols = [
            "그룹/용도",
            "계획",
            "실적",
            "계획대비차이",
            "계획달성률(%)",
            "전년실적",
            "전년대비차이",
            "전년대비증감률(%)",
        ]
        disp = core_issues[show_cols].copy()

        num_cols = ["계획", "실적", "계획대비차이", "전년실적", "전년대비차이"]
        rate_cols = ["계획달성률(%)", "전년대비증감률(%)"]
        for c in num_cols:
            disp[c] = disp[c].apply(fmt_num_safe)
        for c in rate_cols:
            disp[c] = disp[c].apply(fmt_rate)

        styled = center_style(disp.astype(str).style)
        html_table = styled.to_html(index=False, escape=False)
        st.markdown(
            f"<div style='border-radius:12px; overflow-x:auto; border:1px solid #eee;'>{html_table}</div>",
            unsafe_allow_html=True,
        )

    except Exception:
        st.markdown("<div style='font-size:14px;color:#666;'>특이사항 계산 중 오류가 발생해 표시를 생략했어.</div>",
                    unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────
# 1. (판매량) 월별 추이 (★ '연 누적' 고정)
# ─────────────────────────────────────────────────────────
def monthly_trend_section(long_df: pd.DataFrame, unit_label: str, key_prefix: str = ""):
    st.markdown("### 📈 월별 추이 그래프")

    if long_df.empty:
        st.info("데이터가 없습니다.")
        return

    sel_year, sel_month, agg_mode, years_all = render_section_selector(
        long_df, "월별 추이 그래프", key_prefix + "trend_base_",
        fixed_mode="연 누적", show_mode=False
    )

    years = years_all
    preferred_years = [y for y in [2021, 2022, 2023, 2024, 2025] if y in years]
    if sel_year not in preferred_years:
        preferred_years = preferred_years + [sel_year]
    default_years = preferred_years if preferred_years else [sel_year]

    sel_years = st.multiselect(
        "연도 선택(그래프)",
        options=years,
        default=default_years,
        key=f"{key_prefix}trend_years",
    )
    if not sel_years:
        st.info("표시할 연도를 한 개 이상 선택해 줘.")
        return

    try:
        sel_group = st.segmented_control(
            "그룹 선택",
            GROUP_OPTIONS,
            selection_mode="single",
            default="총량",
            key=f"{key_prefix}trend_group",
        )
    except Exception:
        sel_group = st.radio(
            "그룹 선택",
            GROUP_OPTIONS,
            index=0,
            horizontal=True,
            key=f"{key_prefix}trend_group_radio",
        )

    base = long_df[long_df["연"].isin(sel_years)].copy()
    base = apply_period_filter_multi_years(base, sel_month, agg_mode, sel_years)

    if sel_group != "총량":
        base = base[base["그룹"] == sel_group]

    plot_df = (
        base.groupby(["연", "월", "계획/실적"], as_index=False)["값"]
        .sum()
        .sort_values(["연", "월", "계획/실적"])
    )
    if plot_df.empty:
        st.info("선택 조건에 해당하는 데이터가 없어.")
        return

    plot_df["라벨"] = (
        plot_df["연"].astype(str)
        + "년 · "
        + ("" if sel_group == "총량" else sel_group + " · ")
        + plot_df["계획/실적"]
    )

    fig = px.line(
        plot_df,
        x="월",
        y="값",
        color="라벨",
        line_dash="계획/실적",
        category_orders={"계획/실적": ["실적", "계획"]},
        line_dash_map={"실적": "solid", "계획": "dash"},
        markers=True,
    )
    fig.update_layout(
        xaxis=dict(dtick=1),
        yaxis_title=f"판매량 ({unit_label})",
        legend_title="연도 / 구분",
        margin=dict(l=10, r=10, t=60, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.12, xanchor="right", x=1),
    )
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("##### 🔢 월별 수치표")
    table = (
        plot_df.pivot_table(index="월", columns="라벨", values="값", aggfunc="sum")
        .sort_index()
        .fillna(0.0)
    )
    
    total_row = table.sum(numeric_only=True)
    table.index = table.index.astype(object)
    table.loc["소계"] = total_row
    table = table.reset_index()
    numeric_cols = [c for c in table.columns if c != "월"]
    styled = center_style(
        table.style.format({col: "{:,.0f}" for col in numeric_cols})
    )
    st.dataframe(styled, use_container_width=True, hide_index=True)


# ─────────────────────────────────────────────────────────
# 2. (판매량) 계획대비 실적 요약
# ─────────────────────────────────────────────────────────
def yearly_summary_section(long_df: pd.DataFrame, unit_label: str, key_prefix: str = ""):
    st.markdown("### 📊 계획대비 실적 요약 — 그룹별 분석")

    if long_df.empty:
        st.info("데이터가 없습니다.")
        return

    sel_year, sel_month, agg_mode, years_all = render_section_selector(
        long_df, "연간 계획대비 실적 요약", key_prefix + "summary_base_"
    )
    mode_tag = "당월" if agg_mode == "당월" else f"1~{sel_month}월 연 누적"

    col2, col3 = st.columns([2, 1.5])
    with col2:
        view_mode = st.radio(
            "표시 기준",
            ["그룹별 합계", "그룹·용도 세부"],
            index=0,
            horizontal=True,
            key=f"{key_prefix}summary_mode",
        )
    with col3:
        include_prev = st.toggle("(Y-1) 포함", value=False, key=f"{key_prefix}summary_prev")

    base_this = apply_period_filter(long_df, sel_year, sel_month, agg_mode)
    if base_this.empty:
        st.info("선택 기준에 데이터가 없어.")
        return

    prev_year = sel_year - 1
    base_prev = (
        apply_period_filter(long_df, prev_year, sel_month, agg_mode)
        if (include_prev and prev_year in years_all)
        else pd.DataFrame([])
    )
    if not base_prev.empty:
        base_prev = base_prev[base_prev["계획/실적"] == "실적"]

    if view_mode == "그룹별 합계":
        grp_this = base_this.groupby(["그룹", "계획/실적"], as_index=False)["값"].sum()
        idx_col = "그룹"
        grp_prev = (
            base_prev.groupby("그룹", as_index=False)["값"].sum().rename(columns={"값": "전년실적"})
            if not base_prev.empty else pd.DataFrame([])
        )
    else:
        base_this["그룹/용도"] = base_this["그룹"] + " / " + base_this["용도"]
        grp_this = base_this.groupby(["그룹/용도", "계획/실적"], as_index=False)["값"].sum()
        idx_col = "그룹/용도"
        if not base_prev.empty:
            base_prev["그룹/용도"] = base_prev["그룹"] + " / " + base_prev["용도"]
            grp_prev = base_prev.groupby("그룹/용도", as_index=False)["값"].sum().rename(columns={"값": "전년실적"})
        else:
            grp_prev = pd.DataFrame([])

    pivot = grp_this.pivot(index=idx_col, columns="계획/실적", values="값").fillna(0.0)
    for c in ["계획", "실적"]:
        if c not in pivot.columns:
            pivot[c] = 0.0

    pivot["차이(실적-계획)"] = pivot["실적"] - pivot["계획"]
    pivot["달성률(%)"] = np.where(
        pivot["계획"] != 0,
        (pivot["실적"] / pivot["계획"]) * 100.0,
        np.nan
    )
    pivot = pivot[["계획", "실적", "차이(실적-계획)", "달성률(%)"]]

    plan_series = grp_this[grp_this["계획/실적"] == "계획"].set_index(idx_col)["값"]
    act_series = grp_this[grp_this["계획/실적"] == "실적"].set_index(idx_col)["값"]
    prev_series = grp_prev.set_index(idx_col)["전년실적"] if not grp_prev.empty else pd.Series(dtype=float)

    cats = sorted(set(plan_series.index) | set(act_series.index) | set(prev_series.index))
    y_plan = [plan_series.get(c, 0.0) for c in cats]
    y_act = [act_series.get(c, 0.0) for c in cats]
    y_prev = [prev_series.get(c, 0.0) for c in cats] if not prev_series.empty else None

    st.markdown(f"#### 📊 {sel_year}년 {mode_tag} 그룹별 계획·실적 막대그래프")

    fig_bar = go.Figure()
    fig_bar.add_bar(x=cats, y=y_plan, name=f"{sel_year} 계획", marker_color=COLOR_PLAN)
    fig_bar.add_bar(x=cats, y=y_act, name=f"{sel_year} 실적", marker_color=COLOR_ACT)
    if include_prev and y_prev is not None:
        fig_bar.add_bar(x=cats, y=y_prev, name=f"{prev_year} 실적", marker_color=COLOR_PREV)

    fig_bar.update_traces(width=0.25, selector=dict(type="bar"))
    fig_bar.update_layout(
        barmode="group",
        xaxis_title=idx_col,
        yaxis_title=f"기준기간 합계 ({unit_label})",
        margin=dict(l=10, r=10, t=10, b=10),
    )
    st.plotly_chart(fig_bar, use_container_width=True)

    st.markdown("##### 🔢 기준기간 요약 표")
    pivot_reset = pivot.reset_index()
    styled = center_style(
        pivot_reset.style.format(
            {"계획": "{:,.0f}", "실적": "{:,.0f}", "차이(실적-계획)": "{:,.0f}", "달성률(%)": "{:,.1f}"}
        )
    )
    st.dataframe(styled, use_container_width=True, hide_index=True)


# ─────────────────────────────────────────────────────────
# 3. (판매량) 계획대비 월별 실적 (★ '연 누적'고정)
# ─────────────────────────────────────────────────────────
def plan_vs_actual_usage_section(long_df: pd.DataFrame, unit_label: str, key_prefix: str = ""):
    st.markdown("### 🧮 계획대비 월별 실적 (용도 선택)")

    if long_df.empty:
        st.info("데이터가 없습니다.")
        return

    sel_year, sel_month, agg_mode, years_all = render_section_selector(
        long_df, "계획대비 월별 실적", key_prefix + "pv_base_",
        fixed_mode="연 누적", show_mode=False
    )
    mode_tag = f"1~{sel_month}월 연 누적"

    groups_all = sorted(g for g in long_df["그룹"].unique() if g is not None)
    available_groups = ["총량"] + [g for g in GROUP_OPTIONS if g != "총량" and g in groups_all]
    if not available_groups:
        st.info("선택 가능한 그룹이 없습니다.")
        return

    col1, col2 = st.columns([2, 1.5])
    with col1:
        try:
            sel_group = st.segmented_control(
                "용도(그룹) 선택",
                available_groups,
                selection_mode="single",
                default="총량",
                key=f"{key_prefix}pv_group",
            )
        except Exception:
            sel_group = st.radio(
                "용도(그룹) 선택",
                available_groups,
                index=available_groups.index("총량"),
                horizontal=True,
                key=f"{key_prefix}pv_group_radio",
            )
    with col2:
        include_prev = st.toggle("(Y-1) 포함", value=False, key=f"{key_prefix}pv_prev")

    period = st.radio(
        "기간",
        ["연간", "상반기(1~6월)", "하반기(7~12월)"],
        index=0,
        horizontal=False,
        key=f"{key_prefix}pv_period",
    )

    base = long_df.copy() if sel_group == "총량" else long_df[long_df["그룹"] == sel_group].copy()

    if period == "상반기(1~6월)":
        base = base[base["월"].between(1, 6)]
        period_label = "상반기"
    elif period == "하반기(7~12월)":
        base = base[base["월"].between(7, 12)]
        period_label = "하반기"
    else:
        period_label = "연간"

    base_year = apply_period_filter(base, sel_year, sel_month, agg_mode)
    if base_year.empty:
        st.info("선택 기준에 해당하는 데이터가 없어.")
        return

    prev_year = sel_year - 1
    base_prev = (
        apply_period_filter(base, prev_year, sel_month, agg_mode)
        if (include_prev and prev_year in years_all)
        else pd.DataFrame([])
    )
    if not base_prev.empty:
        base_prev = base_prev[base_prev["계획/실적"] == "실적"]

    bars = (
        base_year.groupby(["월", "계획/실적"], as_index=False)["값"]
        .sum()
        .sort_values(["월", "계획/실적"])
    )

    plan_series = bars[bars["계획/실적"] == "계획"].set_index("월")["값"].sort_index()
    actual_series = bars[bars["계획/실적"] == "실적"].set_index("월")["값"].sort_index()

    months_all = sorted(set(plan_series.index) | set(actual_series.index))
    plan_aligned = plan_series.reindex(months_all).fillna(0.0)
    actual_aligned = actual_series.reindex(months_all).fillna(0.0)
    diff_series = actual_aligned - plan_aligned

    fig = go.Figure()

    for status, name, color in [
        ("계획", f"{sel_year}년 계획", COLOR_PLAN),
        ("실적", f"{sel_year}년 실적", COLOR_ACT),
    ]:
        sub = bars[bars["계획/실적"] == status]
        if not sub.empty:
            fig.add_bar(x=sub["월"], y=sub["값"], name=name, width=0.25, marker_color=color)

    if include_prev and not base_prev.empty:
        prev_group = base_prev.groupby("월", as_index=False)["값"].sum().sort_values("월")
        fig.add_bar(
            x=prev_group["월"], y=prev_group["값"],
            name=f"{prev_year}년 실적",
            width=0.25, marker_color=COLOR_PREV
        )

    if len(diff_series) > 0:
        fig.add_scatter(
            x=months_all, y=diff_series.values,
            mode="lines+markers+text",
            name="증감(실적-계획)", yaxis="y2",
            line=dict(color=COLOR_DIFF, width=2),
            marker=dict(color=COLOR_DIFF),
            text=[f"{v:,.0f}" for v in diff_series.values],
            textposition="top center",
            textfont=dict(size=11),
        )

    fig.update_layout(
        title=f"{sel_year}년 {sel_group} 판매량 및 증감 ({period_label}, {mode_tag})",
        xaxis_title="월",
        yaxis_title=f"판매량 ({unit_label})",
        xaxis=dict(dtick=1),
        margin=dict(l=10, r=10, t=40, b=10),
        barmode="group",
        yaxis2=dict(title="증감(실적-계획)", overlaying="y", side="right", showgrid=False),
    )
    st.plotly_chart(fig, use_container_width=True)


# ─────────────────────────────────────────────────────────
# 4. (판매량) 기간별 스택 + 라인
# ─────────────────────────────────────────────────────────
def half_year_stacked_section(long_df: pd.DataFrame, unit_label: str, key_prefix: str = ""):
    st.markdown("### 🧱 기간별 용도 누적 실적 (스택형 막대 + 라인)")

    if long_df.empty:
        st.info("데이터가 없습니다.")
        return

    sel_year, sel_month, agg_mode, years_all = render_section_selector(
        long_df, "기간별 용도 누적 실적", key_prefix + "stack_base_"
    )

    years = years_all
    preferred_years = [y for y in [2021, 2022, 2023, 2024, 2025] if y in years]
    if sel_year not in preferred_years:
        preferred_years = preferred_years + [sel_year]
    default_years = preferred_years if preferred_years else [sel_year]

    sel_years = st.multiselect(
        "연도 선택(스택 그래프)",
        options=years,
        default=default_years,
        key=f"{key_prefix}stack_years",
    )
    if not sel_years:
        st.info("연도를 한 개 이상 선택해 줘.")
        return

    period = st.radio(
        "기간",
        ["연간", "상반기(1~6월)", "하반기(7~12월)"],
        index=0,
        horizontal=True,
        key=f"{key_prefix}period",
    )

    base = long_df[(long_df["연"].isin(sel_years)) & (long_df["계획/실적"] == "실적")].copy()

    if period == "상반기(1~6월)":
        base = base[base["월"].between(1, 6)]
        period_label = "상반기(1~6월)"
    elif period == "하반기(7~12월)":
        base = base[base["월"].between(7, 12)]
        period_label = "하반기(7~12월)"
    else:
        period_label = "연간"

    base = apply_period_filter_multi_years(base, sel_month, agg_mode, sel_years)

    if base.empty:
        st.info("선택 기준에 해당하는 데이터가 없어.")
        return

    grp = base.groupby(["연", "그룹"], as_index=False)["값"].sum()

    total_per_year = grp.groupby("연")["값"].transform("sum")
    grp["비중(%)"] = (grp["값"] / total_per_year) * 100
    
    grp["비중텍스트"] = grp.apply(
        lambda r: f"({r['값']:,.0f}, {r['비중(%)']:.1f}%)" if r["비중(%)"] >= 1.5 else "", 
        axis=1
    )

    fig = px.bar(
        grp, 
        x="연", 
        y="값", 
        color="그룹", 
        barmode="stack",
        text="비중텍스트",
        hover_data={"값": ":,.0f", "비중(%)": ":.1f", "비중텍스트": False}
    )
    
    fig.update_traces(
        width=0.4, 
        textposition="inside", 
        insidetextanchor="middle",
        textangle=0,            
        textfont=dict(size=11), 
        selector=dict(type="bar")
    )

    total = grp.groupby("연", as_index=False)["값"].sum().rename(columns={"값": "합계"})
    home = grp[grp["그룹"] == "가정용"].groupby("연", as_index=False)["값"].sum().rename(columns={"값": "가정용"})

    fig.add_scatter(
        x=total["연"], y=total["합계"],
        mode="lines+markers+text", name="합계",
        line=dict(dash="dash"),
        text=total["합계"].apply(lambda v: f"{v:,.0f}"),
        textposition="top center", textfont=dict(size=11),
    )

    if not home.empty:
        fig.add_scatter(
            x=home["연"], y=home["가정용"],
            mode="lines+markers", name="가정용",
            line=dict(dash="dot"),
        )

    mode_tag = "당월" if agg_mode == "당월" else f"1~{sel_month}월 연 누적"
    fig.update_layout(
        title=f"{period_label} 용도별 실적 판매량 ({mode_tag})",
        xaxis_title="연도",
        yaxis_title=f"판매량 ({unit_label})",
        margin=dict(l=10, r=10, t=40, b=10),
    )
    st.plotly_chart(fig, use_container_width=True)


# ─────────────────────────────────────────────────────────
# 공급량 전용 로더/정리
# ─────────────────────────────────────────────────────────
def load_supply_sheets(excel_bytes: bytes) -> Tuple[pd.DataFrame, pd.DataFrame]:
    xls = pd.ExcelFile(io.BytesIO(excel_bytes), engine="openpyxl")
    month_df = xls.parse("월별계획_실적") if "월별계획_실적" in xls.sheet_names else pd.DataFrame()
    day_df = xls.parse("일별실적") if "일별실적" in xls.sheet_names else pd.DataFrame()
    return month_df, day_df


def clean_supply_month_df(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    df = df.copy()
    if "Unnamed: 0" in df.columns:
        df = df.drop(columns=["Unnamed: 0"])
    df["연"] = pd.to_numeric(df["연"], errors="coerce").astype("Int64")
    df["월"] = pd.to_numeric(df["월"], errors="coerce").astype("Int64")
    num_cols = [c for c in df.columns if c not in ["연", "월"]]
    for c in num_cols:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["연", "월"])
    df["연"] = df["연"].astype(int)
    df["월"] = df["월"].astype(int)
    return df


def clean_supply_day_df(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    df = df.copy()
    df["일자"] = pd.to_datetime(df["일자"], errors="coerce")
    for c in ["공급량(MJ)", "공급량(M3)", "평균기온(℃)"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["일자"])
    return df


# ─────────────────────────────────────────────────────────
# 공급량 섹션들 (모든 표시 단위: GJ)
# ─────────────────────────────────────────────────────────
def supply_core_dashboard(month_df: pd.DataFrame, key_prefix: str = ""):
    st.markdown("## 📌 월간 핵심 대시보드 (공급량)")

    if month_df.empty:
        st.info("데이터가 없습니다.")
        return None

    plan_cols = [c for c in month_df.columns if c.startswith("계획(")]
    act_col = "실적_공급량(MJ)" if "실적_공급량(MJ)" in month_df.columns else None
    if act_col is None:
        st.info("월별 실적(MJ) 컬럼이 없어 핵심대시보드를 표시할 수 없어.")
        return None

    plan_choice = st.radio(
        "계획 기준 선택",
        options=plan_cols,
        index=0,
        horizontal=True,
        key=f"{key_prefix}plan_choice"
    )
    plan_label = "사업계획" if "사업계획" in plan_choice else "마케팅팀계획"

    long_dummy = month_df[["연", "월"]].copy()
    long_dummy["계획/실적"] = "실적"
    long_dummy["값"] = pd.to_numeric(month_df[act_col], errors="coerce")
    long_dummy = long_dummy.dropna(subset=["값"])

    sel_year, sel_month, agg_mode, years_all = render_section_selector(
        long_dummy, "월간 핵심 대시보드", key_prefix + "dash_base_"
    )
    mode_tag = "당월" if agg_mode == "당월" else "연도누적(연 누적)"

    this_period = month_df[month_df["연"] == sel_year].copy()
    if agg_mode == "당월":
        this_period = this_period[this_period["월"] == sel_month]
    else:
        this_period = this_period[this_period["월"] <= sel_month]

    plan_total_mj = this_period[plan_choice].sum(skipna=True)
    act_total_mj = this_period[act_col].sum(skipna=True)
    plan_total = plan_total_mj / 1000.0
    act_total = act_total_mj / 1000.0

    prev_year = sel_year - 1
    has_prev = prev_year in years_all
    if has_prev:
        prev_period = month_df[month_df["연"] == prev_year].copy()
        if agg_mode == "당월":
            prev_period = prev_period[prev_period["월"] == sel_month]
        else:
            prev_period = prev_period[prev_period["월"] <= sel_month]
        prev_total_mj = prev_period[act_col].sum(skipna=True)
        prev_total = prev_total_mj / 1000.0
    else:
        prev_total = np.nan

    plan_diff = act_total - plan_total if not pd.isna(plan_total) else np.nan
    plan_rate = (act_total / plan_total * 100.0) if (plan_total and plan_total > 0) else np.nan

    prev_diff = act_total - prev_total if not pd.isna(prev_total) else np.nan
    prev_rate = (act_total / prev_total * 100.0) if (prev_total and prev_total > 0) else np.nan

    st.markdown("<br>", unsafe_allow_html=True)
    k1, k2, k3 = st.columns(3)

    with k1:
        render_metric_card("📘", f"{plan_label} 계획 합계 (GJ)", fmt_num_safe(plan_total), "", color="#2563eb")

    with k2:
        sub2 = f"계획대비 차이 {fmt_num_safe(plan_diff)} · 달성률({mode_tag}) {fmt_rate(plan_rate)}"
        render_metric_card("📗", f"실적 합계 (GJ)", fmt_num_safe(act_total), sub2, color="#16a34a")

    with k3:
        if pd.isna(prev_total):
            main_prev = "-"
            sub3 = "전년 데이터 없음"
        else:
            main_prev = fmt_num_safe(prev_total)
            sub3 = f"전년대비 차이 {fmt_num_safe(prev_diff)} · 증감률({mode_tag}) {fmt_rate(prev_rate)}"
        render_metric_card("📙", f"전년 동월{' 누적' if agg_mode=='연 누적' else ''} 실적 (GJ)",
                           main_prev, sub3, color="#f97316")

    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("#### 🎯 달성률 요약")

    d1, d2, d3, d4, d5 = st.columns([1, 2, 1, 2, 1])
    with d2:
        render_rate_donut(plan_rate, "#16a34a", "계획 달성률")
        st.caption(f"({plan_label} · {mode_tag})")
    with d4:
        render_rate_donut(prev_rate, "#f97316", "전년대비 증감률")
        st.caption(f"({mode_tag})")

    st.markdown("<br>", unsafe_allow_html=True)
    return sel_year, sel_month, agg_mode, plan_choice, plan_label


def supply_monthly_trend(month_df: pd.DataFrame, plan_choice: str, plan_label: str, sel_month: int, key_prefix: str = ""):
    st.markdown("### 📈 월별 추이 (공급량)")

    if month_df.empty:
        st.info("데이터가 없습니다.")
        return

    years = sorted(month_df["연"].unique().tolist())
    base_year = pick_default_year(years)

    sel_years = st.multiselect(
        "연도 선택(그래프)",
        options=years,
        default=[y for y in [2023, 2024, 2025] if y in years] or [base_year],
        key=f"{key_prefix}supply_trend_years"
    )
    if not sel_years:
        st.info("연도를 한 개 이상 선택해 줘.")
        return

    base = month_df[month_df["연"].isin(sel_years)].copy()
    base = base[base["월"] <= sel_month]  

    act_col = "실적_공급량(MJ)"
    vals_mj = np.column_stack([base[act_col].values, base[plan_choice].values])
    vals_gj = vals_mj / 1000.0

    plot_df = pd.DataFrame({
        "연": np.repeat(base["연"].values, 2),
        "월": np.repeat(base["월"].values, 2),
        "구분": ["실적", "계획"] * len(base),
        "값": np.ravel(vals_gj),
    })

    plot_df["라벨"] = plot_df["연"].astype(str) + "년 · " + plot_df["구분"]

    fig = px.line(
        plot_df,
        x="월", y="값", color="라벨",
        line_dash="구분",
        line_dash_map={"실적": "solid", "계획": "dash"},
        markers=True
    )
    fig.update_layout(
        xaxis=dict(dtick=1),
        yaxis_title="공급량 (GJ)",
        legend_title="연도 / 구분",
        margin=dict(l=10, r=10, t=60, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.12, xanchor="right", x=1),
        title=f"{plan_label} 계획 vs 실적 (1~{sel_month}월 연 누적)"
    )
    st.plotly_chart(fig, use_container_width=True)


def supply_plan_vs_actual_monthly(month_df: pd.DataFrame, plan_choice: str, plan_label: str,
                                  sel_year: int, sel_month: int, key_prefix: str = ""):
    st.markdown("### 🧮 계획대비 월별 실적 (공급량)")

    if month_df.empty:
        st.info("데이터가 없습니다.")
        return

    act_col = "실적_공급량(MJ)"
    base_this = month_df[month_df["연"] == sel_year].copy()
    bars = (
        base_this[base_this["월"] <= sel_month]
        .sort_values("월")
        [["월", plan_choice, act_col]]
    )

    prev_year = sel_year - 1
    base_prev = month_df[month_df["연"] == prev_year].copy()
    base_prev = base_prev[base_prev["월"] <= sel_month][["월", act_col]].sort_values("월")

    plan_gj = bars[plan_choice] / 1000.0
    act_gj = bars[act_col] / 1000.0
    prev_gj = base_prev[act_col] / 1000.0 if not base_prev.empty else None

    fig = go.Figure()
    fig.add_bar(x=bars["월"], y=plan_gj, name=f"{sel_year} {plan_label} 계획", width=0.25, marker_color=COLOR_PLAN)
    fig.add_bar(x=bars["월"], y=act_gj, name=f"{sel_year} 실적", width=0.25, marker_color=COLOR_ACT)

    if not base_prev.empty:
        fig.add_bar(x=base_prev["월"], y=prev_gj, name=f"{prev_year} 실적", width=0.25, marker_color=COLOR_PREV)

    diff = act_gj.fillna(0.0) - plan_gj.fillna(0.0)
    fig.add_scatter(
        x=bars["월"], y=diff,
        mode="lines+markers+text",
        name="증감(실적-계획)", yaxis="y2",
        line=dict(color=COLOR_DIFF, width=2),
        marker=dict(color=COLOR_DIFF),
        text=[f"{v:,.0f}" for v in diff],
        textposition="top center",
        textfont=dict(size=11),
    )

    fig.update_layout(
        title=f"{sel_year}년 공급량 계획 vs 실적 (1~{sel_month}월 연 누적)",
        xaxis_title="월",
        yaxis_title="공급량 (GJ)",
        xaxis=dict(dtick=1),
        margin=dict(l=10, r=10, t=40, b=10),
        barmode="group",
        yaxis2=dict(title="증감(실적-계획) (GJ)", overlaying="y", side="right", showgrid=False),
    )
    st.plotly_chart(fig, use_container_width=True)


def supply_daily_plan_vs_actual_in_month(day_df: pd.DataFrame, month_df: pd.DataFrame,
                                         sel_year: int, sel_month: int,
                                         plan_choice: str, plan_label: str,
                                         key_prefix: str = ""):
    st.markdown("### ❄️ 일일계획량 대비 일별실적 (선택월)")

    if day_df.empty or month_df.empty:
        st.info("일별/월별 데이터가 부족해.")
        return

    act_col = "공급량(MJ)"
    if act_col not in day_df.columns:
        st.info("일별 공급량(MJ) 컬럼이 없어 표시할 수 없어.")
        return

    mrow = month_df[(month_df["연"] == sel_year) & (month_df["월"] == sel_month)]
    if mrow.empty:
        st.info("선택월 월별계획 데이터가 없어.")
        return

    month_plan_mj = float(mrow.iloc[0][plan_choice])
    days_in_month = int(pd.Timestamp(sel_year, sel_month, 1).days_in_month)
    daily_plan_mj = month_plan_mj / days_in_month
    daily_plan_gj = daily_plan_mj / 1000.0

    this_start = pd.Timestamp(sel_year, sel_month, 1)
    this_end = this_start + pd.offsets.MonthEnd(1)

    this_df = day_df[(day_df["일자"] >= this_start) & (day_df["일자"] <= this_end)].copy()
    if this_df.empty:
        st.info("선택한 월의 일별 실적이 없어.")
        return

    this_df["일"] = this_df["일자"].dt.day
    this_df["편차(실적-일계획)_GJ"] = (this_df[act_col] - daily_plan_mj) / 1000.0

    fig = go.Figure()
    fig.add_bar(
        x=this_df["일"], y=this_df[act_col] / 1000.0,
        name=f"{sel_year}년 {sel_month}월 일별실적",
        marker_color=COLOR_ACT, opacity=0.85
    )
    fig.add_scatter(
        x=this_df["일"], y=[daily_plan_gj] * len(this_df),
        mode="lines",
        name=f"일일계획량({plan_label})",
        line=dict(color=COLOR_PLAN, width=3, dash="dash")
    )

    fig.update_layout(
        title=f"{sel_year}년 {sel_month}월: 일별실적 vs 일일계획량(=월계획/{days_in_month}일)",
        xaxis_title="일",
        yaxis_title="공급량 (GJ)",
        xaxis=dict(dtick=1),
        margin=dict(l=10, r=10, t=50, b=10),
    )
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("##### 🔢 일별 편차 요약")
    show = this_df[["일자", act_col, "편차_GJ"]].copy()
    show.columns = ["일자", "일별실적(GJ)", "편차(실적-일계획)(GJ)"]
    show["일별실적(GJ)"] = show["일별실적(GJ)"].apply(lambda v: v / 1000.0)
    styled = center_style(
        show.style.format("{:,.1f}", subset=["일별실적(GJ)", "편차(실적-일계획)(GJ)"])
    )
    st.dataframe(styled, use_container_width=True, hide_index=True)


def _render_supply_top_card(rank: int, row: pd.Series, icon: str, gradient: str):
    date_str = f"{int(row['연'])}년 {int(row['월'])}월 {int(row['일'])}일"
    supply_str = f"{row['공급량_GJ']:,.1f} GJ"
    temp_str = f"{row['평균기온(℃)']:.1f}℃" if not pd.isna(row["평균기온(℃)"]) else "-"

    html = f"""
    <div style="
        border-radius:20px;
        padding:16px 20px;
        background:{gradient};
        box-shadow:0 4px 14px rgba(0,0,0,0.06);
        margin-top:8px;
    ">
      <div style="display:flex; align-items:center; gap:10px; margin-bottom:6px;">
        <div style="font-size:26px;">{icon}</div>
        <div style="font-size:15px; font-weight:700;">최대 공급량 기록 {rank}위</div>
      </div>
      <div style="font-size:14px; margin-bottom:3px;">
        📅 <b>{date_str}</b>
      </div>
      <div style="font-size:14px; margin-bottom:3px;">
        🔥 공급량: <b>{supply_str}</b>
      </div>
      <div style="font-size:14px;">
        🌡 평균기온: <b>{temp_str}</b>
      </div>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)


def supply_daily_tab(day_df: pd.DataFrame, month_df: pd.DataFrame,
                     sel_year: int, sel_month: int, plan_choice: str, plan_label: str,
                     key_prefix: str = ""):
    st.markdown("## 📅 공급량 분석(일)")

    if day_df.empty or month_df.empty:
        st.info("일별/월별 데이터가 부족해.")
        return

    act_col = "공급량(MJ)"
    if act_col not in day_df.columns:
        st.info("일별 공급량(MJ) 컬럼이 없어.")
        return

    df_all = day_df.copy()
    df_all["연"] = df_all["일자"].dt.year
    df_all["월"] = df_all["일자"].dt.month
    df_all["일"] = df_all["일자"].dt.day

    mrow = month_df[(month_df["연"] == sel_year) & (month_df["월"] == sel_month)]
    if mrow.empty:
        st.info("선택월 월별계획 데이터가 없어.")
        return

    month_plan_mj = float(mrow.iloc[0][plan_choice])
    days_in_month = int(pd.Timestamp(sel_year, sel_month, 1).days_in_month)
    daily_plan_mj = month_plan_mj / days_in_month
    daily_plan_gj = daily_plan_mj / 1000.0

    this_df = df_all[(df_all["연"] == sel_year) & (df_all["월"] == sel_month)].copy()

    st.markdown("### 📈 일별 패턴 비교(당년도 vs 과거동월)")

    cand_years = sorted(df_all["연"].unique().tolist())
    past_candidates = [y for y in cand_years if y < sel_year]
    past_recent_10 = past_candidates[-10:]

    default_past = [y for y in [sel_year - 1] if y in past_recent_10]

    try:
        past_years = st.segmented_control(
            "과거 연도 선택(동월 비교)",
            options=past_recent_10,
            selection_mode="multi",
            default=default_past,
            key=f"{key_prefix}past_years_{sel_year}_{sel_month}",
        )
    except Exception:
        past_years = st.multiselect(
            "과거 연도 선택(동월 비교)",
            options=past_recent_10,
            default=default_past,
            key=f"{key_prefix}past_years_ms_{sel_year}_{sel_month}",
        )

    fig1 = go.Figure()

    if not this_df.empty:
        fig1.add_scatter(
            x=this_df["일"],
            y=this_df[act_col] / 1000.0,
            mode="lines+markers",
            name=f"{sel_year}년 {sel_month}월 실적",
            line=dict(color=COLOR_ACT, width=3),
        )

    for y in past_years:
        sub = df_all[(df_all["연"] == y) & (df_all["월"] == sel_month)].copy()
        if sub.empty:
            continue
        fig1.add_scatter(
            x=sub["일"],
            y=sub[act_col] / 1000.0,
            mode="lines+markers",
            name=f"{y}년 {sel_month}월 실적",
            line=dict(width=1.5, dash="dot"),
        )

    fig1.add_scatter(
        x=list(range(1, days_in_month + 1)),
        y=[daily_plan_gj] * days_in_month,
        mode="lines",
        name=f"일일계획량({plan_label})",
        line=dict(color=COLOR_PLAN, width=3, dash="dot"),
    )

    fig1.update_layout(
        title=f"{sel_year}년 {sel_month}월 일별 공급량 패턴",
        xaxis_title="일",
        yaxis_title="공급량 (GJ)",
        xaxis=dict(dtick=1),
        margin=dict(l=10, r=10, t=50, b=10),
    )
    st.plotly_chart(fig1, use_container_width=True)

    if not this_df.empty:
        st.markdown("### 🧮 일일계획 대비 편차 (당년도)")
        this_df["편차_GJ"] = (this_df[act_col] - daily_plan_mj) / 1000.0

        fig2 = go.Figure()
        fig2.add_bar(
            x=this_df["일"],
            y=this_df["편차_GJ"],
            name="편차(실적-일계획)",
            marker_color=COLOR_DIFF,
        )
        fig2.add_hline(y=0, line_width=1, line_color="#999")

        fig2.update_layout(
            title=f"{sel_year}년 {sel_month}월 편차(실적-일계획)",
            xaxis_title="일",
            yaxis_title="편차 (GJ)",
            xaxis=dict(dtick=1),
            margin=dict(l=10, r=10, t=40, b=10),
        )
        st.plotly_chart(fig2, use_container_width=True)

        st.markdown("##### 🔢 일별 수치표")
        show = this_df[["일자", act_col, "편차_GJ"]].copy()
        show.columns = ["일자", "일별실적(GJ)", "편차(실적-일계획)(GJ)"]
        show["일별실적(GJ)"] = show["일별실적(GJ)"].apply(lambda v: v / 1000.0)
        styled = center_style(
            show.style.format("{:,.1f}", subset=["일별실적(GJ)", "편차(실적-일계획)(GJ)"])
        )
        st.dataframe(styled, use_container_width=True, hide_index=True)

    st.markdown("---")
    st.markdown("### 💎 일별 공급량 Top 랭킹")

    month_all = df_all[df_all["월"] == sel_month].copy()
    if month_all.empty:
        st.info("선택월에 해당하는 일별 데이터가 없어.")
    else:
        top_n = st.slider(
            "표시할 순위 개수 (선택월 & 전체기간)",
            min_value=5,
            max_value=50,
            value=10,
            step=5,
            key=f"{key_prefix}top_n_{sel_month}",
        )

        st.markdown("#### 📅 선택월 기준 Top 랭킹")
        month_all["공급량_GJ"] = month_all[act_col] / 1000.0
        rank_df = month_all.sort_values("공급량_GJ", ascending=False).head(top_n).copy()
        rank_df.insert(0, "Rank", range(1, len(rank_df) + 1))

        top3 = rank_df.head(3)
        c1, c2, c3 = st.columns(3)
        cols = [c1, c2, c3]
        icons = ["🥇", "🥈", "🥉"]
        grads = [
            "linear-gradient(120deg,#eff6ff,#fef9c3)",
            "linear-gradient(120deg,#f9fafb,#e5e7eb)",
            "linear-gradient(120deg,#fff7ed,#fef9c3)",
        ]
        for i, (_, row) in enumerate(top3.iterrows()):
            with cols[i]:
                _render_supply_top_card(int(row["Rank"]), row, icons[i], grads[i])

        show_rank = rank_df[
            ["Rank", "공급량_GJ", "연", "월", "일", "평균기온(℃)"]
        ].rename(
            columns={
                "공급량_GJ": "공급량(GJ)",
                "연": "연도",
                "월": "월",
                "일": "일",
                "평균기온(℃)": "평균기온(℃)",
            }
        )
        styled_rank = center_style(
            show_rank.style.format(
                {"공급량(GJ)": "{:,.1f}", "평균기온(℃)": "{:,.1f}"}
            )
        )
        st.markdown("<br>", unsafe_allow_html=True)
        st.dataframe(styled_rank, use_container_width=True, hide_index=True)

        st.markdown("---")
        st.markdown("#### 🏆 전체 기간 공급량 Top 랭킹 (역대 최고)")
        
        global_top = df_all.sort_values(act_col, ascending=False).head(top_n).copy()
        global_top["공급량_GJ"] = global_top[act_col] / 1000.0
        global_top.insert(0, "Rank", range(1, len(global_top) + 1))

        g_top3 = global_top.head(3)
        gc1, gc2, gc3 = st.columns(3)
        gcols = [gc1, gc2, gc3]
        for i, (_, row) in enumerate(g_top3.iterrows()):
            with gcols[i]:
                _render_supply_top_card(int(row["Rank"]), row, icons[i], grads[i])

        show_global = global_top[
            ["Rank", "공급량_GJ", "연", "월", "일", "평균기온(℃)"]
        ].rename(
            columns={
                "공급량_GJ": "공급량(GJ)",
                "연": "연도",
                "월": "월",
                "일": "일",
                "평균기온(℃)": "평균기온(℃)",
            }
        )
        styled_global = center_style(
            show_global.style.format(
                {"공급량(GJ)": "{:,.1f}", "평균기온(℃)": "{:,.1f}"}
            )
        )
        st.markdown("<br>", unsafe_allow_html=True)
        st.dataframe(styled_global, use_container_width=True, hide_index=True)

        st.markdown("#### 🌡️ 기온별 공급량 변화 (3차 다항식)")

        temp_supply = month_all.dropna(subset=["평균기온(℃)", act_col]).copy()
        if len(temp_supply) < 4:
            st.info("3차 다항식을 그리기 위한 데이터가 부족해.")
        else:
            x = temp_supply["평균기온(℃)"].values
            y = temp_supply[act_col].values / 1000.0

            coeffs = np.polyfit(x, y, 3)
            p = np.poly1d(coeffs)

            xs = np.linspace(x.min() - 1, x.max() + 1, 150)
            ys = p(xs)

            fig3 = go.Figure()
            fig3.add_scatter(
                x=x,
                y=y,
                mode="markers",
                name="일별 데이터",
                marker=dict(size=7, opacity=0.7),
            )
            fig3.add_scatter(
                x=xs,
                y=ys,
                mode="lines",
                name="3차 다항 회귀",
                line=dict(color=COLOR_DIFF, width=2),
            )
            fig3.update_layout(
                title=f"{sel_month}월 기온별 공급량 변화 (모든 연도)",
                xaxis_title="평균기온(℃)",
                yaxis_title="공급량 (GJ)",
                margin=dict(l=10, r=10, t=40, b=10),
            )
            st.plotly_chart(fig3, use_container_width=True)

    st.markdown("---")
    temperature_matrix(day_df, default_month=sel_month, key_prefix="tempD_")
    temperature_supply_band_section(day_df, default_month=sel_month, key_prefix="tempBandD_")


def temperature_matrix(day_df: pd.DataFrame, default_month: int = 10, key_prefix: str = "temp_"):
    st.markdown("### 🌡️ 기온 매트릭스 (일별 평균기온)")

    if day_df.empty or "평균기온(℃)" not in day_df.columns:
        st.info("기온 데이터가 없어.")
        return

    day_df = day_df.copy()
    day_df["연"] = day_df["일자"].dt.year
    day_df["월"] = day_df["일자"].dt.month
    day_df["일"] = day_df["일자"].dt.day

    years = sorted(day_df["연"].unique().tolist())
    min_y, max_y = years[0], years[-1]

    c1, c2 = st.columns([2, 1.2])
    with c1:
        yr_range = st.slider(
            "연도 범위",
            min_value=min_y, max_value=max_y,
            value=(min_y, max_y),
            step=1,
            key=f"{key_prefix}yr_range"
        )
    with c2:
        sel_m = st.selectbox(
            "월 선택",
            options=list(range(1, 13)),
            index=default_month - 1,
            key=f"{key_prefix}month"
        )

    sub = day_df[(day_df["연"].between(yr_range[0], yr_range[1])) & (day_df["월"] == sel_m)]
    if sub.empty:
        st.info("선택 범위에 데이터가 없어.")
        return

    pivot = sub.pivot_table(index="일", columns="연", values="평균기온(℃)", aggfunc="mean")
    pivot = pivot.reindex(range(1, 32))  
    avg_row = pivot.mean(axis=0).to_frame().T
    avg_row.index = ["평균"]
    pivot2 = pd.concat([pivot, avg_row], axis=0)

    fig = px.imshow(
        pivot2,
        aspect="auto",
        labels=dict(x="연도", y="일", color="°C"),
        color_continuous_scale="RdBu_r",
    )
    fig.update_layout(
        height=520,
        margin=dict(l=10, r=10, t=30, b=10),
        coloraxis_colorbar=dict(title="°C")
    )
    st.plotly_chart(fig, use_container_width=True)

    st.caption(f"{sel_m}월 기준 · 선택연도 {yr_range[0]}~{yr_range[1]}")


def temperature_supply_band_section(day_df: pd.DataFrame, default_month: int = 10, key_prefix: str = "tempBand_"):
    st.markdown("### 🔥 기온 구간별 평균 공급량 분석")

    act_col = "공급량(MJ)"
    if day_df.empty or "평균기온(℃)" not in day_df.columns or act_col not in day_df.columns:
        st.info("기온 또는 공급량 데이터가 없어.")
        return

    df = day_df.copy()
    df["연"] = df["일자"].dt.year
    df["월"] = df["일자"].dt.month

    years = sorted(df["연"].unique().tolist())
    min_y, max_y = years[0], years[-1]

    c1, c2 = st.columns([2, 1.2])
    with c1:
        yr_range = st.slider(
            "연도 범위(공급량 분석)",
            min_value=min_y, max_value=max_y,
            value=(max(min_y, max_y - 4), max_y),
            step=1,
            key=f"{key_prefix}yr_range"
        )
    with c2:
        sel_m = st.selectbox(
            "월 선택(공급량 분석)",
            options=list(range(1, 13)),
            index=default_month - 1,
            key=f"{key_prefix}month"
        )

    sub = df[(df["연"].between(yr_range[0], yr_range[1])) & (df["월"] == sel_m)]
    sub = sub.dropna(subset=["평균기온(℃)", act_col])
    if sub.empty:
        st.info("선택 범위에 공급량/기온 데이터가 없어.")
        return

    bins = [-100, -10, -5, 0, 5, 10, 15, 20, 25, 30, 100]
    labels = [
        "<-10℃", "-10~-5℃", "-5~0℃",
        "0~5℃", "5~10℃", "10~15℃", "15~20℃", "20~25℃", "25~30℃", "≥30℃"
    ]
    sub["기온구간"] = pd.cut(sub["평균기온(℃)"], bins=bins, labels=labels, right=False)

    grp = sub.groupby("기온구간", as_index=False).agg(
        평균공급량_GJ=(act_col, lambda x: x.mean() / 1000.0),
        일수=(act_col, "count"),
    )

    grp = grp.dropna(subset=["기온구간"])

    fig = px.bar(
        grp,
        x="기온구간",
        y="평균공급량_GJ",
        text="일수",
    )
    fig.update_layout(
        xaxis_title="기온 구간",
        yaxis_title="평균 공급량 (GJ)",
        margin=dict(l=10, r=10, t=40, b=10),
    )
    fig.update_traces(texttemplate="%{text}일", textposition="outside")
    st.plotly_chart(fig, use_container_width=True)

    styled_grp = center_style(
        grp.rename(columns={"평균공급량_GJ": "평균공급량(GJ)"})
        .style.format({"평균공급량(GJ)": "{:,.1f}"})
    )
    st.dataframe(styled_grp, use_container_width=True, hide_index=True)


# ─────────────────────────────────────────────────────────
# 메인 레이아웃 (좌측탭 구성)
# ─────────────────────────────────────────────────────────
st.title("도시가스 계획 / 실적 분석")

with st.sidebar:
    st.header("📌 분석 탭")
    main_tab = st.radio(
        "분석 항목",
        ["판매량 분석", "공급량 분석(월)", "공급량 분석(일)", "분기별 판매량 보고서"],
        index=0,
        key="main_tab"
    )

    st.markdown("---")
    st.header("📂 데이터 불러오기")

    # 판매량 파일
    if main_tab == "판매량 분석":
        src = st.radio("데이터 소스", ["레포 파일 사용", "엑셀 업로드(.xlsx)"], index=0, key="sales_src")
        excel_bytes = None
        base_info = ""
        if src == "엑셀 업로드(.xlsx)":
            up = st.file_uploader("판매량(계획_실적).xlsx 형식", type=["xlsx"], key="sales_uploader")
            if up is not None:
                excel_bytes = up.getvalue()
                base_info = f"소스: 업로드 파일 — {up.name}"
        else:
            path = Path(__file__).parent / DEFAULT_SALES_XLSX
            if path.exists():
                excel_bytes = path.read_bytes()
                base_info = f"소스: 레포 파일 — {DEFAULT_SALES_XLSX}"
            else:
                base_info = f"레포 경로에 {DEFAULT_SALES_XLSX} 파일이 없습니다."

        st.caption(base_info)

    # 공급량 파일
    elif main_tab in ["공급량 분석(월)", "공급량 분석(일)"]:
        src = st.radio("데이터 소스", ["레포 파일 사용", "엑셀 업로드(.xlsx)"], index=0, key="supply_src")
        supply_bytes = None
        supply_info = ""
        if src == "엑셀 업로드(.xlsx)":
            up = st.file_uploader("공급량(계획_실적).xlsx 형식", type=["xlsx"], key="supply_uploader")
            if up is not None:
                supply_bytes = up.getvalue()
                supply_info = f"소스: 업로드 파일 — {up.name}"
        else:
            path = Path(__file__).parent / DEFAULT_SUPPLY_XLSX
            if path.exists():
                supply_bytes = path.read_bytes()
                supply_info = f"소스: 레포 파일 — {DEFAULT_SUPPLY_XLSX}"
            else:
                supply_info = f"레포 경로에 {DEFAULT_SUPPLY_XLSX} 파일이 없습니다."

        st.caption(supply_info)

    # 분기별 판매량 보고서
    elif main_tab == "분기별 판매량 보고서":
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
                    try:
                        df_list.append(pd.read_csv(io.BytesIO(f.getvalue()), encoding="utf-8-sig"))
                    except:
                        try:
                            df_list.append(pd.read_csv(io.BytesIO(f.getvalue()), encoding="cp949"))
                        except:
                            pass
                if df_list:
                    st.session_state['merged_csv_df'] = pd.concat(df_list, ignore_index=True)
                csv_info = f"소스: 업로드 파일 {len(up_csvs)}개 병합 완료"
            else:
                if 'merged_csv_df' in st.session_state:
                    del st.session_state['merged_csv_df']
        else:
            path_csv = Path(__file__).parent / DEFAULT_CSV
            if path_csv.exists():
                csv_info = f"소스: 레포 파일 전체 자동 스캔 중..."
            else:
                csv_info = f"레포 경로에 {DEFAULT_CSV} 파일이 없습니다."
        st.caption(csv_info)


# ─────────────────────────────────────────────────────────
# 1) 판매량 분석
# ─────────────────────────────────────────────────────────
if main_tab == "판매량 분석":
    st.markdown("## 1) 판매량 계획 / 실적 분석")

    long_dict: Dict[str, pd.DataFrame] = {}
    if 'excel_bytes' in locals() and excel_bytes is not None:
        sheets = load_all_sheets(excel_bytes)
        long_dict = build_long_dict(sheets)

    tab_labels: List[str] = []
    if "부피" in long_dict:
        tab_labels.append("부피 기준 (천m³)")
    if "열량" in long_dict:
        tab_labels.append("열량 기준 (GJ)")

    if not tab_labels:
        st.info("유효한 시트를 찾지 못했어. 파일 시트명을 확인해 줘.")
    else:
        tabs = st.tabs(tab_labels)
        for tab_label, tab in zip(tab_labels, tabs):
            with tab:
                if tab_label.startswith("부피"):
                    df_long = long_dict.get("부피", pd.DataFrame())
                    unit = "천m³"
                    prefix = "sales_vol_"
                else:
                    df_long = long_dict.get("열량", pd.DataFrame()).copy()
                    unit = "GJ"
                    prefix = "sales_gj_"

                monthly_core_dashboard(df_long, unit_label=unit, key_prefix=prefix + "dash_")

                st.markdown("---")

                st.markdown("## 📊 실적 분석")
                monthly_trend_section(df_long, unit_label=unit, key_prefix=prefix + "trend_")
                half_year_stacked_section(df_long, unit_label=unit, key_prefix=prefix + "stack_")

                st.markdown("---")

                st.markdown("## 📏 계획대비 분석")
                yearly_summary_section(df_long, unit_label=unit, key_prefix=prefix + "summary_")
                plan_vs_actual_usage_section(df_long, unit_label=unit, key_prefix=prefix + "pv_")


# ─────────────────────────────────────────────────────────
# 2) 공급량 분석(월)
# ─────────────────────────────────────────────────────────
elif main_tab == "공급량 분석(월)":
    st.markdown("## 2) 공급량 분석(월)")

    if 'supply_bytes' not in locals() or supply_bytes is None:
        st.info("공급량 파일을 불러오면 분석이 표시돼.")
    else:
        month_df, day_df = load_supply_sheets(supply_bytes)
        month_df = clean_supply_month_df(month_df)
        day_df = clean_supply_day_df(day_df)

        if month_df.empty:
            st.info("월별계획_실적 시트가 비어있어.")
        else:
            core = supply_core_dashboard(month_df, key_prefix="supplyM_")
            if core is not None:
                sel_year, sel_month, agg_mode, plan_choice, plan_label = core

                st.markdown("---")

                supply_monthly_trend(
                    month_df, plan_choice, plan_label, sel_month,
                    key_prefix="supplyM_"
                )

                st.markdown("---")

                supply_plan_vs_actual_monthly(
                    month_df, plan_choice, plan_label, sel_year, sel_month,
                    key_prefix="supplyM_"
                )

                st.markdown("---")

                supply_daily_plan_vs_actual_in_month(
                    day_df, month_df,
                    sel_year, sel_month,
                    plan_choice, plan_label,
                    key_prefix="supplyM_"
                )

                st.markdown("---")

                temperature_matrix(day_df, default_month=sel_month, key_prefix="tempM_")


# ─────────────────────────────────────────────────────────
# 3) 공급량 분석(일)
# ─────────────────────────────────────────────────────────
elif main_tab == "공급량 분석(일)":
    st.markdown("## 3) 공급량 분석(일)")

    if 'supply_bytes' not in locals() or supply_bytes is None:
        st.info("공급량 파일을 불러오면 분석이 표시돼.")
    else:
        month_df, day_df = load_supply_sheets(supply_bytes)
        month_df = clean_supply_month_df(month_df)
        day_df = clean_supply_day_df(day_df)

        if month_df.empty or day_df.empty:
            st.info("월별/일별 시트 중 하나가 비어있어.")
        else:
            plan_cols = [c for c in month_df.columns if c.startswith("계획(")]
            plan_choice = st.radio(
                "계획 기준 선택",
                options=plan_cols,
                index=0,
                horizontal=True,
                key="supplyD_plan_choice"
            )
            plan_label = "사업계획" if "사업계획" in plan_choice else "마케팅팀계획"

            act_col = "실적_공급량(MJ)"
            long_dummy = month_df[["연", "월"]].copy()
            long_dummy["계획/실적"] = "실적"
            long_dummy["값"] = pd.to_numeric(month_df[act_col], errors="coerce")
            long_dummy = long_dummy.dropna(subset=["값"])

            sel_year, sel_month, agg_mode, years_all = render_section_selector(
                long_dummy, "공급량(일) 기준 선택", "supplyD_base_",
                fixed_mode="당월", show_mode=False
            )

            st.markdown("---")
            supply_daily_tab(
                day_df, month_df,
                sel_year, sel_month,
                plan_choice, plan_label,
                key_prefix="supplyD_"
            )


# ─────────────────────────────────────────────────────────
# 4) 분기별 판매량 보고서 (One Page Report 형태)
# ─────────────────────────────────────────────────────────
elif main_tab == "분기별 판매량 보고서":
    st.markdown("## 📑 분기별 판매량 보고서")
    
    long_dict_rpt: Dict[str, pd.DataFrame] = {}
    if 'excel_bytes' in locals() and excel_bytes is not None:
        sheets_rpt = load_all_sheets(excel_bytes)
        long_dict_rpt = build_long_dict(sheets_rpt)
        
    df_csv = pd.DataFrame()
    
    if src_csv == "레포 파일 사용":
        repo_dir = Path(__file__).parent
        all_csvs = list(repo_dir.glob("*가정용외*.csv")) + list(repo_dir.glob("가정용외*.csv"))
        all_csvs = list(set(all_csvs)) 
        csv_list = []
        for p in all_csvs:
            try:
                csv_list.append(pd.read_csv(p, encoding="utf-8-sig"))
            except:
                try:
                    csv_list.append(pd.read_csv(p, encoding="cp949"))
                except:
                    pass
        if csv_list:
            df_csv = pd.concat(csv_list, ignore_index=True)
    
    if df_csv.empty and 'merged_csv_df' in st.session_state:
        df_csv = st.session_state['merged_csv_df'].copy()
        
    if not df_csv.empty:
        if "사용량(mj)" in df_csv.columns:
            df_csv["사용량(mj)"] = pd.to_numeric(df_csv["사용량(mj)"].astype(str).str.replace(",", ""), errors="coerce").fillna(0)
        if "사용량(m3)" in df_csv.columns:
            df_csv["사용량(m3)"] = pd.to_numeric(df_csv["사용량(m3)"].astype(str).str.replace(",", ""), errors="coerce").fillna(0)
            
    comments_db = load_comments_db()
            
    rpt_tabs = st.tabs(["부피 기준 (천m³)", "열량 기준 (GJ)"])
    
    for idx, rpt_tab in enumerate(rpt_tabs):
        with rpt_tab:
            if idx == 0:
                df_long_rpt = long_dict_rpt.get("부피", pd.DataFrame())
                unit_str = "천m³"
                val_col = "사용량(m3)"
                key_sfx = "_vol"
            else:
                df_long_rpt = long_dict_rpt.get("열량", pd.DataFrame())
                unit_str = "GJ"
                val_col = "사용량(mj)"
                key_sfx = "_gj"

            st.markdown("#### 📅 보고서 기준 일자") 
            
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
                    
            if not df_csv.empty:
                df_csv["날짜_파싱"] = pd.NaT
                
                # [수정] 총량 불일치의 원인이었던 '검침적용일자', '상품계약일자' 등 엉뚱한 과거 날짜 배제
                # 사용자가 요청한 '청구년월'을 최우선으로 매출 기준 년월만 엄격하게 스캔
                for date_column in ["청구년월", "매출년월", "년월", "기준년월"]:
                    if date_column in df_csv.columns:
                        mask1 = df_csv["날짜_파싱"].isna()
                        if mask1.any():
                            df_csv.loc[mask1, "날짜_파싱"] = pd.to_datetime(df_csv.loc[mask1, date_column], format="%b-%y", errors="coerce")
                        
                        mask2 = df_csv["날짜_파싱"].isna()
                        if mask2.any():
                            df_csv.loc[mask2, "날짜_파싱"] = pd.to_datetime(df_csv.loc[mask2, date_column], format="%Y%m", errors="coerce")
                            
                        mask3 = df_csv["날짜_파싱"].isna()
                        if mask3.any():
                            df_csv.loc[mask3, "날짜_파싱"] = pd.to_datetime(df_csv.loc[mask3, date_column], errors="coerce")

                df_csv["연_csv"] = df_csv["날짜_파싱"].dt.year.fillna(years_available[default_y_index])
                df_csv["월_csv"] = df_csv["날짜_파싱"].dt.month.fillna(1)
            
            c_y, c_q, c_empty = st.columns([1, 1, 2])
            with c_y:
                sel_year_rpt = st.selectbox("기준 연도", years_available, index=default_y_index, key=f"rpt_yr{key_sfx}")
            with c_q:
                sel_quarter = st.selectbox("기준 분기", ["1Q (1~3월)", "2Q (1~6월 누적)", "3Q (1~9월 누적)", "4Q (1~12월 누적)"], index=default_q_index, key=f"rpt_qt{key_sfx}")
            
            max_month = int(sel_quarter[0]) * 3 
            
            report_db_key = f"{sel_year_rpt}_{sel_quarter[:2]}_{unit_str}"
            if report_db_key not in comments_db:
                comments_db[report_db_key] = {}
            curr_db = comments_db[report_db_key]
            
            st.markdown("<hr style='margin: 10px 0 30px 0;'>", unsafe_allow_html=True)

            # --- 2. At a Glance ---
            st.markdown("#### 💡 1. At a Glance")
            
            if not df_long_rpt.empty:
                df_base = df_long_rpt[(df_long_rpt["연"].isin([sel_year_rpt, sel_year_rpt-1])) & (df_long_rpt["월"] <= max_month)]
                
                total_curr_plan = df_base[(df_base["연"] == sel_year_rpt) & (df_base["계획/실적"] == "계획")]["값"].sum()
                total_curr_act = df_base[(df_base["연"] == sel_year_rpt) & (df_base["계획/실적"] == "실적")]["값"].sum()
                total_prev_act = df_base[(df_base["연"] == sel_year_rpt-1) & (df_base["계획/실적"] == "실적")]["값"].sum()
                
                achieve_rate_plan = (total_curr_act / total_curr_plan * 100) if total_curr_plan else 0
                achieve_rate_prev = (total_curr_act / total_prev_act * 100) if total_prev_act else 0
                
                col_m1, col_m2, col_m3, col_d1, col_d2 = st.columns([1.1, 1.25, 1.25, 0.7, 0.7])
                with col_m1:
                    render_metric_card("🎯", f"{sel_year_rpt}년 계획", f"{fmt_num_safe(total_curr_plan)} {unit_str}", "", COLOR_PLAN)
                with col_m2:
                    sign_plan = "+" if total_curr_act - total_curr_plan > 0 else ""
                    render_metric_card("🔥", f"{sel_year_rpt}년 실적", f"{fmt_num_safe(total_curr_act)} {unit_str}", f"차이: {sign_plan}{fmt_num_safe(total_curr_act - total_curr_plan)} {unit_str} ({achieve_rate_plan:.1f}%, 계획대비)", COLOR_ACT)
                with col_m3:
                    sign_prev = "+" if total_curr_act - total_prev_act > 0 else ""
                    render_metric_card("🔄", f"{sel_year_rpt-1}년 실적", f"{fmt_num_safe(total_prev_act)} {unit_str}", f"차이: {sign_prev}{fmt_num_safe(total_curr_act - total_prev_act)} {unit_str} ({achieve_rate_prev:.1f}%, 전년대비)", COLOR_PREV)
                with col_d1:
                    render_rate_donut(achieve_rate_plan, COLOR_ACT, "계획대비 달성률")
                with col_d2:
                    render_rate_donut(achieve_rate_prev, COLOR_PREV, "전년대비 증감률")

            render_comment_section("📝 분기 핵심 요약 작성", "glance", curr_db, comments_db, 120, f"예: {sel_year_rpt}년 {sel_quarter[:2]} 누적 총 판매량은 OO {unit_str}로 계획대비 O% 달성. 주요 특이사항은... (자유롭게 입력하세요)", f"glance_{key_sfx}")
            
            st.markdown("<hr style='margin: 30px 0;'>", unsafe_allow_html=True)

            # --- 3. 전체 판매량 표 정리 & One Page Review ---
            st.markdown("#### 📊 2. 전체 판매량 요약 및 주요 증감 원인 (One Page Review)")
            if not df_long_rpt.empty:
                curr_plan = df_base[(df_base["연"] == sel_year_rpt) & (df_base["계획/실적"] == "계획")].groupby("그룹")["값"].sum()
                curr_act = df_base[(df_base["연"] == sel_year_rpt) & (df_base["계획/실적"] == "실적")].groupby("그룹")["값"].sum()
                prev_act = df_base[(df_base["연"] == sel_year_rpt-1) & (df_base["계획/실적"] == "실적")].groupby("그룹")["값"].sum()
                
                summary_df = pd.DataFrame({
                    f"{sel_year_rpt}년 계획": curr_plan,
                    f"{sel_year_rpt}년 실적": curr_act,
                    f"{sel_year_rpt-1}년 실적": prev_act
                }).fillna(0)
                
                summary_df["계획대비 차이"] = summary_df[f"{sel_year_rpt}년 실적"] - summary_df[f"{sel_year_rpt}년 계획"]
                summary_df["달성률(%)"] = np.where(summary_df[f"{sel_year_rpt}년 계획"] > 0, (summary_df[f"{sel_year_rpt}년 실적"] / summary_df[f"{sel_year_rpt}년 계획"]) * 100, 0)
                summary_df["전년대비 증감률(%)"] = np.where(summary_df[f"{sel_year_rpt-1}년 실적"] > 0, (summary_df[f"{sel_year_rpt}년 실적"] / summary_df[f"{sel_year_rpt-1}년 실적"]) * 100, 0)
                
                total_row = summary_df.sum(numeric_only=True)
                total_row["달성률(%)"] = (total_row[f"{sel_year_rpt}년 실적"] / total_row[f"{sel_year_rpt}년 계획"]) * 100 if total_row[f"{sel_year_rpt}년 계획"] else 0
                total_row["전년대비 증감률(%)"] = (total_row[f"{sel_year_rpt}년 실적"] / total_row[f"{sel_year_rpt-1}년 실적"]) * 100 if total_row[f"{sel_year_rpt-1}년 실적"] else 0
                
                summary_df.loc["💡 합계"] = total_row
                summary_df = summary_df.reset_index().rename(columns={"index": "용도"})
                
                st.dataframe(
                    center_style(
                        summary_df.style.format({
                            f"{sel_year_rpt}년 계획": "{:,.0f}", f"{sel_year_rpt}년 실적": "{:,.0f}", f"{sel_year_rpt-1}년 실적": "{:,.0f}",
                            "계획대비 차이": "{:,.0f}", "달성률(%)": "{:,.1f}", "전년대비 증감률(%)": "{:,.1f}"
                        }).apply(highlight_subtotal, axis=1)
                    ), 
                    use_container_width=True, hide_index=True
                )
            else:
                st.warning("👈 좌측 사이드바에서 판매량(.xlsx) 파일을 업로드하거나 레포 파일을 사용해 주세요.")
                
            render_comment_section("📝 주요 증감 원인 작성 (One Page Review)", "review", curr_db, comments_db, 150, "표를 바탕으로 전체적인 실적 증감 원인을 종합적으로 분석해 주세요.", f"review_{key_sfx}")

            st.markdown("<hr style='margin: 30px 0;'>", unsafe_allow_html=True)

            # --- 4, 5, 6. 용도별 판매량 분석 ---
            def render_usage_trend_report(usage_name, section_num, key_sfx, db_key):
                
                if df_long_rpt.empty:
                    st.markdown(f"#### 📈 {section_num}. 용도별 판매량 분석 : {usage_name}")
                    st.info("판매량 데이터가 없습니다.")
                    return ""
                else:
                    df_u = df_long_rpt[(df_long_rpt["그룹"] == usage_name) & (df_long_rpt["월"] <= max_month)]
                    
                    p_curr_plan = df_u[(df_u["연"] == sel_year_rpt) & (df_u["계획/실적"] == "계획")].groupby("월")["값"].sum()
                    p_curr_act = df_u[(df_u["연"] == sel_year_rpt) & (df_u["계획/실적"] == "실적")].groupby("월")["값"].sum()
                    p_prev_act = df_u[(df_u["연"] == sel_year_rpt-1) & (df_u["계획/실적"] == "실적")].groupby("월")["값"].sum()
                    
                    sum_plan = p_curr_plan.sum()
                    sum_act = p_curr_act.sum()
                    sum_prev = p_prev_act.sum()
                    
                    diff_prev = sum_act - sum_prev
                    rate_prev = (sum_act / sum_prev * 100) if sum_prev > 0 else 0
                    sign_prev = "+" if diff_prev > 0 else ""
                    
                    st.markdown(
                        f"""
                        <div style="display: flex; align-items: center; gap: 15px; margin-bottom: 10px;">
                            <h4 style="margin: 0;">📈 {section_num}. 용도별 판매량 분석 : {usage_name}</h4>
                        </div>
                        """, unsafe_allow_html=True
                    )
                    
                    months_list = list(range(1, max_month + 1))
                    col_c, col_m = st.columns([1, 2.5])
                    
                    with col_c:
                        st.markdown(f"**■ 누적 실적 비교 ({sel_quarter[:2]})**")
                        st.markdown(
                            f"""
                            <div style="background-color: #e2e8f0; border-left: 5px solid #1e3a8a; padding: 10px 10px; margin-bottom: 0px; border-radius: 4px; box-shadow: 0 1px 3px rgba(0,0,0,0.1);">
                                <div style="font-size: 14.5px; color: #1e3a8a; font-weight: 700; line-height: 1.5;">
                                    판매량: {sum_act:,.0f} {unit_str}<br>
                                    전년대비: {sign_prev}{diff_prev:,.0f} ({rate_prev:.1f}%)
                                </div>
                            </div>
                            """, unsafe_allow_html=True
                        )
                        
                        fig_c = go.Figure()
                        fig_c.add_trace(go.Bar(x=[f"{sel_year_rpt}년<br>계획", f"{sel_year_rpt}년<br>실적", f"{sel_year_rpt-1}년<br>실적"],
                                               y=[sum_plan, sum_act, sum_prev],
                                               marker_color=[COLOR_PLAN, COLOR_ACT, COLOR_PREV],
                                               text=[f"{sum_plan:,.0f}", f"{sum_act:,.0f}", f"{sum_prev:,.0f}"],
                                               textposition='auto', textfont=dict(size=14)))
                        fig_c.update_layout(margin=dict(t=25, b=10, l=10, r=10), height=420, showlegend=False)
                        st.plotly_chart(fig_c, use_container_width=True)
                        
                    with col_m:
                        st.markdown("**■ 월별 실적 비교**")
                        st.markdown("<div style='padding: 1px; margin-bottom: 27px; line-height: 1.5;'>&nbsp;<br>&nbsp;</div>", unsafe_allow_html=True)
                        
                        fig_m = go.Figure()
                        
                        vals_plan = [p_curr_plan.get(m, 0) for m in months_list]
                        vals_act = [p_curr_act.get(m, 0) for m in months_list]
                        vals_prev = [p_prev_act.get(m, 0) for m in months_list]
                        
                        fig_m.add_trace(go.Bar(x=months_list, y=vals_plan, name=f'{sel_year_rpt}년 계획', marker_color=COLOR_PLAN, text=[f"{v:,.0f}" if v>0 else "" for v in vals_plan], textposition='auto', textfont=dict(size=11)))
                        fig_m.add_trace(go.Bar(x=months_list, y=vals_act, name=f'{sel_year_rpt}년 실적', marker_color=COLOR_ACT, text=[f"{v:,.0f}" if v>0 else "" for v in vals_act], textposition='auto', textfont=dict(size=11)))
                        fig_m.add_trace(go.Bar(x=months_list, y=vals_prev, name=f'{sel_year_rpt-1}년 실적', marker_color=COLOR_PREV, text=[f"{v:,.0f}" if v>0 else "" for v in vals_prev], textposition='auto', textfont=dict(size=11)))
                        
                        fig_m.update_layout(barmode='group', xaxis=dict(tickmode='linear', tick0=1, dtick=1), xaxis_title="월", yaxis_title=f"판매량({unit_str})", margin=dict(t=10, b=10, l=10, r=10), height=420, legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
                        st.plotly_chart(fig_m, use_container_width=True)
                        
                    # 산업용, 업무용인 경우 하단에 세부 업종별 그래프 추가 (엑셀 100% 정합성 반영)
                    if usage_name in ["산업용", "업무용"] and not df_csv.empty and val_col in df_csv.columns:
                        st.markdown(f"**■ 세부 업종별 판매량 비교 (당해연도 vs 전년도)**")
                        
                        if usage_name == "산업용":
                            df_sub_filtered = df_csv[(df_csv["상품명"].astype(str).str.contains("산업용", na=False)) & (df_csv["월_csv"] <= max_month)].copy()
                            grp_col = "업종"
                        else: 
                            df_sub_filtered = df_csv[(df_csv["상품명"].astype(str).str.contains("업무난방용|냉난방용|냉방용|주한미군", na=False, regex=True)) & (df_csv["월_csv"] <= max_month)].copy()
                            if "업종분류" in df_sub_filtered.columns:
                                df_sub_filtered["업종"] = df_sub_filtered["업종분류"]
                            grp_col = "업종"
                            
                        if not df_sub_filtered.empty and grp_col in df_sub_filtered.columns:
                            curr_ind_grp = df_sub_filtered[df_sub_filtered["연_csv"] == sel_year_rpt].groupby(grp_col, as_index=False)[val_col].sum().rename(columns={val_col: f"{sel_year_rpt}년"})
                            prev_ind_grp = df_sub_filtered[df_sub_filtered["연_csv"] == sel_year_rpt - 1].groupby(grp_col, as_index=False)[val_col].sum().rename(columns={val_col: f"{sel_year_rpt-1}년"})
                            
                            ind_comp = pd.merge(curr_ind_grp, prev_ind_grp, on=grp_col, how="outer").fillna(0)
                            ind_comp["증감절대값"] = abs(ind_comp[f"{sel_year_rpt}년"] - ind_comp[f"{sel_year_rpt-1}년"])
                            
                            ind_comp = ind_comp.sort_values(f"{sel_year_rpt}년", ascending=False).reset_index(drop=True)
                            
                            if len(ind_comp) > 10:
                                top10_df = ind_comp.iloc[:10].copy()
                                others_df = ind_comp.iloc[10:].copy()
                                
                                others_row = pd.DataFrame([{
                                    grp_col: "기타", 
                                    f"{sel_year_rpt}년": others_df[f"{sel_year_rpt}년"].sum(), 
                                    f"{sel_year_rpt-1}년": others_df[f"{sel_year_rpt-1}년"].sum(),
                                    "증감절대값": abs(others_df[f"{sel_year_rpt}년"].sum() - others_df[f"{sel_year_rpt-1}년"].sum())
                                }])
                                ind_comp_plot = pd.concat([top10_df, others_row], ignore_index=True)
                            else:
                                ind_comp_plot = ind_comp.copy()
                                
                            max_diff_idx = ind_comp_plot["증감절대값"].idxmax()
                            
                            colors_act = [COLOR_ACT] * len(ind_comp_plot)
                            if pd.notna(max_diff_idx):
                                colors_act[max_diff_idx] = "#d32f2f" 
                                
                            fig_ind = go.Figure()
                            fig_ind.add_trace(go.Bar(x=ind_comp_plot[grp_col], y=ind_comp_plot[f"{sel_year_rpt}년"], name=f'{sel_year_rpt}년', marker_color=colors_act, text=[f"{v:,.0f}" if v>0 else "" for v in ind_comp_plot[f"{sel_year_rpt}년"]], textposition='auto', textfont=dict(size=11)))
                            fig_ind.add_trace(go.Bar(x=ind_comp_plot[grp_col], y=ind_comp_plot[f"{sel_year_rpt-1}년"], name=f'{sel_year_rpt-1}년', marker_color=COLOR_PREV, text=[f"{v:,.0f}" if v>0 else "" for v in ind_comp_plot[f"{sel_year_rpt-1}년"]], textposition='auto', textfont=dict(size=11)))
                            
                            fig_ind.update_layout(barmode='group', xaxis_title="", yaxis_title=f"판매량({unit_str})", margin=dict(t=10, b=10, l=10, r=10), height=420, legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
                            st.plotly_chart(fig_ind, use_container_width=True)
                        else:
                            st.info("해당 용도의 세부 업종 데이터가 없습니다.")
                    
                render_comment_section(f"📝 {usage_name} 세부 코멘트 작성", db_key, curr_db, comments_db, 100, f"{usage_name}의 월별 편차 원인 및 특이사항을 기록하세요.", f"{usage_name}_{key_sfx}")
                st.markdown("<br>", unsafe_allow_html=True)

            render_usage_trend_report("가정용", 3, key_sfx, "home")
            render_usage_trend_report("산업용", 4, key_sfx, "ind")
            render_usage_trend_report("업무용", 5, key_sfx, "biz")

            st.markdown("<hr style='margin: 30px 0;'>", unsafe_allow_html=True)

            # --- 7, 8. 별첨 (업종별 비교표 & Top 30) ---
            st.markdown("#### 📎 6~7. 별첨 (업종별 상세 현황)")
            
            if df_csv.empty or val_col not in df_csv.columns:
                st.warning(f"⚠️ 업종별 상세 데이터를 보려면 '{unit_str}' 단위에 맞는 데이터({val_col} 컬럼 포함)를 CSV로 다중 업로드해주세요.")
            else:
                def render_attachment_report(usage_label, section_num, key_sfx):
                    st.markdown(f"##### 🏭 {section_num}. 별첨 ({usage_label})")
                    
                    # [수정] 엑셀의 용도 그룹핑과 동일한 로직 적용을 위한 CSV 필터링 강화
                    if usage_label == "산업용":
                        df_sub = df_csv[df_csv["상품명"].astype(str).str.contains("산업용", na=False)].copy()
                    else: 
                        df_sub = df_csv[df_csv["상품명"].astype(str).str.contains("업무난방용|냉난방용|냉방용|주한미군", na=False, regex=True)].copy()
                        if "업종분류" in df_sub.columns:
                            df_sub["업종"] = df_sub["업종분류"]
                    
                    if df_sub.empty:
                        st.info(f"업로드된 CSV 내에 '{usage_label}' 용도 데이터가 존재하지 않습니다.")
                        return
                    
                    df_sub_filtered = df_sub[df_sub["월_csv"] <= max_month]
                        
                    st.markdown(f"**■ 🏢 {usage_label} 세부 업종별 비교표**")
                    if "업종" in df_sub_filtered.columns:
                        curr_ind_grp = df_sub_filtered[df_sub_filtered["연_csv"] == sel_year_rpt].groupby("업종", as_index=False)[val_col].sum().rename(columns={val_col: f"{sel_year_rpt}년"})
                        prev_ind_grp = df_sub_filtered[df_sub_filtered["연_csv"] == sel_year_rpt - 1].groupby("업종", as_index=False)[val_col].sum().rename(columns={val_col: f"{sel_year_rpt-1}년"})
                        
                        ind_comp = pd.merge(curr_ind_grp, prev_ind_grp, on="업종", how="outer").fillna(0)
                        ind_comp["증감"] = ind_comp[f"{sel_year_rpt}년"] - ind_comp[f"{sel_year_rpt-1}년"]
                        ind_comp["대비(%)"] = np.where(ind_comp[f"{sel_year_rpt-1}년"] > 0, (ind_comp[f"{sel_year_rpt}년"] / ind_comp[f"{sel_year_rpt-1}년"]) * 100, 0)
                        
                        sort_option = st.radio("표 정렬 기준", ["당해연도 판매량 순", "전년대비 증감량 순"], horizontal=True, key=f"sort_{usage_label}{key_sfx}")
                        
                        if sort_option == "당해연도 판매량 순":
                            ind_comp = ind_comp.sort_values(f"{sel_year_rpt}년", ascending=False).reset_index(drop=True)
                        else:
                            ind_comp = ind_comp.sort_values("증감", ascending=False).reset_index(drop=True)
                        
                        if len(ind_comp) > 10:
                            top10_df = ind_comp.iloc[:10].copy()
                            others_df = ind_comp.iloc[10:].copy()
                            
                            others_curr = others_df[f"{sel_year_rpt}년"].sum()
                            others_prev = others_df[f"{sel_year_rpt-1}년"].sum()
                            others_diff = others_curr - others_prev
                            others_rate = (others_curr / others_prev * 100) if others_prev > 0 else 0
                            
                            others_row = pd.DataFrame([{
                                "업종": "기타", 
                                f"{sel_year_rpt}년": others_curr, 
                                f"{sel_year_rpt-1}년": others_prev, 
                                "증감": others_diff, 
                                "대비(%)": others_rate
                            }])
                            ind_comp = pd.concat([top10_df, others_row], ignore_index=True)
                        
                        sum_curr = ind_comp[f"{sel_year_rpt}년"].sum()
                        sum_prev = ind_comp[f"{sel_year_rpt-1}년"].sum()
                        sum_diff = sum_curr - sum_prev
                        sum_rate = (sum_curr / sum_prev * 100) if sum_prev > 0 else 0
                        
                        sub_ind_row = pd.DataFrame([{
                            "업종": "💡 총계", 
                            f"{sel_year_rpt}년": sum_curr, 
                            f"{sel_year_rpt-1}년": sum_prev, 
                            "증감": sum_diff, 
                            "대비(%)": sum_rate
                        }])
                        ind_comp = pd.concat([ind_comp, sub_ind_row], ignore_index=True)
                        
                        st.dataframe(
                            center_style(
                                ind_comp.style.format({
                                    f"{sel_year_rpt}년": "{:,.0f}", f"{sel_year_rpt-1}년": "{:,.0f}", "증감": "{:,.0f}", "대비(%)": "{:,.1f}"
                                }).apply(highlight_subtotal, axis=1)
                            ), 
                            use_container_width=True, hide_index=True
                        )
                    else:
                        st.error("데이터에 '업종' 컬럼이 없습니다.")
                        
                    st.markdown("<br>", unsafe_allow_html=True)
                    
                    show_details = st.toggle(f"🔍 {usage_label} 세부 분석 및 전체 고객 보기", value=False, key=f"toggle_{usage_label}{key_sfx}")
                    
                    if show_details:
                        st.markdown("<hr style='border-top: 1px dashed #ccc; margin: 10px 0 20px 0;'>", unsafe_allow_html=True)
                        
                        st.markdown(f"**■ 🔍 {usage_label} 업종 내 고객 상세 분석**")
                        available_industries = [ind for ind in ind_comp["업종"].tolist() if ind not in ["💡 총계", "기타"]]
                        sel_ind = st.selectbox(f"상세 조회할 업종을 선택하세요 ({usage_label})", ["선택 안함"] + available_industries, key=f"sel_ind_{usage_label}{key_sfx}")
                        
                        if sel_ind != "선택 안함":
                            ind_data = df_sub_filtered[df_sub_filtered["업종"] == sel_ind]
                            
                            c_curr = ind_data[ind_data["연_csv"] == sel_year_rpt].groupby("고객명", as_index=False)[val_col].sum().rename(columns={val_col: f"{sel_year_rpt}년"})
                            c_prev = ind_data[ind_data["연_csv"] == sel_year_rpt - 1].groupby("고객명", as_index=False)[val_col].sum().rename(columns={val_col: f"{sel_year_rpt-1}년"})
                            
                            cust_comp = pd.merge(c_curr, c_prev, on="고객명", how="outer").fillna(0)
                            cust_comp["증감"] = cust_comp[f"{sel_year_rpt}년"] - cust_comp[f"{sel_year_rpt-1}년"]
                            cust_comp["대비(%)"] = np.where(cust_comp[f"{sel_year_rpt-1}년"] > 0, (cust_comp[f"{sel_year_rpt}년"] / cust_comp[f"{sel_year_rpt-1}년"]) * 100, 0)
                            
                            if sort_option == "당해연도 판매량 순":
                                cust_comp = cust_comp.sort_values(f"{sel_year_rpt}년", ascending=False).reset_index(drop=True)
                            else:
                                cust_comp = cust_comp.sort_values("증감", ascending=False).reset_index(drop=True)
                                
                            sum_curr = cust_comp[f"{sel_year_rpt}년"].sum()
                            sum_prev = cust_comp[f"{sel_year_rpt-1}년"].sum()
                            sum_diff = sum_curr - sum_prev
                            sum_rate = (sum_curr / sum_prev * 100) if sum_prev > 0 else 0
                            
                            sub_cust_row = pd.DataFrame([{
                                "고객명": "💡 소계", 
                                f"{sel_year_rpt}년": sum_curr, 
                                f"{sel_year_rpt-1}년": sum_prev, 
                                "증감": sum_diff, 
                                "대비(%)": sum_rate
                            }])
                            cust_comp = pd.concat([cust_comp, sub_cust_row], ignore_index=True)
                                
                            st.dataframe(
                                center_style(
                                    cust_comp.style.format({
                                        f"{sel_year_rpt}년": "{:,.0f}", f"{sel_year_rpt-1}년": "{:,.0f}", "증감": "{:,.0f}", "대비(%)": "{:,.1f}"
                                    }).apply(highlight_subtotal, axis=1)
                                ), 
                                use_container_width=True, hide_index=True
                            )
                            
                        st.markdown("<hr style='border-top: 1px dashed #ccc; margin: 30px 0;'>", unsafe_allow_html=True)
                            
                        st.markdown(f"**■ 🏆 {usage_label} 전체 고객 업체 List (당해연도 판매량 기준)**")
                        
                        if "고객명" in df_sub_filtered.columns and "업종" in df_sub_filtered.columns:
                            curr_year_data = df_sub_filtered[df_sub_filtered["연_csv"] == sel_year_rpt]
                            total_usage_curr = curr_year_data[val_col].sum()
                            
                            grp_top = curr_year_data.groupby(["고객명", "업종"], as_index=False)[val_col].sum().sort_values(val_col, ascending=False)
                            
                            top30_sum = grp_top[val_col].sum()
                            top30_ratio = (top30_sum / total_usage_curr * 100) if total_usage_curr > 0 else 0
                            
                            subtotal_row = pd.DataFrame([{
                                "고객명": "💡 총계", 
                                "업종": f"전체대비 {top30_ratio:.1f}%", 
                                val_col: top30_sum
                            }])
                            grp_top = pd.concat([grp_top, subtotal_row], ignore_index=True)
                            
                            ranks = list(range(1, len(grp_top))) + ["-"]
                            grp_top.insert(0, "순위", ranks)
                            
                            st.dataframe(
                                center_style(
                                    grp_top.style.format({val_col: "{:,.0f}"}).apply(highlight_subtotal, axis=1)
                                ), 
                                use_container_width=True, hide_index=True
                            )
                            
                            st.markdown("<br>", unsafe_allow_html=True)
                            
                            st.markdown(f"**🔍 {usage_label} 개별 고객 상세 차트**")
                            top_customers = [c for c in grp_top["고객명"] if c != "💡 총계"]
                            sel_cust = st.selectbox(f"상세 분석할 고객명을 선택하세요 ({usage_label})", ["선택 안함"] + top_customers, key=f"sel_cust_{usage_label}{key_sfx}")

                            if sel_cust != "선택 안함":
                                c_data = df_sub[df_sub["고객명"] == sel_cust]
                                c_grp = c_data.groupby(["연_csv", "월_csv"], as_index=False)[val_col].sum()
                                
                                y_cur = c_grp[(c_grp["연_csv"] == sel_year_rpt) & (c_grp["월_csv"] <= max_month)]
                                y_prev = c_grp[(c_grp["연_csv"] == sel_year_rpt - 1) & (c_grp["월_csv"] <= max_month)]
                                
                                sum_cur_c = y_cur[val_col].sum()
                                sum_prev_c = y_prev[val_col].sum()
                                
                                diff_val = sum_cur_c - sum_prev_c
                                rate_val = (sum_cur_c / sum_prev_c * 100) if sum_prev_c > 0 else 0
                                sign_str = "+" if diff_val > 0 else ""
                                yoy_text = f"전년대비 증감: {sign_str}{diff_val:,.0f} ({rate_val:.1f}%)"
                                
                                cc1, cc2 = st.columns([1, 2])
                                with cc1:
                                    fig_cust_cum = go.Figure()
                                    fig_cust_cum.add_trace(go.Bar(x=[f"{sel_year_rpt}년", f"{sel_year_rpt-1}년"], 
                                                                  y=[sum_cur_c, sum_prev_c],
                                                                  marker_color=[COLOR_ACT, COLOR_PREV],
                                                                  text=[f"{sum_cur_c:,.0f}", f"{sum_prev_c:,.0f}"], textposition='auto'))
                                    
                                    fig_cust_cum.add_annotation(
                                        x=0.5, y=1.05, xref="paper", yref="paper",
                                        text=f"<b>{yoy_text}</b>",
                                        showarrow=False, font=dict(size=13, color="#d32f2f" if diff_val < 0 else "#1f77b4"),
                                        bgcolor="#f8f9fa", bordercolor="#d0d7e5", borderwidth=1, borderpad=4
                                    )
                                    
                                    fig_cust_cum.update_layout(title=f"'{sel_cust}' 누적 사용량 ({sel_quarter[:2]})", margin=dict(t=50,b=10,l=10,r=10), height=350)
                                    st.plotly_chart(fig_cust_cum, use_container_width=True)
                                    
                                with cc2:
                                    fig_cust_mon = go.Figure()
                                    months_c = list(range(1, max_month + 1))
                                    
                                    cur_vals = [y_cur[y_cur['월_csv']==m][val_col].sum() for m in months_c]
                                    prev_vals = [y_prev[y_prev['월_csv']==m][val_col].sum() for m in months_c]
                                    
                                    fig_cust_mon.add_trace(go.Bar(
                                        x=months_c, y=cur_vals, name=f"{sel_year_rpt}년", marker_color=COLOR_ACT,
                                        text=[f"{v:,.0f}" if v>0 else "" for v in cur_vals], textposition='auto', textfont=dict(size=11)
                                    ))
                                    fig_cust_mon.add_trace(go.Bar(
                                        x=months_c, y=prev_vals, name=f"{sel_year_rpt-1}년", marker_color=COLOR_PREV,
                                        text=[f"{v:,.0f}" if v>0 else "" for v in prev_vals], textposition='auto', textfont=dict(size=11)
                                    ))
                                    
                                    fig_cust_mon.update_layout(title=f"'{sel_cust}' 월별 사용량 추이", barmode='group', xaxis=dict(tickmode='linear', tick0=1, dtick=1), margin=dict(t=50,b=10,l=10,r=10), height=350, legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
                                    st.plotly_chart(fig_cust_mon, use_container_width=True)
                        else:
                            st.error("데이터에 '고객명' 또는 '업종' 컬럼이 없습니다.")
                            
                    st.markdown("<br><br>", unsafe_allow_html=True)

                render_attachment_report("산업용", 6, key_sfx)
                render_attachment_report("업무용", 7, key_sfx)
            
            # --- 🖨️ PDF 인쇄 기능 ---
            st.markdown("<hr style='border-top: 2px solid #bbb; margin: 40px 0 20px 0;'>", unsafe_allow_html=True)
            st.markdown("### 🖨️ 보고서 출력")
            
            st.markdown("""
                <button onclick="window.print()" style="padding: 12px 20px; font-size: 16px; border-radius: 8px; background-color: #1e3a8a; color: white; border: none; cursor: pointer; width: 100%; font-weight: bold; box-shadow: 0 4px 6px rgba(0,0,0,0.1);">
                    🖨️ 현재 화면 전체를 PDF로 다운로드 (인쇄)
                </button>
            """, unsafe_allow_html=True)
