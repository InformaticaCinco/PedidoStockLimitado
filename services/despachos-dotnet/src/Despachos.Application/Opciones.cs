namespace Despachos.Application;

public sealed record Opciones
{
    public string MongoUri { get; init; } = "mongodb://localhost:27017/?replicaSet=rs0";
    public string Database { get; init; } = "PedidoStockLimitado";
    public string PedidosUrl { get; init; } = "http://localhost:8090";
    public string InternalKey { get; init; } = "";
    public string TransportistaUrl { get; init; } = "http://localhost:9090";
    public string JwksUrl { get; init; } = "http://localhost:8090/.well-known/jwks.json";
    public string Issuer { get; init; } = "http://localhost:8090";
    public string Audience { get; init; } = "pedido-stock-limitado";
    public int PollMs { get; init; } = 1000;
    public int MaxAttempts { get; init; } = 3;
    public int BaseDelayMs { get; init; } = 500;
    public int ProcessTimeoutSeconds { get; init; } = 120;
    public int HttpTimeoutSeconds { get; init; } = 5;
    public int LeaseSeconds { get; init; } = 30;
    public static Opciones Leer()
    {
        string Env(string k, string d) => Environment.GetEnvironmentVariable(k) ?? d;
        int Num(string k, int d) => int.Parse(Env(k, d.ToString(System.Globalization.CultureInfo.InvariantCulture)), System.Globalization.CultureInfo.InvariantCulture);
        var o = new Opciones {
            MongoUri = Env("MONGODB_URI", "mongodb://localhost:27017/?replicaSet=rs0"), Database = Env("MONGODB_DATABASE", "PedidoStockLimitado"),
            PedidosUrl = Env("PEDIDOS_BASE_URL", "http://localhost:8090"), InternalKey = Env("PEDIDOS_INTERNAL_KEY", ""),
            TransportistaUrl = Env("TRANSPORTISTA_BASE_URL", "http://localhost:9090"),
            JwksUrl = Env("JWT_JWKS_URL", Env("PEDIDOS_BASE_URL", "http://localhost:8090").TrimEnd('/') + "/.well-known/jwks.json"),
            Issuer = Env("JWT_ISSUER", "http://localhost:8090"), Audience = Env("JWT_AUDIENCE", "pedido-stock-limitado"),
            PollMs = Num("WORKER_POLL_MS", 1000), MaxAttempts = Num("RETRY_MAX_ATTEMPTS", 3), BaseDelayMs = Num("RETRY_BASE_DELAY_MS", 500),
            ProcessTimeoutSeconds = Num("PROCESS_TIMEOUT_SECONDS", 120), HttpTimeoutSeconds = Num("HTTP_TIMEOUT_SECONDS", 5), LeaseSeconds = Num("WORKER_LEASE_SECONDS", 30)
        };
        if (o.PollMs < 10 || o.MaxAttempts is < 1 or > 20 || o.BaseDelayMs < 0 || o.ProcessTimeoutSeconds < 1 || o.HttpTimeoutSeconds < 1 || o.LeaseSeconds < o.HttpTimeoutSeconds * 3 || o.Issuer.Length == 0 || o.Audience.Length == 0)
            throw new InvalidOperationException("Configuración inválida");
        foreach (string u in new[] { o.PedidosUrl, o.TransportistaUrl, o.JwksUrl })
            if (!Uri.TryCreate(u, UriKind.Absolute, out var uri) || uri.Scheme is not ("http" or "https") || !string.IsNullOrEmpty(uri.UserInfo)) throw new InvalidOperationException("URL inválida");
        return o;
    }
}
