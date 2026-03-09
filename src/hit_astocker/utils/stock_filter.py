"""Stock filtering utilities."""


def is_st_stock(name: str) -> bool:
    """Check if stock is ST (Special Treatment)."""
    upper = name.upper()
    return "ST" in upper or "*ST" in upper


def is_bj_stock(ts_code: str) -> bool:
    """Check if stock is on Beijing Stock Exchange."""
    return ts_code.endswith(".BJ")


def should_exclude(ts_code: str, name: str, max_mv: float = 0, total_mv: float = 0) -> bool:
    """Check if stock should be excluded from analysis."""
    if is_st_stock(name):
        return True
    if is_bj_stock(ts_code):
        return True
    if max_mv > 0 and total_mv > max_mv:
        return True
    return False
