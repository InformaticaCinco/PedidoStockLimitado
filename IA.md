# Uso de inteligencia artificial y supervisión

Se utilizaron **ChatGPT** y **Codex** como apoyo al desarrollo de PedidoStockLimitado. La coordinación se referencia en el [proyecto de ChatGPT](https://chatgpt.com/g/g-p-6aab578df9f88191b422b428e46ebdad-pedidos/project). El enlace identifica el espacio de coordinación; su contenido no se ha auditado desde este cierre documental.

## Alcance del apoyo

ChatGPT apoyó la descomposición del reto, la preparación de instrucciones por componente y la discusión de contratos/decisiones. Codex apoyó la generación y revisión de código repetitivo, modelos de intercambio, adaptadores, validaciones y pruebas, trabajando por módulos y con límites de alcance definidos por el responsable.

El uso incluyó Dockerfiles y Compose, diagnóstico de integración entre Java/.NET/Python/MongoDB, scripts E2E con consultas HTTP y Mongo, Angular y Module Federation, automatización de navegador con Playwright, y preparación/revisión de documentación. También se revisaron comandos antes de ejecutarlos, distinguiendo consultas de acciones que reconstruyen, reinician, alteran stock, restablecen datos o escriben evidencias.

## Criterio de aceptación

Las propuestas de IA **no se aceptaron automáticamente**. El proceso de supervisión contrastó las propuestas con el requerimiento, el código real, las colecciones y estados de MongoDB, las respuestas HTTP, la configuración/ejecución Docker y las ejecuciones E2E. Una respuesta de IA o un test redactado no se consideró evidencia de ejecución: se revisaron resultados, logs y efectos persistidos.

Las correcciones siguientes corresponden al historial de trabajo informado por el responsable. Los scripts finales y las evidencias permiten comprobar el comportamiento corregido; al no existir historial Git en esta copia, no se afirma disponer aquí de todas las versiones descartadas. Los PDF de referencia no están presentes en el repositorio inspeccionado: **PENDIENTE DE CIERRE**, incorporarlos y comprobar la trazabilidad completa contra sus versiones entregadas.

## Ejemplos de corrección y validación

| Caso | Corrección supervisada | Evidencia final conservada |
|---|---|---|
| E2E 01 | La primera prueba asumía una estructura incorrecta para los importes de respuesta. Se revisó el contrato y se corrigió la prueba para los campos reales, sin adaptar el servicio a una expectativa equivocada. | [Script](scripts/scenarios/e2e01_pedido_correcto.py), [resultado HTTP/Mongo](tests/evidencias/e2e01-pedido-correcto.json) |
| E2E 11 | La propuesta inicial de recuperación no coincidía con despachos-dotnet. Tras revisar la implementación, se recuperó una corrida Worker vencida sin reabrir indebidamente el pedido terminal. | [Script](scripts/scenarios/e2e11_tarea_repetida.py), [resultado](tests/evidencias/e2e11-tarea-repetida.json): aumentan Intentos/LeaseVersion sin repetir stock, guía ni pasos |
| E2E 12 | Una ventana temporal no era suficientemente reproducible. Se utilizó un proxy de integración controlado para crear la guía externa y retener la respuesta antes de matar despachos-dotnet. | [Script](scripts/scenarios/e2e12_reinicio_despachos.py), [proxy](tests/integration/e2e09_transportista_proxy.py), [resultado](tests/evidencias/e2e12-reinicio-despachos.json) |
| E2E 13 | Se corrigió `docker compose ps -q` por `docker compose ps -a -q` para obtener el contenedor detenido. | [Script](scripts/scenarios/e2e13_caida_mongodb.py), [resultado de recuperación](tests/evidencias/e2e13-caida-mongodb.json) |
| E2E 17 | Se corrigió la prueba de firma JWT manipulada para alterar bytes reales de la firma, manteniendo un JWT estructuralmente válido. | [Script](scripts/scenarios/e2e17_autenticacion.py), [resultado](tests/evidencias/e2e17-autenticacion.json): firma alterada rechazada por los tres servicios |
| E2E 18 | La automatización de login se ajustó al comportamiento real de la UI; durante el trabajo fue necesario instalar Chromium de Playwright. | [Automatización](frontend/web-host/tests/e2e18-role.mjs), [script](scripts/scenarios/e2e18_autorizacion_roles.py), [resultado](tests/evidencias/e2e18-autorizacion-roles.json): COMPRADOR/VENDEDOR no descargan el remoto |

Estos casos muestran un proceso iterativo de revisión y corrección: los contratos y el comportamiento observable determinaron la solución final. La instalación histórica de Chromium se consigna según el relato de ejecución; no se realizó una nueva instalación ni se afirma conservar aquí su log de instalación.

## Límites de esta documentación

El cierre documental leyó código, Dockerfiles, Compose, scripts, PRUEBAS.xlsx y evidencias. No volvió a ejecutar los E2E, no modificó código ni PRUEBAS.xlsx y no eliminó evidencias. Las ejecuciones previas se distinguen de las comprobaciones documentales actuales.

Los 21 escenarios figuran aprobados; el responsable y PRUEBAS.xlsx registran diez ejecuciones de E2E 04/05/16. En 04/05 la primera queda resumida como validación manual. **PENDIENTE DE CIERRE:** en 16 el resultado base coincide con repetición 10, por lo que solo se distinguen nueve cargas en los JSON disponibles. Se conserva esa discrepancia y se solicita cerrar su evidencia, sin fabricar otra ejecución.

No hay workflow CI en esta copia, ni evidencia de publicación/digests finales de imágenes. No se atribuyen aprobaciones de CI, hashes de publicación o tiempos de trabajo a partir de estimaciones de IA. Los pendientes están centralizados en [LEEME.md](LEEME.md).
