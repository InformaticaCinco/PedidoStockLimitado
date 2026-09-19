# Contratos consumidos por web-host

Fuente de verdad: `services/pedidos-java/CONTRATOS.md`, adaptador HTTP y modelos Java leídos sin modificar. El host utiliza `AuthApiService`, `ProductosApiService` y `PedidosApiService`; los componentes no dispersan HttpClient.

Base configurable `javaApi`, por defecto `/api/java`, resuelta por proxy a 8090. Sobre: `{code,statusCode,message,data,errores?}`. Los modelos funcionales TypeScript están en `src/app/core/models.ts`, sin `any`.

## Autenticación

| Endpoint | Body | Uso |
|---|---|---|
| POST `/auth/login` | `{usuario,clave}` | `{accessToken,refreshToken,expiraEn,usuario:{id,nombre,rol}}` en data |
| POST `/auth/refresh` | `{refreshToken}` | Mismo contrato, rotación y reemplazo |
| POST `/auth/logout` | `{refreshToken}` | Revocación; limpieza local también ante error |

La expiración se calcula como hora de recepción + expiraEn en segundos. No se guarda contraseña. Bearer solo en APIs configuradas, excluidos endpoints auth; `X-Correlation-Id` generado o propagado. Refresh single-flight, un reintento tras 401, limpieza si no puede renovar.

Java actualmente reemplaza el correlation ID recibido en su adaptador; el host lo envía/preserva correctamente, pero no garantiza continuidad en los logs Java. No se cambia backend.

## Productos y stock

| Endpoint | Body/parámetros | Estado de integración |
|---|---|---|
| GET `/productos?pagina=N` | Página desde 0, máximo 50 | Real, comprador y vendedor |
| POST `/productos` | `{sku,nombre,precio,peso}` | Formulario vendedor |
| PUT `/productos/{sku}` | `{nombre,precio,peso}` | Edición vendedor |
| GET `/productos/{sku}/stock?almacenId=...` | SKU y almacén | Consulta visible usando almacenId del producto |
| PUT `/productos/{sku}/stock?almacenId=...` | `{disponible}` | Editor vendedor usando almacenId del producto |

Producto recibido: `{sku,vendedorId,almacenId,nombre,precio,peso}`, consistente en GET/POST/PUT. Java resuelve `almacenId` mediante UsuarioAlmacen; no lo persiste en Producto. El gap de almacén está resuelto. Si una relación legada falta, el valor puede ser null y la UI bloquea ese producto sin inventar almacén.

Comprador: selección de un solo almacén; un intento de mezclarlo muestra un mensaje y no agrega el producto. POST pedidos toma el almacén de la selección, nunca de un input manual. Vendedor: consulta/edita stock con el almacén del producto; el diálogo muestra reservado/total y solo permite modificar disponible (entero 0–1000000000). La consulta inicial de stock limita concurrencia a seis solicitudes; cada fallo tiene reintento. No se usa el seed como API ni se infieren relaciones desde IDs.

Java devuelve el catálogo global incluso a VENDEDOR. El host reúne páginas y filtra por `vendedorId === usuario.id`; las mutaciones continúan protegidas por Java. Precio y peso se muestran numéricamente; el contrato no especifica moneda, por lo que no se inventa un símbolo.

Validación de alta: SKU `SKU-` y 5 dígitos; nombre no vacío hasta 120 caracteres; precio mínimo 0.01 y máximo 999999999.99; peso positivo hasta 100000 kg y 6 decimales. La UI no envía vendedor, propietario ni auditoría. El precio mínimo es conservador respecto del redondeo HALF_UP del backend.

## Pedidos

| Endpoint | Body/parámetros | Uso |
|---|---|---|
| POST `/pedidos` | `{solicitudId,almacenId,zonaEntrega,items:[{sku,cantidad}]}` | Creación habilitada; almacén real único de la selección |
| GET `/pedidos?pagina=N` | Paginado | Comprador: propios; vendedor: filtrado backend |
| GET `/pedidos/{pedidoId}` | ID | Detalle con guía/pasos/compensaciones |
| POST `/pedidos/{pedidoId}/anulacion` | `{}` | Confirmación comprador; 202/200 éxito, 409/404 mensajes seguros |

No se envían clienteId, precio, peso, usuario ni auditoría en creación. Solicitud UUID con guiones, estable durante el reintento de una intención; el borrador congela el contenido enviado y persiste por usuario hasta éxito. 202 nuevo y 200 idempotente navegan al mismo detalle.

Selección: máximo 20 SKU distintos, cantidades enteras de 1–50. Zonas del contrato: LIMA_METROPOLITANA, LIMA_PROVINCIA, PROVINCIA. El almacén procede de la respuesta de producto. Checkout queda habilitado con selección válida de un único almacén; conserva la intención durante reintentos.

Estados oficiales: RECIBIDO, EN_PROCESO, DESPACHADO, COMPENSANDO, ANULADO y REQUIERE_REVISION. Polling 2500 ms mientras esté activo; el error de consulta corta polling y permite reintentar. Al salir de la vista se cancela HTTP/temporizador.

Detalle: pedidoId, estado, almacenId, items, subtotal, envio/total nullable, pesoTotal, anulacionSolicitada; solicitudId/zonaEntrega/correlationId cuando estén presentes. La guía real es `{id,estado}`, no se inventan tracking URL ni datos ausentes. Pasos/compensaciones: `{paso,estado,intentos,ms}`; ms puede ser null. Se conservan intentos/registros múltiples.

La UI normaliza para presentación STOCK_RESERVAR → RESERVAR_STOCK, STOCK_CONFIRMAR → CONFIRMAR_DESPACHO y STOCK_LIBERAR → LIBERAR_STOCK; .NET también realiza su normalización persistida. Los pasos todavía ausentes se identifican como Pendiente, sin afirmar ejecución.

Vendedor: el backend filtra líneas y subtotal/peso propios; no se muestran montos globales, guía ni procesos del comprador en esa vista. Anulación no se ofrece al vendedor.

## Errores

Mensajes centralizados y seguros para 400, 401, 403, 404, 409, 422, 500, 503 y fallo de conexión. Java actualmente no usa 422, pero se contempla para consumidores futuros. No se muestran stack traces ni cuerpos JSON técnicos. Los formularios realizan validación local y preservan datos ante fallo.

## Remoto futuro

La única integración ADMIN es Module Federation ESM: URL runtime `adminRemoteEntry`, exposición `./Routes`, export `ADMIN_ROUTES`. Los servicios .NET/Python y transportista no se invocan desde las vistas comprador/vendedor. El futuro MFE deberá acordar su acceso a la sesión/configuración del host; no se expone la clave técnica del backend en frontend.

## Gaps externos

1. **Resuelto:** almacenId ya se proyecta en GET/POST/PUT productos desde UsuarioAlmacen. Crear pedido y Stock vendedor están habilitados. Las referencias históricas al bloqueo quedan superadas por este contrato.
2. La API de productos no filtra por vendedor ni devuelve total paginado. Filtrado del host requiere reunir páginas; convendría filtro servidor si crece el catálogo.
3. Correlación Java no preserva el header entrante.
4. Remoto ADMIN aún inexistente; el formato de exposición aquí se propone para el siguiente módulo y no se ha probado contra un MFE real.
5. El caso backend de anulación posterior a confirmación de stock sigue pudiendo acabar en REQUIERE_REVISION según acuerdo previo; la UI muestra ese estado sin declarar compensación completa.
