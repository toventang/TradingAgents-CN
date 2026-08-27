#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
统一数据框接口
提供统一的数据获取接口，支持多个数据源的自动降级
"""

from typing import Optional
import pandas as pd
from tradingagents.utils.logging_manager import get_logger

logger = get_logger('agents')


def get_tushare_adapter():
    """获取 Tushare 适配器"""
    from tradingagents.dataflows.providers.china import TushareProvider
    return TushareProvider()


def get_akshare_provider():
    """获取 AKShare 提供器"""
    from tradingagents.dataflows.providers.china import AKShareProvider
    return AKShareProvider()


def get_baostock_provider():
    """获取 BaoStock 提供器"""
    from tradingagents.dataflows.providers.china import BaostockProvider
    return BaostockProvider()


def get_data_source_manager():
    """获取数据源管理器"""
    from tradingagents.dataflows.data_source_manager import DataSourceManager
    return DataSourceManager()


def get_china_daily_df_unified(
    stock_code: str,
    start_date: str,
    end_date: str,
    auto_fallback: bool = True
) -> pd.DataFrame:
    """
    获取中国股票日线数据，支持多源自动降级
    
    参数:
        stock_code: 股票代码 (如 '000001')
        start_date: 开始日期 (格式: 'YYYY-MM-DD')
        end_date: 结束日期 (格式: 'YYYY-MM-DD')
        auto_fallback: 是否自动降级到备用数据源
        
    返回:
        pd.DataFrame: 标准化的日线数据框，包含列: 
                     date, open, high, low, close, volume, amount
    """
    df = pd.DataFrame()
    
    try:
        # 获取数据源管理器
        manager = get_data_source_manager()
        
        # 根据当前源获取数据
        source_value = manager.current_source.value if hasattr(manager.current_source, 'value') else str(manager.current_source)
        
        if source_value == 'tushare':
            try:
                provider = get_tushare_adapter()
                result = provider.get_stock_data(stock_code, start_date, end_date)
                if isinstance(result, pd.DataFrame) and not result.empty:
                    df = result
            except Exception as e:
                logger.warning(f"Tushare 获取失败: {e}")
        
        # 如果主源失败，尝试备用源
        if df.empty and auto_fallback:
            for fallback_source in manager.available_sources:
                try:
                    if fallback_source == 'akshare':
                        provider = get_akshare_provider()
                        result = provider.get_stock_data(stock_code, start_date, end_date)
                        if isinstance(result, pd.DataFrame) and not result.empty:
                            df = result
                            break
                    elif fallback_source == 'baostock':
                        provider = get_baostock_provider()
                        result = provider.get_stock_data(stock_code, start_date, end_date)
                        if isinstance(result, pd.DataFrame) and not result.empty:
                            df = result
                            break
                except Exception as e:
                    logger.warning(f"{fallback_source} 获取失败: {e}")
                    continue
    
    except Exception as e:
        logger.error(f"获取数据异常: {e}")
        return pd.DataFrame()
    
    # 标准化列名
    if not df.empty:
        df = _normalize_dataframe(df)
    
    return df


def _normalize_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """
    标准化数据框列名和数据类型
    
    参数:
        df: 原始数据框
        
    返回:
        pd.DataFrame: 标准化后的数据框
    """
    # 列名映射：将各源的列名统一转换为小写
    column_mapping = {
        'Date': 'date',
        'date': 'date',
        'trade_date': 'date',
        'Open': 'open',
        'open': 'open',
        'High': 'high',
        'high': 'high',
        'Low': 'low',
        'low': 'low',
        'Close': 'close',
        'close': 'close',
        'Volume': 'volume',
        'volume': 'volume',
        'Amount': 'amount',
        'amount': 'amount',
    }
    
    # 重命名列
    df = df.rename(columns=column_mapping)
    
    # 确保必要的列存在
    required_columns = ['date', 'open', 'high', 'low', 'close', 'volume', 'amount']
    for col in required_columns:
        if col not in df.columns:
            df[col] = 0
    
    # 保留必要的列
    df = df[required_columns]
    
    # 转换数据类型
    for col in ['open', 'high', 'low', 'close']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    
    for col in ['volume', 'amount']:
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype(int)
    
    return df
