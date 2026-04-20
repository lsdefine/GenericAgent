"""Opt-in Langfuse tracing. Self-activates on import if langfuse_config exists in mykey.

Hooks only via monkey-patch so core files stay untouched:
- agent_loop.agent_runner_loop        -> outer agent trace (parent of all below)
- llmcore._write_llm_log              -> generation span (Prompt=start, Response=end)
- BaseHandler.tool_before/after       -> tool span
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
    import llmcore, agent_loop
    _tls = threading.local()

    _orig_log = llmcore._write_llm_log
    def _patched_log(label, content):
        try:
            if label == 'Prompt':
                _tls.gen = _lf.start_observation(name='llm.chat', as_type='generation', input=content[:20000])
                _tls.usage = None
            elif label == 'Response' and getattr(_tls, 'gen', None) is not None:
                _tls.gen.update(output=content[:20000], usage_details=getattr(_tls, 'usage', None))
                _tls.gen.end(); _tls.gen = None
        except Exception: pass
        return _orig_log(label, content)
    llmcore._write_llm_log = _patched_log

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
            try: _tls.usage = _extract_usage(buf)
            except Exception: pass
            return ret
        return wrapped
    llmcore._parse_claude_sse = _wrap_parser(llmcore._parse_claude_sse)
    llmcore._parse_openai_sse = _wrap_parser(llmcore._parse_openai_sse)

    _orig_before = agent_loop.BaseHandler.tool_before_callback
    _orig_after = agent_loop.BaseHandler.tool_after_callback

    def _patched_before(self, tool_name, args, response):
        try:
            if not hasattr(_tls, 'tstack'): _tls.tstack = []
            a = {k: v for k, v in args.items() if k != '_index'}
            _tls.tstack.append(_lf.start_observation(name=tool_name, as_type='tool', input=a))
        except Exception: pass
        return _orig_before(self, tool_name, args, response)

    def _patched_after(self, tool_name, args, response, ret):
        try:
            if getattr(_tls, 'tstack', None):
                sp = _tls.tstack.pop()
                out = {'data': ret.data, 'next_prompt': ret.next_prompt, 'should_exit': ret.should_exit} if ret else None
                sp.update(output=out); sp.end()
        except Exception: pass
        return _orig_after(self, tool_name, args, response, ret)

    agent_loop.BaseHandler.tool_before_callback = _patched_before
    agent_loop.BaseHandler.tool_after_callback = _patched_after

    _orig_loop = agent_loop.agent_runner_loop
    def _patched_loop(client, system_prompt, user_input, handler, tools_schema, *a, **kw):
        try: cm = _lf.start_as_current_observation(name='agent.task', as_type='agent', input={'user_input': user_input})
        except Exception: cm = None
        if cm is None:
            ret = yield from _orig_loop(client, system_prompt, user_input, handler, tools_schema, *a, **kw); return ret
        with cm as sp:
            ret = yield from _orig_loop(client, system_prompt, user_input, handler, tools_schema, *a, **kw)
            try: sp.update(output=ret)
            except Exception: pass
        try: _lf.flush()
        except Exception: pass
        return ret
    agent_loop.agent_runner_loop = _patched_loop
    for _m in list(sys.modules.values()):
        if _m and getattr(_m, 'agent_runner_loop', None) is _orig_loop:
            try: setattr(_m, 'agent_runner_loop', _patched_loop)
            except Exception: pass
