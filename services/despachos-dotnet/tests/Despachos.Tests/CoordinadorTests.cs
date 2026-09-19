using Despachos.Domain;
using Xunit;
namespace Despachos.Tests;

public sealed class CoordinadorTests
{
    [Fact] public async Task FlujoCompletoReservaGuiaConfirma()
    {
        var s = new Escenario(); await s.Run();
        Assert.Equal(EstadoPedido.DESPACHADO, s.Repo.Pedido.Estado); Assert.Equal(5.01m, s.Repo.Pedido.Envio);
        Assert.Equal(["reservar", "envio", "generar", "confirmar"], s.Repo.Efectos); Assert.Equal(4, s.Repo.Procesos.Count);
    }
    [Fact] public async Task InsuficienteAnulaSinCompensacionNiGuia()
    {
        var s = new Escenario(); s.Java.Insuficiente = true; await s.Run();
        Assert.Equal(EstadoPedido.ANULADO, s.Repo.Pedido.Estado); Assert.Equal("Stock insuficiente", s.Repo.Motivo);
        Assert.Equal(0, s.Carrier.Posts); Assert.Equal(0, s.Java.Liberaciones); Assert.Single(s.Repo.Procesos);
    }
    [Fact] public async Task TimeoutTrasCrearConsultaSinSegundoPost()
    {
        var s = new Escenario(); s.Carrier.TimeoutDespuesCrear = true; await s.Run();
        Assert.Equal(EstadoPedido.DESPACHADO, s.Repo.Pedido.Estado); Assert.Equal(1, s.Carrier.Posts); Assert.Equal(2, s.Carrier.Gets); Assert.NotNull(s.Repo.Guia);
    }
    [Fact] public async Task ReintentoPostMantieneClaveYConsultaAntes()
    {
        var s = new Escenario(); s.Carrier.FallosPost = 1; await s.Run();
        Assert.Equal(EstadoPedido.DESPACHADO, s.Repo.Pedido.Estado); Assert.Equal(2, s.Carrier.Posts); Assert.Single(s.Carrier.Claves.Distinct()); Assert.Equal(3, s.Carrier.Gets); Assert.Single(s.Espera.Demoras);
    }
    [Fact] public async Task RepeticionFinalNoRepiteEfectos()
    {
        var s = new Escenario(); await s.Run(); await s.Run(); Assert.Equal(1, s.Java.Reservas); Assert.Equal(1, s.Java.Confirmaciones); Assert.Equal(1, s.Carrier.Posts);
    }
    [Fact] public async Task RecuperacionConGuiaPersistidaNoReservaNiGeneraDeNuevo()
    {
        var s = new Escenario(); s.Repo.Pedido = s.Repo.Pedido with { Reserva = EstadoReserva.RESERVADA, Envio = 5m, GuiaIntentada = true, Intento = 2 };
        s.Repo.Guia = new("GUI-1", "PED-1", "G-1", "TRA-1", false); await s.Run();
        Assert.Equal(EstadoPedido.DESPACHADO, s.Repo.Pedido.Estado); Assert.Equal(0, s.Java.Reservas); Assert.Equal(0, s.Carrier.Posts); Assert.Equal(1, s.Java.Confirmaciones);
    }
    [Fact] public async Task RecuperacionConfirmadaSoloCierra()
    {
        var s = new Escenario(); s.Repo.Pedido = s.Repo.Pedido with { Reserva = EstadoReserva.CONFIRMADA, Envio = 5m }; s.Repo.Guia = new("GUI-1", "PED-1", "G-1", "TRA-1", false);
        await s.Run(); Assert.Equal(EstadoPedido.DESPACHADO, s.Repo.Pedido.Estado); Assert.Equal(0, s.Java.Confirmaciones); Assert.Equal(0, s.Carrier.Posts);
    }
    [Fact] public async Task AnulacionAntesDeInicioSinEfectos()
    {
        var s = new Escenario(); s.Repo.Pedido = s.Repo.Pedido with { Anulacion = true }; await s.Run(); Assert.Equal(EstadoPedido.ANULADO, s.Repo.Pedido.Estado); Assert.Empty(s.Repo.Efectos);
    }
    [Fact] public async Task AnulacionTrasReservaSoloLibera()
    {
        var s = new Escenario(); s.Java.DespuesReserva = () => s.Repo.Pedido = s.Repo.Pedido with { Anulacion = true }; await s.Run();
        Assert.Equal(EstadoPedido.ANULADO, s.Repo.Pedido.Estado); Assert.Equal(["reservar", "liberar"], s.Repo.Efectos); Assert.Equal(0, s.Carrier.Anulaciones);
    }
    [Fact] public async Task CompensacionInversaYRepetida()
    {
        var s = new Escenario(); s.Carrier.DespuesCrear = () => s.Repo.Pedido = s.Repo.Pedido with { Anulacion = true }; await s.Run(); await s.Run();
        Assert.Equal(EstadoPedido.ANULADO, s.Repo.Pedido.Estado); Assert.Equal(["reservar", "envio", "generar", "anular", "liberar"], s.Repo.Efectos);
        Assert.Equal(1, s.Java.Liberaciones); Assert.Equal(1, s.Carrier.Anulaciones); Assert.Equal(0, s.Java.Confirmaciones);
    }
    [Fact] public async Task CaidaTransportistaAgotaYDejaRevision()
    {
        var s = new Escenario(); s.Carrier.Caido = true; await s.Run();
        Assert.Equal(EstadoPedido.REQUIERE_REVISION, s.Repo.Pedido.Estado); Assert.Equal(Paso.GENERAR_GUIA, s.Repo.Pedido.Pendiente); Assert.Equal(3, s.Carrier.Gets); Assert.Equal(2, s.Espera.Demoras.Count);
        await s.Run(); Assert.Equal(3, s.Carrier.Gets);
    }
    [Fact] public async Task CompensacionFallidaNoLiberaAntesDeAnularGuia()
    {
        var s = new Escenario(); s.Carrier.FallaAnular = true; s.Carrier.DespuesCrear = () => s.Repo.Pedido = s.Repo.Pedido with { Anulacion = true }; await s.Run();
        Assert.Equal(EstadoPedido.REQUIERE_REVISION, s.Repo.Pedido.Estado); Assert.Equal(0, s.Java.Liberaciones); Assert.True(s.Repo.Pedido.CompensacionPendiente);
    }
    [Fact] public async Task AnulacionDespuesConfirmacionQuedaRevisionSegunAcuerdo()
    {
        var s = new Escenario(); s.Java.DespuesConfirmar = () => s.Repo.Pedido = s.Repo.Pedido with { Anulacion = true }; await s.Run();
        Assert.Equal(EstadoPedido.REQUIERE_REVISION, s.Repo.Pedido.Estado); Assert.Equal("ANULACION_TRAS_CONFIRMACION_REQUIERE_AJUSTE_JAVA", s.Repo.Motivo); Assert.Equal(0, s.Java.Liberaciones);
    }
    [Fact] public async Task RecuperacionTimeoutCompensaReservaExistente()
    {
        var s = new Escenario(); s.Repo.Pedido = s.Repo.Pedido with { Reserva = EstadoReserva.RESERVADA, Inicio = DateTime.UtcNow.AddMinutes(-10) }; await s.Run();
        Assert.Equal(EstadoPedido.ANULADO, s.Repo.Pedido.Estado); Assert.Equal(1, s.Java.Liberaciones); Assert.Equal(0, s.Carrier.Posts);
    }
    [Fact] public async Task TarifaAusenteNoSeInventaYCompensa()
    {
        var s = new Escenario(); s.Repo.Tramos = []; await s.Run(); Assert.Equal(EstadoPedido.ANULADO, s.Repo.Pedido.Estado); Assert.Null(s.Repo.Pedido.Envio); Assert.Equal(1, s.Java.Liberaciones);
    }
}
