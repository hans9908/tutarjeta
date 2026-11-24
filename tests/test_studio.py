import base64
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.request import Request,urlopen
from urllib.error import HTTPError
import zipfile
from PIL import Image
from http.server import ThreadingHTTPServer
from backend import server


class StudioTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)
        self.previous=server.DATA
        server.DATA=Path(self.temp.name)
        self.http=ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        self.thread=threading.Thread(target=self.http.serve_forever,daemon=True);self.thread.start()
        self.url=f'http://127.0.0.1:{self.http.server_port}'
        self.data={'username':'cliente-test','company_name':'Empresa <&>','category':'abogados','final_url':'https://example.com/cliente-test/','contact_email':'hola@example.com','links':[{'name':'Instagram','url':'@empresa','active':False},{'name':'WhatsApp','url':'+52 5512345678','active':True}]}

    def tearDown(self):
        self.http.shutdown();self.http.server_close();self.thread.join();server.DATA=self.previous;self.temp.cleanup()

    def request(self,path,method='GET',data=None,header=True):
        req=Request(self.url+path,method=method,data=json.dumps(data).encode() if data is not None else None,headers={'Content-Type':'application/json',**({'X-Requested-With':'TarjetasStudio'} if header else {})})
        try:
            with urlopen(req) as r:
                body=r.read();return r.status,json.loads(body) if 'application/json' in r.headers['Content-Type'] else body
        except HTTPError as e:
            with e: return e.code,json.loads(e.read())

    def test_persistence_updates_and_disabled_links(self):
        self.assertEqual(self.request('/api/clients','POST',self.data)[0],201)
        updated=self.data|{'company_name':'Otra empresa','links':[{'name':'Instagram','url':'@otra','active':False}]}
        self.assertEqual(self.request('/api/clients/cliente-test','PUT',updated)[0],200)
        loaded=self.request('/api/clients/cliente-test')[1]
        self.assertEqual(loaded['company_name'],'Otra empresa')
        self.assertFalse(loaded['links'][0]['active'])
        self.assertEqual(self.request('/api/clients','POST',self.data)[0],400)
        self.assertEqual(len(self.request('/api/clients')[1]),1)

    def test_generate_zip_qr_vcard_and_stale_status(self):
        self.request('/api/clients','POST',self.data)
        self.assertEqual(self.request('/api/clients/cliente-test/generate','POST',{})[0],200)
        listing=self.request('/api/clients')[1][0]
        self.assertTrue(listing['generated']);self.assertFalse(listing['stale'])
        html=self.request('/cards/cliente-test/')[1].decode()
        self.assertIn('Empresa &lt;&amp;&gt;',html)
        self.assertNotIn('instagram.com/empresa',html)
        self.assertIn('https://wa.me/525512345678',html)
        self.assertNotIn('Guardar contacto',html)
        data=self.request('/api/clients/cliente-test/export')[1]
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            self.assertIn('assets/qr_share.png',z.namelist());self.assertNotIn('profile.json',z.namelist())
            Image.open(io.BytesIO(z.read('assets/qr_share.png'))).verify()
            self.assertIn(b'EMAIL;TYPE=INTERNET:hola@example.com',z.read('assets/contact.vcf'))
        self.request('/api/clients/cliente-test','PUT',self.data|{'bio':'Actualizada'})
        self.assertTrue(self.request('/api/clients')[1][0]['stale'])
        self.assertEqual(self.request('/cards/cliente-test/profile.json')[0],404)
        backup=self.request('/api/backup')[1]
        with zipfile.ZipFile(io.BytesIO(backup)) as z:self.assertIn('clients.sqlite3',z.namelist())
        self.assertEqual(self.request('/api/clients/cliente-test','DELETE',{})[0],200)
        self.assertEqual(self.request('/api/clients/cliente-test')[0],404)

    def test_validation_and_mutation_header(self):
        for username in ['../escape','admin','a..b','x/hi','final-']:
            self.assertEqual(self.request('/api/clients','POST',self.data|{'username':username})[0],400)
        self.assertEqual(self.request('/api/clients','POST',self.data,header=False)[0],400)
        self.assertEqual(self.request('/api/clients','POST',self.data|{'final_url':'javascript:alert(1)'})[0],400)
        self.assertEqual(self.request('/api/clients','POST',self.data|{'logo_path':str(Path(__file__).resolve())})[0],400)
        g=server.CardGenerator()
        for value in ['javascript:alert(1)','data:text/html,hi','java\nscript:alert(1)']:
            self.assertEqual(g._normalize_link_href('Sitio Web',value),'')
        self.assertNotIn('"',g._normalize_link_href('Sitio Web','https://example.com/?x="onload=hi'))

    def test_upload_conversion_and_pdf(self):
        image=io.BytesIO();Image.new('RGB',(32,32),'red').save(image,format='JPEG')
        status,result=self.request('/api/upload','POST',{'kind':'logo','content':base64.b64encode(image.getvalue()).decode()})
        self.assertEqual(status,201)
        with Image.open(result['path']) as image: self.assertEqual(image.format,'PNG')
        self.assertEqual(self.request('/api/upload','POST',{'kind':'catalog','content':base64.b64encode(b'no pdf').decode()})[0],400)

    def test_all_35_designs_render_and_vcard_escape(self):
        gen=server.CardGenerator(self.temp.name)
        data=server.validate(self.data|{'full_name':'Ana\nInjected:evil'})
        for category in server.CATEGORIES:
            for number in range(1,8):
                data.update(category=category,theme_variant=f'Estilo {number}')
                profile=gen._get_design_profile(category,data)
                self.assertIn('<!DOCTYPE html>',gen._get_html_template(data,profile))
                self.assertIn('body',gen._get_css_template(category,profile))
        self.assertNotIn('\r\nInjected:',gen._build_vcard(data,data['final_url']))


    def test_catalog_crud_and_custom_category_generation(self):
        status, catalogs = self.request('/api/catalogs')
        self.assertEqual(status,200)
        self.assertEqual(len(catalogs['categories']),5)
        record={'code':'consultoria','label':'Consultoría','value':'ingenieria','description':'Servicios profesionales','active':True}
        self.assertEqual(self.request('/api/catalogs/categories','POST',record)[0],201)
        self.assertEqual(self.request('/api/catalogs/categories','POST',record)[0],400)
        updated=record|{'label':'Consultoría técnica','active':False}
        self.assertEqual(self.request('/api/catalogs/categories/consultoria','PUT',updated)[0],200)
        self.assertFalse(next(r for r in self.request('/api/catalogs/categories')[1] if r['code']=='consultoria')['active'])
        self.assertEqual(self.request('/api/clients','POST',self.data|{'category':'consultoria'})[0],201)
        self.assertEqual(self.request('/api/clients/cliente-test/generate','POST',{})[0],200)
        self.assertIn(b'category-ingenieria',self.request('/cards/cliente-test/')[1])
        self.assertEqual(self.request('/api/catalogs/categories/consultoria','DELETE',{})[0],400)
        self.assertEqual(self.request('/api/clients/cliente-test','DELETE',{})[0],200)
        self.assertEqual(self.request('/api/catalogs/categories/consultoria','DELETE',{})[0],200)
        self.assertNotIn('consultoria',[r['code'] for r in self.request('/api/catalogs/categories')[1]])

    def test_catalog_delete_is_persistent_and_usage_is_protected(self):
        self.request('/api/clients','POST',self.data)
        self.assertEqual(self.request('/api/catalogs/categories/abogados','DELETE',{})[0],400)
        self.assertEqual(self.request('/api/catalogs/networks/red-3','DELETE',{})[0],400)
        self.assertEqual(self.request('/api/catalogs/networks/red-4','DELETE',{})[0],200)
        self.assertNotIn('red-4',[r['code'] for r in self.request('/api/catalogs/networks')[1]])
        self.assertNotIn('red-4',[r['code'] for r in self.request('/api/catalogs/networks')[1]])
        self.assertEqual(self.request('/api/catalogs/designs','POST',{'code':'bad','label':'Bad','value':'Estilo 100','active':True})[0],400)

    def test_logo_position_survives_regeneration(self):
        self.assertEqual(self.request('/api/clients','POST',self.data|{'logo_position':'34'})[0],201)
        self.assertEqual(self.request('/api/clients/cliente-test/generate','POST',{})[0],200)
        self.assertIn(b'--logo-position: 34%',self.request('/cards/cliente-test/')[1])
        self.assertEqual(self.request('/api/clients/cliente-test','PUT',self.data|{'logo_position':'999'})[0],400)


    def test_seven_compositions_stay_distinct_for_every_design_line(self):
        generator=server.CardGenerator(self.temp.name)
        for line in ['Auto','Formal','Moderna','Buchona','Lujo','Minimalista']:
            indices=[]
            for n in range(1,8):
                data=server.validate(self.data|{'theme_variant':f'Estilo {n}','design_line':line})
                profile=generator._get_design_profile(data['category'],data)
                indices.append(profile['variant_index'])
                self.assertIn(f'composition-{n}',generator._get_html_template(data,profile))
            self.assertEqual(indices,list(range(7)))

    def test_preview_does_not_save_or_change_client(self):
        self.request('/api/clients','POST',self.data)
        status,result=self.request('/api/design-preview','POST',self.data|{'theme_variant':'Estilo 3'})
        self.assertEqual(status,200)
        self.assertIn(b'composition-3',self.request(result['preview'])[1])
        self.assertEqual(len(self.request('/api/clients')[1]),1)
        self.assertEqual(self.request('/api/clients/cliente-test')[1]['theme_variant'],'')
        self.assertFalse((server.DATA/'cards/cliente-test').exists())


if __name__=='__main__':unittest.main()
