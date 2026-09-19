# Decisión 03: arquitectura del reto y evolución productiva

## Contexto

El reto combina concurrencia de stock, procesamiento asíncrono, fallos externos y varias tecnologías, con MongoDB como única base de datos. La entrega necesita ser reproducible y observable mediante contratos, estados persistidos y pruebas. Esa finalidad no equivale a un despliegue de alta disponibilidad.

## Decisión

### Implementado en el reto

Una instancia por servicio en Docker Compose: Java para identidad/catálogo/pedidos/stock; .NET para coordinar despachos; Python para cargas; simulador HTTP del transportista; web-host y admin-mfe servidos por Nginx. `mongo-init` es una tarea de arranque, no una API adicional.

MongoDB 7 es la única base, con volumen persistente y replica set de un nodo. Java, .NET y Python comparten colecciones bajo contratos explícitos. Las tareas/corridas se conservan en MongoDB; no se incorporó un broker. El simulador conserva solo estado volátil. Compose define dependencias de arranque, healthchecks, reinicio de servicios y plataforma linux/amd64.

Se implementaron transacciones y filtros para stock, índices únicos, idempotencia, leases, reconciliación y compensaciones. Hay JWT RS256 con validación independiente, controles por rol/pertenencia, correlationId y logs operativos. Estos elementos hacen viable el alcance del reto y permiten investigar interrupciones con evidencias persistidas.

### Evolución propuesta para producción — no implementada

| Área | Conservar | Cambio propuesto |
|---|---|---|
| Dominio | Reserva/confirmación/liberación, claves idempotentes y estados auditables | Cerrar formalmente la carrera de anulación tras confirmación y definir política de devoluciones/revisión |
| Disponibilidad | Servicios con responsabilidades y health endpoints claros | Varias réplicas, despliegues graduales y orquestación apropiada; MongoDB con nodos en dominios de fallo distintos |
| MongoDB | Transacciones, índices y modelo de invariantes | Autenticación/TLS, privilegios mínimos por servicio, backups, restauración probada, monitoreo y capacidad; evaluar servicio gestionado |
| Escalado | Recuperación y control de propiedad | Revisar el worker único abierto: agregar réplicas no paraleliza por sí solo; diseñar particionado y ownership por pedido conservando fencing/idempotencia |
| Secretos | Firma asimétrica y validación local | Gestor de secretos, claves por entorno, rotación RSA/JWKS, TLS y autenticación de servicios; retirar claves demo de imágenes |
| Observabilidad | Logs y evidencia de pasos/estados | Tracing distribuido, propagación consistente del correlationId (Java hoy lo sustituye), métricas de latencia/colas/reintentos, alertas y objetivos de servicio |
| Mensajería | Estado durable y deduplicación | Si se elimina la restricción actual, evaluar cola durable, outbox/inbox y política de redelivery; mantener idempotencia, no asumir exactly-once global |
| Transportista | Consulta por pedido y clave estable | Proveedor real con contrato durable de idempotencia, reconciliación, cancelación, SLA, credenciales y pruebas de compatibilidad |
| Datos compartidos | Contratos claros y versiones compatibles | Evaluar propiedad de datos por servicio/migraciones, reducir acoplamiento directo sin romper atomicidad requerida |
| Entrega | Dockerfiles y pruebas reproducibles | CI verificable, publicación firmada/versionada, digests de registro, análisis de dependencias y promoción por entorno |

Compose sigue siendo útil para desarrollo e integración local. No se presenta como un orquestador de alta disponibilidad. El diseño productivo requeriría medir carga real y disponibilidad objetivo; no se fijan capacidades o tiempos inventados.

## Alternativas consideradas

Un monolito reduciría la coordinación operativa, pero no reflejaría la separación tecnológica requerida por el reto. Incorporar un broker o varias bases desde el inicio cambiaría la restricción vigente. Crear una plataforma de orquestación completa en esta entrega aumentaría el alcance sin cerrar primero sus contratos funcionales. Estas alternativas se documentan como comparación, no como prototipos construidos.

## Consecuencias

El entorno actual es reproducible, pero tiene puntos únicos de fallo, credenciales de laboratorio, exposición local de puertos y dependencias de esquema compartidas. La capacidad de recuperación probada no acredita disponibilidad continua. Una guía puede perderse al reiniciar el simulador. La UI ADMIN presenta métricas derivadas y referencias locales, no historial global ni BI.

**PENDIENTE DE CIERRE:** primera ejecución de CI en GitHub (workflow creado en [.github/workflows/ci.yml](../../.github/workflows/ci.yml), que reutiliza [scripts/run-tests.sh](../../scripts/run-tests.sh)), registro/digests publicados y PDF de referencia ausentes de esta copia. No se consideran componentes productivos ya entregados.

## Evidencia

- [Compose](../../docker-compose.yml), [Dockerfile Java](../../services/pedidos-java/Dockerfile), [Dockerfile .NET](../../services/despachos-dotnet/Dockerfile), [Dockerfile Python](../../services/cargas-python/Dockerfile), [host Nginx](../../frontend/web-host/nginx.conf).
- [Decisión de consistencia](01-consistencia-stock-mongodb.md) y [decisión de repetición](02-idempotencia-y-repeticion.md).
- [E2E 12](../../tests/evidencias/e2e12-reinicio-despachos.json), [13](../../tests/evidencias/e2e13-caida-mongodb.json) y [14](../../tests/evidencias/e2e14-caida-transportista.json): recuperación o revisión frente a fallos específicos, sin demostrar HA.
- [E2E 17](../../tests/evidencias/e2e17-autenticacion.json), [18](../../tests/evidencias/e2e18-autorizacion-roles.json), [19](../../tests/evidencias/e2e19-pertenencia.json): validaciones de seguridad del reto, no certificación integral de seguridad.
