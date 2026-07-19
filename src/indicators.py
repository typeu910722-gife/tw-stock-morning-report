from __future__ import annotations
import numpy as np
import pandas as pd


def add(df: pd.DataFrame) -> pd.DataFrame:
    x = df.copy().sort_values("date").reset_index(drop=True)
    c, h, l, v = x["close"], x["high"], x["low"], x["volume"]

    x["pct"] = c.pct_change() * 100
    x["ret5"] = c.pct_change(5) * 100
    x["ma5"] = c.rolling(5).mean()
    x["ma20"] = c.rolling(20).mean()
    x["ma60"] = c.rolling(60).mean()
    x["ema12"] = c.ewm(span=12, adjust=False).mean()
    x["ema26"] = c.ewm(span=26, adjust=False).mean()
    x["vol_ratio"] = v / v.shift(1).rolling(5).mean()

    # KD
    lo9, hi9 = l.rolling(9).min(), h.rolling(9).max()
    rsv = (c - lo9) / (hi9 - lo9).replace(0, np.nan) * 100
    x["k"] = rsv.ewm(alpha=1 / 3, adjust=False).mean()
    x["d"] = x["k"].ewm(alpha=1 / 3, adjust=False).mean()

    # MACD
    x["macd"] = x["ema12"] - x["ema26"]
    x["signal"] = x["macd"].ewm(span=9, adjust=False).mean()
    x["hist"] = x["macd"] - x["signal"]

    # RSI
    delta = c.diff()
    gain, loss = delta.clip(lower=0), -delta.clip(upper=0)
    rs = gain.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean() / loss.ewm(
        alpha=1 / 14, adjust=False, min_periods=14
    ).mean().replace(0, np.nan)
    x["rsi"] = 100 - 100 / (1 + rs)

    # ATR
    prev_close = c.shift(1)
    tr = pd.concat([(h - l), (h - prev_close).abs(), (l - prev_close).abs()], axis=1).max(axis=1)
    x["atr14"] = tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()

    # Bollinger Bands
    std20 = c.rolling(20).std(ddof=0)
    x["bb_mid"] = x["ma20"]
    x["bb_upper"] = x["ma20"] + 2 * std20
    x["bb_lower"] = x["ma20"] - 2 * std20

    # OBV
    direction = np.sign(c.diff()).fillna(0)
    x["obv"] = (direction * v.fillna(0)).cumsum()
    x["obv_ma5"] = x["obv"].rolling(5).mean()

    # 支撐壓力：前 20 日高低、MA20 與布林帶的組合
    x["low20"] = l.rolling(20).min()
    x["high20"] = h.rolling(20).max()
    support_candidates = pd.concat([x["low20"], x["ma20"], x["bb_lower"]], axis=1)
    resistance_candidates = pd.concat([x["high20"], x["ma20"], x["bb_upper"]], axis=1)
    x["support"] = support_candidates.where(support_candidates.le(c, axis=0)).max(axis=1)
    x["resistance"] = resistance_candidates.where(resistance_candidates.ge(c, axis=0)).min(axis=1)
    x["support"] = x["support"].fillna(x["low20"])
    x["resistance"] = x["resistance"].fillna(x["high20"])

    x["long_red"] = (x["close"] > x["open"]) & (x["pct"] >= 1.5)
    return x


def trend(r) -> str:
    if pd.isna(r.get("ma5")) or pd.isna(r.get("ma20")):
        return "盤整"
    if r["close"] > r["ma5"] > r["ma20"] and r.get("hist", 0) >= 0:
        return "偏多"
    if r["close"] < r["ma5"] < r["ma20"] and r.get("hist", 0) <= 0:
        return "偏空"
    return "盤整"


def flags(x):
    if len(x) < 2:
        return {}
    p, c = x.iloc[-2], x.iloc[-1]
    return {
        "KD低檔金叉": p["k"] <= p["d"] and c["k"] > c["d"] and c["k"] < 30,
        "KD高檔死叉": p["k"] >= p["d"] and c["k"] < c["d"] and c["k"] > 70,
        "爆量長紅": c["vol_ratio"] >= 1.5 and bool(c["long_red"]),
        "跌破月線": p["close"] >= p["ma20"] and c["close"] < c["ma20"],
    }


def backtest(pool):
    out = {k: [0, 0] for k in ["KD低檔金叉", "KD高檔死叉", "爆量長紅", "跌破月線"]}
    for raw in pool.values():
        x = add(raw)
        for i in range(1, len(x) - 1):
            f = flags(x.iloc[: i + 1])
            cur, nxt = x.iloc[i], x.iloc[i + 1]
            for name, hit in f.items():
                if not hit:
                    continue
                out[name][0] += 1
                up = name in ["KD低檔金叉", "爆量長紅"]
                ok = nxt["close"] > cur["close"] if up else nxt["close"] < cur["close"]
                out[name][1] += int(ok)
    rows = []
    labels = {"KD低檔金叉": "隔日上漲", "KD高檔死叉": "隔日下跌", "爆量長紅": "隔日續漲", "跌破月線": "隔日續跌"}
    for k, (n, w) in out.items():
        rows.append({"signal": k, "samples": n, "wins": w, "rate": round(w / n * 100) if n else 0, "label": labels[k], "small": n < 10})
    return rows
