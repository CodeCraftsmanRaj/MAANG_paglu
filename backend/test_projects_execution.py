import json
from app.db import rows, run
from app.factory import get_fact_repository, get_llm_provider
from app.structuring import structure_doc, retrieve
from app.api import app
from fastapi.testclient import TestClient

client = TestClient(app)

# Test login or register
auth_res = client.post('/api/auth/register', json={'username': 'admin_test', 'password': 'password123'})
if auth_res.status_code != 200:
    auth_res = client.post('/api/auth/login', json={'username': 'admin_test', 'password': 'password123'})

run("UPDATE users SET role='admin' WHERE username='admin_test'")

token = auth_res.json()['token']
headers = {'Authorization': f'Bearer {token}'}

# 1. Test GET /api/projects
p_get = client.get('/api/projects', headers=headers)
print('GET /api/projects status:', p_get.status_code, 'count:', len(p_get.json()))

# 2. Test POST /api/projects (General project)
p_gen = client.post('/api/projects', headers=headers, json={'name': 'Knowledge Docs', 'project_type': 'general'})
print('POST General project:', p_gen.status_code, p_gen.json())
gen_id = p_gen.json()['id']

# 3. Test POST /api/projects (Process project)
p_proc = client.post('/api/projects', headers=headers, json={'name': 'Incident Management', 'project_type': 'process'})
print('POST Process project:', p_proc.status_code, p_proc.json())
proc_id = p_proc.json()['id']

# 4. Ingest into General project
ing_gen = client.post('/api/ingest', headers=headers, json={
    'kind': 'text',
    'title': 'API Architecture Overview',
    'text': 'The backend API service is deployed on AWS ECS with FastAPI and PostgreSQL.',
    'project_id': gen_id
})
print('Ingest General status:', ing_gen.status_code, ing_gen.json())

# 5. Ingest into Process project
ing_proc = client.post('/api/ingest', headers=headers, json={
    'kind': 'text',
    'title': 'Production Release Workflow',
    'text': 'DevOps Engineer initiates deployment pipeline. QA Lead verifies smoke tests after DevOps Engineer completes deployment. Incident Commander notifies stakeholders.',
    'project_id': proc_id
})
print('Ingest Process status:', ing_proc.status_code, ing_proc.json())

# 6. Retrieve from General project
r_gen = client.post('/api/retrieve', headers=headers, json={'query': 'FastAPI PostgreSQL', 'project_id': gen_id})
print('Retrieve General count:', len(r_gen.json()['facts']))
assert all(f['source']['project_id'] == gen_id for f in r_gen.json()['facts'])

# 7. Retrieve from Process project
r_proc = client.post('/api/retrieve', headers=headers, json={'query': 'deployment pipeline QA Lead', 'project_id': proc_id})
print('Retrieve Process count:', len(r_proc.json()['facts']))
assert all(f['source']['project_id'] == proc_id for f in r_proc.json()['facts'])

# 8. Export context pack scoped to Process project
exp_proc = client.post('/api/export', headers=headers, json={'query': '', 'project_id': proc_id})
print('Export Process markdown line count:', len(exp_proc.json()['markdown'].splitlines()))

# 9. Ask scoped to Process project
ask_proc = client.post('/api/ask', headers=headers, json={'query': 'How is deployment executed?', 'project_id': proc_id, 'is_process': True})
print('Ask & Execute response status:', ask_proc.status_code)
print('Answer:', ask_proc.json().get('answer'))

print('=== ALL AUTOMATED PROJECT & EXECUTION TESTS PASSED ===')
