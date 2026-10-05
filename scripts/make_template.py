from pathlib import Path
import sys,xml.etree.ElementTree as ET
root=Path(__file__).resolve().parents[1]
p=root/'unraid/my-no-alias-invoices.xml';tree=ET.parse(p)
image=sys.argv[1].lower()
tree.getroot().find('Repository').text=image+':latest'
tree.getroot().find('Project').text='https://github.com/'+image.removeprefix('ghcr.io/')
tree.write(p,encoding='utf-8',xml_declaration=True)
