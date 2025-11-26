import io
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
    return 2025 if 2025 in years else years[-1]


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
    """각 섹션별 기준선택 UI.
    기준 월 디폴트: 실적(값>0)이 있는 최신 월을 사용, 없으면 단순 마지막 월.
    """
    st.markdown(f"#### ✅ {title} 기준 선택")

    if long_df.empty:
        st.info("연도 정보가 없습니다.")
        return 0, 1, "연 누적", []

    years_all = sorted(long_df["연"].unique().tolist())
    default_year = pick_default_year(years_all)

    # 디폴트 계산용: 실적이 있는 데이터 우선 사용
    df_for_default = long_df.copy()
    if {"계획/실적", "값"}.issubset(df_for_default.columns):
        mask = (
            (df_for_default["계획/실적"] == "실적")
            & df_for_default["값"].notna()
            & (df_for_default["값"] != 0)
        )
        if mask.any():
            df_for_default = df_for_default[mask]

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
            index=years_all.index(default_year),
            key=f"{key_prefix}year",
        )

    # 선택된 연도에서, 실적이 있는 월을 우선 디폴트로 사용
    df_sel = long_df[long_df["연"] == sel_year].copy()
    months_actual: List[int] = []
    if {"계획/실적", "값"}.issubset(df_sel.columns):
        m = (
            (df_sel["계획/실적"] == "실적")
            & df_sel["값"].notna()
            & (df_sel["값"] != 0)
        )
        months_actual = sorted(df_sel[m]["월"].unique().tolist())

    months = months_actual or sorted(df_sel["월"].unique().tolist())
    if not months:
        months = [default_month_global]

    if months_actual:
        default_month_for_sel_year = months_actual[-1]
    else:
        default_month_for_sel_year = months[-1]

    if default_month_for_sel_year not in months:
        default_month_for_sel_year = months[-1]

    with c2:
        sel_month = st.selectbox(
            "기준 월",
            options=months,
            index=months.index(default_month_for_sel_year),
            key=f"{key_prefix}month",
        )

    # fixed_mode 강제(당월/연누적)
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
        <div style="font-size:18px; font-weight:650; color:#444; margin-bottom:6px;">{title}</div>
        <div style="font-size:34px; font-weight:750; color:{color}; margin-bottom:8px;">{main}</div>
        <div style="font-size:14px; color:#444; min-height:20px; font-weight:500;">{sub}</div>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)


def render_rate_donut(rate: float, color: str):
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
        width=240,
        height=240,
        margin=dict(l=0, r=0, t=0, b=0),
        annotations=[dict(
            text=f"{rate:.1f}%",
            x=0.5, y=0.5,
            showarrow=False,
            font=dict(size=20, color=color, family="NanumGothic"),
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
        render_rate_donut(plan_rate, "#16a34a")
        st.caption(f"계획 달성률 · {mode_tag}")
    with d4:
        render_rate_donut(prev_rate, "#f97316")
        st.caption(f"전년대비 증감률 · {mode_tag}")

    st.markdown("<br>", unsafe_allow_html=True)

    # ── 특이사항 (무조건 2건)
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
    ...
