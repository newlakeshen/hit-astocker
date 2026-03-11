from datetime import date

from hit_astocker.models.daily_context import table_has_data_for_date
from hit_astocker.repositories.base import BaseRepository


def test_table_has_data_for_specific_trade_date(in_memory_db):
    repo = BaseRepository(in_memory_db, "ths_hot")
    repo.upsert_many([{
        "trade_date": "20260310",
        "ts_code": "000001.SZ",
        "ts_name": "测试",
        "data_type": "hot",
        "current_price": 10.0,
        "rank": 1,
        "pct_change": 5.0,
        "rank_reason": "",
        "rank_time": "09:30:00",
        "concept": "数据中心",
        "hot": 100,
        "market": "热股",
    }])
    in_memory_db.commit()

    assert table_has_data_for_date(in_memory_db, "ths_hot", date(2026, 3, 10))
    assert not table_has_data_for_date(in_memory_db, "ths_hot", date(2026, 3, 9))
