from pathlib import Path
import json
import yaml

root=Path(__file__).resolve().parents[1]
path=root/'dify-app.yml'
doc=yaml.safe_load(path.read_text(encoding='utf-8'))
graph=doc['workflow']['graph']
nodes={node['id']:node['data'] for node in graph['nodes']}
assert len(nodes)==9
assert len(graph['edges'])==8
for edge in graph['edges']:
    assert edge['source'] in nodes and edge['target'] in nodes
for node_id,data in nodes.items():
    if data['type']=='code':
        compile(data['code'],node_id,'exec')
assert all(not v.get('value') for v in doc['workflow']['environment_variables'] if v['value_type']=='secret')
for other in [root/'dify-cloud.yml',*root.glob('*_*.yml'),*root.joinpath('workflows').glob('*.yml')]:
    assert yaml.safe_load(other.read_text(encoding='utf-8'))==doc, str(other)
scope_ns={};exec(nodes['n_code_scope']['code'],scope_ns)
result=scope_ns['main']('{"scope_id":"test-scope"}','quote " and newline\n')
assert isinstance(json.loads(result['read_body'])['max_bytes'],int)
event_ns={};exec(nodes['n_code_event']['code'],event_ns)
result=event_ns['main']('quote " and newline\n','test-scope')
assert json.loads(result['write_body'])['scope_id']=='test-scope'
print('PASS: 9 nodes, 8 edges, code compiles, secret values omitted, identical DSL copies, JSON serialization valid.')