"""
eng_patterns_data.py — Static pattern dictionaries for learn_skill_from_cases engine.

Extracted from engine.py to keep core logic lean and allow easy maintenance/expansion.
"""
# ============================================================
# Topic Map: skill name keyword → best-practice description
# Used by _decompose_skill_name_en() to generate domain patterns
# Keep only mainstream topics; niche ones removed.
# ============================================================
TOPIC_MAP: dict[str, str] = {
    "deploy": "Deployment automation & release management best practices",
    "production": "Production-ready configuration & environment management",
    "docker": "Containerization & Docker orchestration best practices",
    "kubernetes": "Kubernetes cluster management & pod orchestration",
    "k8s": "Kubernetes cluster management & pod orchestration",
    "api": "API design, versioning & documentation best practices",
    "rest": "RESTful API design & HTTP protocol best practices",
    "database": "Database schema design & query optimization",
    "sql": "SQL query optimization & relational data modeling",
    "python": "Python code organization & packaging best practices",
    "async": "Async programming patterns & concurrency management",
    "testing": "Test strategy & automation framework best practices",
    "monitor": "Monitoring & observability stack implementation",
    "security": "Security hardening & vulnerability management",
    "frontend": "Frontend architecture & component design patterns",
    "backend": "Backend service architecture & middleware patterns",
    "microservice": "Microservice decomposition & inter-service communication",
    "devops": "CI/CD pipeline design & infrastructure as code",
    "ci": "Continuous integration pipeline configuration",
    "cd": "Continuous deployment strategies & rollback patterns",
    "data": "Data pipeline architecture & ETL best practices",
    "machine": "Machine learning pipeline & model lifecycle management",
    "automation": "Workflow automation & task scheduling patterns",
}

# Keywords to scan from case titles (used by _decompose_skill_name_en)
CASE_SCAN_KEYWORDS: list[str] = [
    "deploy", "docker", "kubernetes", "monitoring", "testing",
    "security", "api", "database", "async", "microservice",
    "pipeline", "automation", "config", "devops", "ci", "cd",
]

# ============================================================
# Core Patterns: domain → best-practice principles
# Used by _extract_patterns() to produce knowledge patterns
# Keep only high-impact, cross-domain patterns.
# ============================================================
CORE_PATTERNS: dict[str, dict] = {
    "production": {
        "keywords": ["production", "deploy", "prod", "release"],
        "principles": [
            ("Use environment variables / config files to separate environments", "P_env_separation", 89),
            ("Pin dependency versions to avoid unexpected upgrades", "P_pin_version", 94),
            ("Set resource limits to prevent single service starvation", "P_resource_limits", 85),
        ]
    },
    "testing": {
        "keywords": ["test", "validate", "verify", "lint"],
        "principles": [
            ("Validate configuration files before deployment", "P_config_validation", 93),
            ("Write unit tests for core business logic", "P_unit_test", 87),
            ("Use integration tests to verify component interactions", "P_integration_test", 85),
        ]
    },
    "security": {
        "keywords": ["security", "auth", "encrypt", "secret", "permission"],
        "principles": [
            ("Never hardcode secrets; use secret management tools", "P_secret_mgmt", 95),
            ("Apply principle of least privilege for service accounts", "P_least_privilege", 90),
            ("Enable TLS/SSL for all service communications", "P_tls", 88),
        ]
    },
    "database": {
        "keywords": ["database", "query", "index", "schema", "migration"],
        "principles": [
            ("Use database migrations for schema changes", "P_db_migration", 90),
            ("Add indexes for frequently queried columns", "P_db_index", 88),
            ("Use connection pooling to manage database connections", "P_connection_pool", 85),
        ]
    },
}


# ============================================================
# Assessment Code Generator
# Renders the self-contained assess.py script at Phase 4
# ============================================================
def render_assess_code(*, version: int, skill_name: str,
                       patterns: list, questions: list,
                       case_count: int) -> str:
    """Generate the assess.py script content as a string."""
    import json
    patterns_json = json.dumps(patterns, indent=2)
    questions_json = json.dumps(questions, indent=2)
    return f'''#!/usr/bin/env python3
"""learn_skill_from_cases rev{version} -- {skill_name} Assessment Tool
Auto-generated | Knowledge test + Pattern coverage
"""
import json, sys, os, random
from pathlib import Path

PATTERNS = {patterns_json}
QUESTIONS = {questions_json}

def run_knowledge_test():
    """Run knowledge test and compute score."""
    if not QUESTIONS:
        return 0, []
    per_q = 100.0 / len(QUESTIONS)
    score = 0
    results = []
    border = "-" * 50
    print(f"\\n{{border}}")
    print(f"  Knowledge Test ({{len(QUESTIONS)}} questions)")
    print(f"{{border}}")

    for qi, q in enumerate(QUESTIONS):
        p = PATTERNS[qi] if qi < len(PATTERNS) else {{}}
        level = p.get("level", "basic") if isinstance(p, dict) else "basic"
        confidence = p.get("confidence", 70) if isinstance(p, dict) else 70
        ok = level == "domain" or confidence >= 75
        if ok:
            print(f"  [OK] Q{{qi+1}}: {{q['q'][:60]}}")
            print(f"       -> {{q.get('explain', '')[:60]}}")
            score += per_q
            results.append(True)
        else:
            print(f"  [!] Q{{qi+1}}: {{q['q'][:60]}}")
            print(f"       -> SKIP (low confidence)")
            results.append(False)
    return score, results

def run_pattern_coverage():
    """Check which patterns are covered by cases."""
    covered = 0
    for p in PATTERNS:
        print(f"  [{{'OK' if p.get('level') != 'basic' else '??'}}] {{p.get('principle', '?')[:60]}}")
        if p.get('level') != 'basic':
            covered += 1
    total = len(PATTERNS) or 1
    return (covered / total) * 100

def main():
    print(f"\\n{{'='*55}}")
    print(f"  Assessment: rev{version} -- {skill_name}")
    print(f"{{'='*55}}")
    print(f"  Cases collected: {case_count}")
    print(f"  Patterns extracted: {{len(PATTERNS)}}")

    knowledge_score, _ = run_knowledge_test()
    coverage_score = run_pattern_coverage()
    overall = (knowledge_score * 0.6 + coverage_score * 0.4)

    print(f"\\n{{'='*55}}")
    print(f"  RESULTS")
    print(f"{{'='*55}}")
    print(f"  Knowledge Test: {{knowledge_score:.1f}}/100")
    print(f"  Pattern Coverage: {{coverage_score:.1f}}/100")
    print(f"  Overall Score: {{overall:.1f}}/100")
    print(f"{{'='*55}}\\n")
    return overall

if __name__ == "__main__":
    main()
'''
