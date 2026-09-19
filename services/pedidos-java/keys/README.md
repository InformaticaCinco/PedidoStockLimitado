# Claves JWT de demostración

Los archivos de esta carpeta contienen un par RSA utilizado exclusivamente
por el entorno local/reproducible del reto técnico PedidoStockLimitado.

NO son claves de producción.
NO protegen información real.
NO deben reutilizarse fuera de este proyecto.

Se incluyen en el repositorio únicamente para que:

- `docker compose up --build` funcione desde un clon limpio;
- los servicios puedan validar JWT RS256 de forma reproducible;
- las pruebas automatizadas puedan generar y validar tokens de prueba.

En un entorno productivo estas claves deben almacenarse en un gestor de
secretos y rotarse mediante un procedimiento seguro.
