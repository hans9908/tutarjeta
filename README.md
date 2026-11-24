# Tarjetas Studio 2.0

Editor local en Vue 3, API en Python y almacenamiento SQLite. Conserva el motor de las cinco categorías, siete diseños por categoría y las líneas Formal, Moderna, Buchona, Lujo y Minimalista. La nueva aplicación no utiliza CustomTkinter ni necesita MySQL para trabajar.

## Iniciar

En Windows, abre `iniciar.cmd`. También puedes ejecutar desde esta carpeta:

```powershell
python -m pip install -r backend/requirements.txt
npm ci --prefix web
npm run build --prefix web
python -m backend.server
```

Abre http://127.0.0.1:8877. El lanzador inicia el servidor en segundo plano y abre el navegador cuando está listo. Puedes cerrar la ventana del lanzador. Si ejecutas directamente `python -m backend.server`, conserva esa consola abierta; Ctrl+C lo detiene. Requiere Python 3.10 o superior y Node.js 20.19 o superior para compilar. La interfaz ya está compilada en esta entrega. El primer inicio instala dependencias si faltan. El servidor solo escucha en tu computadora; no está preparado para exponerse directamente a internet como administrador multiusuario.

## Uso

1. Crea un cliente con una URL corta única y su nombre.
2. Completa contacto, biografía, categoría, diseño y enlaces. Los enlaces desactivados se guardan pero no aparecen en la tarjeta.
3. Carga un logotipo y, opcionalmente, un catálogo PDF. Sin logotipo se generan iniciales. Las imágenes cargadas se convierten realmente a PNG.
4. Guarda el borrador. En Entrega indica la URL final pública y pulsa Generar tarjeta.
5. Revisa la tarjeta generada y descarga el ZIP, QR o contacto. La vista móvil muestra la última generación; el boceto inicial solo orienta sobre el contenido.
6. Extrae el ZIP en tu hosting, en la URL que configuraste. Comprueba esa dirección y escanea el QR antes de entregarlo. La aplicación local no publica automáticamente.

Los datos nuevos están en `data/clients.sqlite3`, los archivos cargados en `data/uploads` y las tarjetas en `data/cards`. `dist/` conserva los resultados de la aplicación anterior. No confundas `web/dist/` (interfaz compilada) con `dist/` (tarjetas antiguas).

## Recuperar clientes de MySQL

Los archivos HTML y `dist/admin/clients.json` no contienen todos los campos del perfil. La nueva interfaz incluye enlaces de consulta a esas tarjetas antiguas sin inventar ni sobrescribir información. Para importar los datos completos, inicia MySQL en Laragon y ejecuta:

```powershell
python -m pip install mysql-connector-python
python -m backend.import_mysql
```

Por defecto lee `localhost:3306`, usuario `root`, base `tarjetas_db`. Si tu configuración difiere, establece `MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_USER`, `MYSQL_PASSWORD` y `MYSQL_DATABASE` en el entorno. La importación solo lee MySQL, copia archivos disponibles y omite clientes que ya existen en SQLite. Los errores de cada perfil se muestran por separado. Tras importar, genera de nuevo las tarjetas que necesites. No se altera la base original.

## Respaldos

El botón Descargar respaldo entrega un ZIP con una copia consistente de SQLite, archivos cargados y tarjetas. Contiene información de contacto: guárdalo en un lugar privado. Para restaurar, detén el servidor, guarda una copia de la carpeta `data` actual y extrae el respaldo dentro de `data`, en la misma ubicación del proyecto. Si mueves el proyecto a otra carpeta, los registros de archivos usan rutas absolutas: vuelve a cargar los logotipos y PDF afectados. Los ZIP individuales de tarjetas excluyen el perfil interno.

## Desarrollo y comprobación

```powershell
# Terminal 1
python -m backend.server
# Terminal 2
npm run dev --prefix web
# Pruebas en una base temporal, sin tocar tus clientes
python -m unittest discover -s tests -p test_studio.py -v
```

Vite redirige API y tarjetas al servidor en 8877. Después de editar la interfaz, ejecuta `npm run build --prefix web` para actualizar la versión servida por Python.

## Revisión del sistema anterior

- Un único `main.py` mezclaba ventanas, acceso a MySQL, generación, publicación y campañas. El nuevo generador no importa componentes de escritorio ni consulta la base.
- El guardado anterior forzaba todos los enlaces a activos. Se corrigió también en `main.py`.
- `requests` se importaba sin figurar en dependencias. Se agregó a las dependencias de la versión anterior; el backend nuevo no la necesita.
- Se agregó Guardar contacto a la tarjeta generada, escape del título HTML, protección contra esquemas ejecutables en enlaces y escape/plegado de vCards.
- Se validan identificadores, URLs, correos, rutas y archivos. Se rechazan identificadores duplicados al crear y cambios de URL corta al editar.
- La generación usa una carpeta temporal para conservar la tarjeta anterior si falla. Se identifica cuándo los datos guardados requieren regeneración.
- Se verificó el cierre de conexiones SQLite para evitar archivos bloqueados en Windows.
- El publicador anterior podía eliminar archivos remotos que no estuvieran en `dist`. No se trasladó ese mecanismo: esta versión exporta paquetes para hosting.

`main.py` sigue disponible para las funciones antiguas. La publicación directa en GitHub, su administrador público y la exportación automática de pósteres de campaña permanecen en esa versión; no están migradas al editor Vue. No se han publicado cambios ni se han eliminado archivos remotos.

## Validación realizada

Compilación de producción de Vue correcta. Cinco pruebas de integración correctas: persistencia/actualizaciones, generación y ZIP/QR/vCard/respaldo/eliminación, validación de solicitudes, carga de archivos y renderizado de las 35 plantillas. Se confirmó que la interfaz abre en el navegador integrado en http://127.0.0.1:8877. El puerto anterior 8765 estaba compartido por servidores de otros proyectos. El nuevo servidor reserva su puerto de forma exclusiva y el lanzador comprueba API e interfaz antes de abrir el navegador. La importación se intentó, pero MySQL rechazó la conexión en localhost:3306; falta iniciar el servicio en Laragon y ejecutar el importador.


## Gestión y catálogos

La pantalla inicial presenta el directorio de clientes con búsqueda, filtros por categoría y estado, ordenación, paginación y vistas de tabla o tarjetas. Desde la ficha puedes consultar el perfil, abrir la tarjeta, descargar el ZIP o pasar al editor. La eliminación pide confirmación en un diálogo.

En Catálogos puedes crear, consultar, editar, activar/desactivar y eliminar categorías, diseños, líneas visuales y redes. Se incluyen 35 registros iniciales. Los registros usados por clientes no se pueden eliminar; puedes desactivarlos para no ofrecerlos a nuevos perfiles. Los códigos son estables. Las nuevas categorías usan una de las cinco colecciones visuales compatibles; los nuevos nombres de diseños corresponden a una de las siete composiciones del generador.

El editor incluye una galería de siete composiciones: Editorial, Perfil, Mosaico, Esencial, Signature, Canvas y Portafolio. Cambian jerarquía, composición, formato del logotipo y presentación de enlaces, además de colores y tipografías. La selección explícita de diseño conserva siete opciones distintas incluso al cambiar la línea visual. El botón Previsualizar este diseño usa los datos actuales sin guardarlos ni sustituir la tarjeta entregable.

El encuadre vertical del logotipo se puede ajustar entre 0 y 100 por tarjeta. La tarjeta de Claudia usa 34% para centrar la marca de su imagen original vertical.

Validación actual: compilación de Vue y diez pruebas de integración correctas; directorio, catálogos, formularios, galería y composiciones Signature/Mosaico revisados en navegador. Las dos tarjetas importadas fueron regeneradas. Los ZIP en exportaciones contienen sus versiones actualizadas.


### Actualización automática del editor

La vista móvil se actualiza automáticamente al cambiar los datos, el diseño o el encuadre. Las solicitudes se procesan en orden y se descartan respuestas antiguas para evitar que reaparezca un diseño anterior. Guardar también regenera la tarjeta si tiene una URL final; sin ella conserva un borrador. El botón de actualización manual sigue disponible como respaldo. Se comprobó en el navegador el cambio automático Mosaico/Editorial y el guardado con regeneración. Pruebas de la cola de vista previa: `node --test tests/previewQueue.test.mjs`.
