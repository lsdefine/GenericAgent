;(function(){ if (/streamlit/i.test(document.title)) return;

// Remove meta CSP tags
document.querySelectorAll('meta[http-equiv="Content-Security-Policy"]').forEach(e => e.remove());

// Indicator badge at bottom-right (draggable, userscript style)
(function(){
  if(window.self!==window.top)return;
  const d=document.createElement('div');
  d.id='ljq-ind';
  d.innerText='GA_ljq_driver: 已连接';
  // 从localStorage恢复上次位置，否则默认右下角
  const saved=localStorage.getItem('ljq-ind-pos');
  if(saved){
    const p=JSON.parse(saved);
    d.style.cssText='position:fixed;top:'+p.y+'px;left:'+p.x+'px;background:#4CAF50;color:white;padding:4px 7px;border-radius:4px;font-size:11px;font-weight:bold;z-index:99999;cursor:grab;box-shadow:0 2px 4px rgba(0,0,0,0.2);opacity:0.5;user-select:none;';
  }else{
    d.style.cssText='position:fixed;bottom:8px;right:8px;background:#4CAF50;color:white;padding:4px 7px;border-radius:4px;font-size:11px;font-weight:bold;z-index:99999;cursor:grab;box-shadow:0 2px 4px rgba(0,0,0,0.2);opacity:0.5;user-select:none;';
  }
  // 拖动功能
  let isDragging=false,startX,startY,initLeft,initTop,hasMoved=false;
  d.addEventListener('mousedown',e=>{
    isDragging=true;hasMoved=false;
    startX=e.clientX;startY=e.clientY;
    const rect=d.getBoundingClientRect();
    initLeft=rect.left;initTop=rect.top;
    d.style.cursor='grabbing';
    d.style.opacity='0.8';
    e.preventDefault();
  });
  document.addEventListener('mousemove',e=>{
    if(!isDragging)return;
    const dx=e.clientX-startX,dy=e.clientY-startY;
    if(Math.abs(dx)>2||Math.abs(dy)>2)hasMoved=true;
    d.style.left=(initLeft+dx)+'px';
    d.style.top=(initTop+dy)+'px';
    d.style.right='auto';d.style.bottom='auto';
  });
  document.addEventListener('mouseup',()=>{
    if(!isDragging)return;
    isDragging=false;
    d.style.cursor='grab';d.style.opacity='0.5';
    // 保存位置
    const rect=d.getBoundingClientRect();
    localStorage.setItem('ljq-ind-pos',JSON.stringify({x:rect.left,y:rect.top}));
  });
  // 点击事件：只有没拖动时才触发，折叠展开信息面板
  d.addEventListener('click',e=>{
    if(hasMoved)return;
    let panel=document.getElementById('ljq-ind-panel');
    if(panel){panel.remove();return;}
    panel=document.createElement('div');
    panel.id='ljq-ind-panel';
    panel.style.cssText='position:fixed;background:#333;color:#fff;padding:10px 14px;border-radius:6px;font-size:12px;z-index:999999;box-shadow:0 4px 12px rgba(0,0,0,0.3);max-width:360px;word-break:break-all;font-family:monospace;line-height:1.6;visibility:hidden;';
    const rect=d.getBoundingClientRect();
    // 面板水平居中对齐按钮，垂直显示在按钮上方
    let panelLeft = rect.left + rect.width/2 - 150; // 居中，假设面板最大宽度300
    if(panelLeft < 8) panelLeft = 8;
    if(panelLeft + 300 > window.innerWidth) panelLeft = window.innerWidth - 308;
    panel.style.left = panelLeft + 'px';
    panel.style.top = 'auto';
    panel.style.right = 'auto';
    panel.style.bottom = (window.innerHeight - rect.top + 8) + 'px';
    (document.body||document.documentElement).appendChild(panel);
    // 根据实际高度调整top，确保不超出视口
    const pr=panel.getBoundingClientRect();
    if(pr.top<8){panel.style.top='8px';panel.style.bottom='auto';}
    panel.style.visibility='visible';
    panel.innerHTML='<div style="margin-bottom:6px;font-weight:bold;color:#4CAF50;">✓ ljq_driver 活跃</div>'
      +'<div style="color:#aaa;font-size:11px;">URL:</div><div>'+location.href+'</div>'
      +'<div style="color:#aaa;font-size:11px;margin-top:4px;">Title:</div><div>'+document.title+'</div>';
    (document.body||document.documentElement).appendChild(panel);
    // 点击面板外部关闭
    setTimeout(()=>{
      const close=e2=>{
        if(!panel.contains(e2.target)&&e2.target!==d){panel.remove();document.removeEventListener('click',close);}
      };
      document.addEventListener('click',close);
    },0);
  });
  (document.body||document.documentElement).appendChild(d);
})();

new MutationObserver(muts => {
  for (const m of muts) for (const n of m.addedNodes) {
    if (n.id === TID || (n.querySelector && n.querySelector('#' + TID))) {
      const el = n.id === TID ? n : n.querySelector('#' + TID);
      handle(el);
    }
  }
}).observe(document.documentElement, { childList: true, subtree: true });

async function handle(el) {
  try {
    const req = el.textContent.trim() ? JSON.parse(el.textContent) : { cmd: 'cookies' };
    const cmd = req.cmd || 'cookies';
    let resp;
    if (cmd === 'cookies') {
      resp = await chrome.runtime.sendMessage({ cmd: 'cookies', url: req.url || location.href });
    } else if (cmd === 'cdp') {
      resp = await chrome.runtime.sendMessage({ cmd: 'cdp', method: req.method, params: req.params || {}, tabId: req.tabId });
    } else if (cmd === 'batch') {
      resp = await chrome.runtime.sendMessage({ cmd: 'batch', commands: req.commands, tabId: req.tabId });
    } else if (cmd === 'tabs') {
      resp = await chrome.runtime.sendMessage({ cmd: 'tabs', method: req.method, tabId: req.tabId });
    } else {
      resp = { ok: false, error: 'unknown cmd: ' + cmd };
    }
    el.textContent = JSON.stringify(resp);
  } catch (e) {
    el.textContent = JSON.stringify({ ok: false, error: e.message });
  }
}
})();