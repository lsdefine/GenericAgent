#!/usr/bin/env python3
"""Memory Archive Manager"""
import os, shutil, json, datetime
logging.basicConfig(level=logging.INFO)

class MemoryArchiver:
    def __init__(self, memory_dir="../memory", archive_dir="../memory/archive"):
        self.memory_dir = memory_dir
        self.archive_dir = archive_dir
        os.makedirs(archive_dir, exist_ok=True)

    def archive_old(self, days=30):
        cutoff = datetime.datetime.now() - datetime.timedelta(days=days)
        for fname in os.listdir(self.memory_dir):
            if fname.endswith('.py') or fname.endswith('.md'):
                path = os.path.join(self.memory_dir, fname)
                mtime = datetime.datetime.fromtimestamp(os.path.getmtime(path))
                if mtime < cutoff:
                    dest = os.path.join(self.archive_dir, fname)
                    logging.info(f"Archiving {fname} -> {dest}")
        return True

if __name__ == "__main__":
    archiver = MemoryArchiver()
    archiver.archive_old()
