package pe.reto.pedidos.config;

import dagger.Module;
import dagger.Provides;
import javax.inject.Singleton;
import java.time.Clock;
import pe.reto.pedidos.adapter.out.security.RsaSeguridad;
import pe.reto.pedidos.application.port.out.Seguridad;

@Module public final class SecurityModule {
    @Provides @Singleton static Seguridad seguridad(Settings s, Clock reloj) { return new RsaSeguridad(s, reloj); }
}
