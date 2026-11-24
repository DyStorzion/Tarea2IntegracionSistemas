// Escenario 2 · Fallo con compensación: Acceso responde 500 durante 40 s.
// Las reservas que llegan al paso 3 se compensan en orden inverso (reembolso y liberación): 502 COMPENSADA.
// Tras unos fallos el circuito abre y las siguientes se rechazan sin reservar ni cobrar (503 RECHAZADA);
// cada 10 s una llamada de prueba vuelve a fallar y esa saga también se compensa.
// Con RESILIENCE_ENABLED=false no hay circuito: todas las reservas de la falla se compensan.
// Uso: docker compose run --rm k6 run /scripts/compensacion.js
import { definirEscenario } from './lib/escenario.js';

export { setup, teardown, reservar, consultar, controlarFallas, handleSummary } from './lib/escenario.js';

export const options = definirEscenario({
  nombre: 'compensacion',
  descripcion: 'Acceso responde 500 durante 40 s: las sagas se compensan y ninguna queda a medias.',
  duracion: 80,
  reservasPorSegundo: 2,
  linea: [
    { desde: 0, fase: 'normal' },
    { desde: 15, fase: 'falla', fallas: [['acceso', 'error']] },
    { desde: 55, fase: 'recuperacion', fallas: [['acceso', 'ok']] },
  ],
  umbrales: [
    {
      metrica: 'checks{check:la saga termina en un estado final consistente}',
      condicion: 'rate==1',
      etiqueta: 'ninguna saga queda a medias (COMPENSACION_PENDIENTE) ni sin respuesta',
    },
    {
      metrica: 'sagas{fase:falla,estado:COMPENSADA}',
      condicion: 'count>0',
      etiqueta: 'durante la falla hay sagas compensadas en orden inverso',
    },
    {
      metrica: 'checks{check:durante la falla ninguna reserva se confirma}',
      condicion: 'rate==1',
      etiqueta: 'durante la falla ninguna reserva queda confirmada sin puerta habilitada',
    },
    {
      metrica: 'checks{check:sin falla la reserva queda confirmada}',
      condicion: 'rate==1',
      etiqueta: 'antes de la falla todas las reservas quedan CONFIRMADAS',
    },
  ],
  verificar: ({ fase, estado, status }) => {
    if (fase === 'normal') return { 'sin falla la reserva queda confirmada': status === 201 && estado === 'CONFIRMADA' };
    if (fase === 'falla') return { 'durante la falla ninguna reserva se confirma': estado !== 'CONFIRMADA' };
    return {};
  },
});
