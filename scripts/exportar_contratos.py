"""Exporta el contrato OpenAPI de cada servicio a docs/api/<servicio>.json.

Genera el OpenAPI dentro de la imagen Docker de cada servicio, así que no hace falta
instalar FastAPI localmente. Ejecutar después de cambiar cualquier app/contrato.py o ruta:

    python scripts/exportar_contratos.py

Los archivos generados se versionan: un cambio de contrato aparece en el diff.
"""

import json
import pathlib
import subprocess
import sys

SERVICIOS = ["reservas", "espacios", "pagos", "acceso", "bff-web"]
RAIZ = pathlib.Path(__file__).resolve().parent.parent
DESTINO = RAIZ / "docs" / "api"
CODIGO = "import json; from app.main import app; print(json.dumps(app.openapi(), ensure_ascii=False))"


def exportar(servicio: str) -> bool:
    comando = ["docker", "compose", "run", "--rm", "--no-deps", "--build", "-T", servicio, "python", "-c", CODIGO]
    r = subprocess.run(comando, cwd=RAIZ, capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        print(f"[ERROR] {servicio}:\n{r.stderr.strip()}", file=sys.stderr)
        return False
    # La última línea de stdout es el JSON; lo anterior pueden ser logs del servicio.
    spec = json.loads(r.stdout.strip().splitlines()[-1])
    archivo = DESTINO / f"{servicio}.json"
    archivo.write_text(json.dumps(spec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"[OK] {archivo.relative_to(RAIZ)} ({len(spec.get('paths', {}))} rutas)")
    return True


def main() -> int:
    DESTINO.mkdir(parents=True, exist_ok=True)
    resultados = [exportar(s) for s in SERVICIOS]
    return 0 if all(resultados) else 1


if __name__ == "__main__":
    sys.exit(main())
