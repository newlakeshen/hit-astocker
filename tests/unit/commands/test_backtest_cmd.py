from datetime import date

from hit_astocker.commands.backtest_cmd import (
    _collect_range_coverage,
    _resolve_backtest_window,
)
from hit_astocker.repositories.base import BaseRepository
from hit_astocker.utils.trade_calendar import init_trade_calendar


def _insert_trade_days(conn) -> None:
    conn.executemany(
        "INSERT OR IGNORE INTO trade_cal (cal_date, is_open) VALUES (?, ?)",
        [
            ("20260305", 1),
            ("20260306", 1),
            ("20260307", 0),
            ("20260308", 0),
            ("20260309", 1),
            ("20260310", 1),
        ],
    )
    conn.commit()
    init_trade_calendar(conn)


def test_collect_range_coverage_uses_only_executable_signal_days(in_memory_db):
    _insert_trade_days(in_memory_db)

    BaseRepository(in_memory_db, "daily_bar").upsert_many([
        {
            "trade_date": "20260306", "ts_code": "000001.SZ",
            "open": 10.0, "high": 10.5, "low": 9.8, "close": 10.2,
            "pre_close": 9.9, "change": 0.3, "pct_chg": 3.0,
            "vol": 1000.0, "amount": 10000.0,
        },
        {
            "trade_date": "20260309", "ts_code": "000001.SZ",
            "open": 10.2, "high": 10.8, "low": 10.1, "close": 10.6,
            "pre_close": 10.2, "change": 0.4, "pct_chg": 3.9,
            "vol": 1200.0, "amount": 12000.0,
        },
        {
            "trade_date": "20260310", "ts_code": "000001.SZ",
            "open": 10.6, "high": 11.0, "low": 10.4, "close": 10.9,
            "pre_close": 10.6, "change": 0.3, "pct_chg": 2.8,
            "vol": 1300.0, "amount": 13000.0,
        },
    ])
    BaseRepository(in_memory_db, "ths_hot").upsert_many([
        {
            "trade_date": "20260305", "ts_code": "000001.SZ", "ts_name": "测试",
            "data_type": "热股", "current_price": 10.0, "rank": 1,
            "pct_change": 5.0, "rank_reason": "", "rank_time": "09:30:00",
            "concept": "机器人", "hot": 100, "market": "热股",
        },
        {
            "trade_date": "20260309", "ts_code": "000001.SZ", "ts_name": "测试",
            "data_type": "热股", "current_price": 10.6, "rank": 2,
            "pct_change": 3.0, "rank_reason": "", "rank_time": "09:30:00",
            "concept": "机器人", "hot": 90, "market": "热股",
        },
    ])
    BaseRepository(in_memory_db, "anns_d").upsert_many([{
        "ann_date": "20260306", "ts_code": "000001.SZ",
        "title": "签订合同", "ann_type": "中标", "content": "",
    }])
    in_memory_db.commit()

    coverage = _collect_range_coverage(
        in_memory_db,
        [date(2026, 3, 5), date(2026, 3, 6), date(2026, 3, 9)],
    )

    assert coverage.requested_days == 3
    assert coverage.executable_days == 2

    by_label = {bucket.label: bucket for bucket in coverage.buckets}
    assert by_label["同花顺热股"].covered_days == 1
    assert by_label["公告"].covered_days == 1
    assert by_label["北向资金"].covered_days == 0


def test_resolve_backtest_window_defaults_to_latest_executable_trailing_years(in_memory_db):
    _insert_trade_days(in_memory_db)

    BaseRepository(in_memory_db, "daily_bar").upsert_many([
        {
            "trade_date": "20260305", "ts_code": "000001.SZ",
            "open": 10.0, "high": 10.5, "low": 9.8, "close": 10.2,
            "pre_close": 9.9, "change": 0.3, "pct_chg": 3.0,
            "vol": 1000.0, "amount": 10000.0,
        },
        {
            "trade_date": "20260306", "ts_code": "000001.SZ",
            "open": 10.2, "high": 10.8, "low": 10.1, "close": 10.6,
            "pre_close": 10.2, "change": 0.4, "pct_chg": 3.9,
            "vol": 1200.0, "amount": 12000.0,
        },
        {
            "trade_date": "20260309", "ts_code": "000001.SZ",
            "open": 10.6, "high": 11.0, "low": 10.4, "close": 10.9,
            "pre_close": 10.6, "change": 0.3, "pct_chg": 2.8,
            "vol": 1300.0, "amount": 13000.0,
        },
        {
            "trade_date": "20260310", "ts_code": "000001.SZ",
            "open": 10.9, "high": 11.2, "low": 10.7, "close": 11.0,
            "pre_close": 10.9, "change": 0.1, "pct_chg": 0.9,
            "vol": 1400.0, "amount": 14000.0,
        },
    ])
    in_memory_db.commit()

    window = _resolve_backtest_window(in_memory_db, None, None, 6)

    assert window.end_date == date(2026, 3, 6)
    assert window.start_date == date(2026, 3, 5)
    assert window.truncated
    assert window.requested_years == 6
