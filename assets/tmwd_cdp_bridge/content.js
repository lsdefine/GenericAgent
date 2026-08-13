;(function(){ if (/streamlit/i.test(document.title)) return;

// Remove meta CSP tags
document.querySelectorAll('meta[http-equiv="Content-Security-Policy"]').forEach(e => e.remove());

// Indicator badge at bottom-right (userscript style)
(function(){
  if(window.self!==window.top)return;
  const d=document.createElement('div');
  d.textContent='ljq_driver: 已连接';
  d.style.cssText='position:fixed;bottom:8px;right:8px;background:#4CAF50;color:white;padding:4px 7px;border-radius:4px;font-size:11px;font-weight:bold;z-index:99999;box-shadow:0 2px 4px rgba(0,0,0,0.2);opacity:0.2;pointer-events:none;';
  const S={connected:['已连接','#4CAF50'],connecting:['重连中','#FF9800'],disconnected:['断开','#F44336']};
  const R=s=>{const[t,c]=S[s]||S.disconnected;d.textContent='ljq_driver: '+t;d.style.background=c};
  chrome.runtime.onMessage.addListener(m=>{if(m?.type==='tmwd_status')R(m.data)});
  chrome.runtime.sendMessage({cmd:'status'},r=>R(r?.ok?r.data:'connected'));
  (document.body||document.documentElement).appendChild(d);
})();

})();