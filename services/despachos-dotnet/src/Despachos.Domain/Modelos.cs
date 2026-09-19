namespace Despachos.Domain;

public enum EstadoPedido { RECIBIDO, EN_PROCESO, DESPACHADO, COMPENSANDO, ANULADO, REQUIERE_REVISION }
public enum EstadoReserva { NINGUNA, RESERVADA, LIBERADA, CONFIRMADA }
public enum Paso { RESERVAR_STOCK, CALCULAR_ENVIO, GENERAR_GUIA, CONFIRMAR_DESPACHO, ANULAR_GUIA, LIBERAR_STOCK }
public sealed record Linea(string Sku, int Cantidad, decimal PrecioUnitario, decimal PesoUnitario, decimal Subtotal);
public sealed record Pedido(string Id, EstadoPedido Estado, EstadoReserva Reserva, string Zona,
    string? WorkerId, DateTime? Inicio, DateTime? Fin, int Intento, bool Anulacion,
    string CorrelationId, decimal? Envio, Paso? Pendiente, bool GuiaIntentada, bool ReintentoSolicitado,
    bool CompensacionPendiente, IReadOnlyList<Linea> Lineas);
public sealed record Corrida(string Id, string Propietario, long Version, bool Recuperada);
public sealed record Guia(string Id, string PedidoId, string Numero, string TransporteId, bool Anulada);
public sealed record Tarifa(string Zona, decimal Desde, decimal Hasta, decimal Importe);
public sealed record Importes(decimal Peso, decimal Subtotal, decimal Envio, decimal Total);
public sealed record IntentoPaso(string Id, Paso Paso, int Numero, int Ciclo, DateTime Inicio);
public sealed record GuiaRemota(string NumeroGuia);

public static class Reglas
{
    public static decimal Moneda(decimal importe) => Math.Round(importe, 2, MidpointRounding.AwayFromZero);
    public static Importes Calcular(IReadOnlyList<Linea> lineas, IReadOnlyList<Tarifa> tarifas, string zona)
    {
        if (lineas.Count == 0 || lineas.Any(l => l.Cantidad <= 0 || l.PesoUnitario <= 0 || l.Subtotal < 0))
            throw new FalloProceso("DETALLE_INVALIDO", false);
        decimal peso = lineas.Sum(l => checked(l.Cantidad * l.PesoUnitario));
        // Lower bound inclusive, upper exclusive: adjacent bands never overlap at a boundary.
        var candidatas = tarifas.Where(t => t.Zona == zona && peso >= t.Desde && peso < t.Hasta && t.Importe >= 0).ToArray();
        if (candidatas.Length != 1) throw new FalloProceso("TARIFA_AUSENTE_O_AMBIGUA", false);
        decimal subtotal = Moneda(lineas.Sum(l => l.Subtotal));
        decimal envio = Moneda(candidatas[0].Importe);
        return new(peso, subtotal, envio, Moneda(subtotal + envio));
    }
    public static void Transicion(EstadoPedido actual, EstadoPedido siguiente)
    {
        bool ok = actual == siguiente || actual switch
        {
            EstadoPedido.RECIBIDO => siguiente is EstadoPedido.EN_PROCESO or EstadoPedido.ANULADO or EstadoPedido.REQUIERE_REVISION,
            EstadoPedido.EN_PROCESO => siguiente is EstadoPedido.DESPACHADO or EstadoPedido.COMPENSANDO or EstadoPedido.ANULADO or EstadoPedido.REQUIERE_REVISION,
            EstadoPedido.COMPENSANDO => siguiente is EstadoPedido.ANULADO or EstadoPedido.REQUIERE_REVISION,
            EstadoPedido.REQUIERE_REVISION => siguiente is EstadoPedido.EN_PROCESO or EstadoPedido.COMPENSANDO,
            _ => false
        };
        if (!ok) throw new FalloProceso("TRANSICION_INVALIDA", false);
    }
    public static string ClaveGuia(string pedidoId) => "despacho-guia-" + pedidoId;
    public static bool EsCompensacion(Paso paso) => paso is Paso.ANULAR_GUIA or Paso.LIBERAR_STOCK;
}
public sealed class FalloProceso(string codigo, bool reintentable = true) : Exception(codigo)
{
    public string Codigo { get; } = codigo;
    public bool Reintentable { get; } = reintentable;
}
public sealed class LeasePerdidoException() : Exception("LEASE_PERDIDO");
public sealed class FalloHttp(int codigo, string mensaje) : Exception(mensaje)
{
    public int Codigo { get; } = codigo;
}
