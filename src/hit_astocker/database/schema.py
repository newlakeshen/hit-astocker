"""Database schema definitions."""

TABLES = {
    "limit_list_d": """
        CREATE TABLE IF NOT EXISTS limit_list_d (
            trade_date TEXT NOT NULL,
            ts_code TEXT NOT NULL,
            name TEXT,
            industry TEXT,
            "close" REAL,
            pct_chg REAL,
            amount REAL,
            limit_amount REAL,
            float_mv REAL,
            total_mv REAL,
            turnover_ratio REAL,
            fd_amount REAL,
            first_time TEXT,
            last_time TEXT,
            open_times INTEGER,
            up_stat TEXT,
            limit_times INTEGER,
            "limit" TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (trade_date, ts_code, "limit")
        )
    """,
    "limit_step": """
        CREATE TABLE IF NOT EXISTS limit_step (
            trade_date TEXT NOT NULL,
            ts_code TEXT NOT NULL,
            name TEXT,
            nums INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (trade_date, ts_code)
        )
    """,
    "limit_cpt_list": """
        CREATE TABLE IF NOT EXISTS limit_cpt_list (
            trade_date TEXT NOT NULL,
            ts_code TEXT NOT NULL,
            name TEXT,
            days INTEGER,
            up_stat TEXT,
            cons_nums INTEGER,
            up_nums INTEGER,
            pct_chg REAL,
            rank TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (trade_date, ts_code)
        )
    """,
    "limit_list_ths": """
        CREATE TABLE IF NOT EXISTS limit_list_ths (
            trade_date TEXT NOT NULL,
            ts_code TEXT NOT NULL,
            name TEXT,
            price REAL,
            pct_chg REAL,
            open_num INTEGER,
            lu_desc TEXT,
            limit_type TEXT,
            tag TEXT,
            status TEXT,
            first_lu_time TEXT,
            first_ld_time TEXT,
            limit_order REAL,
            turnover_rate REAL,
            market_type TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (trade_date, ts_code, limit_type)
        )
    """,
    "kpl_list": """
        CREATE TABLE IF NOT EXISTS kpl_list (
            trade_date TEXT NOT NULL,
            ts_code TEXT NOT NULL,
            name TEXT,
            lu_time TEXT,
            ld_time TEXT,
            lu_desc TEXT,
            tag TEXT,
            theme TEXT,
            net_change REAL,
            bid_amount REAL,
            status TEXT,
            pct_chg REAL,
            amount REAL,
            turnover_rate REAL,
            lu_limit_order REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (trade_date, ts_code, tag)
        )
    """,
    "top_list": """
        CREATE TABLE IF NOT EXISTS top_list (
            trade_date TEXT NOT NULL,
            ts_code TEXT NOT NULL,
            name TEXT,
            "close" REAL,
            pct_change REAL,
            turnover_rate REAL,
            amount REAL,
            l_sell REAL,
            l_buy REAL,
            l_amount REAL,
            net_amount REAL,
            net_rate REAL,
            amount_rate REAL,
            float_values REAL,
            reason TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (trade_date, ts_code)
        )
    """,
    "top_inst": """
        CREATE TABLE IF NOT EXISTS top_inst (
            trade_date TEXT NOT NULL,
            ts_code TEXT NOT NULL,
            exalter TEXT,
            side TEXT,
            buy REAL,
            buy_rate REAL,
            sell REAL,
            sell_rate REAL,
            net_buy REAL,
            reason TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (trade_date, ts_code, exalter, side)
        )
    """,
    "moneyflow_ths": """
        CREATE TABLE IF NOT EXISTS moneyflow_ths (
            trade_date TEXT NOT NULL,
            ts_code TEXT NOT NULL,
            name TEXT,
            pct_change REAL,
            latest REAL,
            net_amount REAL,
            net_d5_amount REAL,
            buy_lg_amount REAL,
            buy_lg_amount_rate REAL,
            buy_md_amount REAL,
            buy_md_amount_rate REAL,
            buy_sm_amount REAL,
            buy_sm_amount_rate REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (trade_date, ts_code)
        )
    """,
    "sentiment_daily": """
        CREATE TABLE IF NOT EXISTS sentiment_daily (
            trade_date TEXT NOT NULL PRIMARY KEY,
            limit_up_count INTEGER,
            limit_down_count INTEGER,
            broken_count INTEGER,
            up_down_ratio REAL,
            broken_rate REAL,
            max_consecutive_height INTEGER,
            avg_consecutive_height REAL,
            promotion_rate REAL,
            money_effect_score REAL,
            overall_score REAL,
            risk_level TEXT,
            description TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """,
    "moneyflow_detail": """
        CREATE TABLE IF NOT EXISTS moneyflow_detail (
            trade_date TEXT NOT NULL,
            ts_code TEXT NOT NULL,
            buy_sm_vol REAL,
            buy_sm_amount REAL,
            sell_sm_vol REAL,
            sell_sm_amount REAL,
            buy_md_vol REAL,
            buy_md_amount REAL,
            sell_md_vol REAL,
            sell_md_amount REAL,
            buy_lg_vol REAL,
            buy_lg_amount REAL,
            sell_lg_vol REAL,
            sell_lg_amount REAL,
            buy_elg_vol REAL,
            buy_elg_amount REAL,
            sell_elg_vol REAL,
            sell_elg_amount REAL,
            net_mf_vol REAL,
            net_mf_amount REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (trade_date, ts_code)
        )
    """,
    "daily_bar": """
        CREATE TABLE IF NOT EXISTS daily_bar (
            trade_date TEXT NOT NULL,
            ts_code TEXT NOT NULL,
            "open" REAL,
            high REAL,
            low REAL,
            "close" REAL,
            pre_close REAL,
            "change" REAL,
            pct_chg REAL,
            vol REAL,
            amount REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (trade_date, ts_code)
        )
    """,
    "stock_prediction": """
        CREATE TABLE IF NOT EXISTS stock_prediction (
            trade_date TEXT NOT NULL,
            ts_code TEXT NOT NULL,
            name TEXT,
            direction TEXT,
            confidence REAL,
            factor_scores TEXT,
            predicted_pct REAL,
            actual_pct REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (trade_date, ts_code, direction)
        )
    """,
    "index_daily": """
        CREATE TABLE IF NOT EXISTS index_daily (
            trade_date TEXT NOT NULL,
            ts_code TEXT NOT NULL,
            "open" REAL,
            high REAL,
            low REAL,
            "close" REAL,
            pre_close REAL,
            pct_chg REAL,
            vol REAL,
            amount REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (trade_date, ts_code)
        )
    """,
    "ths_hot": """
        CREATE TABLE IF NOT EXISTS ths_hot (
            trade_date TEXT NOT NULL,
            ts_code TEXT NOT NULL,
            ts_name TEXT,
            data_type TEXT DEFAULT '',
            current_price REAL DEFAULT 0,
            rank INTEGER,
            pct_change REAL,
            rank_reason TEXT DEFAULT '',
            rank_time TEXT DEFAULT '',
            concept TEXT,
            hot INTEGER,
            market TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (trade_date, ts_code, market)
        )
    """,
    "hsgt_top10": """
        CREATE TABLE IF NOT EXISTS hsgt_top10 (
            trade_date TEXT NOT NULL,
            ts_code TEXT NOT NULL,
            name TEXT,
            "close" REAL,
            "change" REAL,
            rank INTEGER,
            market_type TEXT,
            amount REAL,
            net_amount REAL,
            buy REAL,
            sell REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (trade_date, ts_code, market_type)
        )
    """,
    "stk_factor_pro": """
        CREATE TABLE IF NOT EXISTS stk_factor_pro (
            trade_date TEXT NOT NULL,
            ts_code TEXT NOT NULL,
            "close" REAL,
            macd_dif REAL,
            macd_dea REAL,
            macd REAL,
            kdj_k REAL,
            kdj_d REAL,
            kdj_j REAL,
            rsi_6 REAL,
            rsi_12 REAL,
            boll_upper REAL,
            boll_mid REAL,
            boll_lower REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (trade_date, ts_code)
        )
    """,
    "stk_auction": """
        CREATE TABLE IF NOT EXISTS stk_auction (
            trade_date TEXT NOT NULL,
            ts_code TEXT NOT NULL,
            name TEXT,
            "open" REAL,
            pre_close REAL,
            "change" REAL,
            pct_change REAL,
            vol REAL,
            amount REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (trade_date, ts_code)
        )
    """,
    "trade_cal": """
        CREATE TABLE IF NOT EXISTS trade_cal (
            cal_date TEXT NOT NULL PRIMARY KEY,
            is_open INTEGER NOT NULL DEFAULT 0
        )
    """,
    "anns_d": """
        CREATE TABLE IF NOT EXISTS anns_d (
            ann_date TEXT NOT NULL,
            ts_code TEXT NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            ann_type TEXT DEFAULT '',
            content TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (ann_date, ts_code, title)
        )
    """,
    "concept_detail": """
        CREATE TABLE IF NOT EXISTS concept_detail (
            id TEXT NOT NULL,
            concept_name TEXT,
            ts_code TEXT NOT NULL,
            name TEXT,
            in_date TEXT DEFAULT '',
            out_date TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (id, ts_code)
        )
    """,
    "ths_member": """
        CREATE TABLE IF NOT EXISTS ths_member (
            ts_code TEXT NOT NULL,
            code TEXT NOT NULL,
            name TEXT,
            weight REAL DEFAULT 0,
            in_date TEXT DEFAULT '',
            out_date TEXT DEFAULT '',
            is_new TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (ts_code, code)
        )
    """,
    "sync_log": """
        CREATE TABLE IF NOT EXISTS sync_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            api_name TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            record_count INTEGER,
            status TEXT,
            error_msg TEXT,
            sync_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(api_name, trade_date)
        )
    """,
}

INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_limit_list_d_date ON limit_list_d(trade_date)",
    "CREATE INDEX IF NOT EXISTS idx_limit_list_d_code ON limit_list_d(ts_code)",
    "CREATE INDEX IF NOT EXISTS idx_limit_step_date ON limit_step(trade_date)",
    "CREATE INDEX IF NOT EXISTS idx_limit_step_code_date ON limit_step(ts_code, trade_date)",
    "CREATE INDEX IF NOT EXISTS idx_limit_cpt_date ON limit_cpt_list(trade_date)",
    "CREATE INDEX IF NOT EXISTS idx_limit_ths_date ON limit_list_ths(trade_date)",
    "CREATE INDEX IF NOT EXISTS idx_kpl_date ON kpl_list(trade_date)",
    "CREATE INDEX IF NOT EXISTS idx_kpl_date_tag ON kpl_list(trade_date, tag)",
    "CREATE INDEX IF NOT EXISTS idx_top_list_date ON top_list(trade_date)",
    "CREATE INDEX IF NOT EXISTS idx_top_inst_date ON top_inst(trade_date)",
    "CREATE INDEX IF NOT EXISTS idx_moneyflow_date ON moneyflow_ths(trade_date)",
    "CREATE INDEX IF NOT EXISTS idx_moneyflow_code_date ON moneyflow_ths(ts_code, trade_date)",
    "CREATE INDEX IF NOT EXISTS idx_sync_log_api_date ON sync_log(api_name, trade_date)",
    "CREATE INDEX IF NOT EXISTS idx_moneyflow_detail_date ON moneyflow_detail(trade_date)",
    "CREATE INDEX IF NOT EXISTS idx_moneyflow_detail_code ON moneyflow_detail(ts_code)",
    "CREATE INDEX IF NOT EXISTS idx_daily_bar_date ON daily_bar(trade_date)",
    "CREATE INDEX IF NOT EXISTS idx_daily_bar_code_date ON daily_bar(ts_code, trade_date DESC)",
    "CREATE INDEX IF NOT EXISTS idx_prediction_date ON stock_prediction(trade_date)",
    "CREATE INDEX IF NOT EXISTS idx_index_daily_date ON index_daily(trade_date)",
    "CREATE INDEX IF NOT EXISTS idx_index_daily_code ON index_daily(ts_code)",
    "CREATE INDEX IF NOT EXISTS idx_ths_hot_date ON ths_hot(trade_date)",
    "CREATE INDEX IF NOT EXISTS idx_ths_hot_code ON ths_hot(ts_code)",
    "CREATE INDEX IF NOT EXISTS idx_hsgt_top10_date ON hsgt_top10(trade_date)",
    "CREATE INDEX IF NOT EXISTS idx_hsgt_top10_code_date ON hsgt_top10(ts_code, trade_date)",
    "CREATE INDEX IF NOT EXISTS idx_stk_factor_date ON stk_factor_pro(trade_date)",
    "CREATE INDEX IF NOT EXISTS idx_stk_factor_code_date ON stk_factor_pro(ts_code, trade_date DESC)",
    "CREATE INDEX IF NOT EXISTS idx_stk_auction_date ON stk_auction(trade_date)",
    "CREATE INDEX IF NOT EXISTS idx_trade_cal_open ON trade_cal(is_open, cal_date)",
    "CREATE INDEX IF NOT EXISTS idx_anns_d_date ON anns_d(ann_date)",
    "CREATE INDEX IF NOT EXISTS idx_anns_d_code ON anns_d(ts_code)",
    "CREATE INDEX IF NOT EXISTS idx_anns_d_code_date ON anns_d(ts_code, ann_date)",
    "CREATE INDEX IF NOT EXISTS idx_concept_detail_code ON concept_detail(ts_code)",
    "CREATE INDEX IF NOT EXISTS idx_concept_detail_name ON concept_detail(concept_name)",
    "CREATE INDEX IF NOT EXISTS idx_ths_member_code ON ths_member(code)",
    "CREATE INDEX IF NOT EXISTS idx_ths_member_concept ON ths_member(ts_code)",
]


def init_schema(conn) -> None:
    """Create all tables and indexes."""
    for ddl in TABLES.values():
        conn.execute(ddl)
    for idx in INDEXES:
        conn.execute(idx)
    conn.commit()
