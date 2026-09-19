# ADMIN Remote

Microfrontend Angular 17 para administración de pedidos. Se integra en el shell existente de `web-host`, sin duplicar navegación global, login, tokens ni refresh.

## Desarrollo

Desde esta carpeta, con Node 20 y npm:

```sh
npm ci
npm start
```

El servidor escucha en **8081**. Module Federation expone `./Routes`, cuyo export `ADMIN_ROUTES` se monta como hijos de `/admin`:

- `/admin/dashboard`: métricas derivadas, pedidos, búsqueda local y detalle.
- `/admin/cargas`: selección XLSX, seguimiento y reporte.
- `/admin/revision`: pedidos REQUIERE_REVISION, detalle, reintento y anulación con confirmación.

El host consume `http://localhost:8081/remoteEntry.js`. Angular/core, common/http, router, forms y RxJS comparten singleton con versión estricta; no se usa eager. El bootstrap standalone muestra un aviso de desarrollo y proporciona HttpClient únicamente para esa ejecución. Para sesión real, entrar desde el host.

## Sesión y configuración

Las rutas exportadas heredan el HttpClient/interceptor del host. No registran HttpClient, auth ni refresh propios. Así se conservan Bearer, correlationId y el flujo de renovación existente.

`window.__PEDIDOS_CONFIG__` permite configurar `javaApi`, `despachosApi`, `cargasApi`, `maxUploadBytes` y `maxOrderPages`. Valores por defecto: `/api/java`, `/api/despachos`, `/api/cargas`, 10485760 bytes y 100 páginas. Los prefijos deben coincidir con los que reconoce el interceptor del host. No se incluyen secretos internos. El proxy de desarrollo dirige estos prefijos a 8090/8091/8092.

## Funcionalidad y límites

El dashboard recorre páginas de 50 pedidos hasta una página menor o el límite seguro. Muestra total recuperado y seis estados; al alcanzar el límite avisa que las métricas son parciales. Búsqueda y filtro son locales. Son métricas de la API existente, sin endpoint de BI.

Carga masiva acepta un único `.xlsx` no vacío de hasta 10 MiB, con selección accesible y drag/drop. No analiza filas: envía FormData con campo `archivo` sin fijar Content-Type. Tras 202 guarda el ID e inicia consultas cada dos segundos mientras PROCESANDO. Detiene seguimiento al terminar o abandonar la pantalla. No presenta porcentaje hasta conocer el total de filas.

Los contadores muestran filas, aceptadas, rechazadas y duplicadas. El reporte se obtiene como Blob mediante HttpClient autenticado, conserva un nombre seguro de Content-Disposition y libera la URL temporal.

`admin-mfe.recentLoads` conserva como máximo diez IDs en sessionStorage, sin tokens. Son cargas iniciadas en esta sesión del navegador; se reconsultan al entrar y se retiran los IDs que responden 404. Al salir del área ADMIN se limpian para evitar compartir referencias con otro usuario. No existe listado histórico global ni endpoint de detalle de filas: el XLSX es la evidencia por fila.

Revisión consulta el detalle con pasos, compensaciones, intentos, duración y guía. Reintentar llama a .NET; anular llama a Java. Ambos requieren confirmación y refrescan el listado. La aceptación es asíncrona: seguir viendo REQUIERE_REVISION inmediatamente no significa fallo. Una anulación después de confirmar stock puede volver a requerir revisión.

## Diseño

Angular Material 17 y Lucide local; blanco `#FFFFFF`, azul `#006AA8`, naranja `#F69828`, verde `#8DC53E` y rojo semántico. Navegación secundaria compacta, foco visible, mensajes accesibles, grids adaptables y tablas con scroll interno. Sin CDN, Google Fonts, Bootstrap ni Tailwind.

## Validación

```sh
npm test
npm run build
```

27 pruebas focalizadas con Karma/Chrome. El build independiente produce `dist/admin-mfe/remoteEntry.js` y los chunks federados; no requiere host en ejecución ni importa sus fuentes.

Para reproducir el smoke, disponer del backend construido y del build existente del host. En terminales separadas:

```sh
# Desde la raíz, sin reconstruir imágenes:
docker compose up -d --no-build --wait --wait-timeout 240
# Desde esta carpeta:
npm run serve:host
npm start
npm run smoke
```

`serve:host` sirve el dist existente del host en 8080 en modo lectura y agrega el proxy HTTP de pruebas; no compila ni escribe en web-host. El smoke usa Chrome instalado en macOS y Playwright, login seed, rutas ADMIN, headers, aislamiento de roles y selección de archivo sin upload. Evidencias locales quedan en `.build/`. No sustituye una prueba de carga real ni los escenarios finales.

Pendiente: Docker/Compose final del frontend y validación global, fuera de este alcance. Ver `CONTRATOS_FRONT.md` y `RESUMEN_FINAL.md`.
