package pe.reto.pedidos.adapter.in.http;

import io.javalin.Javalin;
import io.javalin.http.*;
import io.javalin.json.JavalinJackson;
import com.fasterxml.jackson.databind.ObjectMapper;
import pe.reto.pedidos.application.port.in.Pedidos;
import pe.reto.pedidos.application.port.out.*;
import pe.reto.pedidos.application.usecase.*;
import pe.reto.pedidos.config.Settings;
import pe.reto.pedidos.domain.*;
import static pe.reto.pedidos.domain.Model.*;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.*;
import org.slf4j.*;

public final class HttpApi {
    private static final Logger LOG = LoggerFactory.getLogger(HttpApi.class);
    private final Javalin app;
    private final JsonEntrada entrada;
    private final Seguridad seguridad;
    private final Settings config;
    public HttpApi(Settings config, ObjectMapper json, Pedidos pedidos, CatalogoService catalogo, AuthService auth, Seguridad seguridad, Repositorio repo) {
        this.config = config; this.seguridad = seguridad; entrada = new JsonEntrada(json);
        app = Javalin.create(c -> { c.jsonMapper(new JavalinJackson(json, false)); c.http.maxRequestSize = 65536; c.showJavalinBanner = false; });
        app.before(ctx -> {
            // Generate server-controlled correlation IDs; do not log client-supplied PII.
            String correlation = UUID.randomUUID().toString();
            ctx.attribute("correlationId", correlation); ctx.header("X-Correlation-Id", correlation);
            ctx.header("Cache-Control", "no-store"); ctx.header("X-Content-Type-Options", "nosniff");
            String path = ctx.path();
            if (path.startsWith("/internal/")) interno(ctx);
            else if (!(path.equals("/health") || path.equals("/health/dependencias") || path.startsWith("/auth/") || path.equals("/.well-known/jwks.json"))) actor(ctx);
        });
        app.after(ctx -> LOG.atInfo().addKeyValue("correlationId", ctx.<String>attribute("correlationId")).addKeyValue("status", ctx.statusCode()).log("http_request"));
        app.exception(Fallo.class, (e, ctx) -> error(ctx, e.codigo(), e.getMessage(), e.errores()));
        app.exception(HttpResponseException.class, (e, ctx) -> error(ctx, e.getStatus(), "Solicitud HTTP rechazada", Map.of()));
        app.exception(Exception.class, (e, ctx) -> {
            LOG.atError().addKeyValue("correlationId", ctx.<String>attribute("correlationId")).addKeyValue("tipo", e.getClass().getSimpleName()).log("request_failed");
            error(ctx, 500, "Error interno", Map.of());
        });
        for (int code : List.of(404, 405, 413, 415, 500)) app.error(code, ctx -> { if (ctx.contentType() == null || !ctx.contentType().startsWith("application/json")) error(ctx, code, "Solicitud HTTP rechazada", Map.of()); });
        app.get("/health", ctx -> ok(ctx, 200, Map.of("estado", "UP")));
        app.get("/health/dependencias", ctx -> {
            long inicio = System.nanoTime();
            try { ok(ctx, 200, Map.of("dependencias", List.of(Map.of("nombre", "MongoDB", "estado", "UP", "latenciaMs", repo.latenciaMongo())))); }
            catch (RuntimeException e) { ctx.status(503).json(Respuesta.crear(503, "MongoDB no disponible; latenciaMs=" + ((System.nanoTime() - inicio) / 1000000), null, Map.of("MongoDB", "DOWN", "latenciaMs", Long.toString((System.nanoTime() - inicio) / 1000000), "dependencias", "MongoDB"))); }
        });
        app.post("/auth/login", ctx -> { var n = entrada.objeto(ctx.body(), "usuario", "clave"); ok(ctx, 200, auth.login(entrada.texto(n, "usuario", 100), entrada.clave(n))); });
        app.post("/auth/refresh", ctx -> ok(ctx, 200, auth.refresh(entrada.refresh(ctx.body()))));
        app.post("/auth/logout", ctx -> { auth.logout(entrada.refresh(ctx.body())); ok(ctx, 200, Map.of("revocado", true)); });
        // Envelope is mandatory in this challenge: consumers must unwrap data before JWKSet.parse.
        app.get("/.well-known/jwks.json", ctx -> ok(ctx, 200, seguridad.jwks()));
        app.get("/productos", ctx -> ok(ctx, 200, catalogo.listar(actor(ctx), pagina(ctx))));
        app.post("/productos", ctx -> ok(ctx, 201, catalogo.guardar(actor(ctx), entrada.producto(ctx.body(), null), true)));
        app.put("/productos/{sku}", ctx -> ok(ctx, 200, catalogo.guardar(actor(ctx), entrada.producto(ctx.body(), ctx.pathParam("sku")), false)));
        app.get("/productos/{sku}/stock", ctx -> { var s = catalogo.consultar(actor(ctx), ctx.pathParam("sku"), ctx.queryParam("almacenId")); ok(ctx, 200, stock(s)); });
        app.put("/productos/{sku}/stock", ctx -> { var n = entrada.objeto(ctx.body(), "disponible"); ok(ctx, 200, stock(catalogo.actualizar(actor(ctx), ctx.pathParam("sku"), ctx.queryParam("almacenId"), entrada.entero(n, "disponible")))); });
        app.post("/pedidos", ctx -> { var r = pedidos.crear(actor(ctx), entrada.pedido(ctx.body()), ctx.attribute("correlationId")); ok(ctx, r.nuevo() ? 202 : 200, resumen(r.pedido())); });
        app.get("/pedidos", ctx -> ok(ctx, 200, pedidos.listar(actor(ctx), pagina(ctx)).stream().map(HttpApi::pedido).toList()));
        app.get("/pedidos/{pedidoId}", ctx -> {
            VistaPedido v = pedidos.consultar(actor(ctx), pedidoId(ctx));
            Map<String, Object> data = pedido(v.pedido()); data.put("guia", v.guia()); data.put("pasos", v.pasos().stream().map(HttpApi::proceso).toList()); data.put("compensaciones", v.compensaciones().stream().map(HttpApi::proceso).toList()); ok(ctx, 200, data);
        });
        app.post("/pedidos/{pedidoId}/anulacion", ctx -> { vacio(ctx); Pedido p = pedidos.anular(actor(ctx), pedidoId(ctx)); ok(ctx, p.estado() == Estado.ANULADO ? 200 : 202, resumen(p)); });
        app.post("/internal/pedidos/{pedidoId}/stock/reservar", ctx -> { vacio(ctx); ok(ctx, 200, resumen(pedidos.operarStock(pedidoId(ctx), OperacionStock.RESERVAR))); });
        app.post("/internal/pedidos/{pedidoId}/stock/liberar", ctx -> { vacio(ctx); ok(ctx, 200, resumen(pedidos.operarStock(pedidoId(ctx), OperacionStock.LIBERAR))); });
        app.post("/internal/pedidos/{pedidoId}/stock/confirmar", ctx -> { vacio(ctx); ok(ctx, 200, resumen(pedidos.operarStock(pedidoId(ctx), OperacionStock.CONFIRMAR))); });
    }
    private void vacio(Context ctx) { Reglas.exigir(ctx.body().isBlank() || ctx.body().trim().equals("{}"), "body", "No admite body funcional"); }
    private String pedidoId(Context ctx) { String id = ctx.pathParam("pedidoId"); Reglas.exigir(id.matches("PED-[A-Za-z0-9-]{1,60}"), "pedidoId", "Identificador inválido"); return id; }
    private int pagina(Context ctx) { String p = ctx.queryParam("pagina"); if (p == null) return 0; Reglas.exigir(p.matches("[0-9]{1,5}"), "pagina", "Entero entre 0 y 99999"); return Integer.parseInt(p); }
    private Actor actor(Context ctx) {
        Actor a = ctx.attribute("actor"); if (a != null) return a;
        String h = ctx.header("Authorization");
        if (h == null || !h.startsWith("Bearer ") || h.length() > 8192) throw new Fallo(401, "Autenticación requerida");
        a = seguridad.validar(h.substring(7)); ctx.attribute("actor", a); return a;
    }
    private void interno(Context ctx) {
        String key = ctx.header("X-Internal-Key");
        if (config.internalKey().isEmpty() || key == null || !MessageDigest.isEqual(config.internalKey().getBytes(StandardCharsets.UTF_8), key.getBytes(StandardCharsets.UTF_8))) throw new Fallo(401, "Autenticación interna requerida");
    }
    private static Map<String, Object> stock(Stock s) { return Map.of("sku", s.sku(), "almacenId", s.almacenId(), "total", s.total(), "reservado", s.reservado(), "disponible", s.disponible()); }
    private static Map<String, Object> resumen(Pedido p) { return Map.of("pedidoId", p.pedidoId(), "estado", p.estado(), "solicitudId", p.solicitudId(), "estadoReserva", p.reserva(), "anulacionSolicitada", p.anulacionSolicitada()); }
    private static Map<String, Object> pedido(Pedido p) {
        Map<String, Object> m = new LinkedHashMap<>(); m.put("pedidoId", p.pedidoId()); m.put("estado", p.estado()); m.put("almacenId", p.almacenId());
        m.put("items", p.items()); m.put("subtotal", p.subtotal()); m.put("envio", p.envio()); m.put("total", p.total()); m.put("pesoTotal", p.pesoTotal()); m.put("anulacionSolicitada", p.anulacionSolicitada());
        if (p.usuarioId() != null) { m.put("solicitudId", p.solicitudId()); m.put("zonaEntrega", p.zonaEntrega()); m.put("correlationId", p.correlationId()); }
        return m;
    }
    private static Map<String, Object> proceso(Proceso p) { Map<String, Object> m = new LinkedHashMap<>(); m.put("paso", p.paso()); m.put("estado", p.estado()); m.put("intentos", p.intentos()); m.put("ms", p.ms()); return m; }
    private void ok(Context ctx, int code, Object data) { ctx.status(code).json(Respuesta.crear(code, code == 202 ? "Aceptado" : "OK", data, Map.of())); }
    private void error(Context ctx, int code, String message, Map<String, String> errores) { ctx.status(code).json(Respuesta.crear(code, message, null, errores)); }
    public HttpApi start() { app.start(config.port()); return this; }
    public int port() { return app.port(); }
    public void stop() { app.stop(); }
}
