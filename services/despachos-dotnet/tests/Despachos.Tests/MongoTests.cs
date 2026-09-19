using System.Diagnostics;
using System.Net;
using System.Net.Sockets;
using Despachos.Application;
using Despachos.Domain;
using Despachos.Infrastructure.Mongo;
using MongoDB.Bson;
using MongoDB.Driver;
using Xunit;
namespace Despachos.Tests;

public sealed class MongoFactAttribute : FactAttribute
{
    public MongoFactAttribute() { if (string.IsNullOrEmpty(Environment.GetEnvironmentVariable("MONGODB_TEST_URI")) && string.IsNullOrEmpty(Environment.GetEnvironmentVariable("MONGODB_TEST_BINARY"))) Skip = "Configurar MONGODB_TEST_URI o MONGODB_TEST_BINARY (MongoDB 7 real)"; }
}
public sealed class MongoFixture : IAsyncLifetime
{
    public IMongoClient Client { get; private set; } = null!;
    public string Uri { get; private set; } = "";
    private Process? process;
    public static string Root
    {
        get { var d = new DirectoryInfo(AppContext.BaseDirectory); while (d is not null && !File.Exists(Path.Combine(d.FullName, "Despachos.slnx"))) d = d.Parent; return d?.FullName ?? throw new InvalidOperationException("Raíz de despachos no encontrada"); }
    }
    public static int Port() { var listener = new TcpListener(IPAddress.Loopback, 0); listener.Start(); int port = ((IPEndPoint)listener.LocalEndpoint).Port; listener.Stop(); return port; }
    public async Task InitializeAsync()
    {
        Uri = Environment.GetEnvironmentVariable("MONGODB_TEST_URI") ?? "";
        if (Uri.Length == 0)
        {
            var binary = Environment.GetEnvironmentVariable("MONGODB_TEST_BINARY"); if (string.IsNullOrEmpty(binary)) return;
            int port = Port(); string dir = Path.Combine(Root, ".build", "mongo-tests", Guid.NewGuid().ToString()); Directory.CreateDirectory(dir);
            var info = new ProcessStartInfo(binary) { UseShellExecute = false, WorkingDirectory = Root };
            foreach (string a in new[] { "--port", port.ToString(), "--bind_ip", "127.0.0.1", "--replSet", "rsDespachos", "--dbpath", dir, "--logpath", Path.Combine(dir, "mongod.log"), "--wiredTigerCacheSizeGB", "0.25" }) info.ArgumentList.Add(a);
            process = Process.Start(info)!;
            var direct = new MongoClient($"mongodb://127.0.0.1:{port}/?directConnection=true&serverSelectionTimeoutMS=30000");
            await direct.GetDatabase("admin").RunCommandAsync<BsonDocument>(new BsonDocument("replSetInitiate", new BsonDocument { { "_id", "rsDespachos" }, { "members", new BsonArray { new BsonDocument { { "_id", 0 }, { "host", $"127.0.0.1:{port}" } } } } }));
            Uri = $"mongodb://127.0.0.1:{port}/?replicaSet=rsDespachos&serverSelectionTimeoutMS=30000";
        }
        Client = new MongoClient(Uri);
        var build = await Client.GetDatabase("admin").RunCommandAsync<BsonDocument>(new BsonDocument("buildInfo", 1));
        if (!build["version"].AsString.StartsWith("7.", StringComparison.Ordinal)) throw new InvalidOperationException("Se requiere MongoDB 7 real");
    }
    public async Task DisposeAsync() { if (process is { HasExited: false }) { process.Kill(); await process.WaitForExitAsync(); process.Dispose(); } }
}
[CollectionDefinition("Mongo real")]
public sealed class MongoCollection : ICollectionFixture<MongoFixture>;

internal sealed class MongoEscenario : IAsyncDisposable
{
    public string Database { get; } = "despachos_it_" + Guid.NewGuid().ToString("N");
    public IMongoDatabase Db { get; }
    public MongoRepositorio Repo { get; }
    public Reloj Clock { get; } = new();
    public Opciones Options { get; }
    private readonly MongoFixture fixture;
    public MongoEscenario(MongoFixture fixture)
    {
        this.fixture = fixture; Options = new Opciones { MongoUri = fixture.Uri, Database = Database };
        Db = fixture.Client.GetDatabase(Database); Repo = new(fixture.Client, Options, Clock);
    }
    public async Task Seed(string id = "PED-1")
    {
        await Repo.Inicializar(default);
        await Db.GetCollection<BsonDocument>("Pedido").InsertOneAsync(Audit(new BsonDocument { { "_id", id }, { "IdSolicitud", "sol-" + id }, { "IdCliente", "CLI-1" }, { "IdUsuarioComprador", "USR-C" }, { "IdAlmacen", "ALM-01" }, { "IdEstado", "RECIBIDO" }, { "EstadoReserva", "NINGUNA" }, { "ZonaEntrega", "PROVINCIA" }, { "HuellaContenido", "fixture" }, { "AnulacionSolicitada", false }, { "CorrelationId", "corr-test" }, { "Subtotal", new Decimal128(20m) }, { "Envio", BsonNull.Value }, { "Total", BsonNull.Value }, { "PesoTotal", new Decimal128(2.5m) } }));
        await Db.GetCollection<BsonDocument>("PedidoDetalle").InsertOneAsync(Audit(new BsonDocument { { "_id", "DET-" + id }, { "IdPedido", id }, { "IdProducto", "SKU-00001" }, { "IdUsuarioVendedor", "USR-V" }, { "Cantidad", 2 }, { "PrecioUnitario", new Decimal128(10m) }, { "PesoUnitario", new Decimal128(1.25m) }, { "Subtotal", new Decimal128(20m) } }));
    }
    public async Task Catalogos()
    {
        await Db.GetCollection<BsonDocument>("Estado").InsertOneAsync(Audit(new BsonDocument { { "_id", "EST-ACTIVO" }, { "Nombre", "ACTIVO" } }));
        await Db.GetCollection<BsonDocument>("Zona").InsertOneAsync(Audit(new BsonDocument { { "_id", "ZON-3" }, { "Codigo", "PROVINCIA" }, { "IdEstado", "EST-ACTIVO" } }));
        await Db.GetCollection<BsonDocument>("ZonaTramo").InsertOneAsync(Audit(new BsonDocument { { "_id", "ZT-1" }, { "IdZona", "ZON-3" }, { "IdEstado", "EST-ACTIVO" }, { "DesdeKg", new Decimal128(0) }, { "HastaKg", new Decimal128(100) }, { "Tarifa", new Decimal128(5.005m) } }));
        await Db.GetCollection<BsonDocument>("Transporte").InsertOneAsync(Audit(new BsonDocument { { "_id", "TRA-1" }, { "IdEstado", "ACTIVO" } }));
    }
    public BsonDocument Audit(BsonDocument d) { d["UsuarioCreacion"] = "TEST"; d["FechaCreacion"] = Clock.GetUtcNow().UtcDateTime; d["UsuarioModificacion"] = BsonNull.Value; d["FechaModificacion"] = BsonNull.Value; return d; }
    public Task Update(string collection, string id, params (string Field, BsonValue Value)[] fields) => Db.GetCollection<BsonDocument>(collection).UpdateOneAsync(Builders<BsonDocument>.Filter.Eq("_id", id), Builders<BsonDocument>.Update.Combine(fields.Select(f => Builders<BsonDocument>.Update.Set(f.Field, f.Value))));
    public Task<BsonDocument> Doc(string collection, string id) => Db.GetCollection<BsonDocument>(collection).Find(Builders<BsonDocument>.Filter.Eq("_id", id)).FirstAsync();
    public ValueTask DisposeAsync() => new(fixture.Client.DropDatabaseAsync(Database));
}
[Collection("Mongo real")]
[Trait("Categoria", "MongoReal")]
public sealed class MongoTests(MongoFixture fixture)
{
    [MongoFact] public async Task ReclamoAtomicoUnaCorridaYSoloUnPedidoAsignado()
    {
        await using var s = new MongoEscenario(fixture); await s.Seed(); await s.Seed("PED-2");
        var runs = await Task.WhenAll(Enumerable.Range(0, 8).Select(i => s.Repo.Adquirir("owner-" + i, default)));
        var run = Assert.Single(runs, r => r is not null)!;
        var p = await s.Repo.Tomar(run, default); Assert.NotNull(p); Assert.Equal(1, p.Intento);
        var other = await s.Doc("Pedido", p.Id == "PED-1" ? "PED-2" : "PED-1"); Assert.False(other.Contains("IdWorker"));
        Assert.Equal("TEST", (await s.Doc("Pedido", p.Id))["UsuarioCreacion"]); Assert.Equal("despachos-dotnet", (await s.Doc("Pedido", p.Id))["UsuarioModificacion"]);
    }
    [MongoFact] public async Task ReinicioRetomaSoloIncompletoYCierraCorridaAnterior()
    {
        await using var s = new MongoEscenario(fixture); await s.Seed(); await s.Seed("PED-2");
        var w1 = (await s.Repo.Adquirir("antes", default))!; var p1 = (await s.Repo.Tomar(w1, default))!;
        Assert.Null(await s.Repo.Adquirir("otro-vivo", default));
        s.Clock.Ahora = s.Clock.Ahora.AddSeconds(31);
        var recovered = (await s.Repo.Adquirir("reinicio", default))!; Assert.True(recovered.Recuperada); Assert.Equal(w1.Id, recovered.Id);
        var resumed = (await s.Repo.Tomar(recovered, default))!; Assert.Equal(p1.Id, resumed.Id); Assert.Equal(2, resumed.Intento); Assert.Equal(p1.Inicio, resumed.Inicio);
        await Assert.ThrowsAsync<LeasePerdidoException>(() => s.Repo.Verificar(w1, default));
        await s.Repo.Finalizar(recovered, resumed.Id, EstadoPedido.ANULADO, "sin efectos", default); await s.Repo.Cerrar(recovered, default);
        var w2 = (await s.Repo.Adquirir("siguiente", default))!; Assert.NotEqual(w1.Id, w2.Id); Assert.False(w2.Recuperada);
        var p2 = (await s.Repo.Tomar(w2, default))!; Assert.NotEqual(p1.Id, p2.Id); Assert.Equal(1, p2.Intento);
    }
    [MongoFact] public async Task CamposJavaYDineroDecimal128Compatibles()
    {
        await using var s = new MongoEscenario(fixture); await s.Seed(); await s.Catalogos(); var w = (await s.Repo.Adquirir("x", default))!; var p = (await s.Repo.Tomar(w, default))!;
        var i = Reglas.Calcular(p.Lineas, await s.Repo.Tarifas(p.Zona, default), p.Zona); await s.Repo.GuardarEnvio(w, p.Id, i, default);
        var d = await s.Doc("Pedido", p.Id); Assert.True(d["Envio"].IsDecimal128); Assert.Equal(5.01m, Decimal128.ToDecimal(d["Envio"].AsDecimal128)); Assert.Equal(25.01m, Decimal128.ToDecimal(d["Total"].AsDecimal128));
        Assert.False(d.Contains("CostoEnvio")); Assert.False(d.Contains("TotalPeso")); Assert.Equal("TRA-1", await s.Repo.Transporte(default));
    }
    [MongoFact] public async Task GuiaUnicaEIdempotente()
    {
        await using var s = new MongoEscenario(fixture); await s.Seed(); var w = (await s.Repo.Adquirir("x", default))!; await s.Repo.Tomar(w, default);
        await s.Repo.GuardarGuia(w, "PED-1", "G-1", "TRA-1", default); await s.Repo.GuardarGuia(w, "PED-1", "G-1", "TRA-1", default);
        Assert.Equal(1, await s.Db.GetCollection<BsonDocument>("Guia").CountDocumentsAsync(new BsonDocument()));
        await Assert.ThrowsAsync<MongoWriteException>(() => s.Db.GetCollection<BsonDocument>("Guia").InsertOneAsync(new BsonDocument { { "_id", "otro" }, { "IdPedido", "PED-1" } }));
        await Assert.ThrowsAsync<FalloProceso>(() => s.Repo.GuardarGuia(w, "PED-1", "G-2", "TRA-1", default));
    }
    [MongoFact] public async Task TrazaStockJavaSeActualizaSinDuplicar()
    {
        await using var s = new MongoEscenario(fixture); await s.Seed(); var w = (await s.Repo.Adquirir("x", default))!; await s.Repo.Tomar(w, default);
        var attempt = await s.Repo.IniciarPaso(w, "PED-1", Paso.RESERVAR_STOCK, default);
        await s.Db.GetCollection<BsonDocument>("PedidoProceso").InsertOneAsync(s.Audit(new BsonDocument { { "_id", "PRC-JAVA" }, { "IdPedidoProceso", "PRC-JAVA" }, { "IdPedido", "PED-1" }, { "Paso", "STOCK_RESERVAR" }, { "TipoProceso", "PROCESO" }, { "NroIntento", 1 }, { "IdEstadoProceso", "COMPLETADO" }, { "FechaInicio", DateTime.UtcNow }, { "FechaFin", DateTime.UtcNow }, { "Log", "Stock actualizado" } }));
        await s.Repo.TerminarPaso(w, "PED-1", attempt, true, "OK", default);
        var d = await s.Doc("PedidoProceso", "PRC-JAVA"); Assert.Equal("RESERVAR_STOCK", d["Paso"]); Assert.Equal("OK", d["IdEstadoProceso"]); Assert.False(d.Contains("ms"));
        Assert.Equal(1, await s.Db.GetCollection<BsonDocument>("PedidoProceso").CountDocumentsAsync(new BsonDocument()));
    }
    [MongoFact] public async Task LimitePersistidoNoSeReseteaConReinicioYAdminHabilita()
    {
        await using var s = new MongoEscenario(fixture); await s.Seed(); var w = (await s.Repo.Adquirir("x", default))!; await s.Repo.Tomar(w, default);
        for (int i = 0; i < 3; i++) { var a = await s.Repo.IniciarPaso(w, "PED-1", Paso.GENERAR_GUIA, default); await s.Repo.TerminarPaso(w, "PED-1", a, false, "TIMEOUT", default); }
        await Assert.ThrowsAsync<FalloProceso>(() => s.Repo.IniciarPaso(w, "PED-1", Paso.GENERAR_GUIA, default));
        await s.Repo.CambiarEstado(w, "PED-1", EstadoPedido.REQUIERE_REVISION, "limite", Paso.GENERAR_GUIA, default); await s.Repo.Cerrar(w, default);
        Assert.Null(await s.Repo.Adquirir("x", default)); await s.Repo.SolicitarReintento("PED-1", "USR-ADMIN", "corr-admin", default);
        Assert.Equal("USR-ADMIN", (await s.Doc("Pedido", "PED-1"))["UsuarioModificacion"]);
        var next = (await s.Repo.Adquirir("x", default))!; var p = (await s.Repo.Tomar(next, default))!; Assert.Equal(Paso.GENERAR_GUIA, p.Pendiente); Assert.Equal(2, p.Intento);
        var intento = await s.Repo.IniciarPaso(next, "PED-1", Paso.GENERAR_GUIA, default); Assert.Equal(4, intento.Numero); Assert.Equal(1, intento.Ciclo);
    }
    [MongoFact] public async Task CasImpideDespachadoConAnulacionYAnuladoConReserva()
    {
        await using var s = new MongoEscenario(fixture); await s.Seed(); var w = (await s.Repo.Adquirir("x", default))!; await s.Repo.Tomar(w, default);
        await s.Repo.GuardarGuia(w, "PED-1", "G-1", "TRA-1", default); await s.Repo.GuardarEnvio(w, "PED-1", new(2.5m, 20, 5, 25), default);
        await s.Update("Pedido", "PED-1", ("EstadoReserva", "CONFIRMADA"), ("AnulacionSolicitada", true));
        Assert.False(await s.Repo.Finalizar(w, "PED-1", EstadoPedido.DESPACHADO, "fin", default)); Assert.False(await s.Repo.Finalizar(w, "PED-1", EstadoPedido.ANULADO, "fin", default));
    }
}
