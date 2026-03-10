"""Tests for 9-factor sentiment analyzer."""

from datetime import date

import pytest

from hit_astocker.analyzers.sentiment import SentimentAnalyzer
from hit_astocker.config.settings import Settings
from hit_astocker.repositories.base import BaseRepository
from hit_astocker.utils.trade_calendar import init_trade_calendar


@pytest.fixture(autouse=True)
def _init_calendar(in_memory_db):
    """Ensure trade calendar is initialized for all sentiment tests."""
    in_memory_db.executemany(
        "INSERT OR IGNORE INTO trade_cal (cal_date, is_open) VALUES (?, ?)",
        [
            ("20260304", 1), ("20260305", 1), ("20260306", 1),
            ("20260307", 0), ("20260308", 0), ("20260309", 1),
        ],
    )
    in_memory_db.commit()
    init_trade_calendar(in_memory_db)


def _insert_data(conn, limit_records, step_records):
    repo_limit = BaseRepository(conn, "limit_list_d")
    repo_limit.upsert_many(limit_records)
    repo_step = BaseRepository(conn, "limit_step")
    repo_step.upsert_many(step_records)
    conn.commit()


def test_sentiment_basic(
    in_memory_db, sample_limit_up_records, sample_limit_down_records,
    sample_broken_records, sample_step_records,
):
    all_limit = sample_limit_up_records + sample_limit_down_records + sample_broken_records
    _insert_data(in_memory_db, all_limit, sample_step_records)

    settings = Settings(tushare_token="test")
    analyzer = SentimentAnalyzer(in_memory_db, settings)
    result = analyzer.analyze(date(2026, 3, 6))

    assert result.limit_up_count == 3
    assert result.limit_down_count == 1
    assert result.broken_count == 1
    assert result.up_down_ratio == 3.0
    assert 0 <= result.broken_rate <= 1.0
    assert result.max_consecutive_height == 5
    assert result.overall_score >= 0
    assert result.overall_score <= 100
    assert result.risk_level in ("LOW", "MEDIUM", "HIGH", "EXTREME")


def test_sentiment_no_data(in_memory_db):
    settings = Settings(tushare_token="test")
    analyzer = SentimentAnalyzer(in_memory_db, settings)
    result = analyzer.analyze(date(2026, 1, 1))

    assert result.limit_up_count == 0
    assert result.limit_down_count == 0
    assert result.overall_score >= 0


def test_sentiment_new_factors(
    in_memory_db, sample_limit_up_records, sample_limit_down_records,
    sample_broken_records, sample_step_records,
):
    """Test new 9-factor fields are populated."""
    all_limit = sample_limit_up_records + sample_limit_down_records + sample_broken_records
    _insert_data(in_memory_db, all_limit, sample_step_records)

    settings = Settings(tushare_token="test")
    analyzer = SentimentAnalyzer(in_memory_db, settings)
    result = analyzer.analyze(date(2026, 3, 6))

    # 一字板: 000001.SZ has open_times=0 → yizi
    assert result.yizi_count == 1
    assert result.yizi_ratio > 0

    # 10cm/20cm structure: 000001.SZ (00→10cm), 600001.SH (60→10cm), 300001.SZ (30→20cm)
    assert result.limit_up_10cm == 2
    assert result.limit_up_20cm == 1

    # 炸板修复: 600001.SH(open_times=1) + 300001.SZ(open_times=3) = 2 recovery
    # 003001.SZ is Z (broken stayed)
    assert result.recovery_count == 2
    assert result.broken_recovery_rate > 0

    # 高位晋级率
    assert 0 <= result.promo_rate_2to3 <= 1
    assert 0 <= result.promo_rate_3to4 <= 1


def test_sentiment_promotion_rate(in_memory_db, sample_step_records):
    repo = BaseRepository(in_memory_db, "limit_step")
    repo.upsert_many(sample_step_records)
    in_memory_db.commit()

    # Also need limit_list_d data for counts
    repo2 = BaseRepository(in_memory_db, "limit_list_d")
    repo2.upsert_many([
        {"trade_date": "20260306", "ts_code": "000001.SZ", "name": "Test", "industry": "",
         "close": 10, "pct_chg": 10, "amount": 0, "limit_amount": 0, "float_mv": 0,
         "total_mv": 0, "turnover_ratio": 0, "fd_amount": 0, "first_time": "", "last_time": "",
         "open_times": 0, "up_stat": "", "limit_times": 1, "limit": "U"},
    ])
    in_memory_db.commit()

    settings = Settings(tushare_token="test")
    analyzer = SentimentAnalyzer(in_memory_db, settings)
    result = analyzer.analyze(date(2026, 3, 6))

    assert result.promotion_rate >= 0


def test_sentiment_prev_premium(in_memory_db):
    """Test prev_limit_up_premium calculation."""
    # Insert yesterday's limit-up record
    repo_limit = BaseRepository(in_memory_db, "limit_list_d")
    repo_limit.upsert_many([{
        "trade_date": "20260305", "ts_code": "000001.SZ", "name": "Test",
        "industry": "", "close": 10.0, "pct_chg": 10, "amount": 5000,
        "limit_amount": 1000, "float_mv": 50000, "total_mv": 60000,
        "turnover_ratio": 5, "fd_amount": 500, "first_time": "09:35",
        "last_time": "09:35", "open_times": 0, "up_stat": "1/1",
        "limit_times": 1, "limit": "U",
    }])

    # Insert today's daily bar with higher open (premium)
    repo_bar = BaseRepository(in_memory_db, "daily_bar")
    repo_bar.upsert_many([{
        "trade_date": "20260306", "ts_code": "000001.SZ",
        "open": 10.5, "high": 11.0, "low": 10.0, "close": 10.8,
        "pre_close": 10.0, "change": 0.8, "pct_chg": 8.0,
        "vol": 100000, "amount": 50000,
    }])

    # Need today's limit data too
    repo_limit.upsert_many([{
        "trade_date": "20260306", "ts_code": "600001.SH", "name": "Other",
        "industry": "", "close": 20, "pct_chg": 10, "amount": 8000,
        "limit_amount": 2000, "float_mv": 100000, "total_mv": 120000,
        "turnover_ratio": 8, "fd_amount": 1000, "first_time": "10:00",
        "last_time": "10:00", "open_times": 0, "up_stat": "1/1",
        "limit_times": 1, "limit": "U",
    }])
    in_memory_db.commit()

    settings = Settings(tushare_token="test")
    analyzer = SentimentAnalyzer(in_memory_db, settings)
    result = analyzer.analyze(date(2026, 3, 6))

    # Premium should be (10.5 - 10.0) / 10.0 * 100 = 5.0%
    assert result.prev_limit_up_premium == 5.0


def test_sentiment_auction_strength(in_memory_db):
    """Test auction stats integration."""
    repo_auction = BaseRepository(in_memory_db, "stk_auction")
    repo_auction.upsert_many([
        {"trade_date": "20260306", "ts_code": "000001.SZ", "name": "A",
         "open": 10.5, "pre_close": 10.0, "change": 0.5, "pct_change": 5.0,
         "vol": 1000, "amount": 5000},
        {"trade_date": "20260306", "ts_code": "000002.SZ", "name": "B",
         "open": 9.8, "pre_close": 10.0, "change": -0.2, "pct_change": -2.0,
         "vol": 800, "amount": 4000},
    ])
    in_memory_db.commit()

    settings = Settings(tushare_token="test")
    analyzer = SentimentAnalyzer(in_memory_db, settings)
    result = analyzer.analyze(date(2026, 3, 6))

    # avg_pct = (5.0 + -2.0) / 2 = 1.5
    assert result.auction_avg_pct == 1.5
    # up_ratio = 1/2 = 0.5
    assert result.auction_up_ratio == 0.5
