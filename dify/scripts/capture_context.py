import argparse, json
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError

parser=argparse.ArgumentParser(description='Capture real PowerContext context for a Dify debug scope; never records the token.')
parser.add_argument('--scope', required=True)
parser.add_argument('--env', default='D:/DifyDemo/runtime/server.env')
parser.add_argument('--url', default='http://127.0.0.1:8017')
parser.add_argument('--out', default='powercontext-context.json')
args=parser.parse_args()
token=next(line.split('=',1)[1] for line in Path(args.env).read_text(encoding='utf-8').splitlines() if line.startswith('POWERCONTEXT_SERVER_AUTH_TOKEN='))
payload={'scope_id':args.scope,'query':'\u4fee\u706f \u98ce\u706f \u627f\u8bfa \u8bb0\u53f7','max_bytes':8000,'assembly':{'sections':[{'family':'memory','limit':6}]}}
req=Request(args.url.rstrip('/')+'/v1/context/prepare',data=json.dumps(payload,ensure_ascii=False).encode(),headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'},method='POST')
with urlopen(req,timeout=30) as response:
    record={'request':payload,'http_status':response.status,'response':json.load(response)}
Path(args.out).write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
print('Saved response; token omitted. Status:',record['response']['status'])