package pe.reto.pedidos.application.usecase;

import static pe.reto.pedidos.domain.Model.*;
import static pe.reto.pedidos.domain.Reglas.*;
import pe.reto.pedidos.application.port.out.*;
import pe.reto.pedidos.domain.Fallo;
import java.time.Clock;

public final class AuthService {
    private final Repositorio repo;
    private final Seguridad seguridad;
    private final Clock reloj;
    private final long accessSeconds, refreshSeconds;
    public AuthService(Repositorio repo, Seguridad seguridad, Clock reloj, long accessSeconds, long refreshSeconds) {
        this.repo = repo; this.seguridad = seguridad; this.reloj = reloj; this.accessSeconds = accessSeconds; this.refreshSeconds = refreshSeconds;
    }
    public Tokens login(String login, String clave) {
        var usuario = repo.usuarioPorLogin(login);
        // A missing user still pays the password verification cost.
        String hash = usuario.map(Usuario::claveHash).orElse("$2a$12$R9h/cIPz0gi.URNNX3kh2OPST9/PgBkqquzi.Ss7KIUgO2t0jWMUW");
        boolean valida = seguridad.verificarClave(clave, hash);
        if (usuario.isEmpty() || !valida) throw new Fallo(401, "Credenciales inválidas");
        Usuario u = usuario.orElseThrow();
        String token = seguridad.nuevoRefresh();
        String access = seguridad.firmar(u);
        repo.guardarRefresh(new Refresh(sha256(token), u.id(), reloj.instant().plusSeconds(refreshSeconds)));
        return tokens(u, access, token);
    }
    public Tokens refresh(String token) {
        String hash = sha256(token);
        Refresh anterior = repo.refreshActivo(hash).filter(r -> r.expira().isAfter(reloj.instant())).orElseThrow(() -> new Fallo(401, "Refresh inválido"));
        Usuario u = repo.usuarioPorId(anterior.usuarioId()).orElseThrow(() -> new Fallo(401, "Refresh inválido"));
        String nuevo = seguridad.nuevoRefresh();
        String access = seguridad.firmar(u);
        if (!repo.rotarRefresh(hash, new Refresh(sha256(nuevo), u.id(), reloj.instant().plusSeconds(refreshSeconds)))) throw new Fallo(401, "Refresh inválido");
        return tokens(u, access, nuevo);
    }
    public void logout(String token) { repo.revocarRefresh(sha256(token)); }
    private Tokens tokens(Usuario u, String access, String refresh) { return new Tokens(access, accessSeconds, refresh, new UsuarioPublico(u.id(), u.nombre(), u.rol())); }
}
