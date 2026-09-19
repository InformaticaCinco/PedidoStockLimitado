# Contratos Front ADMIN

El remoto consume exclusivamente contratos existentes. Prefijos runtime: Java `/api/java`, .NET `/api/despachos`, Python `/api/cargas`; el proxy retira el prefijo, sin alterar la ruta del servicio. Autorización ADMIN validada en backend. HttpClient/interceptor heredado del host añade Bearer y correlationId; el remoto no lee tokens ni renueva sesión.

Respuestas JSON: `{code,statusCode,message,data}`. Se extrae `data`. Los errores muestran mensajes seguros por estado HTTP, sin imprimir el JSON recibido. El reporte usa respuesta binaria, no envelope de éxito.

## Java

| Endpoint del servicio | Request | Respuesta utilizada |
|---|---|---|
| `GET /pedidos?pagina=0` | Página desde cero, sin filtros inventados | 200, `data: PedidoAdmin[]`, máximo 50 por página |
| `GET /pedidos/{id}` | ID codificado en ruta | 200, detalle con `guia`, `pasos`, `compensaciones` |
| `POST /pedidos/{id}/anulacion` | Sin body funcional (`null` en HttpClient) | 202: solicitud aceptada; 200: ya anulado; data con `pedidoId`, `estado`, `solicitudId`, `estadoReserva`, `anulacionSolicitada` |

`PedidoAdmin` incluye `pedidoId`, `estado`, `almacenId`, `subtotal`, `envio`, `total`, `pesoTotal`, `anulacionSolicitada`, `items`; `correlationId` y `zonaEntrega` se tratan como opcionales. Los importes aún no calculados pueden ser null. Cada paso/compensación expone `paso`, `estado`, `intentos`, `ms`; la guía puede ser null o `{id,estado}`.

Se recorren páginas hasta recibir menos de 50 o el límite seguro (100 por defecto). Los IDs se deduplican. Se advierte si los datos están limitados; los resultados no constituyen un snapshot transaccional ni estadísticas BI. Búsqueda por ID y filtro por estado operan sobre pedidos recuperados. Revisión solo muestra REQUIERE_REVISION.

Errores relevantes: 400 entrada inválida, 401 sesión, 403 permisos, 404 pedido inexistente; anulación 409 por estado incompatible/DESPACHADO; 500/503 indisponibilidad. La UI no presupone compensación completa tras 202: la carrera posterior a confirmar stock puede terminar nuevamente en REQUIERE_REVISION.

## .NET

`POST /despachos/{id}/reintento`, sin body funcional. 202: `data: {pedidoId,reintentoSolicitado:true}`. El worker retoma asíncronamente; se refresca la lista sin exigir transición inmediata.

Errores: 400 entrada inválida, 401 sesión, 403 sin rol ADMIN, 404 inexistente, 409 no reintentable/ya solicitado, 500 error seguro. Confirmación Material previa y bloqueo de doble acción mientras está pendiente.

## Python: cargas

`POST /cargas`: FormData con un único campo `archivo` de tipo File. No se fija boundary ni Content-Type. Validación local: presente, no vacío, extensión `.xlsx` sin distinción de mayúsculas, nombre seguro de hasta 200 caracteres y máximo configurable de 10485760 bytes. Las validaciones funcionales de Excel pertenecen al backend.

202: `data: {cargaId:"CG-..."}`. Se conserva el ID y comienza seguimiento. No se envía usuario/cliente desde el remoto. Errores: 400 archivo inválido, 401/403 auth, 413 límite, 500/503 fallo de servicio.

`GET /cargas/{id}`: 200, `data: {cargaId,estado,totales:{filas,aceptadas,rechazadas,duplicadas},reporte}`. Estados PROCESANDO, PROCESADA y ERROR; `reporte` es string o null. Polling cada dos segundos después de cada respuesta mientras PROCESANDO; se detiene en estados finales, error HTTP o destrucción del componente. La UI ofrece reintentar seguimiento ante error. Antes de conocer filas no inventa porcentaje. Cuando filas > 0 deriva `(aceptadas+rechazadas+duplicadas)/filas`, acotado a 100%.

`GET /cargas/{id}/reporte`: descarga autenticada con `responseType: blob`, conservando headers. Éxito 200 XLSX. Preserva filename/filename* UTF-8 seguro de Content-Disposition; fallback `reporte-{cargaId}.xlsx`. Se crea un enlace de descarga temporal y se revoca su Object URL. No abre una pestaña que pierda Bearer ni utiliza un URL arbitrario recibido del backend. Errores 409 aún no disponible, 404 inexistente, 500 inconsistencia; también 401/403/red manejados sin mostrar Blob como JSON.

## Referencias recientes y límites

Se guardan solo IDs iniciados desde esta UI en `sessionStorage["admin-mfe.recentLoads"]`, máximo diez únicos. Se reconsultan al entrar a cargas; 404 retira la referencia. Al salir del área ADMIN se limpia esa clave. La clave de sesión/auth del host no se toca. Dashboard consulta el ID más reciente conocido; sin referencias muestra “Sin carga activa en esta sesión”.

No se consume `GET /cargas` global, no se inventa `/cargas/{id}/detalle` ni filtros server-side. El reporte XLSX contiene la evidencia fila por fila. No hay llamadas al transportista ni secretos internos.

La UI contempla 400, 401, 403, 404, 409, 413, 500, 503 y error de red. El host conserva responsabilidad sobre refresh/logout/guards. El bootstrap standalone es solo desarrollo y no aporta sesión real.
