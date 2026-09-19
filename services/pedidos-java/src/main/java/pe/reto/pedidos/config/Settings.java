package pe.reto.pedidos.config;

public record Settings(int port, String mongoUri, String database, String issuer, String audience,
                       long accessSeconds, long refreshSeconds, String privateKey, String publicKey, String internalKey) {
    public Settings {
        if (port < 0 || port > 65535 || accessSeconds < 1 || refreshSeconds < 1 || issuer.isBlank() || audience.isBlank()) throw new IllegalArgumentException("Configuración inválida");
        if (!internalKey.isEmpty() && internalKey.length() < 32) throw new IllegalArgumentException("INTERNAL_API_KEY requiere al menos 32 caracteres");
    }
    private static String env(String key, String fallback) { return System.getenv().getOrDefault(key, fallback); }
    public static Settings load() {
        return new Settings(Integer.parseInt(env("PORT", "8090")), env("MONGODB_URI", "mongodb://localhost:27017/?replicaSet=rs0"), env("MONGODB_DATABASE", "PedidoStockLimitado"), env("JWT_ISSUER", "http://localhost:8090"), env("JWT_AUDIENCE", "pedido-stock-limitado"), Long.parseLong(env("JWT_ACCESS_EXP_SECONDS", "900")), Long.parseLong(env("JWT_REFRESH_EXP_SECONDS", "604800")), env("JWT_PRIVATE_KEY_PATH", "keys/reto-private.pem"), env("JWT_PUBLIC_KEY_PATH", "keys/reto-public.pem"), env("INTERNAL_API_KEY", ""));
    }
}
