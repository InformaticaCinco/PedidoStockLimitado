package pe.reto.pedidos;

import com.mongodb.client.*;
import org.bson.Document;
import java.net.ServerSocket;
import java.nio.file.*;
import java.time.*;
import java.util.*;
import java.util.concurrent.TimeUnit;
import static org.junit.jupiter.api.Assumptions.assumeTrue;

/** Runs a real MongoDB 7 binary when provided, or connects to an explicit test replica set. */
final class MongoReplica implements AutoCloseable {
    private Process process;
    MongoClient client;
    String uri;
    MongoReplica() throws Exception {
        uri = System.getenv("MONGODB_TEST_URI");
        if (uri == null || uri.isBlank()) {
            String binary = System.getenv("MONGODB_TEST_BINARY");
            assumeTrue(binary != null && !binary.isBlank(), "Requiere MONGODB_TEST_URI (replica set) o MONGODB_TEST_BINARY (mongod 7)");
            int port;
            try (ServerSocket socket = new ServerSocket(0)) { port = socket.getLocalPort(); }
            Path dir = Files.createTempDirectory(Path.of("target"), "mongo-it-").toAbsolutePath();
            process = new ProcessBuilder(binary, "--port", Integer.toString(port), "--bind_ip", "127.0.0.1", "--replSet", "rsTest", "--dbpath", dir.toString(), "--logpath", dir.resolve("mongod.log").toString(), "--wiredTigerCacheSizeGB", "0.25").redirectErrorStream(true).redirectOutput(dir.resolve("process.log").toFile()).start();
            String host = "127.0.0.1:" + port;
            try (var direct = MongoClients.create("mongodb://" + host + "/?directConnection=true&serverSelectionTimeoutMS=30000")) {
                direct.getDatabase("admin").runCommand(new Document("replSetInitiate", new Document("_id", "rsTest").append("members", List.of(new Document("_id", 0).append("host", host)))));
            } catch (Exception e) { close(); throw e; }
            uri = "mongodb://" + host + "/?replicaSet=rsTest&serverSelectionTimeoutMS=30000";
        }
        client = MongoClients.create(uri);
        client.getDatabase("admin").runCommand(new Document("ping", 1));
        String version = client.getDatabase("admin").runCommand(new Document("buildInfo", 1)).getString("version");
        if (!version.startsWith("7.")) { close(); throw new IllegalStateException("Pruebas requieren MongoDB 7, recibido " + version); }
    }
    public void close() {
        if (client != null) client.close();
        if (process != null) { process.destroy(); try { if (!process.waitFor(15, TimeUnit.SECONDS)) process.destroyForcibly(); } catch (InterruptedException e) { Thread.currentThread().interrupt(); } }
    }
}
