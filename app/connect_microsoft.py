import os
import sys
import microsoft_graph

client_id = os.getenv('MICROSOFT_CLIENT_ID', '').strip()
if not client_id:
    print('MICROSOFT_CLIENT_ID is not configured.', file=sys.stderr)
    raise SystemExit(2)

print('No Alias Invoices - Microsoft account connection')
try:
    account = microsoft_graph.connect(client_id)
except KeyboardInterrupt:
    print('Connection cancelled.', file=sys.stderr)
    raise SystemExit(130)
except Exception as error:
    print(str(error), file=sys.stderr)
    raise SystemExit(1)
print('Connected successfully as ' + account + '.')
