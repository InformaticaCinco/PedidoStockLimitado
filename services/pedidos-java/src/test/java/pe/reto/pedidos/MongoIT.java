package pe.reto.pedidos;

import static org.junit.jupiter.api.Assertions.*;
import static pe.reto.pedidos.domain.Model.*;
import static pe.reto.pedidos.domain.Reglas.*;
import static com.mongodb.client.model.Filters.*;
import static com.mongodb.client.model.Updates.*;
import com.mongodb.*;
import com.mongodb.client.*;
import org.bson.*;
import org.bson.types.Decimal128;
import org.junit.jupiter.api.*;
import pe.reto.pedidos.adapter.out.mongo.MongoRepositorio;
import pe.reto.pedidos.adapter.out.security.RsaSeguridad;
import pe.reto.pedidos.application.usecase.*;
import pe.reto.pedidos.domain.Fallo;
import org.mindrot.jbcrypt.BCrypt;
import java.math.BigDecimal;
import java.time.*;
import java.util.*;
import java.util.concurrent.*;

@TestInstance(TestInstance.Lifecycle.PER_CLASS)
class MongoIT {
    MongoReplica mongo;
    MongoDatabase db;
    MongoRepositorio repo;
    final Actor comprador = new Actor("USR-C", Rol.COMPRADOR), vendedor = new Actor("USR-V", Rol.VENDEDOR);
    @BeforeAll void connect() throws Exception { mongo = new MongoReplica(); }
    @AfterAll void disconnect() { if (mongo != null) mongo.close(); }
    @BeforeEach void fixture() {
        db = mongo.client.getDatabase("pedidos_it_" + UUID.randomUUID().toString().replace("-", ""));
        repo = new MongoRepositorio(mongo.client, db, Clock.systemUTC()); repo.crearIndices();
        insert("Rol", new Document("_id", "ROL-C").append("Nombre", "COMPRADOR"));
        insert("Usuario", new Document("_id", "USR-C").append("Usuario", "comprador").append("Nombre", "Prueba").append("IdRol", "ROL-C").append("ClaveHash", BCrypt.hashpw("clave-prueba", BCrypt.gensalt(4))));
        insert("Cliente", new Document("_id", "CLI-1").append("IdUsuario", "USR-C"));
        insert("Cliente", new Document("_id", "CLI-2").append("IdUsuario", "USR-D"));
        insert("Almacen", new Document("_id", "ALM-01"));
        insert("UsuarioAlmacen", new Document("_id", "UA-1").append("IdUsuario", "USR-V").append("IdAlmacen", "ALM-01"));
        for (String sku : List.of("SKU-00001", "SKU-00002")) {
            repo.guardarProducto(vendedor, new DatosProducto(sku, "Producto de prueba", new BigDecimal("10.005"), new BigDecimal("1.25")), true);
            repo.actualizarStock(vendedor, sku, "ALM-01", 5);
        }
    }
    @AfterEach void cleanup() { if (db != null) db.drop(); }
    void insert(String c, Document d) { db.getCollection(c).insertOne(d.append("UsuarioCreacion", "TEST").append("FechaCreacion", new Date()).append("UsuarioModificacion", null).append("FechaModificacion", null)); }
    NuevoPedido input(String id, Item... items) { return new NuevoPedido(id, "ALM-01", "PROVINCIA", List.of(items)); }
    Pedido crear(String id, Item... items) { var p = input(id, items); return repo.crearPedido(comprador, p, huella(p, comprador.id()), "corr").pedido(); }
    @Test void catalogoHttpResuelveAlmacenesDesdeUsuarioAlmacen() throws Exception {
        insert("Almacen", new Document("_id", "ALM-02"));
        insert("UsuarioAlmacen", new Document("_id", "UA-2").append("IdUsuario", "USR-V2").append("IdAlmacen", "ALM-02"));
        repo.guardarProducto(new Actor("USR-V2", Rol.VENDEDOR), new DatosProducto("SKU-00003", "Otro almacén", BigDecimal.TEN, BigDecimal.ONE), true);
        var settings = SeguridadTest.config("a");
        var security = new RsaSeguridad(settings, Clock.systemUTC());
        var api = new pe.reto.pedidos.adapter.in.http.HttpApi(settings, pe.reto.pedidos.config.HttpModule.json(),
                new PedidosService(repo), new CatalogoService(repo), new AuthService(repo, security, Clock.systemUTC(), 900, 3600), security, repo).start();
        try (var http = java.net.http.HttpClient.newHttpClient()) {
            String token = security.firmar(new Usuario(comprador.id(), "Comprador", Rol.COMPRADOR, "unused"));
            var request = java.net.http.HttpRequest.newBuilder(java.net.URI.create("http://localhost:" + api.port() + "/productos"))
                    .header("Authorization", "Bearer " + token).GET().build();
            var response = http.send(request, java.net.http.HttpResponse.BodyHandlers.ofString());
            assertEquals(200, response.statusCode());
            var data = pe.reto.pedidos.config.HttpModule.json().readTree(response.body()).get("data");
            assertEquals(3, data.size());
            assertEquals("ALM-01", data.get(0).get("almacenId").asText());
            assertEquals("ALM-01", data.get(1).get("almacenId").asText());
            assertEquals("ALM-02", data.get(2).get("almacenId").asText());
            assertEquals(vendedor.id(), data.get(0).get("vendedorId").asText());
            assertEquals(0, db.getCollection("Producto").countDocuments(exists("IdAlmacen")));
            db.getCollection("UsuarioAlmacen").updateOne(eq("IdUsuario", "USR-V2"), set("IdAlmacen", "ALM-03"));
            assertEquals("ALM-03", repo.productos(0).get(2).almacenId());
            db.getCollection("UsuarioAlmacen").deleteOne(eq("IdUsuario", "USR-V2"));
            assertNull(repo.productos(0).get(2).almacenId());
        } finally { api.stop(); }
    }
    @Test void productoPostPutVendedor01DevuelveAlmacenSinPersistirlo() throws Exception {
        insert("Rol", new Document("_id", "ROL-V").append("Nombre", "VENDEDOR"));
        insert("Usuario", new Document("_id", vendedor.id()).append("Usuario", "vendedor01").append("Nombre", "Vendedor 01")
                .append("IdRol", "ROL-V").append("ClaveHash", BCrypt.hashpw("clave-prueba", BCrypt.gensalt(4))));
        var settings = SeguridadTest.config("a");
        var security = new RsaSeguridad(settings, Clock.systemUTC());
        var auth = new AuthService(repo, security, Clock.systemUTC(), 900, 3600);
        String token = auth.login("vendedor01", "clave-prueba").accessToken();
        var api = new pe.reto.pedidos.adapter.in.http.HttpApi(settings, pe.reto.pedidos.config.HttpModule.json(),
                new PedidosService(repo), new CatalogoService(repo), auth, security, repo).start();
        try (var http = java.net.http.HttpClient.newHttpClient()) {
            for (String method : List.of("POST", "PUT")) {
                String body = method.equals("POST") ? "{\"sku\":\"SKU-00042\",\"nombre\":\"Nuevo\",\"precio\":12,\"peso\":1}" : "{\"nombre\":\"Editado\",\"precio\":15,\"peso\":2}";
                String path = "/productos" + (method.equals("PUT") ? "/SKU-00042" : "");
                var request = java.net.http.HttpRequest.newBuilder(java.net.URI.create("http://localhost:" + api.port() + path))
                        .header("Authorization", "Bearer " + token).header("Content-Type", "application/json")
                        .method(method, java.net.http.HttpRequest.BodyPublishers.ofString(body)).build();
                var response = http.send(request, java.net.http.HttpResponse.BodyHandlers.ofString());
                assertEquals(method.equals("POST") ? 201 : 200, response.statusCode());
                var data = pe.reto.pedidos.config.HttpModule.json().readTree(response.body()).get("data");
                assertEquals("ALM-01", data.get("almacenId").asText());
                assertEquals(vendedor.id(), data.get("vendedorId").asText());
                assertEquals("SKU-00042", data.get("sku").asText());
            }
            assertEquals(0, db.getCollection("Producto").countDocuments(exists("IdAlmacen")));
        } finally { api.stop(); }
    }
    @Test void indiceUnicoIdempotenciaYMontosDecimal128() {
        var p = input("sol-1", new Item("SKU-00001", 2)); String h = huella(p, comprador.id());
        var first = repo.crearPedido(comprador, p, h, "corr"); assertTrue(first.nuevo());
        var retry = repo.crearPedido(comprador, p, h, "corr"); assertFalse(retry.nuevo()); assertEquals(first.pedido().pedidoId(), retry.pedido().pedidoId());
        assertEquals(409, assertThrows(Fallo.class, () -> repo.crearPedido(comprador, p, "diferente", "corr")).codigo());
        var d = db.getCollection("Pedido").find().first(); assertNotNull(d); assertInstanceOf(Decimal128.class, d.get("Subtotal")); assertInstanceOf(Date.class, d.get("FechaCreacion")); assertNull(d.get("FechaModificacion"));
        assertEquals(new BigDecimal("20.02"), first.pedido().subtotal()); assertNull(first.pedido().envio()); assertNull(first.pedido().total());
        assertThrows(MongoWriteException.class, () -> db.getCollection("Pedido").insertOne(new Document("_id", "otro").append("IdSolicitud", "sol-1")));
        assertEquals(1, db.getCollection("PedidoDetalle").countDocuments()); assertEquals(5, repo.stock("SKU-00001", "ALM-01").disponible());
    }
    @Test void reservaCompletaYRepeticionLiberacion() {
        Pedido p = crear("sol-1", new Item("SKU-00001", 2), new Item("SKU-00002", 3));
        repo.operarStock(p.pedidoId(), OperacionStock.RESERVAR); repo.operarStock(p.pedidoId(), OperacionStock.RESERVAR);
        assertEquals(new Stock("SKU-00001", "ALM-01", 3, 2), repo.stock("SKU-00001", "ALM-01"));
        assertEquals(new Stock("SKU-00002", "ALM-01", 2, 3), repo.stock("SKU-00002", "ALM-01"));
        assertEquals(1, repo.pedido(p.pedidoId()).pasos().size());
        repo.operarStock(p.pedidoId(), OperacionStock.LIBERAR); repo.operarStock(p.pedidoId(), OperacionStock.LIBERAR);
        assertEquals(new Stock("SKU-00001", "ALM-01", 5, 0), repo.stock("SKU-00001", "ALM-01"));
        assertEquals(1, repo.pedido(p.pedidoId()).compensaciones().size());
        assertThrows(Fallo.class, () -> repo.operarStock(p.pedidoId(), OperacionStock.CONFIRMAR));
    }
    @Test void rollbackSiSegundaLineaFalla() {
        Pedido p = crear("sol-1", new Item("SKU-00001", 2), new Item("SKU-00002", 6));
        assertEquals("STOCK_INSUFICIENTE", assertThrows(Fallo.class, () -> repo.operarStock(p.pedidoId(), OperacionStock.RESERVAR)).getMessage());
        assertEquals(new Stock("SKU-00001", "ALM-01", 5, 0), repo.stock("SKU-00001", "ALM-01"));
        assertEquals(new Stock("SKU-00002", "ALM-01", 5, 0), repo.stock("SKU-00002", "ALM-01"));
        var vista = repo.pedido(p.pedidoId()); assertEquals(Reserva.NINGUNA, vista.pedido().reserva()); assertEquals("FALLIDO", vista.pasos().getFirst().estado());
        var proceso = db.getCollection("PedidoProceso").find().first(); assertFalse(proceso.containsKey("ms")); assertInstanceOf(Date.class, proceso.get("FechaInicio"));
    }
    @Test void confirmarNoDescuentaDosVeces() {
        Pedido p = crear("sol-1", new Item("SKU-00001", 2)); repo.operarStock(p.pedidoId(), OperacionStock.RESERVAR);
        repo.operarStock(p.pedidoId(), OperacionStock.CONFIRMAR); repo.operarStock(p.pedidoId(), OperacionStock.CONFIRMAR);
        assertEquals(new Stock("SKU-00001", "ALM-01", 3, 0), repo.stock("SKU-00001", "ALM-01"));
        assertThrows(Fallo.class, () -> repo.operarStock(p.pedidoId(), OperacionStock.LIBERAR));
    }
    <T> List<T> concurrente(int n, java.util.function.IntFunction<T> action) throws Exception {
        CyclicBarrier barrier = new CyclicBarrier(n);
        try (var executor = Executors.newVirtualThreadPerTaskExecutor()) {
            List<Future<T>> futures = new ArrayList<>();
            for (int i = 0; i < n; i++) { final int index = i; futures.add(executor.submit(() -> { barrier.await(20, TimeUnit.SECONDS); return action.apply(index); })); }
            List<T> resultados = new ArrayList<>(); for (var f : futures) resultados.add(f.get(60, TimeUnit.SECONDS)); return resultados;
        }
    }
    @Test void concurrenciaUltimasUnidades() throws Exception {
        var pedidos = new ArrayList<Pedido>(); for (int i = 0; i < 8; i++) pedidos.add(crear("sol-" + i, new Item("SKU-00001", 1)));
        var results = concurrente(8, i -> { try { repo.operarStock(pedidos.get(i).pedidoId(), OperacionStock.RESERVAR); return true; } catch (Fallo e) { assertEquals("STOCK_INSUFICIENTE", e.getMessage()); return false; } });
        assertEquals(5, results.stream().filter(Boolean::booleanValue).count()); assertEquals(new Stock("SKU-00001", "ALM-01", 0, 5), repo.stock("SKU-00001", "ALM-01"));
    }
    @Test void concurrenciaMismaSolicitud() throws Exception {
        var p = input("sol-1", new Item("SKU-00001", 1)); var results = concurrente(6, i -> repo.crearPedido(comprador, p, huella(p, comprador.id()), "corr"));
        assertEquals(1, results.stream().filter(Creacion::nuevo).count()); assertEquals(1, results.stream().map(r -> r.pedido().pedidoId()).distinct().count());
        assertEquals(1, db.getCollection("Pedido").countDocuments()); assertEquals(1, db.getCollection("PedidoDetalle").countDocuments());
    }
    @Test void concurrenciaMismaReservaYCancelacion() throws Exception {
        Pedido p = crear("sol-1", new Item("SKU-00001", 2)); concurrente(6, i -> repo.operarStock(p.pedidoId(), OperacionStock.RESERVAR));
        assertEquals(2, repo.stock("SKU-00001", "ALM-01").reservado()); assertEquals(1, repo.pedido(p.pedidoId()).pasos().size());
        assertTrue(repo.solicitarAnulacion(comprador, p.pedidoId()).anulacionSolicitada());
        assertTrue(repo.solicitarAnulacion(comprador, p.pedidoId()).anulacionSolicitada());
        assertThrows(Fallo.class, () -> repo.operarStock(p.pedidoId(), OperacionStock.CONFIRMAR));
        concurrente(6, i -> repo.operarStock(p.pedidoId(), OperacionStock.LIBERAR)); assertEquals(5, repo.stock("SKU-00001", "ALM-01").disponible());
    }
    @Test void confirmacionesConcurrentesNoDuplicanDescuento() throws Exception {
        Pedido p = crear("sol-1", new Item("SKU-00001", 2)); repo.operarStock(p.pedidoId(), OperacionStock.RESERVAR);
        concurrente(6, i -> repo.operarStock(p.pedidoId(), OperacionStock.CONFIRMAR));
        assertEquals(new Stock("SKU-00001", "ALM-01", 3, 0), repo.stock("SKU-00001", "ALM-01"));
        assertEquals(1, db.getCollection("PedidoProceso").countDocuments(and(eq("IdPedido", p.pedidoId()), eq("Paso", "STOCK_CONFIRMAR"))));
    }
    @Test void grafoDaggerYContratoHttpConPersistenciaReal() throws Exception {
        var base = SeguridadTest.config("a");
        var settings = new pe.reto.pedidos.config.Settings(0, mongo.uri, db.getName(), base.issuer(), base.audience(), 900, 3600, base.privateKey(), base.publicKey(), base.internalKey());
        var component = pe.reto.pedidos.config.DaggerAppComponent.factory().create(settings);
        var api = component.http().start();
        try (var http = java.net.http.HttpClient.newHttpClient()) {
            java.net.URI loginUri = java.net.URI.create("http://localhost:" + api.port() + "/auth/login");
            var loginRequest = java.net.http.HttpRequest.newBuilder(loginUri).timeout(Duration.ofSeconds(10)).header("Content-Type", "application/json")
                    .POST(java.net.http.HttpRequest.BodyPublishers.ofString("{\"usuario\":\"comprador\",\"clave\":\"clave-prueba\"}")).build();
            var login = http.send(loginRequest, java.net.http.HttpResponse.BodyHandlers.ofString()); assertEquals(200, login.statusCode());
            String token = pe.reto.pedidos.config.HttpModule.json().readTree(login.body()).at("/data/accessToken").asText();
            var create = java.net.http.HttpRequest.newBuilder(java.net.URI.create("http://localhost:" + api.port() + "/pedidos"))
                    .timeout(Duration.ofSeconds(10)).header("Content-Type", "application/json").header("Authorization", "Bearer " + token)
                    .POST(java.net.http.HttpRequest.BodyPublishers.ofString("{\"solicitudId\":\"sol-http\",\"almacenId\":\"ALM-01\",\"zonaEntrega\":\"PROVINCIA\",\"items\":[{\"sku\":\"SKU-00001\",\"cantidad\":2}]}")).build();
            var created = http.send(create, java.net.http.HttpResponse.BodyHandlers.ofString()); assertEquals(202, created.statusCode());
            String id = pe.reto.pedidos.config.HttpModule.json().readTree(created.body()).at("/data/pedidoId").asText();
            assertEquals(200, http.send(create, java.net.http.HttpResponse.BodyHandlers.ofString()).statusCode());
            var reserve = java.net.http.HttpRequest.newBuilder(java.net.URI.create("http://localhost:" + api.port() + "/internal/pedidos/" + id + "/stock/reservar"))
                    .timeout(Duration.ofSeconds(10)).header("X-Internal-Key", base.internalKey()).POST(java.net.http.HttpRequest.BodyPublishers.noBody()).build();
            assertEquals(200, http.send(reserve, java.net.http.HttpResponse.BodyHandlers.ofString()).statusCode());
            var cancel = java.net.http.HttpRequest.newBuilder(java.net.URI.create("http://localhost:" + api.port() + "/pedidos/" + id + "/anulacion"))
                    .timeout(Duration.ofSeconds(10)).header("Authorization", "Bearer " + token).POST(java.net.http.HttpRequest.BodyPublishers.noBody()).build();
            assertEquals(202, http.send(cancel, java.net.http.HttpResponse.BodyHandlers.ofString()).statusCode());
            assertEquals(202, http.send(cancel, java.net.http.HttpResponse.BodyHandlers.ofString()).statusCode());
            var doc = db.getCollection("Pedido").find(eq("_id", id)).first(); assertEquals("USR-C", doc.getString("UsuarioCreacion")); assertEquals("USR-C", doc.getString("UsuarioModificacion"));
            assertEquals(created.headers().firstValue("X-Correlation-Id").orElseThrow(), doc.getString("CorrelationId"));
            db.getCollection("Pedido").updateOne(eq("_id", id), set("IdEstado", "DESPACHADO"));
            assertEquals(409, http.send(cancel, java.net.http.HttpResponse.BodyHandlers.ofString()).statusCode());
            db.getCollection("Pedido").updateOne(eq("_id", id), set("IdEstado", "ANULADO"));
            assertEquals(200, http.send(cancel, java.net.http.HttpResponse.BodyHandlers.ofString()).statusCode());
        } finally { api.stop(); component.mongoClient().close(); }
    }
    @Test void pertenenciaYStockPropio() {
        Pedido p = crear("sol-1", new Item("SKU-00001", 1));
        assertEquals(404, assertThrows(Fallo.class, () -> repo.solicitarAnulacion(new Actor("USR-D", Rol.COMPRADOR), p.pedidoId())).codigo());
        assertEquals(403, assertThrows(Fallo.class, () -> repo.actualizarStock(new Actor("OTRO", Rol.VENDEDOR), "SKU-00001", "ALM-01", 100)).codigo());
        assertEquals(403, assertThrows(Fallo.class, () -> repo.actualizarStock(vendedor, "SKU-00001", "ALM-02", 100)).codigo());
        assertTrue(repo.pedidos(new Actor("USR-D", Rol.COMPRADOR), 0).isEmpty());
        assertEquals(1, repo.pedidos(vendedor, 0).size());
        db.getCollection("Pedido").updateOne(eq("_id", p.pedidoId()), set("IdEstado", "DESPACHADO"));
        assertEquals(409, assertThrows(Fallo.class, () -> repo.solicitarAnulacion(comprador, p.pedidoId())).codigo());
        db.getCollection("Pedido").updateOne(eq("_id", p.pedidoId()), set("IdEstado", "ANULADO"));
        assertEquals(Estado.ANULADO, repo.solicitarAnulacion(comprador, p.pedidoId()).estado());
    }
    @Test void refreshRotacionConcurrenteLogoutPersistente() throws Exception {
        var security = new RsaSeguridad(SeguridadTest.config("a"), Clock.systemUTC()); var auth = new AuthService(repo, security, Clock.systemUTC(), 900, 3600);
        var login = auth.login("comprador", "clave-prueba");
        var results = concurrente(4, i -> { try { return auth.refresh(login.refreshToken()); } catch (Fallo e) { assertEquals(401, e.codigo()); return null; } });
        assertEquals(1, results.stream().filter(Objects::nonNull).count());
        var next = results.stream().filter(Objects::nonNull).findFirst().orElseThrow(); auth.logout(next.refreshToken());
        assertThrows(Fallo.class, () -> auth.refresh(next.refreshToken()));
        assertFalse(db.getCollection("RefreshToken").find().first().toJson().contains(login.refreshToken()));
    }
}
