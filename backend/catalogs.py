"""Catálogos persistentes y protección de registros relacionados."""
import re

KINDS = ['categories','designs','lines','networks']
CATEGORY_LABELS = {'abogados':'Abogacía','ingenieria':'Ingeniería','belleza':'Belleza','nutricion':'Nutrición','arquitectura':'Arquitectura'}
DESIGN_NAMES = ['Editorial','Perfil','Mosaico','Esencial','Signature','Canvas','Portafolio']
NETWORKS = ['WhatsApp','Teléfono','Instagram','Facebook','LinkedIn','X (Twitter)','YouTube','TikTok','Telegram','Google Maps','Calendly','Behance','Dribbble','Pinterest','GitHub','Sitio Web','Correo electrónico']


def seed(db):
    if db.execute("SELECT 1 FROM settings WHERE key='catalogs_seeded'").fetchone():
        if not db.execute("SELECT 1 FROM settings WHERE key='design_names_v2'").fetchone():
            for n,name in enumerate(DESIGN_NAMES,1):
                db.execute("UPDATE catalogs SET label=?,description=? WHERE kind='designs' AND code=? AND label=?",(name,'Composición '+name.lower()+': estructura visual propia',f'estilo-{n}',f'Estilo {n}'))
            db.execute("INSERT INTO settings(key,value) VALUES ('design_names_v2','1')")
            db.commit()
        return
    rows=[]
    for code,label in CATEGORY_LABELS.items():rows.append(('categories',code,label,code,'Colección de diseños para '+label,1))
    for n in range(1,8):rows.append(('designs',f'estilo-{n}',DESIGN_NAMES[n-1],f'Estilo {n}','Composición '+DESIGN_NAMES[n-1].lower(),1))
    for value in ['Auto','Formal','Moderna','Buchona','Lujo','Minimalista']:rows.append(('lines',value.lower(),value,value,'Línea de presentación',1))
    for n,value in enumerate(NETWORKS):rows.append(('networks',f'red-{n+1}',value,value,'Canal de contacto o enlace',1))
    db.executemany('INSERT INTO catalogs(kind,code,label,value,description,active) VALUES (?,?,?,?,?,?)',rows)
    db.execute("INSERT INTO settings(key,value) VALUES ('catalogs_seeded','1')")
    db.commit()


def items(kind=None):
    from backend.server import connection
    with connection() as db:
        db.row_factory=__import__('sqlite3').Row
        rows=db.execute('SELECT * FROM catalogs'+(' WHERE kind=?' if kind else '')+' ORDER BY label COLLATE NOCASE', (kind,) if kind else ()).fetchall()
    return [dict(row)|{'active':bool(row['active'])} for row in rows]


def usage(item):
    from backend.server import connection
    import json
    with connection() as db: clients=[json.loads(r[0]) for r in db.execute('SELECT payload FROM clients')]
    field={'categories':'category','designs':'theme_variant','lines':'design_line'}.get(item['kind'])
    if field:
        expected = item['code'] if item['kind']=='categories' else item['value']
        return sum(1 for client in clients if client.get(field)==expected)
    return sum(1 for client in clients if any(l.get('name')==item['value'] for l in client.get('links',[])))


def dispatch(parts,method,read_body):
    from backend.server import connection, CATEGORIES
    if not parts and method=='GET':
        return 200,{kind:[item|{'usage':usage(item)} for item in items(kind)] for kind in KINDS}
    if not parts or parts[0] not in KINDS:raise FileNotFoundError('Catálogo no encontrado.')
    kind=parts[0]
    if len(parts)==1 and method=='GET':return 200,[item|{'usage':usage(item)} for item in items(kind)]
    if len(parts)>2:raise FileNotFoundError('Operación no encontrada.')
    existing=next((i for i in items(kind) if len(parts)==2 and i['code']==parts[1]),None)
    if len(parts)==2 and not existing:raise FileNotFoundError('Registro no encontrado.')
    if method=='DELETE' and existing:
        read_body()
        if usage(existing):raise ValueError('Este registro está en uso. Puedes desactivarlo para conservar sus tarjetas.')
        with connection() as db:db.execute('DELETE FROM catalogs WHERE kind=? AND code=?',(kind,existing['code']))
        return 200,{'ok':True}
    if (method=='POST' and len(parts)==1) or (method=='PUT' and existing):
        raw=read_body()
        if not isinstance(raw,dict):raise ValueError('Registro no válido.')
        code=str(raw.get('code','')).strip();label=str(raw.get('label','')).strip();value=str(raw.get('value','')).strip();description=str(raw.get('description','')).strip()
        if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,49}',code):raise ValueError('El código admite hasta 50 caracteres: minúsculas, números, guiones y guion bajo.')
        if not label or len(label)>100 or not value or len(value)>100 or len(description)>500:raise ValueError('Completa nombre y valor (máximo 100 caracteres). Descripción: hasta 500.')
        allowed={'categories':CATEGORIES,'designs':[f'Estilo {n}' for n in range(1,8)],'lines':['Auto','Formal','Moderna','Buchona','Lujo','Minimalista']}
        if kind in allowed and value not in allowed[kind]:raise ValueError('Selecciona una opción compatible con el generador.')
        if existing and code!=existing['code']:raise ValueError('El código no cambia después de crear el registro.')
        if existing and value!=existing['value'] and usage(existing):raise ValueError('El valor está en uso y no puede cambiar. Puedes modificar el nombre y la descripción.')
        active=raw.get('active',True)
        if not isinstance(active,bool):raise ValueError('Estado no válido.')
        with connection() as db:
            if not existing:
                if db.execute('SELECT 1 FROM catalogs WHERE kind=? AND (code=? OR lower(label)=lower(?))',(kind,code,label)).fetchone():raise ValueError('Ya existe un registro con ese código, nombre o valor.')
                db.execute('INSERT INTO catalogs(kind,code,label,value,description,active) VALUES (?,?,?,?,?,?)',(kind,code,label,value,description,int(active)))
            else:
                if db.execute('SELECT 1 FROM catalogs WHERE kind=? AND code<>? AND lower(label)=lower(?)',(kind,code,label)).fetchone():raise ValueError('Ya existe un registro con ese nombre.')
                db.execute('UPDATE catalogs SET label=?,value=?,description=?,active=? WHERE kind=? AND code=?',(label,value,description,int(active),kind,code))
        return (200 if existing else 201),next(i for i in items(kind) if i['code']==code)
    raise FileNotFoundError('Operación no encontrada.')
