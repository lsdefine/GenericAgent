// Disable alert/confirm/prompt to prevent page JS from blocking extension
// Silent mode: only console.log, no DOM toast — 不影响用户浏览（2026-05-16）
(function() {
  const _log = console.log.bind(console);
  window.alert = function(msg) { _log('[TMWD] alert suppressed:', msg); };
  window.confirm = function(msg) { _log('[TMWD] confirm suppressed:', msg); return true; };
  window.prompt = function(msg, def) { _log('[TMWD] prompt suppressed:', msg); return def || null; };
})();
