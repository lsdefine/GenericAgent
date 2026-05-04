#!/usr/bin/env python3
"""
L4 Vectorizer: Scans L4 raw sessions, creates embeddings (mock if no model), and indexes them.
Since we might not have a local embedding model, this script:
1. Reads JSON files from ../memory/L4_raw_sessions/
2. Extracts user/agent text.
3. Saves a semantic index in a local SQLite or JSON file.
"""
import os
import json
import sqlite3
import hashlib

L4_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'memory', 'L4_raw_sessions')
INDEX_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'l4_session_index.db')

def init_db():
    conn = sqlite3.connect(INDEX_DB)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS sessions
                 (id TEXT PRIMARY KEY, title TEXT, summary TEXT, timestamp TEXT, raw_path TEXT)''')
    conn.commit()
    return conn

def process_sessions():
    if not os.path.exists(L4_PATH):
        print("L4 path not found:", L4_PATH)
        return

    conn = init_db()
    c = conn.cursor()
    files = [f for f in os.listdir(L4_PATH) if f.endswith('.json')]
    print(f"Scanning {len(files)} session files...")

    for f in files:
        fpath = os.path.join(L4_PATH, f)
        try:
            with open(fpath, 'r') as fh:
                data = json.load(fh)
            
            # Extract simple summary/stats
            sid = data.get('id', f)
            title = data.get('title', 'Unknown')
            raw_text = json.dumps(data)[:2000] # Just for demo
            
            # Generate a simple hash as "mock embedding"
            mock_vec = hashlib.md5(raw_text.encode()).hexdigest()
            
            c.execute("INSERT OR REPLACE INTO sessions VALUES (?, ?, ?, ?, ?)", 
                      (sid, title, mock_vec, data.get('timestamp', ''), fpath))
        except Exception as e:
            print(f"Error processing {f}: {e}")
            
    conn.commit()
    conn.close()
    print(f"Indexed {len(files)} sessions to {INDEX_DB}")

if __name__ == '__main__':
    process_sessions()
