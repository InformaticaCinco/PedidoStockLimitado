# Contratos de despachos-dotnet

Base `http://localhost:8091`. Respuesta común:

```json
{"code":200,"statusCode":"HTTP_200_OK","message":"OK","data":{}}
```

Errores: `data:null`; `errores` cuando hay detalle. Sin stack traces. No se exponen endpoints de pruebas. No se emiten tokens.

## GET /health

Público, sin body ni acceso a dependencias. **200**:

```json
{"code":200,"statusCode":"HTTP_200_OK","message":"OK","data":{"estado":"UP"}}
```

## GET /health/dependencias

Público. Comprueba ping MongoDB, GET `/health` Java y GET `/health` transportista, con límite de cinco segundos por comprobación y ejecución en paralelo.

**200** si todos están UP:

```json
{"code":200,"statusCode":"HTTP_200_OK","message":"OK","data":{"dependencias":[{"nombre":"MongoDB","estado":"UP","latenciaMs":2},{"nombre":"pedidos-java","estado":"UP","latenciaMs":3},{"nombre":"transportista","estado":"UP","latenciaMs":4}]}}
```

**503** si alguno falla; mismo array en `errores.dependencias`, `data:null`. No se revela el mensaje de excepción ni URL/credenciales. `/health` del futuro transportista es una decisión de integración que debe implementar ese módulo.

## POST /despachos/{pedidoId}/reintento

Decisión REST prevista por el documento; no existía contrato anterior. `Authorization: Bearer <JWT>`; solo ADMIN. Sin body. ID `PED-` más 1–60 alfanuméricos/guiones.

**202**:

```json
{"code":202,"statusCode":"HTTP_202_ACCEPTED","message":"ACCEPTED","data":{"pedidoId":"PED-...","reintentoSolicitado":true}}
```

Solicita de forma persistente un ciclo de reintento; no ejecuta HTTP externo dentro del request. Mantiene el estado REQUIERE_REVISION hasta que el worker lo reclame, conserva efectos y paso pendiente, reinicia el presupuesto por paso y audita con `sub` del JWT. Si se estaba compensando, reanuda compensación.

- 400: ID incorrecto o body presente.
- 401: token ausente, vencido, firma/algoritmo/issuer/audience inválidos, claims obligatorios ausentes.
- 403: rol distinto de ADMIN.
- 404: pedido inexistente.
- 409: estado distinto de REQUIERE_REVISION o solicitud ya pendiente.
- 500: error interno no controlado.

La anulación pública sigue exclusivamente en Java: `POST /pedidos/{pedidoId}/anulacion`.

## JWT/JWKS

Consumir `JWT_JWKS_URL`, por defecto Java `/.well-known/jwks.json`:

```json
{"code":200,"statusCode":"HTTP_200_OK","message":"OK","data":{"keys":[{"kty":"RSA","kid":"...","alg":"RS256","use":"sig","n":"...","e":"AQAB"}]}}
```

Se extrae `data` como JWKSet y sus `keys`; no se interpreta el sobre completo como JWKS estándar. Validación local independiente RS256, firma, exp obligatoria sin tolerancia adicional, iss/aud exactos; `sub` y `rol` requeridos. No se llama a login/refresh ni se delega la validación a Java. No se confía en X-User-Id/X-Role. La clave privada de Java solo es usada por el proceso Java en las pruebas de integración, nunca por el validador .NET.

## HTTP saliente Java

| POST | Header | Body | Éxito |
|---|---|---|---|
| `/internal/pedidos/{id}/stock/reservar` | `X-Internal-Key` | Vacío | 200, data.pedidoId y estadoReserva=RESERVADA |
| `/internal/pedidos/{id}/stock/liberar` | `X-Internal-Key` | Vacío | 200, estadoReserva=LIBERADA |
| `/internal/pedidos/{id}/stock/confirmar` | `X-Internal-Key` | Vacío | 200, estadoReserva=CONFIRMADA |

También se envía `X-Correlation-Id`. Se valida el sobre y el pedido de respuesta. Solo se llama liberar cuando se observó reserva efectiva; Java sin reserva puede devolver NINGUNA como no-op, caso que no requiere llamada desde este flujo.

409 con `message=STOCK_INSUFICIENTE`: fallo de negocio terminal, ANULADO sin compensación si no hubo efectos. 5xx/408/429 o conexión/timeout: reintento limitado; otros conflictos/contratos inválidos: revisión o anulación si se observó la solicitud. No se modifica Stock desde .NET.

## HTTP saliente transportista

**POST `/guias`**, headers `Idempotency-Key: despacho-guia-{pedidoId}` y `X-Correlation-Id`:

```json
{"pedidoId":"PED-...","pesoKg":12.4,"zona":"LIMA_METROPOLITANA"}
```

Respuesta 2xx: `{"numeroGuia":"G-..."}`. Número alfanumérico/guiones hasta 80 caracteres. Esta respuesta no lleva sobre Java, conforme al documento del transportista.

**GET `/guias?pedidoId=PED-...`**: contrato de consulta acotado, definido aquí porque no había respuesta especificada: 200 con `{"numeroGuia":"G-..."}` para guía activa; **404** para ausencia confirmada de guía activa. Otras respuestas y JSON inválido son errores, nunca ausencia. Se consulta antes de cada POST y después de un fallo ambiguo; usar guía encontrada, sin POST adicional. El transportista debe garantizar idempotencia remota con la clave estable.

**POST `/guias/{numero}/anulacion`**, vacío; headers `Idempotency-Key: anulacion-despacho-guia-{pedidoId}` y `X-Correlation-Id`. 2xx o 404 establecen guía anulada/ausente; demás resultados requieren reintento/revisión. Debe ser idempotente. Solo después se libera stock.

**GET `/health`**: 2xx indica disponibilidad, usado únicamente para health/dependencias. Pendiente implementarlo en el futuro simulador.

## Casos de integración que requieren cambios externos

1. Confirmación Java irreversible seguida de anulación antes del cierre .NET: REQUIERE_REVISION según decisión expresa del usuario; no se declara una compensación completa.
2. Java no preserva actualmente X-Correlation-Id recibido; el header se envía correctamente pero Java genera otro en sus propios logs.
3. Seed global debe definir Estado/Zona/ZonaTramo/Transporte con los campos/representaciones documentados en README; no se genera aquí.
