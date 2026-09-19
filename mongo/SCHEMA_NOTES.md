# Inspección física previa al seed

Fuentes leídas: CONTRATOS/RESUMEN y Model.java, Reglas.java, MongoRepositorio.java, RsaSeguridad.java y Settings.java de Java; RESUMEN, MongoRepositorio.cs y Modelos.cs de .NET; RESUMEN y repositorio Mongo de cargas-python. No se localizaron los tres PDF en el repositorio ni con sus nombres exactos en Descargas.

- Identificadores físicos `_id` string; Producto `_id=SKU`, referencias IdProducto=SKU.
- Usuario: Usuario (login único), Nombre, IdRol, ClaveHash. jBCrypt Java requiere hash compatible `$2a$`. No valida otro patrón para IdUsuario.
- Cliente.IdUsuario apunta a comprador. UsuarioAlmacen impone unicidad tanto IdUsuario como IdAlmacen.
- Producto: IdUsuario vendedor, Precio/Peso Decimal128. Stock: IdAlmacen/IdProducto, CantidadStock disponible, ReservaStock reservada; total=suma. No usar disponible=total-reserva nuevamente.
- Pedido: IdEstado código, PesoTotal/Envio; no campos alternativos IdPedido/TotalPeso/CostoEnvio.
- Activos .NET: IdEstado=ACTIVO o referencias a Estado.Nombre=ACTIVO. Zona por `_id` o Codigo; ZonaTramo: IdZona, IdEstado, DesdeKg, HastaKg, Tarifa Decimal128; intervalos [desde,hasta). Transporte: exactamente uno activo.
- Cargas usa los mismos catálogos; nuevos seed con IdEstado explícito evitan depender de su regla legado de ausencia de estado.
- Índice Worker: Nombre único, nombre una_corrida_abierta, partialFilterExpression {FechaFin:null}. TTL RefreshToken.Expiracion=0.
- Java predetermina database PedidoStockLimitado; cargas predetermina pedido_stock_limitado. El dataset global usará pedidos_stock configurable: Compose deberá pasar el mismo MONGODB_DATABASE a todos.
- Canonicalización Pedido permanece en servicios: usuario comprador (longitud UTF-16), almacén, zona, SKU:cantidad ordenados, SHA-256. El seed no crea Pedidos.

Decisiones: zonas con `_id` igual al código funcional, sin aliases; estados con `_id=Nombre=código`; IDs propios deterministas para maestros. Rango de tarifas [0,2500) cubre el máximo conservador del fixture (20×50×2=2000 kg). No se interpreta [0,50) como cobertura suficiente.
