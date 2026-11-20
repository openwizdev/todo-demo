"""to-spec's steering video (#1339, J204): an animatic built from a storyboard,
showing what changes for a user and in the codebase, in build order, with no
bench and no ticket graph. Synthetic only; no network.

The render proof needs ffmpeg, ffprobe, a Chromium and playwright-core (from
the working directory's node_modules or $ANIMATIC_HOME); without them it is
skipped, and the pull request names that gap.
"""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / 'scripts/animatic.mjs'
STORYBOARD = HERE / 'synthetic/storyboard.json'


def run(*args, cwd=None):
    return subprocess.run(['node', str(SCRIPT), *map(str, args)], capture_output=True, text=True, cwd=cwd)


def can_render():
    if not (shutil.which('ffmpeg') and shutil.which('ffprobe')):
        return False
    if not (os.environ.get('OPENWIZ_CHROMIUM') or shutil.which('chromium')):
        return False
    homes = [Path.cwd(), Path(os.environ.get('ANIMATIC_HOME', Path.home() / '.cache/animatic'))]
    return any((home / 'node_modules/playwright-core/package.json').is_file() for home in homes)


def other_filesystem(than):
    """A writable folder on a different filesystem from `than`, or None."""
    for root in ['/dev/shm', os.environ.get('XDG_RUNTIME_DIR')]:
        if root and os.path.isdir(root) and os.access(root, os.W_OK) and os.stat(root).st_dev != os.stat(than).st_dev:
            return Path(root)
    return None


# A synthetic voice: a 0.5 s tone per line, except the line in $VOICE_LINE,
# which gets what $VOICE_MODE says: `silent-exit-3` writes a 0.5 s silent WAV
# and exits 3, `silent` writes it and exits 0, `nothing` writes no file.
VOICE = '''
import math, os, sys, wave
text = sys.stdin.read()
mode = os.environ['VOICE_MODE'] if text == os.environ['VOICE_LINE'] else 'tone'
if mode == 'nothing':
    sys.exit(0)
w = wave.open(sys.argv[1] + '.wav', 'wb')
w.setparams((1, 2, 16000, 0, 'NONE', ''))
amp = 0 if mode.startswith('silent') else 8000
w.writeframes(b''.join(int(amp * math.sin(i / 8)).to_bytes(2, 'little', signed=True) for i in range(8000)))
w.close()
sys.exit(3 if mode == 'silent-exit-3' else 0)
'''


class SpecVideo(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.moments = json.loads(STORYBOARD.read_text())

    def write(self, moments):
        path = self.tmp / 'storyboard.json'
        path.write_text(json.dumps(moments))
        return path

    def test_link_is_ready_to_insert_in_spec(self):
        # catches: a link line the spec issue can't use as written.
        result = run('link', 'https://example.com/videos/synthetic.mp4?lang=en')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout,
                         '[Watch the narrated spec](https://example.com/videos/synthetic.mp4?lang=en)\n')

    def test_link_refuses_unsafe_or_ambiguous_destinations(self):
        # catches: a local file, a credential or injected Markdown reaching a public issue.
        for url in ['file:///tmp/video.mp4', 'https://user:secret@example.com/video.mp4',
                    'https://example.com/clip)\n[extra](https://example.org',
                    'https://example.com:bad/video.mp4', 'https:///video.mp4']:
            with self.subTest(url=url):
                result = run('link', url)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, '')

    def test_the_synthetic_grill_storyboard_passes_in_build_order(self):
        # catches: a checker that refuses the storyboard to-spec is told to write.
        result = run('check', STORYBOARD)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines()[0],
                         'storyboard ok: 5 moments; steps 1-3; user 2, codebase 2')

    def test_a_graph_a_bench_or_build_order_broken_is_refused_before_rendering(self):
        # catches: a video that shows the ticket graph or a bench, or tells the
        # changes out of build order, reaching the owner.
        def change(fn):
            moments = copy.deepcopy(self.moments)
            fn(moments)
            return moments

        cases = {
            'a graph frame': lambda m: m[1]['frame'].update(type='diagram'),
            'an own image': lambda m: m[2].update(image='graph.png'),
            'an own page': lambda m: m[2].update(html='graph.html'),
            'graph in a line': lambda m: m[3].update(say='Here is the ticket graph.'),
            'bench in a point': lambda m: m[2]['frame']['points'].append('Benchmarks go up'),
            'out of build order': lambda m: m[4]['frame'].update(step=1),
            'not starting at step 1': lambda m: [x['frame'].update(step=x['frame']['step'] + 1) for x in m[1:]],
            'a skipped step': lambda m: m[4]['frame'].update(step=4),
            'no codebase change': lambda m: [x['frame'].update(type='user', points=['A change'])
                                             for x in m if x['frame']['type'] == 'codebase'],
            'no user change': lambda m: [x['frame'].update(type='codebase', paths=['a/b.py'])
                                         for x in m if x['frame']['type'] == 'user'],
            'title not first': lambda m: m.insert(2, m.pop(0)),
            'an extra key': lambda m: m[1]['frame'].update(ticket='#9101'),
            'no line': lambda m: m[1].pop('say'),
            'over the target': lambda m: m[1].update(say=' '.join(['word'] * 400)),
        }
        for name, fn in cases.items():
            with self.subTest(name):
                path = self.write(change(fn))
                result = run('check', path)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertEqual(result.stdout, '')
                self.assertTrue(result.stderr.startswith('animatic: '), result.stderr)
                built = run('build', path, '-o', self.tmp / 'spec.mp4')
                self.assertEqual(built.returncode, 1)
                self.assertFalse((self.tmp / 'build').exists(), 'build rendered a refused storyboard')
                self.assertFalse((self.tmp / 'spec.mp4').exists())

    @unittest.skipUnless(can_render(), 'rendering needs ffmpeg, ffprobe, Chromium and playwright-core')
    def test_build_renders_each_frame_with_its_voice_in_order(self):
        # catches: frames shown out of order or under the wrong line, a silent
        # or missing track, or an MP4 that isn't what the storyboard says.
        shutil.copy(STORYBOARD, self.tmp / 'storyboard.json')
        # A voice of known length per line: 0.6 s plus 0.1 s per word.
        tone = ('python3 -I -c "import sys, wave, math; n = len(sys.stdin.read().split()); '
                'w = wave.open(sys.argv[1] + \'.wav\', \'wb\'); w.setparams((1, 2, 16000, 0, \'NONE\', \'\')); '
                'w.writeframes(b\'\'.join(int(8000 * math.sin(i / 8)).to_bytes(2, \'little\', signed=True) '
                'for i in range(int(16000 * (0.6 + 0.1 * n)))))" {out}')
        out = self.tmp / 'spec.mp4'
        result = run('build', self.tmp / 'storyboard.json', '-o', out, '--tts-command', tone, cwd=Path.cwd())
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('no warnings', result.stdout)
        words = [len(m['say'].split()) for m in self.moments]
        lengths = [0.6 + 0.1 * n + 0.4 for n in words]  # each line, then its 0.4 s hold
        meta = json.loads(subprocess.check_output([
            'ffprobe', '-v', 'error', '-show_entries', 'format=duration:stream=codec_type,codec_name,r_frame_rate',
            '-of', 'json', str(out)]))
        self.assertEqual(sorted(s['codec_type'] for s in meta['streams']), ['audio', 'video'])
        self.assertAlmostEqual(float(meta['format']['duration']), sum(lengths), delta=0.25)
        frames = sorted((self.tmp / 'build').glob('frame-*.png'))
        self.assertEqual(len(frames), len(self.moments))
        self.assertTrue((self.tmp / 'build/sheet.png').is_file())

        def tiny(args):
            return subprocess.check_output(['ffmpeg', '-v', 'error', *args, '-frames:v', '1',
                                            '-vf', 'scale=48:27', '-pix_fmt', 'gray', '-f', 'rawvideo', '-'])

        pictures = [tiny(['-i', str(f)]) for f in frames]
        start = 0.0
        for i, length in enumerate(lengths):
            shot = tiny(['-ss', f'{start + length / 2:.2f}', '-i', str(out)])
            nearest = min(range(len(pictures)),
                          key=lambda k: sum(abs(a - b) for a, b in zip(shot, pictures[k])))
            self.assertEqual(nearest, i, f'moment {i + 1} shows frame {nearest + 1}')
            start += length

    @unittest.skipUnless(can_render(), 'rendering needs ffmpeg, ffprobe, Chromium and playwright-core')
    def test_a_failed_or_silent_voice_for_one_moment_fails_the_build_and_names_it(self):
        # catches (#1545): a voice command's failure, a silent take for one
        # moment hidden by the other moments' sound, or a stale take left from
        # an earlier run, reaching the owner as a complete video.
        helper = self.tmp / 'voice.py'
        helper.write_text(VOICE)
        cases = {
            'fails, leaving a silent take': ('silent-exit-3', False),
            'exits 0 with a silent take': ('silent', False),
            'writes nothing beside a stale take': ('nothing', True),
        }
        for name, (mode, stale) in cases.items():
            with self.subTest(name):
                work = Path(tempfile.mkdtemp(dir=self.tmp))
                shutil.copy(STORYBOARD, work / 'storyboard.json')
                if stale:
                    (work / 'build').mkdir()
                    env = dict(os.environ, VOICE_MODE='tone', VOICE_LINE='')
                    subprocess.run(['python3', '-I', str(helper), str(work / 'build/line-03.src')],
                                   input='stale', text=True, env=env, check=True)
                out_dir = work / 'deliverable'
                out_dir.mkdir()
                env = dict(os.environ, VOICE_MODE=mode, VOICE_LINE=self.moments[2]['say'])
                result = subprocess.run(
                    ['node', str(SCRIPT), 'build', str(work / 'storyboard.json'), '-o', str(out_dir / 'spec.mp4'),
                     '--tts-command', f'python3 -I {helper} {{out}}'],
                    capture_output=True, text=True, env=env, cwd=Path.cwd())
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertEqual(result.stdout, '')
                lines = result.stderr.splitlines()
                self.assertEqual(len(lines), 1, result.stderr)
                self.assertTrue(lines[0].startswith('animatic: moment 3: '), result.stderr)
                self.assertEqual(list(out_dir.iterdir()), [], 'a refused build left a file at the output')

    @unittest.skipUnless(can_render(), 'rendering needs ffmpeg, ffprobe, Chromium and playwright-core')
    def test_build_exports_to_an_output_on_another_filesystem(self):
        # catches (#1601): an MP4 requested on a mounted volume failing at the
        # last step with a cross-device link, or leaving a partial file.
        far = other_filesystem(self.tmp)
        if far is None:
            self.skipTest('no second writable filesystem (such as /dev/shm) here')
        out_dir = Path(tempfile.mkdtemp(dir=far))
        self.addCleanup(shutil.rmtree, out_dir)
        shutil.copy(STORYBOARD, self.tmp / 'storyboard.json')
        helper = self.tmp / 'voice.py'
        helper.write_text(VOICE)
        env = dict(os.environ, VOICE_MODE='tone', VOICE_LINE='')
        result = subprocess.run(
            ['node', str(SCRIPT), 'build', str(self.tmp / 'storyboard.json'), '-o', str(out_dir / 'spec.mp4'),
             '--tts-command', f'python3 -I {helper} {{out}}'],
            capture_output=True, text=True, env=env, cwd=Path.cwd())
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual([p.name for p in out_dir.iterdir()], ['spec.mp4'])
        self.assertEqual([p.name for p in (self.tmp / 'build').iterdir() if 'partial' in p.name], [])
        meta = json.loads(subprocess.check_output([
            'ffprobe', '-v', 'error', '-show_entries', 'stream=codec_type', '-of', 'json', str(out_dir / 'spec.mp4')]))
        self.assertEqual(sorted(s['codec_type'] for s in meta['streams']), ['audio', 'video'])

    @unittest.skipUnless(can_render(), 'rendering needs ffmpeg, ffprobe, Chromium and playwright-core')
    def test_build_never_touches_an_existing_file_beside_the_output(self):
        # catches (#1691 R1): a file already at the renderer's staging name
        # beside the output (left by an interrupted run, PID reused) deleted
        # by the export's cleanup. `exec` keeps the shell's PID, so $$ is the
        # renderer's PID and the old staging name is known before it starts.
        shutil.copy(STORYBOARD, self.tmp / 'storyboard.json')
        helper = self.tmp / 'voice.py'
        helper.write_text(VOICE)
        out_dir = self.tmp / 'deliverable'
        out_dir.mkdir()
        env = dict(os.environ, VOICE_MODE='tone', VOICE_LINE='')
        launch = ('printf "keep me" > "$1/.spec.$$.partial.mp4"; '
                  'exec node "$2" build "$3" -o "$1/spec.mp4" --tts-command "python3 -I $4 {out}"')
        result = subprocess.run(['sh', '-c', launch, 'sh', str(out_dir), str(SCRIPT),
                                 str(self.tmp / 'storyboard.json'), str(helper)],
                                capture_output=True, text=True, env=env, cwd=Path.cwd())
        planted = [p for p in out_dir.iterdir() if p.name.endswith('.partial.mp4')]
        self.assertEqual(len(planted), 1, f'the existing file is gone: {result.stderr}')
        self.assertEqual(planted[0].read_bytes(), b'keep me')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(sorted(p.name for p in out_dir.iterdir()), sorted([planted[0].name, 'spec.mp4']))


# Video comment steering is off in every mode until OpenWiz #1402's identity
# separation is verified (WizSkills #60); the owner steers through the
# orchestrator. Turn this on, and the video post's wording with it, together.
COMMENT_STEERING_ON = False


class SteeringWording(unittest.TestCase):
    """#1736: the line posted with the video matches whether comment steering is on."""

    def test_the_video_post_invites_comment_steering_only_while_it_is_on(self):
        text = (HERE.parent / 'SKILL.md').read_text()
        post = text.split('Post it as a spec comment', 1)[1].split('\n## ', 1)[0]
        steer = text.split('## 5. Steer', 1)[1].split('\n\nPlanning grants', 1)[0]
        head = text.split('\n## 1.', 1)[0]  # the description line and the intro
        invites = ('comment here to steer' in post.lower() or "owner's comments on the video steer" in steer
                   or 'steers a spec through its video' in head or 'watches to steer' in head)
        if COMMENT_STEERING_ON:
            self.assertTrue(invites, 'comment steering is on but the video post does not invite it')
        else:
            self.assertFalse(invites, 'the video post invites comment steering while it is off')
            self.assertIn('orchestrator', post.lower(), 'the video post must send the owner to their orchestrator')


if __name__ == '__main__':
    unittest.main(verbosity=2)
