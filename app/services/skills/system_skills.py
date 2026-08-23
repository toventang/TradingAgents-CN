from typing import List, Dict, Any
from app.models.skill import SkillType, SkillIOContract

# 内置系统 Skill 代码与契约定义

SYSTEM_SKILLS_SPEC: List[Dict[str, Any]] = [
    {
        "skill_id": "sys_skill_market_regime",
        "name": "Market Regime Detector",
        "description": "分析市场收益率与波动率判断牛/熊/震荡格局",
        "skill_type": SkillType.MARKET,
        "contract": SkillIOContract(
            input_schema={"returns_20d": "float", "volatility_20d": "float"},
            output_schema={"regime": "str", "confidence": "float"}
        ),
        "code": """
def run(inputs):
    ret = inputs.get('returns_20d', 0.0)
    vol = inputs.get('volatility_20d', 0.0)

    if ret > 0.05 and vol < 0.25:
        regime = 'BULL_TREND'
        conf = 0.85
    elif ret < -0.05:
        regime = 'BEAR_TREND'
        conf = 0.80
    else:
        regime = 'OSCILLATING'
        conf = 0.70

    return {'regime': regime, 'confidence': conf}
"""
    },
    {
        "skill_id": "sys_skill_fundamental_quality",
        "name": "Fundamental Quality Assessor",
        "description": "评估公司 ROE、负债率与毛利率质量得分",
        "skill_type": SkillType.FUNDAMENTALS,
        "contract": SkillIOContract(
            input_schema={"roe": "float", "debt_ratio": "float", "gross_margin": "float"},
            output_schema={"quality_score": "float", "grade": "str"}
        ),
        "code": """
def run(inputs):
    roe = inputs.get('roe', 0.0)
    debt = inputs.get('debt_ratio', 0.5)
    margin = inputs.get('gross_margin', 0.2)

    score = (roe * 0.5) + ((1.0 - debt) * 0.3) + (margin * 0.2)
    score = round(score, 4)

    if score > 0.15:
        grade = 'A'
    elif score > 0.08:
        grade = 'B'
    else:
        grade = 'C'

    return {'quality_score': score, 'grade': grade}
"""
    },
    {
        "skill_id": "sys_skill_technical_breakout",
        "name": "Technical Breakout Detector",
        "description": "判断价格突破与均线金叉形态",
        "skill_type": SkillType.TECHNICAL,
        "contract": SkillIOContract(
            input_schema={"close": "float", "ma_20": "float", "ma_60": "float"},
            output_schema={"is_breakout": "bool", "signal": "str"}
        ),
        "code": """
def run(inputs):
    close = inputs.get('close', 0.0)
    ma20 = inputs.get('ma_20', 0.0)
    ma60 = inputs.get('ma_60', 0.0)

    is_breakout = (close > ma20) and (ma20 > ma60)
    signal = 'BUY_BREAKOUT' if is_breakout else 'NEUTRAL'

    return {'is_breakout': is_breakout, 'signal': signal}
"""
    },
    {
        "skill_id": "sys_skill_sentiment_tracker",
        "name": "Social Sentiment Tracker",
        "description": "聚合舆情与社交热度评分",
        "skill_type": SkillType.SENTIMENT,
        "contract": SkillIOContract(
            input_schema={"news_score": "float", "social_buzz": "float"},
            output_schema={"composite_sentiment": "float", "bullish": "bool"}
        ),
        "code": """
def run(inputs):
    news = inputs.get('news_score', 0.0)
    buzz = inputs.get('social_buzz', 0.0)

    composite = (news * 0.7) + (buzz * 0.3)
    composite = round(composite, 4)

    return {'composite_sentiment': composite, 'bullish': composite > 0.2}
"""
    },
    {
        "skill_id": "sys_skill_risk_var_monitor",
        "name": "Portfolio Risk VaR Monitor",
        "description": "计算组合 95% VaR 与最大持仓集中度",
        "skill_type": SkillType.RISK,
        "contract": SkillIOContract(
            input_schema={"weights": "list", "returns": "list"},
            output_schema={"var_95": "float", "is_safe": "bool"}
        ),
        "code": """
def run(inputs):
    returns = inputs.get('returns', [-0.01, 0.02, -0.02, 0.01, -0.03, 0.02])
    returns_arr = np.array(returns)
    var_95 = float(-np.percentile(returns_arr, 5)) if len(returns_arr) > 0 else 0.0

    return {'var_95': round(var_95, 4), 'is_safe': var_95 < 0.05}
"""
    },
    {
        "skill_id": "sys_skill_composite_scorer",
        "name": "Multi-Factor Composite Scorer",
        "description": "归一化合成多因子得分",
        "skill_type": SkillType.COMPOSITE,
        "contract": SkillIOContract(
            input_schema={"factor_scores": "dict"},
            output_schema={"final_score": "float"}
        ),
        "code": """
def run(inputs):
    scores = inputs.get('factor_scores', {})
    if not scores:
        return {'final_score': 0.0}

    total = sum(scores.values())
    avg = total / len(scores)
    return {'final_score': round(avg, 4)}
"""
    }
]


def get_all_system_skills() -> List[Dict[str, Any]]:
    return SYSTEM_SKILLS_SPEC
