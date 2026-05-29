"""Langfuse tracing via hook system. Self-activates on import if langfuse_config exists in mykey.

Replaces old monkey-patch approach with hooks on:
  - agent_before / agent_after  -> agent trace
  - llm_before / llm_after    -> generation span
  - tool_before / tool_after  -> tool span

Usage tracking (SSE parser wrapping) stays as internal llmcore patch.
"""
import threading, sys

try:
    from llmcore import _load_mykeys
    _cfg = _load_mykeys().get('langfuse_config')
    from langfuse import Langfuse
    _lf = Langfuse(**_cfg) if _cfg else None
except Exception:
    _lf = None

if _lf:
    import plugins.hooks as hooks, llmcore
    _tls = threading.local()

    # ── Agent trace ──────────────────────────────────────────────

    @hooks.register('agent_before')
    def _on_agent_before(ctx):
        try:
            _tls.trace_obs = _lf.start_observation(
                name='agent.task', as_type='agent',
                input={'user_input': ctx.get('user_input', '')})
        except Exception:
            _tls.trace_obs = None

    @hooks.register('agent_after')
    def _on_agent_after(ctx):
        try:
            obs = getattr(_tls, 'trace_obs', None)
            if obs:
                obs.update(output=ctx.get('exit_reason'))
                obs.end()
                _tls.trace_obs = None
            _lf.flush()
        except Exception:
            pass

    # ── LLM generation span (replaces _write_llm_log patch) ─────

    @hooks.register('llm_before')
    def _on_llm_before(ctx):
        try:
            _tls.gen = _lf.start_observation(
                name='llm.chat', as_type='generation',
                input=str(ctx.get('messages', ''))[:20000])
            _tls._usage = None
        except Exception:
            _tls.gen = None

    @hooks.register('llm_after')
    def _on_llm_after(ctx):
        try:
            gen = getattr(_tls, 'gen', None)
            if gen:
                gen.update(output=str(ctx.get('response', ''))[:20000],
                           usage_details=getattr(_tls, '_usage', None))
                gen.end()
                _tls.gen = None
        except Exception:
            pass

    # ── Tool spans (replaces tool_before/after_callback patches) ─

    @hooks.register('tool_before')
    def _on_tool_before(ctx):
        try:
            name = ctx.get('tool_name', '?')
            args = {k: v for k, v in (ctx.get('args') or {}).items() if not k.startswith('_')}
            if not hasattr(_tls, 'tstack'): _tls.tstack = []
            _tls.tstack.append(_lf.start_observation(name=name, as_type='tool', input=args))
        except Exception:
            pass

    @hooks.register('tool_after')
    def _on_tool_after(ctx):
        try:
            stack = getattr(_tls, 'tstack', [])
            if stack:
                sp = stack.pop()
                ret = ctx.get('ret')
                out = {'data': ret.data, 'next_prompt': ret.next_prompt,
                       'should_exit': ret.should_exit} if ret else None
                sp.update(output=out); sp.end()
        except Exception:
            pass

    # ── Usage tracking: tee SSE data for token counts ───────────

    def _extract_usage(buf):
        u = {}
        import json as _j
        for line in buf:
            s = line.decode('utf-8', 'replace') if isinstance(line, (bytes, bytearray)) else line
            if not s or not s.startswith('data:'): continue
            ds = s[5:].lstrip()
            if ds == '[DONE]': continue
            try: evt = _j.loads(ds)
            except: continue
            if evt.get('type') == 'message_start':
                us = evt.get('message', {}).get('usage', {}) or {}
                u['input'] = us.get('input_tokens', u.get('input', 0))
                if us.get('cache_creation_input_tokens'): u['cache_creation_input_tokens'] = us['cache_creation_input_tokens']
                if us.get('cache_read_input_tokens'): u['cache_read_input_tokens'] = us['cache_read_input_tokens']
            elif evt.get('type') == 'message_delta':
                ot = (evt.get('usage') or {}).get('output_tokens')
                if ot: u['output'] = ot
            elif evt.get('type') == 'response.completed':
                us = evt.get('response', {}).get('usage', {}) or {}
                if us.get('input_tokens'): u['input'] = us['input_tokens']
                if us.get('output_tokens'): u['output'] = us['output_tokens']
                cr = (us.get('input_tokens_details') or {}).get('cached_tokens')
                if cr: u['cache_read_input_tokens'] = cr
            else:
                us = evt.get('usage')
                if us:
                    if us.get('prompt_tokens'): u['input'] = us['prompt_tokens']
                    if us.get('completion_tokens'): u['output'] = us['completion_tokens']
                    cr = (us.get('prompt_tokens_details') or {}).get('cached_tokens')
                    if cr: u['cache_read_input_tokens'] = cr
        return u or None

    def _wrap_parser(orig):
        def wrapped(resp_lines, *a, **kw):
            buf = []
            def tee():
                for ln in resp_lines:
                    buf.append(ln); yield ln
            ret = yield from orig(tee(), *a, **kw)
            try:
                _tls._usage = _extract_usage(buf)
            except Exception:
                pass
            return ret
        return wrapped

    llmcore._parse_claude_sse = _wrap_parser(llmcore._parse_claude_sse)
    llmcore._parse_openai_sse = _wrap_parser(llmcore._parse_openai_sse)