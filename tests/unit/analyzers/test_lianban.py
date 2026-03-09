"""Tests for consecutive board (lianban) analyzer."""

from datetime import date

from hit_astocker.analyzers.lianban import LianbanAnalyzer
from hit_astocker.repositories.base import BaseRepository


def test_lianban_ladder(in_memory_db, sample_step_records):
    repo = BaseRepository(in_memory_db, "limit_step")
    repo.upsert_many(sample_step_records)
    in_memory_db.commit()

    analyzer = LianbanAnalyzer(in_memory_db)
    result = analyzer.analyze(date(2026, 3, 6))

    assert result.max_height == 5
    assert result.leader_name == "测试股票D"
    assert result.leader_code == "600003.SH"
    assert len(result.tiers) == 3  # 2板, 3板, 5板

    # Tiers should be sorted by height descending
    heights = [t.height for t in result.tiers]
    assert heights == sorted(heights, reverse=True)


def test_lianban_promotion_rate(in_memory_db, sample_step_records):
    repo = BaseRepository(in_memory_db, "limit_step")
    repo.upsert_many(sample_step_records)
    in_memory_db.commit()

    analyzer = LianbanAnalyzer(in_memory_db)
    result = analyzer.analyze(date(2026, 3, 6))

    # 2板 tier: yesterday had 2 stocks at 1板, today has 1 at 2板 => rate = 0.5
    tier_2 = next(t for t in result.tiers if t.height == 2)
    assert tier_2.yesterday_count == 2  # 600001.SH and 600004.SH were 1板 yesterday
    assert tier_2.count == 1


def test_lianban_no_data(in_memory_db):
    analyzer = LianbanAnalyzer(in_memory_db)
    result = analyzer.analyze(date(2026, 1, 1))

    assert result.max_height == 0
    assert result.tiers == ()
    assert result.leader_code == ""
