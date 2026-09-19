using Despachos.Domain;
using Xunit;
namespace Despachos.Tests;

public sealed class DominioTests
{
    [Fact] public void PesoTarifaYTotalDecimal()
    {
        var i = Reglas.Calcular([new("SKU-00001", 3, 1.10m, 2.5m, 3.30m), new("SKU-00002", 2, 4m, 0.25m, 8m)], [new("PROVINCIA", 0, 10, 5.005m)], "PROVINCIA");
        Assert.Equal(8m, i.Peso); Assert.Equal(11.30m, i.Subtotal); Assert.Equal(5.01m, i.Envio); Assert.Equal(16.31m, i.Total);
    }
    [Theory][InlineData("1.005", "1.01")][InlineData("-1.005", "-1.01")][InlineData("2.004", "2.00")]
    public void HalfUp(string value, string expected) => Assert.Equal(decimal.Parse(expected, System.Globalization.CultureInfo.InvariantCulture), Reglas.Moneda(decimal.Parse(value, System.Globalization.CultureInfo.InvariantCulture)));
    [Fact] public void LimitesIncluyenDesdeExcluyenHasta()
    {
        var lineas = new[] { new Linea("sku", 1, 1, 10, 1) };
        Assert.Equal(2m, Reglas.Calcular(lineas, [new("Z", 0, 10, 1), new("Z", 10, 20, 2)], "Z").Envio);
        Assert.Throws<FalloProceso>(() => Reglas.Calcular(lineas, [new("OTRA", 0, 20, 1)], "Z"));
        Assert.Throws<FalloProceso>(() => Reglas.Calcular(lineas, [new("Z", 0, 20, 1), new("Z", 0, 30, 2)], "Z"));
    }
    [Fact] public void TransicionesTerminalesRechazadas()
    {
        Assert.Throws<FalloProceso>(() => Reglas.Transicion(EstadoPedido.DESPACHADO, EstadoPedido.COMPENSANDO));
        Assert.Throws<FalloProceso>(() => Reglas.Transicion(EstadoPedido.ANULADO, EstadoPedido.EN_PROCESO));
    }
}
