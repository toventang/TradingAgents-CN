import pandas as pd
import numpy as np

def generate_20_stock_120_day_fixture():
    symbols = [f"{600000 + i:06d}.SH" for i in range(20)]
    dates = pd.date_range("2026-01-01", periods=120, freq="B").strftime("%Y-%m-%d").tolist()

    price_rows = []
    factor_rows = []

    np.random.seed(42)

    for sym_idx, sym in enumerate(symbols):
        base_p = 10.0 + sym_idx
        p = base_p
        for d_idx, d in enumerate(dates):
            change = np.random.normal(0.001, 0.02)
            p = max(1.0, p * (1.0 + change))

            price_rows.append({
                "date": d,
                "symbol": sym,
                "open": round(p * 0.99, 2),
                "high": round(p * 1.02, 2),
                "low": round(p * 0.98, 2),
                "close": round(p, 2),
                "volume": 100000 + (sym_idx * 5000),
                "turnover": round(p * 100000, 2)
            })

            factor_rows.append({
                "date": d,
                "symbol": sym,
                "ret_1d": round(change, 4),
                "ret_5d": round(change * 2, 4),
                "ret_20d": round(change * 5, 4),
                "ret_60d": round(change * 10, 4),
                "pe_ratio": round(15.0 + sym_idx, 2),
                "pb_ratio": round(1.5 + (sym_idx * 0.1), 2),
                "roe": round(0.12 + (sym_idx * 0.005), 4)
            })

    prices_df = pd.DataFrame(price_rows).set_index(["date", "symbol"])
    factors_df = pd.DataFrame(factor_rows).set_index(["date", "symbol"])
    bm_prices = {d: round(1000.0 + (idx * 2.0), 2) for idx, d in enumerate(dates)}

    return symbols, dates, prices_df, factors_df, bm_prices
