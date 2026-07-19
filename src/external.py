from __future__ import annotations
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
import feedparser
import pandas as pd
import yfinance as yf

def yahoo_taiex():
    d=yf.download("^TWII",period="3mo",interval="1d",progress=False,auto_adjust=False,threads=False)
    if d.empty:
        raise ValueError("Yahoo ^TWII 無資料")
    if isinstance(d.columns,pd.MultiIndex):
        d.columns=d.columns.get_level_values(0)
    d=d.reset_index().rename(columns={"Date":"date","Open":"open","High":"high","Low":"low","Close":"close"})
    return d[["date","open","high","low","close"]].dropna()

def global_lines():
    syms={"^DJI":"道瓊","^GSPC":"標普500","^IXIC":"那斯達克","^SOX":"費半","NVDA":"NVDA","AMD":"AMD","MU":"Micron","TSM":"TSM"}
    d=yf.download(list(syms),period="5d",interval="1d",progress=False,auto_adjust=False,threads=False)
    close=d["Close"]
    lines=[]
    for s,name in syms.items():
        try:
            x=close[s].dropna()
            if len(x)>=2:
                pct=(x.iloc[-1]/x.iloc[-2]-1)*100
                lines.append(f"{name} {pct:+.2f}%")
        except Exception:
            pass
    return lines

def news(query,hours=36,limit=3):
    url=f"https://news.google.com/rss/search?q={quote(query)}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
    feed=feedparser.parse(url)
    cutoff=datetime.now(timezone.utc)-timedelta(hours=hours)
    out=[]
    for e in feed.entries:
        p=getattr(e,"published_parsed",None)
        dt=datetime(*p[:6],tzinfo=timezone.utc) if p else None
        if dt and dt<cutoff: continue
        out.append({"title":getattr(e,"title",""),"link":getattr(e,"link","")})
        if len(out)>=limit: break
    return out
