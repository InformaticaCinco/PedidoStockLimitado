package pe.reto.pedidos.application.port.out;

import pe.reto.pedidos.domain.Model.*;
import java.util.Map;

public interface Seguridad {
    boolean verificarClave(String clave, String hash);
    String firmar(Usuario usuario);
    Actor validar(String token);
    String nuevoRefresh();
    Map<String, Object> jwks();
}
