package pe.reto.pedidos.config;

import dagger.Module;
import dagger.Provides;
import java.time.Clock;
import pe.reto.pedidos.application.port.in.Pedidos;
import pe.reto.pedidos.application.port.out.*;
import pe.reto.pedidos.application.usecase.*;

@Module public final class ApplicationModule {
    @Provides static Clock clock() { return Clock.systemUTC(); }
    @Provides static Pedidos pedidos(Repositorio r) { return new PedidosService(r); }
    @Provides static CatalogoService catalogo(Repositorio r) { return new CatalogoService(r); }
    @Provides static AuthService auth(Repositorio r, Seguridad s, Clock reloj, Settings c) { return new AuthService(r, s, reloj, c.accessSeconds(), c.refreshSeconds()); }
}
