from __future__ import annotations
import html
import numpy as np
import pandas as pd


def _safe_num(v):
    try:
        v=float(v)
        return v if np.isfinite(v) else None
    except Exception:
        return None


def candlestick_svg(raw: pd.DataFrame, title: str = "", days: int = 60, width: int = 920, height: int = 360,
                    support=None, resistance=None) -> str:
    if raw is None or raw.empty:
        return '<div class="empty">K 線資料不足</div>'
    x = raw.copy().sort_values("date").tail(days).reset_index(drop=True)
    need = {"open", "high", "low", "close"}
    if not need.issubset(x.columns) or len(x) < 2:
        return '<div class="empty">K 線資料不足</div>'
    for c in need | {"volume"}:
        if c in x.columns:
            x[c] = pd.to_numeric(x[c], errors="coerce")
    x = x.dropna(subset=list(need))
    if len(x) < 2:
        return '<div class="empty">K 線資料不足</div>'

    x["ma5"] = x["close"].rolling(5).mean()
    x["ma20"] = x["close"].rolling(20).mean()
    std20 = x["close"].rolling(20).std(ddof=0)
    x["bb_upper"] = x["ma20"] + 2 * std20
    x["bb_lower"] = x["ma20"] - 2 * std20

    top, bottom, left, right = 34, 82, 52, 18
    pw, ph = width-left-right, height-top-bottom
    candidates = [x["high"].max(), x["low"].min(), x["bb_upper"].max(), x["bb_lower"].min()]
    for v in (support, resistance):
        n=_safe_num(v)
        if n is not None: candidates.append(n)
    hi=max(float(v) for v in candidates if pd.notna(v)); lo=min(float(v) for v in candidates if pd.notna(v))
    pad=max((hi-lo)*0.08, abs(hi)*0.005, 0.01); hi,lo=hi+pad,lo-pad
    span=max(hi-lo,0.0001)
    def yy(v): return top + (hi-float(v))/span*ph
    n=len(x); step=pw/max(n,1); body=max(2.0,min(8.0,step*0.55))
    esc=html.escape(title)
    parts=[f'<svg class="kchart" viewBox="0 0 {width} {height}" role="img" aria-label="{esc} K線圖">',
           f'<text x="{left}" y="18" font-size="13" font-weight="700">{esc}</text>']
    for i in range(5):
        y=top+ph*i/4; val=hi-(hi-lo)*i/4
        parts.append(f'<line x1="{left}" y1="{y:.1f}" x2="{width-right}" y2="{y:.1f}" stroke="#e5e7eb"/>')
        parts.append(f'<text x="2" y="{y+4:.1f}" font-size="10" fill="#6b7280">{val:.1f}</text>')

    # Bollinger band first, behind candles.
    upper=[]; lower=[]
    for i,v in enumerate(x["bb_upper"]):
        if pd.notna(v): upper.append(f'{left+(i+.5)*step:.2f},{yy(v):.2f}')
    for i,v in reversed(list(enumerate(x["bb_lower"]))):
        if pd.notna(v): lower.append(f'{left+(i+.5)*step:.2f},{yy(v):.2f}')
    if len(upper)>1 and len(lower)>1:
        parts.append(f'<polygon points="{" ".join(upper+lower)}" fill="#94a3b8" opacity=".10"/>')
        parts.append(f'<polyline points="{" ".join(upper)}" fill="none" stroke="#94a3b8" stroke-width="1" stroke-dasharray="4 3"/>')
        parts.append(f'<polyline points="{" ".join(reversed(lower))}" fill="none" stroke="#94a3b8" stroke-width="1" stroke-dasharray="4 3"/>')

    for label,v,color in [("支撐",support,"#16a34a"),("壓力",resistance,"#dc2626")]:
        n=_safe_num(v)
        if n is not None and lo <= n <= hi:
            y=yy(n)
            parts.append(f'<line x1="{left}" y1="{y:.2f}" x2="{width-right}" y2="{y:.2f}" stroke="{color}" stroke-width="1.1" stroke-dasharray="6 4"/>')
            parts.append(f'<text x="{width-right-78}" y="{y-3:.2f}" font-size="10" fill="{color}">{label} {n:.2f}</text>')

    for i,r in x.iterrows():
        cx=left+(i+.5)*step; yo,yc,yh,yl=yy(r.open),yy(r.close),yy(r.high),yy(r.low)
        col="#d62828" if r.close>=r.open else "#14804a"
        parts.append(f'<line x1="{cx:.2f}" y1="{yh:.2f}" x2="{cx:.2f}" y2="{yl:.2f}" stroke="{col}" stroke-width="1"/>')
        y=min(yo,yc); h=max(abs(yc-yo),1.3)
        parts.append(f'<rect x="{cx-body/2:.2f}" y="{y:.2f}" width="{body:.2f}" height="{h:.2f}" fill="{col}" rx=".5"><title>開 {r.open:.2f} 高 {r.high:.2f} 低 {r.low:.2f} 收 {r.close:.2f}</title></rect>')

    for col,color in [("ma5","#f59e0b"),("ma20","#2563eb")]:
        pts=[]
        for i,v in enumerate(x[col]):
            if pd.notna(v): pts.append(f'{left+(i+.5)*step:.2f},{yy(v):.2f}')
        if len(pts)>1: parts.append(f'<polyline points="{" ".join(pts)}" fill="none" stroke="{color}" stroke-width="1.7"/>')

    if "volume" in x.columns and x["volume"].notna().any():
        vmax=float(x["volume"].max()) or 1; vy0=height-22; vh=48
        for i,r in x.iterrows():
            if pd.isna(r.volume): continue
            cx=left+(i+.5)*step; bh=float(r.volume)/vmax*vh; col="#d62828" if r.close>=r.open else "#14804a"
            parts.append(f'<rect x="{cx-body/2:.2f}" y="{vy0-bh:.2f}" width="{body:.2f}" height="{bh:.2f}" fill="{col}" opacity=".42"/>')

    last=x.iloc[-1]; last_y=yy(last["close"]); last_col="#d62828" if last.close>=last.open else "#14804a"
    parts.append(f'<line x1="{left}" y1="{last_y:.2f}" x2="{width-right}" y2="{last_y:.2f}" stroke="{last_col}" opacity=".35"/>')
    parts.append(f'<rect x="{width-right-72}" y="{last_y-10:.2f}" width="70" height="18" rx="4" fill="{last_col}"/>')
    parts.append(f'<text x="{width-right-67}" y="{last_y+3:.2f}" font-size="10" fill="white">最新 {last.close:.2f}</text>')
    ma5=_safe_num(last.get("ma5")); ma20=_safe_num(last.get("ma20"))
    legend=[]
    if ma5 is not None: legend.append(f'MA5 {ma5:.2f}')
    if ma20 is not None: legend.append(f'MA20 {ma20:.2f}')
    parts.append(f'<text x="{max(left,width-250)}" y="18" font-size="10" fill="#475569">{" ｜ ".join(legend)}</text>')
    parts.append('</svg>')
    return ''.join(parts)
