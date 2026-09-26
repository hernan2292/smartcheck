# SmartCheck — frontend

Frontend del auditor OWASP Smart Contract Top 10. Este branch (`main`) es lo que
se despliega en **Webflow**. El backend vive en el branch `back` y va a un droplet
de DigitalOcean.

**Vanilla JS, sin build step.** No es un capricho: a Webflow no le podés subir un
bundle de Vite ni correr npm. Solo te deja pegar código o cargar un `<script src>`.
Sin bundler, el mismo archivo sirve en local y por CDN.

```
src/
  app.js        # UI, render y polling
  api.js        # cliente HTTP del backend
  app.css       # estilos, todo namespaceado en .sc-
  taxonomy.js   # las 10 categorias — espejo de app/taxonomy.py del branch back
webflow/
  head.html     # pegar en Page Settings > Inside <head> tag
  embed.html    # pegar en un elemento Embed del body
index.html      # harness de dev local (no se despliega)
```

---

## Verlo funcionando ahora

El backend está desplegado en `https://138.197.155.202.sslip.io` (HTTPS con cert
de Let's Encrypt) y `index.html` apunta ahí por default. Solo hace falta servir
esta carpeta:

```bash
python -m http.server 5173 --bind 127.0.0.1
# abrir http://localhost:5173
```

> Se usa 5173 y no 3000 porque en esta máquina el 3000 ya lo ocupa otro proceso
> Node. Si cambiás de puerto, agregalo a `CORS_ORIGINS` en el `.env` del servidor
> o el navegador va a bloquear las requests.

Para apuntar a otro backend sin editar nada, pasalo por query string:

```
http://localhost:5173/?api=http://localhost:8000
```

El puerto 8000 del droplet ya **no** es accesible desde afuera: uvicorn escucha
solo en loopback y nginx hace de reverse proxy. Todo entra por HTTPS.

`index.html` replica exactamente lo que hacen los snippets de Webflow, así que
podés iterar sin publicar el sitio en cada cambio.

---

## Desplegar en Webflow

Webflow no hostea archivos arbitrarios, así que la estrategia es: **el código se
sirve desde jsDelivr (que lee este repo) y Webflow solo lo carga.** El repo es
público, que es lo único que jsDelivr necesita.

**No hay nada que reemplazar en los snippets.** El repo, la versión y la URL del
backend ya vienen puestos.

### 1. Pegar el `<head>`

Webflow Designer → **Page Settings** → Custom Code → *Inside `<head>` tag*.
Pegá [`webflow/head.html`](webflow/head.html) tal cual. Ahí van los estilos y la
URL del backend.

### 2. Pegar el embed

Arrastrá un elemento **Embed** (Add panel → Components → Embed) donde quieras la
app y pegá [`webflow/embed.html`](webflow/embed.html) tal cual.

### 3. Publicar

Publicá el sitio. El `<div id="smartcheck-app">` se llena solo.

Funciona sin configurar nada más porque el backend ya está detrás de HTTPS (no hay
mixed content) y su CORS acepta cualquier `https://<algo>.webflow.io` por regex
(no hace falta saber de antemano el nombre del sitio).

### Publicar cambios después

Los snippets apuntan a un **tag de versión**, no a `@main`. Es a propósito:
jsDelivr cachea un branch hasta 12h, así que con `@main` los cambios aparecen en
un momento impredecible — lo peor posible para una demo. Con un tag sabés
exactamente qué código se está sirviendo.

Para publicar una versión nueva:

```bash
git tag v0.1.1 && git push origin v0.1.1
```

y cambiás el número en las dos URLs (`head.html` y `embed.html`).

### Si le ponés un dominio propio al sitio

El regex de CORS solo cubre `*.webflow.io`. Un dominio propio hay que agregarlo a
`CORS_ORIGINS` en el `.env` del servidor y reiniciar el servicio.

---

## Lo que ya está resuelto del lado del backend

**CORS.** El backend acepta cualquier `https://<algo>.webflow.io` por regex, así
que publicar en Webflow funciona sin saber de antemano el nombre del sitio. Si le
ponés un **dominio propio**, ese sí hay que agregarlo a `CORS_ORIGINS` en el
`.env` del servidor.

**HTTPS.** Resuelto con Let's Encrypt sobre `138.197.155.202.sslip.io` — un
hostname que resuelve solo a la IP, así que no hizo falta ni un dominio propio ni
tocar el DNS. Ya no hay riesgo de mixed content.

**Rate limiting.** 5 análisis cada 10 minutos por IP. Si lo tocás, la app muestra
el mensaje del backend con los segundos de espera; el polling de un audit en curso
tolera un 429 y reintenta con backoff en vez de tirar la vista.

---

## Notas de diseño

- **Todo el CSS está namespaceado bajo `.sc-`** y las variables se declaran en
  `.sc-app`, no en `:root`. Webflow inyecta su propio reset y clases globales;
  sin el namespace se pelean.
- **Se usa `textContent`, nunca `innerHTML`.** El texto de los hallazgos viene de
  la API (y en última instancia del código del usuario), así que construir el DOM
  nodo por nodo evita cualquier inyección.
- **El modo explorar funciona con el backend caído.** `taxonomy.js` es una copia
  estática de las 10 categorías, así que alguien puede leer la taxonomía completa
  aunque no pueda auditar. Si el backend no responde, el form se dibuja igual y se
  muestra un aviso.
- **El polling se cancela.** Si arrancás un audit mientras otro está corriendo, el
  anterior se corta para que no pise el resultado.
- **El polling tolera fallos transitorios.** Un 429 o un corte de red momentáneo
  no descarta la vista: el análisis ya está corriendo en el backend, así que se
  reintenta con backoff exponencial y solo se abandona tras 5 fallos seguidos.
- **Hay un reset defensivo contra los estilos de Webflow.** Webflow inyecta su
  propio normalize y estilos base para `h1-h6`, `p`, `ul`, `a` y `label`; sin
  neutralizarlos la app hereda títulos gigantes, viñetas con `padding-left: 40px`
  y links subrayados. El reset usa `.sc-app :where(p)` y no `.sc-app p`: así queda
  en especificidad (0,1,0), que le gana a los selectores de elemento de Webflow
  (0,0,1) pero empata con las clases de componente, que por venir después siempre
  ganan. Con `.sc-app p` (0,1,1) el reset le pisaría los estilos a `.sc-hint`.
- **La URL del backend está duplicada a propósito** en `head.html` y como default
  en `api.js`. Si alguien pega solo el embed y se olvida del `<head>`, la app
  funciona igual; un default a `localhost` fallaría por mixed content con un error
  que no dice nada.
- **El embed muestra un placeholder y un error si el CDN falla.** `mount()` limpia
  el contenedor recién cuando tiene algo con qué reemplazarlo, así no hay un hueco
  en blanco mientras carga.

`taxonomy.js` es un **espejo** de `app/taxonomy.py` del branch `back`. Si cambia
una, hay que cambiar la otra — hoy es manual y es la deuda técnica más obvia del
MVP.

---

## Pendientes del MVP

- La UI de export ofrece Markdown y HTML; no hay PDF (el HTML imprime bien desde
  el browser).
- No hay estado en la URL: recargar pierde el resultado en pantalla. El audit
  sigue existiendo en el backend y accesible por su share link.
- UC6 (comparar dos versiones) y UC7 (historial por wallet) no están.
