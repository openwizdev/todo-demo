"""Public CLI proofs on synthetic HTTP pages using the installed browser-harness.

Without an installed harness, CI uses the test-only Chromium/Playwright bridge.
"""
import http.server
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import unittest
import zlib

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'screenshot.py'
PAGE = b'''<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Synthetic screenshot fixture</title>
<style>html,body{margin:0;background:#faf9f6}main{height:1100px;background:#0072b2}
@media(max-width:500px){main{height:1200px;background:#d55e00}}</style>
<script>addEventListener('load',()=>requestAnimationFrame(()=>{
const main=document.createElement('main');main.textContent='Synthetic ready page';
main.id='ready';document.body.append(main);
}));</script>'''
FIXED_PAGE = PAGE + b'''<style>
footer{position:fixed;bottom:0;left:0;width:100%;height:64px;background:#cc79a7}
</style><footer></footer>'''


def png_column(path):
    """The rightmost column's RGB values, top to bottom, from the rendered
    pixels, not DOM coordinates (which miss captureBeyondViewport's fixed-bar
    bug). A small reader of its own: 8-bit, non-interlaced RGB or RGBA, which
    is what Chromium's screenshots are."""
    data = Path(path).read_bytes()
    if data[:8] != b'\x89PNG\r\n\x1a\n':
        raise ValueError('not a PNG')
    off, idat, width, height, channels = 8, [], 0, 0, 0
    while off < len(data):
        length, kind = struct.unpack('>I4s', data[off:off + 8])
        chunk = data[off + 8:off + 8 + length]
        if kind == b'IHDR':
            width, height, depth, colour, _, _, interlace = struct.unpack('>IIBBBBB', chunk)
            channels = {2: 3, 6: 4}.get(colour, 0)
            if depth != 8 or interlace or not channels:
                raise ValueError('unsupported PNG')
        elif kind == b'IDAT':
            idat.append(chunk)
        elif kind == b'IEND':
            break
        off += 12 + length
    raw, stride = zlib.decompress(b''.join(idat)), width * channels
    prev, column = bytearray(stride), []
    for y in range(height):
        base = y * (stride + 1)
        kind, line = raw[base], bytearray(raw[base + 1:base + 1 + stride])
        for x in range(stride):
            a = line[x - channels] if x >= channels else 0
            b = prev[x]
            c = prev[x - channels] if x >= channels else 0
            if kind == 1:
                add = a
            elif kind == 2:
                add = b
            elif kind == 3:
                add = (a + b) >> 1
            elif kind == 4:
                pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                add = a if pa <= pb and pa <= pc else b if pb <= pc else c
            else:
                add = 0
            line[x] = (line[x] + add) & 0xff
        right = (width - 1) * channels
        column.append(list(line[right:right + 3]))
        prev = line
    return column


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200 if self.path in ('/', '/fragment', '/empty', '/broken', '/fixed', '/wide', '/short-wide') else 404)
        self.send_header('Content-Type', 'text/html')
        self.end_headers()
        if self.path == '/fixed':
            self.wfile.write(FIXED_PAGE)
        elif self.path == '/fragment':
            self.wfile.write(b'''<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1">
            <style>html,body{margin:0}</style><body><main id="ready"></main>
            <script>document.querySelector('main').style.height = innerWidth < 500 ? '1200px' : '1500px';</script>''')
        elif self.path == '/wide':
            self.wfile.write(PAGE + b'<style>@media(max-width:500px){body{width:600px}}</style>')
        elif self.path == '/short-wide':
            # Wider than the phone only while the viewport is short, so the
            # first screen overflows and the page-height capture does not.
            self.wfile.write(PAGE + b'<style>@media(max-width:500px) and (max-height:900px)'
                             b'{body{width:600px}}</style>')
        elif self.path == '/empty':
            self.wfile.write(PAGE + b'<img alt="Optional empty placeholder">')
        elif self.path == '/broken':
            self.wfile.write(PAGE + b'<img src="/not-an-image" alt="Broken source">')
        else:
            self.wfile.write(PAGE if self.path == '/' else b'Not found')

    def log_message(self, *args):
        pass


class Screenshots(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f'http://127.0.0.1:{cls.server.server_port}/'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def run_capture(self, output, *args, url=None):
        env = os.environ.copy()
        if shutil.which('browser-harness') is None:
            env['PATH'] = (str(Path(__file__).parent / 'bridge')
                           + os.pathsep + env.get('PATH', ''))
        return subprocess.run([sys.executable, str(SCRIPT), url or self.url,
                               '--out', str(output), '--ready-selector', '#ready',
                               '--timeout', '5', *args], text=True,
                              capture_output=True, timeout=90, env=env)

    def test_phone_and_desktop_capture_real_responsive_ready_page(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / 'round-1'
            result = self.run_capture(out)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertEqual(sorted(p.name for p in out.iterdir()),
                             ['capture.json', 'desktop.png', 'phone.png'])
            for name, dimensions in [('phone', (390, 1200)), ('desktop', (1440, 1100))]:
                png = (out / f'{name}.png').read_bytes()
                self.assertEqual(png[:8], b'\x89PNG\r\n\x1a\n')
                self.assertEqual(struct.unpack('>II', png[16:24]), dimensions)
            manifest = json.loads((out / 'capture.json').read_text())
            self.assertEqual(manifest['url'], self.url)
            self.assertEqual([(p['name'], p['viewport']) for p in manifest['captures']],
                             [('phone', {'width': 390, 'height': 844}),
                              ('desktop', {'width': 1440, 'height': 900})])
            self.assertEqual([p['page']['width'] for p in manifest['captures']], [390, 1440])
            self.assertEqual([p['page']['height'] for p in manifest['captures']], [1200, 1100])
            second = self.run_capture(out)
            self.assertNotEqual(second.returncode, 0, 'existing evidence must survive')
            self.assertEqual(json.loads((out / 'capture.json').read_text()), manifest)

    def test_short_result_names_horizontal_overflow(self):
        # catches: a phone shot wider than its viewport handed back without
        # anyone reading contentWidth in the manifest.
        with tempfile.TemporaryDirectory() as temp:
            wide = self.run_capture(Path(temp) / 'wide', url=self.url + 'wide')
            self.assertEqual(wide.returncode, 0, wide.stderr + wide.stdout)
            self.assertEqual(wide.stdout.splitlines()[1:], ['overflow: phone 600 > 390'])
            plain = self.run_capture(Path(temp) / 'plain')
            self.assertEqual(plain.returncode, 0, plain.stderr + plain.stdout)
            self.assertEqual(plain.stdout.splitlines()[1:], ['overflow: none'])

    def test_overflow_summary_includes_the_first_screen(self):
        # catches (R1): --fixed-at-bottom reporting `overflow: none` because
        # only the tall capture fits, while the first-screen PNG overflows.
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / 'short-wide'
            result = self.run_capture(out, '--fixed-at-bottom', url=self.url + 'short-wide')
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            manifest = json.loads((out / 'capture.json').read_text())
            self.assertEqual(manifest['captures'][0]['firstScreen']['page']['contentWidth'], 600)
            self.assertEqual(manifest['captures'][0]['page']['contentWidth'], 390)
            self.assertEqual(result.stdout.splitlines()[1:],
                             ['overflow: phone first screen 600 > 390'])

    def test_fragment_url_loads_a_fresh_page_at_each_width(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / 'fragment'
            result = self.run_capture(out, url=self.url + 'fragment#view')
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            manifest = json.loads((out / 'capture.json').read_text())
            self.assertEqual([p['page']['height'] for p in manifest['captures']], [1200, 1500])

    def test_fixed_at_bottom_keeps_full_page_and_first_screen_pixels(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / 'fixed'
            result = self.run_capture(out, '--fixed-at-bottom', url=self.url + 'fixed')
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertEqual(sorted(p.name for p in out.iterdir()), [
                'capture.json', 'desktop-first-screen.png', 'desktop.png',
                'phone-first-screen.png', 'phone.png'])
            manifest = json.loads((out / 'capture.json').read_text())
            self.assertEqual(len(manifest['captures']), 2)
            for capture, name, width, height, first_height, colour in [
                (manifest['captures'][0], 'phone', 390, 1200, 844, [213, 94, 0]),
                (manifest['captures'][1], 'desktop', 1440, 1100, 900, [0, 114, 178]),
            ]:
                self.assertEqual(capture['name'], name)
                self.assertEqual(capture['viewport'], {'width': width, 'height': height})
                self.assertEqual(capture['page'], {
                    'width': width, 'height': height, 'contentWidth': width})
                self.assertEqual(capture['firstScreen']['viewport'], {
                    'width': width, 'height': first_height})
                for record, expected_height in [(capture, height), (capture['firstScreen'], first_height)]:
                    png = out / record['file']
                    self.assertEqual(struct.unpack('>II', png.read_bytes()[16:24]),
                                     (width, expected_height))
                    self.assertEqual(png_column(png),
                                     [colour] * (expected_height - 64) + [[204, 121, 167]] * 64)

    def test_default_fixed_footer_stays_at_original_viewport_edge(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / 'default-fixed'
            result = self.run_capture(out, url=self.url + 'fixed')
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            for name, height, first_height, colour in [
                ('phone', 1200, 844, [213, 94, 0]),
                ('desktop', 1100, 900, [0, 114, 178]),
            ]:
                self.assertEqual(png_column(out / f'{name}.png'),
                                 [colour] * (first_height - 64) + [[204, 121, 167]] * 64
                                 + [colour] * (height - first_height))

    def test_optional_image_without_source_does_not_block_a_page(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / 'empty'
            result = self.run_capture(out, url=self.url + 'empty')
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertTrue((out / 'capture.json').is_file())

    def test_broken_image_source_still_fails_without_success_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / 'broken'
            result = self.run_capture(out, url=self.url + 'broken')
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('decoded', result.stderr)
            self.assertFalse((out / 'capture.json').exists())

    def test_missing_ready_state_fails_without_success_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / 'missing'
            result = self.run_capture(out, '--ready-selector', '#absent', '--timeout', '1')
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('ready', result.stderr.lower())
            self.assertFalse((out / 'capture.json').exists())

    def test_http_error_is_not_screenshot_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / 'error'
            result = self.run_capture(out, url=self.url + 'missing')
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('404', result.stderr)
            self.assertFalse((out / 'capture.json').exists())

    def test_invalid_inputs_fail_before_creating_evidence(self):
        for args in [('--timeout', '0'), ('--timeout', 'nan'), ('--timeout', 'inf')]:
            with self.subTest(args=args), tempfile.TemporaryDirectory() as temp:
                out = Path(temp) / 'invalid'
                result = self.run_capture(out, *args)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('positive and finite', result.stderr)
                self.assertFalse(out.exists())
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / 'invalid'
            result = self.run_capture(out, url='file:///synthetic.html')
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('HTTP(S)', result.stderr)
            self.assertFalse(out.exists())


if __name__ == '__main__':
    unittest.main()
