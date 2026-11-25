# Cowork — Reserva de espacios resiliente

Encargo integrador, Unidad 3 de Integración de Sistemas (Forma O).

Sistema de microservicios que reserva un puesto o sala de cowork coordinando **Espacios**, **Pagos** (pasarela externa) y **Acceso** (controlador externo de puerta con QR) mediante una **Saga orquestada**, expuesto por un **API Gateway** y un **BFF**, y protegido con **timeout, Circuit Breaker y Bulkhead**.

> **Estado:** todos los servicios están implementados: gateway, BFF Web, Espacios, simuladores de Pagos y Acceso, y el orquestador de la Saga con su capa de resiliencia. Los escenarios de falla están verificados de punta a punta (ver [Escenarios de falla](#escenarios-de-falla)).

## Arquitectura

```
Cliente ──JWT──► Kong (gateway, :8000) ──┬──► bff-web ──► reservas / espacios / pagos / acceso
                 enruta · JWT · rate     └──► reservas (orquestador Saga)
                 limit · X-Request-ID              │ timeout + Circuit Breaker + Bulkhead
                                                   ├──► espacios ── db-espacios
                                                   ├──► pagos ───── db-pagos      (pasarela simulada)
                                                   └──► acceso ──── db-acceso     (controlador simulado, frágil)
                                         reservas ── db-reservas (saga log)

Prometheus (:9090) y Grafana (:3000) recogen métricas de Kong y de todos los servicios.
Decisiones de diseño y alternativas descartadas: docs/DECISIONES.md
```

| Componente | Carpeta |
|---|---|
| Gateway (Kong DB-less) | [gateway/](gateway/) |
| BFF Web | [services/bff-web/](services/bff-web/) |
| Orquestador de la Saga | [services/reservas/](services/reservas/) |
| Espacios | [services/espacios/](services/espacios/) |
| Pagos (simulador) | [services/pagos/](services/pagos/) |
| Acceso (simulador) | [services/acceso/](services/acceso/) |
| Prometheus + Grafana | [observability/](observability/) |
| Pruebas de carga (k6) | [k6/](k6/) |

## Requisitos

- Docker Desktop (con Docker Compose v2).
- Python 3 solo para generar tokens con el script (no hace falta instalar dependencias).

## Levantar el sistema

```bash
docker compose up -d --build
docker compose ps          # kong y los servicios deben quedar "healthy"
```

No hace falta un `.env`: todo tiene valores por defecto. Para cambiarlos, copiar [.env.example](.env.example) a `.env`.

Puertos disponibles en el host:

| URL | Qué es | Expuesto en |
|---|---|---|
| http://localhost:8000 | API Gateway (Kong), único punto de entrada al sistema. Se cambia con `GATEWAY_PORT` | todas las interfaces |
| http://127.0.0.1:3000 | Grafana (acceso anónimo como administrador, sin login). Se cambia con `GRAFANA_PORT` | solo localhost |
| http://127.0.0.1:9090 | Prometheus. Se cambia con `PROMETHEUS_PORT` | solo localhost |

Los microservicios, las bases de datos y el endpoint de métricas de Kong (`kong:8100/metrics`) no publican puertos: solo son accesibles dentro de la red interna de Docker.

En Windows, si `docker compose up` falla con `bind: An attempt was made to access a socket in a way forbidden by its access permissions`, el sistema tiene reservado ese puerto (rangos de Hyper-V/WinNAT; se ven con `netsh interface ipv4 show excludedportrange protocol=tcp`). Basta con usar otro: `GRAFANA_PORT=3001 docker compose up -d` o fijarlo en el `.env`.

Para bajar todo y borrar las bases de datos:

```bash
docker compose down -v
```

## Autenticación

Kong exige un JWT HS256 en el encabezado `Authorization: Bearer <token>` (sin token o con firma inválida responde `401`). Para generar uno de desarrollo:

```bash
python scripts/generar_token.py                  # consumidor cliente-demo (por defecto)
python scripts/generar_token.py cliente-demo-2   # segundo consumidor
python scripts/generar_token.py --minutos 5      # vigencia distinta (por defecto 60 min)
```

Hay dos consumidores configurados, `cliente-demo` y `cliente-demo-2`, cada uno con su propio secreto. El rate limiting es por consumidor (10 peticiones por segundo; al excederlo Kong responde `429`), así que una ráfaga de uno no afecta al otro. Los secretos de [gateway/kong.yml](gateway/kong.yml) son solo de desarrollo.

## Rutas expuestas por el gateway

| Método | Ruta en el gateway | Servicio interno |
|---|---|---|
| `POST` | `/api/reservas` | `reservas` `POST /reservas` → inicia la Saga |
| `GET` | `/api/reservas/{saga_id}` | `reservas` `GET /reservas/{saga_id}` → estado y saga log |
| `GET` | `/api/espacios?fecha=YYYY-MM-DD` | `espacios` `GET /espacios` → disponibilidad |
| `GET` | `/bff/web/mis-reservas/{saga_id}` | `bff-web` `GET /mis-reservas/{saga_id}` → vista agregada de Espacios, Pagos y Acceso |

Cómo usar la Saga: ver [Reservar un espacio](#reservar-un-espacio-saga).

Cualquier otra ruta responde `404` desde Kong (el `/health` y el `/metrics` del BFF, por ejemplo, no pasan por el gateway). Cada respuesta trae un encabezado `X-Request-ID`, que Kong también envía al servicio para seguir la petición en los logs.

Ejemplo (Git Bash):

```bash
TOKEN=$(python scripts/generar_token.py)
curl -i "http://localhost:8000/api/espacios?fecha=2026-11-20" -H "Authorization: Bearer $TOKEN"
```

## Reservar un espacio (Saga)

`POST /api/reservas` ejecuta la Saga orquestada por `reservas` y responde cuando termina, con el resultado y el saga log. El precio no lo envía el cliente: lo define Espacios.

| Paso | Servicio | Compensación |
|---|---|---|
| 1. Reservar el bloque (devuelve el precio) | Espacios | Liberar el bloque |
| 2. Cobrar el precio | Pagos | Reembolsar |
| 3. Habilitar la puerta (devuelve el QR) | Acceso | Revocar |

- Si un paso falla, se compensan **en orden inverso** los pasos ya aplicados. El paso que falló se compensa solo si su resultado es incierto, por ejemplo un timeout.
- Si el circuito de Acceso está abierto, la saga se rechaza antes de empezar: no se reserva ni se cobra nada.
- El código HTTP indica el resultado: `201 CONFIRMADA`; `404`, `409` o `422` `RECHAZADA` (espacio inexistente, bloque ocupado o bloque que ya empezó); `402` o `502` `COMPENSADA` (una dependencia falló); `503` con `Retry-After` (el Circuit Breaker o el Bulkhead cortaron la llamada).
- `Idempotency-Key` es opcional: si el mismo cliente repite la clave, recibe la misma saga con `200` y no se cobra dos veces.
- Cada saga queda en el saga log de `db-reservas` (tablas `sagas` y `pasos_saga`) y en los logs de `reservas`, con su `saga_id` y el `X-Request-ID` de Kong.

Prueba a mano (Git Bash), con una fecha futura:

```bash
TOKEN=$(python scripts/generar_token.py)

# 1. Disponibilidad del día
curl -s "http://localhost:8000/api/espacios?fecha=2026-12-10" -H "Authorization: Bearer $TOKEN"

# 2. Reservar: 201, "estado": "CONFIRMADA", con precio, QR y los tres pasos en "pasos"
curl -s -X POST http://localhost:8000/api/reservas -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" -H "Idempotency-Key: demo-1" \
  -d '{"espacio_id": "SALA-A", "fecha": "2026-12-10", "bloque": 9}'

# 3. Repetir la misma petición: 200, la misma saga (no cobra de nuevo)
# 4. Otra reserva del mismo bloque sin la clave: 409 RECHAZADA, FRANJA_OCUPADA

# 5. Consultar la saga y la vista del cliente
curl -s http://localhost:8000/api/reservas/<saga_id> -H "Authorization: Bearer $TOKEN"
curl -s http://localhost:8000/bff/web/mis-reservas/<saga_id> -H "Authorization: Bearer $TOKEN"
```

Compensación a mano (escenario 2): con Acceso en modo `error`, la respuesta es `502 COMPENSADA`, y en `pasos` aparece `HABILITAR_ACCESO: ERROR` seguido de `REEMBOLSAR` y `LIBERAR_ESPACIO`, en ese orden.

```bash
python scripts/chaos.py acceso error
curl -s -X POST http://localhost:8000/api/reservas -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" -d '{"espacio_id": "SALA-B", "fecha": "2026-12-10", "bloque": 11}'
python scripts/chaos.py acceso ok
```

Tras unos fallos seguidos el circuito abre, y las reservas siguientes responden `503 RECHAZADA` en milisegundos, con `Retry-After: 10` y sin pasos.

## BFF Web

`GET /bff/web/mis-reservas/{saga_id}` compone en una sola respuesta datos de tres servicios: el espacio (Espacios), el estado del pago (Pagos) y el estado y QR de la puerta (Acceso). Consulta las tres fuentes **en paralelo**, cada una con su timeout y su propio pool de conexiones, de modo que una fuente lenta no agota las conexiones de las otras.

| Situación | Respuesta del BFF |
|---|---|
| Las tres fuentes responden | `200`, `degradado: false` |
| Acceso lento, caído o con error | `200`, `degradado: true`, `acceso.qr: "no disponible"`, `no_disponibles: ["ACCESO"]` |
| Acceso informa que la saga no habilitó la puerta | `200`, `acceso.qr: null` (no es una degradación) |
| Pagos informa que no hubo cobro | `200`, `pago: null` |
| Espacios no conoce el `saga_id` | `404 RESERVA_NO_EXISTE` |
| Espacios o Pagos lentos, caídos o con error | `502 ESPACIOS_FALLO` / `502 PAGOS_FALLO` |

Acceso es la única fuente opcional: sin el QR la vista sigue siendo útil, mientras que sin el espacio o sin el pago podría leerse como "no hay reserva" o "no pagué".

```bash
TOKEN=$(python scripts/generar_token.py)
curl -s "http://localhost:8000/bff/web/mis-reservas/<saga_id>" -H "Authorization: Bearer $TOKEN"
```

Cada consulta reenvía el `X-Request-ID` de Kong y deja una línea de log en JSON con `request_id`, `saga_id`, `fuente`, `resultado` y `duracion_ms` (`docker compose logs bff-web`). Las métricas se publican en `/metrics/` y las recoge Prometheus: `bff_consultas_fuente_total{fuente,resultado}`, `bff_latencia_fuente_segundos{fuente}` y `bff_respuestas_total{resultado}`.

Sus pruebas no necesitan Docker: simulan las tres fuentes en memoria.

```bash
cd services/bff-web
pip install -r requirements.txt pytest
pytest -q
```

## Prueba de la capa de exposición

Comprueba en un solo script que el gateway rechaza sin token y con token inválido (`401`), que una ráfaga de peticiones paralelas recibe `429` y que solo Kong publica un puerto hacia afuera. Requiere el sistema levantado y `curl`:

```bash
bash scripts/probar_exposicion.sh
```

## Prueba de humo

Verifica que el gateway rechaza peticiones sin token o con firma inválida, deja pasar las autenticadas de ambos consumidores hasta el servicio correcto y responde `404` a rutas desconocidas. Requiere el sistema levantado; k6 no arranca con `up`, solo con `run`:

```bash
docker compose run --rm k6 run /scripts/smoke.js
```

> En **Git Bash** hay que anteponer `MSYS_NO_PATHCONV=1` (si no, convierte `/scripts/...` en una ruta de Windows y k6 no encuentra el archivo). En PowerShell funciona tal cual.

## Pruebas de los simuladores

Pagos y Acceso traen pruebas de contrato que se ejecutan dentro de su contenedor, contra el servicio en marcha y su Postgres real (idempotencia, compensaciones, anulación de sagas y modos de falla):

```bash
docker compose exec pagos pytest -q -p no:cacheprovider tests
docker compose exec acceso pytest -q -p no:cacheprovider tests
```

## Resiliencia

Todas las llamadas de `reservas` a Espacios, Pagos y Acceso pasan por un único módulo, [services/reservas/app/resiliencia.py](services/reservas/app/resiliencia.py), sobre un pool HTTP compartido de 20 conexiones:

| Patrón | Dónde | Comportamiento |
|---|---|---|
| Timeout | Todas las llamadas | Conexión: 0,5 s. Pasos: Espacios 1 s, Pagos 2 s, Acceso 1,5 s. Compensaciones: 5 s |
| Reintentos | Pasos | 2 intentos en total, solo ante conexión rechazada o 5xx; nunca ante un timeout |
| Reintentos | Compensaciones | 3 intentos, también ante timeouts, con esperas de 0,2 y 0,4 s más una variación aleatoria |
| Circuit Breaker | Acceso | Abre si fallan al menos el 50 % de las últimas 10 llamadas (con un mínimo de 5). Queda abierto 10 s y luego deja pasar una llamada de prueba. Mientras está abierto, las reservas se rechazan antes de empezar |
| Bulkhead | Acceso | Como máximo 5 llamadas simultáneas; el exceso se rechaza al instante. Así Acceso nunca ocupa más de 5 de las 20 conexiones y Espacios y Pagos siguen teniendo dónde conectarse |

Las compensaciones no pasan por el Circuit Breaker ni por el Bulkhead: tienen que intentarse aunque Acceso esté marcado como caído. Con `RESILIENCE_ENABLED=false` se quitan el Circuit Breaker y el Bulkhead (los timeouts y los reintentos se mantienen), para comparar el sistema con y sin los patrones.

Métricas que publica `reservas` en `/metrics`:

| Métrica | Qué muestra |
|---|---|
| `dependencia_llamadas_total{dependencia,tipo,resultado,detalle}` | Cada intento de llamada: `OK`, `ERROR`, `TIMEOUT` o `RECHAZADO`, y su motivo (`CIRCUITO_ABIERTO`, `BULKHEAD_LLENO`, `POOL_AGOTADO`, `TIMEOUT_RESPUESTA`, el código de error de la dependencia...) |
| `dependencia_duracion_segundos{dependencia,tipo}` | Latencia de cada intento (histograma) |
| `dependencia_en_curso{dependencia}`, `dependencia_pool_conexiones` | Llamadas abiertas hacia cada dependencia, frente al tamaño del pool |
| `circuito_estado{dependencia}` | `0` cerrado, `1` semiabierto, `2` abierto |
| `circuito_transiciones_total{dependencia,hacia}` | Aperturas y cierres del circuito |
| `bulkhead_en_uso{dependencia}`, `bulkhead_cupos{dependencia}` | Cupos ocupados del Bulkhead, frente a los configurados |
| `resiliencia_activada` | `1` si el Circuit Breaker y el Bulkhead están activos |

Pruebas unitarias del módulo. No necesitan los demás servicios: las dependencias se simulan en memoria y el reloj del Circuit Breaker es falso.

```bash
docker compose exec reservas pytest -q -p no:cacheprovider tests
```

### Dashboard

Grafana (http://127.0.0.1:3000) carga solo el dashboard **Cowork · Resiliencia ante fallas**, en la carpeta *Cowork*. Se actualiza cada 5 s y marca con una franja las fallas inyectadas y los servicios que dejan de responder.

| Sección | Qué mirar |
|---|---|
| Estado actual y línea de tiempo | Falla inyectada en Acceso y Pagos, si los patrones están activos y el estado del circuito (cerrado, semiabierto, abierto). Es el eje para leer el resto |
| Lo que ve el cliente | Códigos HTTP de `/api/reservas` (201, 402/409, 502 compensada, 503 fail-fast) y latencia p95 de cada servicio en el gateway |
| Resiliencia | Intentos hacia Acceso por resultado (timeouts que pasan a rechazos del circuito o del Bulkhead), conexiones en uso frente al pool y a los cupos del Bulkhead, latencia de cada dependencia, fallas técnicas de Espacios y Pagos, y compensaciones |
| Dependencias externas y BFF | Lo que Acceso y Pagos realmente aplicaron (incluidas las operaciones que llegan tarde en modo lento) y las respuestas completas o degradadas del BFF |

Para comparar con y sin los patrones, se repite el mismo escenario levantando `reservas` con `RESILIENCE_ENABLED=false` y luego con `true`. Sin Bulkhead, Acceso lento ocupa todo el pool y los pasos de Espacios y Pagos fallan con `POOL_AGOTADO`; con Bulkhead, Acceso no pasa de sus cupos y Espacios y Pagos siguen respondiendo.

## Parámetros de resiliencia

Los timeouts, el Circuit Breaker, el Bulkhead y los reintentos se configuran con variables de entorno, con los valores acordados por defecto (justificados en [docs/DECISIONES.md](docs/DECISIONES.md)). [.env.example](.env.example) lista todos los nombres. Para un experimento basta cambiar uno, por ejemplo:

```bash
TIMEOUT_ACCESO_S=1 docker compose up -d
```

Los `TIMEOUT_*` los leen `reservas` y el BFF.

## Inyección de fallas

Pagos (pasarela de pago) y Acceso (controlador de puerta) son simuladores de servicios externos con un modo de falla configurable. Su endpoint `/admin/chaos` no se publica fuera de la red de Docker; desde el host se cambia con un script que lo llama dentro del contenedor:

```bash
python scripts/chaos.py acceso              # muestra el modo actual
python scripts/chaos.py acceso slow 3000    # responde con 3 s de retardo
python scripts/chaos.py acceso error        # responde 500
python scripts/chaos.py acceso down         # responde 503
python scripts/chaos.py acceso ok           # vuelve a la normalidad
```

| Modo | Comportamiento |
|---|---|
| `ok` | Normal. |
| `slow` | Espera `delay_ms` (por defecto 3000) y luego procesa la petición. Si el cliente se rinde por timeout, la operación se aplica igual, tarde: el resultado es incierto para quien llamó. |
| `error` | Responde `500 ERROR_SIMULADO` sin ejecutar nada. |
| `down` | Responde `503 SERVICIO_NO_DISPONIBLE` sin ejecutar nada. |

Las fallas solo afectan a las rutas de negocio; `/health`, `/metrics` y `/admin` siguen respondiendo. El modo activo se publica en la métrica `chaos_modo_activo`, para ver en Grafana cuándo se activó cada falla. El modo vive en memoria: al reiniciar el servicio vuelve a `ok`.

Para una **caída real** (el contenedor no existe: las llamadas fallan al intentar conectarse):

```bash
docker compose stop acceso
docker compose start acceso
```

Los scripts de k6 corren dentro de la red de Docker y pueden cambiar el modo llamando directamente a `http://acceso:8000/admin/chaos`.

## Escenarios de falla

**Verificados de punta a punta el 24-11-2026, con y sin los patrones:** con los patrones todos los umbrales pasan, y en ninguna de las dos configuraciones queda una saga a medias.

| Escenario | Resultado medido con los patrones (sin ellos) |
|---|---|
| 1. Éxito | 121 de 121 sagas `CONFIRMADA`, p95 de 95 ms (sin los patrones: igual, p95 de 71 ms) |
| 2. Fallo con compensación | Las sagas que llegan a Acceso quedan `COMPENSADA` (reembolso y liberación en orden inverso). Luego el circuito abre y 73 reservas se rechazan sin cobrar (sin el circuito: las 76 se cobran y se reembolsan). 0 en `COMPENSACION_PENDIENTE` |
| 3. Falla en cascada contenida | Con Acceso tardando 3 s, las reservas responden con p95 de 69 ms (sin los patrones: 4,7 s). La disponibilidad sigue en 9 ms (221 de 221 en `200`) |
| 4. Bulkhead | 710 reservas rechazadas al instante con `ACCESO_SATURADO`, 216 confirmadas durante la falla y 0 fallas contagiadas a Espacios o Pagos (sin el Bulkhead: 50 reservas fallan en Espacios) |
| Acceso detenido | Las 5 primeras reservas se compensan en ~0,6 s; desde la sexta el circuito abre y se rechazan en menos de 50 ms. Al levantar Acceso, la siguiente llamada de prueba cierra el circuito |

Cada escenario es un script de k6 que genera reservas a través de Kong, inyecta la falla en el momento indicado (llamando a `/admin/chaos` dentro de la red) y la retira al final. Las reservas se reparten entre los dos consumidores para no chocar con el rate limiting.

| Escenario | Script | Falla inyectada | Resultado esperado |
|---|---|---|---|
| 1. Éxito | `exito.js` (30 s, 4 reservas/s) | Ninguna | Los tres pasos quedan firmes: `201`, saga `CONFIRMADA` |
| 2. Fallo con compensación | `compensacion.js` (80 s, 2 reservas/s) | Acceso responde `500` entre los segundos 15 y 55 | Acceso falla en el paso 3: reembolso y liberación del espacio en orden inverso, `502` `COMPENSADA`. Tras unos fallos el circuito abre y las siguientes reservas se rechazan sin cobrar (`503`) |
| 3. Falla en cascada contenida | `cascada.js` (110 s, 4 reservas/s y 2 consultas de disponibilidad/s) | Acceso tarda 3 s (más que su timeout) entre los segundos 20 y 80 | El Circuit Breaker abre y las reservas fallan en milisegundos (`503`) en vez de esperar a Acceso; la consulta de disponibilidad sigue respondiendo igual |
| 4. Bulkhead | `bulkhead.js` (100 s, 16 reservas/s y 2 consultas/s) | Acceso tarda 1,3 s (dentro del timeout) entre los segundos 20 y 80 | El circuito no abre porque Acceso responde a tiempo; el Bulkhead deja como máximo 5 llamadas simultáneas a Acceso y rechaza el exceso (`503 ACCESO_SATURADO`). Espacios y Pagos no se contagian |

```bash
docker compose run --rm k6 run /scripts/exito.js
docker compose run --rm k6 run /scripts/compensacion.js
docker compose run --rm k6 run /scripts/cascada.js
docker compose run --rm k6 run /scripts/bulkhead.js
```

Al terminar, cada script muestra un resumen y lo guarda en `k6/resultados/` (texto y JSON, con el escenario, la fecha y si los patrones estaban activos): la línea de tiempo, los **umbrales** que el patrón debe garantizar (✓/✗), las sagas por fase y estado, el motivo de las no confirmadas y las latencias que vio el cliente. Mientras corre, el [dashboard](#dashboard) muestra lo mismo en vivo.

**Con y sin los patrones.** Para comparar, se corre el mismo escenario con `reservas` levantado sin Circuit Breaker ni Bulkhead y luego con ellos:

```bash
RESILIENCE_ENABLED=false docker compose up -d reservas   # PowerShell: $env:RESILIENCE_ENABLED="false"; docker compose up -d reservas
docker compose run --rm k6 run /scripts/cascada.js
RESILIENCE_ENABLED=true docker compose up -d reservas    # PowerShell: $env:RESILIENCE_ENABLED="true"; docker compose up -d reservas
docker compose run --rm k6 run /scripts/cascada.js
```

Con los patrones, los umbrales pasan; sin ellos fallan los que muestran el aporte de cada patrón: en `cascada.js` las reservas tardan lo que tarda Acceso, y en `bulkhead.js` Acceso ocupa el pool compartido y las reservas fallan en Espacios o Pagos aunque estén sanos.

**Acceso caído de verdad.** k6 no controla Docker, así que este caso se provoca a mano durante cualquier escenario: `docker compose stop acceso` y luego `docker compose start acceso`. Las llamadas fallan al conectar, el circuito abre igual que con la lentitud y las reservas se rechazan de inmediato.

**Evidencia desde el BFF.** Con una saga confirmada (ver [Reservar un espacio](#reservar-un-espacio-saga)), la degradación de Acceso se ve en la vista del cliente:

```bash
python scripts/chaos.py acceso slow 3000   # Acceso tarda más que el timeout del BFF (1,5 s)
curl -s "http://localhost:8000/bff/web/mis-reservas/<saga_id>" -H "Authorization: Bearer $TOKEN"
# 200 en ~1,5 s, "degradado": true, "qr": "no disponible"; Espacios y Pagos siguen intactos
python scripts/chaos.py acceso ok          # vuelve el QR
```

## Estructura

```
gateway/kong.yml                 Configuración declarativa de Kong
services/<servicio>/             Un microservicio FastAPI por carpeta (Dockerfile + app/)
observability/                   Prometheus, aprovisionamiento de Grafana y el dashboard de resiliencia
k6/                              Prueba de humo y escenarios de falla (lib/ con el código común)
k6/resultados/                   Resumen de cada corrida de los escenarios (no se versiona)
docs/DECISIONES.md               Registro de decisiones de diseño y alternativas descartadas
docs/api/                        Contratos OpenAPI de cada servicio
scripts/generar_token.py         JWT de desarrollo
scripts/probar_exposicion.sh     Verifica JWT, rate limiting y puertos publicados
scripts/chaos.py                 Cambia el modo de falla de Pagos y Acceso
scripts/exportar_contratos.py    Regenera docs/api/ a partir del código
```
