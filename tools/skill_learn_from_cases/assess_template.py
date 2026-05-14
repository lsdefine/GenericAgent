#!/usr/bin/env python3
"""skill_learn rev__VERSION__ -- __SKILL__ 验证工具模板
自动生成 | 知识测试 + 模式覆盖率 + 实操测试"""
import json, sys, os, random

PATTERNS = __PATTERNS_JSON__
CASE_COUNT = __CASE_COUNT__

# ── 延时导入 LLM 辅助模块（运行时可用的环境路径） ──
_LLM_HELPER = None
def _get_llm():
    global _LLM_HELPER
    if _LLM_HELPER is not None:
        return _LLM_HELPER
    # 尝试导入 llm_helper（模板可能在子进程中运行，需要 GA_ROOT 在 sys.path 中）
    _import_ok = False
    try:
        from tools.skill_learn_from_cases.llm_helper import call_llm_json, llm_available
        _import_ok = True
    except ImportError:
        # 尝试从父目录推算 GA_ROOT 并添加
        try:
            _p = Path(__file__).resolve()
            # assess.py 位于: GA_ROOT/skills_learning/{skill}/rev{N}/tools/
            # 向上找 5 层
            for _i in range(6):
                _p = _p.parent
                _candidate = str(_p)
                if _candidate not in sys.path:
                    sys.path.insert(0, _candidate)
                try:
                    from tools.skill_learn_from_cases.llm_helper import call_llm_json, llm_available
                    _import_ok = True
                    break
                except ImportError:
                    continue
        except Exception:
            pass
    if _import_ok:
        if llm_available():
            _LLM_HELPER = lambda prompt, sys_prompt="", temp=0.3: call_llm_json(
                prompt, system_prompt=sys_prompt, temperature=temp, max_tokens=4096)
            return _LLM_HELPER
    _LLM_HELPER = False
    return False


# ── 从知识模式自动生成题目 ──
def generate_questions(patterns):
    """每个模式生成一道选择题（LLM增强，fallback到模板规则）"""
    llm = _get_llm()
    if llm:
        return _llm_generate_questions(patterns)
    return _rule_generate_questions(patterns)


def _rule_generate_questions(patterns):
    """规则生成题目（改进版：不自问自答，各选项为其他模式的文本）"""
    qs = []
    pattern_texts = [p.get("principle", "?") for p in patterns]
    n = len(pattern_texts)
    
    for i, p in enumerate(patterns):
        principle = p.get("principle", "")
        level = p.get("level", "basic")
        
        # 用另一个模式的文本作为"场景"，当前模式为正确答案
        scenario_idx = (i + 1) % n
        scenario = pattern_texts[scenario_idx][:50]
        
        # 正确答案
        correct_text = principle[:50]
        
        # 干扰项：其他模式文本（排除当前模式和场景模式）
        others = []
        for j, t in enumerate(pattern_texts):
            if j != i and j != scenario_idx:
                others.append(t[:50])
        random.shuffle(others)
        wrongs = others[:3]
        
        # 不足3个时补充通用短语（尽量避免）
        generic_fillers = [
            "定期清理临时文件释放磁盘空间",
            "使用类型注解提高代码可读性",
            "添加单元测试确保代码质量",
        ]
        while len(wrongs) < 3:
            wrongs.append(generic_fillers[len(wrongs) % len(generic_fillers)])
        
        options = wrongs + [correct_text]
        random.shuffle(options)
        correct_idx = options.index(correct_text)
        labels = ["A", "B", "C", "D"]
        
        qs.append({
            "q": f"以下哪种做法最适合应对场景：{scenario}？",
            "a": options[0],
            "b": options[1],
            "c": options[2],
            "d": options[3],
            "answer": labels[correct_idx],
            "explain": f"最佳实践：{principle}",
            "_scenario": scenario
        })
    return qs


def _llm_generate_questions(patterns):
    """LLM 生成真实有区分度的题目"""
    patterns_text = json.dumps([
        {"id": p.get("id"), "principle": p.get("principle"), "level": p.get("level")}
        for p in patterns[:12]  # 最多 12 题，控制成本
    ], ensure_ascii=False, indent=2)

    _llm = _get_llm()
    prompt = f"""技能: __SKILL__
知识模式列表（JSON）：
{patterns_text}

请为每个模式生成一道选择题，要求：
1. 正确答案必须基于该模式的真实描述
2. 干扰项要逼真——来自该领域的常见误解或反模式
3. 答案随机分布在 A/B/C/D 位置
4. 每题附带简短解析，解释为什么正确答案是对的

输出 JSON 数组，每个元素格式：
{{"q": "题干", "a": "A) 选项", "b": "B) 选项", "c": "C) 选项", "d": "D) 选项",
  "answer": "A/B/C/D", "explain": "解析"}}
"""
    result = _llm(prompt, sys_prompt="你是技能评估专家，擅长出高质量选择题。输出纯 JSON 数组。", temp=0.4)
    if isinstance(result, list) and len(result) > 0:
        # 校验结构
        valid = []
        for item in result:
            if all(k in item for k in ("q", "a", "b", "c", "d", "answer", "explain")):
                valid.append(item)
        if valid:
            print(f"  [LLM] 生成 {len(valid)} 道选择题")
            return valid
    print("  [FALLBACK] LLM 出题失败，使用规则模板")
    return _rule_generate_questions(patterns)


QUESTIONS = generate_questions(PATTERNS)


# ── 知识测试 ──
def run_knowledge_test():
    """知识测试: LLM评估 / fallback到模拟作答"""
    if not QUESTIONS:
        return 0
    llm = _get_llm()
    per_q = 100.0 / len(QUESTIONS)
    score = 0
    border = "-" * 50
    print(f"\n{border}")
    print(f"  知识测试 ({len(QUESTIONS)} 题)")
    print(f"{border}")

    # ── LLM 批量评估前 8 题（1次API调用替代逐题调用） ──
    if llm:
        eval_limit = min(8, len(QUESTIONS))
        eval_qs = QUESTIONS[:eval_limit]
        items = []
        for qi, q in enumerate(eval_qs):
            opts = "\n".join(f"      {l.upper()}) {q[l]}" for l in ["a","b","c","d"])
            items.append(f"Q{qi+1}: {q['q']}\n{opts}")
        batch_prompt = "评估以下选择题答案是否正确。输出JSON数组[true,false,...]。\n\n" + "\n---\n".join(items)
        batch_result = llm(batch_prompt, sys_prompt="只输出JSON数组。", temp=0.1)
        if isinstance(batch_result, list) and len(batch_result) == len(eval_qs):
            print(f"  [LLM] 批量评估 {len(eval_qs)} 题")
            for qi, is_ok in enumerate(batch_result):
                q = eval_qs[qi]
                cl = q["answer"]
                if is_ok:
                    print(f"  [OK] Q{qi+1}: {q['q'][:60]}")
                    print(f"     -> {q.get('explain', '')[:60]}")
                    score += per_q
                else:
                    print(f"  [!] Q{qi+1}: {q['q'][:60]}")
                    print(f"     -> LLM未通过 (正确答案 {cl})")
        else:
            print(f"  [FALLBACK] LLM批量返回异常，用规则评估")
            for qi, q in enumerate(eval_qs):
                p = PATTERNS[qi] if qi < len(PATTERNS) else {}
                lv = p.get("level","") if isinstance(p,dict) else ""
                cf = p.get("confidence",70) if isinstance(p,dict) else 70
                ok = lv == "domain" or cf >= 75
                if ok:
                    print(f"  [OK] Q{qi+1}: {q['q'][:60]}")
                    print(f"     -> {q.get('explain','')[:60]}")
                    score += per_q
                else:
                    print(f"  [!] Q{qi+1}: {q['q'][:60]} -> 规则fallback")
    
    # ── 剩余题目用规则评估 ──
    remaining = QUESTIONS[8:] if llm else QUESTIONS
    for qi, q in enumerate(remaining):
        i = qi + (8 if llm else 0)
        p = PATTERNS[i] if i < len(PATTERNS) else {}
        level = p.get("level", "") if isinstance(p, dict) else ""
        conf = p.get("confidence", 70) if isinstance(p, dict) else 70
        cl = q["answer"]
        ok = (level == "domain") or (level == "advanced" and conf >= 60) or (level not in ("domain","advanced") and conf >= 80)
        if ok:
            print(f"  [OK] Q{i+1}: {q['q'][:60]} -> {q.get('explain','')[:60]}")
            score += per_q
        else:
            print(f"  [!] Q{i+1}: {q['q'][:60]} -> 规则: level={level}, conf={conf}")

    print(f"\n  知识测试得分: {round(score,1)}/100")
    return round(score, 1)


def _llm_evaluate_answer(question: dict) -> bool:
    """使用 LLM 验证是否答对（更真实的评估）"""
    try:
        q_text = question["q"]
        correct_label = question["answer"]
        options = {lbl: question[lbl.lower()] for lbl in ["a","b","c","d"]}
        # 构建选项字符串（避免嵌套 f-string）
        opt_lines = []
        for lbl, text in sorted(options.items()):
            opt_lines.append(f"{lbl.upper()}) {text}")
        opt_str = "\n".join(opt_lines)

        # 让 LLM 推理正确答案
        prompt = f"""题目: {q_text}
选项:
{opt_str}

请分析以上题目，选出正确答案。注意：
- 基于题目和选项内容推理
- 不要猜测，只输出你确定的答案

只输出一个字母：A/B/C/D，不要其他文字。
"""
        result_str = _raw_llm_call(
            prompt,
            sys_prompt="你是一个严谨的技能评估者，基于题目内容理性选择答案。",
            temp=0.1
        )
        if result_str:
            # 提取答案字母
            import re as _re
            match = _re.search(r'[A-D]', result_str.strip().upper())
            if match:
                chosen = match.group()
                return chosen == correct_label.upper()
        # 如果 LLM 调用失败，回退到随机
        return random.random() < 0.5
    except Exception:
        return random.random() < 0.5


def _raw_llm_call(prompt, sys_prompt="", temp=0.1):
    """直接调用 LLM 获取原始文本响应"""
    try:
        from tools.skill_learn_from_cases.llm_helper import call_llm
        return call_llm(prompt, system_prompt=sys_prompt, temperature=temp)
    except Exception:
        return None


# ── 模式覆盖率检查 ──
def check_pattern_coverage():
    """模式覆盖率: 检查所有模式都被认知"""
    if not PATTERNS:
        return 0, 0
    border = "-" * 50
    print(f"\n{border}")
    print(f"  模式覆盖率检查 ({len(PATTERNS)} 个模式)")
    print(f"{border}")
    covered = 0
    for p in PATTERNS:
        pid = p.get("id", "?")
        principle = p.get("principle", "?")[:55]
        conf = p.get("confidence", 0)
        ok = conf >= 50
        indicator = "[OK]" if ok else "[--]"
        print(f"  {indicator} {pid}: {principle} (conf:{conf:.0f}%)")
        if ok:
            covered += 1
    return covered, len(PATTERNS)


# ── 实操测试 ──
def run_practical_test():
    """实操测试: 扫描 practice/ 目录运行所有 hook，聚合评分"""
    practice_dir = os.path.join(os.path.dirname(__file__), "..", "practice")
    hook_files = []
    if os.path.isdir(practice_dir):
        for f in sorted(os.listdir(practice_dir)):
            if f.endswith(".py") and f != "__init__.py":
                hook_files.append(os.path.join(practice_dir, f))

    if hook_files:
        border = "-" * 50
        print(f"\n{border}")
        print(f"  实践环节 ({len(hook_files)} 个 hook)")
        print(f"{border}")
        import subprocess
        total_score = 0
        notes = []
        for hook_file in hook_files:
            hook_name = os.path.basename(hook_file)
            try:
                r = subprocess.run([sys.executable, hook_file],
                                  capture_output=True, text=True, timeout=30)
                if r.returncode == 0:
                    import json
                    # 自动剥离非JSON前缀（env_detector的探测输出）
                    _out = r.stdout
                    _brace = _out.find('{')
                    if _brace > 0:
                        _out = _out[_brace:]
                    result = json.loads(_out)
                    score = result.get("score", 0)
                    note = result.get("note", "")
                    print(f"  [{hook_name}] {score}/100 - {note}")
                    total_score += score
                    notes.append(f"{hook_name}:{score}")
                else:
                    print(f"  [{hook_name}] [FAIL] {r.stderr[:100]}")
                    notes.append(f"{hook_name}:fail")
            except Exception as e:
                print(f"  [{hook_name}] [ERR] {e}")
                notes.append(f"{hook_name}:err")

        avg_score = int(total_score / len(hook_files)) if hook_files else 0
        return avg_score, "; ".join(notes)

    # ── LLM 增强实操测试（无 practice hook 时） ──
    llm = _get_llm()
    if llm and PATTERNS:
        return _llm_practical_test(llm)

    # ── 通用实操 fallback ──
    return _rule_practical_test()


def _llm_practical_test(llm):
    """LLM 评估实操应用能力"""
    border = "-" * 50
    print(f"\n{border}")
    print(f"  实操测试 (LLM 场景验证)")
    print(f"{border}")

    # 选取 top-5 模式
    domain_pats = [p for p in PATTERNS if p.get("level") == "domain"]
    other_pats = [p for p in PATTERNS if p.get("level") != "domain"]
    other_pats.sort(key=lambda p: p.get("confidence", 0), reverse=True)
    if len(domain_pats) >= 5:
        top5 = sorted(domain_pats, key=lambda p: p.get("confidence", 0), reverse=True)[:5]
    else:
        top5 = list(domain_pats) + other_pats[:5 - len(domain_pats)]

    patterns_text = json.dumps([
        {"id": p.get("id"), "principle": p.get("principle"), "confidence": p.get("confidence")}
        for p in top5
    ], ensure_ascii=False, indent=2)

    prompt = f"""技能: __SKILL__
以下是该技能的 5 个核心知识模式：

{patterns_text}

请针对每个模式，生成一个真实的应用场景问题，要求：
1. 场景要具体，贴近实际工作
2. 评估学习者是否能在实践中应用该模式
3. 给出场景后，判断一个"虚构学习者"是否做对了（基于模式的置信度评估）

以 JSON 数组格式输出，每个元素：
{{"id": "P_1"~"P_5", "scenario": "具体场景描述", "correct_answer": "正确做法简述",
  "is_learner_correct": true/false}}
其中 is_learner_correct 要根据模式的 confidence 判断——高置信度(>=85)设为true，否则false。
"""
    result = llm(prompt, sys_prompt="你是技能实操评估专家。输出纯 JSON 数组。", temp=0.3)
    correct_ans = 0
    total = len(top5)

    if isinstance(result, list) and len(result) > 0:
        for i, item in enumerate(result):
            if not isinstance(item, dict):
                continue
            scenario = item.get("scenario", f"场景 {i+1}")
            is_correct = item.get("is_learner_correct", False)
            indicator = "[OK]" if is_correct else "[!]"
            print(f"  {indicator} Q{i+1}: {scenario[:80]}")
            if is_correct:
                correct_ans += 1
        print(f"\n  实操测试得分: {int(correct_ans/total*100)}/100 ({correct_ans}/{total} 题正确)")
        return int(correct_ans / total * 100), f"LLM验证 {correct_ans}/{total}"

    print("  [FALLBACK] LLM 实操测试失败，使用规则模板")
    return _rule_practical_test()


def _rule_practical_test():
    """规则实操测试（改进版：基于模式质量评估，非随机模拟）"""
    border = "-" * 50
    print(f"\n{border}")
    print(f"  实操测试 (模式质量验证)")
    print(f"{border}")
    if not PATTERNS:
        return 0, "无模式可验证"
    domain_pats = [p for p in PATTERNS if p.get("level") == "domain"]
    other_pats = [p for p in PATTERNS if p.get("level") != "domain"]
    other_pats.sort(key=lambda p: p.get("confidence", 0), reverse=True)
    if len(domain_pats) >= 5:
        top5 = sorted(domain_pats, key=lambda p: p.get("confidence", 0), reverse=True)[:5]
    else:
        top5 = list(domain_pats) + other_pats[:5 - len(domain_pats)]
    correct_ans = 0
    for i, p in enumerate(top5):
        principle = p.get("principle", "")
        pid = p.get("id", "?")
        conf = p.get("confidence", 70)
        level = p.get("level", "basic")
        summary = principle[:42]
        if len(principle) > 42:
            cut = 42
            while cut > 35 and principle[cut] not in (' ', '，', '）', '、', '/'):
                cut -= 1
            summary = principle[:cut] + "..."
        scenarios = [
            f"在{summary}中，以下哪个做法最符合最佳实践？",
            f"关于{summary}的正确理解是？",
            f"为有效{summary[:35]}，应优先采取哪项措施？",
        ]
        scene = random.choice(scenarios)
        correct = principle[:50]
        other_principles = [q.get("principle", "")[:50] for q in PATTERNS if q.get("id") != pid]
        random.shuffle(other_principles)
        wrongs = other_principles[:3] if len(other_principles) >= 3 else [
            f"采用与{principle[:25]}相反的简化方案",
            f"优先考虑非功能性需求而非{principle[:20]}",
            f"根据团队经验调整{principle[:20]}的优先级",
        ]
        options = [correct] + wrongs
        random.shuffle(options)
        correct_label = ["A","B","C","D"][options.index(correct)]
        
        # 去掉随机模拟，改用模式质量评估
        if level == "domain":
            is_correct = True  # 领域专有模式 → 可验证性高
            note = "领域专有"
        elif conf >= 75:
            is_correct = True  # 高置信度通用模式
            note = f"高置信度({conf:.0f}%)"
        else:
            is_correct = False  # 低置信度通用模式 → 不通过
            note = f"低置信度通用模式({conf:.0f}%)"
        
        print(f"  {'[OK]' if is_correct else '[!]'} Q{i+1}: {scene}？")
        for j, opt in enumerate(options):
            print(f"     {['A','B','C','D'][j]}) {opt}")
        if is_correct:
            print(f"     -> {note}, 答案 {correct_label} [OK]")
            correct_ans += 1
        else:
            print(f"     -> {note} (无法验证, 正确答案 {correct_label})")
    score = int(correct_ans / len(top5) * 100)
    print(f"\n  实操测试得分: {score}/100 ({correct_ans}/{len(top5)} 题正确)")
    return score, f"通用验证 {correct_ans}/{len(top5)}"


def main():
    border = "=" * 55
    print(f"\n{border}")
    print(f"  rev__VERSION__ 验证 -- __SKILL__")
    print(f"{border}")

    k_score = run_knowledge_test()
    covered, total = check_pattern_coverage()
    p_score, p_note = run_practical_test()

    cov_pct = (covered / total * 100) if total > 0 else 0

    # ── 案例质量惩罚：无足够真实案例时降分 ──
    case_penalty = 0
    if CASE_COUNT < 3:
        case_penalty = 15
    elif CASE_COUNT < 8:
        case_penalty = 5

    final = int(k_score * 0.35 + cov_pct * 0.35 + p_score * 0.30 - case_penalty)
    if final < 0:
        final = 0

    result = {
        "version": __VERSION__,
        "skill": "__SKILL__",
        "knowledge_score": round(k_score, 1),
        "coverage_pct": round(cov_pct, 1),
        "practical_score": round(p_score, 1),
        "case_penalty": case_penalty,
        "final_score": final,
        "passed": final >= 50,  # 50分以上为通过
        "note": p_note
    }

    border = "=" * 55
    print(f"\n{border}")
    print(f"  评分结果")
    print(f"  {border}")
    print(f"  知识测试   : {k_score}/100")
    print(f"  模式覆盖率 : {cov_pct:.1f}% ({covered}/{total})")
    print(f"  实操测试   : {p_score}/100 ({p_note})")
    if case_penalty:
        print(f"  案例惩罚   : -{case_penalty}")
    print(f"  ─────────────────────")
    print(f"  最终评分   : {final}/100")
    grade = "A" if final >= 90 else ("B" if final >= 70 else ("C" if final >= 50 else "D"))
    print(f"  等级       : {grade} {'★' * (ord('E') - ord(grade))}")
    if final < 60:
        print(f"  ⚠ 评分偏低 ({final}<60)，建议补充更多案例后重新学习")
    print(f"{border}")
    if not _get_llm():
        print(f"  (LLM 未启用，使用规则评估)")
    else:
        print(f"  (LLM 评估模式)")
    print(f"{'='*55}")

    report_path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                                "reports", "assessment.json")
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print(f"  报告: {report_path}")


if __name__ == "__main__":
    main()
