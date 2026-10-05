import urllib.request, json, time
URL='http://127.0.0.1:18085'
for attempt in range(60):
    try:
        with urllib.request.urlopen(URL+'/health',timeout=2) as r:assert r.status==200
        break
    except Exception:
        if attempt==59:raise
        time.sleep(1)
with urllib.request.urlopen(URL+'/api/state') as r:state=json.load(r)
assert state['next']=='0001' and not state['contacts'] and not state['invoices']
assert all(not state['settings'][k] for k in ('name','address','phone','email','account_number','sort_code'))
data=dict(customer='Sample Customer',date='2026-01-01',deposit='0',lines=[dict(date='2026-01-01',venue='Sample Venue',service='Sample Service',fee='100')])
req=urllib.request.Request(URL+'/api/preview',data=json.dumps(data).encode(),headers={'Content-Type':'application/json'})
with urllib.request.urlopen(req,timeout=120) as r:assert r.read().startswith(b'%PDF')
data['lines'] = [dict(date='2026-01-01',venue='Sample Venue',service=f'Sample Service {i+1}',fee='100') for i in range(7)]
req=urllib.request.Request(URL+'/api/preview',data=json.dumps(data).encode(),headers={'Content-Type':'application/json'})
with urllib.request.urlopen(req,timeout=120) as r:assert r.read().startswith(b'%PDF')
print('Startup, blank defaults and one/seven-service PDF generation passed')

contact=dict(kind='customer',name='Numbering Test',address='',separate_numbering=True,invoice_prefix='TEST-',next_invoice_number=169)
def post_json(path,body):
    req=urllib.request.Request(URL+path,data=json.dumps(body).encode(),headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=120) as r:return json.load(r)
post_json('/api/contacts',contact)
data['customer']='Numbering Test';data['token']='smoke-contact-numbering'
saved=post_json('/api/invoices',data)
assert saved['number']=='TEST-0169' and 'warning' not in saved
assert post_json('/api/invoices',data)==saved
with urllib.request.urlopen(URL+'/api/state') as r:state=json.load(r)
assert state['next']=='0001' and state['contacts'][0]['next_invoice_number']==170
post_json('/api/invoices/remove-latest-test',dict(id=saved['id'],confirm=saved['number']))
with urllib.request.urlopen(URL+'/api/state') as r:state=json.load(r)
assert state['next']=='0001' and state['contacts'][0]['next_invoice_number']==169 and not state['invoices']
print('Per-contact numbering, main-counter isolation, retry and test-reset checks passed')
