<script setup>
import {computed, onMounted, onUnmounted, ref, watch} from 'vue'
import {createPreviewQueue} from './previewQueue.js'
import Management from './Management.vue'
const compositionDescriptions=['Titulares grandes y líneas editoriales','Portada con retrato superpuesto','Canales en bloques con personalidad','Diseño claro, limpio y ligero','Emblema central y acabados de lujo','Identidad técnica y composición asimétrica','Presentación horizontal con aire creativo']
const previewSample=ref(false), previewLoading=ref(false), previewError=ref('')
const page=ref('clients'), catalogs=ref({categories:[],designs:[],lines:[],networks:[]})
const clients=ref([]), legacy=ref([]), query=ref(''), selected=ref(''), tab=ref('perfil'), busy=ref(false), message=ref(''), error=ref(''), preview=ref('')
const categories=computed(()=>Object.fromEntries(catalogs.value.categories.map(c=>[c.code,c.label])))
const networks=computed(()=>catalogs.value.networks.filter(n=>n.active).map(n=>n.value))
function go(destination){if(page.value==='editor'&&!allowLeave())return;baseline.value=JSON.stringify(form.value);page.value=destination}
async function reloadManagement(data){if(data)catalogs.value=data;else catalogs.value=await api('/catalogs');await refresh()}
const fields=[['company_name','Empresa o nombre comercial','text'],['full_name','Nombre completo','text'],['job_title','Cargo o especialidad','text'],['contact_email','Correo principal','email'],['contact_phone','Teléfono principal','tel'],['primary_website','Sitio web','url'],['secondary_email','Correo alternativo','email'],['secondary_phone','Teléfono alternativo','tel'],['physical_address','Dirección','text'],['primary_instagram','Instagram (@usuario o URL)','text'],['primary_linkedin','LinkedIn (usuario o URL)','text']]
const empty=()=>({username:'',company_name:'',bio:'',category:'abogados',final_url:'',theme_variant:'Auto',design_line:'Auto',logo_position:'50',logo_path:'',catalog_pdf_path:'',links:[],...Object.fromEntries(fields.map(([k])=>[k,'']))})
const form=ref(empty()), baseline=ref(JSON.stringify(form.value))
const changed=computed(()=>JSON.stringify(form.value)!==baseline.value)
const filtered=computed(()=>clients.value.filter(c=>(c.company_name+' '+c.username+' '+categories.value[c.category]).toLowerCase().includes(query.value.toLowerCase())))
const current=computed(()=>clients.value.find(c=>c.username===selected.value))
const generated=computed(()=>clients.value.filter(c=>c.generated).length)
async function api(path,method='GET',body){const r=await fetch('/api'+path,{method,headers:{'Content-Type':'application/json','X-Requested-With':'TarjetasStudio'},...(body===undefined?{}:{body:JSON.stringify(body)})});const result=await r.json();if(!r.ok)throw Error(result.error||'No se pudo completar la solicitud.');return result}
async function run(fn){busy.value=true;error.value='';message.value='';try{await fn()}catch(e){error.value=e.message}finally{busy.value=false}}
const previewQueue=createPreviewQueue({
 request:data=>api('/design-preview','POST',data),
 apply:result=>{preview.value=result.preview+'?v='+Date.now();previewSample.value=true;previewError.value=''},
 fail:e=>{previewError.value=e.message},
 loading:value=>{previewLoading.value=value}
})
function previewDesign(){previewError.value='';previewQueue.schedule(form.value,true)}
watch([()=>JSON.stringify(form.value),page,busy],()=>{
 previewQueue.cancel()
 if(page.value==='editor'&&!busy.value) {
   previewError.value=''
   previewQueue.schedule(form.value)
 }
})
onUnmounted(()=>previewQueue.dispose())
async function refresh(){clients.value=await api('/clients')}
function allowLeave(){return !changed.value||window.confirm('Hay cambios sin guardar. ¿Quieres descartarlos?')}
async function select(c){if(page.value==='editor'&&!allowLeave())return;await run(async()=>{form.value=await api('/clients/'+c.username);page.value='editor';previewSample.value=false;selected.value=c.username;baseline.value=JSON.stringify(form.value);preview.value=c.generated?'/cards/'+c.username+'/?v='+Date.now():'';tab.value='perfil'})}
function newCard(){previewSample.value=false;if(page.value==='editor'&&!allowLeave())return;page.value='editor';form.value=empty();form.value.category=catalogs.value.categories.find(c=>c.active)?.code||'abogados';selected.value='';baseline.value=JSON.stringify(form.value);preview.value='';error.value='';message.value='';tab.value='perfil'}
async function save(generate=false){
 previewQueue.cancel()
 await run(async()=>{
   if(generate&&!form.value.final_url)throw Error('Indica la URL final en Entrega antes de generar.')
   const data=await api(selected.value?'/clients/'+selected.value:'/clients',selected.value?'PUT':'POST',form.value)
   selected.value=data.username;form.value=data;baseline.value=JSON.stringify(data)
   if(data.final_url){
     try{await api('/clients/'+data.username+'/generate','POST',{})}
     catch(e){await refresh();throw Error('Los datos se guardaron, pero no se pudo actualizar la tarjeta: '+e.message)}
     previewSample.value=false;preview.value='/cards/'+data.username+'/?v='+Date.now()
     message.value='Cambios guardados y diseño aplicado a la tarjeta.'
   }else message.value='Borrador guardado. Agrega la URL final en Entrega para generar la tarjeta.'
   await refresh()
 })
}
async function remove(){if(!selected.value||!window.confirm('¿Eliminar este cliente y su tarjeta local? Esta acción no se puede deshacer.'))return;await run(async()=>{await api('/clients/'+selected.value,'DELETE',{});baseline.value=JSON.stringify(form.value);newCard();await refresh();message.value='Cliente eliminado.'})}
async function upload(event,kind){const file=event.target.files[0];if(!file)return;await run(async()=>{if(file.size>10*1024*1024)throw Error('Selecciona un archivo de hasta 10 MB.');const content=await new Promise((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve(r.result.split(',')[1]);r.onerror=()=>reject(Error('No se pudo leer el archivo.'));r.readAsDataURL(file)});const result=await api('/upload','POST',{kind,content});form.value[kind==='logo'?'logo_path':'catalog_pdf_path']=result.path;message.value='Archivo cargado. Guarda para asociarlo al cliente.'});event.target.value=''}
function addLink(){form.value.links.push({name:'WhatsApp',url:'',active:true})}
function initials(name){return (name||'Tu marca').split(' ').filter(Boolean).slice(0,2).map(w=>w[0]).join('').toUpperCase()}
onMounted(()=>run(async()=>{await reloadManagement();legacy.value=await api('/legacy')}))
window.addEventListener('beforeunload',e=>{if(page.value==='editor'&&changed.value){e.preventDefault();e.returnValue=''}})
</script>

<template>
<div class="workspace">
  <aside class="sidebar">
    <a class="brand" href="/" @click.prevent="newCard"><span class="brand-icon">t<span>·</span></span><span>tarjetas<span class="brand-sub">STUDIO</span></span></a>
    <div class="workspace-label">ESPACIO DE TRABAJO</div>
    <nav class="main-navigation" aria-label="Navegación principal"><button :class="{current:page==='clients'}" @click="go('clients')"><span>▤</span> Clientes <span class="count">{{clients.length}}</span></button><button :class="{current:page==='catalogs'}" @click="go('catalogs')"><span>◈</span> Catálogos</button><button :class="{current:page==='editor'}" @click="go('editor')"><span>✎</span> Editor de tarjeta</button></nav>
    <div class="sidebar-title"><span>CLIENTES</span><button class="icon-button" @click="newCard" :disabled="busy" aria-label="Nuevo cliente">＋</button></div>
    <input class="search" v-model="query" aria-label="Buscar clientes" placeholder="Buscar un cliente…">
    <div class="client-list" aria-label="Lista de clientes">
      <button v-for="c in filtered" :key="c.username" class="client" :class="{selected:selected===c.username}" @click="select(c)" :disabled="busy"><span class="avatar">{{initials(c.company_name)}}</span><span class="client-info"><strong>{{c.company_name}}</strong><small>{{categories[c.category]}}</small></span><span v-if="c.generated" class="status-dot" :title="c.stale?'Pendiente de regenerar':'Generada'"></span></button>
      <p v-if="!filtered.length" class="empty-list">{{query?'Sin coincidencias.':'Tu próxima tarjeta empieza aquí.'}}</p>
    </div>
    <details v-if="legacy.length" class="legacy"><summary>Tarjetas de la versión anterior <span>{{legacy.length}}</span></summary><p>Conservadas para consulta. Archivos originales conservados.</p><a v-for="c in legacy" :key="c.username" :href="'/legacy/'+encodeURIComponent(c.username)+'/'" target="_blank" rel="noopener">{{c.company_name}} ↗</a></details>
    <div class="sidebar-bottom"><a href="/api/backup" class="backup">↓ Descargar respaldo</a><span class="local-dot"></span> Almacenamiento local · SQLite</div>
  </aside>
  <main>
    <header class="topbar"><div>Mi espacio <span>/</span> <strong>{{page==='clients'?'Clientes':page==='catalogs'?'Catálogos':'Editor de tarjeta'}}</strong></div><span class="version">STUDIO 2.0</span></header>
    <div class="content">
      <div v-if="message" role="status" class="notice success">{{message}}</div><div v-if="error" role="alert" class="notice error">{{error}}</div>
      <Management v-if="page!=='editor'" :mode="page" :clients="clients" :catalogs="catalogs" :api="api" @refresh="reloadManagement" @edit="select" @create="newCard" />
      <template v-else>
      <div class="page-heading"><div><span class="eyebrow">CONECTA. COMPARTE. DESTACA.</span><h1>Tu próxima gran conexión.</h1><p>Crea una tarjeta que hable por ti, en un solo lugar.</p></div><button class="primary" @click="newCard" :disabled="busy">＋ Nueva tarjeta</button></div>
      <div class="stats"><div><span class="stat-icon blue">▤</span><div><strong>{{clients.length}}</strong><span>Tarjetas en tu espacio</span></div></div><div><span class="stat-icon green">✓</span><div><strong>{{generated}}</strong><span>Tarjetas generadas</span></div></div><div><span class="stat-icon violet">◈</span><div><strong>35</strong><span>Diseños para tu marca</span></div></div></div>

      <div class="editor-layout">
        <section class="editor panel">
          <div class="panel-heading"><div><h2>{{selected?'Editar tarjeta':'Diseña tu tarjeta'}}</h2><p>{{selected?'/'+selected:'Los pequeños detalles hacen grandes conexiones.'}}</p></div><span class="badge" :class="{unsaved:changed}">{{changed?'Sin guardar':current?.generated?(current.stale?'Pendiente de regenerar':'Generada'):'Borrador'}}</span></div>
          <div class="tabs" role="tablist" aria-label="Secciones del editor"><button v-for="(label,key) in {perfil:'Perfil',diseno:'Diseño y archivos',enlaces:'Enlaces',entrega:'Entrega'}" :key="key" role="tab" :aria-selected="tab===key" :class="{active:tab===key}" @click="tab=key">{{label}}</button></div>
          <form @submit.prevent="save(false)">
          <fieldset :disabled="busy">
            <div v-if="tab==='perfil'" class="form-section">
              <div class="section-heading"><h3>Primero, tu identidad</h3><p>Así te conocerán tus próximos clientes.</p></div>
              <div class="fields"><label class="wide">URL corta <span class="required">*</span><div class="slug-input"><span>/</span><input v-model="form.username" :disabled="!!selected" placeholder="tu-marca" maxlength="50" required pattern="[a-z0-9][a-z0-9._\-]{0,49}"></div><small>Única para cada tarjeta. No cambia después de guardar.</small></label>
                <label v-for="([key,label,type],i) in fields.slice(0,6)" :key="key" :class="{wide:i===0}">{{label}} <span v-if="i===0" class="required">*</span><input v-model="form[key]" :type="type" :required="i===0" :placeholder="i===0?'¿Cómo se llama tu marca?':type==='url'?'https://tusitio.com':''"></label>
                <label class="wide">Biografía <textarea v-model="form.bio" rows="3" placeholder="Cuenta qué haces y qué te hace diferente…"></textarea></label>
              </div>
              <details class="optional"><summary>Más datos de contacto</summary><div class="fields"><label v-for="[key,label,type] in fields.slice(6)" :key="key">{{label}}<input v-model="form[key]" :type="type"></label></div></details>
            </div>
            <div v-if="tab==='diseno'" class="form-section"><div class="section-heading"><h3>Una tarjeta con tu estilo</h3><p>Elige una composición: la vista previa se actualiza automáticamente. Guarda para aplicarla a tu tarjeta.</p></div><div class="fields"><label class="wide">Categoría<select v-model="form.category"><option v-for="c in catalogs.categories.filter(c=>c.active||c.code===form.category)" :value="c.code">{{c.label}}{{!c.active?' (inactiva)':''}}</option></select></label><label>Diseño visual<select v-model="form.theme_variant"><option>Auto</option><option v-for="d in catalogs.designs.filter(d=>d.active||d.value===form.theme_variant)" :value="d.value">{{d.label}}</option></select></label><label>Línea de diseño<select v-model="form.design_line"><option v-for="line in catalogs.lines.filter(l=>l.active||l.value===form.design_line)" :value="line.value">{{line.label}}</option></select></label></div><div class="design-gallery" aria-label="Composiciones disponibles"><button v-for="d in catalogs.designs.filter(d=>d.active||d.value===form.theme_variant)" :key="d.code" type="button" class="design-choice" :class="{picked:form.theme_variant===d.value}" :aria-pressed="form.theme_variant===d.value" @click="form.theme_variant=d.value"><div class="design-mini" :class="'mini-'+d.value.replace('Estilo ','')"><span class="mini-logo"></span><span class="mini-heading"></span><span class="mini-copy"></span><span v-for="i in 3" class="mini-link"></span></div><strong>{{d.label}}</strong><small>{{compositionDescriptions[Number(d.value.replace('Estilo ',''))-1]}}</small></button></div><button type="button" class="secondary preview-design-button" @click="previewDesign" :disabled="busy">{{previewLoading?'Actualizando…':'Actualizar vista previa'}}</button><div class="upload-box"><span class="upload-icon">◇</span><div><strong>Logotipo de tu marca</strong><p>PNG, JPG o WebP · Máximo 10 MB</p><span v-if="form.logo_path" class="file-loaded">✓ Logotipo cargado</span><small v-else>Sin logo: creamos uno con tus iniciales.</small></div><label class="file-button">Elegir imagen<input type="file" accept="image/png,image/jpeg,image/webp" @change="upload($event,'logo')"></label><button v-if="form.logo_path" type="button" class="text-button" @click="form.logo_path=''">Quitar</button></div><label v-if="form.logo_path" class="logo-framing">Encuadre vertical del logotipo · {{form.logo_position||50}}%<input type="range" min="0" max="100" v-model="form.logo_position"><small>Ajusta el área visible y guarda para aplicar. 0% muestra la parte superior; 100%, la inferior.</small></label><div class="upload-box"><span class="upload-icon">▧</span><div><strong>Catálogo de servicios</strong><p>PDF · Máximo 10 MB</p><span v-if="form.catalog_pdf_path" class="file-loaded">✓ Catálogo cargado</span></div><label class="file-button">Elegir PDF<input type="file" accept="application/pdf" @change="upload($event,'catalog')"></label><button v-if="form.catalog_pdf_path" type="button" class="text-button" @click="form.catalog_pdf_path=''">Quitar</button></div></div>
            <div v-if="tab==='enlaces'" class="form-section"><div class="section-heading"><h3>Abre la conversación</h3><p>Agrega tus redes, WhatsApp, ubicación o agenda. Puedes desactivar un enlace sin perderlo.</p></div><div v-for="(link,i) in form.links" :key="i" class="link-row"><input type="checkbox" v-model="link.active" :aria-label="'Activar enlace '+(i+1)"><label><span class="sr-only">Red o servicio</span><select v-model="link.name"><option v-if="!networks.includes(link.name)">{{link.name}}</option><option v-for="network in catalogs.networks.filter(n=>n.active)" :value="network.value">{{network.label}}</option></select></label><label class="link-value"><span class="sr-only">URL, usuario o número</span><input v-model="link.url" placeholder="URL, @usuario o número"></label><button type="button" class="icon-button" @click="form.links.splice(i,1)" aria-label="Quitar enlace">×</button></div><p v-if="!form.links.length" class="empty-links">Tu tarjeta puede conectar con todos tus canales.</p><button type="button" class="secondary" @click="addLink">＋ Agregar enlace</button></div>
            <div v-if="tab==='entrega'" class="form-section"><div class="section-heading"><h3>Lista para compartir</h3><p>El QR apuntará exactamente a la dirección que indiques aquí.</p></div><label>URL final de la tarjeta<input v-model="form.final_url" type="url" placeholder="https://tudominio.com/tu-marca/"><small>Necesaria para generar. Puedes guardar un borrador sin URL.</small></label><div class="delivery-note"><strong>Tu paquete incluye</strong><p>Tarjeta HTML, estilos, logotipo, QR para compartir, contacto vCard y tu catálogo PDF si lo agregaste.</p></div><div v-if="current?.generated" class="download-list"><a :href="'/api/clients/'+selected+'/export'">↓ Descargar tarjeta (.zip)</a><a :href="'/cards/'+selected+'/assets/qr_share.png'" download>↓ Descargar QR</a><a :href="'/cards/'+selected+'/assets/contact.vcf'" download>↓ Descargar contacto</a></div><p class="muted">Descarga el ZIP para subirlo a tu hosting. Generar no publica automáticamente en internet.</p></div>
          </fieldset>
          <div class="editor-footer"><button type="button" class="delete" v-if="selected" @click="remove" :disabled="busy">Eliminar</button><span v-else class="footer-hint">Tu marca, siempre a mano.</span><div><button type="submit" class="secondary" :disabled="busy">Guardar</button><button type="button" class="primary" @click="save(true)" :disabled="busy">{{busy?'Procesando…':'Generar tarjeta'}}</button></div></div>
          </form>
        </section>
        <aside class="preview-column"><div class="preview-heading"><h2>Tu tarjeta, en acción</h2><span aria-live="polite">{{previewLoading?'ACTUALIZANDO…':'VISTA EN VIVO'}}</span></div><div class="phone"><div class="phone-camera"></div><iframe v-if="preview" :key="preview" :src="preview" title="Vista previa de la tarjeta generada" sandbox="allow-downloads allow-popups allow-popups-to-escape-sandbox"></iframe><div v-else class="mock-card" :class="form.design_line.toLowerCase()"><span class="mock-category">{{categories[form.category]}} · {{form.design_line==='Auto'?'Signature':form.design_line}}</span><div class="mock-avatar">{{initials(form.company_name)}}</div><h2>{{form.company_name||'Tu marca empieza aquí'}}</h2><span class="mock-job">{{form.job_title||'Una nueva forma de conectar'}}</span><p>{{form.bio||'Tu experiencia, tu esencia y todos tus canales de contacto. En una sola tarjeta.'}}</p><div v-for="link in form.links.filter(l=>l.active&&l.url).slice(0,3)" class="mock-link">{{link.name}}</div><div class="mock-line"></div><span class="mock-foot">HECHA PARA CONECTAR</span></div></div><p class="preview-note">{{previewError?previewError:previewLoading?'Actualizando tu tarjeta con el diseño seleccionado…':changed?'Vista previa de tus cambios. Guarda para aplicarlos a la tarjeta.':preview?'Vista sincronizada con tus datos. Los cambios de diseño se muestran automáticamente.':'Completa los datos para ver tu tarjeta.'}}</p><a v-if="preview" class="open-preview" :href="preview" target="_blank" rel="noopener">Abrir tarjeta en otra pestaña ↗</a><div class="tip"><span>✦</span><div><strong>Una buena primera impresión</strong><p>Usa una biografía breve y un logotipo claro. Tu tarjeta hará el resto.</p></div></div></aside>
      </div>
      </template>
      <footer class="page-footer"><a href="/api/backup">Descargar respaldo</a> <span>Diseñadas para conectar contigo.</span></footer>
    </div>
  </main>
</div>
</template>
