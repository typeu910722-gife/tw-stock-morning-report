from __future__ import annotations
from pathlib import Path
from jinja2 import Template

TPL=r"""
<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{ title }}</title>
<style>
body{margin:0;background:#f3f4f6;color:#111827;font-family:Arial,"Microsoft JhengHei",sans-serif}
.wrap{max-width:1180px;margin:20px auto;padding:0 14px}.card{background:#fff;border-radius:16px;padding:18px;margin-bottom:14px;box-shadow:0 5px 20px rgba(0,0,0,.06)}
h1{margin:0;font-size:28px}.lead{font-size:22px;font-weight:800;margin-top:10px}.muted{font-size:12px;color:#6b7280}
h2{font-size:18px;margin:0 0 10px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:10px}
.pick{border:1px solid #e5e7eb;border-radius:12px;padding:12px}.up{color:#d62828}.down{color:#14804a}
table{width:100%;border-collapse:collapse;font-size:13px}th,td{padding:8px;border-bottom:1px solid #e5e7eb;text-align:right}th:first-child,td:first-child{text-align:left}
.small{font-size:12px;line-height:1.7}.tag{display:inline-block;padding:2px 8px;border-radius:999px;background:#eef2ff}
@media(max-width:720px){table{font-size:11px}.lead{font-size:18px}.card{padding:12px}}
</style></head><body><div class="wrap">
<div class="card"><div class="muted">報告交易日 {{ trade_date }}｜產生時間 {{ generated }}</div><h1>台股前一交易日晨報</h1><div class="lead">{{ one_liner }}</div></div>
<div class="card"><h2>夜盤＋美股</h2>{% for x in global_lines %}<div>• {{ x }}</div>{% endfor %}</div>
<div class="card"><h2>利多／利空</h2><div class="grid"><div><b class="up">利多</b>{% for n in bull %}<div>• {{ n.title }}</div>{% endfor %}</div><div><b class="down">利空</b>{% for n in bear %}<div>• {{ n.title }}</div>{% endfor %}</div></div></div>
<div class="card"><h2>當沖觀察</h2><div class="muted">依技術條件篩選之觀察清單，僅供參考，非投資建議，當沖風險極高。</div><div class="grid">{% for p in picks %}<div class="pick"><b class="{{ 'up' if p.side=='多' else 'down' }}">{{ p.code }} {{ p.name }}｜{{ p.side }}</b><div>{{ p.reason }}</div><div class="small">進場 {{ p.entry }}｜防守 {{ p.stop }}｜目標 {{ p.target }}</div></div>{% endfor %}</div></div>
<div class="card"><h2>20檔總表</h2><table><thead><tr><th>代號名稱</th><th>收盤</th><th>漲跌%</th><th>量比</th><th>法人</th><th>趨勢</th><th>當沖傾向</th><th>防守價</th></tr></thead><tbody>{% for r in rows %}<tr><td>{{ r.code }} {{ r.name }}</td><td>{{ r.close }}</td><td class="{{ 'up' if r.pct>0 else 'down' if r.pct<0 else '' }}">{{ "%+.2f"|format(r.pct) }}</td><td>{{ "%.2f"|format(r.vol_ratio) }}</td><td>{{ r.inst }}</td><td>{{ r.trend }}</td><td>{{ r.bias }}</td><td>{{ r.stop }}</td></tr>{% endfor %}</tbody></table></div>
<div class="card"><h2>大盤</h2><div>{{ market_summary }}</div><div>支撐 {{ market_support }}｜壓力 {{ market_resistance }}｜趨勢 {{ market_trend }}</div><div class="muted">資料源：{{ market_source }}</div></div>
<div class="card"><details><summary><b>附錄</b></summary><div class="small"><h3>訊號勝率</h3>{% for b in backtests %}<div>{{ b.signal }}：樣本 {{ b.samples }} 次，{{ b.label }} {{ b.wins }} 次（{{ b.rate }}%）{% if b.small %}，樣本過小僅供參考{% endif %}</div>{% endfor %}<h3>完整指標</h3>{% for r in rows %}<div>{{ r.code }} {{ r.name }}｜MA5 {{ r.ma5 }}｜MA20 {{ r.ma20 }}｜K {{ r.k }}｜D {{ r.d }}｜MACD {{ r.macd }}｜RSI {{ r.rsi }}｜支撐 {{ r.support }}｜壓力 {{ r.resistance }}</div>{% endfor %}<h3>資料缺漏</h3>{% for n in notes %}<div>• {{ n }}</div>{% endfor %}</div></details></div>
<div class="card small">免責聲明：本報告僅為公開資料與技術條件整理，不構成任何投資建議。當沖風險極高，交易人應自行判斷並承擔損益。<br>資料來源：臺灣證券交易所、Yahoo Finance、Google News RSS。</div>
</div></body></html>
"""

def write(path:Path,ctx:dict):
    path.write_text(Template(TPL).render(**ctx),encoding="utf-8")
