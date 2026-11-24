# Cowork — Reserva de espacios resiliente

Encargo integrador, Unidad 3 de Integración de Sistemas (Forma O).

Sistema de microservicios que reserva un puesto o sala de cowork coordinando **Espacios**, **Pagos** (pasarela externa) y **Acceso** (controlador externo de puerta con QR) mediante una **Saga orquestada**, expuesto por un **API Gateway** y un **BFF**, y protegido con **timeout, Circuit Breaker y Bulkhead**.

> **Estado:** en desarrollo. Los simuladores de **Pagos** y **Acceso** y el **BFF Web** están implementados; los endpoints de negocio que aún no lo estén responden `501 NO_IMPLEMENTADO` (en ese caso el BFF contesta `502`, ver [BFF Web](#bff-web)).

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

Cualquier otra ruta responde `404` desde Kong (el `/health` y el `/metrics` del BFF, por ejemplo, no pasan por el gateway). Cada respuesta trae un encabezado `X-Request-ID`, que Kong también envía al servicio para seguir la petición en los logs.

Ejemplo (Git Bash):

```bash
TOKEN=$(python scripts/generar_token.py)
curl -i "http://localhost:8000/api/espacios?fecha=2026-11-20" -H "Authorization: Bearer $TOKEN"
```

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

Acceso es la única fuente opcional: sin el QR la vista sigue siendo útil, mientras que sin el espacio o sin el pago podría leerse como "no hay reserva" o "no pagué" (decisión D-54).

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

## Parámetros de resiliencia

Los timeouts, el Circuit Breaker, el Bulkhead y los reintentos se configuran con variables de entorno, con los valores acordados por defecto (ver [docs/DECISIONES.md](docs/DECISIONES.md), D-40 a D-49). [.env.example](.env.example) lista todos los nombres. Para un experimento basta cambiar uno, por ejemplo:

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

_La verificación de punta a punta queda pendiente hasta que esté implementado el orquestador de la Saga._

| Escenario | Cómo provocarlo | Resultado esperado |
|---|---|---|
| 1. Éxito | Sin fallas inyectadas | Los tres pasos quedan firmes: saga `CONFIRMADA` |
| 2. Fallo con compensación | `python scripts/chaos.py acceso error` | Acceso falla en el paso 3: reembolso y liberación del espacio en orden inverso; saga `COMPENSADA` |
| 3. Falla en cascada contenida | `python scripts/chaos.py acceso slow 3000` y luego `docker compose stop acceso` | El Circuit Breaker abre y responde de inmediato, y el Bulkhead rechaza el exceso; el resto del sistema sigue respondiendo |

Para comparar el sistema sin los patrones de resiliencia, levantar con `RESILIENCE_ENABLED=false` (ver [.env.example](.env.example)).

**Evidencia desde el BFF.** Con Espacios y Pagos respondiendo y una saga existente, la degradación de Acceso se puede ver sin esperar al orquestador:

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
observability/                   Prometheus y aprovisionamiento de Grafana
k6/                              Scripts de carga y prueba de humo
docs/DECISIONES.md               Registro de decisiones de diseño y alternativas descartadas
docs/api/                        Contratos OpenAPI de cada servicio
scripts/generar_token.py         JWT de desarrollo
scripts/probar_exposicion.sh     Verifica JWT, rate limiting y puertos publicados
scripts/chaos.py                 Cambia el modo de falla de Pagos y Acceso
scripts/exportar_contratos.py    Regenera docs/api/ a partir del código
```
