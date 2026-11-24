"""Aplicación local: API, SQLite y archivos estáticos. Python 3.10+."""
import base64
from contextlib import contextmanager, closing
import io
import json
import mimetypes
import os
import re
import shutil
import socket
import sqlite3
import tempfile
import threading
import uuid
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, unquote
from PIL import Image
from backend.generator import CardGenerator

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get('CARDS_DATA_DIR', ROOT / 'data')).resolve()
CATEGORIES = ['abogados', 'ingenieria', 'belleza', 'nutricion', 'arquitectura']
FIELDS = ['username','company_name','bio','category','final_url','logo_path','catalog_pdf_path','contact_email','contact_phone','primary_website','full_name','job_title','secondary_email','secondary_phone','physical_address','primary_instagram','primary_linkedin','theme_variant','design_line','logo_position']
LOCK = threading.RLock()


@contextmanager
def connection():
    DATA.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DATA / 'clients.sqlite3')
    db.execute('CREATE TABLE IF NOT EXISTS catalogs (kind TEXT NOT NULL, code TEXT NOT NULL, label TEXT NOT NULL, value TEXT NOT NULL, description TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1, PRIMARY KEY(kind,code))')
    db.execute('CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)')
    from backend.catalogs import seed
    seed(db)
    db.execute('CREATE TABLE IF NOT EXISTS clients (username TEXT PRIMARY KEY, payload TEXT NOT NULL, updated_at TEXT DEFAULT CURRENT_TIMESTAMP)')
    try:
        with db:
            yield db
    finally:
        db.close()


def slug(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-z0-9][a-z0-9._-]{0,49}', value) or value in {'admin', 'campana', '.', '..'}:
        raise ValueError('La URL corta debe tener 1 a 50 caracteres: minúsculas, números, puntos, guiones o guion bajo. No uses admin o campana.')
    return value


def validate(raw):
    if not isinstance(raw, dict):
        raise ValueError('Los datos deben ser un objeto JSON.')
    data = {key: str(raw.get(key) or '').strip() for key in FIELDS}
    slug(data['username'])
    if CardGenerator()._sanitize_username(data['username']) != data['username']:
        raise ValueError('Evita separadores consecutivos o al final de la URL corta.')
    if not data['company_name'] or len(data['company_name']) > 100:
        raise ValueError('Escribe un nombre de empresa de hasta 100 caracteres.')
    from backend.catalogs import items
    if data['category'] not in {item['code'] for item in items('categories')}:
        raise ValueError('Selecciona una categoría válida.')
    if data['theme_variant'] not in ['', 'Auto'] + [f'Estilo {n}' for n in range(1,8)]:
        raise ValueError('Diseño visual no válido.')
    if data['design_line'] not in ['', 'Auto','Formal','Moderna','Buchona','Lujo','Minimalista']:
        raise ValueError('Línea de diseño no válida.')
    for field in ['final_url','primary_website']:
        if data[field]:
            parsed = urlsplit(data[field])
            if parsed.scheme not in ('http','https') or not parsed.hostname or any(c.isspace() for c in data[field]):
                raise ValueError(f'{field}: escribe una dirección completa con https://.')
    for field in ['contact_email','secondary_email']:
        if data[field] and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',data[field]):
            raise ValueError('Revisa los correos electrónicos.')
    for field in ['logo_path','catalog_pdf_path']:
        if data[field]:
            path = Path(data[field]).resolve()
            if not path.is_relative_to(DATA / 'uploads') or not path.is_file():
                raise ValueError('Vuelve a cargar el logotipo o catálogo.')
    position = data['logo_position'] or '50'
    if not position.isdigit() or not 0 <= int(position) <= 100:
        raise ValueError('El encuadre del logotipo debe estar entre 0 y 100.')
    data['logo_position'] = position
    links = raw.get('links', [])
    if not isinstance(links,list) or len(links)>50:
        raise ValueError('Se permiten hasta 50 enlaces.')
    normalized = {}
    for item in links:
        if not isinstance(item,dict):
            raise ValueError('Enlace inválido.')
        name, url = str(item.get('name','')).strip(), str(item.get('url','')).strip()
        if name and url:
            normalized[name] = {'name':name,'url':url,'active':item.get('active',True) is not False}
    # Profile fields are authoritative for these generated contact links.
    for name, field in [('Sitio Web','primary_website'),('Correo electrónico','contact_email')]:
        if data[field]:
            normalized[name] = {'name':name,'url':data[field],'active':True}
    data['links'] = list(normalized.values())
    return data


def get_client(username):
    with connection() as db:
        row = db.execute('SELECT payload FROM clients WHERE username=?',(slug(username),)).fetchone()
    if not row:
        raise FileNotFoundError('Cliente no encontrado.')
    return json.loads(row[0])


def save(data, create=False):
    with connection() as db:
        if create:
            try:
                db.execute('INSERT INTO clients(username,payload) VALUES (?,?)',(data['username'],json.dumps(data,ensure_ascii=False)))
            except sqlite3.IntegrityError:
                raise ValueError('Ya existe un cliente con esa URL corta. Ábrelo para editarlo.')
        else:
            if not db.execute('UPDATE clients SET payload=?,updated_at=CURRENT_TIMESTAMP WHERE username=?',(json.dumps(data,ensure_ascii=False),data['username'])).rowcount:
                raise FileNotFoundError('Cliente no encontrado.')


def generate(data, output=None):
    if not data['final_url']:
        raise ValueError('Indica la URL final para que el QR dirija a la tarjeta publicada.')
    output = output or DATA / 'cards'
    output.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=DATA) as temporary:
        from backend.catalogs import items
        category = next(item['value'] for item in items('categories') if item['code'] == data['category'])
        CardGenerator(temporary).generate(data | {'category': category},data['final_url'])
        source = Path(temporary) / data['username']
        target = output / data['username']
        previous = Path(temporary) / 'previous'
        if target.exists():
            target.rename(previous)
        try:
            source.rename(target)
        except Exception:
            if previous.exists():
                previous.rename(target)
            raise
    (target / 'profile.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')


def archive(folder, private=False):
    result = io.BytesIO()
    with zipfile.ZipFile(result,'w',zipfile.ZIP_DEFLATED) as z:
        for path in folder.rglob('*'):
            if path.is_file() and (private or path.name != 'profile.json'):
                z.write(path,path.relative_to(folder))
    return result.getvalue()


class Handler(BaseHTTPRequestHandler):
    def reply(self,status,payload,kind='application/json; charset=utf-8',filename=None):
        body = json.dumps(payload,ensure_ascii=False).encode() if not isinstance(payload,bytes) else payload
        self.send_response(status)
        self.send_header('Content-Type',kind)
        self.send_header('Content-Length',str(len(body)))
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Cache-Control','no-store')
        if filename:
            self.send_header('Content-Disposition',f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(body)

    def body(self):
        if self.headers.get('X-Requested-With') != 'TarjetasStudio':
            raise ValueError('Solicitud no válida. Abre la aplicación local.')
        size = int(self.headers.get('Content-Length','0'))
        if size>16*1024*1024:
            raise ValueError('Archivo demasiado grande (máximo 10 MB).')
        return json.loads(self.rfile.read(size))

    def do_GET(self): self.handle_request('GET')
    def do_POST(self): self.handle_request('POST')
    def do_PUT(self): self.handle_request('PUT')
    def do_DELETE(self): self.handle_request('DELETE')

    def handle_request(self, method):
        try:
            host = self.headers.get('Host','').split(':')[0]
            if host not in {'127.0.0.1','localhost'}:
                return self.reply(403,{'error':'Solo se permite acceso local.'})
            with LOCK:
                self.dispatch(method)
        except FileNotFoundError as e:
            self.reply(404,{'error':str(e)})
        except (ValueError,KeyError,TypeError) as e:
            self.reply(400,{'error':str(e)})
        except Exception:
            import traceback
            traceback.print_exc()
            self.reply(500,{'error':'No se pudo completar la operación. Revisa la consola del servidor.'})

    def dispatch(self,method):
        path = unquote(urlsplit(self.path).path)
        parts = path.strip('/').split('/')
        if parts[:2] == ['api','catalogs']:
            from backend.catalogs import dispatch
            status, payload = dispatch(parts[2:],method,self.body if method != 'GET' else None)
            return self.reply(status,payload)
        if path=='/api/health' and method=='GET':
            return self.reply(200,{'application':'TarjetasStudio','status':'ok'})
        if path=='/api/clients' and method=='GET':
            with connection() as db:
                clients = [json.loads(row[0]) | {'updated_at':row[1]} for row in db.execute('SELECT payload,updated_at FROM clients ORDER BY updated_at DESC')]
            for c in clients:
                folder=DATA/'cards'/c['username']
                c['generated']=(folder/'index.html').is_file()
                c['stale']=c['generated'] and (not (folder/'profile.json').exists() or json.loads((folder/'profile.json').read_text(encoding='utf-8')) != {k:v for k,v in c.items() if k not in ['updated_at','generated','stale']})
            return self.reply(200,clients)
        if path=='/api/clients' and method=='POST':
            data=validate(self.body()); save(data,create=True)
            return self.reply(201,data)
        if path=='/api/design-preview' and method=='POST':
            raw=self.body()
            raw.update(username=raw.get('username') or 'preview', company_name=raw.get('company_name') or 'Tu marca, tu esencia', final_url=raw.get('final_url') or 'https://example.com/tu-tarjeta/')
            data=validate(raw)
            generate(data, DATA/'designs')
            return self.reply(200,{'preview':f"/designs/{data['username']}/"})
        if path=='/api/legacy' and method=='GET':
            index=ROOT/'dist/admin/clients.json'
            return self.reply(200,json.loads(index.read_text(encoding='utf-8')) if index.exists() else [])
        if path=='/api/upload' and method=='POST':
            body=self.body(); blob=base64.b64decode(body['content'],validate=True)
            if len(blob)>10*1024*1024:
                raise ValueError('El archivo supera 10 MB.')
            folder=DATA/'uploads'; folder.mkdir(parents=True,exist_ok=True)
            if body.get('kind')=='logo':
                image=Image.open(io.BytesIO(blob)); image.verify()
                image=Image.open(io.BytesIO(blob))
                if image.width*image.height>20_000_000:
                    raise ValueError('El logotipo es demasiado grande.')
                dest=folder/f'{uuid.uuid4().hex}.png'; image.convert('RGBA').save(dest)
            elif body.get('kind')=='catalog' and blob.startswith(b'%PDF-'):
                dest=folder/f'{uuid.uuid4().hex}.pdf'; dest.write_bytes(blob)
            else:
                raise ValueError('Carga una imagen válida o un catálogo PDF.')
            return self.reply(201,{'path':str(dest)})
        if path=='/api/backup' and method=='GET':
            with tempfile.TemporaryDirectory(dir=DATA) as temp:
                temp=Path(temp)
                with connection() as db, closing(sqlite3.connect(temp/'clients.sqlite3')) as backup:
                    db.backup(backup)
                if (DATA/'uploads').exists(): shutil.copytree(DATA/'uploads',temp/'uploads')
                if (DATA/'cards').exists(): shutil.copytree(DATA/'cards',temp/'cards')
                return self.reply(200,archive(temp, private=True),'application/zip','tarjetas-respaldo.zip')
        if len(parts)>=3 and parts[:2]==['api','clients']:
            username=slug(parts[2]); data=get_client(username)
            if len(parts)==3:
                if method=='GET': return self.reply(200,data)
                if method=='PUT':
                    updated=validate(self.body())
                    if updated['username']!=username: raise ValueError('La URL corta no puede cambiar al editar.')
                    save(updated); return self.reply(200,updated)
                if method=='DELETE':
                    self.body()
                    # Keep uploads; shared assets and backups must remain valid.
                    target=DATA/'cards'/username
                    if target.exists(): shutil.rmtree(target)
                    with connection() as db: db.execute('DELETE FROM clients WHERE username=?',(username,))
                    return self.reply(200,{'ok':True})
            if len(parts)==4 and parts[3]=='generate' and method=='POST':
                self.body(); generate(data)
                return self.reply(200,{'preview':f'/cards/{username}/'})
            if len(parts)==4 and parts[3]=='export' and method=='GET':
                folder=DATA/'cards'/username
                if not (folder/'index.html').exists(): raise ValueError('Genera la tarjeta antes de descargarla.')
                return self.reply(200,archive(folder),'application/zip',f'{username}.zip')
        if method=='GET' and parts[0] in {'cards','legacy','designs'}:
            root=DATA/parts[0] if parts[0] in {'cards','designs'} else ROOT/'dist'
            return self.static(root,'/'.join(parts[1:]))
        if path.startswith('/api/'):
            raise FileNotFoundError('Operación no encontrada.')
        if method=='GET': return self.static(ROOT/'web/dist',path.lstrip('/'),spa=True)
        raise FileNotFoundError('Operación no encontrada.')

    def static(self,root,relative,spa=False):
        root=root.resolve(); target=(root/relative).resolve()
        if not target.is_relative_to(root) or target.name=='profile.json': raise FileNotFoundError('Archivo no encontrado.')
        if target.is_dir(): target=target/'index.html'
        if spa and not target.exists(): target=root/'index.html'
        if not target.is_file(): raise FileNotFoundError('Archivo no encontrado. Compila la interfaz con npm run build en web.')
        return self.reply(200,target.read_bytes(),mimetypes.guess_type(str(target))[0] or 'application/octet-stream')


class LocalServer(ThreadingHTTPServer):
    allow_reuse_address = False

    def server_bind(self):
        if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


if __name__=='__main__':
    with connection(): pass
    port=int(os.environ.get('PORT','8877'))
    http = LocalServer(('127.0.0.1',port),Handler)
    print(f'Tarjetas Studio: http://127.0.0.1:{port}',flush=True)
    http.serve_forever()
