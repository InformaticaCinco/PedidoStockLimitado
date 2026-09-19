# Contratos HTTP de pedidos

Todos los ejemplos de respuesta siguientes describen **`data`**, dentro del sobre:

```json
{"code":200,"statusCode":"HTTP_200_OK","message":"OK","data":{}}
```

Error: `{"code":400,"statusCode":"HTTP_400_BAD_REQUEST","message":"Entrada inválida","data":null,"errores":{"campo":"detalle"}}`. `errores` se omite si no hay detalle. Nunca se devuelve stack trace. Códigos comunes: 400 entrada/tipos/campos extra, 401 token ausente/expirado/firma/issuer/audience inválidos, 403 rol o producto/almacén ajeno, 404 recurso ausente/pedido de otro comprador, 409 conflicto, 500 fallo no controlado. No se utiliza 422.

## Health y seguridad

| Endpoint | Request | Response (`data`) | HTTP |
|---|---|---|---|
| GET `/health` | Sin body | `{"estado":"UP"}` | 200 sin consultar dependencias |
| GET `/health/dependencias` | Sin body | `{"dependencias":[{"nombre":"MongoDB","estado":"UP","latenciaMs":1}]}` | 200; 503 con data null y `errores` MongoDB=DOWN, latenciaMs y dependencias |
| POST `/auth/login` | `{"usuario":"login","clave":"password"}` | Access/refresh y usuario, ejemplo inferior | 200, 400, 401 idéntico para usuario/clave incorrectos |
| POST `/auth/refresh` | `{"refreshToken":"<token>"}` | Mismo contrato de login, refresh rotado | 200, 400 formato, 401 desconocido/revocado/expirado |
| POST `/auth/logout` | `{"refreshToken":"<token>"}` | `{"revocado":true}` | 200 idempotente incluso ya revocado/desconocido; 400 formato |
| GET `/.well-known/jwks.json` | Sin body | `{"keys":[{"kty":"RSA","kid":"...","alg":"RS256","use":"sig","n":"...","e":"AQAB"}]}` | 200 |

```json
{
  "accessToken":"<JWT RS256>",
  "expiraEn":900,
  "refreshToken":"<token aleatorio>",
  "usuario":{"id":"USR-004","nombre":"...","rol":"VENDEDOR"}
}
```

Tokens refresh: 43 caracteres base64url, 32 bytes aleatorios. Login admite texto usuario de 1–100 caracteres y clave de hasta 72 bytes UTF-8. JWT de APIs funcionales: `Authorization: Bearer <JWT>`; el refresh se usa únicamente para refresh/logout. La respuesta JWKS requiere extraer `data` por el sobre obligatorio.

## Productos y stock

| Endpoint | Request | Response (`data`) | HTTP |
|---|---|---|---|
| GET `/productos?pagina=0` | Sin body | Array de `{sku,vendedorId,almacenId,nombre,precio,peso}`; máximo 50 | 200, 400, 401 |
| POST `/productos` | `{sku,nombre,precio,peso}` | Producto con vendedor derivado del JWT; stock inicial 0 | 201, 400, 401, 403, 404 vendedor sin almacén, 409 SKU existente |
| PUT `/productos/{sku}` | `{nombre,precio,peso}` | Producto actualizado | 200, 400, 401, 403 ajeno, 404 |
| GET `/productos/{sku}/stock?almacenId=ALM-01` | Sin body | Ejemplo inferior | 200, 400, 401, 404 |
| PUT `/productos/{sku}/stock?almacenId=ALM-01` | `{"disponible":30}` | Stock actualizado, preservando reservado | 200, 400, 401, 403 ajeno, 404 |

```json
{"sku":"SKU-00042","nombre":"Producto de ejemplo","precio":19.90,"peso":1.25}
```

Respuesta de producto consistente en GET, POST y PUT (dentro de `data`; GET devuelve array):

```json
{"sku":"SKU-00042","vendedorId":"USR-VEN-01","almacenId":"ALM-01","nombre":"Producto de ejemplo","precio":19.90,"peso":1.25}
```

`almacenId` es una proyección de `Producto.IdUsuario → UsuarioAlmacen.IdUsuario → UsuarioAlmacen.IdAlmacen`, con relación un vendedor/un almacén. **No se persiste IdAlmacen en Producto** ni se acepta como campo del body de alta/edición. GET conserva paginación/orden y resuelve los vendedores de cada página en una consulta adicional con `$in` (sin N+1); POST/PUT reutilizan la relación ya consultada en su transacción. Si un dato legado carece de relación, GET devuelve `almacenId: null`, sin inferir otro almacén; el frontend debe impedir operaciones que lo requieran.

Peso: kg, positivo, hasta 100000 y 6 decimales. Precio positivo hasta 999999999.99, redondeo HALF_UP a dos decimales (debe seguir positivo después de redondear). Nombre: 1–120 caracteres no vacío. Stock disponible: entero 0–1000000000. No se reciben propietario ni auditoría del body.

```json
{"sku":"SKU-00042","almacenId":"ALM-01","total":30,"reservado":2,"disponible":28}
```

## Pedidos

POST `/pedidos`, rol COMPRADOR:

```json
{
  "solicitudId":"sol-000181",
  "almacenId":"ALM-01",
  "zonaEntrega":"LIMA_METROPOLITANA",
  "items":[{"sku":"SKU-00042","cantidad":2},{"sku":"SKU-00117","cantidad":1}]
}
```

Validación antes de persistir: SKU `SKU-` y 5 dígitos, almacén `ALM-` y 2 dígitos, solicitud alfanumérica/guiones de 1–60 caracteres, cantidad entera 1–50, 1–20 líneas sin SKU repetido. Zonas: `LIMA_METROPOLITANA`, `LIMA_PROVINCIA`, `PROVINCIA`. Strings numéricos, cantidades decimales, objetos Mongo, campos desconocidos o faltantes dan 400. Producto ausente: 404; producto de otro almacén: 400. No se acepta `clienteId`, precios ni pesos del cliente.

Respuesta primera válida, **202**:

```json
{"pedidoId":"PED-<uuid>","estado":"RECIBIDO","solicitudId":"sol-000181","estadoReserva":"NINGUNA","anulacionSolicitada":false}
```

Misma solicitud/contenido: **200**, mismo pedido y estado actual. Mismo ID y contenido/usuario diferente: **409** sin efecto. Las validaciones fallidas no consumen el ID. Registrar no reserva stock.

GET `/pedidos?pagina=0`: **200**, array paginado de pedidos según rol. GET `/pedidos/{pedidoId}`: **200**, además guía/procesos/compensaciones. Identificador `PED-` y hasta 60 alfanuméricos/guiones. Respuesta de comprador/ADMIN:

```json
{
  "pedidoId":"PED-<uuid>","estado":"EN_PROCESO","almacenId":"ALM-01",
  "solicitudId":"sol-000181","zonaEntrega":"LIMA_METROPOLITANA","correlationId":"<uuid>",
  "subtotal":39.80,"envio":null,"total":null,"pesoTotal":2.50,"anulacionSolicitada":false,
  "items":[{"sku":"SKU-00042","vendedorId":"USR-004","cantidad":2,"precioUnitario":19.90,"pesoUnitario":1.25,"subtotal":39.80}],
  "guia":null,
  "pasos":[{"paso":"STOCK_RESERVAR","estado":"COMPLETADO","intentos":1,"ms":12}],
  "compensaciones":[]
}
```

Envío/total permanecen null hasta el cálculo de despachos. `ms` es null si el paso no tiene fecha de fin. VENDEDOR solo obtiene líneas propias y subtotal/peso de esas líneas, sin información del comprador ni montos/procesos globales; pedido sin líneas propias da 404. COMPRADOR ajeno: 404. ADMIN puede consultar globalmente.

POST `/pedidos/{pedidoId}/anulacion`: sin body funcional (vacío o `{}`). **202** si todavía no terminó, incluso solicitud repetida; persiste `AnulacionSolicitada` sin compensar. **200** ya ANULADO; **409** DESPACHADO; **404** comprador ajeno/inexistente; **403** vendedor. La respuesta tiene el mismo formato resumido de creación con estado actual y flag de anulación.

## Operaciones internas

Header obligatorio `X-Internal-Key: <clave técnica configurada>`. No se aceptan headers de identidad ni JWT funcional como sustituto. Sin body funcional (vacío o `{}`).

| Endpoint POST | Efecto | HTTP |
|---|---|---|
| `/internal/pedidos/{pedidoId}/stock/reservar` | Reserva todas las líneas; RECIBIDO → EN_PROCESO | 200/repetición; 409 `STOCK_INSUFICIENTE` o reserva/estado/anulación incompatible |
| `/internal/pedidos/{pedidoId}/stock/liberar` | Devuelve reserva; sin reserva, no-op | 200/repetición; 409 confirmada o estado incompatible |
| `/internal/pedidos/{pedidoId}/stock/confirmar` | Reduce reservado, no disponible | 200/repetición; 409 sin reserva, liberada, anulación pendiente o estado incompatible |

Respuesta resumida como creación, incluido `estadoReserva`. Comunes: 400 ID/body, 401 clave técnica inválida/deshabilitada, 404 pedido, 500 error interno. Error de stock insuficiente identificable:

```json
{"code":409,"statusCode":"HTTP_409_CONFLICT","message":"STOCK_INSUFICIENTE","data":null}
```

La repetición exitosa no repite la mutación ni el proceso. Ninguna ruta interna completa el despacho ni la anulación funcional; esa coordinación corresponde a .NET.
