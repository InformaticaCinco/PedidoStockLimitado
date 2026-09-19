# Credenciales de laboratorio

> Solo datos ficticios de laboratorio para el reto técnico.

Contraseña demo para todos: **`Reto2026!`**. No es un secreto real ni una credencial para producción.

| Login | Rol | IdUsuario | Relación |
|---|---|---|---|
| admin | ADMIN | USR-ADMIN-01 | Administración |
| vendedor01 | VENDEDOR | USR-VEN-01 | ALM-01 |
| vendedor02 | VENDEDOR | USR-VEN-02 | ALM-02 |
| vendedor03 | VENDEDOR | USR-VEN-03 | ALM-03 |
| comprador01 | COMPRADOR | USR-COM-001 | CLI-0001 |
| comprador02 | COMPRADOR | USR-COM-002 | CLI-0002 |

Patrón completo: `comprador01` … `comprador40`; IDs `USR-COM-001` … `USR-COM-040`, clientes `CLI-0001` … `CLI-0040`.

Mongo almacena únicamente `ClaveHash`, BCrypt `$2a$` con coste 10, compatible con jBCrypt de Java. El hash demo se generó una vez y quedó fijo en el fixture; ejecutar el seed no vuelve a salar/reescribir los hashes. La contraseña anterior aparece solo en el código/documentación de laboratorio y las peticiones de login de prueba, nunca como campo de Usuario en Mongo.

Si alguien cambia una clave de manera operacional, el seed normal la conserva. Solo un reset explícito devuelve la contraseña demo. Las pruebas de Java guardan identidad/rol/estado HTTP y omiten access/refresh tokens de las evidencias.
