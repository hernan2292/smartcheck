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

## Desarrollo local

Necesitás el backend corriendo en `localhost:8000` (ver el README del branch `back`).

```bash
python -m http.server 3000
# abrir http://localhost:3000
```

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

- `TU-USUARIO/TU-REPO` → tu repo de GitHub
- `https://api.tudominio.com` → la URL de tu backend

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

## Dos cosas que te van a morder en el deploy

**1. CORS.** El backend tiene que tener tu dominio de Webflow en `CORS_ORIGINS`.
Si no, el navegador bloquea todo y la app muestra "no se pudo contactar el backend".

**2. HTTPS obligatorio.** Webflow sirve en HTTPS. Un backend en HTTP puro va a ser
bloqueado por *mixed content* sin siquiera intentar la request. Poné Caddy adelante
del backend (te resuelve el certificado solo) o usá el load balancer de DO.

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
