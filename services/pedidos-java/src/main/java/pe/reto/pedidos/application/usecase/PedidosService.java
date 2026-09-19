package pe.reto.pedidos.application.usecase;

import static pe.reto.pedidos.domain.Model.*;
import static pe.reto.pedidos.domain.Reglas.*;
import pe.reto.pedidos.application.port.in.Pedidos;
import pe.reto.pedidos.application.port.out.Repositorio;
import pe.reto.pedidos.domain.Fallo;
import java.util.List;

public final class PedidosService implements Pedidos {
    private final Repositorio repo;
    public PedidosService(Repositorio repo) { this.repo = repo; }
    public Creacion crear(Actor a, NuevoPedido p, String correlationId) {
        rol(a, Rol.COMPRADOR); validar(p);
        return repo.crearPedido(a, p, huella(p, a.id()), correlationId);
    }
    public VistaPedido consultar(Actor a, String id) {
        rol(a, Rol.COMPRADOR, Rol.VENDEDOR, Rol.ADMIN);
        VistaPedido v = repo.pedido(id);
        if (a.rol() == Rol.VENDEDOR) {
            Pedido filtrado = paraVendedor(v.pedido(), a.id());
            if (filtrado.items().isEmpty()) throw new Fallo(404, "Pedido no encontrado");
            return new VistaPedido(filtrado, null, List.of(), List.of());
        }
        propietario(a, v.pedido()); return v;
    }
    public List<Pedido> listar(Actor a, int pagina) {
        rol(a, Rol.COMPRADOR, Rol.VENDEDOR, Rol.ADMIN);
        return repo.pedidos(a, pagina).stream().map(p -> a.rol() == Rol.VENDEDOR ? paraVendedor(p, a.id()) : p).toList();
    }
    public Pedido anular(Actor a, String id) { rol(a, Rol.COMPRADOR, Rol.ADMIN); return repo.solicitarAnulacion(a, id); }
    public Pedido operarStock(String id, OperacionStock op) { return repo.operarStock(id, op); }
    private Pedido paraVendedor(Pedido p, String vendedor) {
        List<Detalle> items = p.items().stream().filter(d -> d.vendedorId().equals(vendedor)).toList();
        var subtotal = items.stream().map(Detalle::subtotal).reduce(java.math.BigDecimal.ZERO, java.math.BigDecimal::add);
        var peso = items.stream().map(d -> d.pesoUnitario().multiply(java.math.BigDecimal.valueOf(d.cantidad()))).reduce(java.math.BigDecimal.ZERO, java.math.BigDecimal::add);
        return new Pedido(p.pedidoId(), null, null, null, p.almacenId(), null, null, p.estado(), dinero(subtotal), null, null, peso, null, p.anulacionSolicitada(), p.reserva(), items);
    }
}
