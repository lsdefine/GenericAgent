import json, re
from dataclasses import dataclass
from typing import Any, Optional
@dataclass
class StepOutcome:
    data: Any
    next_prompt: Optional[str] = None
    should_exit: bool = False

def try_call_generator(func, *args, **kwargs):
    ret = func(*args, **kwargs)
    if hasattr(ret, '__iter__') and not isinstance(ret, (str, bytes, dict, list)):
        ret = yield from ret
    return ret

class BaseHandler:
    def tool_before_callback(self, tool_name, args, response): pass
    def tool_after_callback(self, tool_name, args, response, ret): pass
    def next_prompt_patcher(self, next_prompt, outcome, turn): return next_prompt
    def dispatch(self, tool_name, args, response, index=0):
        method_name = f"do_{tool_name}"
        if hasattr(self, method_name):
            args['_index'] = index
            prer = yield from try_call_generator(self.tool_before_callback, tool_name, args, response)
            ret = yield from try_call_generator(getattr(self, method_name), args, response)
            _ = yield from try_call_generator(self.tool_after_callback, tool_name, args, response, ret)
            return ret
        elif tool_name == 'bad_json':
            return StepOutcome(None, next_prompt=args.get('msg', 'bad_json'), should_exit=False)
        else:
            yield f"未知工具: {tool_name}\n"
            return StepOutcome(None, next_prompt=f"未知工具 {tool_name}", should_exit=False)

def json_default(o):
    if isinstance(o, set): return list(o)
    return str(o) 

def exhaust(g):
    try: 
        while True: next(g)
    except StopIteration as e: return e.value

def get_pretty_json(data):
    if isinstance(data, dict) and "script" in data:
        data = data.copy()
        data["script"] = data["script"].replace("; ", ";\n  ")
    return json.dumps(data, indent=2, ensure_ascii=False).replace('\\n', '\n')

def agent_runner_loop(client, system_prompt, user_input, handler, tools_schema, max_turns=15, verbose=True, initial_user_content=None):
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": initial_user_content if initial_user_content is not None else user_input}
    ]
    for turn in range(max_turns):
        yield f"**LLM Running (Turn {turn+1}) ...**\n\n"
        if (turn+1) % 10 == 0: client.last_tools = ''  # 每10轮重置一次工具描述，避免上下文过大导致的模型性能下降
        response_gen = client.chat(messages=messages, tools=tools_schema)
        if verbose:
            response = yield from response_gen
            yield '\n\n'
        else:
            response = exhaust(response_gen)
            yield response.content

        if not response.tool_calls: tool_calls = [{'tool_name': 'no_tool', 'args': {}}]
        else: tool_calls = [{'tool_name': tc.function.name, 'args': json.loads(tc.function.arguments)}
                          for tc in response.tool_calls]
       
        next_prompt = ""
        for ii, tc in enumerate(tool_calls):
            tool_name, args = tc['tool_name'], tc['args']
            if tool_name == 'no_tool': pass
            else: 
                showarg = get_pretty_json(args)
                if not verbose and len(showarg) > 200: showarg = showarg[:200] + ' ...'
                yield f"🛠️ **正在调用工具:** `{tool_name}`  📥**参数:**\n````text\n{showarg}\n````\n" 
            handler.current_turn = turn + 1
            gen = handler.dispatch(tool_name, args, response, index=ii)
            if verbose:
                yield '`````\n'
                outcome = yield from gen
                yield '`````\n'
            else: outcome = exhaust(gen)

            if outcome.next_prompt is None: return {'result': 'CURRENT_TASK_DONE', 'data': outcome.data}
            if outcome.should_exit: return {'result': 'EXITED', 'data': outcome.data}
            if outcome.next_prompt.startswith('未知工具'): client.last_tools = ''

            if outcome.data is not None: 
                datastr = json.dumps(outcome.data, ensure_ascii=False, default=json_default) if type(outcome.data) in [dict, list] else str(outcome.data) 
                next_prompt += f"<tool_result>\n{datastr}\n</tool_result>\n\n"
            next_prompt += outcome.next_prompt
        next_prompt = handler.next_prompt_patcher(next_prompt, None, turn+1)
        messages = [{"role": "user", "content": next_prompt}]
    return {'result': 'MAX_TURNS_EXCEEDED'}
