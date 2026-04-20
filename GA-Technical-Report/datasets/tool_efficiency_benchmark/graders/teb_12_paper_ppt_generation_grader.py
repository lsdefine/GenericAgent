#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from pathlib import Path


def slide_text(zf: zipfile.ZipFile, name: str) -> str:
    data = zf.read(name).decode("utf-8", errors="ignore")
    parts = re.findall(r"<a:t>(.*?)</a:t>", data)
    return " ".join(parts)


def grade(workspace_path: str) -> dict:
    root = Path(workspace_path)
    ppt = root / "presentation.pptx"
    notes = root / "presentation_notes.md"

    scores: dict[str, object] = {}
    scores["ppt_created"] = ppt.exists()
    scores["notes_created"] = notes.exists()

    slide_names: list[str] = []
    if not ppt.exists():
        scores["ppt_valid"] = False
        scores["slide_count_ok"] = False
        scores["title_slide_ok"] = False
        scores["last_slide_requirements"] = False
        scores["image_present"] = False
    else:
        try:
            with zipfile.ZipFile(ppt, "r") as zf:
                names = zf.namelist()
                slide_names = sorted(
                    [n for n in names if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)]
                )
                media_names = [n for n in names if n.startswith("ppt/media/")]
                scores["ppt_valid"] = True
                scores["slide_count"] = len(slide_names)
                scores["slide_count_ok"] = 6 <= len(slide_names) <= 8
                scores["image_present"] = len(media_names) > 0

                if slide_names:
                    first_text = slide_text(zf, slide_names[0]).lower()
                    scores["title_slide_ok"] = ("dapo" in first_text) and (
                        "arxiv" in first_text or "http" in first_text
                    )

                    last_text = slide_text(zf, slide_names[-1]).lower()
                    numbered_points = len(re.findall(r"(?:\b1\b|\b2\b|\b3\b|①|②|③)", last_text))
                    has_open_question = any(
                        x in last_text for x in ["开放问题", "open question", "open questions", "question"]
                    )
                    scores["last_slide_requirements"] = numbered_points >= 3 and has_open_question
                else:
                    scores["title_slide_ok"] = False
                    scores["last_slide_requirements"] = False
        except Exception:
            scores["ppt_valid"] = False
            scores["slide_count_ok"] = False
            scores["title_slide_ok"] = False
            scores["last_slide_requirements"] = False
            scores["image_present"] = False

    if notes.exists():
        text = notes.read_text(encoding="utf-8", errors="ignore").lower()
        has_link = ("http://" in text) or ("https://" in text)
        has_slide_count = ("slide" in text and re.search(r"\b[6-8]\b", text) is not None) or (
            "页" in text and re.search(r"\b[6-8]\b", text) is not None
        )
        has_chart_page = any(x in text for x in ["chart", "figure", "图表"]) and any(
            x in text for x in ["page", "页"]
        )
        has_structure_page = any(
            x in text for x in ["structure", "architecture", "flow", "结构图", "流程图"]
        ) and any(x in text for x in ["page", "页"])
        scores["notes_content_ok"] = all([has_link, has_slide_count, has_chart_page, has_structure_page])
    else:
        scores["notes_content_ok"] = False

    completion_keys = [
        "ppt_created",
        "ppt_valid",
        "slide_count_ok",
        "notes_created",
        "notes_content_ok",
        "title_slide_ok",
        "last_slide_requirements",
        "image_present",
    ]
    final_outputs_present = ppt.exists() and notes.exists()
    task_success = all(bool(scores.get(key)) for key in completion_keys)
    scores["task_completion_score"] = round(
        sum(1.0 if bool(scores.get(key)) else 0.0 for key in completion_keys) / len(completion_keys),
        4,
    )
    scores["final_outputs_present"] = final_outputs_present
    scores["task_success"] = task_success
    return scores


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    result = grade(args.workspace)
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
