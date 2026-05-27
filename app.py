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
    
    # 💡 [수정된 부분] 아래 생성하는 컬럼명을 '편차_GJ'로 통일했습니다.
    this_df["편차_GJ"] = (this_df[act_col] - daily_plan_mj) / 1000.0

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
    
    # 💡 위에서 통일한 '편차_GJ'를 정상적으로 호출하게 됩니다.
    show = this_df[["일자", act_col, "편차_GJ"]].copy()
    show.columns = ["일자", "일별실적(GJ)", "편차(실적-일계획)(GJ)"]
    show["일별실적(GJ)"] = show["일별실적(GJ)"].apply(lambda v: v / 1000.0)
    styled = center_style(
        show.style.format("{:,.1f}", subset=["일별실적(GJ)", "편차(실적-일계획)(GJ)"])
    )
    st.dataframe(styled, use_container_width=True, hide_index=True)
