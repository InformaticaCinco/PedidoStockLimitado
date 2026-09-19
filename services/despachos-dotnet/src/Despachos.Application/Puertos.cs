using Despachos.Domain;
namespace Despachos.Application;

public interface IRepositorio
{
    Task Inicializar(CancellationToken ct);
    Task<Corrida?> Adquirir(string propietario, CancellationToken ct);
    Task<bool> Renovar(Corrida corrida, CancellationToken ct);
    Task Verificar(Corrida corrida, CancellationToken ct);
    Task<Pedido?> Tomar(Corrida corrida, CancellationToken ct);
    Task Cerrar(Corrida corrida, CancellationToken ct);
    Task<Pedido> Obtener(string id, CancellationToken ct);
    Task<Guia?> ObtenerGuia(string pedidoId, CancellationToken ct);
    Task<IReadOnlyList<Tarifa>> Tarifas(string zona, CancellationToken ct);
    Task<string> Transporte(CancellationToken ct);
    Task GuardarEnvio(Corrida corrida, string id, Importes importes, CancellationToken ct);
    Task MarcarGuiaIntentada(Corrida corrida, string id, CancellationToken ct);
    Task GuardarGuia(Corrida corrida, string id, string numero, string transporte, CancellationToken ct);
    Task MarcarGuiaAnulada(Corrida corrida, string id, CancellationToken ct);
    Task<IntentoPaso> IniciarPaso(Corrida corrida, string id, Paso paso, CancellationToken ct);
    Task TerminarPaso(Corrida corrida, string id, IntentoPaso intento, bool exito, string log, CancellationToken ct);
    Task CambiarEstado(Corrida corrida, string id, EstadoPedido estado, string motivo, Paso? pendiente, CancellationToken ct);
    Task<bool> Finalizar(Corrida corrida, string id, EstadoPedido estado, string motivo, CancellationToken ct);
    Task SolicitarReintento(string id, string usuario, string correlationId, CancellationToken ct);
    Task Ping(CancellationToken ct);
}
public interface IPedidosClient
{
    Task Reservar(Pedido pedido, CancellationToken ct);
    Task Liberar(Pedido pedido, CancellationToken ct);
    Task Confirmar(Pedido pedido, CancellationToken ct);
}
public interface ITransportistaClient
{
    Task<GuiaRemota?> Consultar(Pedido pedido, CancellationToken ct);
    Task<GuiaRemota> Generar(Pedido pedido, decimal peso, CancellationToken ct);
    Task Anular(Pedido pedido, string numero, CancellationToken ct);
}
public interface IEspera { Task Esperar(TimeSpan demora, CancellationToken ct); }
public sealed class Espera : IEspera { public Task Esperar(TimeSpan demora, CancellationToken ct) => Task.Delay(demora, ct); }
