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
docker compose up --build
```

Puertos disponibles en el host:

| URL | Qué es |
|---|---|
| http://localhost:8000 | API Gateway (único punto de entrada al sistema) |
| http://localhost:3000 | Grafana (solo localhost) |
| http://localhost:9090 | Prometheus (solo localhost) |

Para bajar todo y borrar las bases de datos:

```bash
docker compose down -v
```

## Autenticación

Kong exige un JWT HS256 en el encabezado `Authorization`. Para generar uno de desarrollo:

```bash
python scripts/generar_token.py cliente-1
```

Hay dos consumidores configurados, `cliente-1` y `cliente-2` (útil para mostrar que el rate limiting es por cliente). Los secretos de [gateway/kong.yml](gateway/kong.yml) son solo de desarrollo.

## Rutas expuestas por el gateway

| Método | Ruta en el gateway | Servicio interno |
|---|---|---|
| `POST` | `/api/reservas` | `reservas` → inicia la Saga |
| `GET` | `/api/reservas/{sagaId}` | `reservas` → estado y saga log |
| `GET` | `/api/espacios` | `espacios` → disponibilidad |
| `GET` | `/bff/web/mis-reservas/{sagaId}` | `bff-web` → vista agregada |

Ejemplo (Git Bash):

```bash
TOKEN=$(python scripts/generar_token.py cliente-1)
curl -i http://localhost:8000/api/espacios -H "Authorization: Bearer $TOKEN"
```

## Prueba de humo

Verifica que el gateway rechaza peticiones sin token y deja pasar las autenticadas:

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
