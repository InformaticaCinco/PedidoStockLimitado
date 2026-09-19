package pe.reto.pedidos.adapter.in.http;

import java.util.Map;
import com.fasterxml.jackson.annotation.JsonInclude;

public record Respuesta(int code, String statusCode, String message, Object data,
                        @JsonInclude(JsonInclude.Include.NON_EMPTY) Map<String, String> errores) {
    public static Respuesta crear(int code, String message, Object data, Map<String, String> errores) {
        String estado = switch (code) {
            case 200 -> "OK"; case 201 -> "CREATED"; case 202 -> "ACCEPTED";
            case 400 -> "BAD_REQUEST"; case 401 -> "UNAUTHORIZED"; case 403 -> "FORBIDDEN";
            case 404 -> "NOT_FOUND"; case 405 -> "METHOD_NOT_ALLOWED"; case 409 -> "CONFLICT";
            case 413 -> "CONTENT_TOO_LARGE"; case 415 -> "UNSUPPORTED_MEDIA_TYPE"; case 503 -> "SERVICE_UNAVAILABLE";
            default -> "INTERNAL_SERVER_ERROR";
        };
        return new Respuesta(code, "HTTP_" + code + "_" + estado, message, data, errores);
    }
}
