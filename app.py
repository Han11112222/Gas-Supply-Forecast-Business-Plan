import io
from pathlib import Path
from typing import Dict, List, Optional

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
st.set_page_config(page_title="도시가스 판매량 계획/실적 분석", layout="wide")

DEFAULT_XLSX = "판매량(계획_실적).xlsx"

# 엑셀 헤더 → 분석 그룹 매핑 (명시적 매핑)
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

    # 🔥 열병합 컬럼명 변형 대비
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
COLOR_ACT  = "rgba(0, 150, 255, 1)"
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

def _clean_base(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "Unnamed: 0" in out.columns:
        out = out.drop(columns=["Unnamed: 0"])
    out["연"] = pd.to_numeric(out["연"], errors="coerce").astype("Int64")
    out["월"] = pd.to_numeric(out["월"], errors="coerce").astype("Int64")
    return out


def keyword_group(col: str) -> Optional[str]:
    """컬럼명이 약간 달라도 잡히도록 키워드 기반 보정."""
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
    """wide → long (연·월·그룹·용도·계획/실적·값)."""
    plan_df = _clean_base(plan_df)
    actual_df = _clean_base(actual_df)

    records = []
    for label, df in [("계획", plan_df), ("실적", actual_df)]:
        for col in df.columns:
            if col in ["연", "월"]:
                continue

            # 1) 명시적 매핑 우선
            group = USE_COL_TO_GROUP.get(col)

            # 2) 없으면 키워드 기반 보정
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


def pick_default_year(years: List[int]) -> int:
    return 2025 if 2025 in years else years[-1]


# ─────────────────────────────────────────────────────────
# 0. 상단 월간 핵심 대시보드
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
    """도넛 크기 2/3 수준으로 축소."""
    if pd.isna(rate) or np.isnan(rate):
        st.markdown(
            "<div style='font-size:14px;color:#999;text-align:center;'>데이터 없음</div>",
            unsafe_allow_html=True,
        )
        return

    filled = max(min(float(rate), 200.0), 0.0)
    empty = max(100.0 - filled, 0.0)

    fig = go.Figure(
        data=[
            go.Pie(
                values=[filled, empty],
                hole=0.7,
                sort=False,
                direction="clockwise",
                marker=dict(colors=[color, "#e5e7eb"]),
                textinfo="none",
            )
        ]
    )

    fig.update_layout(
        showlegend=False,
        width=240,   # 줄인 크기
        height=240,  # 줄인 크기
        margin=dict(l=0, r=0, t=0, b=0),
        annotations=[
            dict(
                text=f"{rate:.1f}%",
                x=0.5, y=0.5,
                showarrow=False,
                font=dict(size=20, color=color, family="NanumGothic"),
            )
        ],
    )
    st.plotly_chart(fig, use_container_width=False)


def monthly_core_dashboard(long_df: pd.DataFrame, unit_label: str, key_prefix: str = ""):
    st.markdown("## 📌 월간 핵심 대시보드")

    if long_df.empty:
        st.info("데이터가 없습니다.")
        return

    years = sorted(long_df["연"].unique().tolist())
    if not years:
        st.info("연도 정보가 없습니다.")
        return

    default_year = pick_default_year(years)

    months_for_default = sorted(long_df[long_df["연"] == default_year]["월"].unique())
    if not months_for_default:
        years_with_months = [y for y in years if len(long_df[long_df["연"] == y]["월"].unique()) > 0]
        if years_with_months:
            default_year = pick_default_year(years_with_months)
            months_for_default = sorted(long_df[long_df["연"] == default_year]["월"].unique())
        else:
            st.warning("월 데이터가 있는 연도가 없어. 하단 분석만 표시할게.")
            return

    default_month = months_for_default[-1]

    c_year, c_month, c_mode, c_info = st.columns([1.2, 1.2, 1.6, 3])

    with c_year:
        sel_year = st.selectbox(
            "연도 선택",
            options=years,
            index=years.index(default_year),
            key=f"{key_prefix}dash_year",
        )

    months = sorted(long_df[long_df["연"] == sel_year]["월"].unique().tolist())
    if not months:
        sel_year = default_year
        months = months_for_default
        st.warning(f"선택 연도에 월 데이터가 없어 {default_year}년 기준으로 표시했어.")

    with c_month:
        sel_month = st.selectbox(
            "월 선택",
            options=months,
            index=months.index(default_month) if default_month in months else len(months) - 1,
            key=f"{key_prefix}dash_month",
        )

    with c_mode:
        agg_mode = st.radio(
            "집계 기준",
            ["당월", "월 누적"],
            index=0,
            horizontal=True,
            key=f"{key_prefix}dash_mode",
        )

    is_cum = (agg_mode == "월 누적")
    mode_tag = "당월" if not is_cum else "연도누적(월 누적)"

    with c_info:
        st.markdown(
            f"<div style='padding-top:26px;font-size:15px;color:#555;'>"
            f"선택 연월: <b>{sel_year}년 {sel_month}월</b> · "
            f"<span style='color:#111;'>{agg_mode}</span>"
            f"</div>",
            unsafe_allow_html=True,
        )

    def mask_for(year: int, month: int, cumulative: bool):
        cond_y = long_df["연"] == year
        cond_m = (long_df["월"].between(1, month)) if cumulative else (long_df["월"] == month)
        return cond_y & cond_m

    mask_this = mask_for(sel_year, sel_month, is_cum)
    base_this = long_df[mask_this].copy()

    plan_total = base_this[base_this["계획/실적"] == "계획"]["값"].sum()
    act_total  = base_this[base_this["계획/실적"] == "실적"]["값"].sum()

    prev_year = sel_year - 1
    has_prev = prev_year in years
    if has_prev:
        mask_prev = mask_for(prev_year, sel_month, is_cum)
        base_prev = long_df[mask_prev]
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
        render_metric_card("📙", f"전년 동월{' 누적' if is_cum else ''} 실적 ({unit_label})", main_prev, sub3, color="#f97316")

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

    # ── 특이사항 (무조건 2건 출력)
    st.markdown("#### ⚠️ 특이사항 (계획·전년 대비 편차 핵심 이슈)")

    if base_this.empty:
        st.info("선택 연월에 해당하는 데이터가 없습니다.")
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
            .reset_index()  # ✅ index -> column
        )

        for c in ["계획", "실적"]:
            if c not in pivot.columns:
                pivot[c] = 0.0

        pivot["계획대비차이"] = pivot["실적"] - pivot["계획"]
        with np.errstate(divide="ignore", invalid="ignore"):
            pivot["계획달성률(%)"] = np.where(
                pivot["계획"] != 0,
                (pivot["실적"] / pivot["계획"]) * 100.0,
                np.nan
            )

        # 전년 결합
        if has_prev:
            prev_only = base_prev[base_prev["계획/실적"] == "실적"].copy()
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
        with np.errstate(divide="ignore", invalid="ignore"):
            pivot["전년대비증감률(%)"] = np.where(
                pivot["전년실적"] != 0,
                (pivot["실적"] / pivot["전년실적"]) * 100.0,
                np.nan
            )

        if pivot.empty:
            st.markdown("<div style='font-size:14px;color:#666;'>표시할 특이사항이 없습니다.</div>",
                        unsafe_allow_html=True)
            return

        # -------- 무조건 2건 뽑기 --------
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

        core_issues = pd.DataFrame(picked_rows)

        # 중복 제거 후 2개 채우기
        core_issues = core_issues.drop_duplicates(subset=["그룹/용도"])
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

        html_table = disp.astype(str).to_html(index=False, escape=False)
        st.markdown(
            f"<div style='border-radius:12px; overflow-x:auto; border:1px solid #eee;'>{html_table}</div>",
            unsafe_allow_html=True,
        )

    except Exception:
        st.markdown(
            "<div style='font-size:14px;color:#666;'>특이사항 계산 중 오류가 발생해 표시를 생략했어.</div>",
            unsafe_allow_html=True,
        )


# ─────────────────────────────────────────────────────────
# 1. 월별 추이
# ─────────────────────────────────────────────────────────
def monthly_trend_section(long_df: pd.DataFrame, unit_label: str, key_prefix: str = ""):
    st.markdown("### 📈 월별 추이 그래프")

    if long_df.empty:
        st.info("데이터가 없습니다.")
        return

    years = sorted(long_df["연"].unique().tolist())
    if not years:
        st.info("연도 정보가 없습니다.")
        return

    preferred_years = [y for y in [2021, 2022, 2023, 2024, 2025] if y in years]
    if 2025 in years and 2025 not in preferred_years:
        preferred_years.append(2025)
    default_years = preferred_years if preferred_years else [pick_default_year(years)]

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

    if sel_group == "총량":
        plot_df = (
            base.groupby(["연", "월", "계획/실적"], as_index=False)["값"].sum()
            .sort_values(["연", "월", "계획/실적"])
        )
        plot_df["라벨"] = plot_df["연"].astype(str) + "년 · " + plot_df["계획/실적"]
    else:
        base = base[base["그룹"] == sel_group]
        plot_df = (
            base.groupby(["연", "월", "계획/실적"], as_index=False)["값"].sum()
            .sort_values(["연", "월", "계획/실적"])
        )
        plot_df["라벨"] = plot_df["연"].astype(str) + "년 · " + sel_group + " · " + plot_df["계획/실적"]

    if plot_df.empty:
        st.info("선택 조건에 해당하는 데이터가 없어.")
        return

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
        margin=dict(l=10, r=10, t=10, b=10),
    )
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("##### 🔢 월별 수치표")
    table = (
        plot_df.pivot_table(index="월", columns="라벨", values="값", aggfunc="sum")
        .sort_index()
        .fillna(0.0)
    )
    st.dataframe(table.style.format("{:,.0f}"), use_container_width=True)


# ─────────────────────────────────────────────────────────
# 2. 연간 계획대비 요약
# ─────────────────────────────────────────────────────────
def yearly_summary_section(long_df: pd.DataFrame, unit_label: str, key_prefix: str = ""):
    st.markdown("### 📊 연간 계획대비 실적 요약 — 그룹별 분석")

    if long_df.empty:
        st.info("데이터가 없습니다.")
        return

    years = sorted(long_df["연"].unique().tolist())
    if not years:
        st.info("연도 정보가 없습니다.")
        return

    default_year = pick_default_year(years)
    default_index = years.index(default_year)

    col1, col2, col3 = st.columns([2, 2, 1.5])
    with col1:
        sel_year = st.selectbox(
            "연도 선택(집계)",
            options=years,
            index=default_index,
            key=f"{key_prefix}summary_year",
        )
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

    base_this = long_df[long_df["연"] == sel_year].copy()
    if base_this.empty:
        st.info("선택한 연도에 데이터가 없어.")
        return

    prev_year = sel_year - 1
    base_prev = (
        long_df[(long_df["연"] == prev_year) & (long_df["계획/실적"] == "실적")].copy()
        if include_prev else pd.DataFrame([])
    )

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
    act_series  = grp_this[grp_this["계획/실적"] == "실적"].set_index(idx_col)["값"]
    prev_series = grp_prev.set_index(idx_col)["전년실적"] if not grp_prev.empty else pd.Series(dtype=float)

    cats = sorted(set(plan_series.index) | set(act_series.index) | set(prev_series.index))
    y_plan = [plan_series.get(c, 0.0) for c in cats]
    y_act  = [act_series.get(c, 0.0) for c in cats]
    y_prev = [prev_series.get(c, 0.0) for c in cats] if not prev_series.empty else None

    st.markdown("#### 📊 선택 연도 그룹별 계획·실적 막대그래프")

    fig_bar = go.Figure()
    fig_bar.add_bar(x=cats, y=y_plan, name=f"{sel_year} 계획", marker_color=COLOR_PLAN)
    fig_bar.add_bar(x=cats, y=y_act,  name=f"{sel_year} 실적", marker_color=COLOR_ACT)
    if include_prev and y_prev is not None:
        fig_bar.add_bar(x=cats, y=y_prev, name=f"{prev_year} 실적", marker_color=COLOR_PREV)

    fig_bar.update_traces(width=0.25, selector=dict(type="bar"))
    fig_bar.update_layout(
        barmode="group",
        xaxis_title=idx_col,
        yaxis_title=f"연간 합계 ({unit_label})",
        margin=dict(l=10, r=10, t=10, b=10),
    )
    st.plotly_chart(fig_bar, use_container_width=True)

    st.markdown("##### 🔢 연간 요약 표")
    st.dataframe(
        pivot.reset_index().style.format(
            {"계획":"{:,.0f}", "실적":"{:,.0f}", "차이(실적-계획)":"{:,.0f}", "달성률(%)":"{:,.1f}"}
        ),
        use_container_width=True
    )

    tot_plan = float(pivot["계획"].sum())
    tot_act  = float(pivot["실적"].sum())
    diff = tot_act - tot_plan
    rate = (tot_act / tot_plan * 100.0) if tot_plan != 0 else np.nan

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("계획 합계", f"{tot_plan:,.0f}")
    c2.metric("실적 합계", f"{tot_act:,.0f}")
    c3.metric("차이(실적-계획)", f"{diff:,.0f}")
    c4.metric("달성률(%)", f"{rate:,.1f}" if not np.isnan(rate) else "-")


# ─────────────────────────────────────────────────────────
# 3. 계획대비 월별
# ─────────────────────────────────────────────────────────
def plan_vs_actual_usage_section(long_df: pd.DataFrame, unit_label: str, key_prefix: str = ""):
    st.markdown("### 🧮 계획대비 월별 실적 (용도 선택)")

    if long_df.empty:
        st.info("데이터가 없습니다.")
        return

    groups_all = sorted(g for g in long_df["그룹"].unique() if g is not None)
    available_groups = ["총량"] + [g for g in GROUP_OPTIONS if g != "총량" and g in groups_all]
    if not available_groups:
        st.info("선택 가능한 그룹이 없습니다.")
        return

    years = sorted(long_df["연"].unique().tolist())
    if not years:
        st.info("연도 정보가 없습니다.")
        return

    default_year = pick_default_year(years)
    default_year_index = years.index(default_year)

    col1, col2, col3 = st.columns([2, 2, 1.5])
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
        sel_year = st.selectbox(
            "기준 연도 선택",
            options=years,
            index=default_year_index,
            key=f"{key_prefix}pv_year",
        )

    with col3:
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

    if base.empty:
        st.info("선택 조건에 해당하는 데이터가 없어.")
        return

    df_year = base[base["연"] == sel_year]
    if df_year.empty:
        st.info("선택한 연도의 데이터가 없어.")
        return

    prev_year = sel_year - 1
    df_prev = base[(base["연"] == prev_year) & (base["계획/실적"] == "실적")] if include_prev else pd.DataFrame([])

    bars = df_year.groupby(["월", "계획/실적"], as_index=False)["값"].sum().sort_values(["월", "계획/실적"])

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

    if include_prev and not df_prev.empty:
        prev_group = df_prev.groupby("월", as_index=False)["값"].sum().sort_values("월")
        fig.add_bar(x=prev_group["월"], y=prev_group["값"], name=f"{prev_year}년 실적", width=0.25, marker_color=COLOR_PREV)

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
        title=f"{sel_year}년 {sel_group} 판매량 및 증감 ({period_label})",
        xaxis_title="월",
        yaxis_title=f"판매량 ({unit_label})",
        xaxis=dict(dtick=1),
        margin=dict(l=10, r=10, t=40, b=10),
        barmode="group",
        yaxis2=dict(title="증감(실적-계획)", overlaying="y", side="right", showgrid=False),
    )
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("##### 🔢 월별 계획·실적·전년실적·증감 수치")
    table = bars.pivot(index="월", columns="계획/실적", values="값").sort_index().fillna(0.0)
    if include_prev and not df_prev.empty:
        prev_tbl = df_prev.groupby("월", as_index=False)["값"].sum().set_index("월")["값"]
        table["전년실적"] = prev_tbl
    table["증감(실적-계획)"] = table.get("실적", 0.0) - table.get("계획", 0.0)
    st.dataframe(table.style.format("{:,.0f}"), use_container_width=True)


# ─────────────────────────────────────────────────────────
# 4. 기간별 스택 + 라인 (실적 기준)
# ─────────────────────────────────────────────────────────
def half_year_stacked_section(long_df: pd.DataFrame, unit_label: str, key_prefix: str = ""):
    st.markdown("### 🧱 기간별 용도 누적 실적 (스택형 막대 + 라인)")

    if long_df.empty:
        st.info("데이터가 없습니다.")
        return

    years = sorted(long_df["연"].unique().tolist())
    if not years:
        st.info("연도 정보가 없습니다.")
        return

    preferred_years = [y for y in [2021, 2022, 2023, 2024, 2025] if y in years]
    if 2025 in years and 2025 not in preferred_years:
        preferred_years.append(2025)
    default_years = preferred_years if preferred_years else [pick_default_year(years)]

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

    if base.empty:
        st.info("선택 조건에 해당하는 데이터가 없어.")
        return

    grp = base.groupby(["연", "그룹"], as_index=False)["값"].sum()

    fig = px.bar(grp, x="연", y="값", color="그룹", barmode="stack")
    fig.update_traces(width=0.4, selector=dict(type="bar"))

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
            mode="lines+markers+text", name="가정용",
            line=dict(dash="dot"),
            text=home["가정용"].apply(lambda v: f"{v:,.0f}"),
            textposition="top center", textfont=dict(size=11),
        )

    fig.update_layout(
        title=f"{period_label} 용도별 실적 판매량 (누적)",
        xaxis_title="연도",
        yaxis_title=f"판매량 ({unit_label})",
        margin=dict(l=10, r=10, t=40, b=10),
    )
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("##### 🔢 연도·그룹별 누적 실적 수치")
    summary = grp.pivot(index="연", columns="그룹", values="값").sort_index().fillna(0.0)
    summary["합계"] = summary.sum(axis=1)
    st.dataframe(summary.style.format("{:,.0f}"), use_container_width=True)


# ─────────────────────────────────────────────────────────
# 본문
# ─────────────────────────────────────────────────────────
st.title("도시가스 판매량 계획 / 실적 분석")

with st.sidebar:
    st.header("📂 데이터 불러오기")
    src = st.radio("데이터 소스", ["레포 파일 사용", "엑셀 업로드(.xlsx)"], index=0)
    excel_bytes = None
    base_info = ""
    if src == "엑셀 업로드(.xlsx)":
        up = st.file_uploader("판매량(계획_실적).xlsx 형식", type=["xlsx"])
        if up is not None:
            excel_bytes = up.getvalue()
            base_info = f"소스: 업로드 파일 — {up.name}"
    else:
        path = Path(__file__).parent / DEFAULT_XLSX
        if path.exists():
            excel_bytes = path.read_bytes()
            base_info = f"소스: 레포 파일 — {DEFAULT_XLSX}"
        else:
            base_info = f"레포 경로에 {DEFAULT_XLSX} 파일이 없습니다."

st.caption(base_info)

long_dict: Dict[str, pd.DataFrame] = {}
if excel_bytes is not None:
    sheets = load_all_sheets(excel_bytes)
    long_dict = build_long_dict(sheets)

tab_labels: List[str] = []
if "부피" in long_dict:
    tab_labels.append("부피 기준 (천m³)")
if "열량" in long_dict:
    tab_labels.append("열량 기준 (MJ)")

if not tab_labels:
    st.info("유효한 시트를 찾지 못했어. 파일 시트명을 확인해 줘.")
else:
    tabs = st.tabs(tab_labels)
    for tab_label, tab in zip(tab_labels, tabs):
        with tab:
            if tab_label.startswith("부피"):
                df_long = long_dict.get("부피", pd.DataFrame())
                unit = "천m³"
                prefix = "vol_"
            else:
                df_long = long_dict.get("열량", pd.DataFrame())
                unit = "MJ"
                prefix = "mj_"

            # 맨 상단: 월간 핵심 대시보드
            monthly_core_dashboard(df_long, unit_label=unit, key_prefix=prefix + "dash_")

            st.markdown("---")

            # 상단: 실적 중심
            st.markdown("## 📊 실적 분석")
            monthly_trend_section(df_long, unit_label=unit, key_prefix=prefix)
            half_year_stacked_section(df_long, unit_label=unit, key_prefix=prefix + "stack_")

            st.markdown("---")

            # 하단: 계획대비 분석
            st.markdown("## 📏 계획대비 분석")
            yearly_summary_section(df_long, unit_label=unit, key_prefix=prefix + "summary_")
            plan_vs_actual_usage_section(df_long, unit_label=unit, key_prefix=prefix + "pv_")
