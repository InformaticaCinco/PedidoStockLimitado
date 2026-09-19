package pe.reto.pedidos.application.usecase;

import static pe.reto.pedidos.domain.Model.*;
import static pe.reto.pedidos.domain.Reglas.*;
import pe.reto.pedidos.application.port.out.Repositorio;
import java.util.List;

public final class CatalogoService {
    private final Repositorio repo;
    public CatalogoService(Repositorio repo) { this.repo = repo; }
    public List<Producto> listar(Actor a, int pagina) { rol(a, Rol.COMPRADOR, Rol.VENDEDOR, Rol.ADMIN); return repo.productos(pagina); }
    public Producto guardar(Actor a, DatosProducto p, boolean nuevo) { rol(a, Rol.VENDEDOR); producto(p); return repo.guardarProducto(a, p, nuevo); }
    public Stock consultar(Actor a, String sku, String almacen) { rol(a, Rol.COMPRADOR, Rol.VENDEDOR, Rol.ADMIN); sku(sku); almacen(almacen); return repo.stock(sku, almacen); }
    public Stock actualizar(Actor a, String sku, String almacen, int disponible) {
        rol(a, Rol.VENDEDOR); sku(sku); almacen(almacen); exigir(disponible >= 0 && disponible <= 1000000000, "disponible", "Entero entre 0 y 1000000000");
        return repo.actualizarStock(a, sku, almacen, disponible);
    }
}
