"""Scan source artifacts without printing any matched secret material."""
from pathlib import Path
import json
import re
import sys
ROOT = Path(__file__).resolve().parents[1]
EXCLUDE = {'tools','build','.dart_tool','node_modules','.gradle','.git','raw','processed','__pycache__','.pytest_cache'}
private_key = re.compile('-----BEGIN '+r'(?:RSA |EC )?PRIVATE KEY-----')
bad = []
for path in ROOT.rglob('*'):
    if not path.is_file() or any(p in EXCLUDE for p in path.relative_to(ROOT).parts):
        continue
    if path.suffix.lower() not in {'.py','.dart','.json','.yaml','.yml','.md','.rules','.ps1','.cmd','.txt','.example'} and path.name!='.env':
        continue
    text = path.read_text(encoding='utf-8-sig',errors='ignore')
    if private_key.search(text):
        bad.append(str(path.relative_to(ROOT)))
    if path.suffix=='.json':
        try:
            data=json.loads(text)
            if isinstance(data,dict) and data.get('type')=='service_account' and data.get('private_key'):
                bad.append(str(path.relative_to(ROOT)))
        except ValueError:
            pass
    if path.name=='.env':bad.append(str(path.relative_to(ROOT)))
result={'status':'FAIL' if bad else 'PASS','sensitive_file_paths':sorted(set(bad)),
        'scope':'source and docs; generated caches excluded; public Firebase Android API key is not an Admin credential'}
(ROOT/'docs/secrets-scan.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps(result,indent=2))
sys.exit(bool(bad))
