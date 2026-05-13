#!/usr/bin/env python3
"""Git 实操测试 — 临时仓库验证 git 操作能力"""
import json, sys, tempfile, subprocess


def run(cmd, cwd=None):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=15, cwd=cwd)


def main():
    result = {"score": 0, "passed": False, "note": ""}
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            # init（显式设置默认分支名）
            run(["git", "-c", "init.defaultBranch=main", "init"], tmpdir)
            run(["git", "config", "user.email", "t@t.com"], tmpdir)
            run(["git", "config", "user.name", "T"], tmpdir)

            # commit 1: initial
            with open(tmpdir + "/a.txt", "w") as f:
                f.write("hello")
            run(["git", "add", "."], tmpdir)
            run(["git", "commit", "-m", "init"], tmpdir)

            # branch + switch + commit 2
            run(["git", "checkout", "-b", "feature"], tmpdir)
            with open(tmpdir + "/b.txt", "w") as f:
                f.write("feature work")
            run(["git", "add", "."], tmpdir)
            run(["git", "commit", "-m", "feat: add feature"], tmpdir)

            # back to main
            run(["git", "checkout", "main"], tmpdir)

            # log check: 2 branches, 2 commits
            r = run(["git", "log", "--oneline", "--all"], tmpdir)
            commits = [l for l in r.stdout.strip().split("\n") if l]
            assert len(commits) == 2, f"期望2个提交, 实际{len(commits)}"

            # branch list
            r = run(["git", "branch", "-a"], tmpdir)
            branches = [l.strip().replace("*", "").strip() for l in r.stdout.strip().split("\n") if l.strip()]
            assert "main" in branches, "缺少 main 分支"
            assert "feature" in branches, "缺少 feature 分支"

            result["score"] = 100
            result["passed"] = True
            result["note"] = "Git 实操测试通过！分支创建/切换/提交/日志查看全部正确"
    except AssertionError as e:
        result["score"] = 50
        result["note"] = f"Git 测试: {e}"
    except Exception as e:
        result["score"] = 30
        result["note"] = f"Git 测试异常: {e}"

    print(json.dumps(result))
    sys.exit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
