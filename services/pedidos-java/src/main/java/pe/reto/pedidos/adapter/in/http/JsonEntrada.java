package pe.reto.pedidos.adapter.in.http;

import com.fasterxml.jackson.core.*;
import com.fasterxml.jackson.databind.*;
import static pe.reto.pedidos.domain.Reglas.*;
import pe.reto.pedidos.domain.Fallo;
import pe.reto.pedidos.domain.Model.*;
import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.util.*;

/** Explicit JSON node checks: no string/number coercion and no Mongo operators. */
public final class JsonEntrada {
    private final ObjectMapper json;
    public JsonEntrada(ObjectMapper json) { this.json = json; }
    public JsonNode objeto(String body, String... campos) {
        try {
            JsonNode n = json.readTree(body);
            exigir(n != null && n.isObject(), "body", "Objeto JSON requerido"); campos(n, campos); return n;
        } catch (JsonProcessingException e) { throw new Fallo(400, "JSON inválido"); }
    }
    public void campos(JsonNode n, String... campos) {
        Set<String> permitidos = Set.of(campos);
        n.fieldNames().forEachRemaining(c -> exigir(permitidos.contains(c), c, "Campo no permitido"));
    }
    public String texto(JsonNode n, String c, int max) {
        JsonNode v = n.get(c);
        exigir(v != null && v.isTextual() && !v.textValue().isBlank() && v.textValue().length() <= max, c, "Texto obligatorio hasta " + max + " caracteres");
        return v.textValue();
    }
    public int entero(JsonNode n, String c) {
        JsonNode v = n.get(c); exigir(v != null && v.isIntegralNumber() && v.canConvertToInt(), c, "Entero requerido"); return v.intValue();
    }
    public BigDecimal decimal(JsonNode n, String c) {
        JsonNode v = n.get(c); exigir(v != null && v.isNumber(), c, "Número requerido"); return v.decimalValue();
    }
    public NuevoPedido pedido(String body) {
        JsonNode n = objeto(body, "solicitudId", "almacenId", "zonaEntrega", "items");
        JsonNode items = n.get("items"); exigir(items != null && items.isArray() && items.size() >= 1 && items.size() <= 20, "items", "Entre 1 y 20 líneas");
        List<Item> lineas = new ArrayList<>();
        for (JsonNode item : items) { exigir(item.isObject(), "items", "Objeto requerido"); campos(item, "sku", "cantidad"); lineas.add(new Item(texto(item, "sku", 9), entero(item, "cantidad"))); }
        NuevoPedido p = new NuevoPedido(texto(n, "solicitudId", 60), texto(n, "almacenId", 6), texto(n, "zonaEntrega", 30), List.copyOf(lineas)); validar(p); return p;
    }
    public DatosProducto producto(String body, String sku) {
        JsonNode n = sku == null ? objeto(body, "sku", "nombre", "precio", "peso") : objeto(body, "nombre", "precio", "peso");
        DatosProducto p = new DatosProducto(sku == null ? texto(n, "sku", 9) : sku, texto(n, "nombre", 120), decimal(n, "precio"), decimal(n, "peso"));
        pe.reto.pedidos.domain.Reglas.producto(p); return p;
    }
    public String clave(JsonNode n) { String c = texto(n, "clave", 72); exigir(c.getBytes(StandardCharsets.UTF_8).length <= 72, "clave", "Máximo 72 bytes BCrypt"); return c; }
    public String refresh(String body) { String t = texto(objeto(body, "refreshToken"), "refreshToken", 128); exigir(t.matches("[A-Za-z0-9_-]{43}"), "refreshToken", "Formato inválido"); return t; }
}
