package pe.reto.pedidos.config;

import dagger.*;
import javax.inject.Singleton;
import com.mongodb.client.MongoClient;
import pe.reto.pedidos.adapter.in.http.HttpApi;
import pe.reto.pedidos.adapter.out.mongo.MongoRepositorio;

@Singleton @Component(modules = {MongoModule.class, RepositoryModule.class, SecurityModule.class, ApplicationModule.class, HttpModule.class})
public interface AppComponent {
    HttpApi http();
    MongoRepositorio repositorio();
    MongoClient mongoClient();
    @Component.Factory interface Factory { AppComponent create(@BindsInstance Settings settings); }
}
