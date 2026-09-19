package pe.reto.pedidos;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;
import static pe.reto.pedidos.domain.Model.*;
import org.junit.jupiter.api.*;
import pe.reto.pedidos.adapter.in.http.HttpApi;
import pe.reto.pedidos.adapter.out.security.RsaSeguridad;
import pe.reto.pedidos.application.port.out.Repositorio;
import pe.reto.pedidos.application.usecase.*;
import pe.reto.pedidos.config.*;
import java.net.*;
import java.net.http.*;
import java.time.Clock;
import java.util.*;

class HttpTest {
    HttpApi api;
    Repositorio repo;
    RsaSeguridad security;
    HttpClient client = HttpClient.newBuilder().connectTimeout(java.time.Duration.ofSeconds(5)).build();
    @BeforeEach void start() {
        repo = mock(Repositorio.class); var settings = SeguridadTest.config("a"); security = new RsaSeguridad(settings, Clock.systemUTC());
        api = new HttpApi(settings, HttpModule.json(), new PedidosService(repo), new CatalogoService(repo), new AuthService(repo, security, Clock.systemUTC(), 900, 3600), security, repo).start();
    }
    @AfterEach void stop() { api.stop(); }
    HttpResponse<String> send(String method, String path, String body, String token) throws Exception {
        var b = HttpRequest.newBuilder(URI.create("http://localhost:" + api.port() + path)).timeout(java.time.Duration.ofSeconds(10)).header("Content-Type", "application/json");
        if (token != null) b.header("Authorization", "Bearer " + token);
        return client.send(b.method(method, HttpRequest.BodyPublishers.ofString(body)).build(), HttpResponse.BodyHandlers.ofString());
    }
    String token(Rol rol) { return security.firmar(new Usuario("USR-1", "Prueba", rol, "hash")); }
    @Test void healthIndependienteYErroresEnSobre() throws Exception {
        var health = send("GET", "/health", "", null); assertEquals(200, health.statusCode()); verifyNoInteractions(repo);
        var missing = send("GET", "/pedidos", "", null); assertEquals(401, missing.statusCode()); assertTrue(HttpModule.json().readTree(missing.body()).get("data").isNull());
        assertEquals(401, send("GET", "/pedidos", "", "invalido").statusCode());
        var jwks = send("GET", "/.well-known/jwks.json", "", null); assertEquals(200, jwks.statusCode()); assertTrue(HttpModule.json().readTree(jwks.body()).at("/data/keys").isArray());
        assertEquals(401, send("POST", "/internal/pedidos/PED-1/stock/reservar", "", token(Rol.ADMIN)).statusCode());
    }
    @Test void jsonInyeccionYSuplantacionRechazados() throws Exception {
        assertEquals(400, send("POST", "/auth/login", "{\"usuario\":{\"$ne\":null},\"clave\":\"x\"}", null).statusCode());
        var r = send("POST", "/pedidos", "{\"clienteId\":\"otro\"}", token(Rol.COMPRADOR)); assertEquals(400, r.statusCode()); verifyNoInteractions(repo);
    }
    @Test void creacionYRepeticionTienenCodigosDiferentes() throws Exception {
        var p = ReglasTest.pedido("h"); when(repo.crearPedido(any(), any(), any(), any())).thenReturn(new Creacion(p, true), new Creacion(p, false));
        String body = "{\"solicitudId\":\"sol-1\",\"almacenId\":\"ALM-01\",\"zonaEntrega\":\"PROVINCIA\",\"items\":[{\"sku\":\"SKU-00001\",\"cantidad\":1}]}";
        assertEquals(202, send("POST", "/pedidos", body, token(Rol.COMPRADOR)).statusCode());
        assertEquals(200, send("POST", "/pedidos", body, token(Rol.COMPRADOR)).statusCode());
        assertEquals(403, send("POST", "/pedidos", body, token(Rol.VENDEDOR)).statusCode());
    }
    @Test void compradorAjenoRecibe404() throws Exception {
        when(repo.pedido("PED-1")).thenReturn(new VistaPedido(ReglasTest.pedido("h"), null, List.of(), List.of()));
        String ajeno = security.firmar(new Usuario("USR-2", "Otro", Rol.COMPRADOR, "hash"));
        assertEquals(404, send("GET", "/pedidos/PED-1", "", ajeno).statusCode());
    }
    @Test void headersDeIdentidadNoAutentican() throws Exception {
        var request = HttpRequest.newBuilder(URI.create("http://localhost:" + api.port() + "/pedidos"))
                .timeout(java.time.Duration.ofSeconds(10)).header("X-User-Id", "USR-1").header("X-Role", "ADMIN").GET().build();
        assertEquals(401, client.send(request, HttpResponse.BodyHandlers.ofString()).statusCode()); verifyNoInteractions(repo);
    }
    @Test void vendedorSoloRecibeLineasPropias() throws Exception {
        var d1 = new Detalle("SKU-00001", "USR-1", 1, java.math.BigDecimal.TEN, java.math.BigDecimal.ONE, java.math.BigDecimal.TEN);
        var d2 = new Detalle("SKU-00002", "USR-2", 1, java.math.BigDecimal.TEN, java.math.BigDecimal.ONE, java.math.BigDecimal.TEN);
        var p = new Pedido("PED-1", "sol-secreto", "CLI-1", "USR-C", "ALM-01", "PROVINCIA", "h", Estado.RECIBIDO, java.math.BigDecimal.valueOf(20), null, null, java.math.BigDecimal.TWO, "corr", false, Reserva.NINGUNA, List.of(d1, d2));
        when(repo.pedido("PED-1")).thenReturn(new VistaPedido(p, null, List.of(), List.of()));
        var r = send("GET", "/pedidos/PED-1", "", token(Rol.VENDEDOR)); assertEquals(200, r.statusCode());
        assertFalse(r.body().contains("SKU-00002")); assertFalse(r.body().contains("sol-secreto")); assertFalse(r.body().contains("USR-C"));
        assertEquals(1, HttpModule.json().readTree(r.body()).at("/data/items").size());
    }
}
