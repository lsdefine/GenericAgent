import json
from pathlib import Path
from types import SimpleNamespace

from ga import GenericAgentHandler, _verify_condition


def response(content='done'):
    return SimpleNamespace(content=content, thinking='')


def exhaust(generator):
    try:
        while True: next(generator)
    except StopIteration as result: return result.value


def handler(tmp_path):
    parent = SimpleNamespace(extrakeyinfo=None, intervene=None, task_dir=None, _turn_end_hooks={})
    return GenericAgentHandler(parent, cwd=str(tmp_path))


def test_file_conditions_use_handler_working_directory(tmp_path):
    target = tmp_path / 'report.txt'
    target.write_text('verified output')
    resolve = lambda path: str(tmp_path / path)
    assert _verify_condition({'kind': 'file_exists', 'path': 'report.txt'}, {}, resolve)
    assert _verify_condition({'kind': 'file_contains', 'path': 'report.txt',
                              'substring': 'verified'}, {}, resolve)
    assert not _verify_condition({'kind': 'file_exists'}, {}, resolve)


def test_exit_code_condition_uses_real_code_run_result():
    passed = {'code_run': json.dumps({'status': 'success', 'exit_code': 0})}
    failed = {'code_run': json.dumps({'status': 'error', 'exit_code': 1})}
    condition = {'kind': 'last_exit_code_zero'}
    assert _verify_condition(condition, passed)
    assert not _verify_condition(condition, failed)


def test_tool_result_condition_requires_matching_tool_output():
    condition = {'kind': 'tool_result_contains', 'tool': 'file_read', 'substring': '42 rows'}
    assert _verify_condition(condition, {'file_read': 'exported 42 rows'})
    assert not _verify_condition(condition, {'code_run': 'exported 42 rows'})


def test_unmet_condition_blocks_no_tool_completion(tmp_path):
    agent = handler(tmp_path)
    agent.working['verify_conditions'] = [
        {'kind': 'file_exists', 'path': 'missing.txt', 'description': 'report exists'}]
    for _ in range(6):
        outcome = exhaust(agent.do_no_tool({}, response()))
        assert outcome.next_prompt == '[VERIFY] Completion blocked by unmet conditions:\n- report exists'


def test_tool_result_is_recorded_and_allows_completion(tmp_path):
    agent = handler(tmp_path)
    agent.working['verify_conditions'] = [{'kind': 'last_exit_code_zero'}]
    agent.turn_end_callback(response('<summary>tests ran</summary>'),
                            [{'tool_name': 'code_run', 'id': 'call-1'}],
                            [{'tool_use_id': 'call-1', 'content': json.dumps({'exit_code': 0})}],
                            1, '', {})
    outcome = exhaust(agent.do_no_tool({}, response()))
    assert outcome.next_prompt is None


def test_checkpoint_registers_conditions(tmp_path):
    agent = handler(tmp_path); agent.current_turn = 2
    conditions = [{'kind': 'file_exists', 'path': 'report.txt'}]
    exhaust(agent.do_update_working_checkpoint({'verify_conditions': conditions}, response()))
    assert agent.working['verify_conditions'] == conditions


def test_conditions_are_exposed_in_both_tool_schemas():
    for path in ('assets/tools_schema.json', 'assets/tools_schema_cn.json'):
        schema = json.loads(Path(path).read_text())
        checkpoint = next(tool['function'] for tool in schema
                          if tool['function']['name'] == 'update_working_checkpoint')
        assert 'verify_conditions' in checkpoint['parameters']['properties']
