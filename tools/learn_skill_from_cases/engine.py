"""
engine.py — Simplified skill learning engine (English-only)

5-phase flow:
  Phase 0: Bootstrap + directory creation
  Phase 1: Skill definition (skill_search lookup)
  Phase 2: Case collection (skill_search + web search)
  Phase 3: Pattern extraction & knowledge refinement
  Phase 4: Assessment tool generation
  Phase 5: Validation & report
"""
import sys, os, json, re, subprocess, importlib, random
from pathlib import Path

GA_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(GA_ROOT))

from tools.learn_skill_from_cases import dir_manager
from tools.learn_skill_from_cases.eng_patterns_data import TOPIC_MAP, CASE_SCAN_KEYWORDS, CORE_PATTERNS, render_assess_code


# ===============================================================
# Phase 0: Bootstrap
# ===============================================================
def _ensure_env(ctx: dict):
    """Phase 0 — Ensure environment is ready."""
    print("\n" + ("=" * 55))
    print("  Phase 0: Bootstrap")
    print("=" * 55)
    dir_manager.ensure_root_exists()
    version = dir_manager.next_version(ctx["skill_name"])
    rev_dir = dir_manager.create_revision_dir(ctx["skill_name"], version)
    ctx["version"] = version
    ctx["rev_dir"] = rev_dir
    print(f"  Skill: {ctx['skill_name']}")
    print(f"  Version: rev{version}")
    print(f"  Directory: {rev_dir}")
    print("  [OK] Environment ready")


# ===============================================================
# Phase 1: Skill Definition
# ===============================================================
def _import_skill_search():
    """Lazy import skill_search, return None if unavailable."""
    try:
        from skill_search import search
        return search
    except Exception:
        return None


def _phase1_define(ctx: dict):
    """Phase 1 — Define the skill by looking up known knowledge."""
    print(f"\n{'-' * 55}")
    print("  Phase 1: Skill Definition")
    print("-" * 55)

    ctx["skill_definition"] = {
        "name": ctx["skill_name"],
        "description": "",
        "tags": [],
        "source": "user_input"
    }

    search_fn = _import_skill_search()
    if search_fn:
        try:
            results = search_fn(ctx["skill_name"].replace("_", " "), top_k=5)
            if results:
                best = results[0]
                s = best.skill
                ctx["skill_definition"]["description"] = (s.description or "")[:500]
                ctx["skill_definition"]["tags"] = (s.tags or [])[:10]
                ctx["skill_definition"]["key"] = s.key
                ctx["skill_definition"]["source"] = "skill_search"
                print(f"  Found: {s.key}")
                if s.description:
                    print(f"  Description: {s.description[:100]}...")
            else:
                print(f"  No results from skill_search")
        except Exception as e:
            print(f"  skill_search: [FAIL] {e}")
    else:
        print(f"  skill_search not available")

    # Write definition
    def_file = ctx["rev_dir"] / "reports" / "skill_definition.json"
    with open(def_file, "w", encoding="utf-8") as f:
        json.dump(ctx["skill_definition"], f, indent=2, ensure_ascii=False)
    print("  [OK] Definition saved")


# ===============================================================
# Phase 2: Case Collection
# ===============================================================
def _import_web_search():
    """Simple import of web search; return None if unavailable."""
    try:
        from tools.metaso_search import metaso_search as fn
        return fn
    except Exception:
        return None


def _generate_search_queries(skill_name: str) -> list[str]:
    """Generate English search queries for a skill name."""
    name = skill_name.replace("_", " ").title()
    return [
        f"{name} tutorial",
        f"{name} how to use",
        f"{name} examples guide",
        f"{name} best practices",
        f"{name} getting started",
        f"learn {name}",
    ]


def _phase2_search(ctx: dict):
    """Phase 2 — Collect cases from skill_search + web search."""
    print(f"\n{'-' * 55}")
    print("  Phase 2: Case Collection")
    print("-" * 55)

    all_cases = []

    # Channel A: Skill Hub
    search_fn = _import_skill_search()
    if search_fn:
        try:
            results = search_fn(ctx["skill_name"].replace("_", " "), top_k=10)
            skill_cases = []
            for r in results:
                s = r.skill
                if hasattr(s, 'key') and not s.key.startswith("agentskill_skills/"):
                    skill_cases.append({
                        "source": "skill_hub", "type": "skill_def",
                        "key": s.key,
                        "description": (s.description[:300] if s.description else ""),
                        "tags": s.tags[:5] if s.tags else [],
                    })
            all_cases.extend(skill_cases)
            print(f"  Skill Hub: {len(skill_cases)} results")
        except Exception as e:
            print(f"  Skill Hub: [FAIL] {e}")

    # Channel B: Web Search
    web_engine = _import_web_search()
    if web_engine:
        try:
            queries = _generate_search_queries(ctx["skill_name"])
            web_cases = []
            seen_urls = set()
            seen_titles = set()
            for q in queries:
                results = web_engine(q, size=5)
                for r in results:
                    url = r.get("url", "")
                    title = r.get("title", "").strip()
                    if url and url not in seen_urls and title not in seen_titles:
                        seen_urls.add(url)
                        seen_titles.add(title or url)
                        web_cases.append({
                            "source": "web",
                            "type": "web_article",
                            "title": title,
                            "url": url,
                            "snippet": r.get("snippet", "")[:300]
                        })
            all_cases.extend(web_cases)
            print(f"  Web Search: {len(web_cases)} unique results")
        except Exception as e:
            print(f"  Web Search: [FAIL] {e}")
    else:
        print("  Web Search: engine unavailable")

    # Inherit previous cases
    if os.environ.get("SKILL_FORCE_REFRESH") != "1":
        inherited = dir_manager.get_latest_cases(ctx["skill_name"])
        if inherited:
            seen_keys = {c.get("url") or c.get("key") or "" for c in all_cases}
            added = 0
            for c in inherited:
                key = c.get("url") or c.get("key") or ""
                if key and key not in seen_keys:
                    all_cases.append(c)
                    seen_keys.add(key)
                    added += 1
            print(f"  Inherited from prev revision: +{added} cases")

    # Save
    cases_file = ctx["rev_dir"] / "cases" / "all_cases.json"
    with open(cases_file, "w", encoding="utf-8") as f:
        json.dump(all_cases, f, indent=2, ensure_ascii=False)
    ctx["cases"] = all_cases
    print(f"  Total cases: {len(all_cases)}")
    print("  [OK] Cases saved")


# ===============================================================
# Phase 3: Pattern Extraction (English only)
# ===============================================================
def _decompose_skill_name_en(skill_name: str, cases: list = None) -> list[tuple[str, int]]:
    """Generate sub-topic patterns from an English skill name."""
    words = [w for w in skill_name.replace("_", " ").replace("-", " ").split() if len(w) > 2]

    topic_map = TOPIC_MAP

    sub_patterns = []
    seen = set()
    for word in words:
        for keyword, pattern_text in topic_map.items():
            if keyword in word.lower() or keyword == word.lower():
                if keyword not in seen:
                    seen.add(keyword)
                    sub_patterns.append((pattern_text, 78))

    # Extract keywords from case titles
    case_keywords_found = set()
    cases = cases or []
    for c in cases:
        text = (c.get("title", "") + " " + c.get("snippet", "")).lower()
        for term in CASE_SCAN_KEYWORDS:
            if term in text and term not in seen:
                case_keywords_found.add(term)

    for kw in case_keywords_found:
        display = topic_map.get(kw, f"{kw.title()} related best practices ({skill_name})")
        sub_patterns.append((display, 72))
        seen.add(kw)

    if not sub_patterns:
        generic = [
            f"{skill_name} core concepts & terminology",
            f"{skill_name} common scenarios & solutions",
            f"{skill_name} toolchain & environment setup",
        ]
        sub_patterns = [(s, 70) for s in generic]

    return sub_patterns[:6]


def _extract_patterns(ctx: dict):
    """Phase 3 — Extract knowledge patterns from collected cases."""
    print(f"\n{'-' * 55}")
    print("  Phase 3: Pattern Extraction")
    print("-" * 55)

    cases = ctx.get("cases", [])
    skill_name = ctx["skill_name"]
    all_text = " ".join(
        str(v) for c in cases for v in c.values() if isinstance(v, str)
    ).lower()

    # Core pattern library (from eng_patterns_data)
    core_patterns = CORE_PATTERNS

    patterns = []
    seen_ids = set()

    # Match core patterns against case text
    for category, info in core_patterns.items():
        for kw in info["keywords"]:
            if kw in all_text:
                for principle, pid, conf in info["principles"]:
                    if pid not in seen_ids:
                        patterns.append({"id": pid, "principle": principle, "confidence": conf, "level": "basic"})
                        seen_ids.add(pid)
                break

    # Add domain patterns from skill name decomposition
    sub_ideas = _decompose_skill_name_en(skill_name, cases=cases)
    for i, (sub_name, conf) in enumerate(sub_ideas):
        pid = f"P_domain_{i+1}"
        if pid not in seen_ids:
            patterns.append({
                "id": pid,
                "principle": sub_name,
                "confidence": conf,
                "level": "domain"
            })
            seen_ids.add(pid)

    # Inherit patterns from previous version
    if os.environ.get("SKILL_FORCE_REFRESH") != "1":
        inherited = dir_manager.get_latest_patterns(skill_name)
        if inherited:
            added = 0
            for p in inherited:
                pid = p.get("id")
                if pid and pid not in seen_ids:
                    patterns.append({
                        "id": pid, "principle": p["principle"],
                        "confidence": max(p.get("confidence", 50) - 5, 50),
                        "level": "inherited"
                    })
                    seen_ids.add(pid)
                    added += 1
            print(f"  Inherited: +{added} patterns from prev revision")

    if not patterns:
        # Fallback: generate generic patterns
        patterns = [
            {"id": "P_generic_1", "principle": f"Core concepts of {skill_name}", "confidence": 70, "level": "basic"},
            {"id": "P_generic_2", "principle": f"Best practices for {skill_name} setup", "confidence": 70, "level": "basic"},
            {"id": "P_generic_3", "principle": f"Common pitfalls in {skill_name}", "confidence": 65, "level": "basic"},
        ]

    # Save
    patterns_file = ctx["rev_dir"] / "patterns" / "knowledge_patterns.json"
    with open(patterns_file, "w", encoding="utf-8") as f:
        json.dump(patterns, f, indent=2, ensure_ascii=False)
    ctx["patterns"] = patterns
    print(f"  Patterns extracted: {len(patterns)}")
    for p in patterns:
        print(f"    [{p['level']:>9}] {p['principle'][:60]}")
    print("  [OK] Patterns saved")


# ===============================================================
# Phase 4: Generate Assessment Tool
# ===============================================================
def _generate_assessment(ctx: dict):
    """Phase 4 — Generate an inline assessment script."""
    print(f"\n{'-' * 55}")
    print("  Phase 4: Generate Assessment")
    print("-" * 55)

    patterns = ctx.get("patterns", [])
    case_count = len(ctx.get("cases", []))
    skill_name = ctx["skill_name"]
    version = ctx["version"]

    # Build questions from patterns
    questions = []
    pattern_texts = [p.get("principle", "?") for p in patterns]
    n = len(pattern_texts)
    generic_fillers = [
        "Clean up temp files regularly to free disk space",
        "Use type annotations to improve code readability",
        "Add unit tests to ensure code quality",
        "Document API endpoints for team collaboration",
    ]

    for i, p in enumerate(patterns):
        principle = p.get("principle", "")
        scenario = pattern_texts[(i + 1) % n][:60] if n > 1 else principle[:60]
        correct_text = principle[:60]

        others = [pattern_texts[j][:60] for j in range(n) if j != i and j != (i + 1) % n]
        random.shuffle(others)
        wrongs = others[:3]
        while len(wrongs) < 3:
            wrongs.append(generic_fillers[len(wrongs) % len(generic_fillers)])

        options = wrongs + [correct_text]
        random.shuffle(options)
        correct_idx = options.index(correct_text)
        labels = ["A", "B", "C", "D"]

        questions.append({
            "q": f"Which approach is best for: {scenario}?",
            "a": options[0], "b": options[1], "c": options[2], "d": options[3],
            "answer": labels[correct_idx],
            "explain": f"Best practice: {principle}"
        })

    # Generate assess.py via template
    assess_code = render_assess_code(
        version=version, skill_name=skill_name,
        patterns=patterns, questions=questions,
        case_count=case_count
    )

    assess_file = ctx["rev_dir"] / "tools" / "assess.py"
    with open(assess_file, "w", encoding="utf-8") as f:
        f.write(assess_code)

    ctx["assess_file"] = assess_file
    print(f"  Generated: tools/assess.py ({len(questions)} questions)")
    print("  [OK] Assessment generated")


# ===============================================================
# Phase 5: Validation & Report
# ===============================================================
def _phase5_validate(ctx: dict):
    """Phase 5 — Run validation and generate learning report."""
    print(f"\n{'-' * 55}")
    print("  Phase 5: Validation & Report")
    print("-" * 55)

    assess_file = ctx.get("assess_file")
    if assess_file and assess_file.exists():
        try:
            result = subprocess.run(
                [sys.executable, str(assess_file)],
                capture_output=True, text=True, timeout=60,
                cwd=str(ctx["rev_dir"])
            )
            print(result.stdout)
            if result.stderr:
                print(f"  [STDERR] {result.stderr[:200]}")

            # Parse overall score from output
            score = 0.0
            for line in result.stdout.split("\n"):
                if "Overall Score:" in line:
                    try:
                        score = float(line.split(":")[1].strip().split("/")[0])
                    except ValueError:
                        pass
            ctx["score"] = score
            print(f"  Validation score: {score:.1f}/100")
        except subprocess.TimeoutExpired:
            print("  [FAIL] Validation timed out")
            ctx["score"] = 0
        except Exception as e:
            print(f"  [FAIL] Validation error: {e}")
            ctx["score"] = 0
    else:
        print("  No assess.py found, skipping validation")
        ctx["score"] = 0

    # Generate learning report
    report = f"""# Learning Report: {ctx['skill_name']} (rev{ctx['version']})

## Summary
- **Skill**: {ctx['skill_name']}
- **Version**: rev{ctx['version']}
- **Date**: 2026-05-15
- **Cases collected**: {len(ctx.get('cases', []))}
- **Patterns extracted**: {len(ctx.get('patterns', []))}
- **Validation score**: {ctx.get('score', 0):.1f}/100

## Patterns
"""
    for p in ctx.get("patterns", []):
        report += f"- [{p.get('level', 'basic')}] {p.get('principle', '?')} (confidence: {p.get('confidence', 0)})\n"

    report += f"""
## Next Steps
1. Review extracted patterns and adjust confidence levels if needed
2. Add more targeted web searches for uncovered topics
3. Re-run learning with `--force` for a fresh start
4. Apply learned patterns in real projects
"""

    report_file = ctx["rev_dir"] / "reports" / "learning_report.md"
    with open(report_file, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"  Report saved: reports/learning_report.md")
    print(f"  [OK] rev{ctx['version']} complete!")


# ===============================================================
# Main Orchestrator
# ===============================================================
def run(skill_name: str, dry_run: bool = False, force: bool = False) -> dict:
    """
    Run the full 5-phase skill learning pipeline.

    Args:
        skill_name: English skill name to learn (e.g., "docker_compose_production")
        dry_run: If True, only show what would be done
        force: If True, skip inherited patterns/cases

    Returns:
        Context dict with all phase results
    """
    if force:
        os.environ["SKILL_FORCE_REFRESH"] = "1"

    ctx = {
        "skill_name": skill_name,
        "version": 0,
        "rev_dir": None,
        "cases": [],
        "patterns": [],
        "score": 0,
        "dry_run": dry_run,
    }

    if dry_run:
        print(f"\n{'=' * 55}")
        print(f"  DRY RUN: {skill_name}")
        print(f"{'=' * 55}")
        version = dir_manager.next_version(skill_name)
        rev_dir = dir_manager.get_skill_dir(skill_name) / f"rev{version}"
        print(f"  Would create: {rev_dir}")
        print(f"  Would run: Phase 1-5 pipeline")
        print(f"  [OK] Dry run complete (no changes made)")
        return ctx

    _ensure_env(ctx)
    _phase1_define(ctx)
    _phase2_search(ctx)
    _extract_patterns(ctx)
    _generate_assessment(ctx)
    _phase5_validate(ctx)

    return ctx
