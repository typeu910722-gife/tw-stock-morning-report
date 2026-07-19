from __future__ import annotations
import re
import numpy as np
import pandas as pd

def num(v):
    if v is None:
        return np.nan
    s = str(v).strip().replace(",", "").replace("+", "").replace("X", "")
    s = re.sub(r"[^\d.\-]", "", s)
    if s in {"", "-", ".", "-."}:
        return np.nan
    try:
        return float(s)
    except ValueError:
        return np.nan

def roc_date(v: str) -> pd.Timestamp:
    parts = re.split(r"[/.-]", str(v).strip())
    y, m, d = map(int, parts[:3])
    if y < 1911:
        y += 1911
    return pd.Timestamp(y, m, d)

def normalize_trade_date(v) -> str:
    s = re.sub(r"\D", "", str(v or ""))
    if len(s) == 7:
        return f"{int(s[:3]) + 1911}{s[3:]}"
    if len(s) == 8:
        return s
    raise ValueError(f"無法解析交易日：{v}")

def fmt(v, digits=2, comma=False):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return "N/A"
    if np.isnan(x):
        return "N/A"
    return f"{x:,.{digits}f}" if comma else f"{x:.{digits}f}"
