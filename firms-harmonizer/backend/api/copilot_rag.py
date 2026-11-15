"""Local FTS5/BM25 retrieval over explicitly approved public scientific notes."""
from functools import lru_cache
import json
from pathlib import Path
import re
import sqlite3

ROOT=Path(__file__).resolve().parents[2]


@lru_cache(maxsize=1)
def documents():
    # This is an explicit public knowledge source, not a repository search.
    # Development reports, test outputs, logs and arbitrary added JSON files must
    # never become scientific evidence or enter the model context.
    path = ROOT / 'data/copilot_knowledge/science.json'
    return json.loads(path.read_text(encoding='utf-8'))



@lru_cache(maxsize=4)
def _index(fingerprint):
    conn=sqlite3.connect(':memory:',check_same_thread=False)
    conn.execute('CREATE VIRTUAL TABLE notes USING fts5(id UNINDEXED,title,url UNINDEXED,text,tokenize="unicode61 remove_diacritics 2")')
    for record in json.loads(fingerprint):
        conn.execute('INSERT INTO notes VALUES(?,?,?,?)',[record['id'],record['title'],record['url'],record['text']])
    conn.commit()
    return conn


def search(query:str,limit:int=4):
    # Query words are quoted, never executed as FTS operators or SQL fragments.
    stop={'what','does','mean','the','of','is','are','this','that','here','and','for','in','to','known','how','much','was','it','me','que','por','se','la','el','de','un','una'}
    words=list(dict.fromkeys(re.findall(r'[^\W_]{2,}',query.lower(),re.UNICODE)))
    words=[w for w in words if w not in stop][:30]
    if not words:
        return []
    data=json.dumps(documents(),ensure_ascii=False,sort_keys=True)
    conn=_index(data)
    rows=conn.execute("SELECT id,title,url,text FROM notes WHERE notes MATCH ? ORDER BY CASE WHEN id LIKE 'K%' THEN 0 ELSE 1 END,bm25(notes) LIMIT ?",
        [' OR '.join('"'+w+'"' for w in words),max(1,min(limit,5))]).fetchall()
    return [dict(zip(('id','title','url','text'),row)) for row in rows]
