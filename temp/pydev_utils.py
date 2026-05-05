#!/usr/bin/env python3
"""Python Dev Utilities - Niche Tool Integration"""
import os, sys, time, subprocess, json, logging
logging.basicConfig(level=logging.INFO)

class CodeMetricsAnalyzer:
    """Analyze code quality metrics"""
    def analyze_file(self, filepath):
        with open(filepath, 'r') as f:
            lines = f.readlines()
        n_lines = len(lines)
        n_blanks = sum(1 for l in lines if not l.strip())
        n_comments = sum(1 for l in lines if l.strip().startswith('#'))
        n_funcs = sum(1 for l in lines if 'def ' in l)
        n_classes = sum(1 for l in lines if 'class ' in l)
        return {
            "file": filepath,
            "total_lines": n_lines,
            "code_lines": n_lines - n_blanks - n_comments,
            "blank_lines": n_blanks,
            "comment_lines": n_comments,
            "functions": n_funcs,
            "classes": n_classes,
            "complexity_ratio": round((n_funcs + n_classes) / max(n_lines - n_blanks, 1), 3)
        }

class DependencyAnalyzer:
    """Analyze module dependencies"""
    def __init__(self):
        self.imports = {}

    def scan_directory(self, directory="."):
        for f in os.listdir(directory):
            if f.endswith('.py') and f != 'pydev_utils.py':
                path = os.path.join(directory, f)
                self.imports[f] = self._extract_imports(path)
        return self.imports

    def _extract_imports(self, filepath):
        imports = []
        with open(filepath, 'r') as f:
            for line in f:
                line = line.strip()
                if line.startswith('import ') or line.startswith('from '):
                    imports.append(line)
        return imports

class LogParser:
    """Utility for parsing and analyzing log files"""
    @staticmethod
    def parse_access_log(filepath, max_lines=1000):
        """Simple log parser pattern"""
        patterns = {"ERROR": 0, "WARNING": 0, "INFO": 0}
        with open(filepath, 'r') as f:
            for i, line in enumerate(f):
                if i >= max_lines:
                    break
                for level in patterns:
                    if level in line:
                        patterns[level] += 1
        return patterns

if __name__ == "__main__":
    cma = CodeMetricsAnalyzer()
    result = cma.analyze_file("model_registry.py")
    logging.info(f"Code metrics: {result}")
    
    da = DependencyAnalyzer()
    deps = da.scan_directory(".")
    logging.info(f"Found imports for {len(deps)} files")
