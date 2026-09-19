package pe.reto.pedidos;

import static org.junit.jupiter.api.Assertions.*;
import static pe.reto.pedidos.domain.Model.*;
import static pe.reto.pedidos.domain.Reglas.*;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import pe.reto.pedidos.domain.Fallo;
import pe.reto.pedidos.adapter.in.http.JsonEntrada;
import pe.reto.pedidos.config.HttpModule;
import java.math.BigDecimal;
import java.time.Instant;
import java.util.*;

class ReglasTest {
    static NuevoPedido solicitud(String id, Item... items) { return new NuevoPedido(id, "ALM-01", "LIMA_METROPOLITANA", List.of(items)); }
    static Pedido pedido(String hash) { return new Pedido("PED-1", "sol-1", "CLI-1", "USR-1", "ALM-01", "PROVINCIA", hash, Estado.RECIBIDO, BigDecimal.TEN, null, null, BigDecimal.ONE, "corr", false, Reserva.NINGUNA, List.of()); }
    @Test void canonicalizacionOrdenYPropietario() {
        var a = solicitud("sol-1", new Item("SKU-00001", 1), new Item("SKU-00002", 2));
        var b = solicitud("sol-1", new Item("SKU-00002", 2), new Item("SKU-00001", 1));
        assertEquals(huella(a, "USR-1"), huella(b, "USR-1"));
        assertNotEquals(huella(a, "USR-1"), huella(a, "USR-2"));
        assertNotEquals(huella(a, "USR-1"), huella(solicitud("sol-1", new Item("SKU-00001", 2)), "USR-1"));
    }
    @Test void idempotenciaYConflicto() {
        Pedido p = pedido("hash"); assertSame(p, repeticion(p, "hash").pedido()); assertFalse(repeticion(p, "hash").nuevo());
        assertEquals(409, assertThrows(Fallo.class, () -> repeticion(p, "otro")).codigo());
    }
    @ParameterizedTest @ValueSource(ints = {-1, 0, 51, Integer.MAX_VALUE}) void cantidadesInvalidas(int q) { assertThrows(Fallo.class, () -> validar(solicitud("sol-1", new Item("SKU-00001", q)))); }
    @Test void limitesYDuplicados() {
        validar(solicitud("x", new Item("SKU-00001", 1))); validar(solicitud("x".repeat(60), new Item("SKU-00001", 50)));
        assertThrows(Fallo.class, () -> validar(solicitud("x".repeat(61), new Item("SKU-00001", 1))));
        assertThrows(Fallo.class, () -> validar(solicitud("x", new Item("SKU-00001", 1), new Item("SKU-00001", 2))));
        assertThrows(Fallo.class, () -> validar(solicitud("x")));
        assertThrows(Fallo.class, () -> sku("SKU-1")); assertThrows(Fallo.class, () -> almacen("ALM-1"));
        assertThrows(Fallo.class, () -> validar(new NuevoPedido("x", "ALM-01", "INVALIDA", List.of(new Item("SKU-00001", 1)))));
        var veinte = java.util.stream.IntStream.range(0, 20).mapToObj(i -> new Item("SKU-%05d".formatted(i), 1)).toList();
        validar(new NuevoPedido("x", "ALM-01", "PROVINCIA", veinte));
        var mas = new ArrayList<>(veinte); mas.add(new Item("SKU-99999", 1)); assertThrows(Fallo.class, () -> validar(new NuevoPedido("x", "ALM-01", "PROVINCIA", mas)));
    }
    @Test void stockConservacionYConfirmacion() {
        var inicial = new Stock("SKU-00001", "ALM-01", 5, 0);
        var reservado = inicial.reservar(3); assertEquals(5, reservado.total()); assertEquals(2, reservado.disponible());
        assertEquals(inicial, reservado.liberar(3));
        var confirmado = reservado.confirmar(3); assertEquals(2, confirmado.disponible()); assertEquals(0, confirmado.reservado());
        assertThrows(Fallo.class, () -> inicial.reservar(6)); assertThrows(Fallo.class, () -> confirmado.confirmar(3)); assertThrows(Fallo.class, () -> inicial.liberar(1));
    }
    @Test void dineroHalfUpYDuracion() {
        assertEquals(new BigDecimal("10.01"), dinero(new BigDecimal("10.005")));
        assertEquals(new BigDecimal("30.03"), dinero(new BigDecimal("10.01").multiply(BigDecimal.valueOf(3))));
        assertEquals(1234L, new Proceso("x", "OK", 1, Instant.EPOCH, Instant.EPOCH.plusMillis(1234), null).ms());
        assertNull(new Proceso("x", "OK", 1, Instant.EPOCH, null, null).ms());
    }
    @Test void autorizacionYTransiciones() {
        assertEquals(404, assertThrows(Fallo.class, () -> propietario(new Actor("USR-2", Rol.COMPRADOR), pedido("h"))).codigo());
        propietario(new Actor("USR-1", Rol.COMPRADOR), pedido("h"));
        assertEquals(403, assertThrows(Fallo.class, () -> rol(new Actor("V", Rol.VENDEDOR), Rol.COMPRADOR)).codigo());
        transicion(Estado.RECIBIDO, Estado.EN_PROCESO); transicion(Estado.COMPENSANDO, Estado.ANULADO);
        assertThrows(Fallo.class, () -> transicion(Estado.ANULADO, Estado.EN_PROCESO));
        assertThrows(Fallo.class, () -> transicion(Estado.DESPACHADO, Estado.COMPENSANDO));
    }
    @ParameterizedTest @ValueSource(strings = {"\"2\"", "2.0", "true", "null", "{\"$gt\":0}", "[]"}) void tiposJsonNoSeCoercionan(String cantidad) {
        var entrada = new JsonEntrada(HttpModule.json());
        assertEquals(400, assertThrows(Fallo.class, () -> entrada.pedido("{\"solicitudId\":\"sol-1\",\"almacenId\":\"ALM-01\",\"zonaEntrega\":\"PROVINCIA\",\"items\":[{\"sku\":\"SKU-00001\",\"cantidad\":" + cantidad + "}]}")).codigo());
    }
    @Test void rechazaIdentidadExtraDuplicadosYTrailingJson() {
        var entrada = new JsonEntrada(HttpModule.json());
        assertThrows(Fallo.class, () -> entrada.objeto("{\"usuario\":\"a\",\"usuario\":\"b\"}", "usuario"));
        assertThrows(Fallo.class, () -> entrada.objeto("{} {}"));
        assertThrows(Fallo.class, () -> entrada.objeto("{\"clienteId\":\"ajeno\"}", "items"));
        assertThrows(Fallo.class, () -> entrada.texto(entrada.objeto("{\"usuario\":{\"$ne\":null}}", "usuario"), "usuario", 100));
    }
}
