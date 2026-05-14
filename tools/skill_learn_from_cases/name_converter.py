"""
name_converter.py — 中英技能名转换

将中文技能名（如"金融图像凭证鉴定"）转换为标准英文名（finance_image_voucher_verification）
用于统一目录命名和搜索引擎查询优化。

用法:
    from tools.skill_learn_from_cases.name_converter import convert_name
    en_name = convert_name("金融图像凭证鉴定")
    # → "finance_image_voucher_verification"
"""

from pathlib import Path
import json
import re

# 中文→英文技术术语映射（可编辑扩展）
_MAPPING_FILE = Path(__file__).parent / "chinese_to_english.json"

# 内置缓存
_mapping_cache = None

def _load_mapping() -> dict:
    """加载中英映射字典"""
    global _mapping_cache
    if _mapping_cache is not None:
        return _mapping_cache
    mapping = {}
    if _MAPPING_FILE.exists():
        with open(_MAPPING_FILE, 'r', encoding='utf-8') as f:
            mapping = json.load(f)
    _mapping_cache = mapping
    return mapping


def convert_name(skill_name: str) -> str:
    """将任意技能名转换为标准英文名（下划线分隔）"""
    if not skill_name:
        return "unknown"

    has_cjk = any('\u4e00' <= c <= '\u9fff' for c in skill_name)

    # 纯英文名：直接规范化
    if not has_cjk:
        safe = skill_name.strip().lower().replace(" ", "_").replace("-", "_")
        # 路径注入防护
        safe = re.sub(r'[^\w\-\u4e00-\u9fff]', '', safe).strip('_')
        return safe or "unknown"

    mapping = _load_mapping()
    seen = set()
    result = []
    
    # 1. 提取英文关键词（保留数字组合如 neo4j）
    en_words = re.findall(r'[a-zA-Z][a-zA-Z0-9]*', skill_name)
    for w in en_words:
        w = w.lower()
        if len(w) >= 2 and w not in seen:
            seen.add(w)
            result.append(w)
    
    # 2. 中文映射（按关键词长度降序，优先匹配长词，匹配后消耗文本）
    remaining = skill_name
    sorted_mapping = sorted(mapping.items(), key=lambda x: -len(x[0]))
    for zh, en in sorted_mapping:
        if zh in remaining:
            for word in en.split("_"):
                word = word.strip()
                if word and word not in seen:
                    seen.add(word)
                    result.append(word)
            # 消耗匹配的中文文本（防止"数据"重复匹配"数据库"）
            remaining = remaining.replace(zh, " " * len(zh), 1)
    
    return "_".join(result) if result else skill_name.strip().lower().replace(" ", "_")


def refresh_cache():
    """清除缓存，下次调用将重新加载映射文件（编辑后调用）"""
    global _mapping_cache
    _mapping_cache = None
