using System.Text.Json;
using Microsoft.IdentityModel.Protocols;
using Microsoft.IdentityModel.Protocols.OpenIdConnect;
using Microsoft.IdentityModel.Tokens;
namespace Despachos.Api.Security;

/// <summary>Java wraps its JWKSet in data. No OpenID discovery or Java auth call is used.</summary>
public sealed class JwksEnvuelto(string issuer) : IConfigurationRetriever<OpenIdConnectConfiguration>
{
    public async Task<OpenIdConnectConfiguration> GetConfigurationAsync(string address, IDocumentRetriever retriever, CancellationToken cancel)
    {
        string body = await retriever.GetDocumentAsync(address, cancel);
        using var doc = JsonDocument.Parse(body);
        if (doc.RootElement.GetProperty("code").GetInt32() != 200) throw new InvalidOperationException("JWKS inválido");
        var data = doc.RootElement.GetProperty("data");
        if (data.GetProperty("keys").ValueKind != JsonValueKind.Array) throw new InvalidOperationException("JWKS inválido");
        var set = new JsonWebKeySet(data.GetRawText());
        var config = new OpenIdConnectConfiguration { Issuer = issuer };
        foreach (var key in set.Keys)
            if (key.Kty == "RSA" && key.Alg == "RS256" && key.Use == "sig" && !string.IsNullOrEmpty(key.Kid) && !key.HasPrivateKey)
                config.SigningKeys.Add(key);
        if (config.SigningKeys.Count == 0) throw new InvalidOperationException("JWKS sin claves RS256 públicas");
        return config;
    }
}
