from datetime import date

from hit_astocker.analyzers.stock_sentiment import StockSentimentAnalyzer
from hit_astocker.models.event_data import EventAnalysisResult, StockEvent, ThemeHeat
from hit_astocker.repositories.base import BaseRepository


def test_stock_sentiment_reuses_precomputed_event_result(in_memory_db):
    BaseRepository(in_memory_db, "kpl_list").upsert_many([{
        "trade_date": "20260306",
        "ts_code": "000001.SZ",
        "name": "测试股",
        "lu_time": "09:35:00",
        "ld_time": "",
        "lu_desc": "机器人订单超预期",
        "tag": "涨停",
        "theme": "机器人",
        "net_change": 0.0,
        "bid_amount": 3000.0,
        "status": "封板",
        "pct_chg": 10.0,
        "amount": 50000.0,
        "turnover_rate": 5.0,
        "lu_limit_order": 10000.0,
    }])
    BaseRepository(in_memory_db, "daily_bar").upsert_many([
        {
            "trade_date": "20260305", "ts_code": "000001.SZ",
            "open": 9.8, "high": 10.0, "low": 9.7, "close": 9.9,
            "pre_close": 9.7, "change": 0.2, "pct_chg": 2.0,
            "vol": 1000.0, "amount": 10000.0,
        },
        {
            "trade_date": "20260306", "ts_code": "000001.SZ",
            "open": 10.0, "high": 10.5, "low": 9.9, "close": 10.3,
            "pre_close": 9.9, "change": 0.4, "pct_chg": 4.0,
            "vol": 3000.0, "amount": 30000.0,
        },
    ])
    in_memory_db.commit()

    analyzer = StockSentimentAnalyzer(in_memory_db)

    def should_not_run(_):
        raise AssertionError("should not run")

    analyzer._event_classifier.analyze = should_not_run

    event_result = EventAnalysisResult(
        trade_date=date(2026, 3, 6),
        stock_events=(
            StockEvent(
                ts_code="000001.SZ",
                name="测试股",
                lu_desc="机器人订单超预期",
                event_type="消息面",
                event_types=("消息面",),
                event_weight=0.8,
                theme="机器人",
                themes=("机器人",),
            ),
        ),
        theme_heats=(
            ThemeHeat(
                theme_name="机器人",
                today_count=1,
                yesterday_count=0,
                persistence_days=1,
                heat_trend="NEW",
                heat_score=88.0,
                leader_codes=("000001.SZ",),
                leader_names=("测试股",),
            ),
        ),
        event_distribution={"消息面": 1},
        dominant_event_type="消息面",
        theme_concentration=1.0,
        market_narrative="机器人主线",
    )

    scores = analyzer.analyze(date(2026, 3, 6), event_result=event_result)

    assert len(scores) == 1
    assert scores[0].theme_heat_score == 88.0
    assert scores[0].event_catalyst_score == 80.0
