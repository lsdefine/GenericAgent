"""Project Mode plugin — 零核心代码改动实现 GA 项目模式。

机制：注册 agent_before hook（agent_loop.py 中每个用户轮触发一次）。
当项目模式激活时，把 L1 层（规则 + 记忆文件指针 + 收尾纪律）追加到最后一条 user message（str 直接拼接，多模态 list 追加 text block）。
两层设计：L1 每轮全量注入（轻量、稳定）；L2 = project_memory.md 全文不注入，
由模型按 L1 中的指针与线索（行数/大小）自行判断是否用 file 工具读取。
利用 messages 是 list 引用的事实，直接 mutate 即反映到真正发给 LLM 的内容。

激活态载体 = 文件锚 temp/.active_project（存当前项目名）。文件驱动，跨轮天生持久。
  - 文件存在且非空 → 项目模式激活
  - 进入：agent 读 project_mode_sop 后写该文件（SOP 指示）
  - 退出：清空/删除该文件

目录约定：
  temp/projects/<项目名>/project_memory.md   单文件全文注入的项目记忆
  temp/projects/<项目名>/                     项目私域文件（todo 等），解决多项目覆盖
"""
import os
import plugins.hooks as hooks

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TEMP = os.path.join(_PROJECT_ROOT, 'temp')
_ANCHOR = os.path.join(_TEMP, '.active_project')


def _active_project():
    """读文件锚，返回当前激活的项目名；未激活返回 None。
    异常不在此捕获——hooks.trigger 统一捕获并打印，保持可观测。"""
    if not os.path.isfile(_ANCHOR):
        return None
    return open(_ANCHOR, encoding='utf-8').read().strip() or None


def _project_dir(name):
    return os.path.join(_TEMP, 'projects', name)


def _mem_path(name):
    return os.path.join(_project_dir(name), 'project_memory.md')


def _memory_stat(name):
    """返回 project_memory.md 的 (存在, 行数, 字节数)，供 L1 指针给模型判断依据。"""
    path = _mem_path(name)
    if os.path.isfile(path):
        data = open(path, encoding='utf-8').read()
        return True, len(data.splitlines()), len(data.encode('utf-8'))
    return False, 0, 0


def _build_injection(name):
    """构造追加到 user message 末尾的内容（两层设计的 L1 层）。

    L1（每轮全量注入）：规范/规则/操作说明 + 记忆文件指针（含行数/大小线索）。
    L2（按需）：project_memory.md 全文不注入，由模型自行判断是否用 file 工具去读。
    """
    pdir = _project_dir(name)
    mem_path = _mem_path(name)
    exists, lines, nbytes = _memory_stat(name)
    if exists and nbytes > 0:
        mem_hint = (
            f"项目全量记忆在 {mem_path}（{lines} 行 / {nbytes} 字节）。"
            f"本轮任务若涉及项目上下文（接续工作、查约定、避坑），先读它再动手；"
            f"若与项目认知无关（闲聊、独立小事），可不读。自行判断。"
        )
    else:
        mem_hint = f"项目记忆 {mem_path} 暂为空（本项目尚无沉淀），无需读取。"
    return (
        f"\n\n---\n"
        f"[PROJECT MODE: {name}]\n"
        f"你正在「{name}」项目模式中。\n\n"
        f"## 规则\n"
        f"- 项目私域目录：{pdir}（todo、草稿、产物一律放这里，勿放 temp 根目录）\n"
        f"- {mem_hint}\n\n"
        f"## 收尾纪律\n"
        f"干完本轮活后自问一个问题：「记忆归零、重新接手本项目的我，缺了本轮哪条信息会重复付出认知代价"
        f"——再踩一次坑、再摸索一次、再问一次用户？」会的，就用 file 工具把那条追加进 {mem_path}，"
        f"写成未来的自己能直接复用的一句话；不会的，一个字都不写。\n"
        f"---"
    )


@hooks.register('agent_before')
def inject_project_context(ctx):
    """每个用户轮起始时，若项目模式激活，把项目上下文追加到 user message。"""
    name = _active_project()
    if not name:
        return  # 未激活，普通模式，什么都不做

    # 从尾部找最后一条 user message（不依赖 messages[1] 的位置约定）
    um = next((m for m in reversed(ctx.get('messages') or [])
               if isinstance(m, dict) and m.get('role') == 'user'), None)
    if um is None:
        return
    content = um.get('content')
    if isinstance(content, str):
        um['content'] = content + _build_injection(name)
    elif isinstance(content, list):  # 多模态：追加 text block
        content.append({'type': 'text', 'text': _build_injection(name)})
