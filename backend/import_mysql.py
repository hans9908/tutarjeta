"""Importación explícita y de solo lectura de MySQL a SQLite.
Ejecutar desde la raíz: python -m backend.import_mysql
"""
import json
import os
import shutil
import uuid
from pathlib import Path
import mysql.connector
from backend.server import DATA, FIELDS, connection, save, validate


def run():
    conn=mysql.connector.connect(connection_timeout=5,host=os.getenv('MYSQL_HOST','localhost'),port=int(os.getenv('MYSQL_PORT','3306')),user=os.getenv('MYSQL_USER','root'),password=os.getenv('MYSQL_PASSWORD',''),database=os.getenv('MYSQL_DATABASE','tarjetas_db'))
    imported=skipped=0
    try:
        cursor=conn.cursor(dictionary=True)
        cursor.execute('SELECT * FROM clientes')
        for row in cursor.fetchall():
            username=row['username']
            with connection() as db:
                exists=db.execute('SELECT 1 FROM clients WHERE username=?',(username,)).fetchone()
            if exists:
                skipped+=1; print(f'Omitido (ya existe): {username}'); continue
            try:
                profile=row.get('profile') or {}
                if isinstance(profile,str): profile=json.loads(profile)
                data={key:row.get(key) or profile.get(key) or '' for key in FIELDS}
                links=row.get('links') or []
                if isinstance(links,str): links=json.loads(links)
                data['links']=links
                for name,field in [('Sitio Web','primary_website'),('Correo electrónico','contact_email')]:
                    if not data[field]: data[field]=next((l.get('url','').removeprefix('mailto:') for l in links if l.get('name')==name),'')
                for field in ['logo_path','catalog_pdf_path']:
                    if data[field]:
                        source=Path(data[field])
                        if source.is_file():
                            folder=DATA/'uploads';folder.mkdir(parents=True,exist_ok=True)
                            dest=folder/(uuid.uuid4().hex+source.suffix.lower());shutil.copy2(source,dest);data[field]=str(dest)
                        else:
                            print(f'Aviso {username}: archivo no encontrado en {field}.');data[field]=''
                data=validate(data); save(data,create=True);imported+=1
                print(f'Importado: {username}')
            except (ValueError,TypeError,KeyError) as e:
                print(f'No importado {username}: {e}');skipped+=1
        cursor.close()
    finally:
        conn.close()
    print(f'Finalizado: {imported} importados, {skipped} omitidos. MySQL no fue modificado.')


if __name__=='__main__':
    try:
        run()
    except mysql.connector.Error:
        raise SystemExit('No se pudo conectar a MySQL. Inicia MySQL en Laragon y revisa las variables MYSQL_HOST, MYSQL_PORT, MYSQL_USER, MYSQL_PASSWORD y MYSQL_DATABASE.')
