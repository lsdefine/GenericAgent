#!/usr/bin/env python3
"""
Auto-Summary 单元测试。
"""

import os
import sys
import json
import tempfile
import unittest

# 把代码根加入 path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from auto_summary import (
    _extract_user_text,
    _extract_agent_text,
    _extract_text_from_response,
    _is_low_value,
    _detect_triggers,
    _extract_topic,
    _extract_need,
    _extract_decision,
    _generate_tags,
    _format_entry,
    _last_entry_hash,
    online,
    offline,
    _parse_log_file,
)


class TestExtractUserText(unittest.TestCase):
    """测试从 Prompt JSON 块提取用户文本。"""

    def test_extract_simple(self):
        """简单文本提取。"""
        block = json.dumps({
            'content': [
                {'type': 'text', 'text': '帮我写一个 Python 脚本'},
            ]
        })
        result = _extract_user_text(block)
        self.assertEqual(result, '帮我写一个 Python 脚本')

    def test_extract_multiple_texts(self):
        """多个文本块。"""
        block = json.dumps({
            'content': [
                {'type': 'text', 'text': '第一步'},
                {'type': 'text', 'text': '第二步'},
            ]
        })
        result = _extract_user_text(block)
        self.assertIn('第一步', result)
        self.assertIn('第二步', result)

    def test_ignore_tool_result(self):
        """忽略 tool_result 或其他类型。"""
        block = json.dumps({
            'content': [
                {'type': 'tool_result', 'content': '{}'},
                {'type': 'text', 'text': '用户消息'},
            ]
        })
        result = _extract_user_text(block)
        self.assertEqual(result, '用户消息')

    def test_ignore_system_blocks(self):
        """忽略带 WORKING MEMORY 和 SYSTEM 的文本块。"""
        block = json.dumps({
            'content': [
                {'type': 'text', 'text': '\n### [WORKING MEMORY]\n...'},
                {'type': 'text', 'text': '实际用户消息'},
            ]
        })
        result = _extract_user_text(block)
        self.assertEqual(result, '实际用户消息')

    def test_empty_block(self):
        """空块返回空字符串。"""
        self.assertEqual(_extract_user_text('{}'), '')
        self.assertEqual(_extract_user_text(''), '')
        self.assertEqual(_extract_user_text('not json'), '')


class TestExtractAgentText(unittest.TestCase):
    """测试从 Response 块提取 Agent 文本。"""

    def test_extract_simple(self):
        """简单列表格式。"""
        block = json.dumps([
            {'type': 'text', 'text': '这是回复内容。'}
        ])
        result = _extract_agent_text(block)
        self.assertEqual(result, '这是回复内容。')

    def test_extract_with_thinking(self):
        """混合 thinking 和 text。"""
        block = json.dumps([
            {'type': 'thinking', 'thinking': '内部思考...'},
            {'type': 'text', 'text': '最终回复。'},
        ])
        result = _extract_agent_text(block)
        self.assertEqual(result, '最终回复。')

    def test_extract_multiple_texts(self):
        """多个 text 块。"""
        block = json.dumps([
            {'type': 'text', 'text': '第一段。'},
            {'type': 'text', 'text': '第二段。'},
        ])
        result = _extract_agent_text(block)
        self.assertEqual(result, '第一段。\n第二段。')

    def test_extract_no_text(self):
        """没有 text 块。"""
        block = json.dumps([
            {'type': 'thinking', 'thinking': '思考中'}
        ])
        self.assertEqual(_extract_agent_text(block), '')


class TestExtractTextFromResponse(unittest.TestCase):
    """测试从 LLM response 对象提取文本。"""

    def test_string_response(self):
        """字符串直接返回。"""
        self.assertEqual(_extract_text_from_response('hello'), 'hello')

    def test_dict_response(self):
        """带 content 的 dict 格式。"""
        response = type('Response', (), {'content': 'text content'})()
        self.assertEqual(_extract_text_from_response(response), 'text content')

    def test_list_response(self):
        """带 content list 的格式（类 Anthropic）。"""
        class TextBlock:
            def __init__(self, text):
                self.type = 'text'
                self.text = text
        response = type('Response', (), {'content': [
            TextBlock('hello'),
            TextBlock('world'),
        ]})()
        self.assertEqual(_extract_text_from_response(response), 'hello\nworld')

    def test_dict_list_response(self):
        """content list 中是 dict 格式。"""
        response = type('Response', (), {'content': [
            {'type': 'text', 'text': 'hello'},
            {'type': 'text', 'text': 'world'},
        ]})()
        self.assertEqual(_extract_text_from_response(response), 'hello\nworld')


class TestIsLowValue(unittest.TestCase):
    """测试低价值状态更新过滤。"""

    def test_short_message(self):
        """短消息被认为是低价值。"""
        self.assertTrue(_is_low_value('short'))
        self.assertTrue(_is_low_value(''))

    def test_subagent_status(self):
        """Subagent 状态更新被过滤。"""
        texts = [
            'Subagent 正在工作（Turn 1 已完成环境探测）',
            'Subagent 已到 Turn 4，继续观察完成状态',
            'Subagent 在工作完成中',
        ]
        for t in texts:
            self.assertTrue(_is_low_value(t), f"未过滤: {t}")

    def test_wait_patterns(self):
        """等待/观察模式被过滤。"""
        texts = [
            '接近完成，再等一会儿收结果',
            '等待子任务完成',
            '继续观察完成状态',
        ]
        for t in texts:
            self.assertTrue(_is_low_value(t), f"未过滤: {t}")

    def test_read_complete(self):
        """已读取完毕被过滤。"""
        self.assertTrue(_is_low_value('已读取完毕。以下是内容...'))

    def test_meaningful_text_not_filtered(self):
        """有意义的文本不应被过滤。"""
        texts = [
            '确认执行方案B，开始实现代码吧',  # 15 chars, >= 10 threshold
            '我决定采用Plan Mode来规划任务',
            '重要发现：模型在10轮后开始过拟合',
            '总结一下：这个方案有三个优点',
        ]
        for t in texts:
            self.assertFalse(_is_low_value(t), f"被误过滤: {t}")


class TestDetectTriggers(unittest.TestCase):
    """测试触发条件检测。"""

    def test_detect_decision(self):
        """检测方案选择。"""
        texts = [
            '我选方案A',
            '采用方案B来处理',
            '用方案一二三',
            '就按你说的方案来',
            '走方案C路线',
        ]
        for t in texts:
            tags = _detect_triggers(t)
            self.assertIn('决策:方案选择', tags, f"未检测到决策: {t}")

    def test_detect_confirm(self):
        """检测确认。"""
        texts = [
            '可以，开始执行',
            '确认执行计划',
            '同意，开始实施',
            '就这么办',
            '好，开始吧',
        ]
        for t in texts:
            tags = _detect_triggers(t)
            self.assertIn('决策:确认', tags, f"未检测到确认: {t}")

    def test_detect_completion(self):
        """检测阶段完成。"""
        texts = [
            '任务完成',
            '第一阶段结束',
            '收工',
            '搞定',
            '总结一下方案',
        ]
        for t in texts:
            tags = _detect_triggers(t)
            self.assertIn('阶段完成', tags, f"未检测到完成: {t}")

    def test_detect_fact(self):
        """检测重要事实。"""
        texts = [
            '重要发现：性能提升了50%',
            '关键结论是这个方案可行',
            '教训是不要过早优化',
            '记一下这个参数很重要',
        ]
        for t in texts:
            tags = _detect_triggers(t)
            self.assertIn('重要事实', tags, f"未检测到事实: {t}")

    def test_no_trigger(self):
        """普通文本不应触发。"""
        self.assertEqual(_detect_triggers('今天天气不错'), [])
        self.assertEqual(_detect_triggers('让我先查一下文档'), [])
        self.assertEqual(_detect_triggers('今天天气挺不错的'), [])


class TestExtractTopic(unittest.TestCase):
    """测试话题提取。"""

    def test_from_user_text(self):
        """从用户文本提取话题。"""
        topic = _extract_topic(
            '帮我写一个 Python 脚本处理数据',
            '好的，我来写这个脚本。'
        )
        self.assertIn('Python', topic)

    def test_from_agent_text(self):
        """从 Agent 文本提取话题。"""
        topic = _extract_topic(
            '',
            '<summary>已经完成数据分析。</summary>'
        )
        self.assertEqual(topic, '已经完成数据分析。')

    def test_fallback(self):
        """无有效话题时返回占位。"""
        topic = _extract_topic('', '', '')
        self.assertEqual(topic, '(未能提取话题)')


class TestExtractNeed(unittest.TestCase):
    """测试用户需求提取。"""

    def test_simple_need(self):
        """提取前两句。"""
        need = _extract_need('帮我写个脚本。需要处理 CSV 文件。')
        self.assertIn('帮我写个脚本', need)

    def test_ignore_blocks(self):
        """忽略 JSON 块和摘要标签。"""
        need = _extract_need('{}\n[1,2,3]\n实际需求\n补充说明')
        self.assertIn('实际需求', need)
        self.assertIn('补充说明', need)
        self.assertNotIn('{', need)


class TestExtractDecision(unittest.TestCase):
    """测试决策内容提取。"""

    def test_extract_decision_pattern(self):
        """从方案选择模式提取。"""
        decision = _extract_decision(
            '我选方案B。',
            '好的，开始执行方案B。'
        )
        self.assertTrue(len(decision) > 0)

    def test_extract_confirm(self):
        """从确认模式提取。"""
        decision = _extract_decision(
            '确认执行。',
            '收到，开始执行计划。'
        )
        self.assertIn('确认', decision)

    def test_no_filepath_noise(self):
        """不提取含文件路径的决策。"""
        decision = _extract_decision(
            '读一下 projects/session_index_pr/HANDOFF.md',
            '<summary>用户要求读取一个文件。</summary>'
        )
        # "用户"中的"用"不应触发决策提取
        self.assertEqual(decision, '')

    def test_no_false_positive(self):
        """普通对话不应提取出虚假决策。"""
        decision = _extract_decision(
            '继续推进项目',
            '了解，我来看一下具体方案。'
        )
        self.assertEqual(decision, '')


class TestGenerateTags(unittest.TestCase):
    """测试标签生成。"""

    def test_keyword_tags(self):
        """关键词标签自动追加。"""
        tags = _generate_tags(
            '帮我写一个 Python 脚本处理数据',
            '好的，使用pandas处理',
            ['阶段完成']
        )
        self.assertIn('#数据', tags)

    def test_pr_tag(self):
        """PR 关键词触发 #PR 标签。"""
        tags = _generate_tags(
            '提交一个 PR',
            '',
            []
        )
        self.assertIn('#PR', tags)


class TestFormatEntry(unittest.TestCase):
    """测试 Markdown 格式化。"""

    def test_format_simple(self):
        """基本格式检查。"""
        entry = _format_entry(
            '2026-05-30 12:00',
            '话题',
            '需求',
            '讨论内容',
            '决策内容',
            ['阶段完成', '#代码']
        )
        self.assertIn('2026-05-30 12:00', entry)
        self.assertIn('话题: 话题', entry)
        self.assertIn('用户需求: 需求', entry)
        self.assertIn('讨论内容: 讨论内容', entry)
        self.assertIn('决策: 决策内容', entry)
        self.assertIn('标签: 阶段完成 #代码', entry)

    def test_truncated_discussion(self):
        """讨论内容超长截断。"""
        long_text = 'A' * 250
        entry = _format_entry(
            '2026-05-30 12:00', '话题', '', long_text, '', []
        )
        self.assertIn('...', entry)
        self.assertLess(len(entry), 400)


class TestLastEntryHash(unittest.TestCase):
    """测试去重哈希。"""

    def test_empty_file(self):
        """空文件返回空。"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            f.write('')
            path = f.name
        try:
            self.assertEqual(_last_entry_hash(path), '')
        finally:
            os.unlink(path)

    def test_last_entry(self):
        """返回最后一条内容的前 80 字符。"""
        content = '---\n2026-05-30 12:00\n  话题: test\n  标签: done\n\n'
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            f.write(content)
            path = f.name
        try:
            h = _last_entry_hash(path)
            self.assertTrue(h.startswith('---'), msg=f"Hash starts with: {h[:20]!r}")
        finally:
            os.unlink(path)


class TestOnline(unittest.TestCase):
    """测试在线模式。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmpdir, 'discussion_log.md')

    def tearDown(self):
        if os.path.isfile(self.log_path):
            os.unlink(self.log_path)
        os.rmdir(self.tmpdir)

    def test_decision_triggers_write(self):
        """方案选择触发写入。"""
        result = online(
            user_message='我选方案B，开始实现吧',
            agent_response='好的，开始执行方案B。',
            log_path=self.log_path,
        )
        self.assertTrue(result['written'])
        self.assertIn('决策:方案选择', result['tags'])

    def test_confirm_triggers_write(self):
        """确认触发写入。"""
        result = online(
            user_message='确认执行',
            agent_response='收到，开始执行。',
            log_path=self.log_path,
        )
        self.assertTrue(result['written'])
        self.assertIn('决策:确认', result['tags'])

    def test_completion_triggers_write(self):
        """阶段完成触发写入。"""
        result = online(
            user_message='第一阶段完成',
            agent_response='总结一下成果。',
            log_path=self.log_path,
        )
        self.assertTrue(result['written'])
        self.assertIn('阶段完成', result['tags'])

    def test_low_value_skipped(self):
        """低价值状态更新跳过。"""
        result = online(
            user_message='',
            agent_response='Subagent 正在工作（Turn 1 已完成环境探测）',
            log_path=self.log_path,
        )
        self.assertFalse(result['written'])

    def test_no_trigger_skipped(self):
        """无触发条件时跳过。"""
        result = online(
            user_message='今天天气不错',
            agent_response='是的，适合户外活动。',
            log_path=self.log_path,
        )
        self.assertFalse(result['written'])

    def test_dedup(self):
        """连续相同条目去重。"""
        result1 = online(
            user_message='确认执行方案',
            agent_response='收到。',
            log_path=self.log_path,
        )
        if result1['written']:
            result2 = online(
                user_message='确认执行方案',
                agent_response='收到。',
                log_path=self.log_path,
            )
            self.assertFalse(result2.get('written', False),
                             msg="应检测到重复条目")


class TestParseLogFile(unittest.TestCase):
    """测试日志文件解析。"""

    def _make_log(self, lines: list) -> str:
        """Helper: 创建临时日志文件。"""
        fd, path = tempfile.mkstemp(suffix='.txt', prefix='model_responses_')
        with os.fdopen(fd, 'w') as f:
            f.write('\n'.join(lines))
        return path

    def test_simple_turn(self):
        """解析一个完整的轮次。"""
        prompt = json.dumps({
            'content': [{'type': 'text', 'text': '用户消息'}]
        })
        response = json.dumps([
            {'type': 'text', 'text': 'Agent回复'}
        ])
        log_lines = [
            f'=== Prompt === 2026-05-30 12:00:00',
            prompt,
            '',
            f'=== Response === 2026-05-30 12:00:05',
            response,
        ]
        path = self._make_log(log_lines)
        try:
            turns = _parse_log_file(path)
            self.assertEqual(len(turns), 1)
            self.assertEqual(turns[0]['user_msg'], '用户消息')
            self.assertEqual(turns[0]['agent_msg'], 'Agent回复')
        finally:
            os.unlink(path)

    def test_multiple_turns(self):
        """解析多个轮次。"""
        prompt1 = json.dumps({'content': [{'type': 'text', 'text': '第一轮'}]})
        resp1 = json.dumps([{'type': 'text', 'text': '第一轮回复'}])
        prompt2 = json.dumps({'content': [{'type': 'text', 'text': '第二轮'}]})
        resp2 = json.dumps([{'type': 'text', 'text': '第二轮回复'}])
        log_lines = [
            f'=== Prompt === 2026-05-30 12:00:00',
            prompt1, '',
            f'=== Response === 2026-05-30 12:00:05',
            resp1, '',
            f'=== Prompt === 2026-05-30 12:01:00',
            prompt2, '',
            f'=== Response === 2026-05-30 12:01:05',
            resp2,
        ]
        path = self._make_log(log_lines)
        try:
            turns = _parse_log_file(path)
            self.assertEqual(len(turns), 2)
        finally:
            os.unlink(path)


class TestOfflineIntegration(unittest.TestCase):
    """集成测试：离线模式处理真实日志。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.output = os.path.join(self.tmpdir, 'discussion_log.md')

    def tearDown(self):
        if os.path.isfile(self.output):
            os.unlink(self.output)
        os.rmdir(self.tmpdir)

    def test_process_real_log(self):
        """处理真实日志文件。"""
        # 使用项目目录下的真实日志
        log_dir = os.path.join(
            os.path.dirname(__file__), '..', 'temp', 'model_responses'
        )
        logs = sorted([
            os.path.join(log_dir, f)
            for f in os.listdir(log_dir)
            if f.startswith('model_responses_') and f.endswith('.txt')
        ])
        if not logs:
            self.skipTest("无真实日志文件可用")
        
        result = offline(
            log_path=logs[0],
            output_path=self.output,
        )
        self.assertGreaterEqual(result['turns_analyzed'], 0)
        self.assertGreaterEqual(result['files_scanned'], 1)
        # 可能是0，如果日志中没有触发条件
        self.assertGreaterEqual(result['entries_written'], 0)

    def test_no_logs(self):
        """日志目录不存在时优雅降级。"""
        result = offline(
            log_path='/tmp/nonexistent_log.txt',
            output_path=self.output,
        )
        self.assertEqual(result['files_scanned'], 1)
        self.assertEqual(result['turns_analyzed'], 0)
        self.assertEqual(result['entries_written'], 0)


if __name__ == '__main__':
    unittest.main()
