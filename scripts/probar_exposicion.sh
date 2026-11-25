#!/usr/bin/env bash
# Verifica la capa de exposición: JWT, rate limiting y que solo Kong publica puerto.
# Requiere el sistema levantado (docker compose up -d --build).
set -uo pipefail

GW="${GATEWAY_URL:-http://localhost:8000}"
RUTA="${RUTA:-/api/espacios}"   # cualquier ruta enrutada sirve: aquí solo importa pasar la puerta
DIR="$(cd "$(dirname "$0")" && pwd)"
# Se usa el primer intérprete que realmente funcione: en Windows, `python3` suele ser el acceso
# directo de la Microsoft Store, que existe en el PATH pero no ejecuta nada.
PY=""
for candidato in python3 python; do
  if command -v "$candidato" >/dev/null 2>&1 && "$candidato" -c "import sys" >/dev/null 2>&1; then
    PY="$candidato"
    break
  fi
done
if [ -z "$PY" ]; then echo "No encontré un python3 o python que funcione en el PATH de este bash" >&2; exit 1; fi
TOKEN="$("$PY" "$DIR/generar_token.py")"

codigo() { curl -s -o /dev/null -w '%{http_code}' "$@"; }

echo "1) Sin token                -> esperado 401"
echo "   obtenido: $(codigo "$GW$RUTA")"

echo "2) Token inválido           -> esperado 401"
echo "   obtenido: $(codigo -H 'Authorization: Bearer abc.def.ghi' "$GW$RUTA")"

echo "3) Token válido             -> esperado distinto de 401 (404 del servicio es OK si no hay ruta)"
echo "   obtenido: $(codigo -H "Authorization: Bearer $TOKEN" "$GW$RUTA")"

echo "4) Ráfaga de 40 peticiones en paralelo -> esperado: algunos 429"
sleep 1.1   # que la ventana de 1 s parta limpia
seq 1 40 | xargs -P 40 -I{} curl -s -o /dev/null -w '%{http_code}\n' \
  -H "Authorization: Bearer $TOKEN" "$GW$RUTA" | sort | uniq -c | sed 's/^/   /'

echo "5) Puertos publicados (esperado: solo Kong hacia afuera; Grafana y Prometheus solo en 127.0.0.1)"
if command -v docker >/dev/null 2>&1; then
  docker compose config --format json 2>/dev/null \
    | "$PY" -c '
import json, sys
cfg = json.load(sys.stdin)
for nombre, svc in cfg["services"].items():
    for p in svc.get("ports", []):
        ip = p.get("host_ip") or "0.0.0.0"
        alcance = "solo este equipo" if ip.startswith("127.") else "todas las interfaces"
        print("   %-10s %s:%s -> %s  (%s)" % (nombre, ip, p.get("published"), p.get("target"), alcance))
'
else
  echo "   (docker no disponible; revisa con: docker compose ps)"
fi