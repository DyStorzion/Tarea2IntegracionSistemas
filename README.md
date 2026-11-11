# Cowork — Reserva de espacios resiliente

Encargo integrador, Unidad 3 de Integración de Sistemas (Forma O).

Sistema de microservicios que reserva un puesto o sala de cowork coordinando **Espacios**, **Pagos** (pasarela externa) y **Acceso** (controlador externo de puerta con QR) mediante una **Saga orquestada**, expuesto por un **API Gateway** y un **BFF**, y protegido con **timeout, Circuit Breaker y Bulkhead**.

> **Estado:** esqueleto. Los servicios levantan y responden `/health` y `/metrics/`; los endpoints de negocio responden `501 No implementado`.

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

## Escenarios de falla

_Por completar a medida que se implementen._

1. **Éxito:** camino feliz de la Saga.
2. **Fallo con compensación:** Acceso falla en el paso 3 → reembolso y liberación en orden inverso.
3. **Falla en cascada contenida:** Acceso lento y luego caído → el Circuit Breaker abre y el Bulkhead rechaza el exceso.

Para comparar el sistema sin los patrones de resiliencia, levantar con `RESILIENCE_ENABLED=false` (ver [.env.example](.env.example)).

## Estructura

```
gateway/kong.yml                 Configuración declarativa de Kong
services/<servicio>/             Un microservicio FastAPI por carpeta (Dockerfile + app/)
observability/                   Prometheus y aprovisionamiento de Grafana
k6/                              Scripts de carga y prueba de humo
scripts/generar_token.py         JWT de desarrollo
```
