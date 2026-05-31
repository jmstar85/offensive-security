import ws from 'k6/ws';
import { check } from 'k6';

export const options = {
  vus: 100,
  duration: '60s',
  thresholds: { ws_session_duration: ['p(95)<2500'] },
};

const HOST = __ENV.OSA_WS_HOST || 'ws://backend:8000';

export default function () {
  const url = `${HOST}/ws/sessions/${__VU}-${__ITER}?topic=conversation`;
  const res = ws.connect(url, {}, function (socket) {
    socket.on('open', () => socket.setTimeout(() => socket.close(), 500));
    socket.on('message', (m) => check(m, { 'msg has type': (s) => s.includes('type') }));
  });
  check(res, { 'connected': (r) => r && r.status === 101 });
}
