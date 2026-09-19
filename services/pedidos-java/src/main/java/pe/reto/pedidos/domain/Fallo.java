package pe.reto.pedidos.domain;

import java.util.Map;

public class Fallo extends RuntimeException {
    private final int codigo;
    private final Map<String, String> errores;
    public Fallo(int codigo, String mensaje) { this(codigo, mensaje, Map.of()); }
    public Fallo(int codigo, String mensaje, Map<String, String> errores) {
        super(mensaje); this.codigo = codigo; this.errores = Map.copyOf(errores);
    }
    public int codigo() { return codigo; }
    public Map<String, String> errores() { return errores; }
}
