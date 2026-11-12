# Cowork — Reserva de espacios resiliente

Encargo integrador, Unidad 3 de Integración de Sistemas (Forma O).

Sistema de microservicios que reserva un puesto o sala de cowork coordinando **Espacios**, **Pagos** (pasarela externa) y **Acceso** (controlador externo de puerta con QR) mediante una **Saga orquestada**, expuesto por un **API Gateway** y un **BFF**, y protegido con **timeout, Circuit Breaker y Bulkhead**.

> **Estado:** en desarrollo. Los simuladores de **Pagos** y **Acceso** están implementados; los demás endpoints de negocio responden `501 NO_IMPLEMENTADO`.

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
| http://127.0.0.1:3000 | Grafana (acceso anónimo como administrador, sin login) | solo localhost |
| http://127.0.0.1:9090 | Prometheus | solo localhost |

Los microservicios, las bases de datos y el endpoint de métricas de Kong (`kong:8100/metrics`) no publican puertos: solo son accesibles dentro de la red interna de Docker.

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
| `GET` | `/bff/web/mis-reservas/{saga_id}` | `bff-web` `GET /mis-reservas/{saga_id}` → vista agregada |

Cualquier otra ruta responde `404` desde Kong. Cada respuesta trae un encabezado `X-Request-ID`, que Kong también envía al servicio para seguir la petición en los logs.

Ejemplo (Git Bash):

```bash
TOKEN=$(python scripts/generar_token.py)
curl -i "http://localhost:8000/api/espacios?fecha=2026-11-20" -H "Authorization: Bearer $TOKEN"
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

Para una **caída real** (el contenedor no existe, las conexiones se rechazan):

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

## Estructura

```
gateway/kong.yml                 Configuración declarativa de Kong
services/<servicio>/             Un microservicio FastAPI por carpeta (Dockerfile + app/)
observability/                   Prometheus y aprovisionamiento de Grafana
k6/                              Scripts de carga y prueba de humo
docs/api/                        Contratos OpenAPI de cada servicio
scripts/generar_token.py         JWT de desarrollo
scripts/chaos.py                 Cambia el modo de falla de Pagos y Acceso
scripts/exportar_contratos.py    Regenera docs/api/ a partir del código
```
