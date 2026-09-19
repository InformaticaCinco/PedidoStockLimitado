using System.Net;
using System.Net.Http.Json;
using System.Text.Json;
using Despachos.Application;
using Despachos.Domain;
namespace Despachos.Infrastructure.Http;

public sealed class PedidosClient(HttpClient http, Opciones options) : IPedidosClient
{
    public Task Reservar(Pedido p, CancellationToken ct) => Operar(p, "reservar", ct);
    public Task Liberar(Pedido p, CancellationToken ct) => Operar(p, "liberar", ct);
    public Task Confirmar(Pedido p, CancellationToken ct) => Operar(p, "confirmar", ct);
    private async Task Operar(Pedido p, string operacion, CancellationToken ct)
    {
        if (string.IsNullOrWhiteSpace(options.InternalKey)) throw new FalloProceso("PEDIDOS_INTERNAL_KEY_NO_CONFIGURADA", false);
        using var request = new HttpRequestMessage(HttpMethod.Post, $"/internal/pedidos/{Uri.EscapeDataString(p.Id)}/stock/{operacion}");
        request.Headers.Add("X-Internal-Key", options.InternalKey); request.Headers.Add("X-Correlation-Id", p.CorrelationId);
        try
        {
            using var response = await http.SendAsync(request, ct);
            using var json = JsonDocument.Parse(await response.Content.ReadAsStringAsync(ct));
            var root = json.RootElement;
            if (response.StatusCode == HttpStatusCode.Conflict && root.TryGetProperty("message", out var m) && m.GetString() == "STOCK_INSUFICIENTE") throw new FalloProceso("STOCK_INSUFICIENTE", false);
            if (!response.IsSuccessStatusCode) throw new FalloProceso("JAVA_HTTP_" + (int)response.StatusCode, (int)response.StatusCode >= 500 || response.StatusCode is HttpStatusCode.RequestTimeout or HttpStatusCode.TooManyRequests);
            string esperado = operacion switch { "reservar" => "RESERVADA", "liberar" => "LIBERADA", _ => "CONFIRMADA" };
            if (root.GetProperty("code").GetInt32() != 200 || root.GetProperty("data").GetProperty("pedidoId").GetString() != p.Id || root.GetProperty("data").GetProperty("estadoReserva").GetString() != esperado)
                throw new FalloProceso("JAVA_CONTRATO_INVALIDO", false);
        }
        catch (OperationCanceledException) when (!ct.IsCancellationRequested) { throw new FalloProceso("JAVA_TIMEOUT"); }
        catch (HttpRequestException) { throw new FalloProceso("JAVA_CONEXION"); }
        catch (Exception e) when (e is JsonException or KeyNotFoundException or InvalidOperationException) { throw new FalloProceso("JAVA_CONTRATO_INVALIDO", false); }
    }
}
public sealed class TransportistaClient(HttpClient http) : ITransportistaClient
{
    private static HttpRequestMessage Request(HttpMethod method, string url, Pedido p)
    { var r = new HttpRequestMessage(method, url); r.Headers.Add("X-Correlation-Id", p.CorrelationId); return r; }
    public async Task<GuiaRemota?> Consultar(Pedido p, CancellationToken ct)
    {
        using var request = Request(HttpMethod.Get, "/guias?pedidoId=" + Uri.EscapeDataString(p.Id), p);
        using var response = await Send(request, ct);
        if (response.StatusCode == HttpStatusCode.NotFound) return null; // Only explicit 404 establishes absence.
        Check(response); return await Guia(response, ct);
    }
    public async Task<GuiaRemota> Generar(Pedido p, decimal peso, CancellationToken ct)
    {
        using var request = Request(HttpMethod.Post, "/guias", p);
        request.Headers.Add("Idempotency-Key", Reglas.ClaveGuia(p.Id));
        request.Content = JsonContent.Create(new { pedidoId = p.Id, pesoKg = peso, zona = p.Zona });
        using var response = await Send(request, ct); Check(response); return await Guia(response, ct);
    }
    public async Task Anular(Pedido p, string numero, CancellationToken ct)
    {
        using var request = Request(HttpMethod.Post, "/guias/" + Uri.EscapeDataString(numero) + "/anulacion", p);
        request.Headers.Add("Idempotency-Key", "anulacion-" + Reglas.ClaveGuia(p.Id));
        using var response = await Send(request, ct);
        if (response.StatusCode == HttpStatusCode.NotFound) return;
        Check(response);
    }
    private async Task<HttpResponseMessage> Send(HttpRequestMessage request, CancellationToken ct)
    {
        try { return await http.SendAsync(request, ct); }
        catch (OperationCanceledException) when (!ct.IsCancellationRequested) { throw new FalloProceso("TRANSPORTISTA_TIMEOUT"); }
        catch (HttpRequestException) { throw new FalloProceso("TRANSPORTISTA_CONEXION"); }
    }
    private static void Check(HttpResponseMessage response)
    {
        if (!response.IsSuccessStatusCode) throw new FalloProceso("TRANSPORTISTA_HTTP_" + (int)response.StatusCode,
            (int)response.StatusCode >= 500 || response.StatusCode is HttpStatusCode.RequestTimeout or HttpStatusCode.TooManyRequests);
    }
    private static async Task<GuiaRemota> Guia(HttpResponseMessage response, CancellationToken ct)
    {
        try
        {
            using var json = JsonDocument.Parse(await response.Content.ReadAsStringAsync(ct));
            string? numero = json.RootElement.GetProperty("numeroGuia").GetString();
            if (numero is null || !System.Text.RegularExpressions.Regex.IsMatch(numero, "^[A-Za-z0-9-]{1,80}$")) throw new JsonException();
            return new(numero);
        }
        catch (Exception e) when (e is JsonException or KeyNotFoundException or InvalidOperationException) { throw new FalloProceso("TRANSPORTISTA_CONTRATO_INVALIDO", false); }
    }
}
