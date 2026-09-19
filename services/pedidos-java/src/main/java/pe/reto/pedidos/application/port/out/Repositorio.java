package pe.reto.pedidos.application.port.out;

import pe.reto.pedidos.domain.Model.*;
import java.util.*;

/** Atomic boundaries belong to the persistence port, never to HTTP handlers. */
public interface Repositorio {
    Optional<Usuario> usuarioPorLogin(String login);
    Optional<Usuario> usuarioPorId(String id);
    void guardarRefresh(Refresh refresh);
    boolean rotarRefresh(String anteriorHash, Refresh siguiente);
    Optional<Refresh> refreshActivo(String hash);
    void revocarRefresh(String hash);
    List<Producto> productos(int pagina);
    Producto guardarProducto(Actor actor, DatosProducto datos, boolean nuevo);
    Stock stock(String sku, String almacen);
    Stock actualizarStock(Actor actor, String sku, String almacen, int disponible);
    Creacion crearPedido(Actor actor, NuevoPedido datos, String huella, String correlationId);
    VistaPedido pedido(String id);
    List<Pedido> pedidos(Actor actor, int pagina);
    Pedido solicitarAnulacion(Actor actor, String id);
    Pedido operarStock(String id, OperacionStock operacion);
    long latenciaMongo();
}
