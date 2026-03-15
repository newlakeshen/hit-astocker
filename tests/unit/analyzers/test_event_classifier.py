"""Tests for 3-layer event classifier."""

from datetime import date

import pytest

from hit_astocker.analyzers.event_classifier import EventClassifier
from hit_astocker.models.event_data import EventType
from hit_astocker.repositories.base import BaseRepository
from hit_astocker.utils.trade_calendar import init_trade_calendar


@pytest.fixture(autouse=True)
def _init_calendar(in_memory_db):
    in_memory_db.executemany(
        "INSERT OR IGNORE INTO trade_cal (cal_date, is_open) VALUES (?, ?)",
        [
            ("20260303", 1),
            ("20260304", 1),
            ("20260305", 1),
            ("20260306", 1),
            ("20260307", 0),
            ("20260308", 0),
        ],
    )
    in_memory_db.commit()
    init_trade_calendar(in_memory_db)


def _insert_kpl(conn, records):
    repo = BaseRepository(conn, "kpl_list")
    repo.upsert_many(records)
    conn.commit()


def _make_kpl_record(ts_code, name, lu_desc="", theme="", tag="涨停"):
    return {
        "trade_date": "20260306",
        "ts_code": ts_code,
        "name": name,
        "lu_time": "09:35",
        "ld_time": "",
        "lu_desc": lu_desc,
        "tag": tag,
        "theme": theme,
        "net_change": 0,
        "bid_amount": 0,
        "status": "封板",
        "pct_chg": 10.0,
        "amount": 50000,
        "turnover_rate": 5.0,
        "lu_limit_order": 0,
    }


def test_layer1_announcement_classification(in_memory_db):
    """L1: Stock with matching announcement should be classified by ann_type."""
    _insert_kpl(
        in_memory_db,
        [
            _make_kpl_record("000001.SZ", "测试A", lu_desc="", theme=""),
        ],
    )

    # Insert announcement
    repo = BaseRepository(in_memory_db, "anns_d")
    repo.upsert_many(
        [
            {
                "ann_date": "20260306",
                "ts_code": "000001.SZ",
                "title": "关于签订重大合同的公告",
                "ann_type": "中标",
                "content": "",
            }
        ]
    )
    in_memory_db.commit()

    classifier = EventClassifier(in_memory_db)
    result = classifier.analyze(date(2026, 3, 6))

    assert len(result.stock_events) == 1
    ev = result.stock_events[0]
    assert ev.event_type == EventType.NEWS  # 中标 → NEWS
    assert ev.event_layer == "ANNOUNCEMENT"
    assert "合同" in ev.ann_title


def test_layer2_concept_classification(in_memory_db):
    """L2: Stock with concept membership should be classified by concept."""
    _insert_kpl(
        in_memory_db,
        [
            _make_kpl_record("000002.SZ", "测试B", lu_desc="", theme="人工智能"),
        ],
    )

    # Insert concept membership (no announcement)
    repo = BaseRepository(in_memory_db, "concept_detail")
    repo.upsert_many(
        [
            {
                "id": "C001",
                "concept_name": "碳中和概念",
                "ts_code": "000002.SZ",
                "name": "测试B",
                "in_date": "20200101",
                "out_date": None,
            }
        ]
    )
    in_memory_db.commit()

    classifier = EventClassifier(in_memory_db)
    result = classifier.analyze(date(2026, 3, 6))

    ev = result.stock_events[0]
    assert ev.event_type == EventType.POLICY  # 碳中和 → POLICY
    assert ev.event_layer == "CONCEPT"
    assert "碳中和概念" in ev.concepts


def test_layer3_keyword_fallback(in_memory_db):
    """L3: Without announcement or concept, fall back to keyword matching."""
    _insert_kpl(
        in_memory_db,
        [
            _make_kpl_record("000003.SZ", "测试C", lu_desc="业绩预增超预期", theme=""),
        ],
    )
    in_memory_db.commit()

    classifier = EventClassifier(in_memory_db)
    result = classifier.analyze(date(2026, 3, 6))

    ev = result.stock_events[0]
    assert ev.event_type == EventType.EARNINGS  # 业绩 keyword
    assert ev.event_layer == "KEYWORD"


def test_layer3_theme_keyword_fallback(in_memory_db):
    """L3: Theme names like '化工' should classify as INDUSTRY, not UNKNOWN."""
    _insert_kpl(
        in_memory_db,
        [
            _make_kpl_record("000004.SZ", "测试D", lu_desc="涨停原因不明", theme="化工"),
        ],
    )
    in_memory_db.commit()

    classifier = EventClassifier(in_memory_db)
    result = classifier.analyze(date(2026, 3, 6))

    ev = result.stock_events[0]
    assert ev.event_type == EventType.INDUSTRY  # 化工 → INDUSTRY
    assert ev.event_layer == "KEYWORD"


def test_unknown_reduced(in_memory_db):
    """Theme-based fallback should catch cases that previously fell to UNKNOWN."""
    _insert_kpl(
        in_memory_db,
        [
            _make_kpl_record("000010.SZ", "AI股", lu_desc="", theme="人工智能"),
            _make_kpl_record("000011.SZ", "建设股", lu_desc="", theme="基础建设"),
        ],
    )
    in_memory_db.commit()

    classifier = EventClassifier(in_memory_db)
    result = classifier.analyze(date(2026, 3, 6))

    # Neither should be UNKNOWN
    for ev in result.stock_events:
        assert ev.event_type != EventType.UNKNOWN, f"{ev.name} classified as UNKNOWN"


def test_layer_priority_announcement_wins(in_memory_db):
    """L1 announcement should take priority over L2 concept."""
    _insert_kpl(
        in_memory_db,
        [
            _make_kpl_record("000005.SZ", "优先级测试", lu_desc="", theme=""),
        ],
    )

    # Both announcement AND concept exist
    ann_repo = BaseRepository(in_memory_db, "anns_d")
    ann_repo.upsert_many(
        [
            {
                "ann_date": "20260306",
                "ts_code": "000005.SZ",
                "title": "业绩预增200%",
                "ann_type": "业绩预告",
                "content": "",
            }
        ]
    )
    concept_repo = BaseRepository(in_memory_db, "concept_detail")
    concept_repo.upsert_many(
        [
            {
                "id": "C002",
                "concept_name": "新能源车",
                "ts_code": "000005.SZ",
                "name": "优先级测试",
                "in_date": "20200101",
                "out_date": None,
            }
        ]
    )
    in_memory_db.commit()

    classifier = EventClassifier(in_memory_db)
    result = classifier.analyze(date(2026, 3, 6))

    ev = result.stock_events[0]
    assert ev.event_type == EventType.EARNINGS  # L1 wins
    assert ev.event_layer == "ANNOUNCEMENT"


def test_diffusion_rate(in_memory_db):
    """Diffusion rate should reflect % of concept members that are limit-up."""
    _insert_kpl(
        in_memory_db,
        [
            _make_kpl_record("000001.SZ", "A", theme="碳中和"),
            _make_kpl_record("000002.SZ", "B", theme="碳中和"),
        ],
    )

    # Insert concept with 4 members, 2 are limit-up
    concept_repo = BaseRepository(in_memory_db, "concept_detail")
    concept_repo.upsert_many(
        [
            {
                "id": "C100",
                "concept_name": "碳中和概念",
                "ts_code": "000001.SZ",
                "name": "A",
                "in_date": "",
                "out_date": None,
            },
            {
                "id": "C100",
                "concept_name": "碳中和概念",
                "ts_code": "000002.SZ",
                "name": "B",
                "in_date": "",
                "out_date": None,
            },
            {
                "id": "C100",
                "concept_name": "碳中和概念",
                "ts_code": "000003.SZ",
                "name": "C",
                "in_date": "",
                "out_date": None,
            },
            {
                "id": "C100",
                "concept_name": "碳中和概念",
                "ts_code": "000004.SZ",
                "name": "D",
                "in_date": "",
                "out_date": None,
            },
        ]
    )
    in_memory_db.commit()

    classifier = EventClassifier(in_memory_db)
    result = classifier.analyze(date(2026, 3, 6))

    # Both stocks should have diffusion_rate = 2/4 = 0.5
    for ev in result.stock_events:
        assert ev.diffusion_rate == 0.5


def test_narrative_includes_layer_info(in_memory_db):
    """Market narrative should include layer coverage breakdown."""
    _insert_kpl(
        in_memory_db,
        [
            _make_kpl_record("000001.SZ", "A", lu_desc="业绩预增", theme="半导体"),
        ],
    )
    in_memory_db.commit()

    classifier = EventClassifier(in_memory_db)
    result = classifier.analyze(date(2026, 3, 6))

    assert "识别" in result.market_narrative
