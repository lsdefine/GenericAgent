#!/usr/bin/env python3
"""Memory Audit & Compression Tool"""
import os, json, logging
logging.basicConfig(level=logging.INFO)

class MemoryAuditor:
    def __init__(self, memory_dir="../memory"):
        self.memory_dir = memory_dir
        self.stats = {}

    def audit(self):
        for fname in os.listdir(self.memory_dir):
            path = os.path.join(self.memory_dir, fname)
            if os.path.isfile(path):
                size = os.path.getsize(path)
                with open(path, 'r', errors='ignore') as f:
                    lines = len(f.readlines())
                self.stats[fname] = {"size_kb": round(size/1024, 1), "lines": lines}
        return self.stats

    def find_duplicates(self):
        """Find files with high content overlap"""
        content_hashes = {}
        dupes = []
        for fname, stats in self.stats.items():
            path = os.path.join(self.memory_dir, fname)
            try:
                with open(path, 'r') as f:
                    content = f.read()
                h = hash(content)
                if h in content_hashes:
                    dupes.append((content_hashes[h], fname))
                else:
                    content_hashes[h] = fname
            except:
                pass
        return dupes

    def compress(self, threshold_lines=50):
        """Identify files that could be compressed"""
        candidates = [f for f, s in self.stats.items() if s["lines"] > threshold_lines]
        return candidates

    def generate_report(self):
        audit = self.audit()
        dupes = self.find_duplicates()
        candidates = self.compress()
        return {
            "audit": audit,
            "potential_duplicates": dupes,
            "compress_candidates": candidates,
            "total_files": len(audit),
            "total_size_kb": round(sum(s["size_kb"] for s in audit.values()), 1)
        }

if __name__ == "__main__":
    auditor = MemoryAuditor()
    report = auditor.generate_report()
    logging.info(f"Memory Audit: {report['total_files']} files, {report['total_size_kb']}KB")
    if report['compress_candidates']:
        logging.info(f"Compress candidates: {report['compress_candidates']}")
