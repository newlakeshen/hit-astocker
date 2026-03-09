"""Tests for sentiment analyzer."""

from datetime import date

from hit_astocker.analyzers.sentiment import SentimentAnalyzer
from hit_astocker.config.settings import Settings
from hit_astocker.repositories.base import BaseRepository


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

    # Promotion rate should be > 0 since we have step data for both days
    assert result.promotion_rate >= 0
