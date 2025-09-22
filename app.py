# === 바뀐 부분만 발췌 ===
import re

GROUP_NAMES = [
    "가정용","영업용","업무용","산업용","열병합","연료전지","자가열전용","열전용설비용","CNG","수송용","합계"
]

def simplify_key(s: str) -> str:
    s = unicodedata.normalize("NFC", str(s)).strip()
    return re.sub(r"[ \t/,_\-.]+", "", s).lower()

def parse_column_name(raw_name: str) -> Optional[Tuple[str, str]]:
    n = unicodedata.normalize("NFC", str(raw_name)).strip()
    key = simplify_key(n)

    # (1) 명시 매핑
    for k, (g, s) in COL_TO_GROUP.items():
        if simplify_key(k) == key:
            return (g, s)

    # (2) 그룹-세부 패턴(공백/슬래시/언더스코어/하이픈/점)
    parts = re.split(r"[ \t/,_\-.]+", n)
    if len(parts) >= 2:
        g_cand = parts[0]
        s_cand = " ".join(parts[1:])  # 나머지 모두 세부로
        if g_cand in GROUP_NAMES:
            return (g_cand, s_cand)

    # (3) '그룹세부' 붙은 형태
    for g in GROUP_NAMES:
        if n.startswith(g):
            rest = n[len(g):].strip()
            if rest:
                return (g, rest)
    return None

def sheet_column_order_pairs(raw_df: pd.DataFrame) -> List[Tuple[str, str]]:
    """엑셀 '열 등장 순서'를 그대로 보존."""
    order, seen = [], set()
    for c in raw_df.columns:
        p = parse_column_name(c)
        if p and p not in seen:
            order.append(p)
            seen.add(p)
    return order

def reorder_by_sheet_columns(pv: pd.DataFrame, order_pairs: List[Tuple[str, str]]) -> pd.DataFrame:
    """
    1) 엑셀 열 등장 순서를 '그룹/세부'의 절대 순서로 사용
    2) 그룹별 소계는 그룹 말미
    3) 전체 합계는 최하단
    """
    if pv.empty:
        return pv

    # ① 기본 순서: order_pairs에서 존재하는 행만 그대로 나열(소계/합계 제외)
    linear_order: List[Tuple[str, str]] = []
    for pair in order_pairs:
        if pair in pv.index and pair[1] not in ("소계", "합계"):
            linear_order.append(pair)

    # ② order_pairs에 없지만 pivot에 존재하는 행(소수의 예외) 뒤에 덧붙임
    for idx in pv.index:
        if idx[1] not in ("소계", "합계") and idx not in linear_order:
            linear_order.append(idx)

    # ③ 그룹별 소계는 각 그룹 말미에 배치
    final_index: List[Tuple[str, str]] = []
    grouped: Dict[str, List[Tuple[str, str]]] = {}
    for g, s in linear_order:
        grouped.setdefault(g, []).append((g, s))

    for g in [gp for gp, _ in order_pairs if gp != "합계"] + [g for g in grouped.keys() if g not in [gp for gp,_ in order_pairs]]:
        if g in grouped:
            final_index.extend(grouped[g])
            if (g, "소계") in pv.index:
                final_index.append((g, "소계"))

    # ④ 전체 합계는 최하단
    if ("합계", "합계") in pv.index:
        final_index.append(("합계", "합계"))

    # ⑤ 누락/중복 보정
    seen = set()
    cleaned = []
    for idx in final_index:
        if idx in pv.index and idx not in seen:
            cleaned.append(idx)
            seen.add(idx)
    for idx in pv.index:
        if idx not in seen:
            cleaned.append(idx)

    return pv.reindex(cleaned)
# === 바뀐 부분 끝 ===
