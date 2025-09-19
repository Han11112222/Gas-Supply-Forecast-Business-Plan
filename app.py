# app.py — 공급량 실적 및 계획 상세 (데이터/best/conservative, 2024~2027, None→0, 동적 그래프)
import io, os, re, unicodedata
import numpy as np
import pandas as pd
import matplotlib as mpl
import streamlit as st
from pandas.api.types import is_datetime64_any_dtype as is_dt, is_integer_dtype
import altair as alt

DEFAULT_REPO_FILE = "사업계획최종.xlsx"

# ───────────────── 폰트
def set_korean_font():
    import matplotlib.font_manager as fm
    for path, name in [
        ("NanumGothic-Regular.ttf", "NanumGothic"),
        ("/usr/share/fonts/truetype/nanum/NanumGothic.ttf", "NanumGothic"),
        ("C:/Windows/Fonts/malgun.ttf", "Malgun Gothic"),
        ("/System/Library/Fonts/AppleGothic.ttf", "AppleGothic"),
    ]:
        if os.path.exists(path):
            try: fm.fontManager.addfont(path)
            except Exception: pass
            mpl.rcParams["font.family"] = name
            mpl.rcParams["axes.unicode_minus"] = False
            return
    mpl.rcParams["font.family"] = "DejaVu Sans"
    mpl.rcParams["axes.unicode_minus"] = False
set_korean_font()

st.set_page_config(page_title="공급량 실적 및 계획 상세", layout="wide")
st.title("📊 공급량 실적 및 계획 상세")

# ───────────────── 표 스펙
ROWS_SPEC = [
    ("가정용", "취사용"),
    ("가정용", "개별난방"),
    ("가정용", "중앙난방"),
    ("가정용", "소계"),
    ("영업용", "일반용1"),
    ("업무용", "일반용2"),
    ("업무용", "냉난방용"),
    ("업무용", "주한미군"),
    ("업무용", "소계"),
    ("산업용", "합계"),
    ("열병합", "합계"),
    ("연료전지", "합계"),
    ("자가열전용", "합계"),   # ← 변경: 자가열병합 → 자가열전용
    ("열전용설비용", "합계"),
    ("CNG", "합계"),
    ("수송용", "BIO"),
    ("수송용", "소계"),
    ("합계", ""),
]
MONTH_COLS = [f"{m}월" for m in range(1,13)]
ALL_COLS = ["구분","세부"]+MONTH_COLS+["합계"]

def blank_table():
    df = pd.DataFrame(ROWS_SPEC, columns=["구분","세부"])
    for c in MONTH_COLS: df[c]=np.nan
    df["합계"]=np.nan
    return df

def norm(s):
    if s is None: return ""
    s = unicodedata.normalize("NFKC", str(s)).strip().lower()
    return re.sub(r"\s+","",s)

# ───────────────── 동의어 사전 (업무난방 포함, 자가열전용으로 정정)
SYN = {
    "취사용": ["취사용","취사","주택취사"],
    "개별난방": ["개별난방","개난","개별 난방"],
    "중앙난방": ["중앙난방","중난","중앙 난방"],
    "일반용1": ["일반용1","영업용1","일반1"],
    "일반용2": ["일반용2","업무용","업무난방","업무용난방","업무 일반"],
    "냉난방용": ["냉난방용","냉난방","냉/난방","업무냉난방"],
    "주한미군": ["주한미군","주택미군","주한 미군","usfk","주택미급"],
    "산업용":   ["산업용","산업"],
    "열병합":   ["열병합","chp"],
    "연료전지": ["연료전지","fc"],
    "자가열전용": ["자가열전용","자가 열전용","자가열전용설비","자가전용열","자가 전용 열"],
    "열전용설비용": ["열전용설비용","열전용"],
    "CNG": ["cng","씨엔지"],
    "BIO": ["bio","바이오"],
}

YEAR_HINTS  = ["연도","년도","year","yr","연"]
MONTH_HINTS = ["월","month","mm","mon"]
DATE_HINTS  = ["일자","날짜","date","기준일"]

def best_match(colnames, aliases):
    cn=[norm(c) for c in colnames]
    for al in aliases:
        nal=norm(al)
        if nal in cn: return colnames[cn.index(nal)]
    for i,c in enumerate(cn):
        for al in aliases:
            if norm(al) and norm(al) in c:
                return colnames[i]
    return None

def likely_numeric(s: pd.Series): return pd.to_numeric(s, errors="coerce").notna().mean()>=0.6
def detect_year_col(cols):  return best_match(cols, YEAR_HINTS)
def detect_month_col(cols): return best_match(cols, MONTH_HINTS)
def detect_date_col(cols):  return best_match(cols, DATE_HINTS)

def _epoch_to_dt(series):
    s = pd.to_numeric(series, errors="coerce")
    med = s.dropna().astype("float64").abs().median()
    if med > 1e12: return pd.to_datetime(s, errors="coerce")
    elif med > 1e10: return pd.to_datetime(s, unit="ms", errors="coerce")
    elif med > 1e9: return pd.to_datetime(s, unit="s", errors="coerce")
    else: return None

def auto_map_usage_columns(df):
    cols=df.columns.tolist(); out={}
    for key, aliases in SYN.items():
        cand=[]
        for c in cols:
            if best_match([c], aliases)==c and likely_numeric(df[c]): cand.append(c)
        if not cand:
            for c in cols:
                if any(norm(al) in norm(c) for al in aliases) and likely_numeric(df[c]): cand.append(c)
        out[key]=cand[0] if cand else None
    return out

def calc_subtotals(table: pd.DataFrame)->pd.DataFrame:
    t=table.copy()
    def sum_num(mask, col): return pd.to_numeric(t.loc[mask,col], errors="coerce").sum()
    # 가정용 소계
    m_sc=(t["구분"]=="가정용") & (t["세부"]=="소계")
    for c in MONTH_COLS:
        m=(t["구분"]=="가정용") & (t["세부"].isin(["취사용","개별난방","중앙난방"]))
        t.loc[m_sc,c]=sum_num(m,c)
    # 업무용 소계
    m_sc=(t["구분"]=="업무용") & (t["세부"]=="소계")
    for c in MONTH_COLS:
        m=(t["구분"]=="업무용") & (t["세부"].isin(["일반용2","냉난방용","주한미군"]))
        t.loc[m_sc,c]=sum_num(m,c)
    # 수송용 소계
    m_sc=(t["구분"]=="수송용") & (t["세부"]=="소계")
    for c in MONTH_COLS:
        m=(t["구분"]=="수송용") & (t["세부"]=="BIO")
        t.loc[m_sc,c]=sum_num(m,c)
    # 전체 합계
    m_total=(t["구분"]=="합계")
    m_body=(t["구분"]!="합계") & t["세부"].ne("소계") & t["세부"].ne("합계")
    for c in MONTH_COLS: t.loc[m_total,c]=sum_num(m_body,c)
    t["합계"]=t[MONTH_COLS].apply(pd.to_numeric, errors="coerce").sum(axis=1, min_count=1)
    return t

def highlight_rows(df):
    sty=pd.DataFrame("", index=df.index, columns=df.columns)
    sty.loc[df["세부"]=="소계",:]="background-color:#f2f7ff"
    sty.loc[df["구분"]=="합계",:]="background-color:#fff3e6"
    return sty

def coerce_numeric_inplace(df):
    for c in MONTH_COLS+["합계"]:
        df[c]=pd.to_numeric(df[c], errors="coerce").fillna(0.0)

def prepare_df(df_in):
    df=df_in.copy()
    yc=detect_year_col(df.columns); mc=detect_month_col(df.columns); dc=detect_date_col(df.columns)
    if (yc is None or mc is None) and (dc is not None):
        dt=pd.to_datetime(df[dc], errors="coerce")
        if yc is None: df["_연도_"]=dt.dt.year.astype("Int64")
        if mc is None: df["_월_"]=dt.dt.month.astype("Int64")
    if "_연도_" not in df.columns:
        if yc is None: raise ValueError("연(연도) 컬럼을 찾을 수 없습니다.")
        y=df[yc]
        if is_dt(y): y=y.dt.year
        elif is_integer_dtype(y):
            dt=_epoch_to_dt(y); y = dt.dt.year if dt is not None else y
        else: y=pd.to_numeric(y, errors="coerce")
        df["_연도_"]=y.astype("Int64")
    if "_월_" not in df.columns:
        if mc is None: raise ValueError("월 컬럼을 찾을 수 없습니다.")
        m=df[mc]; m=m.dt.month if is_dt(m) else pd.to_numeric(m, errors="coerce")
        df["_월_"]=m.astype("Int64")
    return df, auto_map_usage_columns(df)

def monthly_sum(df, year, col):
    sub=df.loc[df["_연도_"]==year, ["_월_", col]].copy()
    sub[col]=pd.to_numeric(sub[col], errors="coerce")
    s=sub.groupby("_월_")[col].sum(min_count=1)
    out=pd.Series(index=range(1,13), dtype="float64"); out.update(s); return out

def build_table_for_year(df, auto_map, year:int):
    base=blank_table()
    # 잎 항목
    leaf_map={
        ("가정용","취사용"):"취사용",
        ("가정용","개별난방"):"개별난방",
        ("가정용","중앙난방"):"중앙난방",
        ("영업용","일반용1"):"일반용1",
        ("업무용","일반용2"):"일반용2",
        ("업무용","냉난방용"):"냉난방용",
        ("업무용","주한미군"):"주한미군",
        ("수송용","BIO"):"BIO",
    }
    for (g,d), key in leaf_map.items():
        src=auto_map.get(key)
        if src:
            s=monthly_sum(df, year, src)
            for m in range(1,13):
                base.loc[(base["구분"]==g)&(base["세부"]==d), f"{m}월"]=float(s[m]) if pd.notna(s[m]) else 0.0
    # 합계형 라인(산업용·열병합·연료전지·자가열전용·열전용설비용·CNG)
    direct_groups=["산업용","열병합","연료전지","자가열전용","열전용설비용","CNG"]
    for g in direct_groups:
        src=auto_map.get(g)
        if src:
            s=monthly_sum(df, year, src)
            for m in range(1,13):
                base.loc[(base["구분"]==g)&(base["세부"]=="합계"), f"{m}월"]=float(s[m]) if pd.notna(s[m]) else 0.0
    filled=calc_subtotals(base)
    coerce_numeric_inplace(filled)
    return filled

# ───────────────── 데이터 소스
sb=st.sidebar; sb.header("데이터 불러오기")
src_mode=sb.radio("데이터 소스", ["리포 파일 사용","엑셀 업로드(.xlsx)"], index=0)
if src_mode=="리포 파일 사용":
    if not os.path.exists(DEFAULT_REPO_FILE):
        st.error(f"`{DEFAULT_REPO_FILE}` 파일이 리포에 없습니다."); st.stop()
    import openpyxl; xls=pd.ExcelFile(DEFAULT_REPO_FILE, engine="openpyxl"); file_name=DEFAULT_REPO_FILE
else:
    up=sb.file_uploader("엑셀 업로드(.xlsx)", type=["xlsx"])
    if not up: st.info("엑셀 업로드 후 표/그래프가 표시됩니다."); st.stop()
    import openpyxl; xls=pd.ExcelFile(io.BytesIO(up.getvalue()), engine="openpyxl"); file_name=up.name

scenario_candidates=[s for s in ["데이터","best","conservative"] if s in xls.sheet_names] or [xls.sheet_names[0]]
st.caption(f"소스: {file_name}")

scenario_tabs=st.tabs(scenario_candidates)
for scen_i, scen in enumerate(scenario_candidates):
    with scenario_tabs[scen_i]:
        st.subheader(f"시나리오: {scen}")
        raw=xls.parse(scen, header=0)
        try:
            df_prep, auto_map = prepare_df(raw)
        except Exception as e:
            st.error(f"[{scen}] 처리 오류: {e}"); continue

        with st.expander("자동 매핑 결과(필요시 수정)", expanded=False):
            for k in SYN.keys():
                cands=[c for c in df_prep.columns if likely_numeric(df_prep[c])]
                default=auto_map.get(k)
                if default and default not in cands: cands=[default]+cands
                auto_map[k]=st.selectbox(k, [None]+cands,
                                          index=(0 if default is None else ([None]+cands).index(default)),
                                          key=f"{scen}-{k}")

        year_tabs=st.tabs([f"{y}년 표" for y in [2024,2025,2026,2027]])
        tables={}
        existing_years=sorted(df_prep["_연도_"].dropna().unique().tolist())
        for idx,y in enumerate([2024,2025,2026,2027]):
            with year_tabs[idx]:
                tbl = build_table_for_year(df_prep, auto_map, y) if y in existing_years else calc_subtotals(blank_table())
                for c in MONTH_COLS+["합계"]:
                    tbl[c]=pd.to_numeric(tbl[c], errors="coerce").fillna(0).round(0).astype(int)
                sty=tbl[ALL_COLS].style.apply(highlight_rows, axis=None).format({c:"{:,.0f}".format for c in MONTH_COLS+["합계"]})
                st.dataframe(sty, use_container_width=True)
                tables[y]=tbl

        st.subheader("월별 추이 그래프")
        groups=["전체","가정용","영업용","업무용","산업용","열병합","연료전지","자가열전용","열전용설비용","CNG","수송용"]
        gsel=st.radio("보기 선택", groups, horizontal=True, index=0, key=f"grp-{scen}")

        def series(tbl, group):
            if group=="전체":
                mask = tbl["구분"].ne("합계") & tbl["세부"].ne("소계") & tbl["세부"].ne("합계")
            elif group=="수송용":
                mask = (tbl["구분"]=="수송용") & (tbl["세부"]=="소계")
            elif group in ["산업용","열병합","연료전지","자가열전용","열전용설비용","CNG"]:
                mask = (tbl["구분"]==group) & (tbl["세부"]=="합계")
            else:
                mask = (tbl["구분"]==group) & tbl["세부"].ne("소계") & tbl["세부"].ne("합계")
            s = tbl.loc[mask, MONTH_COLS].apply(pd.to_numeric, errors="coerce").sum(numeric_only=True)
            return [float(s.get(f"{m}월",0.0)) for m in range(1,13)]

        rows=[]
        for y in [2024,2025,2026,2027]:
            t=tables[y]; ys=series(t, gsel)
            for m,v in enumerate(ys,1): rows.append({"연도":str(y),"월":m,"공급량(㎥)":v})
        chart_df=pd.DataFrame(rows)
        sel=alt.selection_point(fields=["연도"], bind="legend")
        chart=(alt.Chart(chart_df)
               .mark_line(point=True)
               .encode(x=alt.X("월:O", title="월"),
                       y=alt.Y("공급량(㎥):Q", title="공급량(㎥)"),
                       color=alt.Color("연도:N", legend=alt.Legend(title="연도")),
                       tooltip=["연도","월","공급량(㎥)"])
               .add_params(sel)
               .transform_filter(sel)
               ).properties(height=360, width="container")
        st.altair_chart(chart, use_container_width=True)
