using System.Diagnostics;
using System.Net;
using System.Text;
using Despachos.Application;
using Despachos.Domain;
using Despachos.Infrastructure.Http;
using Despachos.Api.Security;
using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Hosting.Server;
using Microsoft.AspNetCore.Hosting.Server.Features;
using Microsoft.AspNetCore.Http;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Logging.Abstractions;
using Microsoft.IdentityModel.Protocols;
using MongoDB.Bson;
using MongoDB.Driver;
using Xunit;
namespace Despachos.Tests;

public sealed class JavaFactAttribute : FactAttribute
{
    public JavaFactAttribute()
    {
        if (string.IsNullOrEmpty(Environment.GetEnvironmentVariable("PEDIDOS_TEST_JAR")) ||
            (string.IsNullOrEmpty(Environment.GetEnvironmentVariable("MONGODB_TEST_URI")) && string.IsNullOrEmpty(Environment.GetEnvironmentVariable("MONGODB_TEST_BINARY"))))
            Skip = "Requiere JAR Java existente, claves ficticias y MongoDB 7 real";
    }
}
internal sealed class JavaProceso : IAsyncDisposable
{
    private Process process = null!;
    private readonly StringBuilder logs = new();
    private string logPath = "";
    public string Url { get; private set; } = "";
    public const string Key = "clave-interna-ficticia-integracion-2026";
    public static async Task<JavaProceso> Start(MongoEscenario scenario, MongoFixture fixture)
    {
        var java = new JavaProceso(); int port = MongoFixture.Port(); java.Url = $"http://127.0.0.1:{port}";
        java.logPath = Path.Combine(MongoFixture.Root, ".build", "java-" + scenario.Database + ".log");
        var info = new ProcessStartInfo(Environment.GetEnvironmentVariable("JAVA_TEST_BINARY") ?? "java") { WorkingDirectory = MongoFixture.Root, RedirectStandardOutput = true, RedirectStandardError = true, UseShellExecute = false };
        info.ArgumentList.Add("-jar"); info.ArgumentList.Add(Environment.GetEnvironmentVariable("PEDIDOS_TEST_JAR")!);
        info.Environment["PORT"] = port.ToString(); info.Environment["MONGODB_URI"] = fixture.Uri; info.Environment["MONGODB_DATABASE"] = scenario.Database;
        info.Environment["JWT_PRIVATE_KEY_PATH"] = Environment.GetEnvironmentVariable("PEDIDOS_TEST_PRIVATE_KEY")!;
        info.Environment["JWT_PUBLIC_KEY_PATH"] = Environment.GetEnvironmentVariable("PEDIDOS_TEST_PUBLIC_KEY")!;
        info.Environment["INTERNAL_API_KEY"] = Key;
        java.process = Process.Start(info)!;
        void Capture(object sender, DataReceivedEventArgs e) { if (e.Data is not null) lock (java.logs) java.logs.AppendLine(e.Data); }
        java.process.OutputDataReceived += Capture; java.process.ErrorDataReceived += Capture; java.process.BeginOutputReadLine(); java.process.BeginErrorReadLine();
        using var http = new HttpClient { Timeout = TimeSpan.FromSeconds(1) };
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(30));
        try
        {
            while (!deadline.IsCancellationRequested)
            {
                if (java.process.HasExited) throw new InvalidOperationException("Java terminó antes de readiness");
                try { if ((await http.GetAsync(java.Url + "/health", deadline.Token)).IsSuccessStatusCode) return java; }
                catch (HttpRequestException) { }
                catch (OperationCanceledException) when (!deadline.IsCancellationRequested) { }
                await Task.Delay(100, deadline.Token);
            }
            throw new TimeoutException();
        }
        catch { await java.DisposeAsync(); throw; }
    }
    public async ValueTask DisposeAsync()
    {
        if (process is { HasExited: false }) { process.Kill(); await process.WaitForExitAsync(); }
        if (process is not null) process.Dispose();
        string text; lock (logs) text = logs.ToString(); await File.WriteAllTextAsync(logPath, text);
    }
}
[Collection("Mongo real")]
[Trait("Categoria", "JavaReal")]
public sealed class JavaIntegrationTests(MongoFixture fixture)
{
    private async Task Flujo(bool cortar, bool anular)
    {
        await using var s = new MongoEscenario(fixture); await s.Seed(); await s.Catalogos();
        await s.Db.GetCollection<BsonDocument>("Stock").InsertOneAsync(s.Audit(new BsonDocument { { "_id", "STK-1" }, { "IdAlmacen", "ALM-01" }, { "IdProducto", "SKU-00001" }, { "CantidadStock", 5 }, { "ReservaStock", 0 } }));
        await using var java = await JavaProceso.Start(s, fixture);
        var builder = WebApplication.CreateBuilder(); builder.Logging.ClearProviders(); builder.WebHost.UseUrls("http://127.0.0.1:0");
        await using var carrier = builder.Build(); bool existe = false; int posts = 0; int cancelaciones = 0; List<string> correlations = [];
        carrier.MapGet("/guias", (HttpContext c) => { correlations.Add(c.Request.Headers["X-Correlation-Id"].ToString()); return existe ? Results.Json(new { numeroGuia = "G-REAL" }) : Results.NotFound(); });
        carrier.MapPost("/guias", async (HttpContext c) => {
            posts++; existe = true; Assert.Equal(Reglas.ClaveGuia("PED-1"), c.Request.Headers["Idempotency-Key"].ToString());
            if (anular) await s.Update("Pedido", "PED-1", ("AnulacionSolicitada", true));
            if (cortar) { c.Abort(); return; }
            await c.Response.WriteAsJsonAsync(new { numeroGuia = "G-REAL" });
        });
        carrier.MapPost("/guias/{numero}/anulacion", () => { cancelaciones++; existe = false; return Results.Ok(); });
        await carrier.StartAsync();
        var address = carrier.Services.GetRequiredService<IServer>().Features.Get<IServerAddressesFeature>()!.Addresses.Single();
        using var javaHttp = new HttpClient { BaseAddress = new Uri(java.Url), Timeout = TimeSpan.FromSeconds(5) };
        using var carrierHttp = new HttpClient { BaseAddress = new Uri(address), Timeout = TimeSpan.FromSeconds(5) };
        var options = s.Options with { InternalKey = JavaProceso.Key };
        var coordinator = new Coordinador(s.Repo, new PedidosClient(javaHttp, options), new TransportistaClient(carrierHttp), options, new SinEspera(), s.Clock, NullLogger<Coordinador>.Instance);
        var w = (await s.Repo.Adquirir("java-test", default))!; var p = (await s.Repo.Tomar(w, default))!;
        await coordinator.Procesar(w, p, default); await coordinator.Procesar(w, await s.Repo.Obtener(p.Id, default), default);
        var final = await s.Repo.Obtener(p.Id, default); Assert.Equal(anular ? EstadoPedido.ANULADO : EstadoPedido.DESPACHADO, final.Estado);
        var stock = await s.Doc("Stock", "STK-1"); Assert.Equal(anular ? 5 : 3, stock["CantidadStock"].AsInt32); Assert.Equal(0, stock["ReservaStock"].AsInt32);
        Assert.Equal(1, posts); Assert.Equal(anular ? 1 : 0, cancelaciones); Assert.All(correlations, c => Assert.Equal("corr-test", c));
        var procesos = await s.Db.GetCollection<BsonDocument>("PedidoProceso").Find(new BsonDocument("IdPedido", p.Id)).ToListAsync();
        Assert.DoesNotContain(procesos, d => d["Paso"].AsString.StartsWith("STOCK_", StringComparison.Ordinal));
        Assert.Single(procesos, d => d["Paso"] == "RESERVAR_STOCK");
        var jwks = await new JwksEnvuelto("http://localhost:8090").GetConfigurationAsync(java.Url + "/.well-known/jwks.json", new HttpDocumentRetriever(javaHttp) { RequireHttps = false }, default);
        Assert.Single(jwks.SigningKeys);
        await s.Repo.Cerrar(w, default); await carrier.StopAsync();
    }
    [JavaFact] public Task DespachoCompletoConJavaRealYMongoReal() => Flujo(false, false);
    [JavaFact] public Task CorteDespuesDeGuiaSeRecuperaSinSegundoPostConJavaReal() => Flujo(true, false);
    [JavaFact] public Task AnulacionDuranteGuiaCompensaConJavaReal() => Flujo(false, true);
}
