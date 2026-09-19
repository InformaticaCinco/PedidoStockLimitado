package pe.reto.pedidos.config;

import dagger.Module;
import dagger.Provides;
import javax.inject.Singleton;
import com.mongodb.client.*;
import java.time.Clock;
import pe.reto.pedidos.adapter.out.mongo.MongoRepositorio;
import pe.reto.pedidos.application.port.out.Repositorio;

@Module public final class RepositoryModule {
    @Provides @Singleton static MongoRepositorio mongo(MongoClient c, MongoDatabase db, Clock reloj) { return new MongoRepositorio(c, db, reloj); }
    @Provides static Repositorio repo(MongoRepositorio repo) { return repo; }
}
