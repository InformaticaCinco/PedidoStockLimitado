package pe.reto.pedidos.bootstrap;

import pe.reto.pedidos.config.*;

public final class Main {
    private Main() {}
    public static void main(String[] args) {
        AppComponent app = DaggerAppComponent.factory().create(Settings.load());
        try {
            app.repositorio().crearIndices();
            var http = app.http().start();
            Runtime.getRuntime().addShutdownHook(new Thread(() -> { http.stop(); app.mongoClient().close(); }));
        } catch (RuntimeException e) { app.mongoClient().close(); throw e; }
    }
}
