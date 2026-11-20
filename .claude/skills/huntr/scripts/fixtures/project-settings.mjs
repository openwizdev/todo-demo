// The consuming project's huntr settings for the tests: `docs/agents/huntr.md`
// in the nearest folder at or above the working directory that has one, so a
// test run from the project's root or any folder in it reads the project's own
// file. With none, the path below the working directory, which does not exist.
import { existsSync } from 'node:fs';
import { dirname, join } from 'node:path';

export function projectSettings(start = process.cwd()) {
  for (let folder = start; ; folder = dirname(folder)) {
    const file = join(folder, 'docs/agents/huntr.md');
    if (existsSync(file)) return file;
    if (dirname(folder) === folder) return join(start, 'docs/agents/huntr.md');
  }
}
