package pe.reto.pedidos.domain;

import static pe.reto.pedidos.domain.Model.*;
import java.math.*;
import java.nio.charset.StandardCharsets;
import java.security.*;
import java.util.*;

public final class Reglas {
    private Reglas() {}
    public static void exigir(boolean condicion, String campo, String mensaje) {
        if (!condicion) throw new Fallo(400, "Entrada inválida", Map.of(campo, mensaje));
    }
    public static void sku(String valor) { exigir(valor != null && valor.matches("SKU-[0-9]{5}"), "sku", "Formato SKU-00000 requerido"); }
    public static void almacen(String valor) { exigir(valor != null && valor.matches("ALM-[0-9]{2}"), "almacenId", "Formato ALM-00 requerido"); }
    public static void validar(NuevoPedido p) {
        exigir(p != null, "pedido", "Obligatorio");
        exigir(p.solicitudId() != null && p.solicitudId().matches("[A-Za-z0-9-]{1,60}"), "solicitudId", "De 1 a 60 alfanuméricos o guiones");
        almacen(p.almacenId());
        exigir(p.zonaEntrega() != null && Set.of("LIMA_METROPOLITANA", "LIMA_PROVINCIA", "PROVINCIA").contains(p.zonaEntrega()), "zonaEntrega", "Zona inválida");
        exigir(p.items() != null && !p.items().isEmpty() && p.items().size() <= 20, "items", "Entre 1 y 20 líneas");
        Set<String> unicos = new HashSet<>();
        for (Item i : p.items()) {
            exigir(i != null, "items", "Línea inválida"); sku(i.sku());
            exigir(i.cantidad() >= 1 && i.cantidad() <= 50, "cantidad", "Entero entre 1 y 50");
            exigir(unicos.add(i.sku()), "items", "SKU repetido");
        }
    }
    public static BigDecimal dinero(BigDecimal valor) { return valor.setScale(2, RoundingMode.HALF_UP); }
    public static void producto(DatosProducto p) {
        exigir(p != null, "producto", "Obligatorio"); sku(p.sku());
        exigir(p.nombre() != null && !p.nombre().isBlank() && p.nombre().length() <= 120, "nombre", "Entre 1 y 120 caracteres");
        exigir(p.precio() != null && p.precio().signum() > 0 && p.precio().compareTo(new BigDecimal("999999999.99")) <= 0 && dinero(p.precio()).signum() > 0, "precio", "Precio positivo hasta 999999999.99");
        exigir(p.peso() != null && p.peso().signum() > 0 && p.peso().compareTo(new BigDecimal("100000")) <= 0 && p.peso().scale() <= 6, "peso", "Peso positivo hasta 100000 kg y 6 decimales");
    }
    public static String sha256(String valor) {
        try { return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(valor.getBytes(StandardCharsets.UTF_8))); }
        catch (NoSuchAlgorithmException e) { throw new IllegalStateException(e); }
    }
    public static String huella(NuevoPedido p, String usuarioId) {
        validar(p);
        StringBuilder texto = new StringBuilder(usuarioId.length() + ":" + usuarioId + "|" + p.almacenId() + "|" + p.zonaEntrega());
        p.items().stream().sorted(Comparator.comparing(Item::sku)).forEach(i -> texto.append('|').append(i.sku()).append(':').append(i.cantidad()));
        return sha256(texto.toString());
    }
    public static Creacion repeticion(Pedido existente, String huella) {
        if (!existente.huella().equals(huella)) throw new Fallo(409, "solicitudId ya utilizada con otro contenido");
        return new Creacion(existente, false);
    }
    public static void rol(Actor actor, Rol... permitidos) {
        if (actor == null) throw new Fallo(401, "Autenticación requerida");
        if (!Arrays.asList(permitidos).contains(actor.rol())) throw new Fallo(403, "Operación no permitida");
    }
    public static void propietario(Actor actor, Pedido pedido) {
        rol(actor, Rol.COMPRADOR, Rol.ADMIN);
        if (actor.rol() != Rol.ADMIN && !pedido.usuarioId().equals(actor.id())) throw new Fallo(404, "Pedido no encontrado");
    }
    public static void transicion(Estado actual, Estado siguiente) {
        if (actual == siguiente) return;
        Set<Estado> permitidos = switch (actual) {
            case RECIBIDO -> Set.of(Estado.EN_PROCESO, Estado.ANULADO, Estado.COMPENSANDO, Estado.REQUIERE_REVISION);
            case EN_PROCESO -> Set.of(Estado.DESPACHADO, Estado.COMPENSANDO, Estado.ANULADO, Estado.REQUIERE_REVISION);
            case COMPENSANDO -> Set.of(Estado.ANULADO, Estado.REQUIERE_REVISION);
            case REQUIERE_REVISION -> Set.of(Estado.COMPENSANDO);
            case DESPACHADO, ANULADO -> Set.of();
        };
        if (!permitidos.contains(siguiente)) throw new Fallo(409, "Transición de pedido inválida");
    }
}
