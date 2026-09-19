using System.Diagnostics;
using Despachos.Application;
namespace Despachos.Api.Endpoints;

public sealed record Dependencia(string Nombre, string Estado, long LatenciaMs);
public sealed class Dependencias(IRepositorio repo, IHttpClientFactory clients)
{
    public async Task<Dependencia[]> Consultar(string correlation, CancellationToken ct)
    {
        async Task<Dependencia> Medir(string nombre, Func<CancellationToken, Task> accion)
        {
            var watch = Stopwatch.StartNew();
            using var limite = CancellationTokenSource.CreateLinkedTokenSource(ct); limite.CancelAfter(TimeSpan.FromSeconds(5));
            try { await accion(limite.Token); return new(nombre, "UP", watch.ElapsedMilliseconds); }
            catch (Exception) when (!ct.IsCancellationRequested) { return new(nombre, "DOWN", watch.ElapsedMilliseconds); }
        }
        async Task Http(string client, string path, CancellationToken token)
        {
            using var request = new HttpRequestMessage(HttpMethod.Get, path); request.Headers.Add("X-Correlation-Id", correlation);
            using var response = await clients.CreateClient(client).SendAsync(request, token);
            if (!response.IsSuccessStatusCode) throw new HttpRequestException();
        }
        return await Task.WhenAll(Medir("MongoDB", repo.Ping), Medir("pedidos-java", c => Http("pedidos-health", "/health", c)), Medir("transportista", c => Http("transportista-health", "/health", c)));
    }
}
