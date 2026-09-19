package pe.reto.pedidos.domain;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.List;

public final class Model {
    private Model() {}
    public enum Rol { COMPRADOR, VENDEDOR, ADMIN }
    public enum Estado { RECIBIDO, EN_PROCESO, DESPACHADO, COMPENSANDO, ANULADO, REQUIERE_REVISION }
    public enum Reserva { NINGUNA, RESERVADA, LIBERADA, CONFIRMADA }
    public enum OperacionStock { RESERVAR, LIBERAR, CONFIRMAR }
    public record Actor(String id, Rol rol) {}
    public record Usuario(String id, String nombre, Rol rol, String claveHash) {}
    public record Item(String sku, int cantidad) {}
    public record NuevoPedido(String solicitudId, String almacenId, String zonaEntrega, List<Item> items) {}
    public record Producto(String sku, String vendedorId, String almacenId, String nombre, BigDecimal precio, BigDecimal peso) {}
    public record DatosProducto(String sku, String nombre, BigDecimal precio, BigDecimal peso) {}
    public record Stock(String sku, String almacenId, int disponible, int reservado) {
        public Stock {
            if (disponible < 0 || reservado < 0) throw new IllegalArgumentException("Stock negativo");
        }
        public long total() { return (long) disponible + reservado; }
        public Stock reservar(int q) {
            if (q <= 0 || disponible < q) throw new Fallo(409, "STOCK_INSUFICIENTE");
            return new Stock(sku, almacenId, disponible - q, Math.addExact(reservado, q));
        }
        public Stock liberar(int q) {
            if (q <= 0 || reservado < q) throw new Fallo(409, "RESERVA_INSUFICIENTE");
            return new Stock(sku, almacenId, Math.addExact(disponible, q), reservado - q);
        }
        public Stock confirmar(int q) {
            if (q <= 0 || reservado < q) throw new Fallo(409, "RESERVA_INSUFICIENTE");
            return new Stock(sku, almacenId, disponible, reservado - q);
        }
    }
    public record Detalle(String sku, String vendedorId, int cantidad, BigDecimal precioUnitario,
                          BigDecimal pesoUnitario, BigDecimal subtotal) {}
    public record Pedido(String pedidoId, String solicitudId, String clienteId, String usuarioId,
                         String almacenId, String zonaEntrega, String huella, Estado estado,
                         BigDecimal subtotal, BigDecimal envio, BigDecimal total, BigDecimal pesoTotal,
                         String correlationId, boolean anulacionSolicitada, Reserva reserva, List<Detalle> items) {}
    public record Creacion(Pedido pedido, boolean nuevo) {}
    public record Proceso(String paso, String estado, int intentos, Instant inicio, Instant fin, String log) {
        public Long ms() { return inicio == null || fin == null ? null : java.time.Duration.between(inicio, fin).toMillis(); }
    }
    public record Guia(String id, String estado) {}
    public record VistaPedido(Pedido pedido, Guia guia, List<Proceso> pasos, List<Proceso> compensaciones) {}
    public record Refresh(String hash, String usuarioId, Instant expira) {}
    public record Tokens(String accessToken, long expiraEn, String refreshToken, UsuarioPublico usuario) {}
    public record UsuarioPublico(String id, String nombre, Rol rol) {}
}
