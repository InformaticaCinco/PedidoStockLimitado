# Decisión 01: consistencia del stock en MongoDB

## Contexto

Pedidos individuales y pedidos importados compiten por existencias limitadas. Cada pedido puede tener varias líneas, todas del mismo almacén, y no debe reservar parcialmente ni producir cantidades negativas. MongoDB es la única base permitida. `CantidadStock` significa disponible; `ReservaStock`, comprometido. El total mostrado es su suma, no una tercera cantidad persistida que se descuente separadamente.

## Decisión

Se usa el replica set `rs0` de un nodo definido en Compose, necesario para las transacciones implementadas. Java ejecuta `ClientSession.withTransaction` con `ReadConcern.SNAPSHOT`, `WriteConcern.MAJORITY` y lectura primaria. El índice único `Stock(IdAlmacen, IdProducto)` identifica una existencia por producto/almacén.

`MongoRepositorio.operarStock` consulta el pedido y su `EstadoReserva`, ordena las líneas por SKU y ejecuta `findOneAndUpdate` con filtro de cantidad suficiente dentro de una única transacción:

| Operación para q unidades | Condición de cantidad | Cambio |
|---|---|---|
| RESERVAR | `CantidadStock >= q` | `CantidadStock -= q`, `ReservaStock += q` |
| LIBERAR | `ReservaStock >= q` | `CantidadStock += q`, `ReservaStock -= q` |
| CONFIRMAR | `ReservaStock >= q` | `ReservaStock -= q` |

La misma transacción incluye todas las líneas, `Pedido.EstadoReserva`, la transición de pedido cuando corresponde y el registro exitoso `PedidoProceso`. Si cualquier actualización no encuentra una fila compatible, lanza error y aborta los cambios de todas las líneas. En stock insuficiente se registra el intento fallido en una transacción posterior para conservar evidencia del rollback.

El alta de Pedido/PedidoDetalle también es transaccional, pero **alta y reserva no son una única transacción**: el alta deja RECIBIDO/NINGUNA y el worker .NET llama después al endpoint interno Java. Python inserta pedidos y sus detalles transaccionalmente, sin reservar durante la importación; pasan por el mismo mecanismo de despacho.

La concurrencia se controla con filtros atómicos, conflictos/reintentos transaccionales del driver, índice único y estado de reserva persistido. No hay mutex de aplicación que sustituya las garantías de Mongo. Una reserva cambia NINGUNA a RESERVADA; repetir el estado objetivo no vuelve a incrementar/descontar stock. Confirmación y liberación exigen estado compatible. La actualización del vendedor modifica solo disponible y conserva reservas.

## Alternativas consideradas

Alternativas de diseño para comparación, sin afirmar que fueran implementadas: leer stock y luego escribir sin condición permitiría carreras; un lock local no cubriría procesos distintos ni reinicios; actualizar cada línea por separado requeriría reparar reservas parciales. Guardar todo el catálogo en un documento trasladaría la contención y alteraría el modelo. Se conserva el modelo por existencia con transacciones multilínea.

## Consecuencias

Se requiere replica set incluso en desarrollo. La contención puede provocar reintentos y el éxito de HTTP 202 de alta no garantiza stock ni despacho. El worker del reto procesa secuencialmente, pero no se usa esa serialización como sustituto de las condiciones de stock. La confirmación reduce el total físico; reserva/liberación solo redistribuyen disponible y reservado.

Las transacciones Mongo no cubren el efecto remoto de crear una guía. Se usa coordinación persistida y compensación, no una transacción distribuida. La anulación después de stock CONFIRMADA no tiene restitución implementada: termina REQUIERE_REVISION. El replica set de un nodo habilita transacciones, pero no alta disponibilidad.

## Evidencia

- [Java MongoRepositorio](../../services/pedidos-java/src/main/java/pe/reto/pedidos/adapter/out/mongo/MongoRepositorio.java): `TX`, `crearPedido`, `operarStock`, `actualizarStock`.
- [Compose](../../docker-compose.yml), [índices](../../mongo/indexes/specs.py), [persistencia Python](../../services/cargas-python/app/infrastructure/mongo.py).
- [E2E 04](../../tests/evidencias/e2e04-repeticiones-02-10.json): repeticiones 02–10 con 40 competidores, tres despachos, 37 anulaciones y mínimos observados de stock no negativos; repetición 01 resumida como manual.
- [E2E 06](../../tests/evidencias/e2e06-pedido-multilinea-sin-stock.json): falta de stock en una línea sin cambios en la otra y sin guía.
- [E2E 09](../../tests/evidencias/e2e09-anulacion-durante-proceso.json): guía anulada y stock restituido.
- [E2E 15](../../tests/evidencias/e2e15-carga-masiva-500.json) y [E2E 16](../../tests/evidencias/e2e16-carga-masiva-trafico.json): cargas y tráfico individual convergen en el mismo stock limitado.

Son evidencias previas, no nuevas ejecuciones. La cobertura de diez ejecuciones distintas de E2E 16 tiene un **PENDIENTE DE CIERRE** documental descrito en [LEEME](../../LEEME.md): base y repetición 10 coinciden.
