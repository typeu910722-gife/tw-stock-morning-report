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
        """GET JSON with retries and a useful error when TWSE returns HTML/blank text."""
        last = None
        for i in range(retries + 1):
            try:
                r = self.s.get(url, params=params, timeout=self.timeout)
                r.raise_for_status()
                text = (r.text or "").strip()
                if not text:
                    raise RuntimeError(f"empty response (HTTP {r.status_code})")
                try:
                    data = r.json()
                except ValueError as e:
                    preview = text[:160].replace("\n", " ")
                    raise RuntimeError(
                        f"non-JSON response (HTTP {r.status_code}, "
                        f"content-type={r.headers.get('content-type', '')}, body={preview!r})"
                    ) from e
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

    def _turnover_frame(self, rows):
        df = pd.DataFrame(rows)
        if df.empty:
            raise ValueError("成交值資料為空")
        cols = {
            "code": next(c for c in ["Code", "證券代號"] if c in df.columns),
            "name": next(c for c in ["Name", "證券名稱"] if c in df.columns),
            "value": next(c for c in ["TradeValue", "成交金額"] if c in df.columns),
        }
        def optional(names):
            return next((c for c in names if c in df.columns), None)
        close_col = optional(["ClosingPrice", "收盤價"])
        change_col = optional(["Change", "漲跌價差"])
        volume_col = optional(["TradeVolume", "成交股數"])
        out = pd.DataFrame({
            "code": df[cols["code"]].astype(str).str.strip(),
            "name": df[cols["name"]].astype(str).str.strip(),
            "trade_value": df[cols["value"]].map(num),
            "close": df[close_col].map(num) if close_col else float("nan"),
            "change": df[change_col].map(num) if change_col else float("nan"),
            "volume": df[volume_col].map(num) if volume_col else float("nan"),
        })
        out = out[out["code"].str.fullmatch(r"\d{4}", na=False)]
        out = out[~out["code"].str.startswith("00")]
        return out.dropna(subset=["trade_value"]).sort_values("trade_value", ascending=False)

    def _top_turnover_from_mi_index(self, base_date):
        payload = self.get(
            f"{self.BASE}/rwd/zh/afterTrading/MI_INDEX",
            {"date": base_date, "type": "ALLBUT0999", "response": "json"},
            retries=3,
        )
        # New TWSE response stores multiple tables. Locate the stock table by fields.
        for table in payload.get("tables", []) if isinstance(payload, dict) else []:
            fields = table.get("fields") or []
            if "證券代號" in fields and "成交金額" in fields:
                return self._turnover_frame([
                    dict(zip(fields, row)) for row in (table.get("data") or [])
                ])
        # Compatibility with older response keys such as fields9/data9.
        if isinstance(payload, dict):
            for key, fields in payload.items():
                if not key.startswith("fields") or not isinstance(fields, list):
                    continue
                if "證券代號" in fields and "成交金額" in fields:
                    rows = payload.get(key.replace("fields", "data"), [])
                    return self._turnover_frame([dict(zip(fields, row)) for row in rows])
        raise ValueError("MI_INDEX 找不到個股成交行情表")

    def _fallback_liquid_stocks(self):
        # Last-resort universe. Histories are still fetched live, so the report can finish
        # even when the ranking endpoint blocks GitHub-hosted runners.
        stocks = [
            ("2330", "台積電"), ("2317", "鴻海"), ("2454", "聯發科"),
            ("2308", "台達電"), ("2382", "廣達"), ("3231", "緯創"),
            ("2881", "富邦金"), ("2882", "國泰金"), ("2891", "中信金"),
            ("2886", "兆豐金"), ("2303", "聯電"), ("3711", "日月光投控"),
            ("2412", "中華電"), ("2603", "長榮"), ("2609", "陽明"),
            ("2615", "萬海"), ("2002", "中鋼"), ("1301", "台塑"),
            ("1303", "南亞"), ("6505", "台塑化"), ("3037", "欣興"),
            ("2327", "國巨"), ("2379", "瑞昱"), ("2345", "智邦"),
        ]
        return pd.DataFrame([
            {"code": code, "name": name, "trade_value": 0.0,
             "close": float("nan"), "change": float("nan"), "volume": float("nan")}
            for code, name in stocks
        ])

    def top_turnover(self, n, base_date=None):
        errors = []
        try:
            rows = self.get(f"{self.OPEN}/exchangeReport/STOCK_DAY_ALL", retries=3)
            return self._turnover_frame(rows).head(n).reset_index(drop=True), "TWSE OpenAPI"
        except Exception as e:
            errors.append(f"OpenAPI: {e}")
        if base_date:
            try:
                return self._top_turnover_from_mi_index(base_date).head(n).reset_index(drop=True), "TWSE MI_INDEX 備援"
            except Exception as e:
                errors.append(f"MI_INDEX: {e}")
        fallback = self._fallback_liquid_stocks().head(n).reset_index(drop=True)
        return fallback, "固定高流動性清單（成交值排行來源失敗：" + " | ".join(errors) + "）"

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
        months = []
        cursor = base
        for _ in range(4):
            months.append(cursor.strftime("%Y%m%d"))
            cursor = cursor.replace(day=1) - timedelta(days=1)
        frames, sources = [], []
        for qd in months:
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

    def notices(self):
        """TWSE OpenAPI: 當日公布注意股票。欄位名稱可能調整，交由 pipeline 彈性解析。"""
        rows = self.get(f"{self.OPEN}/announcement/notice")
        return pd.DataFrame(rows if isinstance(rows, list) else [])

    def punishment_openapi(self):
        """TWSE OpenAPI 處置資訊備援。"""
        rows = self.get(f"{self.OPEN}/announcement/punish")
        return pd.DataFrame(rows if isinstance(rows, list) else [])
