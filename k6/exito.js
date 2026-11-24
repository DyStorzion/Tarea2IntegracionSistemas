// Escenario 1 · Éxito: sin fallas inyectadas, cada reserva recorre los tres pasos y queda confirmada.
// Uso: docker compose run --rm k6 run /scripts/exito.js
import { definirEscenario } from './lib/escenario.js';

export { setup, teardown, reservar, consultar, controlarFallas, handleSummary } from './lib/escenario.js';

export const options = definirEscenario({
  nombre: 'exito',
  descripcion: 'Sin fallas inyectadas: Espacios, Pagos y Acceso responden y cada reserva queda CONFIRMADA.',
  duracion: 30,
  reservasPorSegundo: 4,
  linea: [{ desde: 0, fase: 'normal' }],
  umbrales: [
    {
      metrica: 'checks{check:la reserva queda confirmada}',
      condicion: 'rate==1',
      etiqueta: 'todas las reservas quedan CONFIRMADAS (201)',
    },
    {
      metrica: 'http_req_duration{escenario:reserva}',
      condicion: 'p(95)<500',
      etiqueta: 'p95 de las reservas bajo 500 ms',
    },
  ],
  verificar: ({ estado, status }) => ({ 'la reserva queda confirmada': status === 201 && estado === 'CONFIRMADA' }),
});
