"""Extract the highest numeric version from releases, with strict archive checks."""
from pathlib import Path, PurePosixPath
import re, zipfile, shutil, json, sys, os

def extract(root):
    candidates=[]
    for path in (root/'releases').glob('no-alias-invoices-v*.zip'):
        match=re.fullmatch(r'no-alias-invoices-v(\d+(?:\.\d+){1,2})\.zip',path.name)
        if match:candidates.append((tuple(map(int,match[1].split('.'))),match[1],path))
    if not candidates:raise ValueError('Upload a versioned ZIP into releases/.')
    _,version,path=max(candidates)
    target=root/'_build'
    if target.exists():shutil.rmtree(target)
    target.mkdir()
    with zipfile.ZipFile(path) as z:
        entries=[i for i in z.infolist() if not i.is_dir()]
        if sum(i.file_size for i in entries)>32*1024*1024:raise ValueError('Archive is too large')
        for i in entries:
            name=PurePosixPath(i.filename)
            if name.is_absolute() or '..' in name.parts or '\\' in i.filename:raise ValueError('Unsafe path')
            if (i.external_attr>>16)&0o170000==0o120000:raise ValueError('Symlinks are not allowed')
            if not name.parts or name.parts[0]!='no-alias-invoices':raise ValueError('ZIP must contain one no-alias-invoices folder')
            rel=PurePosixPath(*name.parts[1:])
            if rel.suffix in ('.sqlite3','.db','.pyc') or '__pycache__' in rel.parts or rel.name in ('.env','invoice-template.docx'):raise ValueError('Private data is not allowed in the release')
            dest=target/str(rel);dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(z.read(i))
    if (target/'VERSION').read_text().strip()!=version:raise ValueError('Filename and VERSION disagree')
    for required in ('app.py','documents.py','Dockerfile','templates/invoice.docx','static/index.html'):
        if not (target/required).is_file():raise ValueError('Missing '+required)
    (target/'VERSION').write_text(version+'\n')
    return version
if __name__=='__main__':
    version=extract(Path(__file__).resolve().parents[1])
    print('Selected v'+version)
    if os.getenv('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'],'a') as f:f.write('version='+version+'\n')
