# Registro de decisiones — Encargo Unidad 3, Forma O (Cowork)

Este documento registra **cada decisión de diseño** del proyecto, **qué alternativas se descartaron y por qué**. Sirve como base para el informe (ABET 2: diseño con criterio) y para preparar la defensa oral.

**Contexto:** equipo de 3 personas · Python · entrega 17-11-2026.

## Cómo usar este documento

- Cada decisión tiene un ID (`D-XX`) que no se reutiliza.
- Si una decisión cambia, **no se borra**: se marca como `Reemplazada por D-YY` y se agrega la nueva.
- Las preguntas abiertas van en [Decisiones pendientes](#decisiones-pendientes) hasta cerrarse.

Estados posibles: `Aceptada` · `Pendiente` · `Reemplazada`.

---

## Índice

| ID | Tema | Decisión | Estado |
|---|---|---|---|
| D-01 | Lenguaje | Python | Aceptada |
| D-02 | Framework | FastAPI + `httpx` asíncrono | Aceptada |
| D-03 | API Gateway | Kong en modo DB-less | Aceptada |
| D-04 | Autenticación | JWT HS256 validado en Kong | Aceptada |
| D-05 | Rate limiting | Plugin `rate-limiting` de Kong por consumidor | Aceptada |
| D-06 | Estilo de Saga | Orquestación | Aceptada |
| D-07 | Saga vs 2PC | Saga | Aceptada |
| D-08 | Comunicación | HTTP síncrono, sin broker | Aceptada |
| D-09 | Ubicación del orquestador | Servicio propio `reservas` | Aceptada |
| D-10 | Fallback con circuito abierto | Rechazo previo + compensación | Aceptada |
| D-11 | Bases de datos | Un contenedor Postgres por servicio | Aceptada |
| D-12 | Regla "una franja, un cliente" | Índice único en BD | Aceptada |
| D-13 | Idempotencia | `sagaId` como clave de idempotencia | Aceptada |
| D-14 | Circuit Breaker | Implementación propia | Aceptada |
| D-15 | Bulkhead | `asyncio.Semaphore` con rechazo inmediato | Aceptada (precisada por D-43) |
| D-16 | Timeout | Timeout de `httpx` en toda llamada | Aceptada (precisada por D-40 y D-46) |
| D-17 | Retry | `tenacity`, solo en pasos idempotentes (opcional) | Reemplazada por D-44 |
| D-18 | Servicios externos | Simuladores con `/admin/chaos` | Aceptada |
| D-19 | Observabilidad | Prometheus + Grafana + logs JSON con `sagaId` | Aceptada |
| D-20 | Comparación "sin el patrón" | Variable `RESILIENCE_ENABLED` | Aceptada |
| D-21 | Pruebas de carga | k6 | Aceptada |
| D-22 | Cliente | Sin front; Postman / `.http` | Aceptada |
| D-23 | BFF | BFF Web con vista agregada de reserva | Aceptada |
| D-24 | Exposición | Solo Kong publica puerto | Aceptada |
| D-25 | Alcance | Mínimo completo, sin extras | Aceptada |
| D-26 | Reparto | 3 roles: exposición, saga, resiliencia | Aceptada |
| D-27 | Puertos de observabilidad | Grafana y Prometheus solo en `127.0.0.1` | Aceptada |
| D-28 | Trazabilidad de peticiones | Kong genera `X-Request-ID` | Aceptada |
| D-29 | Estructura del repositorio | Un directorio y Dockerfile por servicio, sin código compartido | Aceptada |
| D-30 | Forma de los contratos | Contrato en código (Pydantic + rutas) y OpenAPI exportado | Aceptada |
| D-31 | Estilo de pasos y compensaciones | POST de comando con `saga_id` en el body | Aceptada |
| D-32 | Representación de la franja | `fecha` + `bloque` de una hora (8 a 19) | Aceptada |
| D-33 | Precio | Lo define Espacios, nunca el cliente | Aceptada |
| D-34 | Respuesta de `POST /reservas` | Síncrona, con el resultado final de la saga | Aceptada |
| D-35 | Códigos de `POST /reservas` | Tabla por resultado de la saga | Aceptada |
| D-36 | Formato de errores | `detail` con `codigo` y `mensaje` | Aceptada |
| D-37 | Convenciones de la API | Nombres, tipos, encabezados, idempotencia | Aceptada |
| D-38 | Rutas públicas | Con prefijo: `/api/...` y `/bff/web/...` | Aceptada |
| D-39 | Compensación que llega antes que su paso | Registrar la saga como ANULADA | Aceptada |
| D-40 | Timeouts de los pasos | Por dependencia: Espacios 1 s, Pagos 2 s, Acceso 1,5 s | Aceptada |
| D-41 | Apertura del Circuit Breaker | ≥50 % de fallos en las últimas 10 llamadas (mínimo 5) | Aceptada |
| D-42 | Circuito abierto y semiabierto | 10 s abierto; 1 llamada de prueba | Aceptada |
| D-43 | Recurso que aísla el Bulkhead | Pool HTTP compartido de 20 + semáforo de 5 para Acceso | Aceptada |
| D-44 | Retry | En pasos y compensaciones, con reglas | Aceptada |
| D-45 | Compensar el paso que falló | Solo si su resultado es incierto | Aceptada |
| D-46 | Timeout de las compensaciones | 5 s, más largo que el de los pasos | Aceptada |
| D-47 | Timeout de Kong hacia `reservas` | 30 s, sin plazo interno en la saga | Aceptada |
| D-48 | Configuración de la resiliencia | Variables de entorno con valores por defecto | Aceptada |
| D-49 | Alcance de CB y Bulkhead | Solo sobre Acceso | Aceptada |
| D-50 | Activación de fallas | Script con `docker compose exec` + k6 dentro de la red | Aceptada |
| D-51 | Acceso a datos | SQLAlchemy ORM asíncrono sobre `asyncpg`, como Pagos y Acceso | Aceptada |
| D-52 | Modelo de datos de Espacios | Catálogo en BD, PK `saga_id`, ANULADA en la misma tabla, copia del precio | Aceptada |
| D-53 | Reglas del paso 1 | Repetición → 200; índice único; `422 FRANJA_PASADA` en hora local | Aceptada |
| D-54 | Frontera entre orquestador y resiliencia | Toda llamada a dependencias pasa por `app/resiliencia.py`; el orquestador decide qué hacer con el resultado | Pendiente de confirmar (rol B) |
| D-55 | Fuentes del BFF | 502 si fallan Espacios o Pagos; solo Acceso se degrada | Aceptada |

---

## 1. Tecnología base

### D-01 · Lenguaje: Python
- **Fecha:** 10-11-2026 · **Estado:** Aceptada
- **Decisión:** todos los servicios propios se escriben en Python.
- **Alternativas descartadas:**
  - *Java + Spring Boot + Resilience4j:* trae CB/Bulkhead/métricas listos, pero el equipo no lo domina y la defensa pregunta por cualquier línea.
  - *Node + Express + opossum:* buen CB, pero no es el lenguaje del equipo.
  - *.NET + Polly:* mismo motivo.
- **Justificación:** dominio del equipo; en una semana pesa más poder explicar el código que la cantidad de librerías disponibles.

### D-02 · Framework: FastAPI + `httpx` asíncrono
- **Fecha:** 10-11-2026 · **Estado:** Aceptada
- **Decisión:** FastAPI para los servicios y `httpx.AsyncClient` para las llamadas entre servicios.
- **Alternativas descartadas:**
  - *Flask + requests:* síncrono; el bulkhead exigiría pools de hilos y el modelo de concurrencia es menos claro.
  - *Django / DRF:* demasiado pesado para microservicios pequeños.
- **Justificación:** asíncrono nativo (encaja con semáforos y timeouts), liviano, y genera OpenAPI automáticamente (útil para el informe y para acordar contratos).

---

## 2. Exposición (Gateway + BFF)

### D-03 · API Gateway: Kong en modo DB-less
- **Fecha:** 10-11-2026 · **Estado:** Aceptada
- **Decisión:** Kong configurado declarativamente con un único `kong.yml`.
- **Alternativas descartadas:**
  - *Traefik:* no valida JWT de forma nativa (requiere ForwardAuth hacia otro servicio).
  - *NGINX open source:* sin validación JWT nativa (requiere njs o Lua).
  - *KrakenD:* valida JWT pero exige publicar un JWK set; más configuración.
  - *Gateway propio en FastAPI:* más código que mantener y riesgo de filtrar lógica de negocio en el gateway.
- **Justificación:** enrutamiento, JWT y rate limiting con configuración, sin código. Cumple por construcción el criterio "gateway sin lógica de negocio" de la rúbrica.

### D-04 · Autenticación: JWT HS256 validado en Kong
- **Fecha:** 10-11-2026 · **Estado:** Aceptada
- **Decisión:** Kong valida un JWT firmado con secreto compartido (plugin `jwt`). Los servicios internos confían en que la petición ya pasó por el gateway.
- **Alternativas descartadas:**
  - *Keycloak / OAuth2 completo:* contenedor pesado y mucha configuración para el alcance del encargo.
  - *API keys simples:* menos representativo de autenticación por token.
- **Justificación:** cumple "autenticación central" con el mínimo de piezas. El emisor del token queda en [P-01](#decisiones-pendientes).

### D-05 · Rate limiting: plugin `rate-limiting` de Kong por consumidor
- **Fecha:** 10-11-2026 · **Estado:** Aceptada
- **Decisión:** límite por consumidor (cliente identificado por el JWT), con política `local`.
- **Alternativas descartadas:**
  - *Rate limiting en cada servicio:* duplica lógica y no protege en la entrada.
  - *Política `redis`:* solo es necesaria con varias réplicas de Kong; agrega un contenedor sin beneficio aquí.
- **Justificación:** protege de picos y abuso en el único punto de entrada. Valores concretos en [P-02](#decisiones-pendientes).

### D-23 · BFF Web con vista agregada de reserva
- **Fecha:** 10-11-2026 · **Estado:** Aceptada
- **Decisión:** un BFF Web con, al menos, `GET /mis-reservas/{id}`, que compone en una sola respuesta: datos del espacio (Espacios), estado del pago (Pagos) y estado/QR (Acceso). Si Acceso no responde, devuelve la respuesta igual con `"qr": "no disponible"` (degradación elegante).
- **Alternativas descartadas:**
  - *BFF móvil:* no aporta diferencia para el encargo; con uno basta.
  - *Agregación en el gateway:* viola la separación de responsabilidades.
- **Justificación:** cumple "agrega ≥ 2 servicios" y sirve además como evidencia de que el sistema sigue funcionando con Acceso caído.

### D-24 · Solo Kong publica puerto al exterior
- **Fecha:** 10-11-2026 · **Estado:** Aceptada
- **Decisión:** en `docker-compose.yml` solo Kong tiene `ports:`. BFF, `reservas`, servicios de dominio y bases de datos quedan en la red interna.
- **Alternativas descartadas:**
  - *Exponer también el BFF:* permitido por el enunciado, pero abriría una segunda entrada que salta la autenticación y el rate limiting.
- **Justificación:** un único punto de entrada, fácil de demostrar (intentar llamar a un servicio interno desde fuera falla).

### D-55 · El BFF responde 502 si fallan Espacios o Pagos; solo Acceso se degrada
- **Fecha:** 23-11-2026 · **Estado:** Aceptada · **Precisa:** D-23
- **Decisión:** `GET /mis-reservas/{saga_id}` consulta las tres fuentes en paralelo, cada una con su timeout (D-40) y su propio pool HTTP.
  - *Acceso* es una fuente opcional: si da timeout, error o está caído, la respuesta es `200` con `degradado: true`, `acceso.qr: "no disponible"` y `no_disponibles: ["ACCESO"]`. Si Acceso responde `ACCESO_NO_EXISTE`, la saga no habilitó la puerta y la respuesta es `200` con `acceso.qr: null` (no es una degradación).
  - *Espacios* y *Pagos* son fuentes obligatorias: si dan timeout, error o están caídas, el BFF responde `502` con `ESPACIOS_FALLO` o `PAGOS_FALLO` (si fallan ambas, `ESPACIOS_FALLO`). `RESERVA_NO_EXISTE` de Espacios es `404`; `COBRO_NO_EXISTE` de Pagos es `200` con `pago: null`.
  - Un `404` que no trae el código de "no existe" esperado (p. ej. una ruta inexistente) cuenta como fallo de la fuente, no como ausencia de datos.
- **Alternativas descartadas:**
  - *Respuesta parcial para las tres fuentes (`espacio: null`, `pago: null`):* una vista sin el espacio o sin el estado del pago puede leerse como "no hay reserva" o "no pagué", y el cliente actuaría sobre un dato falso. Con Acceso no pasa: su ausencia solo afecta al QR y se informa explícitamente.
  - *502 también cuando falla Acceso:* contradice D-23 y quita al BFF su papel de evidencia de que el sistema sigue funcionando con la puerta caída (escenario 3).
  - *Consultas en serie:* la latencia sería la suma de las tres fuentes en vez de la mayor.
- **Justificación:** separa lo que hace inútil la vista (el espacio y el pago) de lo que solo la empobrece (el QR). El `502` indica que una dependencia falló de verdad. Un pool por dependencia evita que una fuente lenta agote las conexiones de las otras.
- **Consecuencia:** cambia `services/bff-web/app/contrato.py` (`espacio` pasa a ser obligatorio, `FuenteDatos` solo contiene `ACCESO`, nuevos códigos `ESPACIOS_FALLO` y `PAGOS_FALLO`). Hay que regenerar `docs/api/bff-web.json` con `scripts/exportar_contratos.py`.

---

## 3. Transacción distribuida (Saga)

### D-06 · Estilo de Saga: orquestación
- **Fecha:** 10-11-2026 · **Estado:** Aceptada
- **Decisión:** un orquestador ejecuta los pasos y, ante fallo, las compensaciones en orden inverso.
- **Alternativas descartadas:**
  - *Coreografía por eventos:* requiere broker, el flujo queda repartido entre servicios y el orden inverso de compensaciones es más difícil de garantizar y de evidenciar; no cabe en el plazo.
- **Justificación:**
  - Son 3 pasos lineales: el flujo cabe completo y legible en un solo lugar.
  - El orden inverso de compensaciones queda explícito en código.
  - Todas las llamadas a Acceso pasan por el orquestador: es el sitio natural para timeout, CB y bulkhead.
  - El estado de cada saga queda persistido (saga log), lo que facilita la evidencia.

### D-07 · Saga en lugar de Two-Phase Commit
- **Fecha:** 10-11-2026 · **Estado:** Aceptada
- **Decisión:** consistencia eventual con compensaciones (Saga).
- **Alternativas descartadas:**
  - *Two-Phase Commit:*
    - Pagos (pasarela) y Acceso (controlador de puerta) son **externos**: no implementan una fase de *prepare* ni aceptan quedar bloqueados.
    - 2PC mantiene bloqueos mientras espera votos: un controlador lento bloquearía la reserva del espacio para todos.
    - El coordinador es un punto único de falla y la disponibilidad total baja con cada participante.
- **Justificación:** con participantes externos e inestables, solo es viable una transacción basada en compensaciones.

### D-08 · Comunicación: HTTP síncrono, sin broker
- **Fecha:** 10-11-2026 · **Estado:** Aceptada
- **Decisión:** el orquestador llama a cada servicio por HTTP.
- **Alternativas descartadas:**
  - *RabbitMQ / Kafka:* necesarios solo para coreografía (descartada en D-06); agregan infraestructura y otro punto de falla.
- **Justificación:** timeout, Circuit Breaker y bulkhead se aplican naturalmente sobre llamadas HTTP, y el flujo es más simple de seguir en logs.

### D-09 · El orquestador vive en un servicio propio: `reservas`
- **Fecha:** 10-11-2026 · **Estado:** Aceptada
- **Decisión:** servicio `reservas` dedicado a la Saga, con su propia base (saga log).
- **Alternativas descartadas:**
  - *En el gateway:* viola "gateway sin lógica de negocio".
  - *En el BFF:* el BFF es por cliente; si mañana hay un BFF móvil, la saga quedaría duplicada.
  - *Dentro de Espacios:* acopla un servicio de dominio a los otros dos.
- **Justificación:** separación de responsabilidades clara y defendible.

### D-10 · Fallback con el circuito de Acceso abierto
- **Fecha:** 10-11-2026 · **Estado:** Aceptada
- **Decisión:** dos niveles:
  1. **Rechazo previo:** si el circuito de Acceso está abierto, `reservas` no inicia la saga y responde de inmediato "reservas temporalmente suspendidas" (no se reserva ni se cobra).
  2. **Compensación:** si Acceso falla con el circuito cerrado (timeout o error en el paso 3), se revoca/reembolsa/libera en orden inverso, como exige la regla 2.4.
- **Alternativas descartadas:**
  - *Solo compensar:* cobra y reembolsa a clientes cuando ya se sabía que la puerta no responde; peor experiencia y más movimientos de dinero.
  - *Dejar la reserva "pendiente de QR" y reintentar más tarde:* contradice la regla 2.4 ("si la puerta no habilita, se compensan el cobro y la reserva") y agrega estado intermedio difícil de evidenciar.
- **Justificación:** degradación elegante real (fail-fast sin efectos laterales) sin romper la regla de negocio.

### D-12 · Regla "una franja, un cliente": índice único en BD
- **Fecha:** 10-11-2026 · **Estado:** Aceptada
- **Decisión:** índice único `(espacio_id, franja)` sobre las reservas activas en la base de Espacios. Precisada por D-32: el índice es `(espacio_id, fecha, bloque)` sobre las reservas en estado `RESERVADA`.
- **Alternativas descartadas:**
  - *Validar solo en código ("¿existe ya?" y luego insertar):* condición de carrera con peticiones concurrentes; dos clientes podrían quedar con la misma franja.
- **Justificación:** la base garantiza la regla incluso bajo carga, lo que se puede demostrar con k6.

### D-13 · Idempotencia: `sagaId` como clave de idempotencia
- **Fecha:** 10-11-2026 · **Estado:** Aceptada
- **Decisión:** cada paso y cada compensación recibe el `sagaId`. Cada servicio registra las operaciones ya procesadas (restricción única por `sagaId` + operación) y, ante un repetido, devuelve el resultado anterior sin re-ejecutar.
  - Cobrar dos veces el mismo `sagaId` → un solo cobro.
  - Reembolsar algo ya reembolsado → no hace nada.
  - Liberar/revocar algo ya liberado/revocado → no hace nada.
- **Alternativas descartadas:**
  - *Confiar en que no habrá reintentos:* falso con timeouts (la petición pudo ejecutarse aunque la respuesta no llegara) y con retry.
- **Justificación:** requisito explícito del enunciado y condición necesaria para usar retry de forma segura.

---

## 4. Resiliencia

### D-14 · Circuit Breaker: implementación propia
- **Fecha:** 10-11-2026 · **Estado:** Aceptada
- **Decisión:** clase propia (~50 líneas) con estados cerrado → abierto → semiabierto, umbral de fallos y tiempo de espera antes de probar. Expone su estado como métrica.
- **Alternativas descartadas:**
  - *`pybreaker`:* soporte asíncrono deficiente.
  - *`aiobreaker` / `purgatory`:* funcionan, pero son una caja negra poco conocida que habría que explicar igual en la defensa.
- **Justificación:** se entiende y se explica línea por línea; control total sobre las métricas expuestas.

### D-15 · Bulkhead: `asyncio.Semaphore` con rechazo inmediato
- **Fecha:** 10-11-2026 · **Estado:** Aceptada
- **Decisión:** en `reservas`, las llamadas a Acceso pasan por un semáforo de N cupos. Si no hay cupo, se rechaza al instante (HTTP 503) y se incrementa un contador de rechazos.
- **Alternativas descartadas:**
  - *Semáforo con espera en cola:* las peticiones se acumulan y la latencia del sistema crece igual; no contiene la falla.
  - *Pool de hilos separado por dependencia:* más complejo y poco natural en asyncio.
- **Justificación:** aísla el recurso que consume la dependencia lenta para que el resto (consultas, BFF) siga respondiendo. Tamaño N en [P-03](#decisiones-pendientes).

### D-16 · Timeout en toda llamada entre servicios
- **Fecha:** 10-11-2026 · **Estado:** Aceptada
- **Decisión:** `httpx` con timeout explícito en cada cliente HTTP; nunca se usa el valor por defecto.
- **Alternativas descartadas:** ninguna razonable (sin timeout, una dependencia lenta retiene conexiones indefinidamente).
- **Justificación:** requisito del enunciado; base para que el CB cuente fallos por lentitud. Valores en [P-03](#decisiones-pendientes).

### D-17 · Retry con backoff: `tenacity`, solo en pasos idempotentes (opcional)
- **Fecha:** 10-11-2026 · **Estado:** Reemplazada por D-44
- **Decisión:** si hay tiempo, retry con backoff exponencial y pocos intentos, solo en operaciones idempotentes (D-13). No es obligatorio en la rúbrica.
- **Alternativas descartadas:**
  - *Retry sobre la dependencia con el CB abierto:* el CB debe cortar; reintentar contra un circuito abierto anula su propósito.
  - *Retry sin idempotencia:* riesgo de doble cobro.
- **Justificación:** mejora la tolerancia a fallos transitorios sin comprometer la consistencia.

### D-18 · Servicios externos simulados con inyección de fallas
- **Fecha:** 10-11-2026 · **Estado:** Aceptada
- **Decisión:** Pagos (pasarela) y Acceso (controlador de puerta) son simuladores propios con un endpoint `POST /admin/chaos` y modos `ok`, `slow` (con `delayMs`), `error` y `down`. La caída real se provoca con `docker compose stop acceso`.
- **Alternativas descartadas:**
  - *Toxiproxy:* potente, pero es otro componente que configurar y explicar.
  - *Provocar fallas a mano editando código o deteniendo procesos al azar:* no reproducible.
- **Justificación:** escenarios de falla reproducibles con un comando, documentables en el README (criterio de ABET 6).

---

## 5. Datos

### D-11 · Un contenedor Postgres por servicio
- **Fecha:** 10-11-2026 · **Estado:** Aceptada
- **Decisión:** `db-espacios`, `db-pagos`, `db-acceso` y `db-reservas` (saga log), cada uno en su contenedor.
- **Alternativas descartadas:**
  - *Un servidor Postgres con varias bases:* válido, pero el aislamiento es menos evidente y una caída del servidor afecta a todos.
  - *SQLite por servicio:* concurrencia de escritura limitada; peor para demostrar la regla de la franja bajo carga.
- **Justificación:** "cada servicio con su propia base" queda explícito en el diagrama y en el Compose, con poco costo adicional.

### D-51 · Acceso a datos: SQLAlchemy ORM asíncrono sobre `asyncpg`
- **Fecha:** 20-11-2026 · **Estado:** Aceptada · **Cierra:** P-04
- **Decisión:** Espacios y `reservas` usan SQLAlchemy 2 en modo asíncrono con el ORM (`db.py` + `modelos.py`), igual que Pagos y Acceso. Las tablas se crean al arrancar con `create_all`, sin migraciones.
- **Alternativas descartadas:**
  - *SQLAlchemy Core sin ORM:* más cerca del SQL ejecutado, pero con un estilo distinto al del resto del repositorio.
  - *`asyncpg` directo con SQL a mano:* sin abstracción, pero obliga a manejar pool, transacciones y conversión de filas a mano, y rompe la consistencia con Pagos y Acceso.
- **Justificación:** los cuatro servicios con base de datos comparten el mismo patrón, que cualquiera del equipo puede leer y defender. La regla de la franja (D-12) y la idempotencia (D-13) siguen garantizadas en la base: índice único parcial declarado en el modelo e `INSERT ... ON CONFLICT`.

### D-52 · Modelo de datos de Espacios
- **Fecha:** 23-11-2026 · **Estado:** Aceptada
- **Decisión:**
  - **Catálogo en la base:** tabla `espacios` (id, nombre, tipo, precio) sembrada al arrancar con `INSERT ... ON CONFLICT DO NOTHING`. Las reservas la referencian con clave foránea.
  - **Clave primaria `saga_id`** en `reservas_espacio`, como Pagos y Acceso: la base impide que una saga reserve dos veces.
  - **Saga anulada (D-39) en la misma tabla:** fila con estado `ANULADA` y las columnas de reserva nulas.
  - **Copia del precio en la reserva:** se guarda el precio vigente al reservar.
- **Alternativas descartadas:**
  - *Catálogo como constante en el código:* sin clave foránea, y cambiar un precio obliga a reconstruir la imagen.
  - *Catálogo cargado desde un archivo semilla aparte:* un archivo más que mantener, sin beneficio para el alcance.
  - *Id propio + `saga_id` único:* mismas garantías con una columna más.
  - *Tabla aparte `sagas_anuladas`:* evita columnas nulas, pero el paso 1 tendría que consultar dos tablas.
  - *Leer siempre el precio del catálogo:* un cambio de precio alteraría lo que muestran las reservas ya cobradas.
- **Justificación:** el mismo patrón que Pagos y Acceso, y lo cobrado queda fijo aunque cambie el catálogo.

### D-53 · Reglas del paso 1 (reservar espacio)
- **Fecha:** 23-11-2026 · **Estado:** Aceptada
- **Decisión:**
  - **Repetición con el mismo `saga_id`:** responde `200` con la reserva original, aunque traiga otros datos (como Pagos y Acceso).
  - **Bloque ocupado:** solo el índice único lo detecta. El `INSERT` usa `ON CONFLICT` sobre `saga_id`; si otra saga tiene el bloque, Postgres rechaza la sentencia por el índice `un_cliente_por_bloque` y se responde `409 FRANJA_OCUPADA`.
  - **Bloques pasados:** se rechaza con `422 FRANJA_PASADA` un bloque que ya empezó en hora local del cowork (`America/Santiago`, configurable con `ESPACIOS_ZONA_HORARIA`). Una repetición de una reserva ya hecha no se rechaza por esto.
  - **Observabilidad:** contador `espacios_operaciones_total{operacion,resultado}` y una línea de log por resultado.
- **Alternativas descartadas:**
  - *`409` si la repetición trae datos distintos:* en este sistema el `saga_id` lo genera `reservas` y siempre reenvía los mismos datos; agregaría un caso sin uso real.
  - *Consulta previa y luego `INSERT`:* dos caminos para el mismo error; el índice igual es necesario por las carreras.
  - *Aceptar fechas pasadas:* permitiría reservar (y cobrar) una hora que ya pasó.
  - *Rechazar solo días anteriores:* hoy se podría reservar un bloque que ya terminó.
  - *UTC:* el bloque 9 quedaría desfasado 3 horas respecto al cowork.
  - *`409 FRANJA_PASADA`:* `409` indica conflicto con el estado; un bloque pasado es un dato inválido.
- **Evidencia:** con 20 sagas simultáneas por el mismo bloque, exactamente una recibe `201` y las demás `409 FRANJA_OCUPADA`.

---

## 6. Observabilidad y evidencia

### D-19 · Prometheus + Grafana + logs JSON con `sagaId`
- **Fecha:** 10-11-2026 · **Estado:** Aceptada
- **Decisión:**
  - `prometheus-client` en `reservas` (y donde aporte): estado del CB (gauge), rechazos del bulkhead (counter), sagas completadas / compensadas / rechazadas (counter), latencia de llamadas (histogram).
  - Prometheus + Grafana con un dashboard **provisionado en el repo**, para que aparezca listo con `docker compose up`.
  - Logs estructurados en JSON con `sagaId` y paso, para seguir una saga completa y mostrar el orden inverso de compensaciones.
  - Respaldo si falta tiempo: logs + resumen de k6.
- **Alternativas descartadas:**
  - *Solo logs:* no muestran tendencias ni el antes/después de forma visual.
  - *ELK / Loki:* pesados para el alcance.
  - *Tracing distribuido (Jaeger / OpenTelemetry):* deseable, pero fuera del plazo.
- **Justificación:** la evidencia ante fallas vale el 40% de la nota; el dashboard produce directamente las capturas del antes/después.

### D-20 · Comparación "sin el patrón": variable `RESILIENCE_ENABLED`
- **Fecha:** 10-11-2026 · **Estado:** Aceptada
- **Decisión:** con `RESILIENCE_ENABLED=false`, `reservas` llama a Acceso sin CB ni bulkhead (mantiene el timeout para no colgarse indefinidamente durante la demo).
- **Alternativas descartadas:**
  - *Explicar solo en teoría qué pasaría:* la rúbrica pide interpretar la evidencia y qué habría pasado sin el patrón; una medición real es mucho más convincente.
  - *Mantener dos ramas de código:* difícil de sincronizar.
- **Justificación:** el mismo experimento con y sin patrón da una comparación directa.

### D-21 · Pruebas de carga: k6
- **Fecha:** 10-11-2026 · **Estado:** Aceptada
- **Decisión:** scripts de k6 en el repo, ejecutables con la imagen Docker oficial (sin instalar nada).
- **Alternativas descartadas:**
  - *Locust:* es Python, pero necesita interfaz o configuración extra para resúmenes reproducibles.
  - *hey / ab:* demasiado básicos para escenarios con varias etapas (rampa, pico).
  - *JMeter:* pesado y basado en GUI.
- **Justificación:** escenarios de pico reproducibles con umbrales y un resumen final citable en el informe.

---

## 7. Alcance y organización

### D-22 · Sin front; cliente con Postman o archivos `.http`
- **Fecha:** 10-11-2026 · **Estado:** Aceptada
- **Decisión:** la demo se hace con una colección de Postman y/o scripts `curl`/`.http` versionados.
- **Alternativas descartadas:**
  - *Front web:* no se evalúa y consume días del plazo.
- **Justificación:** el BFF es una API; el esfuerzo se concentra en evidencia.

### D-25 · Alcance: mínimo completo del enunciado, sin extras
- **Fecha:** 10-11-2026 · **Estado:** Aceptada
- **Decisión:** no se pide reducción de alcance al docente; se implementa todo el mínimo del enunciado y se recortan extras (broker, front, Keycloak, tracing, retry avanzado).
- **Alternativas descartadas:**
  - *Pedir alcance reducido por ser 3:* el mínimo es abarcable y pedir reducción podría limitar la nota.
- **Justificación:** "una solución modesta bien justificada y evidenciada vale más que una ambiciosa".

### D-26 · Reparto en 3 roles
- **Fecha:** 10-11-2026 · **Estado:** Aceptada
- **Decisión:**

  | Rol | Responsable | Componentes |
  |---|---|---|
  | A · Exposición e infraestructura | Nicolás López | `docker-compose.yml`, Kong (JWT + rate limiting), emisión de tokens, BFF Web |
  | B · Saga y dominio | Sofía López | `reservas` (orquestador + saga log), compensaciones, idempotencia, servicio Espacios |
  | C · Resiliencia y evidencia | Benjamín Espinoza | Simuladores Pagos y Acceso con `/admin/chaos`, CB, bulkhead, timeouts, Prometheus/Grafana, k6 |

  Informe y video: entre todos, cada uno su parte.

  Carpetas del repositorio por rol:

  | Carpeta | Componente | Rol |
  |---|---|---|
  | `docker-compose.yml` | Orquestación de contenedores | A |
  | `gateway/` | Kong DB-less | A |
  | `scripts/generar_token.py` | Emisión provisoria de JWT | A |
  | `services/bff-web/` | BFF Web | A |
  | `services/reservas/` | Orquestador de la Saga (capa de resiliencia hacia Acceso: C) | B |
  | `services/espacios/` | Espacios | B |
  | `services/pagos/` | Pagos (simulador) | C |
  | `services/acceso/` | Acceso (simulador) | C |
  | `observability/` | Prometheus + Grafana | C |
  | `k6/` | Pruebas de carga y humo | C |
  | `README.md` | Documentación del proyecto | Todos |
- **Justificación:** cada rol tiene commits identificables y un área que defender en la oral.

### Calendario de referencia

| Fecha | Hito |
|---|---|
| 10-11 | Decisiones, esqueleto del repo y Compose, contratos de API |
| 11–12-11 | Servicios de dominio, Kong enrutando, camino feliz de la Saga (escenario 1) |
| 13-11 | Compensaciones, idempotencia, BFF (escenario 2) |
| 14-11 | Inyección de fallas, CB, bulkhead, métricas (escenario 3) |
| 15-11 | Pruebas de carga y capturas con/sin patrón — **congelar código** |
| 16-11 | Informe, diagramas, video |
| 17-11 | Margen y entrega |

---

## 8. Decisiones del esqueleto

### D-27 · Grafana y Prometheus publicados solo en `127.0.0.1`
- **Fecha:** 10-11-2026 · **Estado:** Aceptada
- **Decisión:** Grafana (`127.0.0.1:3000`) y Prometheus (`127.0.0.1:9090`) publican puerto solo en la interfaz local. No forman parte de la API del sistema: son herramientas para capturar evidencia.
- **Alternativas descartadas:**
  - *No publicarlos:* no se podría ver el dashboard durante la demo.
  - *Publicarlos en todas las interfaces:* expone herramientas internas sin autenticación.
  - *Pasarlos por Kong:* mezcla tráfico de observabilidad con el de negocio y lo sometería al rate limiting.
- **Justificación:** mantiene D-24 para el tráfico de negocio (Kong como única entrada) y permite mostrar la evidencia en vivo.

### D-28 · Kong genera `X-Request-ID` (plugin `correlation-id`)
- **Fecha:** 10-11-2026 · **Estado:** Aceptada
- **Decisión:** Kong asigna un UUID a cada petición, lo envía a los servicios y lo devuelve al cliente.
- **Alternativas descartadas:**
  - *Generarlo en cada servicio:* no correlaciona la petición de punta a punta.
- **Justificación:** junto al `sagaId` (D-19), permite seguir una petición desde el gateway hasta cada paso en los logs. Costo: una línea de configuración.

### D-29 · Un directorio y Dockerfile por servicio, sin código compartido
- **Fecha:** 10-11-2026 · **Estado:** Aceptada
- **Decisión:** cada servicio en `services/<nombre>/` con su `Dockerfile`, `requirements.txt` y `app/`. No hay librería común entre servicios.
- **Alternativas descartadas:**
  - *Paquete `common/` compartido (logging, cliente HTTP):* menos duplicación, pero acopla los despliegues y complica los contextos de build de Docker.
- **Justificación:** servicios independientes, como se espera de microservicios; la duplicación es mínima (configuración de logging y métricas).

---

## 9. Contratos de API

Dónde está cada contrato:

| Servicio | Modelos | Rutas | OpenAPI exportado |
|---|---|---|---|
| reservas | `services/reservas/app/contrato.py` | `services/reservas/app/main.py` | `docs/api/reservas.json` |
| espacios | `services/espacios/app/contrato.py` | `services/espacios/app/main.py` | `docs/api/espacios.json` |
| pagos | `services/pagos/app/contrato.py` | `services/pagos/app/main.py` | `docs/api/pagos.json` |
| acceso | `services/acceso/app/contrato.py` | `services/acceso/app/main.py` | `docs/api/acceso.json` |
| bff-web | `services/bff-web/app/contrato.py` | `services/bff-web/app/main.py` | `docs/api/bff-web.json` |

Resumen de rutas:

| Servicio | Ruta | Uso |
|---|---|---|
| reservas | `POST /reservas` · `GET /reservas/{saga_id}` | Ejecuta la saga · consulta la saga y su saga log |
| espacios | `GET /espacios?fecha=` | Disponibilidad por fecha |
| espacios | `POST /reservas-espacio` · `POST /reservas-espacio/{saga_id}/liberar` · `GET /reservas-espacio/{saga_id}` | Paso 1 · compensación · consulta |
| pagos | `POST /cobros` · `POST /cobros/{saga_id}/reembolso` · `GET /cobros/{saga_id}` | Paso 2 · compensación · consulta |
| acceso | `POST /accesos` · `POST /accesos/{saga_id}/revocar` · `GET /accesos/{saga_id}` | Paso 3 · compensación · consulta |
| pagos, acceso | `GET /admin/chaos` · `POST /admin/chaos` | Ver y cambiar el modo de falla |
| bff-web | `GET /mis-reservas/{saga_id}` | Vista agregada de Espacios + Pagos + Acceso |

Cómo cambiar un contrato: editar `app/contrato.py` y/o las rutas del servicio, avisar al equipo, y regenerar el OpenAPI con `python scripts/exportar_contratos.py` (usa Docker; no requiere instalar FastAPI). El diff de `docs/api/*.json` muestra el cambio.

### D-30 · Contrato escrito en código y OpenAPI exportado
- **Fecha:** 11-11-2026 · **Estado:** Aceptada · **Cierra:** P-05
- **Decisión:** antes de implementar, cada servicio define su contrato en código: modelos Pydantic en `app/contrato.py` y rutas en `app/main.py` con `response_model`, código de estado y respuestas de error documentadas. Las rutas responden `501 NO_IMPLEMENTADO` hasta que se implementen. El OpenAPI generado por FastAPI se exporta a `docs/api/<servicio>.json` y se versiona.
- **Alternativas descartadas:**
  - *Code-first sin acuerdo previo:* el contrato existiría recién al terminar el código; bloquea a quien consume el servicio.
  - *OpenAPI en YAML escrito a mano:* verboso, se mantiene en dos lugares y se desalinea del código.
  - *Contrato en Markdown:* rápido, pero no verificable y se desactualiza.
  - *Modelos Pydantic compartidos en un paquete común:* contradice D-29 y acopla despliegues.
- **Justificación:** se acuerda antes de implementar, no hay duplicación (el contrato es el código), cada uno ve el contrato de los demás en `/docs` y el JSON exportado sirve para el informe.

### D-31 · Pasos y compensaciones como POST de comando con `saga_id` en el body
- **Fecha:** 11-11-2026 · **Estado:** Aceptada
- **Decisión:** cada paso es `POST /<recurso>` con `saga_id` en el body, y cada compensación es `POST /<recurso>/{saga_id}/<accion>` (`liberar`, `reembolso`, `revocar`). La idempotencia la da `saga_id` (D-13).
- **Alternativas descartadas:**
  - *PUT y DELETE identificados por `saga_id`:* idempotentes por definición de HTTP, pero un reembolso no es "borrar un cobro"; DELETE queda mal en Pagos.
  - *POST con encabezado `Idempotency-Key` en cada servicio:* es como funcionan las pasarelas reales, pero obliga a guardar respuestas por clave en los tres servicios.
- **Justificación:** cada paso y compensación tiene nombre propio, lo que hace legible el flujo en logs y en el saga log.

### D-32 · La franja es `fecha` + `bloque` de una hora
- **Fecha:** 11-11-2026 · **Estado:** Aceptada
- **Decisión:** `fecha` (AAAA-MM-DD) y `bloque` (entero de 8 a 19, hora de inicio; el bloque cubre `[bloque:00, bloque+1:00)`). Una reserva ocupa un bloque.
- **Alternativas descartadas:**
  - *Rango libre `inicio`/`fin`:* más realista, pero detectar solapamientos exige una restricción de exclusión en Postgres (`tstzrange` + `btree_gist`).
  - *Texto libre:* dos textos distintos pueden describir la misma franja y la regla se puede saltar.
- **Justificación:** la regla "un bloque, un cliente" queda en un índice único `(espacio_id, fecha, bloque)` (D-12), simple de implementar y de demostrar bajo carga.

### D-33 · El precio lo define Espacios
- **Fecha:** 11-11-2026 · **Estado:** Aceptada
- **Decisión:** el cliente no envía monto. Espacios devuelve `precio` al reservar (paso 1) y el orquestador lo usa para cobrar (paso 2).
- **Alternativas descartadas:**
  - *El cliente envía el monto:* un cliente podría pagar lo que quisiera.
- **Justificación:** el precio queda en el servicio dueño de esos datos.

### D-34 · `POST /reservas` responde de forma síncrona
- **Fecha:** 11-11-2026 · **Estado:** Aceptada
- **Decisión:** la petición espera a que la saga termine y responde con su resultado final. `GET /reservas/{saga_id}` permite consultar la saga y su saga log después.
- **Alternativas descartadas:**
  - *Asíncrona (`202 Accepted` + consulta posterior):* más robusta, pero exige ejecutar la saga en segundo plano y manejar la caída del orquestador a mitad de camino; más difícil de demostrar en vivo.
- **Justificación:** simple y fácil de demostrar. La espera está acotada por los timeouts y el Circuit Breaker. Sin el patrón (D-20), la petición queda colgada, lo que sirve como evidencia.
- **Consecuencia:** el `read_timeout` de Kong hacia `reservas` debe ser mayor que la peor duración posible de una saga (timeouts de los 3 pasos + compensaciones). Coordinar con P-03.

### D-35 · Códigos de respuesta de `POST /reservas`
- **Fecha:** 11-11-2026 · **Estado:** Aceptada
- **Decisión:** el cuerpo es siempre `SagaOut` (con `saga_id`, `estado`, `error` y `pasos`). El código depende del resultado:

  | Resultado | Código | Estado | `error.codigo` |
  |---|---|---|---|
  | Los tres pasos se confirmaron | `201` | `CONFIRMADA` | — |
  | Repetición con la misma `Idempotency-Key` | `200` | el de la saga original | — |
  | El espacio no existe (paso 1) | `404` | `RECHAZADA` | `ESPACIO_NO_EXISTE` |
  | La franja estaba ocupada (paso 1) | `409` | `RECHAZADA` | `FRANJA_OCUPADA` |
  | El bloque ya empezó (paso 1, D-53) | `422` | `RECHAZADA` | `FRANJA_PASADA` |
  | El pago fue rechazado (paso 2) | `402` | `COMPENSADA` | `PAGO_RECHAZADO` |
  | Una dependencia falló o no respondió a tiempo | `502` | `COMPENSADA` | `ESPACIOS_FALLO` / `PAGOS_FALLO` / `ACCESO_FALLO` |
  | Además falló una compensación | `502` | `COMPENSACION_PENDIENTE` | `COMPENSACION_FALLIDA` |
  | Circuito de Acceso abierto antes de empezar (D-10) | `503` + `Retry-After` | `RECHAZADA` | `ACCESO_NO_DISPONIBLE` |
  | Circuito abierto o Bulkhead sin cupo al llegar al paso 3 | `503` + `Retry-After` | `COMPENSADA` | `ACCESO_NO_DISPONIBLE` / `ACCESO_SATURADO` |

- **Regla para leer los códigos:** `502` significa que una dependencia falló de verdad; `503` significa que los patrones de resiliencia cortaron la llamada (fail-fast). Así la evidencia distingue "falló Acceso" de "el patrón protegió al sistema".
- **Casos agregados al acordar los contratos** (no estaban en la propuesta original): fallas técnicas de Espacios y Pagos (`502`), compensación fallida y rechazo del Bulkhead.
- **Justificación:** el resultado de la saga se lee directo en la respuesta, sin revisar logs.

### D-36 · Formato de errores: `detail` con `codigo` y `mensaje`
- **Fecha:** 11-11-2026 · **Estado:** Aceptada
- **Decisión:** los errores de petición responden `{"detail": {"codigo": "FRANJA_OCUPADA", "mensaje": "..."}}`. Los códigos son constantes en MAYÚSCULAS listadas en `CodigoError` de cada `contrato.py`. Las validaciones automáticas de FastAPI (`422`) mantienen su formato.
- **Excepción:** el resultado de una saga no es un error de la petición; `POST /reservas` responde siempre `SagaOut`, con el mismo objeto `{codigo, mensaje}` en su campo `error` (D-35).
- **Alternativas descartadas:**
  - *Formato por defecto de FastAPI (`{"detail": "texto"}`):* el orquestador tendría que interpretar textos para distinguir errores de negocio de errores técnicos.
  - *RFC 9457 (Problem Details):* estándar, pero exige un manejador de excepciones en cada servicio.
- **Justificación:** una línea por error y el orquestador decide según el código (compensar sin reintentar, o contar para el Circuit Breaker).

### D-37 · Convenciones de la API
- **Fecha:** 11-11-2026 · **Estado:** Aceptada
- **Decisión:** todos los servicios siguen estas convenciones:
  - **Rutas:** sustantivos en español, plural, en kebab-case (`/reservas-espacio`). Sin versión (`/v1`): hay una sola versión de la API.
  - **Campos JSON:** snake_case en español (`saga_id`, `espacio_id`, `actualizado_en`). Se aceptan términos técnicos establecidos (`qr`, `delay_ms`).
  - **Enumeraciones:** valores en MAYÚSCULAS (`CONFIRMADA`, `RESERVADA`). Excepción: los modos de inyección de fallas (`ok`, `slow`, `error`, `down`), que mantienen los nombres de D-18.
  - **Identificadores:**
    - `saga_id`: UUID v4 generado por `reservas` al iniciar la saga; es la clave de idempotencia de todos los pasos y compensaciones.
    - `espacio_id`: legible, p. ej. `SALA-A`, `PUESTO-01`.
    - `cliente_id`: el nombre del consumidor de Kong (`cliente-demo`).
    - `cobro_id`: lo genera Pagos.
  - **Fechas y horas:** `fecha` en ISO 8601 (AAAA-MM-DD); marcas de tiempo en ISO 8601 con zona horaria, con nombres terminados en `_en` (`creada_en`, `actualizada_en`).
  - **Montos:** enteros en pesos chilenos (`monto`, `precio`).
  - **Encabezados:**
    - `X-Consumer-Username`: lo agrega Kong al validar el JWT. Solo `reservas` lo lee y lo pasa como `cliente_id` en el body a los demás servicios.
    - `X-Request-ID`: lo genera Kong (D-28). Todo servicio lo reenvía en sus llamadas salientes y lo incluye en sus logs.
    - `Idempotency-Key`: opcional en `POST /reservas`; si el cliente repite la petición con la misma clave, recibe la misma saga y no se cobra dos veces.
  - **Idempotencia de pasos:** la primera ejecución responde `201`; una repetición con el mismo `saga_id` responde `200` con el mismo cuerpo, sin volver a ejecutar.
  - **Compensaciones:** responden siempre `200` (salvo una falla inyectada), incluso si ya se habían ejecutado.
  - **Inyección de fallas:** `POST /admin/chaos` con `{"modo": "slow", "delay_ms": 3000}`. Afecta solo a las rutas de negocio (no a `/health`, `/metrics` ni `/admin`). `error` responde `500 ERROR_SIMULADO`; `down` responde `503 SERVICIO_NO_DISPONIBLE`.
  - **Rutas sin implementar:** responden `501 NO_IMPLEMENTADO`.
- **Justificación:** convenciones uniformes hacen que cualquiera del equipo pueda leer, probar y defender cualquier servicio.

### D-38 · Rutas públicas con prefijo
- **Fecha:** 11-11-2026 · **Estado:** Aceptada
- **Decisión:** Kong expone:

  | Ruta pública | Servicio interno |
  |---|---|
  | `POST /api/reservas` · `GET /api/reservas/{saga_id}` | `reservas` (`/reservas...`) |
  | `GET /api/espacios?fecha=` | `espacios` (`/espacios`) |
  | `GET /bff/web/mis-reservas/{saga_id}` | `bff-web` (`/mis-reservas/...`) |

- **Alternativas descartadas:**
  - *Rutas en la raíz (`/reservas`, `/mis-reservas`), como quedó en el primer avance del gateway:* más cortas, pero colisionan por prefijo (`/reservas` también captura `/reservas-espacio`) y no distinguen la API de dominio de la del BFF.
- **Justificación:** separa la API de dominio (`/api`) de la API del BFF (`/bff/web`) y evita capturas accidentales.

### D-39 · Una compensación que llega antes que su paso anula la saga en ese servicio
- **Fecha:** 11-11-2026 · **Estado:** Aceptada (confirmada el 11-11-2026; ver su relación con D-44 y D-45)
- **Problema:** si un paso hace timeout, el orquestador no sabe si se ejecutó; por eso compensa igual. Pero la petición original puede llegar al servicio **después** de la compensación (p. ej., cobrar después de haber reembolsado).
- **Decisión:** si una compensación llega para un `saga_id` sin registro, el servicio guarda la saga como `ANULADA` y responde `200` (`ANULADA`/`ANULADO`). Si después llega el paso con ese `saga_id`, responde `409 SAGA_ANULADA` y no ejecuta nada.
- **Alternativas descartadas:**
  - *Responder 404 a la compensación:* el orquestador no podría distinguir "no hay nada que compensar" de un error, y el paso tardío se ejecutaría igual, dejando un cobro sin reserva.
  - *Ignorar el caso:* deja estados inconsistentes justo en el escenario de lentitud que hay que demostrar.
- **Justificación:** cierra el caso de mensajes fuera de orden con un registro por saga, sin coordinación adicional. Es una pregunta probable en la defensa.

---

## 10. Parámetros de resiliencia y activación de fallas

Valores acordados (todos configurables por variables de entorno, D-48):

| Parámetro | Valor |
|---|---|
| Timeout de conexión (todas las llamadas) | 0,5 s |
| Timeout de respuesta de los pasos: Espacios / Pagos / Acceso | 1 s / 2 s / 1,5 s |
| Timeout de respuesta de las compensaciones | 5 s (D-46) |
| Circuit Breaker (solo Acceso) | Abre con ≥50 % de fallos en las últimas 10 llamadas, con mínimo 5; 10 s abierto; 1 llamada de prueba |
| Bulkhead (solo Acceso) | 5 llamadas simultáneas, dentro de un pool HTTP compartido de 20 conexiones |
| Retry de pasos | 2 intentos en total, solo ante errores rápidos (conexión rechazada, 5xx) |
| Retry de compensaciones | 3 intentos, incluidos timeouts; esperas de 0,2 y 0,4 s con variación aleatoria |
| Timeout de Kong hacia `reservas` | 30 s |
| Retardo de Acceso para la demo de lentitud | 3 s (mayor que 1,5 s del paso, menor que 5 s de la compensación) |

Duración de la saga en cada escenario con estos valores:

| Escenario | Qué ocurre | Duración aproximada | Estado final |
|---|---|---|---|
| 1. Camino feliz | 3 pasos | 0,1 s | `CONFIRMADA` |
| 2. Acceso en modo `error` | 500 → 1 reintento → 500 → no se revoca (error explícito, D-45) → reembolso → liberación | 0,3 s | `COMPENSADA` |
| 3a. Acceso lento (3 s) | Timeout de 1,5 s → incierto → revocar (responde a los 3 s) → reembolso → liberación | 4,6 s | `COMPENSADA` |
| 3a. Tras ~5 sagas fallidas | El circuito abre; rechazo previo (D-10) | milisegundos | `RECHAZADA` (503) |
| 3a. Con más concurrencia que cupos | El Bulkhead rechaza el exceso en el paso 3 | milisegundos | `COMPENSADA` (503) |
| 3b. Acceso detenido | Conexión rechazada → 1 reintento → no se revoca → reembolso → liberación | 0,3 s | `COMPENSADA` |
| Peor caso con **una** dependencia lenta (> 5 s) | Paso con timeout + compensación con 3 timeouts de 5 s | ~18 s | `COMPENSACION_PENDIENTE` |

Límite aceptado: si dos o más dependencias están lentas a la vez, la saga puede pasar de 30 s. Kong responde 504, pero la saga termina igual en `reservas` y su resultado se consulta con `GET /api/reservas/{saga_id}`. Ningún escenario exigido cae en este caso.

### D-40 · Timeouts de los pasos por dependencia
- **Fecha:** 11-11-2026 · **Estado:** Aceptada · **Cierra parte de:** P-03
- **Decisión:** timeout de conexión 0,5 s para todas las llamadas; timeout de respuesta de los pasos: Espacios 1 s, Pagos 2 s, Acceso 1,5 s.
- **Alternativas descartadas:**
  - *Un mismo timeout para todas (p. ej. 2 s):* simple, pero no refleja el riesgo de cada dependencia.
  - *Valores más altos (2 / 3 / 2 s):* con retry y compensaciones, el peor caso se acercaba a los 30 s de Kong.
- **Justificación:** Pagos tiene el más alto porque un timeout al cobrar deja la duda de si se cobró; Acceso, la dependencia frágil, falla rápido.

### D-41 · El Circuit Breaker abre por tasa de fallos en ventana deslizante
- **Fecha:** 11-11-2026 · **Estado:** Aceptada · **Cierra parte de:** P-03
- **Decisión:** se guardan los resultados de las últimas 10 llamadas a Acceso; el circuito abre si fallan ≥50 %, siempre que haya al menos 5 llamadas registradas. Cuentan como fallo: timeouts, errores de conexión y respuestas 5xx. No cuentan: respuestas 4xx de negocio (p. ej. `409 SAGA_ANULADA`) ni los rechazos del Bulkhead. Cada intento de un retry cuenta por separado.
- **Alternativas descartadas:**
  - *N fallos seguidos:* lo más simple, pero si Acceso alterna éxitos y fallos el contador se reinicia y el circuito nunca abre.
  - *Fallos en una ventana de tiempo:* con poco tráfico se comporta de forma irregular y es más difícil de explicar.
- **Justificación:** el enunciado describe Acceso como **inestable**; una tasa de fallos detecta ese comportamiento, un contador de fallos seguidos no.

### D-42 · Circuito abierto 10 s y semiabierto con una llamada de prueba
- **Fecha:** 11-11-2026 · **Estado:** Aceptada · **Cierra parte de:** P-03
- **Decisión:** el circuito queda abierto 10 s. Luego pasa a semiabierto y deja pasar **una** llamada: si responde bien se cierra, si falla vuelve a abrirse. Mientras esa llamada está en curso, las demás se rechazan. En semiabierto, el rechazo previo (D-10) deja iniciar la saga.
- **Alternativas descartadas:**
  - *30 a 60 s abierto:* realista en producción, pero en un video de 8 minutos no alcanza a verse el ciclo completo.
  - *Varias llamadas de prueba:* más robusto, pero más código y más difícil de mostrar.
- **Justificación:** el ciclo completo (cerrado → abierto → semiabierto → cerrado) se ve con claridad en la demo.

### D-43 · El Bulkhead aísla un pool HTTP compartido
- **Fecha:** 11-11-2026 · **Estado:** Aceptada · **Precisa:** D-15
- **Decisión:** `reservas` usa un único cliente HTTP con un pool de **20 conexiones** para todas las dependencias. Las llamadas a Acceso piden antes un cupo de un semáforo de **5**; si no hay cupo se rechazan al instante (`503 ACCESO_SATURADO`). Con `RESILIENCE_ENABLED=false` se quita el semáforo y el pool sigue compartido.
- **Qué protege:** una dependencia lenta acumula llamadas abiertas (concurrencia = llegadas × latencia). Sin límite, las llamadas lentas a Acceso ocupan todas las conexiones del pool y las de Espacios y Pagos quedan esperando: falla en cascada. Con el semáforo, Acceso ocupa como máximo 5 de 20 conexiones.
- **Diferencia con el Circuit Breaker:** el Circuit Breaker reacciona a fallos ya observados; el Bulkhead limita la concurrencia desde la primera llamada y también protege de llamadas lentas que **sí** responden antes del timeout, que el Circuit Breaker cuenta como éxitos.
- **Alternativas descartadas:**
  - *Un pool separado por dependencia:* es un Bulkhead válido, pero para tener una línea base "sin patrón" habría que volver a un pool compartido; además el exceso espera una conexión en vez de rechazarse al instante.
  - *Limitar la concurrencia de todo `POST /reservas`:* no aísla nada.
- **Justificación:** el experimento con y sin el patrón sale natural (latencia de los pasos 1 y 2, rechazos y cupos en uso), y eso es lo que mide ABET 6.

### D-44 · Retry en pasos y compensaciones, con reglas
- **Fecha:** 11-11-2026 · **Estado:** Aceptada · **Reemplaza:** D-17
- **Decisión:**
  - **Orden de las capas:** `retry → circuit breaker → bulkhead → timeout → llamada`. Cada intento cuenta en la ventana del Circuit Breaker (D-41).
  - **Nunca se reintenta** si el circuito está abierto, si el Bulkhead rechazó la llamada o si la respuesta fue 4xx.
  - **Pasos:** 2 intentos en total, solo ante errores rápidos (conexión rechazada, 5xx). **No se reintentan los timeouts**: la lentitud persistente la maneja el Circuit Breaker.
  - **Compensaciones:** 3 intentos, incluidos timeouts, con esperas de 0,2 y 0,4 s más una variación aleatoria. **No pasan por el Circuit Breaker ni por el Bulkhead**: tienen que intentarse aunque el circuito esté abierto. Si una compensación falla en los 3 intentos, las demás se ejecutan igual y la saga queda en `COMPENSACION_PENDIENTE`.
- **Alternativas descartadas:**
  - *Sin retry:* una falla pasajera en una compensación deja la saga a medio compensar.
  - *Retry solo en compensaciones:* deja sin tolerancia a fallas pasajeras a los pasos.
  - *Retry en todo, sin reglas:* antes de que abra el circuito multiplica la carga sobre la dependencia que ya está mal ("tormenta de reintentos"); con lentitud, cada reintento paga el timeout completo y ocupa un cupo del Bulkhead.
- **Justificación:** el retry cubre fallas pasajeras y el Circuit Breaker corta las persistentes; las reglas evitan que el retry trabaje en contra del Circuit Breaker. Todo es seguro porque pasos y compensaciones son idempotentes (D-13).

### D-45 · El paso que falló se compensa solo si su resultado es incierto
- **Fecha:** 11-11-2026 · **Estado:** Aceptada
- **Decisión:** los pasos anteriores, que se confirmaron, se compensan siempre. El paso que falló se compensa solo si no se sabe si se aplicó:

  | Resultado del paso que falló | ¿Se aplicó? | ¿Se compensa? |
  |---|---|---|
  | Respuesta de error explícita (4xx, 5xx) | No | No |
  | Conexión rechazada (`ConnectError`), circuito abierto, Bulkhead sin cupo | No (la petición no salió) | No |
  | Timeout de respuesta o conexión cortada después de enviar | No se sabe | **Sí** |

- **Supuesto:** un 5xx significa que el servicio no aplicó el paso. Los simuladores lo garantizan, porque la inyección de fallas responde antes de ejecutar nada.
- **Alternativas descartadas:**
  - *Compensar siempre el paso que falló:* en el escenario 2 (Acceso en modo `error`) la revocación también fallaría y la saga quedaría en `COMPENSACION_PENDIENTE` en vez de `COMPENSADA`.
  - *No compensarlo nunca:* tras un timeout, la puerta podría quedar habilitada para una reserva reembolsada.
- **Relación con D-39:** el caso incierto es justamente el que cubre D-39. Si la revocación llega a Acceso antes que la habilitación demorada, la saga queda `ANULADA` y la habilitación tardía se rechaza con `409 SAGA_ANULADA`. Si llega después, Acceso la revoca. En ambos órdenes el estado final es consistente.

### D-46 · Las compensaciones tienen un timeout más largo que los pasos
- **Fecha:** 11-11-2026 · **Estado:** Aceptada · **Cierra parte de:** P-03
- **Problema:** con el mismo timeout que los pasos (1,5 s) y Acceso lento (3 s), los 3 intentos de revocar hacen timeout. Acceso igual procesa las revocaciones un poco después y el estado real queda consistente, pero `reservas` no lo sabe y marca la saga como `COMPENSACION_PENDIENTE`.
- **Decisión:** las compensaciones usan un timeout de respuesta de 5 s.
- **Principio:** los pasos fallan rápido, porque protegen la latencia del cliente y el Circuit Breaker se encarga de la lentitud persistente. Las compensaciones son pacientes, porque tienen que completarse para que el estado sea consistente.
- **Alternativas descartadas:**
  - *Mismo timeout que los pasos:* deja `COMPENSACION_PENDIENTE` en el escenario de lentitud, aunque el estado real sea consistente.
  - *Reintentador en segundo plano para compensaciones pendientes:* más robusto, pero es otro componente que implementar.

### D-47 · Timeout de Kong hacia `reservas` de 30 s, sin plazo interno
- **Fecha:** 11-11-2026 · **Estado:** Aceptada · **Cierra parte de:** P-03
- **Decisión:** el `read_timeout` de Kong hacia `reservas` sube de 10 s a 30 s (aplicado en `gateway/kong.yml`). La saga no tiene un plazo máximo propio.
- **Alternativas descartadas:**
  - *Plazo interno de 8 s, con Kong en 10 s y respuesta `202 COMPENSANDO` si se cumple:* obliga a afinar todos los valores para que calcen dentro del plazo; la demo dependería de los parámetros más que de los patrones.
- **Justificación:** con una dependencia lenta, el peor caso es ~18 s y queda margen. Ver el límite aceptado en la tabla de escenarios de esta sección.

### D-48 · Parámetros de resiliencia en variables de entorno
- **Fecha:** 11-11-2026 · **Estado:** Aceptada · **Cierra parte de:** P-03
- **Decisión:** cada parámetro de la tabla de esta sección se lee de una variable de entorno de `reservas`, con el valor acordado por defecto, y se declara en `docker-compose.yml`. Igual que `RESILIENCE_ENABLED`.
- **Alternativas descartadas:**
  - *Constantes en el código:* cambiar un valor entre experimentos obliga a reconstruir la imagen.
- **Justificación:** permite repetir un experimento con otro valor sin tocar el código.

### D-49 · Circuit Breaker y Bulkhead solo sobre Acceso
- **Fecha:** 11-11-2026 · **Estado:** Aceptada
- **Decisión:** Circuit Breaker y Bulkhead protegen solo las llamadas a Acceso. Espacios y Pagos tienen timeout y retry.
- **Alternativas descartadas:**
  - *Circuit Breaker también sobre Pagos:* reutilizaría la misma clase; queda como extra si sobra tiempo.
- **Justificación:** el enunciado exige los patrones sobre la dependencia frágil, y la evidencia se concentra en Acceso.

### D-50 · Activación de fallas: script con `docker compose exec` y k6 dentro de la red
- **Fecha:** 11-11-2026 · **Estado:** Aceptada · **Cierra:** P-07
- **Decisión:**
  - **Manual:** `python scripts/chaos.py <pagos|acceso> <ok|slow|error|down> [delay_ms]` ejecuta `docker compose exec` y llama a `/admin/chaos` dentro del contenedor.
  - **Automatizado:** los scripts de k6 corren en la red interna y llaman directo a `http://acceso:8000/admin/chaos`. Un experimento cambia el modo por etapas (p. ej. normal → lento → caído → normal) en el mismo script, y queda reproducible.
  - **Caída real:** `docker compose stop acceso`.
- **Alternativas descartadas:**
  - *Ruta `/admin/...` en Kong con ACL:* expone la inyección de fallas en el gateway público y la somete al rate limiting.
  - *Contenedor de herramientas en la red interna:* otro servicio más que mantener.
  - *Publicar Pagos y Acceso en `127.0.0.1`:* expone el servicio completo saltándose Kong; se puede leer como incumplir "solo el gateway se expone".
  - *Variables de entorno y reinicio:* tarda segundos y no permite cambiar el modo durante una prueba de carga.
- **Justificación:** no expone nada, no agrega infraestructura y permite experimentos automatizados con una línea de tiempo clara.

---

## 11. Frontera entre el orquestador y la resiliencia

### D-54 · Toda llamada a las dependencias pasa por el módulo de resiliencia
- **Fecha:** 23-11-2026 · **Estado:** Pendiente de confirmar (revisión del rol B)
- **Contexto:** el orquestador (rol B) y la capa de resiliencia (rol C) viven en el mismo servicio, `reservas`. Sin una frontera acordada, los dos roles editarían las mismas funciones y las garantías de D-40 a D-49 dependerían de que cada llamada se escriba "bien".
- **Regla para dividir el trabajo:** el módulo decide **cómo** se llama a una dependencia (si se llama, cuántas veces, cuánto se espera y qué pasó). El orquestador decide **qué** se llama, en qué orden y qué significa el resultado para la saga.

  | Responsabilidad | Módulo de resiliencia (C) | Orquestador (B) |
  |---|---|---|
  | Llamada HTTP con timeout, retry, Circuit Breaker y Bulkhead | ✅ | |
  | Clasificar el resultado: OK, error, timeout, rechazado, incierto | ✅ | |
  | Informar si el circuito de Acceso está abierto | ✅ | |
  | Ordenar los pasos y compensar en orden inverso | | ✅ |
  | Rechazo previo con el circuito abierto (D-10) | Da el dato | ✅ Decide |
  | Compensar el paso fallido solo si fue incierto (D-45) | Da el dato | ✅ Decide |
  | Interpretar los 4xx de negocio (`404`, `409`, `402`, `422`) | | ✅ |
  | Guardar la saga y su saga log; responder con los códigos de D-35 | | ✅ |

- **Interfaz** (`services/reservas/app/resiliencia.py`):

  ```python
  await iniciar()   # en el lifespan de main.py, al arrancar: crea el cliente HTTP compartido
  await cerrar()    # en el lifespan de main.py, al apagar

  r = await paso(dependencia, metodo, ruta, json=None, request_id=None)          # pasos 1, 2 y 3
  r = await compensacion(dependencia, metodo, ruta, json=None, request_id=None)  # liberar, reembolsar, revocar
  acceso_disponible() -> bool   # False si el circuito de Acceso está abierto (rechazo previo, D-10)
  ```

  `dependencia` es `"espacios"`, `"pagos"` o `"acceso"`. `paso()` aplica las reglas de los pasos (Circuit Breaker y Bulkhead en Acceso, timeouts de D-40, retry solo ante errores rápidos); `compensacion()` aplica las de las compensaciones (sin Circuit Breaker ni Bulkhead, timeout de 5 s, 3 intentos). Ninguna de las dos lanza excepciones por fallas de red: siempre devuelven un `Resultado`.

- **`Resultado`:** sus campos coinciden con los de `Paso` del contrato de `reservas`, así el saga log se arma copiando campos.

  | Campo | Significado |
  |---|---|
  | `resultado` | `OK`, `ERROR`, `TIMEOUT` o `RECHAZADO` (el `ResultadoPaso` del contrato) |
  | `codigo_http` | Código que respondió la dependencia; `None` si no respondió |
  | `cuerpo` | JSON de la respuesta (p. ej. `precio` de Espacios, `qr` de Acceso); `None` si no respondió |
  | `detalle` | Código fijo del motivo, para que el orquestador decida sin comparar textos: el `codigo` del error si la dependencia respondió con error (p. ej. `FRANJA_OCUPADA`; `HTTP_<código>` si la respuesta no trae el formato común, como un 500 no controlado), o uno de `CIRCUITO_ABIERTO`, `BULKHEAD_LLENO`, `POOL_AGOTADO`, `CONEXION_RECHAZADA`, `CONEXION_CORTADA`, `TIMEOUT_CONEXION`, `TIMEOUT_RESPUESTA`. `None` si salió bien |
  | `incierto` | `True` si no se sabe si la dependencia aplicó la operación (D-45) |
  | `intentos` | Cuántas veces se intentó la llamada |
  | `inicio`, `duracion_ms` | Momento del primer intento y duración total, retries incluidos |

- **Clasificación** (la hace el módulo, según D-44 y D-45):

  | Qué pasó | `resultado` | `detalle` | `incierto` |
  |---|---|---|---|
  | Respuesta 2xx | `OK` | `None` | No |
  | Respuesta 4xx o 5xx | `ERROR` (con `codigo_http` y `cuerpo`) | `codigo` del error | No |
  | Conexión rechazada (nadie escucha en ese puerto) | `ERROR` | `CONEXION_RECHAZADA` | No: la petición no salió |
  | Timeout al conectar (también un contenedor detenido: su nombre no se resuelve a tiempo) | `TIMEOUT` | `TIMEOUT_CONEXION` | No: la petición no salió |
  | Sin conexión libre en el pool compartido dentro del timeout | `TIMEOUT` | `POOL_AGOTADO` | No: la petición no salió |
  | Timeout de respuesta | `TIMEOUT` | `TIMEOUT_RESPUESTA` | **Sí** |
  | Conexión cortada después de enviar | `ERROR` | `CONEXION_CORTADA` | **Sí** |
  | Circuito abierto | `RECHAZADO` | `CIRCUITO_ABIERTO` | No: no se llamó |
  | Bulkhead sin cupo | `RECHAZADO` | `BULKHEAD_LLENO` | No: no se llamó |

  Con esto, los `503` de D-35 salen directo del `detalle`: `CIRCUITO_ABIERTO` → `ACCESO_NO_DISPONIBLE`, `BULKHEAD_LLENO` → `ACCESO_SATURADO`.

- **Reglas para el orquestador:**
  1. **No usa `httpx` para llamar a Espacios, Pagos ni Acceso.** Un cliente propio rompería el pool compartido que protege el Bulkhead (D-43) y dejaría llamadas sin timeout ni Circuit Breaker.
  2. **No captura excepciones de red**; usa `resultado` e `incierto`.
  3. **Pasa el `X-Request-ID`** recibido de Kong en `request_id`, para que la petición se pueda seguir en los logs de todos los servicios.
- **Archivos y responsables:**

  | Archivo o elemento | Responsable |
  |---|---|
  | `app/resiliencia.py`, `tests/test_resiliencia.py` | C |
  | `app/main.py`, el código de la saga, `db.py`, `modelos.py`, sus pruebas | B |
  | Dos líneas en el lifespan de `main.py` (`iniciar()` y `cerrar()`) | B, al integrar |
  | `requirements.txt` y `Dockerfile` de `reservas` | Ambos: avisarse (C agrega `pytest` y `COPY tests`; B, SQLAlchemy y `asyncpg`) |
  | Bloque de variables de resiliencia de `reservas` en `docker-compose.yml` | C, avisando al rol A |
  | Métricas `dependencia_*`, `circuito_*`, `bulkhead_*` | C |
  | Métricas `saga_*` | B |

- **Variables de entorno** (D-48), con sus valores por defecto: `RESILIENCE_ENABLED=true`, `POOL_CONEXIONES=20`, `TIMEOUT_CONEXION_S=0.5`, `TIMEOUT_ESPACIOS_S=1`, `TIMEOUT_PAGOS_S=2`, `TIMEOUT_ACCESO_S=1.5`, `TIMEOUT_COMPENSACION_S=5`, `CB_VENTANA=10`, `CB_MINIMO_LLAMADAS=5`, `CB_UMBRAL_FALLOS=0.5`, `CB_ESPERA_ABIERTO_S=10`, `BULKHEAD_ACCESO_CUPOS=5`, `RETRY_INTENTOS_PASO=2`, `RETRY_INTENTOS_COMPENSACION=3`.
- **Trabajo en paralelo:** el rol C sube primero una versión de `resiliencia.py` con esta interfaz que hace llamadas simples (con timeout, sin los patrones). El rol B escribe el orquestador contra ella desde ese momento; después, el rol C completa el módulo sin que cambie la interfaz.
- **Alternativas descartadas:**
  - *Patrones escritos dentro del código de la saga:* mezcla responsabilidades, los dos roles editarían las mismas funciones y `RESILIENCE_ENABLED` quedaría repartido por todo el código.
  - *El módulo lanza excepciones (`CircuitoAbierto`, `Timeout`…) que el orquestador captura:* el orquestador tendría que conocer los tipos de error de red y repetir la clasificación de D-45, con más riesgo de tratar un timeout incierto como certero.
  - *Decoradores que el orquestador aplica a cada llamada:* si se olvida uno, esa llamada queda sin protección y fuera del pool compartido.
  - *Un proxy aparte (p. ej. Envoy) con los patrones:* infraestructura extra y contradice la implementación propia de D-14.
- **Justificación:** cada rol trabaja en sus propios archivos y puede probar su parte por separado. Las garantías de resiliencia quedan en un solo lugar, y el comportamiento con y sin los patrones (D-20) se cambia sin tocar el código de la saga.

---

## Decisiones pendientes

| ID | Pregunta | Opciones en evaluación | Responsable |
|---|---|---|---|
| P-01 | ¿Quién emite el JWT? | Endpoint `/login` mínimo · tokens pregenerados con un script. **Provisorio:** `scripts/generar_token.py` | A |
| P-02 | Valores de rate limiting | p. ej. 10 req/s por consumidor | A |
| ~~P-03~~ | ~~Parámetros de resiliencia~~ | **Resuelta** por D-40 a D-49 | C |
| ~~P-04~~ | ~~Acceso a datos~~ | **Resuelta** por D-51 | B |
| ~~P-05~~ | ~~Contratos de API~~ | **Resuelta** por D-30 a D-39 | Todos |
| P-06 | Nombres en el reparto | Asignar A / B / C | Todos |
| ~~P-07~~ | ~~¿Cómo se invoca `/admin/chaos`?~~ | **Resuelta** por D-50 | C |
