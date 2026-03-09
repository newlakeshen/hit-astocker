"""Tests for first-board analyzer."""

from datetime import date

from hit_astocker.analyzers.firstboard import FirstBoardAnalyzer
from hit_astocker.config.settings import Settings
from hit_astocker.repositories.base import BaseRepository


def test_firstboard_analysis(in_memory_db, sample_limit_up_records):
    repo = BaseRepository(in_memory_db, "limit_list_d")
    repo.upsert_many(sample_limit_up_records)
    in_memory_db.commit()

    settings = Settings(tushare_token="test")
    analyzer = FirstBoardAnalyzer(in_memory_db, settings)
    results = analyzer.analyze(date(2026, 3, 6))

    # Only stocks with limit_times == 1 are first-board
    first_boards = [r for r in sample_limit_up_records if r["limit_times"] == 1]
    assert len(results) == len(first_boards)

    # Should be sorted by composite score descending
    scores = [r.composite_score for r in results]
    assert scores == sorted(scores, reverse=True)


def test_firstboard_seal_time_scoring(in_memory_db):
    records = [
        {
            "trade_date": "20260306", "ts_code": "000001.SZ", "name": "早封",
            "industry": "", "close": 10, "pct_chg": 10, "amount": 50000,
            "limit_amount": 10000, "float_mv": 100000, "total_mv": 150000,
            "turnover_ratio": 5, "fd_amount": 3000, "first_time": "09:32:00",
            "last_time": "09:32:00", "open_times": 0, "up_stat": "1/1",
            "limit_times": 1, "limit": "U",
        },
        {
            "trade_date": "20260306", "ts_code": "000002.SZ", "name": "晚封",
            "industry": "", "close": 10, "pct_chg": 10, "amount": 50000,
            "limit_amount": 10000, "float_mv": 100000, "total_mv": 150000,
            "turnover_ratio": 5, "fd_amount": 3000, "first_time": "14:30:00",
            "last_time": "14:30:00", "open_times": 0, "up_stat": "1/1",
            "limit_times": 1, "limit": "U",
        },
    ]
    repo = BaseRepository(in_memory_db, "limit_list_d")
    repo.upsert_many(records)
    in_memory_db.commit()

    settings = Settings(tushare_token="test")
    analyzer = FirstBoardAnalyzer(in_memory_db, settings)
    results = analyzer.analyze(date(2026, 3, 6))

    # Early seal should score higher
    early = next(r for r in results if r.ts_code == "000001.SZ")
    late = next(r for r in results if r.ts_code == "000002.SZ")
    assert early.seal_time_score > late.seal_time_score


def test_firstboard_no_data(in_memory_db):
    settings = Settings(tushare_token="test")
    analyzer = FirstBoardAnalyzer(in_memory_db, settings)
    results = analyzer.analyze(date(2026, 1, 1))
    assert results == []
