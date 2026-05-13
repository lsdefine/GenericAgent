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
from tools.skill_learn_from_cases.restore_funcs import _import_skill_search, _import_web_search, _web_search_wikipedia


def _detect_docker():
    """检测 Docker 是否可用"""
    try:
        r = subprocess.run(
            ["wsl.exe", "--exec", "bash", "-c", "docker --version 2>/dev/null"],
            capture_output=True, text=True, timeout=10
        )
        if r.returncode == 0 and r.stdout.strip():
            ver = r.stdout.strip()
            print(f"  Docker: [OK] {ver}")
            return ver
    except Exception:
        pass

    
    return None


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
    
    # 尝试用 Web 搜索增强定义（含 Wikipedia fallback）
    web_fn = _import_web_search()
    wiki_fn = None
    try:
        from tools.skill_learn_from_cases.engine import _web_search_wikipedia as wiki_fn
    except Exception:
        pass
    snippets = []
    if web_fn:
        try:
            web_results = web_fn(keyword=name_clean, size=3)
            if web_results and isinstance(web_results, list):
                for r in web_results[:3]:
                    s = r.get("snippet", "") or r.get("summary", "") or ""
                    if s:
                        snippets.append(s[:200])
                if snippets:
                    brief = "；".join(snippets)[:300]
                    ctx["skill_definition"]["description"] = brief
                    ctx["skill_definition"]["web_summary"] = brief
                    print(f"  Web 摘要: {len(snippets)} 条")
        except Exception:
            pass
    
    # ── 搜索引擎无结果时，Wikipedia 降级 ├────
    if not snippets and wiki_fn:
        try:
            wiki_results = wiki_fn(keyword=name_clean, size=3)
            if wiki_results:
                for r in wiki_results[:3]:
                    s = r.get("snippet", "") or ""
                    if s:
                        snippets.append(s[:200])
                if snippets:
                    brief = "；".join(snippets)[:300]
                    ctx["skill_definition"]["description"] = brief
                    ctx["skill_definition"]["wiki_summary"] = brief
                    print(f"  Wikipedia 摘要: {len(snippets)} 条")
        except Exception:
            pass

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
            name = ctx["skill_name"]
            # 检测是否包含中文，调整查询策略
            has_cjk = any('\u4e00' <= c <= '\u9fff' for c in name)
            
            # 提取英文关键词（含字母数字组合词如 neo4j）
            import re as _re
            # 匹配至少包含一个字母的连续字符（保留数字，如 neo4j）
            en_kws = _re.findall(r'[a-zA-Z][a-zA-Z0-9]*', name)
            # 去重并排除单字母无意义词
            en_kws = sorted(set(w for w in en_kws if len(w) > 2))
            en_kw = " ".join(en_kws) if en_kws else ""
            
            queries = []
            if has_cjk:
                # 中文查询
                queries.extend([
                    f"{name} 最佳实践",
                    f"{name} 实战 经验",
                    f"{name} 技术方案 案例",
                    f"{name.split('图像')[0] if '图像' in name else name} 图像识别 凭证验证",
                ])
                # 如果有英文关键词，额外生成英文查询
                if en_kw and len(en_kw) > 3:
                    queries.extend([
                        f"{en_kw} best practices tutorial",
                        f"{en_kw} guide examples",
                    ])
            else:
                queries = [
                    f"{name.replace('_',' ')} best practices 2025",
                    f"{name.replace('_',' ')} production experience",
                    f"{name.replace('_',' ')} tutorial guide"
                ]
            web_cases = []
            seen_urls = set()
            for q in queries:
                results = search_engine(q, size=5)
                for r in results:
                    url = r.get("url", "")
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        web_cases.append({
                            "source": "web",
                            "title": r.get("title", ""),
                            "url": url,
                            "snippet": r.get("snippet", "")[:300]
                        })
            all_cases.extend(web_cases)
            print(f"  Web: {len(web_cases)} 条 (去重)")

            # ── 搜索引擎返回 0 条时，自动降级到 Wikipedia 搜索 ──
            if len(web_cases) == 0:
                try:
                    wiki_fn = _web_search_wikipedia
                    wiki_queries = [f"{en_kw}", name] if en_kws else [name]
                    wiki_seen = set()
                    wiki_cases = []
                    for wq in wiki_queries:
                        wiki_results = wiki_fn(wq, size=5)
                        for wr in wiki_results:
                            title = wr.get("title", "")
                            url = wr.get("url", "")
                            if url and url not in wiki_seen:
                                wiki_seen.add(url)
                                wiki_cases.append({
                                    "source": "wikipedia",
                                    "title": title,
                                    "url": url,
                                    "snippet": wr.get("snippet", "")[:300]
                                })
                    if wiki_cases:
                        print(f"  Wikipedia: {len(wiki_cases)} 条 (搜索引擎降级)")
                        all_cases.extend(wiki_cases)
                except Exception as e:
                    print(f"  Wikipedia: [FAIL] {e}")
        except Exception as e:
            print(f"  Web: [FAIL] {e}")
    else:
        print(f"  Web: [FAIL] 搜索引擎不可用")

    # 继承上一版案例（--force 时跳过）
    if os.environ.get("SKILL_FORCE_REFRESH") == "1":
        print(f"  --force: 跳过继承旧案例")
    else:
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

def _decompose_skill_name(skill_name: str, cases: list) -> list:
    """将技能名分解为子主题，生成初始模式（0案例fallback用）"""
    if not cases:
        cases = []
    
    # 从技能名称中提取有意义片段
    words = skill_name.replace("_", " ").replace("-", " ")
    # 对中文名按语义切分
    parts = []
    buf = ""
    for ch in words:
        if '\u4e00' <= ch <= '\u9fff':
            if buf and not any('\u4e00' <= c <= '\u9fff' for c in buf):
                parts.append(buf.strip())
                buf = ""
            buf += ch
        elif ch == ' ':
            if buf:
                parts.append(buf.strip())
                buf = ""
        else:
            buf += ch
    if buf:
        parts.append(buf.strip())
    parts = [p for p in parts if len(p) > 1]
    
    # 基于常见技能后缀生成子主题模板映射
    topic_map = {
        "图像": "图像采集与预处理最佳实践",
        "图片": "图像采集与预处理最佳实践",
        "凭证": "凭证标准化与格式校验规范",
        "证件": "凭证标准化与格式校验规范",
        "鉴定": "鉴定流程与判定标准",
        "验证": "验证流程与防篡改机制",
        "识别": "识别算法选型与准确率优化",
        "检测": "异常检测与告警阈值设定",
        "审核": "审核流程自动化与风控策略",
        "审查": "审核流程自动化与风控策略",
        "贷款": "贷款业务场景与合规要求",
        "信贷": "贷款业务场景与合规要求",
        "金融": "金融级安全与数据隐私保护",
        "风控": "金融级安全与数据隐私保护",
        "OCR": "OCR识别与文字提取技术选型",
        "ocr": "OCR识别与文字提取技术选型",
        "防伪": "防伪特征检测与真伪鉴别",
        "篡改": "图像篡改检测与完整性校验",
        "安全": "安全防护与数据隐私合规",
        "合规": "合规审查与审计追溯",
        "小微": "小微金融业务风控体系",
        "文档": "文档结构化解析与关键信息提取",
        "合同": "合同关键条款抽取与比对",
        "报表": "报表自动生成与数据可视化",
        "签名": "电子签名与数字证书验证",
        "水印": "水印检测与防伪溯源",
        "卫星": "卫星影像几何校正与预处理",
        "遥感": "多光谱遥感数据分析与解译",
        "无人机": "无人机影像处理与拼接",
        "航拍": "航拍影像三维重建与正射校正",
        "SAR": "SAR雷达影像处理与目标识别",
        "雷达": "SAR雷达影像处理与目标识别",
        "光谱": "光谱分析在地物分类中的应用",
        "测绘": "测绘数据标准化与地图制图",
        "地理": "地理空间分析与GIS集成",
        "像素": "像素级影像融合与分辨率增强",
        "neo4j": "Neo4j图数据库建模与Cypher查询",
        "cypher": "Cypher查询语言核心语法与模式匹配",
        "图数据": "图数据建模与路径查询优化",
        "图查询": "图查询语言与遍历算法",
        "节点": "图数据库节点类型与属性设计",
        "关系": "图数据库关系建模与关联分析",
        "知识图谱": "知识图谱构建与图数据库存储",
        "图算法": "图算法在路径分析与社区发现中的应用",
    }
    
    sub_patterns = []
    seen = set()
    for part in parts:
        for keyword, pattern_text in topic_map.items():
            if keyword in part or keyword in skill_name:
                if keyword not in seen:
                    seen.add(keyword)
                    sub_patterns.append((f"{pattern_text}（{skill_name[:20]}）", 78))
    
    # 从案例标题/摘要中提取关键词，新增为低置信度模式
    case_keywords_found = set()
    for c in cases:
        text = (c.get("title","") + " " + c.get("snippet","")).lower()
        # 提取案例中的技术/业务关键词
        for tech_term in ["ocr","深度学习","cnn","数字签名","哈希校验",
                          "篡改检测","防伪","水印","合规","审计",
                          "风控","信用","评估","识别率","准确率",
                          "卫星","遥感","光谱","雷达","sar","gis",
                          "变化检测","目标检测","语义分割","像素",
                          "多光谱","高光谱","无人机","航拍","配准",
                          "neo4j","cypher","图数据库","知识图谱",
                          "图算法","图查询","图遍历","节点","关系"]:
            if tech_term in text and tech_term not in seen:
                case_keywords_found.add(tech_term)
    
    for kw in case_keywords_found:
        sub_patterns.append((f"{kw}相关技术与最佳实践（{skill_name[:20]}）", 72))
        seen.add(kw)
    
    # 如果找不到匹配，生成通用结构
    if not sub_patterns:
        generic_subs = [
            f"{skill_name[:30]}核心概念与术语体系",
            f"{skill_name[:30]}常见场景与解决方案",
            f"{skill_name[:30]}工具链与环境搭建",
        ]
        sub_patterns = [(s, 70) for s in generic_subs]
    
    return sub_patterns[:5]

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
    # 从 JSON 文件加载，方便用户扩展/修改
    _patterns_file = Path(__file__).parent / "skill_domain_patterns.json"
    if _patterns_file.exists():
        with open(_patterns_file, "r", encoding="utf-8") as _f:
            _raw = json.load(_f)
        # 将 JSON 中的 dict 格式 principles 还原为 (principle, id, confidence) 三元组
        skill_domain_patterns = {}
        for _domain, _info in _raw.items():
            skill_domain_patterns[_domain] = {
                "keywords": _info["keywords"],
                "principles": [
                    (_p["principle"], _p["id"], _p["confidence"])
                    for _p in _info["principles"]
                ]
            }
    else:
        skill_domain_patterns = {}
        print("  [WARN] skill_domain_patterns.json 不存在，跳过领域模式匹配")

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

    # ── 始终合并领域专有模式（不依赖案例，直接从技能名语义分解） ──
    sub_ideas = _decompose_skill_name(skill_name, cases)
    added_domain_ids = set()
    for i, (sub_name, conf) in enumerate(sub_ideas):
        pid = f"P_domain_{i+1}"
        if pid not in seen_ids and pid not in added_domain_ids:
            patterns.append({
                "id": pid,
                "principle": sub_name,
                "confidence": conf,
                "level": "domain"
            })
            seen_ids.add(pid)
            added_domain_ids.add(pid)

    # ── 技能相关性评分：过滤/降权不相关的通用模式 ──
    skill_lower = skill_name.lower()
    # 从 skill_domain_patterns 中提取与技能名相关的领域前缀
    relevant_prefixes = set()
    for domain, info in skill_domain_patterns.items():
        if domain in skill_lower or any(kw in skill_lower for kw in info["keywords"]):
            # 从该领域第一条原则的ID提取领域前缀（如 P_fin_、P_img_、P_doc_）
            for p in info["principles"]:
                pid_str = p[1] if isinstance(p, tuple) else (p.get("id", "") if isinstance(p, dict) else "")
                parts = pid_str.split("_")
                if len(parts) >= 2 and parts[0] == "P":
                    relevant_prefixes.add(f"P_{parts[1]}_")
                    break
    # 始终包含 DOMAIN 模式
    relevant_prefixes.add("P_domain_")

    # ── 领域互斥：如果技能名含图数据库相关词，排除SQL的database领域 ──
    if any(kw in skill_lower for kw in ["图数据库", "neo4j", "cypher", "graph", "知识图谱",
                                         "图数据", "图查询", "图算法"]):
        if "P_db_" in relevant_prefixes:
            relevant_prefixes.discard("P_db_")
            print(f"  检测到图数据库技能，排除 SQL database 领域模式")

    for p in patterns:
        pid = p["id"]
        level = p.get("level", "basic")
        # DOMAIN 模式直接从 skill name 生成，保持高置信度
        if level == "domain":
            p["confidence"] = min(p["confidence"] + 5, 95)
            continue
        # 检查模式是否属于相关领域（按ID前缀匹配）
        is_relevant = any(pid.startswith(prefix) for prefix in relevant_prefixes)
        if level == "advanced":
            if is_relevant:
                p["confidence"] = min(p["confidence"] + 3, 95)
            else:
                # 不相关的高级模式降权
                p["confidence"] = max(p["confidence"] - 20, 40)
        # BASIC 通用模式降权
        if level == "basic":
            p["confidence"] = max(p["confidence"] - 10, 35)

    # ── 过滤低分噪声模式（置信度 < 65 的不保留） ──
    before = len(patterns)
    patterns = [p for p in patterns if p.get("confidence", 0) >= 65]
    filtered = before - len(patterns)
    if filtered:
        print(f"  过滤掉 {filtered} 个低相关性模式（置信度 < 65）")
    print(f"  保留 {len(patterns)} 个有效模式")

    # 排序（按置信度降序，domain 模式优先于同分）
    patterns.sort(key=lambda x: (x.get("confidence", 0), x.get("level", "")), reverse=True)
    return patterns


def _phase3_analyze(ctx: dict):
    """Phase 3: 分析提炼知识模式"""
    print(f"\n{'-'*55}")
    print("  Phase 3: 模式提炼")
    print(f"{'-'*55}")

    cases = ctx.get("cases", [])
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
    case_count = len(ctx.get("cases", []))

    # 从外部模板文件读取
    template_file = Path(__file__).parent / 'assess_template.py'
    tool_code = template_file.read_text(encoding='utf-8')
    tool_code = tool_code.replace("__VERSION__", str(ctx["version"]))
    tool_code = tool_code.replace("__SKILL__", ctx["skill_name"])
    tool_code = tool_code.replace("__SKILL_DISPLAY__",
        ctx.get("skill_definition", {}).get("display_name", ctx["skill_name"]))
    tool_code = tool_code.replace("__PATTERNS_JSON__", patterns_json)
    tool_code = tool_code.replace("__CASE_COUNT__", str(case_count))

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

    # 生成 Markdown 报告
    _generate_markdown_report(ctx)


def _generate_markdown_report(ctx: dict):
    """生成人类可读的 Markdown 学习报告"""
    rev_dir = ctx.get("rev_dir")
    if not rev_dir:
        return
    skill = ctx.get("skill_name", "unknown")
    version = ctx.get("version", 0)
    patterns = ctx.get("patterns", [])
    cases = ctx.get("cases", [])
    assessment = ctx.get("assessment", {})
    score = assessment.get("final_score", 0)
    passed = assessment.get("passed", False)
    inherited = ctx.get("inherited_patterns", [])
    inherited_ids = {p["id"] for p in inherited}
    prev_version = version - 1 if version > 1 else None

    # 分割模式
    domains = [p for p in patterns if p.get("level") == "domain"]
    advanced = [p for p in patterns if p.get("level") == "advanced"]
    basics = [p for p in patterns if p.get("level") == "basic"]
    
    # 区分继承vs新增
    inherited_cnt = sum(1 for p in patterns if p["id"] in inherited_ids)
    new_cnt = len(patterns) - inherited_cnt

    lines = []
    lines.append(f"# 技能学习报告: {skill}")
    lines.append(f"")
    lines.append(f"| 属性 | 值 |")
    lines.append(f"|------|-----|")
    lines.append(f"| 版本 | rev{version} |")
    lines.append(f"| 评分 | {score}/100 {'PASS' if passed else 'FAIL'} |")
    lines.append(f"| 案例数 | {len(cases)} 条 |")
    lines.append(f"| 模式总数 | {len(patterns)} 个 |")
    if prev_version:
        lines.append(f"| 继承自 rev{prev_version} | {inherited_cnt} 个 |")
        lines.append(f"| 新增 | {new_cnt} 个 |")
    lines.append(f"")
    lines.append(f"## 知识模式")
    lines.append(f"")
    if domains:
        lines.append(f"### 领域专有 ({len(domains)}个)")
        for p in sorted(domains, key=lambda x: -x.get("confidence", 0)):
            lines.append(f"- [{p['confidence']}%] {p['principle']}")
        lines.append(f"")
    if advanced:
        lines.append(f"### 高级模式 ({len(advanced)}个)")
        for p in sorted(advanced, key=lambda x: -x.get("confidence", 0)):
            lines.append(f"- [{p['confidence']}%] {p['principle']}")
        lines.append(f"")
    if basics:
        lines.append(f"### 基础模式 ({len(basics)}个)")
        for p in sorted(basics, key=lambda x: -x.get("confidence", 0)):
            lines.append(f"- [{p['confidence']}%] {p['principle']}")
        lines.append(f"")

    # 案例摘要
    if cases:
        lines.append(f"## 参考案例 ({len(cases)}条)")
        lines.append(f"")
        for c in cases[:10]:
            title = c.get("title", c.get("key", "?"))
            url = c.get("url", "")
            if url:
                lines.append(f"- [{title}]({url})")
            else:
                lines.append(f"- {title}")

    report_path = rev_dir / "reports" / "learning_report.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"  [OK] 学习报告: reports/learning_report.md")
