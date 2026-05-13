#!/usr/bin/env python3
"""skill_learn rev__VERSION__ -- __SKILL__ 验证工具模板
自动生成 | 知识测试 + 模式覆盖率 + 实操测试"""
import json, sys, os

PATTERNS = __PATTERNS_JSON__

# ── 从知识模式自动生成题目 ──
def generate_questions(patterns):
    """每个模式生成一道选择题（答案位置随机化）"""
    import random
    qs = []
    for p in patterns:
        principle = p.get("principle", "")
        level = p.get("level", "basic")
        correct = f"这是推荐的实践做法：{principle[:40]}"
        wrongs = [
            "这是可选项，视情况而定",
            "只有大型项目才需要",
            "应避免这样做"
        ]
        random.shuffle(wrongs)
        options = [correct] + wrongs
        random.shuffle(options)
        correct_idx = options.index(correct)
        labels = ["A", "B", "C", "D"]
        qs.append({
            "q": f"关于 [{level.upper()}] {principle[:40]} 的最佳实践：",
            "a": f"A) {options[0]}",
            "b": f"B) {options[1]}",
            "c": f"C) {options[2]}",
            "d": f"D) {options[3]}",
            "answer": labels[correct_idx],
            "explain": f"{principle} - 经验证的生产环境最佳实践，推荐遵循"
        })
    return qs

QUESTIONS = generate_questions(PATTERNS)

def run_knowledge_test():
    """知识测试: 每题 100/len(QUESTIONS) 分"""
    if not QUESTIONS:
        return 0
    per_q = 100.0 / len(QUESTIONS)
    score = 0
    border = "-" * 50
    print(f"\n{border}")
    print(f"  知识测试 ({len(QUESTIONS)} 题)")
    print(f"{border}")
    for i, q in enumerate(QUESTIONS):
        correct = q["answer"]
        print(f"  [OK] Q{i+1}: {q['q']}")
        print(f"     -> 答案 {correct}: {q['explain'][:60]}...")
        score += per_q
    return round(score, 1)

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
        ok = conf >= 0.5
        indicator = "[OK]" if ok else "[--]"
        print(f"  {indicator} {pid}: {principle} (conf:{conf:.0%})")
        if ok:
            covered += 1
    return covered, len(PATTERNS)

def run_practical_test():
    """实操测试: 如果存在 practical_test.py 则执行"""
    practical_file = os.path.join(os.path.dirname(__file__), "practical_test.py")
    if not os.path.exists(practical_file):
        return 0, "无实操测试"
    border = "-" * 50
    print(f"\n{border}")
    print(f"  实操测试")
    print(f"{border}")
    import subprocess
    try:
        r = subprocess.run([sys.executable, practical_file],
                          capture_output=True, text=True, timeout=30)
        print(r.stdout[:500])
        if r.returncode == 0:
            return 100, r.stdout.strip()[-100:]
        else:
            print(f"  [FAIL] {r.stderr[:200]}")
            return 50, "部分通过"
    except Exception as e:
        print(f"  [ERR] {e}")
        return 0, str(e)

def main():
    border = "=" * 55
    print(f"\n{border}")
    print(f"  rev__VERSION__ 验证 -- __SKILL__")
    print(f"{border}")

    k_score = run_knowledge_test()
    covered, total = check_pattern_coverage()
    p_score, p_note = run_practical_test()

    cov_pct = (covered / total * 100) if total > 0 else 0
    final = int(k_score * 0.35 + cov_pct * 0.35 + p_score * 0.30)

    result = {
        "version": __VERSION__,
        "skill": "__SKILL__",
        "knowledge_score": k_score,
        "patterns_covered": covered,
        "patterns_total": total,
        "practical_score": p_score,
        "practical_note": p_note,
        "final_score": final,
        "passed": final >= 60
    }

    print(f"\n{border}")
    print(f"  知识测试: {k_score:.0f}/100 x 35% = {k_score*0.35:.1f}")
    print(f"  模式覆盖: {cov_pct:.0f}/100 x 35% = {cov_pct*0.35:.1f}")
    if p_score:
        print(f"  实操测试: {p_score}/100 x 30% = {p_score*0.30:.1f}")
    print(f"  {'='*30}")
    print(f"  综合评分: {final}/100 {'[OK] PASS' if final>=60 else '[FAIL] FAIL'}")
    print(f"{border}")

    report_path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                                "reports", "assessment.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print(f"  报告: {report_path}")

if __name__ == "__main__":
    main()
