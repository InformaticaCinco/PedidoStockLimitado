# Gestión de Pedidos — web-host

Host independiente Angular **17.3.12**, standalone, Angular Material 17 y Module Federation webpack 17. Puerto de desarrollo **8080**. Implementa login, sesión, shell y experiencias COMPRADOR/VENDEDOR según el contrato Java disponible. ADMIN se carga exclusivamente desde el futuro remoto; no hay panel ADMIN local.

## Instalar y desarrollar

Node 18.13+ o 20.9+ dentro de esas versiones mayores y npm. Validado con Node 20.19.5 y npm 10.8.2.

```bash
cd frontend/web-host
npm ci
npm start
```

Abrir `http://localhost:8080`. La caché npm queda en `.build/npm-cache`, dentro del módulo. No se usa Angular CLI global.

El backend debe estar iniciado. Desde la raíz del repositorio, con las imágenes existentes:

```bash
docker compose up -d --no-build --wait --wait-timeout 240
```

No es necesario reconstruir backend ni ejecutar sus suites. Credenciales ficticias: ver `../../mongo/seed/credentials.md`.

## API y configuración

`src/assets/config.js` centraliza las bases de API y la URL del remoto. Se carga antes del bootstrap y puede sustituirse en una futura entrega sin cambiar componentes. El proxy de desarrollo `proxy.conf.json` transforma `/api/java/*` hacia Java 8090; también reserva prefijos para despachos 8091 y cargas 8092. El host actual consume únicamente Java. No contiene claves técnicas internas.

El build requiere que el futuro servidor estático resuelva las rutas SPA y los prefijos same-origin; `proxy.conf.json` solo se aplica al dev server. El host se sirve en la raíz del origen (`base href=/`, `publicPath=/`). No se crea aquí un gateway ni un Dockerfile.

## Identidad visual y responsive

Tokens en `src/styles.scss`: blanco `#FFFFFF`, azul `#006AA8`, naranja `#F69828` y verde `#8DC53E`. Las variantes oscuras se usan para texto legible; el rojo queda reservado a errores/anulación. Material utiliza la paleta azul y tipografía del sistema. Lucide proporciona SVG locales; no hay Google Fonts, CDN ni imágenes remotas.

Desktop: sidebar y topbar, catálogo en grid, productos del vendedor en tabla visual. Tablet y móvil: drawer por debajo de 1000 px, grids reducidos y cards; tablas de pedidos con scroll contenido. Formularios con labels, validaciones y foco visible; mensajes importantes con `aria-live`/`role=alert`, iconos con etiquetas accesibles y enlace para saltar al contenido. No se realizó una auditoría WCAG completa.

## Sesión y seguridad de navegación

Access token, refresh token, expiración calculada y usuario se guardan en `sessionStorage`. Nunca se guarda la contraseña. La sesión se restaura al recargar; un almacenamiento no disponible deja sesión en memoria.

El refresh se programa 30 s antes de expirar y también se resuelve al recibir 401. Un único observable compartido evita rotaciones concurrentes; access/refresh se reemplazan juntos. El interceptor reintenta como máximo una vez, preserva/genera `X-Correlation-Id`, excluye auth del flujo recursivo y solo envía Bearer a bases API configuradas. Un 401 tardío puede reutilizar el token ya renovado. La revocación de logout se intenta incluso durante una rotación; la limpieza local no depende de su éxito.

Los guards controlan navegación, no sustituyen validación de roles y pertenencia en el backend. El host no interpreta un JWT como prueba local de autorización; Java sigue siendo la autoridad.

## Rutas

| Rol | Ruta | Función |
|---|---|---|
| Público | `/login` | Login real y redirección por rol |
| COMPRADOR | `/comprador/catalogo` | Catálogo, búsqueda y selección |
| COMPRADOR | `/comprador/pedidos` | Lista propia paginada |
| COMPRADOR | `/comprador/pedidos/:pedidoId` | Detalle, polling y anulación |
| VENDEDOR | `/vendedor/productos` | Productos propios, alta y edición |
| VENDEDOR | `/vendedor/pedidos` | Pedidos con líneas propias |
| VENDEDOR | `/vendedor/pedidos/:pedidoId` | Solo información del vendedor |
| ADMIN | `/admin` y rutas hijas del remoto | Carga remota o fallback |

El catálogo se obtiene por páginas de 50 y se reúne para filtrar/buscar; Java devuelve productos globales también a vendedores. El host muestra al vendedor solo los de su `usuario.id`.

El detalle actualiza cada 2,5 s en RECIBIDO, EN_PROCESO y COMPENSANDO; termina en DESPACHADO, ANULADO, REQUIERE_REVISION o al destruir la vista. Los fallos de consulta se muestran y requieren reintento. Se presentan las líneas, importes disponibles, guía, intentos, duración y compensaciones reales. El vendedor no ve información global de comprador/despacho.

## Límite contractual: almacén

El backend no expone almacén en login/productos ni una consulta que permita resolverlo. **Stock y envío de nuevos pedidos están bloqueados en la UI por ese dato faltante.** No se deduce el almacén del SKU/usuario, no se copia el seed y no se añade un input manual de ALM.

`WarehouseResolver` devuelve `null` deliberadamente hasta disponer de una fuente contractual. Los servicios GET/PUT stock y POST pedido están tipados y probados con HTTP controlado; no debe confundirse eso con un checkout real habilitado.

La selección y el formulario de zona están preparados. Cuando pueda resolverse el almacén, `OrderDraft` conserva solicitudId y contenido inmutables durante reintentos (también en sessionStorage, por usuario). Tras una respuesta exitosa, 202 o repetición 200, limpia el borrador y navega al detalle. No se permite editar una intención cuyo resultado es ambiguo.

## Module Federation

Configuración real en `webpack.config.js` usando `@angular-architects/module-federation` y `ngx-build-plus`, bootstrap asíncrono y Angular/RxJS compartidos singleton con versión estricta. El host tiene `remotes: {}`: no registra ni descarga el remoto al iniciar y no configura precarga.

La ruta ADMIN ejecuta `adminCanMatch` antes de cargar su componente lazy. Solo ese componente invoca `loadRemoteModule` con:

- `type: 'module'`;
- URL configurable, por defecto `http://localhost:8081/remoteEntry.js`;
- `exposedModule: './Routes'`;
- export esperado `ADMIN_ROUTES: Routes`.

Este es el contrato **propuesto para el futuro admin-mfe**, no una afirmación de que ya exista. Sus rutas se montarán como hijas de `/admin` dentro del shell; debe exportar una ruta vacía para su pantalla inicial y utilizar versiones Angular compatibles. No se requiere remoteName para una entrada ESM.

Si no está disponible aparece “Módulo de administración no disponible”, con botón Reintentar. No se implementan cargas, dashboard ni reintentos ADMIN localmente. COMPRADOR/VENDEDOR se redirigen antes del loader; se verifica tanto con router tests como con tráfico real del navegador.

`publicPath=/` evita que webpack introduzca `import.meta.url` en el `styles.js` que Angular CLI 17 inyecta como script clásico durante desarrollo. El remoto sigue siendo ESM y conserva su propia configuración de assets.

Referencias consultadas: [plugin oficial y compatibilidad Angular 17](https://github.com/angular-architects/module-federation-plugin/blob/main/libs/mf/README.md), [Module Federation con standalone](https://www.angulararchitects.io/blog/module-federation-with-angulars-standalone-components/).

## Tests y build

```bash
npm test
npm run build
```

Tests Jasmine/Karma en Chrome Headless. En macOS se detecta Chrome instalado; en otros entornos definir `CHROME_BIN` apuntando a Chrome/Chromium. El build de producción se genera en `dist/web-host`. Los resultados de esta ejecución están en `RESUMEN_FINAL.md`.

Smoke de navegador opcional, con backend y `npm start` activos:

```bash
npm run smoke
```

Usa Playwright y Chrome existente, sin instalar navegador adicional. Permite sobrescribir `CHROME_BIN`. Verifica comprador01, vendedor01 y fallback admin, reload, aislamiento remoto, UI móvil y APIs mediante proxy. No crea pedidos ni modifica productos/stock. No guarda tokens completos en evidencias. Las capturas y resultados se escriben en `.build/`.

## Pendiente

Contrato para resolver almacenes; admin-mfe; servidor/gateway y Compose frontend; publicación e integración final. No se modifican módulos externos en este paso.
