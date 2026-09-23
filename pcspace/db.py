"""Compact directory index plus the existing SQLite action/history ledger."""
from __future__ import annotations
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA='''
CREATE TABLE IF NOT EXISTS scans(id TEXT PRIMARY KEY,root TEXT NOT NULL,started REAL NOT NULL,
 ended REAL,status TEXT NOT NULL,files INTEGER DEFAULT 0,logical_bytes INTEGER DEFAULT 0,
 allocated_bytes INTEGER DEFAULT 0,unknown_alloc INTEGER DEFAULT 0,skipped INTEGER DEFAULT 0,
 errors INTEGER DEFAULT 0,current_path TEXT DEFAULT '',note TEXT DEFAULT '',policy_hash TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS tree(scan_id TEXT NOT NULL,path TEXT NOT NULL,parent TEXT NOT NULL,
 own_bytes INTEGER DEFAULT 0,own_files INTEGER DEFAULT 0,own_candidates INTEGER DEFAULT 0,
 logical_bytes INTEGER DEFAULT 0,files INTEGER DEFAULT 0,candidate_bytes INTEGER DEFAULT 0,
 done INTEGER DEFAULT 0,PRIMARY KEY(scan_id,path));
CREATE INDEX IF NOT EXISTS tree_parent ON tree(scan_id,parent,logical_bytes DESC);
CREATE TABLE IF NOT EXISTS scan_queue(scan_id TEXT NOT NULL,path TEXT NOT NULL,PRIMARY KEY(scan_id,path));
CREATE TABLE IF NOT EXISTS issues(id INTEGER PRIMARY KEY,scan_id TEXT NOT NULL,path TEXT NOT NULL,reason TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS plans(id TEXT PRIMARY KEY,created REAL NOT NULL,action TEXT NOT NULL,
 status TEXT NOT NULL,policy_hash TEXT NOT NULL,items TEXT NOT NULL,results TEXT DEFAULT '[]',
 before_space TEXT DEFAULT '{}',after_space TEXT DEFAULT '{}');
CREATE TABLE IF NOT EXISTS operation_entries(plan_id TEXT NOT NULL,path TEXT NOT NULL,is_dir INTEGER NOT NULL,
 snapshot TEXT NOT NULL,PRIMARY KEY(plan_id,path));
CREATE TABLE IF NOT EXISTS disk_history(id INTEGER PRIMARY KEY,sampled REAL NOT NULL,root TEXT NOT NULL,total INTEGER NOT NULL,free INTEGER NOT NULL);
'''
class Database:
    def __init__(self,path:Path):
        self.path=path
        with self.connect() as c:
            c.executescript(SCHEMA)
            cols={r['name'] for r in c.execute('PRAGMA table_info(scans)')}
            for name,decl in [('engine',"TEXT NOT NULL DEFAULT 'legacy'"),('stale','INTEGER NOT NULL DEFAULT 0')]:
                if name not in cols:c.execute(f'ALTER TABLE scans ADD COLUMN {name} {decl}')
            c.execute("UPDATE scans SET status='paused',note='앱 재시작: 이어서 분석할 수 있습니다.' WHERE status='running' AND engine='tree2'")
            c.execute("UPDATE scans SET status='interrupted' WHERE status='running' AND engine!='tree2'")
            c.execute("UPDATE plans SET status='needs_review' WHERE status IN ('applying','preparing')")
            # Preserve old scan snapshots without reprocessing a million file rows.
            if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='folders'").fetchone():
                c.execute('''INSERT OR IGNORE INTO tree(scan_id,path,parent,logical_bytes,files,done)
                  SELECT scan_id,path,parent,logical_bytes,files,1 FROM folders''')

    @contextmanager
    def connect(self):
        c=sqlite3.connect(self.path,timeout=20)
        c.row_factory=sqlite3.Row
        c.execute('PRAGMA journal_mode=WAL');c.execute('PRAGMA busy_timeout=20000')
        try:yield c;c.commit()
        except BaseException:c.rollback();raise
        finally:c.close()
    def rows(self,sql,args=()):
        with self.connect() as c:return [dict(r) for r in c.execute(sql,args)]
    def one(self,sql,args=()):
        with self.connect() as c:
            r=c.execute(sql,args).fetchone();return dict(r) if r else None
    def execute(self,sql,args=()):
        with self.connect() as c:return c.execute(sql,args).lastrowid

def encode(x):return json.dumps(x,ensure_ascii=False,separators=(',',':'))
