"""Shared test fixtures."""

import sqlite3

import pytest

from hit_astocker.database.schema import init_schema


@pytest.fixture
def in_memory_db():
    """Create an in-memory SQLite database with schema applied."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_schema(conn)
    yield conn
    conn.close()


@pytest.fixture
def sample_limit_up_records():
    """Factory for realistic limit-up records."""
    return [
        {
            "trade_date": "20260306",
            "ts_code": "000001.SZ",
            "name": "平安银行",
            "industry": "银行",
            "close": 15.50,
            "pct_chg": 10.0,
            "amount": 50000.0,
            "limit_amount": 8000.0,
            "float_mv": 200000.0,
            "total_mv": 300000.0,
            "turnover_ratio": 5.2,
            "fd_amount": 3000.0,
            "first_time": "09:35:00",
            "last_time": "09:35:00",
            "open_times": 0,
            "up_stat": "1/1",
            "limit_times": 1,
            "limit": "U",
        },
        {
            "trade_date": "20260306",
            "ts_code": "600001.SH",
            "name": "测试股票A",
            "industry": "半导体",
            "close": 25.00,
            "pct_chg": 10.0,
            "amount": 80000.0,
            "limit_amount": 12000.0,
            "float_mv": 150000.0,
            "total_mv": 200000.0,
            "turnover_ratio": 8.5,
            "fd_amount": 5000.0,
            "first_time": "10:15:00",
            "last_time": "10:15:00",
            "open_times": 1,
            "up_stat": "2/3",
            "limit_times": 2,
            "limit": "U",
        },
        {
            "trade_date": "20260306",
            "ts_code": "300001.SZ",
            "name": "测试股票B",
            "industry": "新能源",
            "close": 35.00,
            "pct_chg": 20.0,
            "amount": 120000.0,
            "limit_amount": 5000.0,
            "float_mv": 100000.0,
            "total_mv": 120000.0,
            "turnover_ratio": 15.3,
            "fd_amount": 2000.0,
            "first_time": "14:20:00",
            "last_time": "14:50:00",
            "open_times": 3,
            "up_stat": "1/1",
            "limit_times": 1,
            "limit": "U",
        },
    ]


@pytest.fixture
def sample_limit_down_records():
    return [
        {
            "trade_date": "20260306",
            "ts_code": "002001.SZ",
            "name": "跌停A",
            "industry": "房地产",
            "close": 5.00,
            "pct_chg": -10.0,
            "amount": 30000.0,
            "limit_amount": 0.0,
            "float_mv": 80000.0,
            "total_mv": 100000.0,
            "turnover_ratio": 3.0,
            "fd_amount": 0.0,
            "first_time": "09:30:00",
            "last_time": "09:30:00",
            "open_times": 0,
            "up_stat": "",
            "limit_times": 1,
            "limit": "D",
        },
    ]


@pytest.fixture
def sample_broken_records():
    return [
        {
            "trade_date": "20260306",
            "ts_code": "003001.SZ",
            "name": "炸板A",
            "industry": "医药",
            "close": 20.00,
            "pct_chg": 5.0,
            "amount": 60000.0,
            "limit_amount": 0.0,
            "float_mv": 90000.0,
            "total_mv": 110000.0,
            "turnover_ratio": 12.0,
            "fd_amount": 0.0,
            "first_time": "10:00:00",
            "last_time": "13:30:00",
            "open_times": 2,
            "up_stat": "",
            "limit_times": 0,
            "limit": "Z",
        },
    ]


@pytest.fixture
def sample_step_records():
    return [
        {"trade_date": "20260306", "ts_code": "600001.SH", "name": "测试股票A", "nums": 2},
        {"trade_date": "20260306", "ts_code": "600002.SH", "name": "测试股票C", "nums": 3},
        {"trade_date": "20260306", "ts_code": "600003.SH", "name": "测试股票D", "nums": 5},
        {"trade_date": "20260305", "ts_code": "600001.SH", "name": "测试股票A", "nums": 1},
        {"trade_date": "20260305", "ts_code": "600002.SH", "name": "测试股票C", "nums": 2},
        {"trade_date": "20260305", "ts_code": "600003.SH", "name": "测试股票D", "nums": 4},
        {"trade_date": "20260305", "ts_code": "600004.SH", "name": "测试股票E", "nums": 1},
    ]
