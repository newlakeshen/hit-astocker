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


def test_firstboard_prefers_kpl_seal_order_and_theme(in_memory_db):
    limit_repo = BaseRepository(in_memory_db, "limit_list_d")
    limit_repo.upsert_many([{
        "trade_date": "20260306",
        "ts_code": "000001.SZ",
        "name": "题材首板",
        "industry": "银行",
        "close": 10,
        "pct_chg": 10,
        "amount": 50000,
        "limit_amount": 0,
        "float_mv": 100000,
        "total_mv": 150000,
        "turnover_ratio": 5,
        "fd_amount": 0,
        "first_time": "09:32:00",
        "last_time": "09:32:00",
        "open_times": 0,
        "up_stat": "1/1",
        "limit_times": 1,
        "limit": "U",
    }])
    kpl_repo = BaseRepository(in_memory_db, "kpl_list")
    kpl_repo.upsert_many([{
        "trade_date": "20260306",
        "ts_code": "000001.SZ",
        "name": "题材首板",
        "lu_time": "09:32:00",
        "ld_time": "",
        "lu_desc": "算力",
        "tag": "涨停",
        "theme": "数据中心、AI应用",
        "net_change": 0,
        "bid_amount": 0,
        "status": "",
        "pct_chg": 10,
        "amount": 50000,
        "turnover_rate": 5,
        "lu_limit_order": 12000,
    }])
    sector_repo = BaseRepository(in_memory_db, "limit_cpt_list")
    sector_repo.upsert_many([{
        "trade_date": "20260306",
        "ts_code": "BK001",
        "name": "数据中心",
        "days": 1,
        "up_stat": "",
        "cons_nums": 1,
        "up_nums": 10,
        "pct_chg": 3.2,
        "rank": "1",
    }])
    in_memory_db.commit()

    settings = Settings(tushare_token="test")
    analyzer = FirstBoardAnalyzer(in_memory_db, settings)
    result = analyzer.analyze(date(2026, 3, 6))[0]

    assert result.limit_amount == 12000
    assert result.seal_strength_score > 25
    assert result.sector_name == "数据中心"
    assert result.sector_score == 100.0
