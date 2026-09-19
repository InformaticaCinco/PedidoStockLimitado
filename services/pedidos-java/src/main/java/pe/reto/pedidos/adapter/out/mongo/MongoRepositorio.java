package pe.reto.pedidos.adapter.out.mongo;

import static pe.reto.pedidos.domain.Model.*;
import static pe.reto.pedidos.domain.Reglas.*;
import static com.mongodb.client.model.Filters.*;
import static com.mongodb.client.model.Updates.*;
import static com.mongodb.client.model.Indexes.*;
import com.mongodb.*;
import com.mongodb.client.*;
import com.mongodb.client.model.*;
import org.bson.Document;
import org.bson.conversions.Bson;
import org.bson.types.Decimal128;
import pe.reto.pedidos.application.port.out.Repositorio;
import pe.reto.pedidos.domain.Fallo;
import java.math.BigDecimal;
import java.time.*;
import java.util.*;
import java.util.function.Function;

public final class MongoRepositorio implements Repositorio {
    private final MongoClient client;
    private final MongoDatabase db;
    private final Clock reloj;
    // One-node replica set in development; transactions ensure complete-order-or-nothing.
    // Conditional writes prevent negative stock; no in-memory locks are used.
    private static final TransactionOptions TX = TransactionOptions.builder().readConcern(ReadConcern.SNAPSHOT)
            .writeConcern(WriteConcern.MAJORITY).readPreference(ReadPreference.primary()).build();
    public MongoRepositorio(MongoClient client, MongoDatabase db, Clock reloj) {
        this.client = client; this.db = db.withReadConcern(ReadConcern.MAJORITY).withWriteConcern(WriteConcern.MAJORITY).withReadPreference(ReadPreference.primary()); this.reloj = reloj;
    }
    private MongoCollection<Document> c(String nombre) { return db.getCollection(nombre); }
    private <T> T tx(Function<ClientSession, T> action) {
        try (ClientSession s = client.startSession(ClientSessionOptions.builder().causallyConsistent(true).build())) {
            return s.withTransaction(() -> action.apply(s), TX);
        }
    }
    private Date ahora() { return Date.from(reloj.instant()); }
    private Document audit(Document d, String actor) { return d.append("UsuarioCreacion", actor).append("FechaCreacion", ahora()).append("UsuarioModificacion", null).append("FechaModificacion", null); }
    private Bson mod(String actor) { return combine(set("UsuarioModificacion", actor), set("FechaModificacion", ahora())); }
    private static Document requerido(Document d, String mensaje) { if (d == null) throw new Fallo(404, mensaje); return d; }
    private static String id(String prefijo) { return prefijo + UUID.randomUUID(); }
    private static Decimal128 decimal(BigDecimal n) { return n == null ? null : new Decimal128(n); }
    private static BigDecimal numero(Document d, String k) { return d.get(k) == null ? null : d.get(k, Decimal128.class).bigDecimalValue(); }

    public void crearIndices() {
        // Each index either enforces cardinality or serves an explicit access path.
        c("Pedido").createIndex(ascending("IdSolicitud"), new IndexOptions().unique(true));
        c("Pedido").createIndex(ascending("IdCliente", "_id"));
        c("Producto").createIndex(ascending("SKU"), new IndexOptions().unique(true));
        c("Producto").createIndex(ascending("IdUsuario"));
        c("Stock").createIndex(ascending("IdAlmacen", "IdProducto"), new IndexOptions().unique(true));
        c("Usuario").createIndex(ascending("Usuario"), new IndexOptions().unique(true));
        c("Cliente").createIndex(ascending("IdUsuario"), new IndexOptions().unique(true));
        c("UsuarioAlmacen").createIndex(ascending("IdUsuario"), new IndexOptions().unique(true));
        c("UsuarioAlmacen").createIndex(ascending("IdAlmacen"), new IndexOptions().unique(true));
        c("PedidoDetalle").createIndex(ascending("IdPedido", "IdProducto"), new IndexOptions().unique(true));
        c("PedidoDetalle").createIndex(ascending("IdUsuarioVendedor", "IdPedido"));
        c("PedidoProceso").createIndex(ascending("IdPedido", "FechaInicio"));
        c("Guia").createIndex(ascending("IdPedido"), new IndexOptions().unique(true));
        c("RefreshToken").createIndex(ascending("Expiracion"), new IndexOptions().expireAfter(0L, java.util.concurrent.TimeUnit.SECONDS));
    }
    private Usuario usuario(Document u) {
        Document r = requerido(c("Rol").find(eq("_id", u.getString("IdRol"))).first(), "Rol no encontrado");
        return new Usuario(u.getString("_id"), u.getString("Nombre"), Rol.valueOf(r.getString("Nombre")), u.getString("ClaveHash"));
    }
    public Optional<Usuario> usuarioPorLogin(String login) { return Optional.ofNullable(c("Usuario").find(eq("Usuario", login)).first()).map(this::usuario); }
    public Optional<Usuario> usuarioPorId(String id) { return Optional.ofNullable(c("Usuario").find(eq("_id", id)).first()).map(this::usuario); }
    private Document refreshDoc(Refresh r) { return audit(new Document("_id", r.hash()).append("IdUsuario", r.usuarioId()).append("Expiracion", Date.from(r.expira())).append("Revocado", false).append("FechaRevocacion", null), r.usuarioId()); }
    private Bson activo(String hash) { return and(eq("_id", hash), eq("Revocado", false), gt("Expiracion", ahora())); }
    public void guardarRefresh(Refresh r) { c("RefreshToken").insertOne(refreshDoc(r)); }
    public Optional<Refresh> refreshActivo(String hash) {
        Document d = c("RefreshToken").find(activo(hash)).first();
        return d == null ? Optional.empty() : Optional.of(new Refresh(hash, d.getString("IdUsuario"), d.getDate("Expiracion").toInstant()));
    }
    public boolean rotarRefresh(String hash, Refresh siguiente) {
        return tx(s -> {
            var result = c("RefreshToken").updateOne(s, and(activo(hash), eq("IdUsuario", siguiente.usuarioId())), combine(set("Revocado", true), set("FechaRevocacion", ahora()), mod(siguiente.usuarioId())));
            if (result.getModifiedCount() != 1) return false;
            c("RefreshToken").insertOne(s, refreshDoc(siguiente)); return true;
        });
    }
    public void revocarRefresh(String hash) {
        Document d = c("RefreshToken").find(eq("_id", hash)).first();
        if (d != null) c("RefreshToken").updateOne(and(eq("_id", hash), eq("Revocado", false)), combine(set("Revocado", true), set("FechaRevocacion", ahora()), mod(d.getString("IdUsuario"))));
    }
    private Producto producto(Document p, String almacenId) {
        return new Producto(p.getString("SKU"), p.getString("IdUsuario"), almacenId,
                p.getString("Nombre"), numero(p, "Precio"), numero(p, "Peso"));
    }
    public List<Producto> productos(int pagina) {
        List<Document> productos = c("Producto").find().sort(ascending("SKU"))
                .skip(pagina * 50).limit(50).into(new ArrayList<>());
        if (productos.isEmpty()) return List.of();
        // Resolve the whole page with one additional query, never one query per product.
        Set<String> vendedores = new HashSet<>();
        productos.forEach(p -> vendedores.add(p.getString("IdUsuario")));
        Map<String, String> almacenes = new HashMap<>();
        c("UsuarioAlmacen").find(in("IdUsuario", vendedores))
                .forEach(rel -> almacenes.put(rel.getString("IdUsuario"), rel.getString("IdAlmacen")));
        // An inconsistent legacy relationship stays null; never guess a warehouse.
        return productos.stream().map(p -> producto(p, almacenes.get(p.getString("IdUsuario")))).toList();
    }
    private Document relacion(ClientSession s, String vendedor) { return requerido(c("UsuarioAlmacen").find(s, eq("IdUsuario", vendedor)).first(), "Vendedor sin almacén"); }
    public Producto guardarProducto(Actor actor, DatosProducto p, boolean nuevo) {
        try {
            return tx(s -> {
                Document rel = relacion(s, actor.id());
                requerido(c("Almacen").find(s, eq("_id", rel.getString("IdAlmacen"))).first(), "Almacén no encontrado");
                Document existente = c("Producto").find(s, eq("SKU", p.sku())).first();
                if (nuevo && existente != null) throw new Fallo(409, "SKU existente");
                if (!nuevo) {
                    requerido(existente, "Producto no encontrado");
                    if (!actor.id().equals(existente.getString("IdUsuario"))) throw new Fallo(403, "Producto ajeno");
                    c("Producto").updateOne(s, eq("SKU", p.sku()), combine(set("Nombre", p.nombre()), set("Precio", decimal(dinero(p.precio()))), set("Peso", decimal(p.peso())), mod(actor.id())));
                } else {
                    c("Producto").insertOne(s, audit(new Document("_id", p.sku()).append("SKU", p.sku()).append("IdUsuario", actor.id()).append("Nombre", p.nombre()).append("Precio", decimal(dinero(p.precio()))).append("Peso", decimal(p.peso())), actor.id()));
                    c("Stock").insertOne(s, audit(new Document("_id", id("STK-")).append("IdAlmacen", rel.getString("IdAlmacen")).append("IdProducto", p.sku()).append("CantidadStock", 0).append("ReservaStock", 0), actor.id()));
                }
                return new Producto(p.sku(), actor.id(), rel.getString("IdAlmacen"), p.nombre(), dinero(p.precio()), p.peso());
            });
        } catch (MongoException e) { if (e.getCode() == 11000) throw new Fallo(409, "SKU existente"); throw e; }
    }
    private Stock stock(Document d) { return new Stock(d.getString("IdProducto"), d.getString("IdAlmacen"), d.getInteger("CantidadStock"), d.getInteger("ReservaStock")); }
    private Bson stockKey(String sku, String almacen) { return and(eq("IdAlmacen", almacen), eq("IdProducto", sku)); }
    public Stock stock(String sku, String almacen) { return stock(requerido(c("Stock").find(stockKey(sku, almacen)).first(), "Stock no encontrado")); }
    public Stock actualizarStock(Actor a, String sku, String almacen, int disponible) {
        return tx(s -> {
            Document p = requerido(c("Producto").find(s, eq("SKU", sku)).first(), "Producto no encontrado");
            if (!a.id().equals(p.getString("IdUsuario"))) throw new Fallo(403, "Producto ajeno");
            if (!almacen.equals(relacion(s, a.id()).getString("IdAlmacen"))) throw new Fallo(403, "Almacén ajeno");
            // Sets only available units. Existing reservations are never overwritten.
            Document d = c("Stock").findOneAndUpdate(s, stockKey(sku, almacen), combine(set("CantidadStock", disponible), mod(a.id())), new FindOneAndUpdateOptions().returnDocument(ReturnDocument.AFTER));
            return stock(requerido(d, "Stock no encontrado"));
        });
    }
    private Detalle detalle(Document d) { return new Detalle(d.getString("IdProducto"), d.getString("IdUsuarioVendedor"), d.getInteger("Cantidad"), numero(d, "PrecioUnitario"), numero(d, "PesoUnitario"), numero(d, "Subtotal")); }
    private Pedido pedido(ClientSession s, Document d) {
        List<Detalle> detalles = c("PedidoDetalle").find(s, eq("IdPedido", d.getString("_id"))).sort(ascending("IdProducto")).map(this::detalle).into(new ArrayList<>());
        return new Pedido(d.getString("_id"), d.getString("IdSolicitud"), d.getString("IdCliente"), d.getString("IdUsuarioComprador"), d.getString("IdAlmacen"), d.getString("ZonaEntrega"), d.getString("HuellaContenido"), Estado.valueOf(d.getString("IdEstado")), numero(d, "Subtotal"), numero(d, "Envio"), numero(d, "Total"), numero(d, "PesoTotal"), d.getString("CorrelationId"), d.getBoolean("AnulacionSolicitada", false), Reserva.valueOf(d.getString("EstadoReserva")), detalles);
    }
    public Creacion crearPedido(Actor a, NuevoPedido input, String huella, String correlationId) {
        try {
            return tx(s -> {
                Document anterior = c("Pedido").find(s, eq("IdSolicitud", input.solicitudId())).first();
                if (anterior != null) return repeticion(pedido(s, anterior), huella);
                Document cliente = requerido(c("Cliente").find(s, eq("IdUsuario", a.id())).first(), "Cliente no encontrado");
                String pedidoId = id("PED-");
                BigDecimal subtotal = BigDecimal.ZERO, peso = BigDecimal.ZERO;
                List<Document> detalles = new ArrayList<>();
                for (Item item : input.items().stream().sorted(Comparator.comparing(Item::sku)).toList()) {
                    Document p = requerido(c("Producto").find(s, eq("SKU", item.sku())).first(), "Producto no encontrado");
                    if (!input.almacenId().equals(relacion(s, p.getString("IdUsuario")).getString("IdAlmacen"))) throw new Fallo(400, "Producto no corresponde al almacén");
                    requerido(c("Stock").find(s, stockKey(item.sku(), input.almacenId())).first(), "Stock no encontrado");
                    BigDecimal precio = dinero(numero(p, "Precio")), pesoUnitario = numero(p, "Peso");
                    BigDecimal parcial = dinero(precio.multiply(BigDecimal.valueOf(item.cantidad())));
                    subtotal = subtotal.add(parcial); peso = peso.add(pesoUnitario.multiply(BigDecimal.valueOf(item.cantidad())));
                    detalles.add(audit(new Document("_id", id("DET-")).append("IdPedido", pedidoId).append("IdProducto", item.sku()).append("IdUsuarioVendedor", p.getString("IdUsuario")).append("Cantidad", item.cantidad()).append("PrecioUnitario", decimal(precio)).append("PesoUnitario", decimal(pesoUnitario)).append("Subtotal", decimal(parcial)), a.id()));
                }
                Document d = audit(new Document("_id", pedidoId).append("IdSolicitud", input.solicitudId()).append("IdCliente", cliente.getString("_id")).append("IdUsuarioComprador", a.id()).append("IdAlmacen", input.almacenId()).append("ZonaEntrega", input.zonaEntrega()).append("HuellaContenido", huella).append("IdEstado", Estado.RECIBIDO.name()).append("Subtotal", decimal(dinero(subtotal))).append("Envio", null).append("Total", null).append("PesoTotal", decimal(peso)).append("CorrelationId", correlationId).append("AnulacionSolicitada", false).append("FechaSolicitudAnulacion", null).append("EstadoReserva", Reserva.NINGUNA.name()), a.id());
                c("Pedido").insertOne(s, d); c("PedidoDetalle").insertMany(s, detalles);
                return new Creacion(pedido(s, d), true);
            });
        } catch (MongoException e) {
            if (e.getCode() != 11000) throw e;
            return tx(s -> repeticion(pedido(s, requerido(c("Pedido").find(s, eq("IdSolicitud", input.solicitudId())).first(), "Pedido no encontrado")), huella));
        }
    }
    private Proceso proceso(Document d) { return new Proceso(d.getString("Paso"), d.getString("IdEstadoProceso"), d.getInteger("NroIntento"), d.getDate("FechaInicio") == null ? null : d.getDate("FechaInicio").toInstant(), d.getDate("FechaFin") == null ? null : d.getDate("FechaFin").toInstant(), d.getString("Log")); }
    public VistaPedido pedido(String id) {
        return tx(s -> {
            Pedido p = pedido(s, requerido(c("Pedido").find(s, eq("_id", id)).first(), "Pedido no encontrado"));
            List<Proceso> pasos = new ArrayList<>(), compensaciones = new ArrayList<>();
            for (Document d : c("PedidoProceso").find(s, eq("IdPedido", id)).sort(ascending("FechaInicio"))) {
                ("COMPENSACION".equals(d.getString("TipoProceso")) ? compensaciones : pasos).add(proceso(d));
            }
            Document g = c("Guia").find(s, eq("IdPedido", id)).first();
            return new VistaPedido(p, g == null ? null : new Guia(g.getString("_id"), g.getString("IdEstado")), pasos, compensaciones);
        });
    }
    public List<Pedido> pedidos(Actor a, int pagina) {
        return tx(s -> {
            Bson filtro = new Document();
            if (a.rol() == Rol.COMPRADOR) {
                Document cliente = c("Cliente").find(s, eq("IdUsuario", a.id())).first();
                if (cliente == null) return List.of();
                filtro = eq("IdCliente", cliente.getString("_id"));
            } else if (a.rol() == Rol.VENDEDOR) {
                // Join and filter before pagination; only matching order lines reach the application.
                List<Bson> pipeline = List.of(Aggregates.match(eq("IdUsuarioVendedor", a.id())), Aggregates.group("$IdPedido"), Aggregates.sort(ascending("_id")), Aggregates.skip(pagina * 50), Aggregates.limit(50));
                List<String> ids = c("PedidoDetalle").aggregate(s, pipeline).map(d -> d.getString("_id")).into(new ArrayList<>());
                if (ids.isEmpty()) return List.of();
                return c("Pedido").find(s, in("_id", ids)).sort(ascending("_id")).map(d -> pedido(s, d)).into(new ArrayList<>());
            }
            return c("Pedido").find(s, filtro).sort(ascending("_id")).skip(pagina * 50).limit(50).map(d -> pedido(s, d)).into(new ArrayList<>());
        });
    }
    public Pedido solicitarAnulacion(Actor a, String id) {
        return tx(s -> {
            Document d = requerido(c("Pedido").find(s, eq("_id", id)).first(), "Pedido no encontrado");
            Pedido p = pedido(s, d); propietario(a, p);
            if (p.estado() == Estado.DESPACHADO) throw new Fallo(409, "Pedido ya despachado");
            if (p.estado() == Estado.ANULADO || p.anulacionSolicitada()) return p;
            c("Pedido").updateOne(s, eq("_id", id), combine(set("AnulacionSolicitada", true), set("FechaSolicitudAnulacion", ahora()), mod(a.id())));
            return pedido(s, c("Pedido").find(s, eq("_id", id)).first());
        });
    }
    public Pedido operarStock(String id, OperacionStock op) {
        try {
            return tx(s -> {
                Document d = requerido(c("Pedido").find(s, eq("_id", id)).first(), "Pedido no encontrado");
                Pedido p = pedido(s, d);
                Reserva objetivo = switch (op) { case RESERVAR -> Reserva.RESERVADA; case LIBERAR -> Reserva.LIBERADA; case CONFIRMAR -> Reserva.CONFIRMADA; };
                if (p.reserva() == objetivo) return p;
                if (op == OperacionStock.RESERVAR) {
                    if (p.reserva() != Reserva.NINGUNA || p.anulacionSolicitada() || !(p.estado() == Estado.RECIBIDO || p.estado() == Estado.EN_PROCESO)) throw new Fallo(409, "Reserva incompatible con pedido");
                } else if (op == OperacionStock.LIBERAR && p.reserva() == Reserva.NINGUNA) {
                    return p; // Nothing was reserved; no stock mutation.
                } else if (p.reserva() != Reserva.RESERVADA || p.estado() == Estado.DESPACHADO || p.estado() == Estado.ANULADO) {
                    throw new Fallo(409, "No existe reserva compatible");
                }
                if (op == OperacionStock.CONFIRMAR && (p.anulacionSolicitada() || p.estado() != Estado.EN_PROCESO)) throw new Fallo(409, "Confirmación incompatible con pedido");
                Date inicio = ahora();
                for (Detalle item : p.items().stream().sorted(Comparator.comparing(Detalle::sku)).toList()) {
                    int q = item.cantidad();
                    Bson filtro = and(stockKey(item.sku(), p.almacenId()), gte(op == OperacionStock.RESERVAR ? "CantidadStock" : "ReservaStock", q));
                    Bson cantidades = switch (op) {
                        case RESERVAR -> combine(inc("CantidadStock", -q), inc("ReservaStock", q));
                        case LIBERAR -> combine(inc("CantidadStock", q), inc("ReservaStock", -q));
                        case CONFIRMAR -> inc("ReservaStock", -q);
                    };
                    Document actualizado = c("Stock").findOneAndUpdate(s, filtro, combine(cantidades, mod("SYSTEM:despachos")));
                    if (actualizado == null) throw new Fallo(409, op == OperacionStock.RESERVAR ? "STOCK_INSUFICIENTE" : "RESERVA_INCONSISTENTE");
                }
                Estado estado = p.estado();
                if (op == OperacionStock.RESERVAR) { transicion(estado, Estado.EN_PROCESO); estado = Estado.EN_PROCESO; }
                c("Pedido").updateOne(s, eq("_id", id), combine(set("EstadoReserva", objetivo.name()), set("IdEstado", estado.name()), mod("SYSTEM:despachos")));
                registrarProceso(s, id, op, "COMPLETADO", inicio, "Stock actualizado");
                return pedido(s, c("Pedido").find(s, eq("_id", id)).first());
            });
        } catch (Fallo e) {
            if ("STOCK_INSUFICIENTE".equals(e.getMessage())) {
                // Separate transaction: failure evidence must survive the stock rollback.
                tx(s -> { registrarProceso(s, id, op, "FALLIDO", ahora(), "STOCK_INSUFICIENTE: ninguna línea reservada"); return null; });
            }
            throw e;
        }
    }
    private void registrarProceso(ClientSession s, String id, OperacionStock op, String estado, Date inicio, String log) {
        int intento = Math.toIntExact(c("PedidoProceso").countDocuments(s, and(eq("IdPedido", id), eq("Paso", "STOCK_" + op)))) + 1;
        String procesoId = id("PRC-");
        c("PedidoProceso").insertOne(s, audit(new Document("_id", procesoId).append("IdPedidoProceso", procesoId).append("IdPedido", id).append("IdEstadoProceso", estado).append("Paso", "STOCK_" + op).append("TipoProceso", op == OperacionStock.LIBERAR ? "COMPENSACION" : "PROCESO").append("NroIntento", intento).append("FechaInicio", inicio).append("FechaFin", ahora()).append("Log", log), "SYSTEM:despachos"));
    }
    public long latenciaMongo() { long inicio = System.nanoTime(); db.runCommand(new Document("ping", 1)); return (System.nanoTime() - inicio) / 1000000; }
}
