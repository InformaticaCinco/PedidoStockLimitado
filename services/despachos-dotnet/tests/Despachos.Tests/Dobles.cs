using Despachos.Application;
using Despachos.Domain;
using Microsoft.Extensions.Logging.Abstractions;
namespace Despachos.Tests;

internal sealed class Reloj : TimeProvider
{
    public DateTimeOffset Ahora { get; set; } = DateTimeOffset.UtcNow;
    public override DateTimeOffset GetUtcNow() => Ahora;
}
internal sealed class SinEspera : IEspera
{
    public List<TimeSpan> Demoras { get; } = [];
    public Task Esperar(TimeSpan d, CancellationToken ct) { ct.ThrowIfCancellationRequested(); Demoras.Add(d); return Task.CompletedTask; }
}
internal sealed class Memoria : IRepositorio
{
    public Pedido Pedido { get; set; } = new("PED-1", EstadoPedido.EN_PROCESO, EstadoReserva.NINGUNA, "PROVINCIA", "WRK-1", DateTime.UtcNow, null, 1, false, "corr-prueba", null, null, false, false, false, [new("SKU-00001", 2, 10m, 1.25m, 20m)]);
    public Guia? Guia { get; set; }
    public List<string> Efectos { get; } = [];
    public List<(IntentoPaso Intento, bool Ok, string Log)> Procesos { get; } = [];
    public Dictionary<Paso, int> Contadores { get; } = [];
    public IReadOnlyList<Tarifa> Tramos { get; set; } = [new("PROVINCIA", 0, 100, 5.005m)];
    public int Max { get; set; } = 3;
    public int Pings { get; private set; }
    public bool FallarPing { get; set; }
    public string? Auditor { get; private set; }
    public string? Motivo { get; private set; }
    public Task Inicializar(CancellationToken ct) => Task.CompletedTask;
    public Task<Corrida?> Adquirir(string owner, CancellationToken ct) => Task.FromResult<Corrida?>(new("WRK-1", owner, 1, false));
    public Task<bool> Renovar(Corrida r, CancellationToken ct) => Task.FromResult(true);
    public Task Verificar(Corrida r, CancellationToken ct) => Task.CompletedTask;
    public Task<Pedido?> Tomar(Corrida r, CancellationToken ct) => Task.FromResult<Pedido?>(null);
    public Task Cerrar(Corrida r, CancellationToken ct) => Task.CompletedTask;
    public Task<Pedido> Obtener(string id, CancellationToken ct) => id == Pedido.Id ? Task.FromResult(Pedido) : throw new FalloHttp(404, "Pedido no encontrado");
    public Task<Guia?> ObtenerGuia(string id, CancellationToken ct) => Task.FromResult(Guia);
    public Task<IReadOnlyList<Tarifa>> Tarifas(string z, CancellationToken ct) => Task.FromResult(Tramos);
    public Task<string> Transporte(CancellationToken ct) => Task.FromResult("TRA-1");
    public Task GuardarEnvio(Corrida r, string id, Importes i, CancellationToken ct) { Pedido = Pedido with { Envio = i.Envio }; Efectos.Add("envio"); return Task.CompletedTask; }
    public Task MarcarGuiaIntentada(Corrida r, string id, CancellationToken ct) { Pedido = Pedido with { GuiaIntentada = true }; return Task.CompletedTask; }
    public Task GuardarGuia(Corrida r, string id, string numero, string t, CancellationToken ct) { Guia ??= new("GUI-1", id, numero, t, false); return Task.CompletedTask; }
    public Task MarcarGuiaAnulada(Corrida r, string id, CancellationToken ct) { Guia = Guia! with { Anulada = true }; return Task.CompletedTask; }
    public Task<IntentoPaso> IniciarPaso(Corrida r, string id, Paso p, CancellationToken ct)
    {
        int n = Contadores.GetValueOrDefault(p) + 1;
        if (n > Max) throw new FalloProceso("REINTENTOS_AGOTADOS", false);
        Contadores[p] = n; Pedido = Pedido with { Pendiente = p }; return Task.FromResult(new IntentoPaso(Guid.NewGuid().ToString(), p, n, n, DateTime.UtcNow));
    }
    public Task TerminarPaso(Corrida r, string id, IntentoPaso p, bool ok, string log, CancellationToken ct) { Procesos.Add((p, ok, log)); return Task.CompletedTask; }
    public Task CambiarEstado(Corrida r, string id, EstadoPedido e, string log, Paso? p, CancellationToken ct)
    { Reglas.Transicion(Pedido.Estado, e); Motivo = log; Pedido = Pedido with { Estado = e, Pendiente = p, CompensacionPendiente = e == EstadoPedido.COMPENSANDO || Pedido.CompensacionPendiente }; return Task.CompletedTask; }
    public Task<bool> Finalizar(Corrida r, string id, EstadoPedido e, string log, CancellationToken ct)
    {
        if (e == EstadoPedido.DESPACHADO && (Pedido.Anulacion || Pedido.Reserva != EstadoReserva.CONFIRMADA || Guia is not { Anulada: false })) return Task.FromResult(false);
        if (e == EstadoPedido.ANULADO && (Pedido.Reserva is EstadoReserva.CONFIRMADA or EstadoReserva.RESERVADA || Guia is { Anulada: false })) return Task.FromResult(false);
        Reglas.Transicion(Pedido.Estado, e); Motivo = log; Pedido = Pedido with { Estado = e, Fin = DateTime.UtcNow, Pendiente = null }; return Task.FromResult(true);
    }
    public Task SolicitarReintento(string id, string user, string c, CancellationToken ct)
    {
        if (id != Pedido.Id) throw new FalloHttp(404, "Pedido no encontrado");
        if (Pedido.Estado != EstadoPedido.REQUIERE_REVISION || Pedido.ReintentoSolicitado) throw new FalloHttp(409, "Estado no reintentable");
        Auditor = user; Contadores.Clear(); Pedido = Pedido with { ReintentoSolicitado = true }; return Task.CompletedTask;
    }
    public Task Ping(CancellationToken ct) { Pings++; if (FallarPing) throw new InvalidOperationException(); return Task.CompletedTask; }
}
internal sealed class JavaFake(Memoria repo) : IPedidosClient
{
    public bool Insuficiente { get; set; }
    public int Reservas { get; private set; }
    public int Confirmaciones { get; private set; }
    public int Liberaciones { get; private set; }
    public Action? DespuesReserva { get; set; }
    public Action? DespuesConfirmar { get; set; }
    public Task Reservar(Pedido p, CancellationToken ct)
    {
        if (Insuficiente) throw new FalloProceso("STOCK_INSUFICIENTE", false);
        if (repo.Pedido.Reserva == EstadoReserva.NINGUNA) { Reservas++; repo.Efectos.Add("reservar"); repo.Pedido = repo.Pedido with { Reserva = EstadoReserva.RESERVADA }; }
        DespuesReserva?.Invoke(); return Task.CompletedTask;
    }
    public Task Liberar(Pedido p, CancellationToken ct)
    { if (repo.Pedido.Reserva == EstadoReserva.RESERVADA) { Liberaciones++; repo.Efectos.Add("liberar"); repo.Pedido = repo.Pedido with { Reserva = EstadoReserva.LIBERADA }; } return Task.CompletedTask; }
    public Task Confirmar(Pedido p, CancellationToken ct)
    {
        if (repo.Pedido.Reserva != EstadoReserva.CONFIRMADA) { Confirmaciones++; repo.Efectos.Add("confirmar"); repo.Pedido = repo.Pedido with { Reserva = EstadoReserva.CONFIRMADA }; }
        DespuesConfirmar?.Invoke(); return Task.CompletedTask;
    }
}
internal sealed class TransportistaFake(Memoria repo) : ITransportistaClient
{
    public GuiaRemota? Remota { get; set; }
    public int Posts { get; private set; }
    public int Gets { get; private set; }
    public int Anulaciones { get; private set; }
    public int FallosPost { get; set; }
    public bool TimeoutDespuesCrear { get; set; }
    public bool Caido { get; set; }
    public bool FallaAnular { get; set; }
    public Action? DespuesCrear { get; set; }
    public List<string> Claves { get; } = [];
    public Task<GuiaRemota?> Consultar(Pedido p, CancellationToken ct) { Gets++; if (Caido) throw new FalloProceso("TRANSPORTISTA_CONEXION"); return Task.FromResult(Remota); }
    public Task<GuiaRemota> Generar(Pedido p, decimal peso, CancellationToken ct)
    {
        Posts++; Claves.Add(Reglas.ClaveGuia(p.Id));
        if (FallosPost-- > 0) throw new FalloProceso("TRANSPORTISTA_HTTP_503");
        Remota ??= new("G-1"); repo.Efectos.Add("generar"); DespuesCrear?.Invoke();
        if (TimeoutDespuesCrear) throw new FalloProceso("TRANSPORTISTA_TIMEOUT"); return Task.FromResult(Remota);
    }
    public Task Anular(Pedido p, string numero, CancellationToken ct)
    { if (FallaAnular) throw new FalloProceso("TRANSPORTISTA_HTTP_503"); if (Remota is not null) { Anulaciones++; repo.Efectos.Add("anular"); Remota = null; } return Task.CompletedTask; }
}
internal sealed class Escenario
{
    public Memoria Repo { get; } = new();
    public JavaFake Java { get; }
    public TransportistaFake Carrier { get; }
    public SinEspera Espera { get; } = new();
    public Reloj Reloj { get; } = new();
    public Corrida Corrida { get; } = new("WRK-1", "owner", 1, false);
    public Coordinador Coordinador { get; }
    public Escenario()
    {
        Java = new(Repo); Carrier = new(Repo);
        Coordinador = new(Repo, Java, Carrier, new Opciones(), Espera, Reloj, NullLogger<Coordinador>.Instance);
    }
    public Task Run() => Coordinador.Procesar(Corrida, Repo.Pedido, CancellationToken.None);
}
