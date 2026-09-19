package pe.reto.pedidos.application.port.in;

import pe.reto.pedidos.domain.Model.*;
import java.util.List;

public interface Pedidos {
    Creacion crear(Actor actor, NuevoPedido datos, String correlationId);
    VistaPedido consultar(Actor actor, String id);
    List<Pedido> listar(Actor actor, int pagina);
    Pedido anular(Actor actor, String id);
    Pedido operarStock(String id, OperacionStock operacion);
}
