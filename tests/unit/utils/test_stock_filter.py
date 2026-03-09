"""Tests for stock filtering utilities."""

from hit_astocker.utils.stock_filter import is_bj_stock, is_st_stock, should_exclude


def test_st_detection():
    assert is_st_stock("ST中天")
    assert is_st_stock("*ST金洲")
    assert not is_st_stock("平安银行")
    assert not is_st_stock("中天科技")


def test_bj_stock():
    assert is_bj_stock("430047.BJ")
    assert not is_bj_stock("000001.SZ")
    assert not is_bj_stock("600001.SH")


def test_should_exclude():
    assert should_exclude("000001.SZ", "ST测试")
    assert should_exclude("430047.BJ", "北交所测试")
    assert not should_exclude("000001.SZ", "正常股票")

    # Market cap filter
    assert should_exclude("000001.SZ", "正常", max_mv=100, total_mv=150)
    assert not should_exclude("000001.SZ", "正常", max_mv=200, total_mv=150)
