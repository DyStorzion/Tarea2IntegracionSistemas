#!/usr/bin/env bash
# Verifica la capa de exposición: JWT, rate limiting y que solo Kong publica puerto.
# Requiere el sistema levantado (docker compose up -d --build).
set -uo pipefail

GW="${GATEWAY_URL:-http://localhost:8000}"
RUTA="${RUTA:-/api/espacios}"   # cualquier ruta enrutada sirve: aquí solo importa pasar la puerta
DIR="$(cd "$(dirname "$0")" && pwd)"
TOKEN="$(python3 "$DIR/generar_token.py")"

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

echo "5) Puertos publicados al exterior (esperado: solo el de Kong)"
if command -v docker >/dev/null 2>&1; then
  docker compose config --format json 2>/dev/null \
    | python3 -c '
import json, sys
cfg = json.load(sys.stdin)
for nombre, svc in cfg["services"].items():
    for p in svc.get("ports", []):
        print("   %s -> %s:%s" % (nombre, p.get("published"), p.get("target")))
'
else
  echo "   (docker no disponible; revisa con: docker compose ps)"
fi
