"""Independent first-party chronology review; does not use Copilot retrieval code."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
from tempfile import TemporaryDirectory

import httpx
from lxml import html

ROOT=Path(__file__).resolve().parents[1]
SOURCES=[
    ('regional-spread','https://www.comunidad.madrid/noticias/2026/07/24/diaz-ayuso-es-peor-incendio-historia-comunidad-madrid-prioridad-es-salvar-vidas',
     ['confluencia','temperaturas','fuerte viento'], 'Reported spread conditions and merging fronts; no attribution of every selected thermal cell.'),
    ('operational-status','https://www.comunidad.madrid/noticias/2026/07/30/diaz-ayuso-comprueba-situacion-terreno-afectado-incendios-sierra-oeste',
     ['Situación Operativa 2','evacuadas'], 'Operational de-escalation on July 30 with continuing evacuations; this is not an extinction timestamp.'),
    ('national-order','https://www.boe.es/diario_boe/txt.php?id=BOE-A-2026-16657',
     ['estabilizado','30 de julio de 2026','puntos calientes'], 'July 30 stabilization and continuing hot-spot work; de-escalation is distinct from extinction.'),
    ('merged-identity','https://www.comunidad.madrid/medio-ambiente/montes-comunidad-madrid',
     ['24 de julio de 2026','Villa del Prado','Almorox'], 'Regional incident formed from merged fires on July 24; no automatic match to a selected satellite cell.'),
    ('restoration-chronology','https://www.comunidad.madrid/docs/2026-11/plan_rest_forestal_sierra_oeste_divulgacion_03112026.pdf',
     ['22 y el 28 de julio de 2026','varios focos'], 'Retrospective main-fire chronology; does not establish a fourteen-day official incident duration or a final extinction date.'),
]


def main():
    records=[]
    for identifier,url,needles,support in SOURCES:
        record={'id':identifier,'url':url,'checked_at_utc':datetime.now(timezone.utc).isoformat(),
                'expected_content':needles,'supports':support,'limits':'A regional report is not proof of membership in a particular thermal cell. No source here verifies a fourteen-day incident lifecycle.'}
        try:
            response=httpx.get(url,timeout=20,follow_redirects=True)
            response.raise_for_status()
            body=response.content
            record['sha256']=hashlib.sha256(body).hexdigest()
            if 'application/pdf' in response.headers.get('content-type',''):
                with TemporaryDirectory() as directory:
                    file=Path(directory)/'source.pdf';file.write_bytes(body)
                    text=subprocess.run(['pdftotext',str(file),'-'],check=True,text=True,capture_output=True).stdout
            else:
                tree=html.fromstring(body)
                for node in tree.xpath('//script|//style|//nav|//footer|//header'):
                    node.drop_tree()
                text=tree.text_content()
            normalized=' '.join(text.split())
            checks={needle:needle.casefold() in normalized.casefold() for needle in needles}
            record.update(checks=checks,result='passed' if all(checks.values()) else 'failed')
            # Retain short independently read excerpts, not entire publisher pages.
            first=needles[0]
            offset=normalized.casefold().find(first.casefold())
            record['short_excerpt']=' '.join(normalized[offset:offset+300].split()[:22]) if offset>=0 else ''
        except (httpx.HTTPError,ValueError,subprocess.SubprocessError,FileNotFoundError) as exc:
            record.update(result='blocked',reason=type(exc).__name__)
        records.append(record)
        print(identifier,record['result'],flush=True)
    output=ROOT.parent/'docs/verification/2026-11-15-copilot-quality/source-review.json'
    output.write_text(json.dumps(records,indent=2,ensure_ascii=False))
    if any(record['result']!='passed' for record in records):
        raise SystemExit(1)


if __name__=='__main__':
    main()
