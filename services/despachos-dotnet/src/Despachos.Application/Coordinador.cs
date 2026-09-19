using Despachos.Domain;
using Microsoft.Extensions.Logging;
namespace Despachos.Application;

public sealed class Coordinador(IRepositorio repo, IPedidosClient java, ITransportistaClient transportista,
    Opciones opciones, IEspera espera, TimeProvider reloj, ILogger<Coordinador> logger)
{
    public async Task Procesar(Corrida corrida, Pedido tomado, CancellationToken ct)
    {
        using var scope = logger.BeginScope(new Dictionary<string, object?> {
            ["servicio"] = "despachos-dotnet", ["correlationId"] = tomado.CorrelationId,
            ["pedidoId"] = tomado.Id, ["workerId"] = corrida.Id
        });
        Pedido p = await repo.Obtener(tomado.Id, ct);
        if (p.Estado is EstadoPedido.DESPACHADO or EstadoPedido.ANULADO or EstadoPedido.REQUIERE_REVISION) return;
        try
        {
            if (p.Estado == EstadoPedido.COMPENSANDO || p.CompensacionPendiente || p.Anulacion || Vencido(p))
            { await Compensar(corrida, p, Vencido(p) ? "TIMEOUT_PROCESO" : "ANULACION_SOLICITADA", ct); return; }
            if (p.Reserva == EstadoReserva.NINGUNA)
            {
                await Ejecutar(corrida, p, Paso.RESERVAR_STOCK, c => java.Reservar(p, c), ct);
                p = await Actual(corrida, p, ct);
            }
            if (await Detener(corrida, p, ct)) return;
            if (p.Reserva is EstadoReserva.LIBERADA) throw new FalloProceso("RESERVA_YA_LIBERADA", false);
            if (p.Envio is null)
            {
                await Ejecutar(corrida, p, Paso.CALCULAR_ENVIO, async c => {
                    var importes = Reglas.Calcular(p.Lineas, await repo.Tarifas(p.Zona, c), p.Zona);
                    await repo.GuardarEnvio(corrida, p.Id, importes, c);
                }, ct);
                p = await Actual(corrida, p, ct);
            }
            if (await Detener(corrida, p, ct)) return;
            var guia = await repo.ObtenerGuia(p.Id, ct);
            if (guia is null)
            {
                await Ejecutar(corrida, p, Paso.GENERAR_GUIA, async c => {
                    // Always reconcile first, including the first attempt after restart.
                    string transporteId = await repo.Transporte(c);
                    var remota = await transportista.Consultar(p, c);
                    if (remota is null)
                    {
                        await repo.MarcarGuiaIntentada(corrida, p.Id, c); // Write-ahead before any remote side effect.
                        await repo.Verificar(corrida, c);
                        try { remota = await transportista.Generar(p, p.Lineas.Sum(l => l.Cantidad * l.PesoUnitario), c); }
                        catch (FalloProceso)
                        {
                            remota = await transportista.Consultar(p, c);
                            if (remota is null) throw;
                        }
                    }
                    await repo.GuardarGuia(corrida, p.Id, remota.NumeroGuia, transporteId, c);
                }, ct);
                p = await Actual(corrida, p, ct);
            }
            if (await Detener(corrida, p, ct)) return;
            guia = await repo.ObtenerGuia(p.Id, ct);
            if (guia is null || guia.Anulada || p.Envio is null) throw new FalloProceso("CONFIRMACION_SIN_PRERREQUISITOS", false);
            if (p.Reserva != EstadoReserva.CONFIRMADA)
            {
                await Ejecutar(corrida, p, Paso.CONFIRMAR_DESPACHO, async c => {
                    var actual = await Actual(corrida, p, c);
                    if (actual.Anulacion) throw new CancelacionSolicitada();
                    await java.Confirmar(actual, c);
                }, ct);
                p = await Actual(corrida, p, ct);
            }
            // CAS includes cancellation=false and reservation=CONFIRMADA. Never hide the Java contract gap.
            if (!await repo.Finalizar(corrida, p.Id, EstadoPedido.DESPACHADO, "DESPACHO_COMPLETADO", ct))
                await Compensar(corrida, await Actual(corrida, p, ct), "ANULACION_CONCURRENTE", ct);
        }
        catch (CancelacionSolicitada) { await Compensar(corrida, await Actual(corrida, p, ct), "ANULACION_SOLICITADA", ct); }
        catch (FalloProceso e) when (e.Codigo == "STOCK_INSUFICIENTE")
        {
            var actual = await Actual(corrida, p, ct);
            if (actual.Reserva == EstadoReserva.NINGUNA && !actual.GuiaIntentada)
                await repo.Finalizar(corrida, p.Id, EstadoPedido.ANULADO, "Stock insuficiente", ct);
            else await Revision(corrida, actual, "STOCK_INSUFICIENTE_CON_EFECTOS", ct);
        }
        catch (FalloProceso e)
        {
            var actual = await Actual(corrida, p, ct);
            if (actual.Anulacion && actual.Estado != EstadoPedido.COMPENSANDO)
                await Compensar(corrida, actual, "ANULACION_SOLICITADA", ct);
            else if (e.Codigo == "TARIFA_AUSENTE_O_AMBIGUA")
                await Compensar(corrida, actual, e.Codigo, ct);
            else await Revision(corrida, actual, e.Codigo, ct);
        }
    }
    private bool Vencido(Pedido p) => p.Inicio is { } inicio && reloj.GetUtcNow().UtcDateTime >= inicio.AddSeconds(opciones.ProcessTimeoutSeconds);
    private async Task<Pedido> Actual(Corrida corrida, Pedido p, CancellationToken ct) { await repo.Verificar(corrida, ct); return await repo.Obtener(p.Id, ct); }
    private async Task<bool> Detener(Corrida corrida, Pedido p, CancellationToken ct)
    {
        p = await Actual(corrida, p, ct);
        if (!p.Anulacion && !Vencido(p)) return false;
        await Compensar(corrida, p, p.Anulacion ? "ANULACION_SOLICITADA" : "TIMEOUT_PROCESO", ct); return true;
    }
    private async Task Ejecutar(Corrida corrida, Pedido p, Paso paso, Func<CancellationToken, Task> accion, CancellationToken ct)
    {
        while (true)
        {
            ct.ThrowIfCancellationRequested(); await repo.Verificar(corrida, ct);
            var actual = await repo.Obtener(p.Id, ct);
            if (!Reglas.EsCompensacion(paso) && (actual.Anulacion || Vencido(actual))) throw new CancelacionSolicitada();
            var intento = await repo.IniciarPaso(corrida, p.Id, paso, ct);
            var inicio = reloj.GetTimestamp();
            try
            {
                await accion(ct);
                await repo.TerminarPaso(corrida, p.Id, intento, true, "OK", ct);
                logger.LogInformation("Paso {paso} intento {intento} duración {duracionMs} resultado {resultado}", paso, intento.Numero, reloj.GetElapsedTime(inicio).TotalMilliseconds, "OK");
                return;
            }
            catch (CancelacionSolicitada)
            { await repo.TerminarPaso(corrida, p.Id, intento, false, "ANULACION_SOLICITADA", ct); throw; }
            catch (FalloProceso e)
            {
                await repo.TerminarPaso(corrida, p.Id, intento, false, e.Codigo, ct);
                logger.LogWarning("Paso {paso} intento {intento} duración {duracionMs} error {error}", paso, intento.Numero, reloj.GetElapsedTime(inicio).TotalMilliseconds, e.Codigo);
                if (!e.Reintentable || intento.Ciclo >= opciones.MaxAttempts) throw;
                await espera.Esperar(TimeSpan.FromMilliseconds((long)opciones.BaseDelayMs * intento.Ciclo), ct);
            }
        }
    }
    private async Task Compensar(Corrida corrida, Pedido pedido, string motivo, CancellationToken ct)
    {
        try
        {
            var p = await Actual(corrida, pedido, ct);
            if (p.Estado is EstadoPedido.DESPACHADO or EstadoPedido.ANULADO) return;
            if (p.Reserva == EstadoReserva.CONFIRMADA)
            { await Revision(corrida, p, "ANULACION_TRAS_CONFIRMACION_REQUIERE_AJUSTE_JAVA", ct); return; }
            var guia = await repo.ObtenerGuia(p.Id, ct);
            bool posiblesEfectos = p.Reserva == EstadoReserva.RESERVADA || guia is { Anulada: false } || p.GuiaIntentada;
            if (posiblesEfectos && p.Estado != EstadoPedido.COMPENSANDO)
                await repo.CambiarEstado(corrida, p.Id, EstadoPedido.COMPENSANDO, motivo, p.Pendiente, ct);
            if (guia is { Anulada: false } || (guia is null && p.GuiaIntentada))
            {
                await Ejecutar(corrida, p, Paso.ANULAR_GUIA, async c => {
                    var existente = await repo.ObtenerGuia(p.Id, c);
                    if (existente is null)
                    {
                        var remota = await transportista.Consultar(p, c); // Unknown outcome: never assume no guide on timeout.
                        if (remota is null) return;
                        await repo.GuardarGuia(corrida, p.Id, remota.NumeroGuia, await repo.Transporte(c), c);
                        existente = await repo.ObtenerGuia(p.Id, c);
                    }
                    if (existente is { Anulada: false })
                    {
                        await transportista.Anular(p, existente.Numero, c);
                        await repo.MarcarGuiaAnulada(corrida, p.Id, c);
                    }
                }, ct);
            }
            p = await Actual(corrida, p, ct);
            if (p.Reserva == EstadoReserva.RESERVADA)
                await Ejecutar(corrida, p, Paso.LIBERAR_STOCK, c => java.Liberar(p, c), ct);
            if (!await repo.Finalizar(corrida, p.Id, EstadoPedido.ANULADO, motivo, ct))
                await Revision(corrida, await Actual(corrida, p, ct), "COMPENSACION_NO_VERIFICADA", ct);
        }
        catch (FalloProceso e) { await Revision(corrida, await repo.Obtener(pedido.Id, ct), e.Codigo, ct); }
    }
    private Task Revision(Corrida corrida, Pedido p, string motivo, CancellationToken ct) =>
        repo.CambiarEstado(corrida, p.Id, EstadoPedido.REQUIERE_REVISION, motivo, p.Pendiente, ct);
    private sealed class CancelacionSolicitada : Exception;
}
