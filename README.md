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
sirve desde jsDelivr (que lee tu repo de GitHub) y Webflow solo lo carga.**

### 1. El repo tiene que ser público

jsDelivr solo sirve repos públicos. Si el tuyo es privado, la alternativa es
pegar el contenido de `app.css` y `app.js` directamente en los custom code de
Webflow (funciona, pero perdés el poder actualizar con un `git push`).

### 2. Pegar el snippet del `<head>`

Webflow Designer → **Page Settings** → Custom Code → *Inside `<head>` tag*.
Copiá [`webflow/head.html`](webflow/head.html) y reemplazá:

- `TU-USUARIO/TU-REPO` → ya viene con `hernan2292/smartcheck`

La URL del backend ya viene puesta y es HTTPS, así que no hay que tocar nada.

### 3. Pegar el embed en la página

Arrastrá un elemento **Embed** (Add panel → Components → Embed) donde quieras la
app y pegá [`webflow/embed.html`](webflow/embed.html), reemplazando
`TU-USUARIO/TU-REPO` igual que antes.

### 4. Publicar

Publicá el sitio en Webflow. El `<div id="smartcheck-app">` se llena solo.

### Actualizar después

`git push` a `main` y jsDelivr toma el cambio. Ojo: **jsDelivr cachea agresivamente**
(hasta 12h para un branch). Para forzar el refresh en la demo, usá un tag de
versión en la URL en vez del branch:

```
https://cdn.jsdelivr.net/gh/TU-USUARIO/TU-REPO@v0.1.1/src/app.js
```

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
