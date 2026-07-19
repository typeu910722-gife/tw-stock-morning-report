from __future__ import annotations
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
import numpy as np
import pandas as pd
from .twse import Twse
from .indicators import add, trend, backtest, flags
from .external import yahoo_taiex, global_lines, news
from .report import write
from .charts import candlestick_svg
from .utils import fmt, num

log = logging.getLogger(__name__)


def institution_data(df):
    stock_map, total = {}, {"foreign": 0.0, "trust": 0.0, "dealer": 0.0, "total": 0.0}
    if df.empty:
        return stock_map, total
    code_col = next((c for c in df.columns if "證券代號" in str(c)), None)
    foreign = next((c for c in df.columns if "外陸資買賣超" in str(c)), None)
    trust = next((c for c in df.columns if "投信買賣超" in str(c)), None)
    dealer_cols = [c for c in df.columns if "自營商買賣超" in str(c)]
    if not code_col:
        return stock_map, total
    for _, r in df.iterrows():
        code = str(r[code_col]).strip()
        f = num(r[foreign]) if foreign else np.nan
        t = num(r[trust]) if trust else np.nan
        d = np.nansum([num(r[c]) for c in dealer_cols]) if dealer_cols else np.nan
        net = np.nansum([f, t, d])
        stock_map[code] = {
            "label": "買" if net > 0 else "賣" if net < 0 else "中性",
            "foreign": f, "trust": t, "dealer": d, "net": net,
        }
        total["foreign"] += 0 if np.isnan(f) else f
        total["trust"] += 0 if np.isnan(t) else t
        total["dealer"] += 0 if np.isnan(d) else d
    total["total"] = total["foreign"] + total["trust"] + total["dealer"]
    return stock_map, total


def format_lots(value):
    if value is None or np.isnan(value):
        return "N/A"
    return f"{value / 1000:+,.0f}張"


def format_billion(value):
    return f"{value / 100_000_000:+,.2f}億"


def _find_col(df, keys):
    for c in df.columns:
        text = str(c).replace(" ", "")
        if any(k in text for k in keys):
            return c
    return None


def _clean_reason(text, limit=180):
    text = " ".join(str(text or "").replace("\\n", " ").split())
    return text[:limit] + ("…" if len(text) > limit else "")


def _parse_period_dates(text):
    text = str(text or "")
    dates = re.findall(r"(\d{2,3})[./年](\d{1,2})[./月](\d{1,2})", text)
    out=[]
    for y,m,d in dates[:2]:
        try:
            y=int(y); y=y+1911 if y < 1911 else y
            out.append(datetime(y,int(m),int(d)).strftime("%Y/%m/%d"))
        except ValueError:
            pass
    return (out+["",""])[:2]


def _status_impact(status, measure=""):
    if status == "注意":
        return ["代表近期交易出現價格、成交量、周轉率等異常條件之一", "仍可交易，但短線震盪與追價風險通常較高", "是否可當沖仍依個股交易資格與券商控管為準"]
    text=str(measure or "")
    impacts=["處置期間可能採分盤撮合，成交速度與價格連續性會下降", "可能要求預收款券或提高交易控管，實際措施以公告為準"]
    if "分鐘" in text: impacts.append("撮合間隔依公告所列分鐘數執行")
    if "預收" in text or "款券" in text: impacts.append("下單前可能需要先備妥款項或股票")
    return impacts


def announcement_map(df, status, base_date=None):
    """將 TWSE 注意/處置公告轉成 code -> 詳細資訊。欄位改名時仍可盡量辨識。"""
    out = {}
    if df is None or df.empty:
        return out
    code_col = _find_col(df, ["證券代號", "Code", "股票代號"])
    name_col = _find_col(df, ["證券名稱", "Name", "股票名稱"])
    if code_col is None:
        return out
    reason_cols = [c for c in df.columns if any(k in str(c) for k in ["原因", "標準", "條件", "內容", "措施", "備註", "注意交易資訊"])]
    period_col = _find_col(df, ["處置起迄", "處置期間", "期間"])
    measure_col = _find_col(df, ["處置措施", "措施"])
    for _, r in df.iterrows():
        code = str(r.get(code_col, "")).strip()
        if not (code.isdigit() and len(code) == 4):
            continue
        chunks = []
        for c in reason_cols:
            v = str(r.get(c, "")).strip()
            if v and v.lower() != "nan" and v not in chunks:
                chunks.append(v)
        reason = _clean_reason("；".join(chunks)) or ("當日達證交所公布注意交易資訊標準" if status == "注意" else "達證交所處置有價證券條件")
        period = _clean_reason(r.get(period_col, ""), 90) if period_col else ""
        if status == "處置" and base_date and period:
            dates = re.findall(r"(\d{2,3})[./年](\d{1,2})[./月](\d{1,2})", period)
            if len(dates) >= 2:
                def roc_tuple_to_date(t):
                    y, m, d = map(int, t)
                    return datetime(y + 1911, m, d).date()
                try:
                    target = datetime.strptime(base_date, "%Y%m%d").date()
                    if not (roc_tuple_to_date(dates[0]) <= target <= roc_tuple_to_date(dates[1])):
                        continue
                except ValueError:
                    pass
        measure = _clean_reason(r.get(measure_col, ""), 220) if measure_col else ""
        start_date, end_date = _parse_period_dates(period)
        out[code] = {
            "status": status,
            "name": str(r.get(name_col, "")).strip() if name_col else "",
            "reason": reason,
            "period": period,
            "measure": measure,
            "start_date": start_date,
            "end_date": end_date,
            "impact": _status_impact(status, measure),
        }
    return out


def star_text(stars):
    stars = max(1, min(5, int(stars)))
    return "★" * stars + "☆" * (5 - stars)


def recommendation(row):
    if row.get("partial"):
        negatives = ["歷史資料不足，無法計算技術指標與 K 線"]
        if row.get("status") == "注意": negatives.append("已列注意股，異常波動風險提高")
        elif row.get("status") == "處置": negatives.append("處置期間可能有撮合或款券限制")
        return 1, star_text(1), "高", [], negatives
    positives, negatives = [], []
    score = 3
    if row["trend"] == "偏多": score += 1; positives.append("價格與均線結構偏多")
    elif row["trend"] == "偏空": score -= 1; negatives.append("價格與均線結構偏空")
    if row["inst_raw"] > 0: score += 1; positives.append("三大法人合計買超")
    elif row["inst_raw"] < 0: score -= 1; negatives.append("三大法人合計賣超")
    if row["vol_ratio"] >= 1.5: positives.append("成交量明顯放大")
    elif row["vol_ratio"] < 0.7: negatives.append("量能偏弱")
    if row["obv_up"]: positives.append("OBV 資金動能偏強")
    else: negatives.append("OBV 資金動能偏弱")
    if row["pct"] <= -9.5 or row["pct"] >= 9.5:
        score -= 1; negatives.append("接近漲跌停，隔日跳空與流動性風險較高")
    if row["status"] == "注意":
        score -= 1; negatives.append("已列注意股，異常波動風險提高")
    elif row["status"] == "處置":
        score = min(score, 2); negatives.append("處置期間可能分盤撮合或預收款券，不列優先標的")
    atr_pct = row["atr_pct"]
    if atr_pct >= 7: negatives.append("ATR 波動率很高")
    elif atr_pct >= 4: negatives.append("ATR 波動率偏高")
    else: positives.append("近期波動尚屬可控")
    stars = max(1, min(5, score))
    risk_points = (2 if row["status"] == "處置" else 1 if row["status"] == "注意" else 0) + (2 if atr_pct >= 7 else 1 if atr_pct >= 4 else 0) + (1 if abs(row["pct"]) >= 8 else 0)
    # 讓風險原因可直接讀懂，而非只顯示高、中、低。
    if row.get("vol_ratio", 0) >= 2.0:
        negatives.append(f"成交量約為近期均量 {row['vol_ratio']:.2f} 倍，盤中震盪可能放大")
    close=float(row.get("close",0) or 0); resistance=row.get("resistance_raw", np.nan); support=row.get("support_raw", np.nan)
    if close and pd.notna(resistance) and 0 <= (resistance-close)/close <= 0.03:
        negatives.append("距離技術壓力不到 3%，追價空間較窄")
    if close and pd.notna(support) and 0 <= (close-support)/close <= 0.02:
        negatives.append("接近支撐區，跌破後可能加速波動")
    risk = "高" if risk_points >= 3 else "中" if risk_points >= 1 else "低"
    return stars, star_text(stars), risk, positives[:4], list(dict.fromkeys(negatives))[:6]

def market_analysis(client, base_date, notes):
    try:
        df, src = client.market_history(base_date)
    except Exception as e:
        notes.append(f"TWSE 大盤資料失敗，改用 Yahoo：{e}")
        df, src = yahoo_taiex(), "Yahoo Finance ^TWII 備援"
    df = df.sort_values("date").drop_duplicates("date")
    base_ts = pd.Timestamp(datetime.strptime(base_date, "%Y%m%d").date())
    df = df[df["date"] <= base_ts]
    if len(df) < 2:
        raise RuntimeError("大盤資料少於2筆")
    df["ma5"] = df["close"].rolling(5).mean()
    df["ma20"] = df["close"].rolling(20).mean()
    prev_close = df["close"].shift(1)
    tr = pd.concat([(df["high"] - df["low"]), (df["high"] - prev_close).abs(), (df["low"] - prev_close).abs()], axis=1).max(axis=1)
    df["atr14"] = tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    last, prev = df.iloc[-1], df.iloc[-2]
    change = last["close"] - prev["close"]
    pct = change / prev["close"] * 100
    atr = last["atr14"] if pd.notna(last["atr14"]) else (last["high"] - last["low"])
    support = max(df["low"].tail(20).min(), last["close"] - atr)
    resistance = min(df["high"].tail(20).max(), last["close"] + atr)
    mtrend = "偏多" if last["close"] > last["ma5"] > last["ma20"] else "偏空" if last["close"] < last["ma5"] < last["ma20"] else "盤整"
    summary = f"加權指數收 {last['close']:,.2f}，{change:+,.2f} 點（{pct:+.2f}%）。MA5 {last['ma5']:,.2f}，MA20 {last['ma20']:,.2f}，ATR14 約 {atr:,.2f} 點。"
    return summary, support, resistance, mtrend, src, pct, df


def analyze_stock(client, code, name, base_date, inst, announcement):
    hist = client.stock_history(code, base_date)
    x = add(hist)
    r = x.iloc[-1]
    tr = trend(r)
    support, resistance = r["support"], r["resistance"]
    atr = r["atr14"] if pd.notna(r["atr14"]) else r["close"] * 0.02
    stop = support if tr != "偏空" else resistance
    inst_row = inst.get(code, {})
    return {
        "code": code, "name": name, "close": float(r["close"]),
        "pct": float(r["pct"]) if pd.notna(r["pct"]) else 0.0,
        "vol_ratio": float(r["vol_ratio"]) if pd.notna(r["vol_ratio"]) else 0.0,
        "inst": inst_row.get("label", "N/A"), "inst_net": format_lots(inst_row.get("net", np.nan)),
        "inst_raw": float(inst_row.get("net", 0) if pd.notna(inst_row.get("net", 0)) else 0),
        "trend": tr, "bias": "處置" if announcement.get("status") == "處置" else "觀望",
        "stop": fmt(stop), "punished": announcement.get("status") == "處置", "history": hist,
        "status": announcement.get("status", "正常"), "status_reason": announcement.get("reason", ""),
        "status_period": announcement.get("period", ""), "status_measure": announcement.get("measure", ""),
        "status_start": announcement.get("start_date", ""), "status_end": announcement.get("end_date", ""),
        "status_impact": announcement.get("impact", []),
        "ma5": fmt(r["ma5"]), "ma20": fmt(r["ma20"]), "ma60": fmt(r["ma60"]),
        "ema12": fmt(r["ema12"]), "ema26": fmt(r["ema26"]),
        "k": fmt(r["k"]), "d": fmt(r["d"]), "macd": fmt(r["macd"], 3),
        "rsi": fmt(r["rsi"]), "atr": fmt(r["atr14"]),
        "bb_upper": fmt(r["bb_upper"]), "bb_lower": fmt(r["bb_lower"]),
        "support": fmt(support), "resistance": fmt(resistance), "flags": flags(x),
        "atr_raw": float(atr), "support_raw": float(support) if pd.notna(support) else np.nan,
        "resistance_raw": float(resistance) if pd.notna(resistance) else np.nan,
        "obv_up": bool(pd.notna(r["obv_ma5"]) and r["obv"] >= r["obv_ma5"]),
        "atr_pct": float(atr / r["close"] * 100) if r["close"] else 0.0,
        "partial": False, "data_note": "",
    }


def fallback_stock_row(top_row, inst, announcement, error_text):
    """歷史 K 線抓不到時，保留當日成交榜資料，避免整檔消失。"""
    code, name = str(top_row["code"]), str(top_row["name"])
    close = float(top_row.get("close", np.nan))
    change = float(top_row.get("change", np.nan))
    pct = (change / (close - change) * 100) if pd.notna(close) and pd.notna(change) and (close - change) else 0.0
    inst_row = inst.get(code, {})
    status = announcement.get("status", "正常")
    return {
        "code": code, "name": name, "close": close if pd.notna(close) else "N/A",
        "pct": float(pct), "vol_ratio": 0.0,
        "inst": inst_row.get("label", "N/A"), "inst_net": format_lots(inst_row.get("net", np.nan)),
        "inst_raw": float(inst_row.get("net", 0) if pd.notna(inst_row.get("net", 0)) else 0),
        "trend": "資料不足", "bias": "處置" if status == "處置" else "觀望",
        "stop": "N/A", "punished": status == "處置", "history": pd.DataFrame(),
        "status": status, "status_reason": announcement.get("reason", ""),
        "status_period": announcement.get("period", ""), "status_measure": announcement.get("measure", ""),
        "status_start": announcement.get("start_date", ""), "status_end": announcement.get("end_date", ""),
        "status_impact": announcement.get("impact", []),
        "ma5": "N/A", "ma20": "N/A", "ma60": "N/A", "ema12": "N/A", "ema26": "N/A",
        "k": "N/A", "d": "N/A", "macd": "N/A", "rsi": "N/A", "atr": "N/A",
        "bb_upper": "N/A", "bb_lower": "N/A", "support": "N/A", "resistance": "N/A", "flags": [],
        "atr_raw": 0.0, "support_raw": np.nan, "resistance_raw": np.nan,
        "obv_up": False, "atr_pct": 99.0, "partial": True,
        "data_note": f"歷史資料取得失敗：{_clean_reason(error_text, 120)}",
    }


def trade_reason(r, side):
    bits = [f"{r['trend']}結構", f"漲跌 {r['pct']:+.2f}%", f"量比 {r['vol_ratio']:.2f}"]
    bits.append("OBV偏強" if r["obv_up"] else "OBV偏弱")
    if side == "多":
        trigger = "開盤站穩昨收且量能放大再留意，跌破支撐不追。"
    else:
        trigger = "反彈無法站回昨收且量能轉弱再留意，突破壓力撤退。"
    return "、".join(bits) + "。" + trigger


def choose(rows, backtests, market_pct):
    longs = [r for r in rows if not r["punished"] and r["trend"] == "偏多" and r["vol_ratio"] >= 1.0]
    shorts = [r for r in rows if not r["punished"] and r["trend"] == "偏空" and r["vol_ratio"] >= 0.8]
    longs = sorted(longs, key=lambda r: (r["pct"], r["vol_ratio"]), reverse=True)[:3]
    shorts = sorted(shorts, key=lambda r: (r["pct"], -r["vol_ratio"]))[:3]
    picks = []
    for r in longs:
        r["bias"] = "多"
        stop = r["support_raw"] if not np.isnan(r["support_raw"]) else r["close"] - r["atr_raw"]
        target1, target2 = r["close"] + r["atr_raw"] * 0.8, r["close"] + r["atr_raw"] * 1.3
        picks.append({"code": r["code"], "name": r["name"], "side": "多", "reason": trade_reason(r, "多"),
                      "entry": f"{r['close'] * .998:.2f}–{r['close'] * 1.003:.2f}", "stop": f"{stop:.2f}", "target": f"{target1:.2f}–{target2:.2f}"})
    for r in shorts:
        r["bias"] = "空"
        stop = r["resistance_raw"] if not np.isnan(r["resistance_raw"]) else r["close"] + r["atr_raw"]
        target1, target2 = r["close"] - r["atr_raw"] * 0.8, r["close"] - r["atr_raw"] * 1.3
        picks.append({"code": r["code"], "name": r["name"], "side": "空", "reason": trade_reason(r, "空"),
                      "entry": f"{r['close'] * .997:.2f}–{r['close'] * 1.002:.2f}", "stop": f"{stop:.2f}", "target": f"{target2:.2f}–{target1:.2f}"})
    return picks


def run_pipeline(base: Path, cfg: dict) -> Path:
    notes = []
    client = Twse(cfg.get("request_timeout", 25))
    base_date = client.latest_trade_date()
    print(f"[交易日] {base_date}")
    top, top_source = client.top_turnover(cfg.get("top_n", 20), base_date)
    print(f"[清單] 已取得 {len(top)} 檔（{top_source}）")
    if not top_source.startswith("TWSE OpenAPI"):
        notes.append(f"成交值清單改用：{top_source}")

    try:
        inst_df = client.institutional(base_date)
        inst, inst_total = institution_data(inst_df)
    except Exception as e:
        inst, inst_total = {}, {"foreign": 0, "trust": 0, "dealer": 0, "total": 0}
        notes.append(f"法人個股資料失敗：{e}")

    now = datetime.now()
    notice_map, punish_map = {}, {}
    try:
        notice_map = announcement_map(client.notices(), "注意", base_date)
    except Exception as e:
        notes.append(f"注意股資料失敗：{e}")
    try:
        punish_df = client.punishments((now - timedelta(days=45)).strftime("%Y%m%d"), now.strftime("%Y%m%d"))
        punish_map = announcement_map(punish_df, "處置", base_date)
        if not punish_map:
            punish_map = announcement_map(client.punishment_openapi(), "處置", base_date)
    except Exception as e:
        notes.append(f"處置股資料失敗：{e}")
    announcements = dict(notice_map)
    announcements.update(punish_map)  # 處置優先於注意

    rows, pool, failed = [], {}, []
    print("[步驟 5/7] 分析成交值前列股票")
    with ThreadPoolExecutor(max_workers=cfg.get("max_workers", 4)) as ex:
        futures = {ex.submit(analyze_stock, client, str(r["code"]), str(r["name"]), base_date, inst, announcements.get(str(r["code"]), {})): (i + 1, r.to_dict()) for i, r in top.iterrows()}
        done = 0
        for fut in as_completed(futures):
            _, top_row = futures[fut]
            code, name = str(top_row["code"]), str(top_row["name"])
            done += 1
            try:
                item = fut.result(); rows.append(item); pool[code] = item["history"]
                print(f"[{done:02d}/{len(top):02d}] {code} {name}  完成")
            except Exception as e:
                failed.append((top_row, str(e)))
                print(f"[{done:02d}/{len(top):02d}] {code} {name}  等待重試")

    # 並行請求偶爾會被 TWSE 限流。失敗項目改用新連線逐檔重試一次。
    if failed:
        print(f"[重試] 共 {len(failed)} 檔，改用單線逐檔補抓")
    retry_client = Twse(max(cfg.get("request_timeout", 25), 30))
    for top_row, first_error in failed:
        code, name = str(top_row["code"]), str(top_row["name"])
        try:
            item = analyze_stock(retry_client, code, name, base_date, inst, announcements.get(code, {}))
            rows.append(item); pool[code] = item["history"]
            print(f"       {code} {name}  重試成功")
        except Exception as second_error:
            item = fallback_stock_row(top_row, inst, announcements.get(code, {}), str(second_error))
            rows.append(item)
            notes.append(f"{code} {name} 僅保留當日資料，技術指標與 K 線略過：{second_error}")
            print(f"       {code} {name}  部分完成（K線略過）")

    order = {str(r["code"]): i for i, r in top.iterrows()}
    rows.sort(key=lambda r: order.get(r["code"], 999))
    for r in rows:
        stars, stars_text, risk, pros, cons = recommendation(r)
        r.update({"stars": stars, "stars_text": stars_text, "risk": risk,
                  "recommend_reasons": pros, "risk_reasons": cons,
                  "chart_svg": candlestick_svg(r.get("history"), f"{r['code']} {r['name']}", days=45, width=720, height=300, support=r.get("support_raw"), resistance=r.get("resistance_raw"))})
    if len(rows) < cfg.get("top_n", 20):
        notes.append(f"完整分析檔數 {len(rows)}，少於目標 {cfg.get('top_n',20)} 檔。")

    backtests = backtest(pool)
    market_summary, market_support, market_resistance, market_trend, market_source, market_pct, market_hist = market_analysis(client, base_date, notes)
    picks = choose(rows, backtests, market_pct)
    row_by_code = {r["code"]: r for r in rows}
    for p in picks:
        r = row_by_code[p["code"]]
        p.update({k: r[k] for k in ["stars", "stars_text", "risk", "status", "status_reason", "status_period", "status_measure", "status_start", "status_end", "status_impact", "recommend_reasons", "risk_reasons", "chart_svg"]})


    try:
        glines = global_lines() if cfg.get("enable_global_market", True) else []
    except Exception as e:
        glines = []; notes.append(f"國際盤資料失敗：{e}")
    try:
        bull = news("台股 利多 OR 半導體 OR AI OR 法說", cfg.get("news_hours", 48), 4) if cfg.get("enable_news", True) else []
        bear = news("台股 利空 OR 關稅 OR 匯率 OR 地緣政治", cfg.get("news_hours", 48), 4) if cfg.get("enable_news", True) else []
    except Exception as e:
        bull = []; bear = []; notes.append(f"新聞資料失敗：{e}")
    if not bull:
        bull = [{"title": "近期利多新聞未取得，請搭配券商即時新聞確認。", "link": ""}]
    if not bear:
        bear = [{"title": "近期利空新聞未取得，請搭配券商即時新聞確認。", "link": ""}]

    long_codes = [p["code"] for p in picks if p["side"] == "多"]
    short_codes = [p["code"] for p in picks if p["side"] == "空"]
    tone = "偏多" if market_pct > 0.5 else "偏空" if market_pct < -0.5 else "震盪"
    one = f"大盤前一日 {tone}，法人合計 {format_billion(inst_total['total'])}；多方觀察 {','.join(long_codes) or '無'}，空方觀察 {','.join(short_codes) or '無'}。"
    institution_summary = [
        f"外資 {format_billion(inst_total['foreign'])}",
        f"投信 {format_billion(inst_total['trust'])}",
        f"自營商 {format_billion(inst_total['dealer'])}",
        f"合計 {format_billion(inst_total['total'])}",
    ]

    # 資料驅動市場摘要，不呼叫付費 AI，也避免固定罐頭句。
    summary_parts=[]
    summary_parts.append(f"加權指數前一交易日{('重挫' if market_pct <= -3 else '收跌' if market_pct < -0.5 else '上漲' if market_pct > 0.5 else '震盪')} {abs(market_pct):.2f}%，技術結構為{market_trend}。")
    if inst_total['total'] < 0:
        sellers=[]
        if inst_total['foreign'] < 0: sellers.append('外資')
        if inst_total['trust'] < 0: sellers.append('投信')
        if inst_total['dealer'] < 0: sellers.append('自營商')
        summary_parts.append(f"{'、'.join(sellers) or '法人'}站在賣方，合計賣超 {abs(inst_total['total'])/100_000_000:.2f} 億元。")
    elif inst_total['total'] > 0:
        summary_parts.append(f"三大法人合計買超 {inst_total['total']/100_000_000:.2f} 億元，籌碼面提供部分支撐。")
    global_text=' '.join(glines)
    if 'VIX +' in global_text: summary_parts.append('國際風險情緒升溫，開盤需提防跳空與急速震盪。')
    if market_trend == '偏空': summary_parts.append('操作上宜先確認權值股止穩與量能回流，再考慮追價。')
    elif market_trend == '偏多': summary_parts.append('多方仍占優勢，但接近壓力區的標的不宜盲目追高。')
    watch=[]
    if long_codes: watch.append('觀察 '+','.join(long_codes)+' 多方動能能否延續')
    if short_codes: watch.append('留意 '+','.join(short_codes)+' 反彈是否仍受壓')
    market_brief=' '.join(summary_parts)
    market_watch=watch or ['先觀察大盤開盤量價是否一致，再決定交易方向']

    out_dir = base / "outputs" / base_date[:4] / base_date[4:6]
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"台股日報_{base_date}.html"
    write(out, {
        "title": f"台股日報 {base_date}", "version": "V5.1", "trade_date": f"{base_date[:4]}/{base_date[4:6]}/{base_date[6:]}",
        "generated": datetime.now().strftime("%Y/%m/%d %H:%M"), "one_liner": one,
        "global_lines": glines[:10] or ["國際盤資料暫缺"], "institution_summary": institution_summary,
        "bull": bull, "bear": bear, "picks": picks, "rows": rows,
        "market_summary": market_summary, "market_support": fmt(market_support, 2, True),
        "market_resistance": fmt(market_resistance, 2, True), "market_trend": market_trend,
        "market_source": market_source, "market_chart_svg": candlestick_svg(market_hist, "加權指數近 60 日", days=60, support=market_support, resistance=market_resistance),
        "market_brief": market_brief, "market_watch": market_watch,
        "backtests": backtests, "notes": notes or ["無重大缺漏。"]
    })
    return out
