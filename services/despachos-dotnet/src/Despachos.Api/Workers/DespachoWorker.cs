using Despachos.Application;
using Despachos.Domain;
namespace Despachos.Api.Workers;

public sealed class DespachoWorker(IRepositorio repo, Coordinador coordinador, Opciones opciones, ILogger<DespachoWorker> logger) : BackgroundService
{
    private readonly string propietario = Guid.NewGuid().ToString();
    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        bool inicializado = false;
        while (!stoppingToken.IsCancellationRequested)
        {
            try
            {
                if (!inicializado) { await repo.Inicializar(stoppingToken); inicializado = true; }
                var corrida = await repo.Adquirir(propietario, stoppingToken);
                if (corrida is not null) await EjecutarCorrida(corrida, stoppingToken);
            }
            catch (OperationCanceledException) when (stoppingToken.IsCancellationRequested) { break; }
            catch (Exception e) { logger.LogError("Servicio {servicio} resultado {resultado} error {error}", "despachos-dotnet", "WORKER_PAUSADO", e.GetType().Name); }
            try { await Task.Delay(opciones.PollMs, stoppingToken); }
            catch (OperationCanceledException) when (stoppingToken.IsCancellationRequested) { break; }
        }
    }
    public async Task EjecutarCorrida(Corrida corrida, CancellationToken stoppingToken)
    {
        using var lease = CancellationTokenSource.CreateLinkedTokenSource(stoppingToken);
        var heartbeat = Heartbeat(corrida, lease);
        try
        {
            do
            {
                var p = await repo.Tomar(corrida, lease.Token);
                if (p is null) break;
                try { await coordinador.Procesar(corrida, p, lease.Token); }
                catch (OperationCanceledException) when (lease.IsCancellationRequested) { throw; }
                catch (LeasePerdidoException) { throw; }
                catch (Exception e)
                {
                    logger.LogError("Servicio {servicio} pedidoId {pedidoId} workerId {workerId} correlationId {correlationId} error {error}", "despachos-dotnet", p.Id, corrida.Id, p.CorrelationId, e.GetType().Name);
                    var actual = await repo.Obtener(p.Id, lease.Token);
                    if (actual.Estado is not (EstadoPedido.DESPACHADO or EstadoPedido.ANULADO or EstadoPedido.REQUIERE_REVISION))
                        await repo.CambiarEstado(corrida, p.Id, EstadoPedido.REQUIERE_REVISION, "ERROR_INTERNO_" + e.GetType().Name, actual.Pendiente, lease.Token);
                }
                // Recovery completes only the interrupted order, then closes the original run.
                if (corrida.Recuperada) break;
            } while (!lease.IsCancellationRequested);
            await repo.Cerrar(corrida, lease.Token);
        }
        finally { await lease.CancelAsync(); await heartbeat; }
    }
    private async Task Heartbeat(Corrida corrida, CancellationTokenSource source)
    {
        try
        {
            using var timer = new PeriodicTimer(TimeSpan.FromSeconds(Math.Max(1, opciones.LeaseSeconds / 3)));
            while (await timer.WaitForNextTickAsync(source.Token))
                if (!await repo.Renovar(corrida, source.Token)) { await source.CancelAsync(); return; }
        }
        catch (OperationCanceledException) when (source.IsCancellationRequested) { }
        catch (Exception e) { logger.LogError("WorkerId {workerId} error {error}", corrida.Id, e.GetType().Name); await source.CancelAsync(); }
    }
}
