"""Announcement data model."""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class AnnouncementRecord:
    """上市公司公告记录."""

    ts_code: str
    ann_date: date
    title: str
    ann_type: str  # 公告类型 (业绩预告/重大合同/资产重组/增减持...)
    content: str  # 公告摘要
