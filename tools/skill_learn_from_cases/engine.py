"""
engine.py -- skill_learn_from_cases 核心引擎

5 阶段流程编排：
  Phase 0: 启动 + 目录创建
  Phase 1: 技能定义（skill_search 查前置知识）
  Phase 2: 案例搜索（skill_search + Web Search）
  Phase 3: 分析提炼知识模式
  Phase 4: 构建验证工具
  Phase 5: 运行验证 -> 出报告
"""

import sys
import os
import json
import subprocess
from pathlib import Path

# -- 项目路径 --
GA_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(GA_ROOT))
sys.path.insert(0, str(GA_ROOT / "memory" / "skill_search"))

from tools.skill_learn_from_cases import dir_manager


def _import_skill_search():
    """延迟导入 skill_search，失败时降级"""
    try:
        from skill_search import search
        return search
    except Exception:
        return None


def _import_web_search():
    """导入搜索引擎模块，通过环境变量 SEARCH_ENGINE_MODULE 配置"""
    import importlib
    import os
    module_name = os.environ.get("SEARCH_ENGINE_MODULE")
    func_name = os.environ.get("SEARCH_ENGINE_FUNC", "search")
    if not module_name:
        return None
    try:
        mod = importlib.import_module(module_name)
        return getattr(mod, func_name)
    except Exception:
        return None


def _detect_docker():
    """检测 Docker 是否可用"""
    try:
        r = subprocess.run(
            ["wsl.exe", "--exec", "bash", "-c", "docker --version 2>/dev/null"],
            capture_output=True, text=True, timeout=10
        )
        if r.returncode == 0 and r.stdout.strip():
            ver = r.stdout.strip()
        else:
            # 尝试直接运行
            r2 = subprocess.run(
                ["docker", "--version"],
                capture_output=True, text=True, timeout=5
            )
            ver = r2.stdout.strip()
        return ver if ver else None
    except Exception:
        return None


# ===============================================================
# Phase 0: 启动
# ===============================================================

def _phase0_bootstrap(skill_name: str) -> dict:
    """启动环境 + 创建 revN 目录"""
    print(f"\n{'='*55}")
    print(f"  skill_learn_from_cases(\"{skill_name}\")")
    print(f"{'='*55}")

    # 已有版本
    versions = dir_manager.get_versions(skill_name)
    if versions:
        print(f"  已有版本: rev{', rev'.join(map(str, versions))}")
    else:
        print(f"  新技能，无历史版本")

    # 创建新目录
    ver = dir_manager.next_version(skill_name)
    rev_dir = dir_manager.create_revision_dir(skill_name, ver)
    print(f"  创建: rev{ver}/")

    # 继承上一版模式
    inherited_patterns = dir_manager.get_latest_patterns(skill_name)
    if inherited_patterns:
        patterns_file = rev_dir / "patterns" / "knowledge_patterns.json"
        with open(patterns_file, "w", encoding="utf-8") as f:
            json.dump(inherited_patterns, f, indent=2, ensure_ascii=False)
        print(f"  继承: {len(inherited_patterns)} 个知识模式")
    else:
        print(f"  无继承模式")

    # 探测 Docker
    docker_ver = _detect_docker()
    if docker_ver:
        print(f"  Docker: [OK] {docker_ver}")
    else:
        print(f"  Docker: [FAIL] 不可用（compose 语法校验将跳过）")

    return {
        "skill_name": skill_name,
        "version": ver,
        "rev_dir": rev_dir,
        "docker_ver": docker_ver,
        "inherited_patterns": inherited_patterns
    }


# ===============================================================
# Phase 1: 技能定义
# ===============================================================

def _phase1_define(ctx: dict):
    """定义技能：查 skill hub 获取前置知识"""
    print(f"\n{'-'*55}")
    print("  Phase 1: 技能定义")
    print(f"{'-'*55}")

    # 从技能名称推断
    name_clean = ctx["skill_name"].replace("_", " ").title()
    ctx["skill_definition"] = {
        "name": ctx["skill_name"],
        "display_name": name_clean,
        "prerequisites": [],
        "description": f"通过案例学习 {name_clean}",
    }
    print(f"  技能: {name_clean}")

    # 尝试用 skill_search 获取更精确的定义
    search_fn = _import_skill_search()
    if search_fn:
        try:
            results = search_fn(name_clean, top_k=3)
            if results:
                tags = []
                for r in results:
                    if hasattr(r, 'skill') and hasattr(r.skill, 'tags'):
                        tags.extend(r.skill.tags or [])
                    desc = getattr(r, 'skill', None)
                    if desc and getattr(desc, 'description', None):
                        ctx["skill_definition"]["description"] = desc.description[:200]
                ctx["skill_definition"]["related_tags"] = list(set(tags))[:10]
                print(f"  Skill Hub: {len(results)} 条相关技能卡")
        except Exception as e:
            print(f"  Skill Hub: [!] {e}")

    # 写入定义
    def_file = ctx["rev_dir"] / "reports" / "skill_definition.json"
    with open(def_file, "w", encoding="utf-8") as f:
        json.dump(ctx["skill_definition"], f, indent=2, ensure_ascii=False)
    print(f"  [OK] 定义已保存")


# ===============================================================
# Phase 2: 案例搜索
# ===============================================================

def _phase2_search(ctx: dict):
    """双渠道搜索案例"""
    print(f"\n{'-'*55}")
    print("  Phase 2: 案例搜索")
    print(f"{'-'*55}")

    all_cases = []

    # 渠道 A: Skill Hub
    search_fn = _import_skill_search()
    if search_fn:
        try:
            results = search_fn(ctx["skill_name"].replace("_", " "), top_k=10)
            skill_cases = []
            for r in results:
                s = r.skill
                skill_cases.append({
                    "source": "skill_hub",
                    "key": s.key,
                    "description": (s.description[:300] if s.description else ""),
                    "tags": s.tags[:5] if s.tags else [],
                    "score": r.final_score
                })
            all_cases.extend(skill_cases)
            print(f"  Skill Hub: {len(skill_cases)} 条")
        except Exception as e:
            print(f"  Skill Hub: [FAIL] {e}")

    # 渠道 B: Web 搜索
    search_engine = _import_web_search()
    if search_engine:
        try:
            queries = [
                f"{ctx['skill_name'].replace('_',' ')} best practices 2025",
                f"{ctx['skill_name'].replace('_',' ')} 实战 经验",
                f"{ctx['skill_name'].replace('_',' ')} production 案例"
            ]
            web_cases = []
            for q in queries:
                results = search_engine(q, size=5)
                for r in results:
                    web_cases.append({
                        "source": "web",
                        "title": r.get("title", ""),
                        "url": r.get("url", ""),
                        "snippet": r.get("snippet", "")[:200]
                    })
            all_cases.extend(web_cases)
            print(f"  Web: {len(web_cases)} 条")
        except Exception as e:
            print(f"  Web: [FAIL] {e}")
    else:
        print(f"  Web: [FAIL] 搜索引擎不可用")

    # 继承上一版案例
    inherited_cases = dir_manager.get_latest_cases(ctx["skill_name"])
    if inherited_cases:
        # 去重（按 URL/Key 去重）
        seen_keys = set()
        for c in all_cases:
            key = c.get("url") or c.get("key") or ""
            seen_keys.add(key)
        for c in inherited_cases:
            key = c.get("url") or c.get("key") or ""
            if key and key not in seen_keys:
                all_cases.append(c)
                seen_keys.add(key)
        print(f"  继承上一版: +{len(inherited_cases)} 条（去重后）")

    # 保存
    cases_file = ctx["rev_dir"] / "cases" / "all_cases.json"
    with open(cases_file, "w", encoding="utf-8") as f:
        json.dump(all_cases, f, indent=2, ensure_ascii=False)
    ctx["cases"] = all_cases
    print(f"  合计: {len(all_cases)} 条案例")
    print(f"  [OK] 已保存")


# ===============================================================
# Phase 3: 分析提炼知识模式
# ===============================================================

def _extract_patterns_from_cases(cases: list[dict], skill_name: str) -> list[dict]:
    """从案例中提取知识模式（关键词匹配 + 启发式 + 技能感知）"""
    # ── 通用模式关键词库（基础设施相关，对所有技能适用） ──
    generic_patterns = {
        "production": {
            "keywords": ["production", "deploy", "prod", "release","deployment"],
            "principles": [
                ("使用环境变量/配置文件分离环境差异", "P_env_separation", 89),
                ("固定版本号避免意外升级", "P_pin_version", 94),
                ("资源限制防止单服务耗尽", "P_resource_limits", 85),
            ]
        },
        "reliability": {
            "keywords": ["restart", "health", "monitor", "recover", "resilient"],
            "principles": [
                ("配置重启策略确保服务自动恢复", "P_restart", 92),
                ("添加健康检查机制确保服务可用", "P_healthcheck", 88),
                ("配置日志轮转防止磁盘爆满", "P_logging", 90),
            ]
        },
        "testing_config": {
            "keywords": ["test", "validate", "config", "verify", "lint"],
            "principles": [
                ("部署前验证配置文件正确性", "P_config_validation", 93),
            ]
        },
    }

    # ── 技能领域模式库（按技能名和案例内容自动匹配） ──
    skill_domain_patterns = {
        "async": {
            "keywords": ["async", "asyncio", "await", "coroutine", "event loop",
                         "异步", "协程", "concurrent", "parallel", "非阻塞"],
            "principles": [
                ("使用 async/await 而非回调模式", "P_async_await", 93),
                ("避免在异步中使用阻塞 IO 操作", "P_async_no_block", 92),
                ("使用 asyncio 正确管理事件循环", "P_async_event_loop", 91),
                ("合理使用 asyncio.gather 并发执行", "P_async_gather", 89),
                ("掌握异步编程核心模式", "P_async_patterns", 88),
                ("使用 asyncio.Semaphore 控制并发数", "P_async_semaphore", 85),
                ("使用 asyncio.TaskGroup 管理任务生命周期", "P_async_taskgroup", 87),
                ("使用 asyncio.timeout 设置超时控制", "P_async_timeout", 86),
                ("使用 asyncio.Queue 实现生产者消费者模式", "P_async_queue", 84),
                ("使用异步上下文管理器处理资源释放", "P_async_context", 83),
                ("使用 asyncio.create_task 启动后台任务", "P_async_createtask", 82),
                ("使用 asyncio.as_completed 处理最先完成的任务", "P_async_ascompleted", 80),
            ]
        },
        "performance": {
            "keywords": ["performance", "optimize", "profiling", "benchmark", "speed",
                         "性能", "优化", "cProfile", "memory", "latency", "throughput"],
            "principles": [
                ("使用 cProfile/py-spy 定位性能瓶颈", "P_perf_profiling", 90),
                ("使用 LRU/本地缓存减少重复计算", "P_perf_cache", 87),
                ("批量操作代替逐条处理", "P_perf_batch", 86),
                ("使用 local cache/redis 缓存热点数据", "P_perf_cache_strategy", 85),
                ("数据库查询优化(N+1, 索引, 连接池)", "P_perf_db_query", 88),
            ]
        },
        "fastapi": {
            "keywords": ["fastapi", "api", "endpoint", "middleware", "rest"],
            "principles": [
                ("使用异步路由处理 IO 密集型请求", "P_fastapi_async", 90),
                ("合理使用依赖注入管理资源", "P_fastapi_di", 85),
                ("配置请求验证(Pydantic模型)", "P_fastapi_validation", 88),
            ]
        },
        "web_scraping": {
            "keywords": ["scraping", "crawl", "爬虫", "request", "fetch", "http"],
            "principles": [
                ("异步批量请求避免串行等待", "P_scrape_async_batch", 90),
                ("使用连接池复用 TCP 连接", "P_scrape_conn_pool", 85),
                ("添加退避重试机制应对限流", "P_scrape_retry", 88),
            ]
        },
        "kubernetes": {
            "keywords": ["kubernetes", "k8s", "pod", "deployment", "service", "ingress", "helm",
                         "容器编排", "container orchestration", "kubectl",
                         "namespace", "configmap", "statefulset", "daemonset", "hpa"],
            "principles": [
                ("使用 Deployment + ReplicaSet 管理无状态服务", "P_k8s_deployment", 92),
                ("使用 Service + Ingress 暴露服务", "P_k8s_service_ingress", 90),
                ("使用 ConfigMap + Secret 管理配置", "P_k8s_config", 90),
                ("使用 PV/PVC 管理持久化存储", "P_k8s_storage", 88),
                ("使用 HPA 实现自动扩缩容", "P_k8s_hpa", 85),
                ("使用 Namespace 做多环境隔离", "P_k8s_namespace", 85),
                ("使用 Readiness/Liveness Probe 确保服务健康", "P_k8s_probe", 90),
                ("使用 Helm Charts 管理复杂部署", "P_k8s_helm", 82),
                ("使用 RBAC 实现权限控制", "P_k8s_rbac", 85),
                ("使用 NetworkPolicy 实现网络隔离", "P_k8s_network_policy", 82),
            ]
        },
        "database": {
            "keywords": ["database", "数据库", "sql", "mysql", "postgresql", "mongodb",
                         "redis", "query", "查询", "migration", "迁移",
                         "orm", "sqlalchemy", "connection pool", "connection pooling",
                         "index", "索引", "transaction", "事务",
                         "backup", "备份", "replica", "sharding", "分库分表"],
            "principles": [
                ("使用连接池管理数据库连接", "P_db_conn_pool", 90),
                ("合理设计索引提升查询性能", "P_db_index", 92),
                ("使用 ORM 管理数据库迁移", "P_db_migration", 87),
                ("避免 N+1 查询问题", "P_db_n_plus_one", 90),
                ("读写分离提升吞吐量", "P_db_read_write", 85),
                ("定期备份和验证恢复流程", "P_db_backup", 88),
                ("使用 EXPLAIN 分析查询执行计划", "P_db_explain", 90),
                ("合理使用 CTE 代替子查询提升可读性", "P_db_cte", 83),
                ("窗口函数优化分组聚合查询", "P_db_window", 85),
                ("正确使用 JOIN 类型避免笛卡尔积", "P_db_join", 88),
                ("使用事务保证数据一致性(ACID)", "P_db_transaction", 90),
                ("分批处理大数据量操作避免锁表", "P_db_batch", 86),
            ]
        },
        "frontend_react": {
            "keywords": ["react", "vue", "frontend", "前端", "component", "组件",
                         "hook", "hooks", "jsx", "state", "props", "redux", "typescript"],
            "principles": [
                ("使用函数组件 + Hooks 替代类组件", "P_react_hooks", 90),
                ("合理拆分组件保持单一职责", "P_react_component", 88),
                ("使用 React.memo/useMemo 避免不必要渲染", "P_react_memo", 86),
                ("状态管理: 避免 prop drilling，使用 Context/Redux", "P_react_state", 85),
                ("使用 TypeScript 提升代码健壮性", "P_react_typescript", 87),
                ("代码分割 + 懒加载优化首屏性能", "P_react_lazy", 85),
            ]
        },
        "git": {
            "keywords": ["git", "version control", "版本控制", "branch", "分支",
                         "merge", "rebase", "ci/cd", "pipeline", "github actions"],
            "principles": [
                ("使用 Git Flow 或 Trunk-Based 分支策略", "P_git_branch", 88),
                ("提交信息规范(Conventional Commits)", "P_git_commit", 85),
                ("使用 CI/CD 自动化测试和部署", "P_git_cicd", 90),
                ("PR/MR 代码审查流程", "P_git_review", 86),
                ("使用 rebase 保持提交历史整洁", "P_git_rebase", 82),
                ("cherry-pick 选择性合并特定提交", "P_git_cherry", 80),
                ("git bisect 二分查找引入 bug 的提交", "P_git_bisect", 78),
                ("使用 git hooks 自动化代码检查", "P_git_hooks", 84),
                ("git stash 暂存未完成的工作", "P_git_stash", 82),
                ("子模块管理(submodule)多仓库项目", "P_git_submodule", 76),
                ("git tag 版本标记与发布管理", "P_git_tag", 83),
                ("解决合并冲突的策略和技巧", "P_git_conflict", 87),
            ]
        },
        "testing": {
            "keywords": ["test", "testing", "测试", "unit test", "pytest", "unittest",
                         "integration", "集成测试", "tdd", "mock", "coverage"],
            "principles": [
                ("使用 pytest 编写单元测试", "P_test_pytest", 90),
                ("使用 Mock 隔离外部依赖", "P_test_mock", 87),
                ("测试覆盖核心逻辑和边界情况", "P_test_coverage", 88),
                ("集成测试验证组件间协作", "P_test_integration", 85),
            ]
        },
        "networking": {
            "keywords": ["network", "网络", "tcp", "http", "dns", "load balancer",
                         "负载均衡", "firewall", "防火墙", "proxy", "代理", "ssl", "tls"],
            "principles": [
                ("合理规划网络拓扑和安全策略", "P_net_topology", 85),
                ("使用 CDN 加速静态内容分发", "P_net_cdn", 82),
                ("配置负载均衡实现高可用", "P_net_lb", 88),
                ("使用 HTTPS/TLS 加密传输", "P_net_tls", 92),
            ]
        },
    }

    # ── 合并文本用于匹配 ──
    all_text = ""
    for c in cases:
        text = " ".join(str(v) for v in c.values() if isinstance(v, str))
        all_text += text.lower() + " "

    patterns = []
    seen_ids = set()

    # 匹配通用模式
    for category, info in generic_patterns.items():
        for kw in info["keywords"]:
            if kw in all_text:
                for principle, pid, conf in info["principles"]:
                    if pid not in seen_ids:
                        patterns.append({"id": pid, "principle": principle, "confidence": conf, "level": "basic"})
                        seen_ids.add(pid)
                break

    # 匹配技能领域模式：技能名 + 案例内容
    skill_keywords = skill_name.lower().replace("_", " ").replace("-", " ")
    matched_domains = set()
    for domain, info in skill_domain_patterns.items():
        # 技能名匹配
        if domain in skill_keywords:
            matched_domains.add(domain)
            continue
        # 关键词匹配
        for kw in info["keywords"]:
            if kw in all_text or kw in skill_keywords:
                matched_domains.add(domain)
                break

    for domain in matched_domains:
        for principle, pid, conf in skill_domain_patterns[domain]["principles"]:
            if pid not in seen_ids:
                patterns.append({"id": pid, "principle": principle, "confidence": conf, "level": "advanced"})
                seen_ids.add(pid)

    # ── 从案例标题启发式提取（作为补充） ──
    for c in cases:
        title = (c.get("title") or c.get("key") or "").lower()
        desc = (c.get("description") or c.get("snippet") or "").lower()
        combined = title + " " + desc
        # 匹配到但未覆盖的模式ID前缀
        if not patterns:
            # 完全没匹配到任何模式时，生成一个兜底模式
            break

    # 仍然无匹配时生成默认模式
    if not patterns:
        skill_words = skill_keywords.split()
        clean_name = " ".join(w.capitalize() for w in skill_words[:3])
        patterns.append({
            "id": "P_skill_basics",
            "principle": f"掌握 {clean_name} 核心概念和最佳实践",
            "confidence": 80,
            "level": "basic"
        })

    # 排序
    patterns.sort(key=lambda x: x.get("confidence", 0), reverse=True)
    return patterns


def _phase3_analyze(ctx: dict):
    """Phase 3: 分析提炼知识模式"""
    print(f"\n{'-'*55}")
    print("  Phase 3: 模式提炼")
    print(f"{'-'*55}")

    cases = ctx.get("all_cases", [])
    skill_name = ctx["skill_name"]
    patterns = _extract_patterns_from_cases(cases, skill_name)

    # 合并历史模式（如果有继承）
    existing = ctx.get("inherited_patterns", [])
    existing_ids = {p["id"] for p in existing}
    merged = list(existing)
    for p in patterns:
        if p["id"] not in existing_ids:
            merged.append(p)
            existing_ids.add(p["id"])

    merged.sort(key=lambda x: x.get("confidence", 0), reverse=True)

    patterns_file = ctx["rev_dir"] / "patterns" / "knowledge_patterns.json"
    with open(patterns_file, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2, ensure_ascii=False)
    ctx["patterns"] = merged

    print(f"  继承: {len(existing)} 个")
    print(f"  新增: {len(patterns)} 个")
    print(f"  总计: {len(merged)} 个")
    for p in merged[:5]:
        print(f"    [{p.get('confidence',0)}%] {p['principle'][:50]}")
    if len(merged) > 5:
        print(f"    ... 还有 {len(merged)-5} 个")
    print(f"  [OK] 已保存")

# ===============================================================
# Phase 4: 构建验证工具
# ===============================================================

# 验证工具模板
# ── 验证工具模板（外部文件） ──
TEMPLATE_FILE = Path(__file__).parent / 'assess_template.py'



def _phase4_build_tool(ctx: dict):
    """生成验证工具"""
    print(f"\n{'-'*55}")
    print("  Phase 4: 构建验证工具")
    print(f"{'-'*55}")

    patterns = ctx.get("patterns", [])
    patterns_json = json.dumps(patterns, indent=2, ensure_ascii=False)

    # 从外部模板文件读取
    template_file = Path(__file__).parent / 'assess_template.py'
    tool_code = template_file.read_text(encoding='utf-8')
    tool_code = tool_code.replace("__VERSION__", str(ctx["version"]))
    tool_code = tool_code.replace("__SKILL__", ctx["skill_name"])
    tool_code = tool_code.replace("__SKILL_DISPLAY__",
        ctx.get("skill_definition", {}).get("display_name", ctx["skill_name"]))
    tool_code = tool_code.replace("__PATTERNS_JSON__", patterns_json)

    tool_file = ctx["rev_dir"] / "tools" / "assess.py"
    with open(tool_file, "w", encoding="utf-8") as f:
        f.write(tool_code)

    # 语法检查
    try:
        compile(tool_code, str(tool_file), "exec")
        print(f"  [OK] 工具已创建: tools/assess.py (语法检查通过)")
    except SyntaxError as e:
        print(f"  [!]  工具已创建，但语法检查失败: {e}")

    ctx["tool_file"] = tool_file

    # ── 技能专属实操测试：检测是否有匹配的 practical hook ──
    skill_lower = ctx["skill_name"].lower()
    hooks_dir = Path(__file__).parent / "practical_hooks"
    hook_file = None

    # 关键词匹配规则（按特异性从高到低）
    for keyword, hook_name in [
        ("docker", "docker_compose.py"),
        ("compose", "docker_compose.py"),
        ("container", "docker_compose.py"),
        ("sql", "sql.py"),          # SQL/数据库技能 → SQLite 查询验证
        ("database", "sql.py"),
        ("mysql", "sql.py"),
        ("postgres", "sql.py"),
        ("git", "git.py"),              # Git 技能 → Git 仓库操作验证
        ("async", "python_async.py"),   # Python async 技能 → 异步代码执行
        ("asyncio", "python_async.py"),
    ]:
        if keyword in skill_lower:
            hook_file = hooks_dir / hook_name
            if hook_file.exists():
                break

    if hook_file and hook_file.exists():
        practical_target = ctx["rev_dir"] / "tools" / "practical_test.py"
        import shutil
        shutil.copy2(str(hook_file), str(practical_target))
        print(f"  [OK] 实操测试已添加: practical_test.py ({hook_file.name})")
        ctx["has_practical"] = True
    else:
        ctx["has_practical"] = False



# ===============================================================
# Phase 5: 运行验证
# ===============================================================

def _phase5_validate(ctx: dict):
    """运行验证工具"""
    print(f"\n{'-'*55}")
    print("  Phase 5: 运行验证")
    print(f"{'-'*55}")

    tool_file = ctx.get("tool_file")
    if not tool_file or not tool_file.exists():
        print("  [FAIL] 验证工具不存在")
        return

    # 直接在本 Python 进程中运行
    try:
        sys.path.insert(0, str(tool_file.parent))
        result = subprocess.run(
            [sys.executable, str(tool_file)],
            capture_output=True, text=True, timeout=30
        )
        print(result.stdout)
        if result.stderr:
            print(f"  [stderr]: {result.stderr[:200]}")
    except subprocess.TimeoutExpired:
        print("  [!]  验证超时")
    except Exception as e:
        print(f"  [!]  运行失败: {e}")

    # 读取报告
    report_file = ctx["rev_dir"] / "reports" / "assessment.json"
    if report_file.exists():
        with open(report_file, encoding="utf-8") as f:
            report = json.load(f)
        ctx["assessment"] = report
        passed = report.get("passed", False)
        score = report.get("final_score", 0)
        print(f"\n  {'='*55}")
        print(f"  rev{ctx['version']} {'[OK] PASS' if passed else '[FAIL] FAIL'} ({score}/100)")
        print(f"  {'='*55}")

        # 更新 meta.json
        meta_file = ctx["rev_dir"] / "meta.json"
        if meta_file.exists():
            with open(meta_file, encoding="utf-8") as f:
                meta = json.load(f)
            meta["status"] = "passed" if passed else "failed"
            meta["score"] = score
            with open(meta_file, "w", encoding="utf-8") as f:
                json.dump(meta, f, indent=2)
    else:
        print("  [!]  未生成验证报告")


# ===============================================================
# 主入口
# ===============================================================

def learn_skill(skill_name: str):
    """
    案例驱动技能学习完整流程

    用法:
        learn_skill("docker_compose_production")
    """
    ctx = {}

    try:
        ctx = _phase0_bootstrap(skill_name)
        _phase1_define(ctx)
        _phase2_search(ctx)
        _phase3_analyze(ctx)
        _phase4_build_tool(ctx)
        _phase5_validate(ctx)
    except KeyboardInterrupt:
        print("\n  NO_ENTRY 用户中断")
        return
    except Exception as e:
        print(f"\n  [FAIL] 流程异常: {e}")
        import traceback
        traceback.print_exc()
        return

    # 输出总结
    assessment = ctx.get("assessment", {})
    print(f"\n  [CHART] 总结: rev{ctx.get('version','?')} | "
          f"模式: {len(ctx.get('patterns',[]))}个 | "
          f"评分: {assessment.get('final_score','?')}/100")
    print(f"  目录: {ctx.get('rev_dir','')}")
