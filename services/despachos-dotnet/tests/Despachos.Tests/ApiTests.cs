using System.Net;
using System.Net.Http.Headers;
using System.Security.Cryptography;
using System.Text.Json;
using Despachos.Application;
using Despachos.Api.Workers;
using Despachos.Domain;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.AspNetCore.TestHost;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.DependencyInjection.Extensions;
using Microsoft.Extensions.Hosting;
using Microsoft.IdentityModel.JsonWebTokens;
using Microsoft.IdentityModel.Tokens;
using Xunit;
namespace Despachos.Tests;

internal sealed class ApiFactory : WebApplicationFactory<Program>
{
    public Memoria Repo { get; } = new();
    public RSA Rsa { get; } = RSA.Create(2048);
    public bool HttpCaido { get; set; }
    public List<string> Correlations { get; } = [];
    protected override void ConfigureWebHost(IWebHostBuilder builder)
    {
        builder.ConfigureTestServices(s => {
            foreach (var d in s.Where(d => d.ServiceType == typeof(IHostedService) && d.ImplementationType == typeof(DespachoWorker)).ToList()) s.Remove(d);
            s.RemoveAll<IRepositorio>(); s.AddSingleton<IRepositorio>(Repo);
            s.RemoveAll<IHttpClientFactory>(); s.AddSingleton<IHttpClientFactory>(new Factory(this));
        });
    }
    private sealed class Factory(ApiFactory owner) : IHttpClientFactory
    {
        public HttpClient CreateClient(string name) => new(new Handler((r, _) => {
            if (r.Headers.TryGetValues("X-Correlation-Id", out var c)) owner.Correlations.Add(c.Single());
            if (r.RequestUri!.AbsolutePath.EndsWith("jwks.json"))
            {
                var p = owner.Rsa.ExportParameters(false);
                return Task.FromResult(Handler.Json(HttpStatusCode.OK, new { code = 200, statusCode = "HTTP_200_OK", message = "OK", data = new { keys = new[] { new { kty = "RSA", alg = "RS256", use = "sig", kid = "test-kid", n = Base64UrlEncoder.Encode(p.Modulus!), e = Base64UrlEncoder.Encode(p.Exponent!) } } } }));
            }
            return Task.FromResult(new HttpResponseMessage(owner.HttpCaido ? HttpStatusCode.ServiceUnavailable : HttpStatusCode.OK));
        })) { BaseAddress = new Uri("http://fake"), Timeout = TimeSpan.FromSeconds(5) };
    }
    public string Token(string rol = "ADMIN", bool expired = false, string audience = "pedido-stock-limitado", bool badSignature = false, string issuer = "http://localhost:8090")
    {
        using var wrong = RSA.Create(2048);
        var key = new RsaSecurityKey(badSignature ? wrong : Rsa) { KeyId = "test-kid" };
        return new JsonWebTokenHandler().CreateToken(new SecurityTokenDescriptor { Issuer = issuer, Audience = audience, Claims = new Dictionary<string, object> { ["sub"] = "USR-ADMIN", ["rol"] = rol }, IssuedAt = DateTime.UtcNow.AddMinutes(-20), NotBefore = DateTime.UtcNow.AddMinutes(-20), Expires = expired ? DateTime.UtcNow.AddSeconds(-1) : DateTime.UtcNow.AddMinutes(5), SigningCredentials = new SigningCredentials(key, SecurityAlgorithms.RsaSha256) });
    }
    protected override void Dispose(bool disposing) { base.Dispose(disposing); if (disposing) Rsa.Dispose(); }
}
public sealed class ApiTests
{
    [Fact] public async Task HealthSinDependenciasYPropagaCorrelation()
    {
        using var f = new ApiFactory(); using var c = f.CreateClient(); c.DefaultRequestHeaders.Add("X-Correlation-Id", "corr-api-123");
        var r = await c.GetAsync("/health"); Assert.Equal(HttpStatusCode.OK, r.StatusCode); Assert.Equal(0, f.Repo.Pings); Assert.Equal("corr-api-123", r.Headers.GetValues("X-Correlation-Id").Single());
        r = await c.GetAsync("/health/dependencias"); Assert.Equal(HttpStatusCode.OK, r.StatusCode); Assert.Equal(1, f.Repo.Pings); Assert.All(f.Correlations, x => Assert.Equal("corr-api-123", x));
    }
    [Fact] public async Task DependenciasCaidasDevuelven503EnSobre()
    {
        using var f = new ApiFactory { HttpCaido = true }; f.Repo.FallarPing = true; using var c = f.CreateClient();
        var r = await c.GetAsync("/health/dependencias"); Assert.Equal(HttpStatusCode.ServiceUnavailable, r.StatusCode);
        using var j = JsonDocument.Parse(await r.Content.ReadAsStringAsync()); Assert.Equal(JsonValueKind.Null, j.RootElement.GetProperty("data").ValueKind); Assert.Equal(3, j.RootElement.GetProperty("errores").GetProperty("dependencias").GetArrayLength());
    }
    [Theory][InlineData("ausente")][InlineData("expirado")][InlineData("firma")][InlineData("aud")][InlineData("iss")]
    public async Task TokenInvalido401(string caso)
    {
        using var f = new ApiFactory(); using var c = f.CreateClient();
        if (caso != "ausente") c.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue("Bearer", f.Token(expired: caso == "expirado", audience: caso == "aud" ? "otra" : "pedido-stock-limitado", badSignature: caso == "firma", issuer: caso == "iss" ? "otro" : "http://localhost:8090"));
        c.DefaultRequestHeaders.Add("X-User-Id", "USR-ADMIN"); c.DefaultRequestHeaders.Add("X-Role", "ADMIN");
        var r = await c.PostAsync("/despachos/PED-1/reintento", null); Assert.Equal(HttpStatusCode.Unauthorized, r.StatusCode);
        using var j = JsonDocument.Parse(await r.Content.ReadAsStringAsync()); Assert.Equal(401, j.RootElement.GetProperty("code").GetInt32());
    }
    [Theory][InlineData("COMPRADOR")][InlineData("VENDEDOR")]
    public async Task ReintentoSoloAdmin(string rol)
    {
        using var f = new ApiFactory(); using var c = f.CreateClient(); c.DefaultRequestHeaders.Authorization = new("Bearer", f.Token(rol));
        Assert.Equal(HttpStatusCode.Forbidden, (await c.PostAsync("/despachos/PED-1/reintento", null)).StatusCode);
    }
    [Fact] public async Task AdminValidaJwksEnvueltoYAuditaDesdeSub()
    {
        using var f = new ApiFactory(); f.Repo.Pedido = f.Repo.Pedido with { Estado = EstadoPedido.REQUIERE_REVISION }; using var c = f.CreateClient(); c.DefaultRequestHeaders.Authorization = new("Bearer", f.Token());
        Assert.Equal(HttpStatusCode.Accepted, (await c.PostAsync("/despachos/PED-1/reintento", null)).StatusCode); Assert.Equal("USR-ADMIN", f.Repo.Auditor);
        Assert.Equal(HttpStatusCode.Conflict, (await c.PostAsync("/despachos/PED-1/reintento", null)).StatusCode);
        Assert.Equal(HttpStatusCode.NotFound, (await c.PostAsync("/despachos/PED-999/reintento", null)).StatusCode);
        Assert.Equal(HttpStatusCode.BadRequest, (await c.PostAsync("/despachos/PED-1/reintento", new StringContent("{\"usuario\":\"otro\"}"))).StatusCode);
    }
}
