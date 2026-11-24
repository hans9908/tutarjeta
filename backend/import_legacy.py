"""Recupera perfiles editables a partir de las tarjetas HTML y vCards antiguas.
No modifica dist ni sobrescribe clientes existentes. python -m backend.import_legacy
"""
from html.parser import HTMLParser
from pathlib import Path
import json
import re
import shutil
import uuid
from backend import server


class CardParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack=[]
        self.company=[]
        self.bio=[]
        self.style=[]
        self.body=''
        self.links=[]

    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        self.stack.append((tag,attrs))
        if tag=='body': self.body=attrs.get('class','')
        if tag=='a' and 'link-btn' in attrs.get('class','').split():
            self.links.append({'href':attrs.get('href',''),'classes':attrs.get('class',''),'text':[]})
        if tag in {'img','meta','link','br','input','hr'}: self.stack.pop()

    def handle_endtag(self,tag):
        for i in range(len(self.stack)-1,-1,-1):
            if self.stack[i][0]==tag:
                del self.stack[i:];break

    def handle_data(self,text):
        if any(tag=='h1' for tag,attrs in self.stack):self.company.append(text)
        if any('bio' in attrs.get('class','').split() for tag,attrs in self.stack):self.bio.append(text)
        if any('design-chip' in attrs.get('class','').split() for tag,attrs in self.stack):self.style.append(text)
        if self.links and any(tag=='a' for tag,attrs in self.stack):self.links[-1]['text'].append(text)


def read_vcard(path):
    result={}
    if path.is_file():
        text=re.sub(r'\n[ \t]', '', path.read_text(encoding='utf-8').replace('\r\n','\n'))
        for line in text.splitlines():
            if ':' in line:
                key,value=line.split(':',1)
                result.setdefault(key.upper(),[]).append(value.replace('\\n','\n').replace('\\,',',').replace('\\;',';').replace('\\\\','\\'))
    return result


def recover(folder):
    parser=CardParser();parser.feed((folder/'index.html').read_text(encoding='utf-8'))
    vcard=read_vcard(folder/'assets/contact.vcf')
    data={key:'' for key in server.FIELDS}
    category=re.search(r'category-([a-z]+)',parser.body)
    data.update(username=folder.name,company_name=''.join(parser.company).strip(),bio=''.join(parser.bio).strip(),category=category[1] if category else 'abogados',full_name=vcard.get('FN',[''])[0],job_title=vcard.get('TITLE',[''])[0],theme_variant='Auto',design_line='Auto',links=[])
    # Old vCards sometimes use a social profile or an obsolete localhost URL as
    # the card URL. Use the actual local card route until the owner chooses hosting.
    data['final_url']=f'http://127.0.0.1:8877/cards/{folder.name}/'
    mapping={'link-whatsapp':'WhatsApp','link-phone':'Teléfono','link-linkedin':'LinkedIn','link-instagram':'Instagram','link-web':'Sitio Web','link-email':'Correo electrónico','link-tiktok':'TikTok','link-youtube':'YouTube','link-facebook':'Facebook'}
    for link in parser.links:
        href=link['href']
        if not href or href.startswith('./assets/'):continue
        name=next((name for cls,name in mapping.items() if cls in link['classes'].split()),''.join(link['text']).strip())
        if name:
            data['links'].append({'name':name,'url':href,'active':True})
        field={'Sitio Web':'primary_website','Correo electrónico':'contact_email','LinkedIn':'primary_linkedin'}.get(name)
        if field:data[field]=href.removeprefix('mailto:')
    data['contact_email']=data['contact_email'] or vcard.get('EMAIL;TYPE=INTERNET',[''])[0]
    data['contact_phone']=vcard.get('TEL;TYPE=CELL',[''])[0]
    data['secondary_phone']=vcard.get('TEL;TYPE=WORK',[''])[0]
    data['secondary_email']=vcard.get('EMAIL;TYPE=WORK',[''])[0]
    style=''.join(parser.style).strip()
    generator=server.CardGenerator()
    for n in range(1,8):
        candidate=data|{'theme_variant':f'Estilo {n}'}
        profile=generator._get_design_profile(data['category'],candidate)
        if profile['style_name']==style:
            data['theme_variant']=f'Estilo {n}';break
    return data


def run():
    imported=[]
    for folder in sorted((server.ROOT/'dist').iterdir()):
        if not folder.is_dir() or folder.name in {'admin','campana'} or not (folder/'index.html').is_file():continue
        with server.connection() as db:
            if db.execute('SELECT 1 FROM clients WHERE username=?',(folder.name,)).fetchone():
                print(f'Omitido (ya existe): {folder.name}');continue
        data=recover(folder)
        uploads=server.DATA/'uploads';uploads.mkdir(parents=True,exist_ok=True)
        for name,field in [('logo.png','logo_path'),('catalogo.pdf','catalog_pdf_path')]:
            source=folder/'assets'/name
            if source.is_file():
                destination=uploads/f'{uuid.uuid4().hex}{source.suffix}'
                shutil.copy2(source,destination);data[field]=str(destination)
        data=server.validate(data)
        # Generate first: a failure never leaves an incomplete editable client.
        server.generate(data)
        server.save(data,create=True)
        imported.append({'username':data['username'],'theme':data['theme_variant'],'links':len(data['links']),'final_url':data['final_url']})
    print(json.dumps(imported,ensure_ascii=False,indent=2))


if __name__=='__main__':run()
