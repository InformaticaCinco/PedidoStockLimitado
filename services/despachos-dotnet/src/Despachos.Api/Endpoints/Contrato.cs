using System.Text.Json.Serialization;
namespace Despachos.Api.Endpoints;

public sealed record Respuesta(int Code, string StatusCode, string Message, object? Data,
    [property: JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)] object? Errores = null)
{
    public static Respuesta Crear(int code, object? data = null, string? message = null, object? errores = null)
    {
        string status = code switch { 200 => "OK", 202 => "ACCEPTED", 400 => "BAD_REQUEST", 401 => "UNAUTHORIZED", 403 => "FORBIDDEN", 404 => "NOT_FOUND", 405 => "METHOD_NOT_ALLOWED", 409 => "CONFLICT", 413 => "CONTENT_TOO_LARGE", 422 => "UNPROCESSABLE_ENTITY", 503 => "SERVICE_UNAVAILABLE", _ => "INTERNAL_SERVER_ERROR" };
        return new(code, $"HTTP_{code}_{status}", message ?? status, data, errores);
    }
}
