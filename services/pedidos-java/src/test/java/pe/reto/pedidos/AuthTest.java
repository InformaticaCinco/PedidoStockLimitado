package pe.reto.pedidos;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;
import static pe.reto.pedidos.domain.Model.*;
import static pe.reto.pedidos.domain.Reglas.sha256;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import pe.reto.pedidos.application.port.out.*;
import pe.reto.pedidos.application.usecase.*;
import pe.reto.pedidos.domain.Fallo;
import java.time.*;
import java.util.*;

class AuthTest {
    final Repositorio repo = mock(Repositorio.class);
    final Seguridad seguridad = mock(Seguridad.class);
    final Clock reloj = Clock.fixed(Instant.parse("2026-09-18T00:00:00Z"), ZoneOffset.UTC);
    final AuthService auth = new AuthService(repo, seguridad, reloj, 900, 3600);
    final Usuario user = new Usuario("USR-1", "Prueba", Rol.COMPRADOR, "hash-bcrypt");
    @Test void loginSoloPersisteHash() {
        when(repo.usuarioPorLogin("login")).thenReturn(Optional.of(user)); when(seguridad.verificarClave("clave", "hash-bcrypt")).thenReturn(true);
        when(seguridad.nuevoRefresh()).thenReturn("refresh-original"); when(seguridad.firmar(user)).thenReturn("jwt");
        Tokens tokens = auth.login("login", "clave"); assertEquals(900, tokens.expiraEn());
        ArgumentCaptor<Refresh> cap = ArgumentCaptor.forClass(Refresh.class); verify(repo).guardarRefresh(cap.capture());
        assertEquals(sha256("refresh-original"), cap.getValue().hash()); assertNotEquals(tokens.refreshToken(), cap.getValue().hash());
    }
    @Test void mensajesIdenticosParaUsuarioAusenteYClaveIncorrecta() {
        when(repo.usuarioPorLogin("ausente")).thenReturn(Optional.empty()); when(repo.usuarioPorLogin("existe")).thenReturn(Optional.of(user));
        Fallo a = assertThrows(Fallo.class, () -> auth.login("ausente", "x")); Fallo b = assertThrows(Fallo.class, () -> auth.login("existe", "x"));
        assertEquals(401, a.codigo()); assertEquals(a.getMessage(), b.getMessage()); verify(repo, never()).guardarRefresh(any());
    }
    @Test void rotacionAtomicaYLogout() {
        when(repo.refreshActivo(sha256("old"))).thenReturn(Optional.of(new Refresh(sha256("old"), user.id(), reloj.instant().plusSeconds(60))));
        when(repo.usuarioPorId(user.id())).thenReturn(Optional.of(user)); when(seguridad.nuevoRefresh()).thenReturn("new"); when(seguridad.firmar(user)).thenReturn("jwt");
        when(repo.rotarRefresh(eq(sha256("old")), any())).thenReturn(true).thenReturn(false);
        assertEquals("new", auth.refresh("old").refreshToken());
        assertEquals(401, assertThrows(Fallo.class, () -> auth.refresh("old")).codigo());
        auth.logout("new"); verify(repo).revocarRefresh(sha256("new"));
    }
    @Test void refreshExpirado() {
        when(repo.refreshActivo(any())).thenReturn(Optional.of(new Refresh("x", user.id(), reloj.instant().minusSeconds(1))));
        assertThrows(Fallo.class, () -> auth.refresh("old")); verify(repo, never()).rotarRefresh(any(), any());
    }
    @Test void validacionNoConsumeSolicitud() {
        var service = new PedidosService(repo);
        assertThrows(Fallo.class, () -> service.crear(new Actor("USR-1", Rol.COMPRADOR), ReglasTest.solicitud("sol-1", new Item("SKU-00001", 0)), "c"));
        verifyNoInteractions(repo);
    }
}
