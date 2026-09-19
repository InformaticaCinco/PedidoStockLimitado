using System.Text.RegularExpressions;
using Despachos.Application;
using Despachos.Domain;
using Despachos.Infrastructure.Http;
using Despachos.Infrastructure.Mongo;
using Despachos.Api.Endpoints;
using Despachos.Api.Security;
using Despachos.Api.Workers;
using Microsoft.AspNetCore.Authentication.JwtBearer;
using Microsoft.IdentityModel.Protocols;
using Microsoft.IdentityModel.Protocols.OpenIdConnect;
using Microsoft.IdentityModel.Tokens;
using MongoDB.Driver;

var builder = WebApplication.CreateBuilder(args);
var opciones = Opciones.Leer();
builder.WebHost.UseUrls("http://0.0.0.0:8091");
builder.Logging.ClearProviders(); builder.Logging.AddJsonConsole(o => { o.IncludeScopes = true; o.TimestampFormat = "yyyy-MM-ddTHH:mm:ss.fffZ"; o.UseUtcTimestamp = true; });
builder.Logging.AddFilter("Microsoft", LogLevel.Warning).AddFilter("System.Net.Http.HttpClient", LogLevel.None).AddFilter("MongoDB", LogLevel.None);
builder.Services.AddSingleton(opciones); builder.Services.AddSingleton(TimeProvider.System);
builder.Services.AddSingleton<IMongoClient>(_ => {
    var s = MongoClientSettings.FromConnectionString(opciones.MongoUri); s.ReadConcern = ReadConcern.Majority; s.WriteConcern = WriteConcern.WMajority; s.ReadPreference = ReadPreference.Primary; s.ServerSelectionTimeout = TimeSpan.FromSeconds(5); return new MongoClient(s);
});
builder.Services.AddSingleton<IRepositorio, MongoRepositorio>(); builder.Services.AddSingleton<IEspera, Espera>();
builder.Services.AddSingleton<Coordinador>(); builder.Services.AddSingleton<Dependencias>();
builder.Services.AddHttpClient<IPedidosClient, PedidosClient>(c => { c.BaseAddress = new Uri(opciones.PedidosUrl); c.Timeout = TimeSpan.FromSeconds(opciones.HttpTimeoutSeconds); }).ConfigurePrimaryHttpMessageHandler(() => new HttpClientHandler { AllowAutoRedirect = false });
builder.Services.AddHttpClient<ITransportistaClient, TransportistaClient>(c => { c.BaseAddress = new Uri(opciones.TransportistaUrl); c.Timeout = TimeSpan.FromSeconds(opciones.HttpTimeoutSeconds); }).ConfigurePrimaryHttpMessageHandler(() => new HttpClientHandler { AllowAutoRedirect = false });
builder.Services.AddHttpClient("pedidos-health", c => { c.BaseAddress = new Uri(opciones.PedidosUrl); c.Timeout = TimeSpan.FromSeconds(5); });
builder.Services.AddHttpClient("transportista-health", c => { c.BaseAddress = new Uri(opciones.TransportistaUrl); c.Timeout = TimeSpan.FromSeconds(5); });
builder.Services.AddHttpClient("jwks", c => c.Timeout = TimeSpan.FromSeconds(5)).ConfigurePrimaryHttpMessageHandler(() => new HttpClientHandler { AllowAutoRedirect = false });
builder.Services.AddHostedService<DespachoWorker>();
builder.Services.AddAuthentication(JwtBearerDefaults.AuthenticationScheme).AddJwtBearer();
builder.Services.AddOptions<JwtBearerOptions>(JwtBearerDefaults.AuthenticationScheme).Configure<IHttpClientFactory>((o, factory) => {
    o.MapInboundClaims = false;
    o.ConfigurationManager = new ConfigurationManager<OpenIdConnectConfiguration>(opciones.JwksUrl, new JwksEnvuelto(opciones.Issuer), new HttpDocumentRetriever(factory.CreateClient("jwks")) { RequireHttps = new Uri(opciones.JwksUrl).Scheme == "https" });
    o.TokenValidationParameters = new TokenValidationParameters { ValidateIssuerSigningKey = true, RequireSignedTokens = true, ValidateIssuer = true, ValidIssuer = opciones.Issuer, ValidateAudience = true, ValidAudience = opciones.Audience, ValidateLifetime = true, RequireExpirationTime = true, ClockSkew = TimeSpan.Zero, ValidAlgorithms = [SecurityAlgorithms.RsaSha256], NameClaimType = "sub", RoleClaimType = "rol" };
    o.Events = new JwtBearerEvents {
        OnTokenValidated = c => { if (string.IsNullOrWhiteSpace(c.Principal?.FindFirst("sub")?.Value) || c.Principal?.FindFirst("rol")?.Value is not ("ADMIN" or "VENDEDOR" or "COMPRADOR")) c.Fail("Claims inválidos"); return Task.CompletedTask; },
        OnChallenge = async c => { c.HandleResponse(); c.Response.StatusCode = 401; await c.Response.WriteAsJsonAsync(Respuesta.Crear(401, message: "Token ausente o inválido")); },
        OnForbidden = async c => { c.Response.StatusCode = 403; await c.Response.WriteAsJsonAsync(Respuesta.Crear(403, message: "Operación reservada a ADMIN")); }
    };
});
builder.Services.AddAuthorization(o => o.AddPolicy("Admin", p => p.RequireAuthenticatedUser().RequireRole("ADMIN")));
var app = builder.Build();
app.Use(async (ctx, next) => {
    string? supplied = ctx.Request.Headers["X-Correlation-Id"].FirstOrDefault();
    string correlation = supplied is not null && Regex.IsMatch(supplied, "^[A-Za-z0-9-]{1,80}$") ? supplied : Guid.NewGuid().ToString();
    ctx.Items["correlationId"] = correlation; ctx.Response.Headers["X-Correlation-Id"] = correlation; ctx.Response.Headers.CacheControl = "no-store";
    using var scope = app.Logger.BeginScope(new Dictionary<string, object?> { ["servicio"] = "despachos-dotnet", ["correlationId"] = correlation });
    try { await next(); }
    catch (FalloHttp e) { ctx.Response.StatusCode = e.Codigo; await ctx.Response.WriteAsJsonAsync(Respuesta.Crear(e.Codigo, message: e.Message)); }
    catch (Exception e) { app.Logger.LogError("Error {error}", e.GetType().Name); ctx.Response.StatusCode = 500; await ctx.Response.WriteAsJsonAsync(Respuesta.Crear(500, message: "Error interno")); }
});
app.UseStatusCodePages(async c => await c.HttpContext.Response.WriteAsJsonAsync(Respuesta.Crear(c.HttpContext.Response.StatusCode)));
app.UseAuthentication(); app.UseAuthorization();
app.MapGet("/health", () => Results.Json(Respuesta.Crear(200, new { estado = "UP" })));
app.MapGet("/health/dependencias", async (HttpContext c, Dependencias dependencias, CancellationToken ct) => {
    var d = await dependencias.Consultar((string)c.Items["correlationId"]!, ct); bool up = d.All(x => x.Estado == "UP");
    return Results.Json(Respuesta.Crear(up ? 200 : 503, up ? new { dependencias = d } : null, errores: up ? null : new { dependencias = d }), statusCode: up ? 200 : 503);
});
app.MapPost("/despachos/{pedidoId}/reintento", async (string pedidoId, HttpContext c, IRepositorio repo, CancellationToken ct) => {
    if (!Regex.IsMatch(pedidoId, "^PED-[A-Za-z0-9-]{1,60}$")) throw new FalloHttp(400, "pedidoId inválido");
    if (c.Request.ContentLength > 0 || c.Request.Headers.ContainsKey("Transfer-Encoding")) throw new FalloHttp(400, "No se admite body");
    await repo.SolicitarReintento(pedidoId, c.User.FindFirst("sub")!.Value, (string)c.Items["correlationId"]!, ct);
    return Results.Json(Respuesta.Crear(202, new { pedidoId, reintentoSolicitado = true }), statusCode: 202);
}).RequireAuthorization("Admin");
app.Run();
public partial class Program;
