package pe.reto.pedidos;

import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;
import pe.reto.pedidos.adapter.out.security.RsaSeguridad;
import pe.reto.pedidos.config.Settings;
import pe.reto.pedidos.domain.Fallo;
import static pe.reto.pedidos.domain.Model.*;
import java.time.*;
import org.mindrot.jbcrypt.BCrypt;

class SeguridadTest {
    static Settings config(String audience) { return new Settings(0, "mongodb://localhost:27017", "test", "reto", audience, 900, 3600, "keys/reto-private.pem", "keys/reto-public.pem", "clave-ficticia-interna-de-pruebas-2026"); }
    @Test void jwtFirmaIssuerAudienciaExpiracion() {
        Clock now = Clock.fixed(Instant.parse("2026-09-18T00:00:00Z"), ZoneOffset.UTC);
        var s = new RsaSeguridad(config("a"), now); var usuario = new Usuario("USR-1", "No-en-claims", Rol.COMPRADOR, "hash");
        String token = s.firmar(usuario); assertEquals(new Actor("USR-1", Rol.COMPRADOR), s.validar(token));
        assertThrows(Fallo.class, () -> new RsaSeguridad(config("b"), now).validar(token));
        Settings original = config("a");
        Settings otroEmisor = new Settings(0, original.mongoUri(), original.database(), "otro-emisor", "a", 900, 3600, original.privateKey(), original.publicKey(), original.internalKey());
        assertThrows(Fallo.class, () -> new RsaSeguridad(otroEmisor, now).validar(token));
        assertThrows(Fallo.class, () -> new RsaSeguridad(config("a"), Clock.offset(now, Duration.ofSeconds(900))).validar(token));
        String[] partes = token.split("\\."); String alterado = partes[0] + "." + partes[1] + "." + (partes[2].startsWith("A") ? "B" : "A") + partes[2].substring(1);
        assertThrows(Fallo.class, () -> s.validar(alterado)); assertThrows(Fallo.class, () -> s.validar("invalid"));
        var key = (java.util.Map<?, ?>) ((java.util.List<?>) s.jwks().get("keys")).getFirst();
        for (String campo : java.util.List.of("d", "p", "q", "dp", "dq", "qi")) assertFalse(key.containsKey(campo));
        assertEquals(43, s.nuevoRefresh().length());
    }
    @Test void bcryptVerificaSinTextoPlano() {
        var s = new RsaSeguridad(config("a"), Clock.systemUTC()); String hash = BCrypt.hashpw("prueba", BCrypt.gensalt(4));
        assertTrue(s.verificarClave("prueba", hash)); assertFalse(s.verificarClave("otra", hash));
    }
}
