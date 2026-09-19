package pe.reto.pedidos.config;

import dagger.Module;
import dagger.Provides;
import javax.inject.Singleton;
import com.fasterxml.jackson.core.*;
import com.fasterxml.jackson.databind.*;
import com.fasterxml.jackson.databind.json.JsonMapper;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import pe.reto.pedidos.application.port.in.Pedidos;
import pe.reto.pedidos.application.port.out.*;
import pe.reto.pedidos.application.usecase.*;
import pe.reto.pedidos.adapter.in.http.HttpApi;

@Module public final class HttpModule {
    public static ObjectMapper json() {
        return JsonMapper.builder(JsonFactory.builder().enable(StreamReadFeature.STRICT_DUPLICATE_DETECTION)
                .streamReadConstraints(StreamReadConstraints.builder().maxNestingDepth(20).maxNumberLength(40).maxStringLength(8192).build()).build())
                .addModule(new JavaTimeModule()).enable(DeserializationFeature.USE_BIG_DECIMAL_FOR_FLOATS)
                .enable(DeserializationFeature.FAIL_ON_TRAILING_TOKENS).disable(SerializationFeature.WRITE_DATES_AS_TIMESTAMPS).build();
    }
    @Provides @Singleton static ObjectMapper mapper() { return json(); }
    @Provides @Singleton static HttpApi http(Settings c, ObjectMapper json, Pedidos p, CatalogoService catalogo, AuthService auth, Seguridad seguridad, Repositorio repo) { return new HttpApi(c, json, p, catalogo, auth, seguridad, repo); }
}
