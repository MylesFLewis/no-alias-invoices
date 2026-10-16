"""Create a reproducible, public-safe release ZIP from the tracked app sources."""
from pathlib import Path
import re
import zipfile

ROOT=Path(__file__).resolve().parents[1]
from select_release import extract
extract(ROOT)
SOURCE=ROOT/'_build'
VERSION=(SOURCE/'VERSION').read_text().strip()
if not re.fullmatch(r'\d+\.\d+(?:\.\d+)?',VERSION):raise ValueError('Invalid version')
files=['.dockerignore','CHANGELOG.md','Dockerfile','VERSION','app.py','documents.py','invoice_mail.py','booking_import.py','email_templates.py','microsoft_graph.py','connect_microsoft.py','bootstrap.py','requirements.txt',
       'static/app.js','static/index.html','static/style.css','static/email_editor.js','templates/invoice.docx','tests/test_invoice_email.py','tests/test_microsoft_connection.py','tests/test_email_templates.py','tests/test_booking_import.py']
target=ROOT/'releases'/('no-alias-invoices-v'+VERSION+'.zip');target.parent.mkdir(exist_ok=True)
with zipfile.ZipFile(target,'w',compression=zipfile.ZIP_DEFLATED) as archive:
    for name in files:
        info=zipfile.ZipInfo('no-alias-invoices/'+name,date_time=(2026,10,14,0,0,0))
        info.compress_type=zipfile.ZIP_DEFLATED;info.external_attr=0o100644<<16
        archive.writestr(info,(SOURCE/name).read_bytes())
print(target.name)
