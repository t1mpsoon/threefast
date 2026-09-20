"""Собирает app/static/js/qr.js из MIT-библиотеки QRCode (Kazuhiko Arase, как в qrcode-terminal).

Запуск при необходимости пересобрать: python tools/build_qr.py <путь к vendor/QRCode>
"""
import sys
from pathlib import Path

src = Path(sys.argv[1])
order = ["QRMode", "QRErrorCorrectLevel", "QRMaskPattern", "QRMath", "QRPolynomial", "QRUtil",
         "QRRSBlock", "QRBitBuffer", "QR8bitByte", "index"]
parts = ["/* QR-код без внешних сервисов. Основа: QRCode for JavaScript (c) 2009 Kazuhiko Arase, MIT. */",
         "(function () {", "var M = {}, C = {};",
         "function req(n) { n = n.replace('./', ''); if (C[n]) return C[n].exports;",
         "  var m = C[n] = { exports: {} }; M[n](m, m.exports, req); return m.exports; }"]
for name in order:
    code = (src / f"{name}.js").read_text(encoding="utf-8")
    parts.append(f"M['{name}'] = function (module, exports, require) {{\n{code}\n}};")
parts.append("""
var QRCode = req('index'), Level = req('QRErrorCorrectLevel');

/* Матрица модулей: подбирает наименьшую версию, в которую влезает текст. */
function matrix(text, level) {
  for (var type = 1; type <= 40; type++) {
    try {
      var qr = new QRCode(type, level === undefined ? Level.M : level);
      qr.addData(text); qr.make();
      var n = qr.getModuleCount(), rows = [];
      for (var r = 0; r < n; r++) { var row = []; for (var c = 0; c < n; c++) row.push(qr.isDark(r, c)); rows.push(row); }
      return rows;
    } catch (e) { if (type === 40) throw e; }
  }
}

/* SVG: тёмные модули на белом, с полем в 4 модуля — так код читается любой камерой. */
function svg(text, opts) {
  opts = opts || {};
  var m = matrix(text), n = m.length, q = 4, d = '';
  for (var r = 0; r < n; r++) {
    var c = 0;
    while (c < n) {
      if (m[r][c]) { var s = c; while (c < n && m[r][c]) c++; d += 'M' + (s + q) + ' ' + (r + q) + 'h' + (c - s) + 'v1h-' + (c - s) + 'z'; }
      else c++;
    }
  }
  var t = n + q * 2, px = opts.size || 220;
  return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ' + t + ' ' + t + '" width="' + px + '" height="' + px +
    '" shape-rendering="crispEdges" role="img" aria-label="' + (opts.label || 'QR-код') + '"><rect width="' + t + '" height="' + t +
    '" fill="#fff"/><path d="' + d + '" fill="#000"/></svg>';
}

window.EPQR = { matrix: matrix, svg: svg };
})();""")
Path("app/static/js/qr.js").write_text("\n".join(parts), encoding="utf-8")
print("ok")
