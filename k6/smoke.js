// Prueba de humo del gateway: autenticación y enrutamiento.
// Uso: docker compose run --rm k6 run /scripts/smoke.js
import http from 'k6/http';
import { check } from 'k6';
import { generarToken } from './lib/token.js';

const BASE_URL = __ENV.BASE_URL || 'http://kong:8000';

export const options = {
  vus: 1,
  iterations: 1,
  thresholds: { checks: ['rate==1'] }, // cualquier check fallido hace fallar la prueba
};

// Kong agrega X-Kong-Upstream-Latency solo cuando la petición llegó al servicio.
// Mientras los servicios no estén implementados responden 501 (o 404 propio):
// lo importante es que el gateway dejó pasar la petición.
const llegoAlServicio = (r) => r.headers['X-Kong-Upstream-Latency'] !== undefined;
const conToken = (consumidor, extra = {}) => ({
  headers: { Authorization: `Bearer ${generarToken(consumidor)}`, ...extra },
});

export default function () {
  const fecha = new Date().toISOString().slice(0, 10);
  const espacios = `${BASE_URL}/api/espacios?fecha=${fecha}`;

  const sinToken = http.get(espacios);
  check(sinToken, { 'sin token -> 401': (r) => r.status === 401 });

  const [h, p] = generarToken('cliente-demo').split('.');
  const invalido = http.get(espacios, { headers: { Authorization: `Bearer ${h}.${p}.${'A'.repeat(43)}` } });
  check(invalido, { 'firma inválida -> 401': (r) => r.status === 401 });

  const esp = http.get(espacios, conToken('cliente-demo'));
  check(esp, {
    'GET /api/espacios (cliente-demo) -> llega a espacios': llegoAlServicio,
    'respuesta trae X-Request-ID': (r) => !!r.headers['X-Request-Id'],
  });

  const reserva = http.post(
    `${BASE_URL}/api/reservas`,
    JSON.stringify({ espacio_id: 'SALA-A', fecha, bloque: 9 }),
    conToken('cliente-demo', { 'Content-Type': 'application/json', 'Idempotency-Key': `smoke-${Date.now()}` }),
  );
  check(reserva, { 'POST /api/reservas (cliente-demo) -> llega a reservas': llegoAlServicio });

  const bff = http.get(`${BASE_URL}/bff/web/mis-reservas/smoke-saga`, conToken('cliente-demo-2'));
  check(bff, { 'GET /bff/web/mis-reservas/{saga_id} (cliente-demo-2) -> llega a bff-web': llegoAlServicio });

  const desconocida = http.get(`${BASE_URL}/no-existe`, conToken('cliente-demo-2'));
  check(desconocida, { 'ruta desconocida -> 404 de Kong': (r) => r.status === 404 && !llegoAlServicio(r) });
}
