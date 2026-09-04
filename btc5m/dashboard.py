import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>BTC 5分钟预测市场</title>
<style>
:root{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;color:#17202a;background:#f4f6f8}
*{box-sizing:border-box}body{max-width:1380px;margin:20px auto;padding:0 16px}
header{display:flex;justify-content:space-between;align-items:end;gap:16px;margin-bottom:14px}
h1{margin:0;font-size:26px}.muted{color:#68737d}.up{color:#16834b}.down{color:#bb3e35}
.status{display:flex;gap:12px;flex-wrap:wrap;justify-content:flex-end;font-size:13px}
.grid{display:grid;grid-template-columns:repeat(6,minmax(130px,1fr));gap:10px;margin-bottom:12px}
.panel{background:#fff;border:1px solid #d9dee3;border-radius:6px;padding:14px;margin-bottom:12px}
.label{font-size:12px;color:#68737d}.value{font-size:22px;font-weight:700;margin-top:5px;overflow-wrap:anywhere}
.round{display:grid;grid-template-columns:1.4fr 1fr 1fr 1fr;gap:12px;align-items:center}
.round-main{font-size:27px;font-weight:750}.round-main small{font-size:13px;font-weight:400;color:#68737d}
.chart-wrap{padding:10px;background:#111820;border-radius:4px}#chart{width:100%;height:400px;display:block}
.two-col{display:grid;grid-template-columns:minmax(0,1.15fr) minmax(330px,.85fr);gap:12px}
.three-col{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}
.prob-row{display:flex;justify-content:space-between;font-size:14px;margin:9px 0 4px}
.bar{height:9px;background:#edf0f2;border-radius:2px;overflow:hidden}.bar i{display:block;height:100%}
.bar .green{background:#22a064}.bar .red{background:#d85a56}
.metric-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:9px;margin-top:12px}
.metric{border-top:1px solid #edf0f2;padding-top:8px;font-size:13px}.metric strong{display:block;font-size:16px;margin-top:3px}
button{min-height:36px;border:1px solid #1769aa;background:#1769aa;color:#fff;border-radius:4px;padding:0 13px;font:inherit;cursor:pointer}
button.secondary{border-color:#c9d0d6;background:#fff;color:#17202a}button.danger{border-color:#bb3e35;background:#bb3e35}
button:disabled{opacity:.6;cursor:wait}.controls{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
input{width:100%;min-height:36px;border:1px solid #c9d0d6;border-radius:4px;padding:7px 9px;font:inherit}
.inline-form{display:grid;grid-template-columns:1fr auto;gap:8px;margin-top:10px}
.account-form{display:grid;grid-template-columns:1fr 1fr auto;gap:8px;align-items:end}
.check{display:flex;gap:7px;align-items:center;min-height:36px;font-size:13px;white-space:nowrap}
.account-actions{display:flex;gap:8px;align-items:center;margin-top:9px;flex-wrap:wrap}
.balance-list{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-top:12px}
.balance{border-top:1px solid #edf0f2;padding-top:8px;font-size:13px}.balance strong{display:block;font-size:16px}
table{width:100%;border-collapse:collapse;background:#fff}th,td{text-align:left;padding:8px 9px;border-bottom:1px solid #edf0f2;font-size:12px;white-space:nowrap}
.table-scroll{overflow:auto}.empty{padding:18px;text-align:center;color:#68737d}
.notice{font-size:12px;line-height:1.5;padding:9px;background:#fff7e6;border-left:3px solid #d89925;margin-top:10px}
.decision{display:grid;grid-template-columns:1.1fr 1fr 1fr 1fr;gap:12px;align-items:start}
.decision-action{font-size:25px;font-weight:750}.decision-action.wait{color:#9a6a00}.decision-action.enter{color:#16834b}.decision-action.close{color:#bb3e35}
.reason-list{margin:8px 0 0;padding-left:18px;font-size:13px;line-height:1.55}.quality{font-weight:700}
@media(max-width:1050px){.grid{grid-template-columns:repeat(3,minmax(130px,1fr))}.round{grid-template-columns:repeat(2,1fr)}}
@media(max-width:700px){body{margin:12px auto}.grid{grid-template-columns:repeat(2,minmax(130px,1fr))}header{display:block}.status{justify-content:flex-start;margin-top:8px}.two-col,.three-col{display:block}.decision{grid-template-columns:1fr 1fr}.account-form{grid-template-columns:1fr}.balance-list{grid-template-columns:repeat(2,1fr)}#chart{height:300px}}
</style>
</head>
<body>
<header>
  <div><h1>BTCUSDT 5分钟预测市场</h1><span class="muted">默认纸上交易，Spot账户连接仅用于账户读取</span></div>
  <div class="status"><span id="service-status">服务连接中</span><span id="updated">-</span></div>
</header>
<section class="grid">
  <div class="panel"><div class="label">预测市场权益</div><div id="equity" class="value">-</div></div>
  <div class="panel"><div class="label">本轮涨跌幅</div><div id="change" class="value">-</div></div>
  <div class="panel"><div class="label">AI方向</div><div id="signal" class="value">-</div></div>
  <div class="panel"><div class="label">UP概率</div><div id="up-prob" class="value up">-</div></div>
  <div class="panel"><div class="label">DOWN概率</div><div id="down-prob" class="value down">-</div></div>
  <div class="panel"><div class="label">最大回撤</div><div id="drawdown" class="value">-</div></div>
</section>
<section class="panel round">
  <div><div class="label">当前周期</div><div id="round-id" class="round-main">-</div><small id="round-status">-</small></div>
  <div><div class="label">倒计时</div><div id="countdown" class="value">-</div></div>
  <div><div class="label">开盘价 / 当前价</div><div id="prices" class="value">-</div></div>
  <div><div class="label">已结算准确率</div><div id="accuracy" class="value">-</div></div>
</section>
<section class="panel"><div class="chart-wrap"><canvas id="chart"></canvas></div></section>
<section class="panel decision">
  <div><div class="label">实时出手决策</div><div id="decision-action" class="decision-action wait">-</div><div id="decision-direction" class="muted">-</div></div>
  <div><div class="label">决策概率 / 置信度</div><div id="decision-prob" class="value">-</div><div id="decision-confidence" class="muted">-</div><div id="decision-deep" class="muted">深度模型 -</div></div>
  <div><div class="label">数据质量</div><div id="decision-quality" class="quality">-</div><div id="decision-market-data" class="muted">-</div><div id="decision-model-status" class="muted">模型 -</div></div>
  <div><div class="label">实时压力</div><div id="decision-pressure" class="muted">-</div><div id="decision-reason" class="muted">-</div></div>
  <div style="grid-column:1/-1"><div class="label">判断依据</div><ul id="decision-reasons" class="reason-list"><li>-</li></ul></div>
</section>
<section class="three-col">
  <div class="panel">
    <div class="label">5-minute close forecast</div>
    <div id="close-direction" class="decision-action wait">-</div>
    <div class="metric-grid">
      <div class="metric">UP probability<strong id="close-prob">-</strong></div>
      <div class="metric">confidence<strong id="close-confidence">-</strong></div>
      <div class="metric">price vs lock<strong id="close-price-change">-</strong></div>
      <div class="metric">forecast state<strong id="close-status">-</strong></div>
    </div>
  </div>
  <div class="panel">
    <div class="label">Buy / sell pressure</div>
    <div id="pressure-state" class="decision-action wait">-</div>
    <div class="metric-grid">
      <div class="metric">pressure score<strong id="pressure-score">-</strong></div>
      <div class="metric">15s flow<strong id="pressure-flow">-</strong></div>
      <div class="metric">60s flow<strong id="pressure-flow-60">-</strong></div>
      <div class="metric">divergence<strong id="pressure-divergence">-</strong></div>
    </div>
  </div>
  <div class="panel">
    <div class="label">Spot grid (paper only)</div>
    <div id="grid-regime" class="decision-action wait">-</div>
    <div class="metric-grid">
      <div class="metric">range<strong id="grid-range">-</strong></div>
      <div class="metric">spacing<strong id="grid-spacing">-</strong></div>
      <div class="metric">buy levels<strong id="grid-buy-levels">-</strong></div>
      <div class="metric">sell levels<strong id="grid-sell-levels">-</strong></div>
    </div>
    <div id="grid-reason" class="muted" style="margin-top:8px">-</div>
  </div>
</section>
<section class="three-col">
  <div class="panel">
    <div class="label">AI预测分析</div>
    <div class="prob-row"><span>UP</span><strong id="up-bar-text">-</strong></div><div class="bar"><i id="up-bar" class="green" style="width:0"></i></div>
    <div class="prob-row"><span>DOWN</span><strong id="down-bar-text">-</strong></div><div class="bar"><i id="down-bar" class="red" style="width:0"></i></div>
    <div class="metric-grid"><div class="metric">置信度<strong id="confidence">-</strong></div><div class="metric">建议<strong id="recommendation">-</strong></div><div class="metric">模型状态<strong id="model-status">-</strong></div><div class="metric">预测来源<strong>Binance公开行情</strong></div></div>
  </div>
  <div class="panel">
    <div class="label">赔率与收益计算</div>
    <div class="metric-grid"><div class="metric">UP赔率<strong id="up-odds">-</strong><small id="up-effective-odds" class="muted">含滑点 -</small></div><div class="metric">DOWN赔率<strong id="down-odds">-</strong><small id="down-effective-odds" class="muted">含滑点 -</small></div><div class="metric">UP资金池<strong id="up-pool">-</strong></div><div class="metric">DOWN资金池<strong id="down-pool">-</strong></div><div class="metric">UP期望值<strong id="up-ev">-</strong></div><div class="metric">DOWN期望值<strong id="down-ev">-</strong></div><div class="metric">UP Kelly建议<strong id="up-kelly">-</strong></div><div class="metric">DOWN Kelly建议<strong id="down-kelly">-</strong></div></div>
    <div class="notice">赔率、资金池和提前平仓估值当前是纸上市场模拟值，不代表 Binance 实时预测市场订单簿。</div>
  </div>
  <div class="panel">
    <div class="label">风险控制</div>
    <div class="metric-grid"><div class="metric">自动交易<strong id="auto-status">关闭</strong></div><div class="metric">控制状态<strong id="control-status">正常</strong></div><div class="metric">本日交易<strong id="daily-trades">-</strong></div><div class="metric">本日亏损<strong id="daily-loss">-</strong></div><div class="metric">连败次数<strong id="loss-streak">-</strong></div><div class="metric">单周期上限<strong id="stake-limit">-</strong></div><div class="metric">最后禁入<strong id="no-trade">-</strong></div></div>
  </div>
</section>
<section class="panel">
  <div class="label">交易控制</div>
  <div class="controls">
    <button id="auto-toggle" type="button">开启自动交易</button><button id="pause-toggle" class="secondary" type="button">暂停</button><button id="stop" class="danger" type="button">紧急停止</button><button id="resume" class="secondary" type="button">解除停止</button>
  </div>
  <form id="order-form" class="inline-form"><input id="stake" type="number" min="5" step="0.01" placeholder="手动下注金额 USDT"><button type="submit">按当前建议下注</button></form>
  <div id="trade-message" class="muted" style="margin-top:8px">自动交易默认关闭。先用纸上账户验证策略。</div>
</section>
<section class="two-col">
  <div>
    <div class="panel"><div class="label">活跃预测仓位</div><div class="table-scroll"><table><thead><tr><th>方向</th><th>金额</th><th>入场赔率</th><th>当前估值</th><th>浮动盈亏</th><th>操作</th></tr></thead><tbody id="position-rows"></tbody></table></div></div>
    <div class="panel"><div class="label">预测市场历史</div><div class="table-scroll"><table><thead><tr><th>周期</th><th>开盘</th><th>收盘</th><th>结果</th><th>状态</th></tr></thead><tbody id="round-rows"></tbody></table></div></div>
  </div>
  <div>
    <div class="panel"><div class="label">连接 Binance Spot 账户</div>
      <form id="account-form" class="account-form"><label>API Key<input id="api-key" type="text" autocomplete="off" spellcheck="false"></label><label>API Secret<input id="api-secret" type="password" autocomplete="new-password"></label><label class="check"><input id="testnet" type="checkbox" checked> Testnet</label></form>
      <div class="account-actions"><button id="connect" type="submit" form="account-form">连接并读取余额</button><button id="disconnect" class="secondary" type="button">断开</button><span id="account-message" class="muted">密钥只保存在当前进程内存</span></div><div id="balances" class="balance-list"></div>
      <div class="notice">此处连接的是 Binance Spot REST 账户，不等同于预测市场钱包。不要在聊天中发送 API Key/Secret；建议关闭提现权限并限制 IP。</div>
    </div>
    <div class="panel table-scroll"><div class="label">现货订单记录</div><table><thead><tr><th>时间</th><th>模式</th><th>方向</th><th>价格</th><th>状态</th></tr></thead><tbody id="order-rows"></tbody></table></div>
  </div>
</section>
<script>
const state={data:null};const $=id=>document.getElementById(id);
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const n=(v,d=2)=>Number(v||0).toLocaleString(undefined,{minimumFractionDigits:d,maximumFractionDigits:d});
const pct=(v,d=1)=>n(Number(v||0)*100,d)+'%';const dt=v=>v?new Date(v).toLocaleTimeString():'-';
function drawChart(bars,round){const c=$('chart'),r=c.getBoundingClientRect(),d=devicePixelRatio||1,w=Math.max(320,r.width),h=Math.max(240,r.height);c.width=w*d;c.height=h*d;const x=c.getContext('2d');x.setTransform(d,0,0,d,0,0);x.clearRect(0,0,w,h);if(!bars?.length){x.fillStyle='#aeb9c4';x.fillText('等待K线数据',20,30);return}const pad={l:58,r:14,t:18,b:28},pw=w-pad.l-pad.r,ph=h-pad.t-pad.b,hi=Math.max(...bars.map(b=>b.high)),lo=Math.min(...bars.map(b=>b.low)),sp=hi-lo||1,max=hi+sp*.05,min=lo-sp*.05,y=p=>pad.t+(max-p)/(max-min)*ph,step=pw/bars.length,cw=Math.max(2,Math.min(14,step*.65));x.font='11px system-ui';x.strokeStyle='#2b3742';x.fillStyle='#aeb9c4';for(let i=0;i<5;i++){let gy=pad.t+ph*i/4;x.beginPath();x.moveTo(pad.l,gy);x.lineTo(w-pad.r,gy);x.stroke();x.fillText(n(max-(max-min)*i/4),5,gy+4)}bars.forEach((b,i)=>{let cx=pad.l+step*(i+.5),o=y(b.open),cl=y(b.close),color=b.close>=b.open?'#22b573':'#e45b5b';x.strokeStyle=color;x.fillStyle=color;x.beginPath();x.moveTo(cx,y(b.high));x.lineTo(cx,y(b.low));x.stroke();x.fillRect(cx-cw/2,Math.min(o,cl),cw,Math.max(1,Math.abs(o-cl)))});if(round?.lock_price){x.strokeStyle='#e0b04f';x.setLineDash([5,4]);x.beginPath();x.moveTo(pad.l,y(round.lock_price));x.lineTo(w-pad.r,y(round.lock_price));x.stroke();x.setLineDash([]);x.fillStyle='#e0b04f';x.fillText('本轮开盘 '+n(round.lock_price),pad.l+5,y(round.lock_price)-5)}}
function renderAccount(a){$('account-message').textContent=a.error||(!a.connected?'未连接':(a.testnet?'Testnet 已连接':'主网已连接'));$('account-message').className=a.error?'down':(a.connected?'up':'muted');const es=Object.entries(a.balances||{}).slice(0,9);$('balances').innerHTML=es.length?es.map(([asset,b])=>'<div class="balance"><span>'+esc(asset)+'</span><strong>'+n(Number(b.free)+Number(b.locked),6)+'</strong><small>free '+n(b.free,6)+' / locked '+n(b.locked,6)+'</small></div>').join(''):'<span class="muted">暂无账户余额</span>'}
function render(d){state.data=d;const r=d.prediction_market?.round,p=d.latest_prediction,bars=d.bars||[],risk=d.prediction_risk||{};$('updated').textContent='更新 '+new Date().toLocaleTimeString();$('service-status').textContent='实时运行';$('equity').textContent=n(d.prediction_market?.account?.quote);if(r){$('round-id').textContent=new Date(r.start_time).toLocaleTimeString()+' - '+new Date(r.end_time).toLocaleTimeString();$('round-status').textContent=r.status==='live'?'交易中':'结算中';$('countdown').textContent=Math.max(0,Math.floor((r.end_time-Date.now())/1000))+' 秒';$('prices').textContent=n(r.lock_price)+' / '+n(r.current_price);$('change').textContent=pct(r.current_price/r.lock_price-1,3);$('change').className='value '+(r.current_price>=r.lock_price?'up':'down');$('up-prob').textContent=pct(r.p_up);$('down-prob').textContent=pct(1-r.p_up);$('signal').textContent=r.p_up>=.5?'UP':'DOWN';$('signal').className='value '+(r.p_up>=.5?'up':'down');$('up-bar-text').textContent=pct(r.p_up);$('down-bar-text').textContent=pct(1-r.p_up);$('up-bar').style.width=(r.p_up*100)+'%';$('down-bar').style.width=((1-r.p_up)*100)+'%';$('confidence').textContent=pct(r.confidence);$('recommendation').textContent=r.p_up>=.5?'BUY UP':'BUY DOWN';$('up-odds').textContent=n(r.up_odds,3)+'x';$('down-odds').textContent=n(r.down_odds,3)+'x';$('up-pool').textContent='$'+n(r.up_pool);$('down-pool').textContent='$'+n(r.down_pool);$('up-ev').textContent=pct(r.up_ev);$('down-ev').textContent=pct(r.down_ev);$('model-status').textContent=p?'在线':'预热中'}$('accuracy').textContent=d.metrics.accuracy==null?'-':pct(d.metrics.accuracy);$('drawdown').textContent=d.risk.max_drawdown==null?'-':pct(d.risk.max_drawdown,2);$('auto-status').textContent=d.prediction_controls.auto_trading?'开启':'关闭';$('control-status').textContent=d.prediction_controls.emergency_stop?'紧急停止':(d.prediction_controls.paused?'已暂停':'正常');$('daily-trades').textContent=(risk.daily_trades??'-')+' / '+d.settings.prediction_max_daily_trades;$('daily-loss').textContent='$'+n(risk.daily_loss);$('loss-streak').textContent=(risk.loss_streak??'-')+' / '+d.settings.prediction_max_loss_streak;$('stake-limit').textContent='$'+n(d.settings.prediction_max_stake);$('no-trade').textContent=d.settings.prediction_no_trade_last_seconds+' 秒';$('pause-toggle').textContent=d.prediction_controls.paused?'继续':'暂停';drawChart(bars,r);$('position-rows').innerHTML=(d.prediction_market?.positions||[]).length?d.prediction_market.positions.map(x=>'<tr><td class="'+(x.direction==='UP'?'up':'down')+'">'+x.direction+'</td><td>$'+n(x.stake)+'</td><td>'+n(x.entry_odds,3)+'x</td><td>$'+n(x.value)+'</td><td class="'+(x.pnl>=0?'up':'down')+'">$'+n(x.pnl)+'</td><td><button class="secondary close-position" data-id="'+x.id+'">平仓</button></td></tr>').join(''):'<tr><td colspan="6" class="empty">暂无活跃仓位</td></tr>';$('round-rows').innerHTML=(d.prediction_rounds||[]).map(x=>'<tr><td>'+dt(x.start_time)+'</td><td>'+n(x.lock_price)+'</td><td>'+(x.close_price==null?'-':n(x.close_price))+'</td><td>'+(x.close_price==null?'-':(x.close_price>x.lock_price?'UP':'DOWN'))+'</td><td>'+esc(x.status)+'</td></tr>').join('');$('order-rows').innerHTML=d.orders.length?d.orders.map(x=>'<tr><td>'+dt(x.created_at)+'</td><td>'+esc(x.mode)+'</td><td>'+esc(x.side)+'</td><td>'+n(x.price)+'</td><td>'+esc(x.status)+'</td></tr>').join(''):'<tr><td colspan="5" class="empty">暂无现货订单</td></tr>';renderAccount(d.account)}
const baseRender=render;render=function(d){baseRender(d);const r=d.prediction_market?.round;if(!r)return;const slip=1-d.settings.prediction_slippage_bps/10000;$('up-effective-odds').textContent='含滑点 '+n(r.up_odds*slip,3)+'x';$('down-effective-odds').textContent='含滑点 '+n(r.down_odds*slip,3)+'x';$('up-kelly').textContent=pct(r.up_kelly);$('down-kelly').textContent=pct(r.down_kelly)}
const decisionRender=render;render=function(d){decisionRender(d);const r=d.prediction_market?.round,q=r?.decision||{},a=$('decision-action');const labels={WAIT:'观察',NO_TRADE:'禁止交易',ENTER_UP:'出手 UP',ENTER_DOWN:'出手 DOWN',HOLD:'继续持有',CLOSE:'平仓'};a.textContent=labels[q.action]||q.action||'等待数据';a.className='decision-action '+((q.action||'').startsWith('ENTER')?'enter':q.action==='CLOSE'?'close':'wait');$('decision-direction').textContent=q.direction&&q.direction!=='NONE'?'方向 '+q.direction:'当前不建议开仓';$('decision-prob').textContent=q.combined_probability==null?'-':pct(q.combined_probability);$('decision-confidence').textContent='基线 '+(q.baseline_probability==null?'-':pct(q.baseline_probability))+' / 置信度 '+(q.confidence==null?'-':pct(q.confidence));$('decision-deep').textContent='深度模型 '+(q.deep_probability==null?'未训练':pct(q.deep_probability))+' / '+(q.model_agreement||'不可用')+' / 决策使用 '+(q.deep_used_for_decision?'是':'否');$('decision-quality').textContent=q.quality||'-';$('decision-market-data').textContent='延迟 '+(q.data_age_ms==null?'-':q.data_age_ms+' ms')+' / 价差 '+(q.spread_bps==null?'-':n(q.spread_bps,2)+' bps');$('decision-model-status').textContent='校准 '+(q.calibration_status||'-')+' / 样本 '+(q.training_samples||0);$('decision-pressure').textContent='成交15s '+pct(q.trade_imbalance_15s,1)+' / 盘口 '+pct(q.book_imbalance,1)+' / 动量 '+pct(q.momentum_15s,3);$('decision-reason').textContent=q.reason||'-';$('decision-reasons').innerHTML=(q.reasons||[]).map(x=>'<li>'+esc(x)+'</li>').join('')||'<li>-</li>';const realtime=d.prediction_market?.realtime||d.realtime,rtbars=realtime?.bars_1s||[];if(rtbars.length)drawChart(rtbars,r)}
const analysisRender=render;render=function(d){analysisRender(d);const r=d.prediction_market?.round||{},q=r.decision||{},f=r.close_forecast||{},p=r.pressure||{},g=r.grid||{};const cd=$('close-direction');cd.textContent=f.direction||'-';cd.className='decision-action '+(f.direction==='UP'?'enter':f.direction==='DOWN'?'close':'wait');$('close-prob').textContent=f.p_up==null?'-':pct(f.p_up);$('close-confidence').textContent=f.confidence==null?'-':pct(f.confidence);$('close-price-change').textContent=f.price_change_pct==null?'-':pct(f.price_change_pct,3);$('close-status').textContent=f.status||'-';const ps=$('pressure-state');ps.textContent=p.strength||q.pressure_strength||'-';ps.className='decision-action '+((p.direction||q.pressure_direction)==='UP'?'enter':(p.direction||q.pressure_direction)==='DOWN'?'close':'wait');$('pressure-score').textContent=p.score==null?'-':n(p.score,3);$('pressure-flow').textContent=p.trade_imbalance_15s==null?'-':pct(p.trade_imbalance_15s,1);$('pressure-flow-60').textContent=p.trade_imbalance_60s==null?'-':pct(p.trade_imbalance_60s,1);$('pressure-divergence').textContent=p.divergence||'-';$('grid-regime').textContent=g.enabled?'READY':(g.regime||'DISABLED');$('grid-regime').className='decision-action '+(g.enabled?'enter':'wait');$('grid-range').textContent=g.range_pct==null?'-':pct(g.range_pct,2);$('grid-spacing').textContent=g.spacing_pct==null?'-':pct(g.spacing_pct,2);$('grid-buy-levels').textContent=(g.buy_levels||[]).map(x=>n(x,2)).join(', ')||'-';$('grid-sell-levels').textContent=(g.sell_levels||[]).map(x=>n(x,2)).join(', ')||'-';$('grid-reason').textContent=g.reason||'-';const closeLabels={UP:'CLOSE UP',DOWN:'CLOSE DOWN',NEUTRAL:'CLOSE NEUTRAL'};$('signal').textContent=closeLabels[f.direction]||'NO FORECAST';$('signal').className='value '+(f.direction==='UP'?'up':f.direction==='DOWN'?'down':'muted');const actionLabels={WAIT:'WAIT',NO_TRADE:'NO TRADE',ENTER_UP:'ENTER UP',ENTER_DOWN:'ENTER DOWN',HOLD:'HOLD',CLOSE:'CLOSE'};$('recommendation').textContent=actionLabels[q.action]||'WAIT'}
async function refresh(){try{const r=await fetch('/api/status',{cache:'no-store'});if(!r.ok)throw Error('status '+r.status);render(await r.json())}catch(e){$('service-status').textContent='服务连接失败';$('service-status').className='down'}}
async function post(path,body){const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body||{})});const d=await r.json();if(!r.ok)throw Error(d.error||d.reason||'请求失败');return d}
$('auto-toggle').onclick=async()=>{try{await post('/api/prediction/controls',{auto_trading:!state.data.prediction_controls.auto_trading});await refresh()}catch(e){$('trade-message').textContent=e.message}};
$('pause-toggle').onclick=async()=>{try{await post('/api/prediction/controls',{paused:!state.data.prediction_controls.paused});await refresh()}catch(e){$('trade-message').textContent=e.message}};
$('stop').onclick=async()=>{try{await post('/api/prediction/controls',{emergency_stop:true,auto_trading:false});await refresh()}catch(e){$('trade-message').textContent=e.message}};
$('resume').onclick=async()=>{try{await post('/api/prediction/controls',{emergency_stop:false});await refresh()}catch(e){$('trade-message').textContent=e.message}};
$('order-form').onsubmit=async e=>{e.preventDefault();try{const d=await post('/api/prediction/order',{direction:state.data.prediction_market.round.p_up>=.5?'UP':'DOWN',stake:Number($('stake').value||0)});$('trade-message').textContent=d.executed?'已创建纸上仓位 #'+d.position_id:d.reason;await refresh()}catch(x){$('trade-message').textContent=x.message}};
document.onclick=async e=>{if(e.target.classList.contains('close-position')){try{const d=await post('/api/prediction/close',{position_id:e.target.dataset.id});$('trade-message').textContent='已平仓，盈亏 $'+n(d.pnl);await refresh()}catch(x){$('trade-message').textContent=x.message}}};
$('account-form').onsubmit=async e=>{e.preventDefault();const b=$('connect');b.disabled=true;$('account-message').textContent='连接中...';try{const d=await post('/api/account/connect',{api_key:$('api-key').value,api_secret:$('api-secret').value,testnet:$('testnet').checked});$('api-key').value='';$('api-secret').value='';renderAccount(d.account);await refresh()}catch(x){$('account-message').textContent=x.message;$('account-message').className='down'}finally{b.disabled=false}};
$('disconnect').onclick=async()=>{await post('/api/account/disconnect');$('api-key').value='';$('api-secret').value='';await refresh()};window.onresize=()=>state.data&&drawChart(state.data.bars,state.data.prediction_market?.round);refresh();setInterval(refresh,4000);setInterval(()=>{if(state.data?.prediction_market?.round){let s=Math.max(0,Math.floor((state.data.prediction_market.round.end_time-Date.now())/1000));$('countdown').textContent=s+' 秒'}},1000);
</script>
</body></html>"""


def account_status(engine):
    try:
        return engine.trader.account_snapshot()
    except Exception as error:
        return {"connected": False, "error": str(error)}


def json_body(handler):
    length = int(handler.headers.get("Content-Length", "0"))
    if length > 10_000:
        raise ValueError("request body is too large")
    raw = handler.rfile.read(length) if length else b"{}"
    return json.loads(raw.decode("utf-8"))


def make_handler(engine):
    class Handler(BaseHTTPRequestHandler):
        def send_json(self, payload, status=200):
            body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/" or self.path.startswith("/?"):
                body = HTML.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if self.path == "/api/status":
                try:
                    market = engine.refresh_prediction_market()
                    market_error = None
                except Exception as error:
                    market = engine.prediction_state
                    market_error = str(error)
                stats = engine.store.prediction_daily_stats(
                    engine._day_start_ms(__import__("time").time_ns() // 1_000_000)
                )
                self.send_json(
                    {
                        "latest_prediction": engine.store.latest_prediction(),
                        "predictions": engine.store.predictions(50),
                        "metrics": engine.store.metrics(),
                        "orders": engine.store.orders(50),
                        "risk": engine.store.risk_metrics(),
                        "account": account_status(engine),
                        "bars": engine.store.bars(180),
                        "paper": engine.store.paper_account(),
                        "prediction_rounds": engine.store.prediction_rounds(20),
                        "prediction_market": market,
                        "prediction_risk": stats,
                        "prediction_controls": engine.prediction_controls,
                        "settings": {
                            "symbol": engine.settings.symbol,
                            "interval": engine.settings.interval,
                            "websocket": engine.settings.websocket_enabled,
                            "testnet": engine.settings.testnet,
                            "live_trading": engine.settings.live_trading,
                            "prediction_mode": engine.settings.prediction_mode,
                            "prediction_fee_bps": engine.settings.prediction_fee_bps,
                            "prediction_slippage_bps": engine.settings.prediction_slippage_bps,
                            "prediction_max_stake": engine.settings.prediction_max_stake,
                            "prediction_max_daily_trades": engine.settings.prediction_max_daily_trades,
                            "prediction_max_loss_streak": engine.settings.prediction_max_loss_streak,
                            "prediction_no_trade_last_seconds": engine.settings.prediction_no_trade_last_seconds,
                            "prediction_observation_seconds": engine.settings.prediction_observation_seconds,
                            "prediction_entry_probability": engine.settings.prediction_entry_probability,
                            "prediction_decision_min_ev": engine.settings.prediction_decision_min_ev,
                            "prediction_max_spread_bps": engine.settings.prediction_max_spread_bps,
                            "prediction_realtime_stale_ms": engine.settings.prediction_realtime_stale_ms,
                            "prediction_deep_enabled": engine.settings.prediction_deep_enabled,
                            "prediction_deep_use_for_decision": engine.settings.prediction_deep_use_for_decision,
                            "prediction_deep_min_test_accuracy": engine.settings.prediction_deep_min_test_accuracy,
                            "prediction_deep_max_test_brier": engine.settings.prediction_deep_max_test_brier,
                            "prediction_neutral_lower": engine.settings.prediction_neutral_lower,
                            "prediction_neutral_upper": engine.settings.prediction_neutral_upper,
                            "prediction_min_pressure_score": engine.settings.prediction_min_pressure_score,
                            "grid_enabled": engine.settings.grid_enabled,
                            "grid_levels": engine.settings.grid_levels,
                            "grid_spacing_pct": engine.settings.grid_spacing_pct,
                            "grid_min_spacing_pct": engine.settings.grid_min_spacing_pct,
                            "grid_max_quote": engine.settings.grid_max_quote,
                            "deep_model": engine.deep_model.status(),
                        },
                        "prediction_market_error": market_error,
                    }
                )
                return
            self.send_error(404, "not found")

        def do_POST(self):
            try:
                payload = json_body(self)
                if self.path == "/api/account/connect":
                    engine.trader.connect_account(
                        str(payload.get("api_key", "")).strip(),
                        str(payload.get("api_secret", "")).strip(),
                        bool(payload.get("testnet", True)),
                    )
                    self.send_json({"ok": True, "account": engine.trader.account_snapshot()})
                    return
                if self.path == "/api/account/disconnect":
                    engine.trader.disconnect_account()
                    self.send_json({"ok": True, "account": account_status(engine)})
                    return
                if self.path == "/api/prediction/controls":
                    self.send_json({"ok": True, "controls": engine.set_prediction_controls(payload)})
                    return
                if self.path == "/api/prediction/order":
                    result = engine.open_prediction_position(
                        str(payload.get("direction", "")),
                        float(payload.get("stake", 0)),
                    )
                    self.send_json(result, 200 if result.get("executed") else 400)
                    return
                if self.path == "/api/prediction/close":
                    result = engine.close_prediction_position(int(payload.get("position_id")))
                    self.send_json(result, 200 if result.get("executed") else 400)
                    return
                self.send_error(404, "not found")
            except Exception as error:
                self.send_json({"ok": False, "error": str(error)}, 400)

        def log_message(self, *_):
            return

    return Handler


def serve(engine, port: int):
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(engine))
    server.serve_forever()
