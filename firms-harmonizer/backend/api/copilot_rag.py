"""Local FTS5/BM25 retrieval over versioned science notes and current ETL documentation."""
from functools import lru_cache
import json
from pathlib import Path
import re
import sqlite3

ROOT=Path(__file__).resolve().parents[2]


@lru_cache(maxsize=1)
def documents():
    records=[]
    for path in sorted((ROOT/'data/copilot_knowledge').glob('*.json')):
        records.extend(json.loads(path.read_text()))
    path=ROOT/'data/ETL_SPEC.md'
    section_no=0
    for section in re.split(r'(?m)^## ',path.read_text()):
        title=section.splitlines()[0].strip('# ') or 'ETL documentation'
        if any(word in title.lower() for word in ('test','log','verification','evidence')):
            continue
        paragraphs=[p.strip() for p in section.split('\n\n') if p.strip() and not p.startswith(('```','platform ','cachedir:','rootdir:'))]
        for paragraph in paragraphs:
            if len(paragraph)>1800:
                continue
            records.append({'id':f'E{section_no}','title':title,'url':None,'text':paragraph})
            section_no+=1
    return records


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
