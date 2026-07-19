from __future__ import annotations
import time
from datetime import datetime, timedelta
import pandas as pd
import requests
from .utils import num, roc_date, normalize_trade_date

class Twse:
    BASE = "https://www.twse.com.tw"
    OPEN = "https://openapi.twse.com.tw/v1"

    def __init__(self, timeout=25):
        self.timeout = timeout
        self.s = requests.Session()
        self.s.headers.update({
            "User-Agent": "Mozilla/5.0 Chrome/142 Safari/537.36",
            "Accept": "application/json,text/plain,*/*",
            "Referer": "https://www.twse.com.tw/",
        })

    def get(self, url, params=None, retries=2):
        last = None
        for i in range(retries + 1):
            try:
                r = self.s.get(url, params=params, timeout=self.timeout)
                r.raise_for_status()
                data = r.json()
                if isinstance(data, dict):
                    stat = str(data.get("stat", "")).upper()
                    if stat and stat != "OK":
                        raise RuntimeError(f"stat={data.get('stat')}")
                return data
            except Exception as e:
                last = e
                if i < retries:
                    time.sleep(1.5 * (i + 1))
        raise RuntimeError(f"{url}: {last}")

    def latest_trade_date(self):
        d = self.get(f"{self.BASE}/rwd/zh/afterTrading/MI_INDEX20", {"response":"json"})
        return normalize_trade_date(d.get("date"))

    def top_turnover(self, n):
        rows = self.get(f"{self.OPEN}/exchangeReport/STOCK_DAY_ALL")
        df = pd.DataFrame(rows)
        cols = {
            "code": next(c for c in ["Code","證券代號"] if c in df.columns),
            "name": next(c for c in ["Name","證券名稱"] if c in df.columns),
            "value": next(c for c in ["TradeValue","成交金額"] if c in df.columns),
        }
        out = pd.DataFrame({
            "code": df[cols["code"]].astype(str).str.strip(),
            "name": df[cols["name"]].astype(str).str.strip(),
            "trade_value": df[cols["value"]].map(num),
        })
        out = out[out["code"].str.fullmatch(r"\d{4}", na=False)]
        out = out[~out["code"].str.startswith("00")]
        return out.sort_values("trade_value", ascending=False).head(n).reset_index(drop=True)

    def stock_month(self, code, qd):
        p = self.get(f"{self.BASE}/rwd/zh/afterTrading/STOCK_DAY",
                     {"date":qd,"stockNo":code,"response":"json"})
        rows, fields = p.get("data") or [], p.get("fields") or []
        if len(rows) <= 1:
            raise ValueError(f"{code} {qd} 資料不足")
        df = pd.DataFrame(rows, columns=fields).rename(columns={
            "日期":"date","成交股數":"volume","成交金額":"turnover",
            "開盤價":"open","最高價":"high","最低價":"low",
            "收盤價":"close","漲跌價差":"change","成交筆數":"trades"
        })
        for c in ["date","volume","open","high","low","close"]:
            if c not in df.columns:
                raise ValueError(f"{code} 缺少欄位 {c}")
        df["date"] = df["date"].map(roc_date)
        for c in ["volume","turnover","open","high","low","close","change","trades"]:
            if c in df:
                df[c] = df[c].map(num)
        return df

    def stock_history(self, code, base_date):
        base = datetime.strptime(base_date, "%Y%m%d").date()
        m1 = base.replace(day=1) - timedelta(days=1)
        m2 = m1.replace(day=1) - timedelta(days=1)
        parts, errs = [], []
        for qd in [base.strftime("%Y%m%d"), m1.strftime("%Y%m%d"), m2.strftime("%Y%m%d")]:
            try:
                parts.append(self.stock_month(code, qd))
            except Exception as e:
                errs.append(str(e))
        if not parts:
            raise RuntimeError("; ".join(errs))
        return pd.concat(parts).drop_duplicates("date").sort_values("date").reset_index(drop=True)

    def market_payload_to_df(self, p):
        rows, fields = p.get("data") or [], p.get("fields") or []
        if not rows:
            raise ValueError("無資料")
        df = pd.DataFrame(rows, columns=fields).rename(columns={
            "日期":"date","開盤指數":"open","最高指數":"high",
            "最低指數":"low","收盤指數":"close"
        })
        for c in ["date","open","high","low","close"]:
            if c not in df.columns:
                raise ValueError(f"缺少 {c}，收到 {list(df.columns)}")
        df["date"] = df["date"].map(roc_date)
        for c in ["open","high","low","close"]:
            df[c] = df[c].map(num)
        return df.dropna(subset=["close"])

    def market_month(self, qd):
        candidates = [
            (f"{self.BASE}/rwd/zh/TAIEX/MI_5MINS_HIST","TWSE新版"),
            (f"{self.BASE}/indicesReport/MI_5MINS_HIST","TWSE相容舊版"),
        ]
        errs = []
        for url, source in candidates:
            try:
                return self.market_payload_to_df(
                    self.get(url, {"date":qd,"response":"json"}, retries=1)
                ), source
            except Exception as e:
                errs.append(f"{source}:{e}")
        raise RuntimeError(" | ".join(errs))

    def market_history(self, base_date):
        base = datetime.strptime(base_date, "%Y%m%d").date()
        prev = base.replace(day=1) - timedelta(days=1)
        frames, sources = [], []
        for qd in [base.strftime("%Y%m%d"), prev.strftime("%Y%m%d")]:
            df, src = self.market_month(qd)
            frames.append(df); sources.append(src)
        out = pd.concat(frames).drop_duplicates("date").sort_values("date").reset_index(drop=True)
        return out, "+".join(sorted(set(sources)))

    def institutional(self, base_date):
        p = self.get(f"{self.BASE}/rwd/zh/fund/T86",
                     {"date":base_date,"selectType":"ALLBUT0999","response":"json"})
        return pd.DataFrame(p.get("data") or [], columns=p.get("fields") or [])

    def punishments(self, start_date, end_date):
        p = self.get(f"{self.BASE}/rwd/zh/announcement/punish",
                     {"startDate":start_date,"endDate":end_date,"response":"json"})
        return pd.DataFrame(p.get("data") or [], columns=p.get("fields") or [])
