from __future__ import annotations
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
import numpy as np
import pandas as pd
from .twse import Twse
from .indicators import add, trend, backtest, flags
from .external import yahoo_taiex, global_lines, news
from .report import write
from .utils import fmt, num

log=logging.getLogger(__name__)

def institution_map(df):
    out={}
    if df.empty: return out
    code_col=next((c for c in df.columns if "證券代號" in str(c)),None)
    if not code_col: return out
    foreign=next((c for c in df.columns if "外陸資買賣超" in str(c)),None)
    trust=next((c for c in df.columns if "投信買賣超" in str(c)),None)
    for _,r in df.iterrows():
        code=str(r[code_col]).strip()
        vals=[num(r[c]) for c in [foreign,trust] if c]
        net=np.nansum(vals) if vals else np.nan
        out[code]="買" if net>0 else "賣" if net<0 else "中性" if not np.isnan(net) else "N/A"
    return out

def punishment_codes(df):
    if df.empty: return set()
    text=df.astype(str).fillna("").agg(" ".join,axis=1)
    codes=set()
    for line in text:
        for token in line.split():
            if token.isdigit() and len(token)==4:
                codes.add(token)
    return codes

def market_analysis(client,base_date,notes):
    try:
        df,src=client.market_history(base_date)
    except Exception as e:
        notes.append(f"TWSE 大盤資料失敗，改用 Yahoo：{e}")
        df=yahoo_taiex(); src="Yahoo Finance ^TWII 備援"
    df=df.sort_values("date").drop_duplicates("date")
    base_ts=pd.Timestamp(datetime.strptime(base_date,"%Y%m%d").date())
    df=df[df["date"]<=base_ts]
    if len(df)<2:
        raise RuntimeError("大盤資料少於2筆")
    df["ma5"]=df["close"].rolling(5).mean()
    df["ma20"]=df["close"].rolling(20).mean()
    last,prev=df.iloc[-1],df.iloc[-2]
    change=last["close"]-prev["close"]
    pct=change/prev["close"]*100
    support=df["low"].tail(20).min()
    resistance=df["high"].tail(20).max()
    mtrend="偏多" if last["close"]>last["ma5"]>last["ma20"] else "偏空" if last["close"]<last["ma5"]<last["ma20"] else "盤整"
    summary=f"加權指數收 {last['close']:,.2f}，{change:+,.2f} 點（{pct:+.2f}%）。MA5 {last['ma5']:,.2f}，MA20 {last['ma20']:,.2f}。"
    return summary,support,resistance,mtrend,src,pct

def analyze_stock(client,code,name,base_date,inst,punished):
    hist=client.stock_history(code,base_date)
    x=add(hist)
    r=x.iloc[-1]
    tr=trend(r)
    stop=r["support20"] if tr!="偏空" else r["resistance20"]
    return {
        "code":code,"name":name,"close":float(r["close"]),
        "pct":float(r["pct"]) if pd.notna(r["pct"]) else 0.0,
        "vol_ratio":float(r["vol_ratio"]) if pd.notna(r["vol_ratio"]) else 0.0,
        "inst":inst.get(code,"N/A"),"trend":tr,
        "bias":"處置" if punished else "觀望",
        "stop":fmt(stop),"punished":punished,"history":hist,
        "ma5":fmt(r["ma5"]),"ma20":fmt(r["ma20"]),
        "k":fmt(r["k"]),"d":fmt(r["d"]),"macd":fmt(r["macd"],3),
        "rsi":fmt(r["rsi"]),"support":fmt(r["support20"]),
        "resistance":fmt(r["resistance20"]),"flags":flags(x)
    }

def choose(rows,backtests,market_pct):
    rates={b["signal"]:b["rate"] for b in backtests}
    longs=[r for r in rows if not r["punished"] and r["trend"]=="偏多"]
    shorts=[r for r in rows if not r["punished"] and r["trend"]=="偏空"]
    longs=sorted(longs,key=lambda r:(r["pct"],r["vol_ratio"]),reverse=True)[:3]
    shorts=sorted(shorts,key=lambda r:(r["pct"],-r["vol_ratio"]))[:3]
    picks=[]
    for r in longs:
        r["bias"]="多"
        picks.append({"code":r["code"],"name":r["name"],"side":"多",
        "reason":f"偏多排列，漲跌 {r['pct']:+.2f}%、量比 {r['vol_ratio']:.2f}；爆量長紅隔日續漲率 {rates.get('爆量長紅',0)}%。",
        "entry":f"{r['close']*.997:.2f}–{r['close']*1.003:.2f}","stop":r["stop"],
        "target":f"{r['close']*1.015:.2f}–{r['close']*1.025:.2f}"})
    for r in shorts:
        r["bias"]="空"
        picks.append({"code":r["code"],"name":r["name"],"side":"空",
        "reason":f"偏空排列，漲跌 {r['pct']:+.2f}%、量比 {r['vol_ratio']:.2f}；跌破月線隔日續跌率 {rates.get('跌破月線',0)}%。",
        "entry":f"{r['close']*.997:.2f}–{r['close']*1.003:.2f}",
        "stop":f"{r['close']*1.012:.2f}","target":f"{r['close']*.975:.2f}–{r['close']*.985:.2f}"})
    return picks

def run_pipeline(base:Path,cfg:dict)->Path:
    notes=[]
    client=Twse(cfg.get("request_timeout",25))
    base_date=client.latest_trade_date()
    print(f"[交易日] {base_date}")
    top=client.top_turnover(cfg.get("top_n",20))
    print(f"[清單] 已取得成交值前 {len(top)} 檔")

    try:
        inst_df=client.institutional(base_date)
        inst=institution_map(inst_df)
    except Exception as e:
        inst={}
        notes.append(f"法人個股資料失敗：{e}")

    now=datetime.now()
    try:
        punish_df=client.punishments((now-timedelta(days=31)).strftime("%Y%m%d"),now.strftime("%Y%m%d"))
        punished=punishment_codes(punish_df)
    except Exception as e:
        punished=set()
        notes.append(f"處置股資料失敗：{e}")

    rows=[]; pool={}
    max_workers=cfg.get("max_workers",6)
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures={}
        for i,r in top.iterrows():
            code,name=str(r["code"]),str(r["name"])
            futures[ex.submit(analyze_stock,client,code,name,base_date,inst,code in punished)]=(i+1,code,name)
        done=0
        for fut in as_completed(futures):
            idx,code,name=futures[fut]
            done+=1
            try:
                item=fut.result(); rows.append(item); pool[code]=item["history"]
                print(f"[{done:02d}/{len(top):02d}] {code} {name} OK")
            except Exception as e:
                notes.append(f"{code} {name} 資料不全：{e}")
                print(f"[{done:02d}/{len(top):02d}] {code} {name} 失敗")

    order={str(r["code"]):i for i,r in top.iterrows()}
    rows.sort(key=lambda r:order.get(r["code"],999))
    if len(rows)<20:
        notes.append(f"完整分析檔數 {len(rows)}，少於目標20檔。")

    backtests=backtest(pool)
    market_summary,market_support,market_resistance,market_trend,market_source,market_pct=market_analysis(client,base_date,notes)
    picks=choose(rows,backtests,market_pct)

    try:
        glines=global_lines() if cfg.get("enable_global_market",True) else []
    except Exception as e:
        glines=[]; notes.append(f"國際盤資料失敗：{e}")
    try:
        bull=news("台股 利多 半導體 AI 伺服器",cfg.get("news_hours",36),3) if cfg.get("enable_news",True) else []
        bear=news("台股 利空 關稅 匯率 地緣政治",cfg.get("news_hours",36),3) if cfg.get("enable_news",True) else []
    except Exception as e:
        bull=[]; bear=[]; notes.append(f"新聞資料失敗：{e}")

    long_codes=[p["code"] for p in picks if p["side"]=="多"]
    short_codes=[p["code"] for p in picks if p["side"]=="空"]
    tone="偏多" if market_pct>0.5 else "偏空" if market_pct<-0.5 else "震盪"
    one=f"大盤前一日 {tone}，多方觀察 {','.join(long_codes) or '無'}；空方觀察 {','.join(short_codes) or '無'}，開盤先看量價確認。"

    out_dir=base/"outputs"/base_date[:4]/base_date[4:6]
    out_dir.mkdir(parents=True,exist_ok=True)
    out=out_dir/f"台股日報_{base_date}.html"
    write(out,{
        "title":f"台股日報 {base_date}",
        "trade_date":f"{base_date[:4]}/{base_date[4:6]}/{base_date[6:]}",
        "generated":datetime.now().strftime("%Y/%m/%d %H:%M"),
        "one_liner":one,"global_lines":glines[:5] or ["國際盤資料暫缺"],
        "bull":bull,"bear":bear,"picks":picks,"rows":rows,
        "market_summary":market_summary,"market_support":fmt(market_support,2,True),
        "market_resistance":fmt(market_resistance,2,True),"market_trend":market_trend,
        "market_source":market_source,"backtests":backtests,"notes":notes or ["無重大缺漏。"]
    })
    return out
