"""Consulta o cambia el modo de falla de los simuladores pagos y acceso.

El endpoint /admin/chaos no se publica fuera de la red de Docker, para que nadie
externo pueda provocar fallas. Por eso este script no llama al servicio desde el
host: ejecuta `docker compose exec` y hace la petición DENTRO del contenedor, a
http://localhost:8000/admin/chaos.

Modos:
- ok:    comportamiento normal.
- slow:  espera delay_ms (por defecto 3000) y luego procesa la petición.
- error: responde 500 sin ejecutar nada.
- down:  responde 503 sin ejecutar nada.
Solo afectan a las rutas de negocio; /health, /metrics y /admin siguen respondiendo.

Uso (desde cualquier carpeta):
    python scripts/chaos.py pagos              # muestra el modo actual
    python scripts/chaos.py pagos slow         # slow con 3000 ms
    python scripts/chaos.py pagos slow 1500
    python scripts/chaos.py acceso down
    python scripts/chaos.py pagos ok           # vuelve a la normalidad

Los scripts de k6 corren dentro de la red de Docker, así que pueden llamar
directamente a http://<servicio>:8000/admin/chaos. Para una caída real (el
contenedor no existe, no solo responde 503) usar `docker compose stop acceso`.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DELAY_POR_DEFECTO = 3000

# Corre dentro del contenedor. El método y el cuerpo llegan como argumentos (no se
# insertan en el código) para evitar problemas de comillas. Siempre imprime una línea
# JSON con el status y el cuerpo, también cuando la respuesta es un error HTTP.
CODIGO = """
import json, sys, urllib.error, urllib.request
cuerpo = sys.argv[2].encode() if len(sys.argv) > 2 else None
req = urllib.request.Request("http://localhost:8000/admin/chaos", data=cuerpo, method=sys.argv[1],
                             headers={"Content-Type": "application/json"})
try:
    with urllib.request.urlopen(req, timeout=10) as r:
        status, texto = r.status, r.read().decode()
except urllib.error.HTTPError as e:
    status, texto = e.code, e.read().decode()
print(json.dumps({"status": status, "body": texto}))
"""


def describir_error(cuerpo) -> str:
    detalle = cuerpo.get("detail", cuerpo) if isinstance(cuerpo, dict) else cuerpo
    if isinstance(detalle, dict):
        return f"{detalle.get('codigo', '?')}: {detalle.get('mensaje', '')}"
    if isinstance(detalle, list):  # 422 de FastAPI: lista de errores de validación
        return "VALIDACION: " + "; ".join(str(e.get("msg", e)) for e in detalle)
    return str(detalle)


def main() -> int:
    # En Windows, si la salida no es una consola (p. ej. Git Bash), Python usaría cp1252 y los acentos se verían mal.
    for flujo in (sys.stdout, sys.stderr):
        flujo.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description="Consulta o cambia el modo de falla de pagos/acceso.")
    p.add_argument("servicio", choices=["pagos", "acceso"])
    p.add_argument("modo", nargs="?", choices=["ok", "slow", "error", "down"], help="sin modo: muestra el actual")
    p.add_argument("delay_ms", nargs="?", type=int, help=f"solo para slow (por defecto {DELAY_POR_DEFECTO})")
    a = p.parse_args()

    peticion = ["GET"]
    if a.modo:  # delay_ms solo se envía con slow; en los otros modos el servicio lo deja en 0
        cambio = {"modo": a.modo}
        if a.modo == "slow":
            cambio["delay_ms"] = DELAY_POR_DEFECTO if a.delay_ms is None else a.delay_ms
        peticion = ["POST", json.dumps(cambio)]
    comando = ["docker", "compose", "exec", "-T", a.servicio, "python", "-c", CODIGO, *peticion]
    try:
        r = subprocess.run(comando, cwd=RAIZ, capture_output=True, text=True, encoding="utf-8")
    except FileNotFoundError:
        print("error: no se encontró el comando docker (¿está instalado y en el PATH?)", file=sys.stderr)
        return 1
    if r.returncode != 0:
        causa = (r.stderr.strip().splitlines() or ["sin detalle"])[-1]
        print(f"error: no se pudo llamar a {a.servicio} dentro de su contenedor: {causa}", file=sys.stderr)
        print(f"Si el contenedor no está corriendo, levantarlo con: docker compose up -d {a.servicio}", file=sys.stderr)
        return 1

    respuesta = json.loads(r.stdout.strip().splitlines()[-1])
    try:
        cuerpo = json.loads(respuesta["body"])
    except ValueError:
        cuerpo = respuesta["body"]
    if respuesta["status"] >= 400:
        print(f"{a.servicio}: HTTP {respuesta['status']} {describir_error(cuerpo)}", file=sys.stderr)
        return 1
    print(f"{a.servicio}: modo={cuerpo['modo']} delay_ms={cuerpo['delay_ms']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
