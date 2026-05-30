"""
Auto-Summary Plugin: 通过 hook 系统自动记录关键决策/阶段完成到 discussion_log.md。

安装:
  - 确保 auto_summary.py 在代码根目录
  - 无需修改 agent_loop.py，插件通过 import 自动注册 hook
  - 可通过移除环境变量 AUTO_SUMMARY_DISABLE=1 禁用

工作原理:
  钩在 'turn_after' 事件上，提取用户消息和 Agent 回复，
  调用 auto_summary.online() 检测触发条件并写入 discussion_log.md。
"""

import os
import sys

# 将代码根加入 path（这样能 import auto_summary）
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_CODE_ROOT = os.path.abspath(os.path.join(_SCRIPT_DIR, '..'))
if _CODE_ROOT not in sys.path:
    sys.path.insert(0, _CODE_ROOT)

# 如果设置了禁用环境变量，跳过
if os.environ.get('AUTO_SUMMARY_DISABLE'):
    # 静默跳过
    pass
else:
    import plugins.hooks as hooks
    import auto_summary

    @hooks.register('turn_after')
    def _auto_summary_on_turn_end(ctx):
        """在每次 Agent 轮次结束时检查是否需记录摘要。"""
        try:
            # 提取用户消息
            user_msg = ''
            # 优先用原始的 user_input
            if ctx.get('user_input'):
                user_msg = ctx['user_input']
            # 如果有 next_prompts，用最新的
            next_prompts = ctx.get('next_prompts') or []
            if next_prompts and next_prompts[-1]:
                user_msg = next_prompts[-1]
            
            # 提取 Agent 回复
            response = ctx.get('response')
            
            # 获取轮次和时间
            turn = ctx.get('turn', 0)
            from datetime import datetime
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M')
            
            # 调用 auto_summary.online()
            result = auto_summary.online(
                user_message=user_msg,
                response_obj=response,
                turn=turn,
                timestamp=timestamp,
            )
            
            if result.get('written'):
                tags = ' '.join(result.get('tags', []))
                print(f"[Auto-Summary] ✓ 记录摘要 ({tags})")
            
        except Exception as e:
            # 插件不中断主流程
            print(f"[Auto-Summary] ⚠ 插件异常: {e}")
