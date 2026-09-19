using System.Text.Json;
using Despachos.Domain;
using Despachos.Infrastructure.Http;

if (args.Length != 2) throw new ArgumentException("URL y modo normal/partial requeridos");
using var http = new HttpClient { BaseAddress = new Uri(args[0]), Timeout = TimeSpan.FromSeconds(5) };
var client = new TransportistaClient(http);
var pedido = new Pedido("PED-DOTNET", EstadoPedido.EN_PROCESO, EstadoReserva.RESERVADA, "LIMA_METROPOLITANA", "WRK-TEST", DateTime.UtcNow, null, 1, false, "corr-dotnet-real", 1m, null, false, false, false, []);
void Check(bool condition, string reason) { if (!condition) throw new InvalidOperationException(reason); }
Check((await http.GetAsync("/health")).IsSuccessStatusCode, "health");
Check(await client.Consultar(pedido, default) is null, "GET inicial debe ser 404/ausencia");
GuiaRemota? creada = null;
string? error = null;
if (args[1] == "partial")
{
    try { await client.Generar(pedido, 12.4m, default); throw new InvalidOperationException("Se esperaba error real de conexión"); }
    catch (FalloProceso e) when (e.Codigo == "TRANSPORTISTA_CONEXION") { error = e.Codigo; }
}
else creada = await client.Generar(pedido, 12.4m, default);
var descubierta = await client.Consultar(pedido, default);
Check(descubierta is not null, "GET debe encontrar guía");
Check(creada is null || creada.NumeroGuia == descubierta!.NumeroGuia, "POST y GET deben coincidir");
var repetida = await client.Generar(pedido, 12.4m, default);
Check(repetida.NumeroGuia == descubierta!.NumeroGuia, "Misma clave debe repetir número");
await client.Anular(pedido, descubierta.NumeroGuia, default);
await client.Anular(pedido, descubierta.NumeroGuia, default);
Check(await client.Consultar(pedido, default) is null, "GET debe ser 404 después de anular");
Console.WriteLine(JsonSerializer.Serialize(new { modo = args[1], error, numeroGuia = descubierta.NumeroGuia, health = 200, consulta = "compatible", replay = "compatible", anulacion = "compatible" }));
