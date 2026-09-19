using Despachos.Application;
using Despachos.Domain;
using MongoDB.Bson;
using MongoDB.Driver;
namespace Despachos.Infrastructure.Mongo;

public sealed class MongoRepositorio : IRepositorio
{
    private readonly IMongoClient client;
    private readonly IMongoDatabase db;
    private readonly Opciones options;
    private readonly TimeProvider clock;
    private static readonly FilterDefinitionBuilder<BsonDocument> F = Builders<BsonDocument>.Filter;
    private static readonly UpdateDefinitionBuilder<BsonDocument> U = Builders<BsonDocument>.Update;
    private const string Tecnico = "despachos-dotnet";
    public MongoRepositorio(IMongoClient client, Opciones options, TimeProvider clock)
    {
        this.client = client; this.options = options; this.clock = clock;
        db = client.GetDatabase(options.Database).WithReadConcern(ReadConcern.Majority).WithWriteConcern(WriteConcern.WMajority).WithReadPreference(ReadPreference.Primary);
    }
    private IMongoCollection<BsonDocument> C(string collection) => db.GetCollection<BsonDocument>(collection);
    private DateTime Now => clock.GetUtcNow().UtcDateTime;
    private static string Str(BsonDocument d, string key, string fallback = "") => d.TryGetValue(key, out var value) && !value.IsBsonNull ? value.AsString : fallback;
    private static DateTime? Date(BsonDocument d, string key) => d.TryGetValue(key, out var v) && v.IsBsonDateTime ? v.ToUniversalTime() : null;
    private static decimal Dec(BsonDocument d, string key) => Decimal128.ToDecimal(d[key].AsDecimal128);
    private static int Int(BsonDocument d, string key) => d.TryGetValue(key, out var v) ? v.ToInt32() : 0;
    private static bool Bool(BsonDocument d, string key) => d.GetValue(key, false).ToBoolean();
    private BsonDocument Audit(BsonDocument d, string who = Tecnico)
    { d["UsuarioCreacion"] = who; d["FechaCreacion"] = Now; d["UsuarioModificacion"] = BsonNull.Value; d["FechaModificacion"] = BsonNull.Value; return d; }
    private UpdateDefinition<BsonDocument> Mod(string who = Tecnico) => U.Set("UsuarioModificacion", who).Set("FechaModificacion", Now);
    private async Task<T> Tx<T>(Func<IClientSessionHandle, CancellationToken, Task<T>> work, CancellationToken ct)
    {
        using var session = await client.StartSessionAsync(cancellationToken: ct);
        return await session.WithTransactionAsync(work, new TransactionOptions(ReadConcern.Snapshot, ReadPreference.Primary, WriteConcern.WMajority), ct);
    }
    public async Task Inicializar(CancellationToken ct)
    {
        await C("Worker").Indexes.CreateOneAsync(new CreateIndexModel<BsonDocument>(Builders<BsonDocument>.IndexKeys.Ascending("Nombre"),
            new CreateIndexOptions<BsonDocument> { Unique = true, PartialFilterExpression = F.Eq("FechaFin", BsonNull.Value), Name = "una_corrida_abierta" }), cancellationToken: ct);
        await C("Pedido").Indexes.CreateManyAsync(new[] {
            new CreateIndexModel<BsonDocument>(Builders<BsonDocument>.IndexKeys.Ascending("IdEstado").Ascending("ReintentoSolicitado").Ascending("FechaCreacion")),
            new CreateIndexModel<BsonDocument>(Builders<BsonDocument>.IndexKeys.Ascending("IdWorker").Ascending("FechaFinProceso")) }, ct);
        await C("Guia").Indexes.CreateOneAsync(new CreateIndexModel<BsonDocument>(Builders<BsonDocument>.IndexKeys.Ascending("IdPedido"), new CreateIndexOptions { Unique = true }), cancellationToken: ct);
        await C("PedidoProceso").Indexes.CreateOneAsync(new CreateIndexModel<BsonDocument>(Builders<BsonDocument>.IndexKeys.Ascending("IdPedido").Ascending("Paso").Ascending("NroIntento")), cancellationToken: ct);
        await C("ZonaTramo").Indexes.CreateOneAsync(new CreateIndexModel<BsonDocument>(Builders<BsonDocument>.IndexKeys.Ascending("IdZona").Ascending("IdEstado").Ascending("DesdeKg").Ascending("HastaKg")), cancellationToken: ct);
    }
    private FilterDefinition<BsonDocument> Abierta => F.Eq("Nombre", Tecnico) & F.Eq("FechaFin", BsonNull.Value);
    private FilterDefinition<BsonDocument> Elegibles => (F.Eq("IdEstado", "RECIBIDO") & F.Eq("IdWorker", BsonNull.Value)) |
        (F.Eq("IdEstado", "REQUIERE_REVISION") & F.Eq("ReintentoSolicitado", true));
    private FilterDefinition<BsonDocument> Lease(Corrida r) => F.Eq("_id", r.Id) & Abierta & F.Eq("LeaseOwner", r.Propietario) & F.Eq("LeaseVersion", r.Version) & F.Gt("LeaseHeartbeat", Now.AddSeconds(-options.LeaseSeconds));
    public async Task<Corrida?> Adquirir(string propietario, CancellationToken ct)
    {
        var abierta = await C("Worker").Find(Abierta).FirstOrDefaultAsync(ct);
        if (abierta is not null)
        {
            var d = await C("Worker").FindOneAndUpdateAsync(Abierta & F.Eq("_id", abierta["_id"]) & (F.Lte("LeaseHeartbeat", Now.AddSeconds(-options.LeaseSeconds)) | F.Exists("LeaseHeartbeat", false)),
                U.Set("LeaseOwner", propietario).Set("LeaseHeartbeat", Now).Inc("LeaseVersion", 1L).Inc("Intentos", 1).Combine(Mod()),
                new FindOneAndUpdateOptions<BsonDocument> { ReturnDocument = ReturnDocument.After }, ct);
            return d is null ? null : new Corrida(d["_id"].AsString, propietario, d["LeaseVersion"].ToInt64(), true);
        }
        if (!await C("Pedido").Find(Elegibles).AnyAsync(ct)) return null;
        string id = "WRK-" + Guid.NewGuid();
        try
        {
            await C("Worker").InsertOneAsync(Audit(new BsonDocument { { "_id", id }, { "IdWorker", id }, { "Nombre", Tecnico }, { "FechaInicio", Now }, { "FechaFin", BsonNull.Value }, { "Intentos", 1 }, { "LeaseOwner", propietario }, { "LeaseVersion", 1L }, { "LeaseHeartbeat", Now } }), cancellationToken: ct);
            return new Corrida(id, propietario, 1, false);
        }
        catch (MongoWriteException e) when (e.WriteError.Category == ServerErrorCategory.DuplicateKey) { return null; }
    }
    public async Task<bool> Renovar(Corrida r, CancellationToken ct) => (await C("Worker").UpdateOneAsync(Lease(r), U.Set("LeaseHeartbeat", Now).Combine(Mod()), cancellationToken: ct)).MatchedCount == 1;
    public async Task Verificar(Corrida r, CancellationToken ct) { if (!await C("Worker").Find(Lease(r)).AnyAsync(ct)) throw new LeasePerdidoException(); }
    private async Task Fence(IClientSessionHandle s, Corrida r, CancellationToken ct)
    {
        // A write to the lease inside each transaction fences stale owners, not just a stale snapshot read.
        if ((await C("Worker").UpdateOneAsync(s, Lease(r), U.Inc("Secuencia", 1L).Combine(Mod()), cancellationToken: ct)).MatchedCount != 1) throw new LeasePerdidoException();
    }
    public Task<Pedido?> Tomar(Corrida r, CancellationToken ct) => Tx<Pedido?>(async (s, token) => {
        await Fence(s, r, token);
        var filtro = r.Recuperada ? F.Eq("IdWorker", r.Id) & F.Eq("FechaFinProceso", BsonNull.Value) & F.In("IdEstado", new[] { "EN_PROCESO", "COMPENSANDO" }) : Elegibles;
        var d = await C("Pedido").Find(s, filtro).Sort(Builders<BsonDocument>.Sort.Ascending("FechaCreacion")).FirstOrDefaultAsync(token);
        if (d is null) return null;
        string estado = r.Recuperada ? d["IdEstado"].AsString : Bool(d, "CompensacionPendiente") ? "COMPENSANDO" : "EN_PROCESO";
        if (!r.Recuperada) Reglas.Transicion(Enum.Parse<EstadoPedido>(d["IdEstado"].AsString), Enum.Parse<EstadoPedido>(estado));
        var update = U.Set("IdWorker", r.Id).Set("IdEstado", estado).Set("FechaFinProceso", BsonNull.Value).Set("ReintentoSolicitado", false).Inc("IntentoProceso", 1).Combine(Mod());
        if (!r.Recuperada) update = update.Set("FechaInicioProceso", Now);
        if (!d.Contains("CorrelationId")) update = update.Set("CorrelationId", Guid.NewGuid().ToString());
        d = await C("Pedido").FindOneAndUpdateAsync(s, F.Eq("_id", d["_id"]) & filtro, update, new FindOneAndUpdateOptions<BsonDocument> { ReturnDocument = ReturnDocument.After }, token);
        if (d is null) return null;
        // Reuse Java records in-place, including effects completed before a coordinator crash.
        await SincronizarJava(s, d["_id"].AsString, token);
        return await Map(s, d, token);
    }, ct);
    private async Task SincronizarJava(IClientSessionHandle s, string id, CancellationToken ct)
    {
        foreach (var (alias, paso) in new[] { ("STOCK_RESERVAR", Paso.RESERVAR_STOCK), ("STOCK_LIBERAR", Paso.LIBERAR_STOCK), ("STOCK_CONFIRMAR", Paso.CONFIRMAR_DESPACHO) })
        {
            var docs = await C("PedidoProceso").Find(s, F.Eq("IdPedido", id) & F.Eq("Paso", alias)).ToListAsync(ct);
            foreach (var d in docs)
                await C("PedidoProceso").UpdateOneAsync(s, F.Eq("_id", d["_id"]), U.Set("Paso", paso.ToString()).Set("IdEstadoProceso", Str(d, "IdEstadoProceso") == "COMPLETADO" ? "OK" : Str(d, "IdEstadoProceso")).Combine(Mod()), cancellationToken: ct);
        }
    }
    public Task Cerrar(Corrida r, CancellationToken ct) => Tx(async (s, token) => {
        await Fence(s, r, token);
        if (await C("Pedido").Find(s, F.Eq("IdWorker", r.Id) & F.Eq("FechaFinProceso", BsonNull.Value)).AnyAsync(token)) throw new FalloProceso("CORRIDA_CON_PEDIDO_INCOMPLETO", false);
        await C("Worker").UpdateOneAsync(s, Lease(r), U.Set("FechaFin", Now).Combine(Mod()), cancellationToken: token); return true;
    }, ct);
    private async Task<Pedido> Map(IClientSessionHandle? s, BsonDocument d, CancellationToken ct)
    {
        var filtro = F.Eq("IdPedido", d["_id"]);
        var detalles = s is null ? await C("PedidoDetalle").Find(filtro).ToListAsync(ct) : await C("PedidoDetalle").Find(s, filtro).ToListAsync(ct);
        var lineas = detalles.Select(l => new Linea(Str(l, "IdProducto"), Int(l, "Cantidad"), Dec(l, "PrecioUnitario"), Dec(l, "PesoUnitario"), Dec(l, "Subtotal"))).ToArray();
        var pendiente = Str(d, "PasoPendiente");
        return new Pedido(d["_id"].AsString, Enum.Parse<EstadoPedido>(Str(d, "IdEstado")), Enum.Parse<EstadoReserva>(Str(d, "EstadoReserva", "NINGUNA")), Str(d, "ZonaEntrega"), Str(d, "IdWorker"), Date(d, "FechaInicioProceso"), Date(d, "FechaFinProceso"), Int(d, "IntentoProceso"), Bool(d, "AnulacionSolicitada"), Str(d, "CorrelationId", Guid.NewGuid().ToString()), d.GetValue("Envio", BsonNull.Value).IsBsonNull ? null : Dec(d, "Envio"), pendiente.Length == 0 ? null : Enum.Parse<Paso>(pendiente), Bool(d, "GuiaIntentada"), Bool(d, "ReintentoSolicitado"), Bool(d, "CompensacionPendiente"), lineas);
    }
    public async Task<Pedido> Obtener(string id, CancellationToken ct)
    {
        var d = await C("Pedido").Find(F.Eq("_id", id)).FirstOrDefaultAsync(ct) ?? throw new FalloHttp(404, "Pedido no encontrado");
        return await Map(null, d, ct);
    }
    public async Task<Guia?> ObtenerGuia(string id, CancellationToken ct)
    {
        var d = await C("Guia").Find(F.Eq("IdPedido", id)).FirstOrDefaultAsync(ct);
        return d is null ? null : new Guia(d["_id"].AsString, id, Str(d, "Numero"), Str(d, "IdTransporte"), Str(d, "IdEstado") == "ANULADO");
    }
    private async Task<string[]> Activos(CancellationToken ct)
    {
        var catalogo = await C("Estado").Find(F.Eq("Nombre", "ACTIVO")).ToListAsync(ct);
        return catalogo.Select(d => d["_id"].AsString).Append("ACTIVO").Distinct().ToArray();
    }
    public async Task<IReadOnlyList<Tarifa>> Tarifas(string zona, CancellationToken ct)
    {
        var activos = await Activos(ct);
        var zonas = await C("Zona").Find((F.Eq("_id", zona) | F.Eq("Codigo", zona)) & F.In("IdEstado", activos)).ToListAsync(ct);
        if (zonas.Count != 1) throw new FalloProceso("ZONA_AUSENTE_O_AMBIGUA", false);
        var docs = await C("ZonaTramo").Find(F.Eq("IdZona", zonas[0]["_id"]) & F.In("IdEstado", activos)).ToListAsync(ct);
        return docs.Select(d => new Tarifa(zona, Dec(d, "DesdeKg"), Dec(d, "HastaKg"), Dec(d, "Tarifa"))).ToArray();
    }
    public async Task<string> Transporte(CancellationToken ct)
    {
        var docs = await C("Transporte").Find(F.In("IdEstado", await Activos(ct))).Limit(2).ToListAsync(ct);
        if (docs.Count != 1) throw new FalloProceso("TRANSPORTE_AUSENTE_O_AMBIGUO", false);
        return docs[0]["_id"].AsString;
    }
    private Task Mutar(Corrida r, string id, UpdateDefinition<BsonDocument> update, CancellationToken ct) => Tx(async (s, token) => {
        await Fence(s, r, token);
        var result = await C("Pedido").UpdateOneAsync(s, F.Eq("_id", id) & F.Eq("IdWorker", r.Id) & F.Eq("FechaFinProceso", BsonNull.Value), update.Combine(Mod()), cancellationToken: token);
        if (result.MatchedCount != 1) throw new LeasePerdidoException(); return true;
    }, ct);
    public Task GuardarEnvio(Corrida r, string id, Importes i, CancellationToken ct) => Mutar(r, id, U.Set("PesoTotal", new Decimal128(i.Peso)).Set("Subtotal", new Decimal128(i.Subtotal)).Set("Envio", new Decimal128(i.Envio)).Set("Total", new Decimal128(i.Total)), ct);
    public Task MarcarGuiaIntentada(Corrida r, string id, CancellationToken ct) => Mutar(r, id, U.Set("GuiaIntentada", true), ct);
    public Task GuardarGuia(Corrida r, string id, string numero, string transporte, CancellationToken ct) => Tx(async (s, token) => {
        await Fence(s, r, token);
        var existente = await C("Guia").Find(s, F.Eq("IdPedido", id)).FirstOrDefaultAsync(token);
        if (existente is not null) { if (Str(existente, "Numero") != numero) throw new FalloProceso("GUIAS_INCONSISTENTES", false); return true; }
        string guiaId = "GUI-" + Guid.NewGuid();
        await C("Guia").InsertOneAsync(s, Audit(new BsonDocument { { "_id", guiaId }, { "IdGuia", guiaId }, { "IdPedido", id }, { "Numero", numero }, { "IdTransporte", transporte }, { "IdEstado", "ACTIVO" } }), cancellationToken: token); return true;
    }, ct);
    public Task MarcarGuiaAnulada(Corrida r, string id, CancellationToken ct) => Tx(async (s, token) => {
        await Fence(s, r, token); await C("Guia").UpdateOneAsync(s, F.Eq("IdPedido", id), U.Set("IdEstado", "ANULADO").Combine(Mod()), cancellationToken: token); return true;
    }, ct);
    public Task<IntentoPaso> IniciarPaso(Corrida r, string id, Paso paso, CancellationToken ct) => Tx(async (s, token) => {
        await Fence(s, r, token);
        var pedido = await C("Pedido").Find(s, F.Eq("_id", id)).FirstAsync(token);
        int usados = pedido.GetValue("IntentosPasos", new BsonDocument()).AsBsonDocument.GetValue(paso.ToString(), 0).ToInt32();
        if (usados >= options.MaxAttempts) throw new FalloProceso("REINTENTOS_AGOTADOS", false);
        var anteriores = await C("PedidoProceso").Find(s, F.Eq("IdPedido", id) & F.Eq("Paso", paso.ToString())).Sort(Builders<BsonDocument>.Sort.Descending("NroIntento")).FirstOrDefaultAsync(token);
        int numero = (anteriores is null ? 0 : Int(anteriores, "NroIntento")) + 1;
        var inicio = Now;
        var intento = new IntentoPaso("DSP-" + Guid.NewGuid(), paso, numero, usados + 1, inicio);
        await C("Pedido").UpdateOneAsync(s, F.Eq("_id", id), U.Set("PasoPendiente", paso.ToString()).Set("FechaInicioPaso", inicio).Inc("IntentosPasos." + paso, 1).Combine(Mod()), cancellationToken: token);
        // Do not insert a second stock step: Java may create its record during the HTTP call.
        return intento;
    }, ct);
    public Task TerminarPaso(Corrida r, string id, IntentoPaso intento, bool exito, string log, CancellationToken ct) => Tx(async (s, token) => {
        await Fence(s, r, token);
        string alias = intento.Paso switch { Paso.RESERVAR_STOCK => "STOCK_RESERVAR", Paso.LIBERAR_STOCK => "STOCK_LIBERAR", Paso.CONFIRMAR_DESPACHO => "STOCK_CONFIRMAR", _ => "" };
        var java = alias.Length == 0 ? null : await C("PedidoProceso").Find(s, F.Eq("IdPedido", id) & F.Eq("Paso", alias)).Sort(Builders<BsonDocument>.Sort.Descending("FechaInicio")).FirstOrDefaultAsync(token);
        if (java is not null)
            await C("PedidoProceso").UpdateOneAsync(s, F.Eq("_id", java["_id"]), U.Set("Paso", intento.Paso.ToString()).Set("NroIntento", intento.Numero).Set("IdEstadoProceso", exito ? "OK" : "FALLIDO").Set("Log", log).Set("FechaFin", Now).Combine(Mod()), cancellationToken: token);
        else
            await C("PedidoProceso").InsertOneAsync(s, Audit(new BsonDocument { { "_id", intento.Id }, { "IdPedidoProceso", intento.Id }, { "IdPedido", id }, { "IdEstadoProceso", exito ? "OK" : "FALLIDO" }, { "Paso", intento.Paso.ToString() }, { "TipoProceso", Reglas.EsCompensacion(intento.Paso) ? "COMPENSACION" : "PROCESO" }, { "NroIntento", intento.Numero }, { "FechaInicio", intento.Inicio }, { "FechaFin", Now }, { "Log", log } }), cancellationToken: token);
        return true;
    }, ct);
    public Task CambiarEstado(Corrida r, string id, EstadoPedido estado, string motivo, Paso? pendiente, CancellationToken ct) => Tx(async (s, token) => {
        await Fence(s, r, token);
        var d = await C("Pedido").Find(s, F.Eq("_id", id) & F.Eq("IdWorker", r.Id)).FirstAsync(token);
        var actual = Enum.Parse<EstadoPedido>(Str(d, "IdEstado")); Reglas.Transicion(actual, estado);
        var u = U.Set("IdEstado", estado.ToString()).Set("Observacion", motivo).Set("PasoPendiente", pendiente is null ? (BsonValue)BsonNull.Value : new BsonString(pendiente.ToString())).Combine(Mod());
        if (estado == EstadoPedido.COMPENSANDO) u = u.Set("CompensacionPendiente", true);
        if (estado == EstadoPedido.REQUIERE_REVISION) u = u.Set("FechaFinProceso", Now).Set("ReintentoSolicitado", false);
        await C("Pedido").UpdateOneAsync(s, F.Eq("_id", id), u, cancellationToken: token); return true;
    }, ct);
    public Task<bool> Finalizar(Corrida r, string id, EstadoPedido estado, string motivo, CancellationToken ct) => Tx(async (s, token) => {
        await Fence(s, r, token);
        var d = await C("Pedido").Find(s, F.Eq("_id", id) & F.Eq("IdWorker", r.Id)).FirstAsync(token);
        if (Str(d, "IdEstado") == estado.ToString()) return true;
        Reglas.Transicion(Enum.Parse<EstadoPedido>(Str(d, "IdEstado")), estado);
        var guia = await C("Guia").Find(s, F.Eq("IdPedido", id)).FirstOrDefaultAsync(token);
        var filtro = F.Eq("_id", id) & F.Eq("IdWorker", r.Id) & F.Eq("IdEstado", d["IdEstado"]);
        if (estado == EstadoPedido.DESPACHADO)
        {
            if (guia is null || Str(guia, "IdEstado") != "ACTIVO" || d.GetValue("Envio", BsonNull.Value).IsBsonNull) return false;
            filtro &= F.Eq("AnulacionSolicitada", false) & F.Eq("EstadoReserva", "CONFIRMADA");
        }
        else if (estado == EstadoPedido.ANULADO)
        {
            if (guia is not null && Str(guia, "IdEstado") != "ANULADO") return false;
            filtro &= F.In("EstadoReserva", new[] { "NINGUNA", "LIBERADA" });
        }
        else throw new InvalidOperationException("Final inválido");
        return (await C("Pedido").UpdateOneAsync(s, filtro, U.Set("IdEstado", estado.ToString()).Set("FechaFinProceso", Now).Set("Observacion", motivo).Set("PasoPendiente", BsonNull.Value).Set("CompensacionPendiente", false).Combine(Mod()), cancellationToken: token)).ModifiedCount == 1;
    }, ct);
    public async Task SolicitarReintento(string id, string usuario, string correlationId, CancellationToken ct)
    {
        var result = await C("Pedido").UpdateOneAsync(F.Eq("_id", id) & F.Eq("IdEstado", "REQUIERE_REVISION") & F.Ne("ReintentoSolicitado", true),
            U.Set("ReintentoSolicitado", true).Set("FechaSolicitudReintento", Now).Set("CorrelationIdReintento", correlationId).Set("IntentosPasos", new BsonDocument()).Combine(Mod(usuario)), cancellationToken: ct);
        if (result.ModifiedCount == 1) return;
        if (!await C("Pedido").Find(F.Eq("_id", id)).AnyAsync(ct)) throw new FalloHttp(404, "Pedido no encontrado");
        throw new FalloHttp(409, "Pedido no reintentable o reintento ya solicitado");
    }
    public async Task Ping(CancellationToken ct) { await db.RunCommandAsync<BsonDocument>(new BsonDocument("ping", 1), cancellationToken: ct); }
}
internal static class UpdateExtensions
{
    public static UpdateDefinition<BsonDocument> Combine(this UpdateDefinition<BsonDocument> first, UpdateDefinition<BsonDocument> second) => Builders<BsonDocument>.Update.Combine(first, second);
}
