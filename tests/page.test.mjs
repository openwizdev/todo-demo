import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

test('the app page exists and has a title', async () => {
  const html = await readFile(new URL('../app/index.html', import.meta.url), 'utf8');
  assert.match(html, /<title>[^<]+<\/title>/);
});
