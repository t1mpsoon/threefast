/* Проверка круга «генерация -> распознавание» без браузера.
 *
 * Берём QR, который рисует наш app/static/js/qr.js, растеризуем его в пиксели
 * и читаем тем самым декодером, который отдаётся сканеру
 * (app/static/js/vendor/jsQR.min.js). Если круг замкнулся — код на экране гостя
 * действительно читается сканером кухни.
 *
 * Запуск: node tools/check_qr_roundtrip.js
 */
'use strict';

const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = path.resolve(__dirname, '..');

function loadGenerator() {
  const sandbox = { window: {}, console };
  sandbox.window.window = sandbox.window;
  vm.createContext(sandbox);
  vm.runInContext(
    fs.readFileSync(path.join(ROOT, 'app', 'static', 'js', 'qr.js'), 'utf8'),
    sandbox
  );
  return sandbox.window.EPQR;
}

function loadDecoder() {
  const loaded = require(path.join(ROOT, 'app', 'static', 'js', 'vendor', 'jsQR.min.js'));
  return typeof loaded === 'function' ? loaded : loaded.default;
}

/* Матрица модулей -> RGBA-пиксели: тёмные модули на белом, поле в 4 модуля. */
function rasterize(matrix, scale) {
  const quiet = 4;
  const modules = matrix.length + quiet * 2;
  const size = modules * scale;
  const data = new Uint8ClampedArray(size * size * 4).fill(255);
  for (let r = 0; r < matrix.length; r++) {
    for (let c = 0; c < matrix.length; c++) {
      if (!matrix[r][c]) continue;
      for (let y = 0; y < scale; y++) {
        for (let x = 0; x < scale; x++) {
          const px = ((r + quiet) * scale + y) * size + ((c + quiet) * scale + x);
          data[px * 4] = 0;
          data[px * 4 + 1] = 0;
          data[px * 4 + 2] = 0;
        }
      }
    }
  }
  return { data, size };
}

const CASES = [
  ['витрина заведения', 'https://threefast.onrender.com/e/1/menu'],
  ['ссылка со меткой стола', 'https://threefast.onrender.com/e/3/menu?src=table12'],
  ['страница заказа гостя', 'https://threefast.onrender.com/order?code=EX-3467'],
  ['короткий код', 'EX-3467'],
  ['длинный адрес', 'https://threefast.onrender.com/e/2/menu?src=table60&utm=poster'],
];

const SCALES = [8, 4, 3];

const EPQR = loadGenerator();
const jsQR = loadDecoder();

if (typeof jsQR !== 'function') {
  console.error('jsQR не загрузился: декодер не экспортирует функцию');
  process.exit(2);
}

let failures = 0;

for (const [title, text] of CASES) {
  const matrix = EPQR.matrix(text);
  for (const scale of SCALES) {
    const { data, size } = rasterize(matrix, scale);
    const found = jsQR(data, size, size, { inversionAttempts: 'attemptBoth' });
    const ok = Boolean(found) && found.data === text;
    if (!ok) failures++;
    const mark = ok ? 'OK  ' : 'FAIL';
    const extra = ok ? '' : ` (прочитано: ${found ? JSON.stringify(found.data) : 'ничего'})`;
    console.log(`[${mark}] ${title}, версия ${matrix.length}x${matrix.length}, ${scale} px/модуль${extra}`);
  }
}

console.log(failures ? `\nПРОВАЛОВ: ${failures}` : '\nВсе QR читаются декодером сканера.');
process.exit(failures ? 1 : 0);
