"""Concept membership and THS member data models."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ConceptMember:
    """概念板块成分股 (concept_detail)."""

    id: str  # 概念ID
    concept_name: str  # 概念名称
    ts_code: str  # 股票代码
    name: str  # 股票名称
    in_date: str  # 纳入日期
    out_date: str  # 剔除日期 (空=仍在)


@dataclass(frozen=True)
class ThsMember:
    """同花顺概念成分股 (ths_member)."""

    ts_code: str  # 概念指数代码
    code: str  # 成分股代码
    name: str  # 成分股名称
    weight: float  # 权重
    in_date: str
    out_date: str
    is_new: str  # 是否新进 (Y/N)
