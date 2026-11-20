import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

const script = fileURLToPath(new URL('../scripts/hitl-loop.template.sh', import.meta.url));
const prompts = ['Open the synthetic panel.', 'Did the synthetic count duplicate?'];

function run(input, args = prompts) {
  const result = spawnSync('bash', [script, ...args], {
    input,
    encoding: 'utf8',
    timeout: 5000,
  });
  assert.ifError(result.error);
  assert.equal(result.signal, null);
  return result;
}

test('the exact symptom reports red, explicit absence reports green', () => {
  for (const [answer, status, record] of [
    ['y', 1, 'SYMPTOM_PRESENT=yes'],
    ['n', 0, 'SYMPTOM_PRESENT=no'],
  ]) {
    const result = run(`\n${answer}\n`);
    assert.equal(result.status, status, result.stderr);
    assert.deepEqual(result.stdout.split('\n').filter((line) => line.startsWith('SYMPTOM_PRESENT=')), [record]);
    assert.equal(result.stderr, '');
  }
});

test('missing input and unknown observations are inconclusive, never green', () => {
  for (const input of ['', '\n', '\ny', '\n\n', '\nyes\n', '\nN\n', '\nunknown\n']) {
    const result = run(input);
    assert.equal(result.status, 2, result.stderr);
    assert.equal(result.stdout.includes('SYMPTOM_PRESENT='), false);
    assert.match(result.stderr, /inconclusive/);
  }
});

test('a non-observation is neither echoed nor treated as a command', () => {
  const result = run('\n$(printf SYNTHETIC_INVALID)\n');
  assert.equal(result.status, 2);
  assert.equal((result.stdout + result.stderr).includes('SYNTHETIC_INVALID'), false);
});

test('scenario instructions are literal arguments and one answer ends the run', () => {
  const step = '-n ~ "quotes" $(printf SYNTHETIC_EXPANSION)';
  const result = run('\nn\ny\n', [step, prompts[1]]);
  assert.equal(result.status, 0, result.stderr);
  assert.equal(result.stdout.includes(step), true);
  assert.deepEqual(result.stdout.split('\n').filter((line) => line.startsWith('SYMPTOM_PRESENT=')), ['SYMPTOM_PRESENT=no']);
});

test('both nonempty scenario prompts are required', () => {
  for (const args of [[], ['one'], ['', 'question'], ['step', ''], [...prompts, 'extra']]) {
    const result = run('', args);
    assert.equal(result.status, 2, result.stderr);
    assert.match(result.stderr, /usage:/);
    assert.equal(result.stdout.includes('SYMPTOM_PRESENT='), false);
  }
});
