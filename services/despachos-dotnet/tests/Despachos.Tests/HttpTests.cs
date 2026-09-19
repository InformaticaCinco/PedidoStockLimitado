using System.Net;
using System.Net.Http.Json;
using System.Text.Json;
using Despachos.Application;
using Despachos.Domain;
using Despachos.Infrastructure.Http;
using Xunit;
namespace Despachos.Tests;

internal sealed class Handler(Func<HttpRequestMessage, CancellationToken, Task<HttpResponseMessage>> responder) : HttpMessageHandler
{
    protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken ct) => responder(request, ct);
    public static HttpResponseMessage Json(HttpStatusCode code, object body) => new(code) { Content = JsonContent.Create(body) };
}
public sealed class HttpTests
{
    [Fact] public async Task JavaUsaRutasHeaderTecnicoYSobreReal()
    {
        List<string> rutas = [];
        var handler = new Handler((r, _) => {
            rutas.Add(r.RequestUri!.AbsolutePath); Assert.Equal("key", r.Headers.GetValues("X-Internal-Key").Single()); Assert.Equal("corr-prueba", r.Headers.GetValues("X-Correlation-Id").Single());
            string estado = r.RequestUri.AbsolutePath.EndsWith("reservar") ? "RESERVADA" : r.RequestUri.AbsolutePath.EndsWith("liberar") ? "LIBERADA" : "CONFIRMADA";
            return Task.FromResult(Handler.Json(HttpStatusCode.OK, new { code = 200, statusCode = "HTTP_200_OK", message = "OK", data = new { pedidoId = "PED-1", estadoReserva = estado } }));
        });
        var client = new PedidosClient(new HttpClient(handler) { BaseAddress = new Uri("http://java") }, new Opciones { InternalKey = "key" }); var p = new Memoria().Pedido;
        await client.Reservar(p, default); await client.Liberar(p, default); await client.Confirmar(p, default);
        Assert.Equal(["/internal/pedidos/PED-1/stock/reservar", "/internal/pedidos/PED-1/stock/liberar", "/internal/pedidos/PED-1/stock/confirmar"], rutas);
    }
    [Fact] public async Task StockInsuficienteEsNegocioNoReintento()
    {
        var h = new Handler((_, _) => Task.FromResult(Handler.Json(HttpStatusCode.Conflict, new { code = 409, message = "STOCK_INSUFICIENTE", data = (object?)null })));
        var c = new PedidosClient(new HttpClient(h) { BaseAddress = new Uri("http://java") }, new Opciones { InternalKey = "key" });
        var e = await Assert.ThrowsAsync<FalloProceso>(() => c.Reservar(new Memoria().Pedido, default)); Assert.Equal("STOCK_INSUFICIENTE", e.Codigo); Assert.False(e.Reintentable);
    }
    [Fact] public async Task TransportistaTimeoutRealDeHandlerSeReconciliaSinSegundoPost()
    {
        bool existe = false; int posts = 0, gets = 0; var repo = new Memoria(); var java = new JavaFake(repo);
        var handler = new Handler((r, _) => {
            Assert.Equal(repo.Pedido.CorrelationId, r.Headers.GetValues("X-Correlation-Id").Single());
            if (r.Method == HttpMethod.Get) { gets++; return Task.FromResult(existe ? Handler.Json(HttpStatusCode.OK, new { numeroGuia = "G-1" }) : new HttpResponseMessage(HttpStatusCode.NotFound)); }
            posts++; Assert.Equal(Reglas.ClaveGuia("PED-1"), r.Headers.GetValues("Idempotency-Key").Single()); existe = true; throw new HttpRequestException("connection reset after commit");
        });
        var carrier = new TransportistaClient(new HttpClient(handler) { BaseAddress = new Uri("http://carrier") });
        var coordinator = new Coordinador(repo, java, carrier, new Opciones(), new SinEspera(), TimeProvider.System, Microsoft.Extensions.Logging.Abstractions.NullLogger<Coordinador>.Instance);
        await coordinator.Procesar(new("WRK-1", "owner", 1, false), repo.Pedido, default);
        Assert.Equal(1, posts); Assert.Equal(2, gets); Assert.Equal(EstadoPedido.DESPACHADO, repo.Pedido.Estado);
    }
    [Fact] public async Task ConsultaAmbiguaNoEquivaleAusencia()
    {
        var c = new TransportistaClient(new HttpClient(new Handler((_, _) => Task.FromResult(new HttpResponseMessage(HttpStatusCode.ServiceUnavailable)))) { BaseAddress = new Uri("http://carrier") });
        await Assert.ThrowsAsync<FalloProceso>(() => c.Consultar(new Memoria().Pedido, default));
    }
    [Fact] public async Task RequestGuiaUsaDecimalSinPerderPrecision()
    {
        var c = new TransportistaClient(new HttpClient(new Handler(async (r, ct) => {
            using var j = JsonDocument.Parse(await r.Content!.ReadAsStringAsync(ct)); Assert.Equal(12.4m, j.RootElement.GetProperty("pesoKg").GetDecimal()); Assert.Equal("PROVINCIA", j.RootElement.GetProperty("zona").GetString());
            return Handler.Json(HttpStatusCode.OK, new { numeroGuia = "G-123" });
        })) { BaseAddress = new Uri("http://carrier") });
        Assert.Equal("G-123", (await c.Generar(new Memoria().Pedido, 12.4m, default)).NumeroGuia);
    }
}
