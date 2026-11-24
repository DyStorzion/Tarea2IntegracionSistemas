// Escenario 3 · Falla en cascada contenida: Acceso tarda 3 s (más que su timeout de 1,5 s) durante 60 s,
// mientras en paralelo se consulta la disponibilidad de espacios.
// Los primeros segundos ("deteccion") las reservas esperan el timeout y se compensan; luego el circuito
// abre y las reservas se rechazan al instante (503). La consulta de disponibilidad no se entera.
// Con RESILIENCE_ENABLED=false cada reserva espera el timeout y la revocación lenta (~4,5 s): el umbral
// de latencia de las reservas falla.
// Uso: docker compose run --rm k6 run /scripts/cascada.js
import { definirEscenario } from './lib/escenario.js';

export { setup, teardown, reservar, consultar, controlarFallas, handleSummary } from './lib/escenario.js';

export const options = definirEscenario({
  nombre: 'cascada',
  descripcion: 'Acceso tarda 3 s durante 60 s: las reservas fallan rápido y la consulta de disponibilidad sigue igual.',
  duracion: 110,
  reservasPorSegundo: 4,
  consultasPorSegundo: 2,
  linea: [
    { desde: 0, fase: 'normal' },
    { desde: 20, fase: 'deteccion', fallas: [['acceso', 'slow', 3000]] }, // el circuito necesita unos fallos para abrir
    { desde: 26, fase: 'falla' },
    { desde: 80, fase: 'recuperacion', fallas: [['acceso', 'ok']] },
  ],
  umbrales: [
    {
      metrica: 'http_req_duration{escenario:reserva,fase:falla}',
      condicion: 'p(95)<1000',
      etiqueta: 'durante la falla las reservas responden en menos de 1 s (p95): fallan rápido en vez de esperar a Acceso',
    },
    {
      metrica: 'http_req_duration{escenario:consulta,fase:falla}',
      condicion: 'p(95)<300',
      etiqueta: 'durante la falla la consulta de disponibilidad responde en menos de 300 ms (p95)',
    },
    {
      metrica: 'checks{check:la consulta de disponibilidad responde 200}',
      condicion: 'rate==1',
      etiqueta: 'todas las consultas de disponibilidad responden 200',
    },
    {
      metrica: 'checks{check:la saga termina en un estado final consistente}',
      condicion: 'rate==1',
      etiqueta: 'ninguna saga queda a medias (COMPENSACION_PENDIENTE) ni sin respuesta',
    },
  ],
});
