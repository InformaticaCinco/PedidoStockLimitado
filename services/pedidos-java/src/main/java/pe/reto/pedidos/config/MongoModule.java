package pe.reto.pedidos.config;

import dagger.Module;
import dagger.Provides;
import javax.inject.Singleton;
import com.mongodb.*;
import com.mongodb.client.*;
import java.util.concurrent.TimeUnit;

@Module public final class MongoModule {
    @Provides @Singleton static MongoClient client(Settings s) {
        return MongoClients.create(MongoClientSettings.builder().applyConnectionString(new ConnectionString(s.mongoUri()))
                .writeConcern(WriteConcern.MAJORITY).readConcern(ReadConcern.MAJORITY).readPreference(ReadPreference.primary())
                .applyToClusterSettings(c -> c.serverSelectionTimeout(5, TimeUnit.SECONDS)).build());
    }
    @Provides @Singleton static MongoDatabase database(MongoClient c, Settings s) { return c.getDatabase(s.database()); }
}
