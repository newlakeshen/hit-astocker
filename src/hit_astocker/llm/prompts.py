"""Prompt templates for LLM calls."""

EVENT_CLASSIFY_PROMPT = """\
你是A股市场事件分类专家。请对以下涨停股票的涨停原因进行分类。

可选事件类型: POLICY/EARNINGS/CONCEPT/RESTRUCTURE/TECHNICAL/CAPITAL/INDUSTRY/NEWS
同时判断:
1. event_type: 从上述类型中选择最匹配的一个
2. policy_level: 国家级S/部委级A/行业级B/地方级C/无null
3. amount_wan: 金额(万元)，无则null
4. confidence: 你的判断置信度 0-1

输入:
{json_input}

请严格返回JSON数组，不要输出其他内容:
[{{"code":"...","event_type":"...","policy_level":null,"amount_wan":null,"confidence":0.85}}]"""


DAILY_NARRATIVE_PROMPT = """\
你是A股打板交易分析师。请根据以下当日市场数据，生成一段200字以内的市场综述。

要求包含：
1. 市场格局判断（情绪冷热、多空态势）
2. 主线题材解读（哪些板块是主线、为什么）
3. 操作建议（适合什么策略）
4. 风险提示（需要注意什么）

市场数据:
{market_data}

请直接输出综述文本，不要使用markdown格式。"""


SIGNAL_REASON_PROMPT = """\
你是A股打板交易分析师。请为以下交易信号生成简洁的交易论据（每个50字以内）。

要求：
- 结合因子数据说明为什么值得关注
- 点明核心催化和风险点
- 语言简练有力

信号数据:
{signals_data}

请严格返回JSON数组:
[{{"ts_code":"...","reason":"..."}}]"""


THEME_CLUSTER_PROMPT = """\
你是A股市场题材分析专家。请将以下当日涨停相关题材进行语义聚类，合并相关题材为主线。

当日题材列表:
{themes}

请将语义相关的题材合并为主线，输出JSON数组:
[{{"main_theme":"主线名称","sub_themes":["子题材1","子题材2"],"narrative":"一句话解读这条主线"}}]"""


BACKTEST_NARRATIVE_PROMPT = """\
你是量化策略分析师。请分析以下打板策略回测结果，给出绩效解读和改进建议。

要求包含：
1. 整体绩效评价（胜率、盈亏比是否合理）
2. 盈亏原因分析（哪类信号表现好/差）
3. 周期适应性（什么市场环境适合这个策略）
4. 具体改进建议（参数调优/策略优化方向）

回测数据:
{backtest_data}

请直接输出分析文本。"""
