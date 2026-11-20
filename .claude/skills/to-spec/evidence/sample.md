# Sample steering video (#1339)

Rendered from the synthetic grill's storyboard (`test/synthetic/storyboard.json`,
from `test/synthetic/grill.md`) with the default voice:

```
node skills/to-spec/scripts/animatic.mjs build storyboard.json -o spec-sample.mp4
storyboard ok: 5 moments; steps 1-3; user 2, codebase 2
  01    0.0 s  title            Widget export. Here's what changes, in the order we'll build
  02    4.3 s  codebase step 1  First, one versioned export contract, that everything else w
  03    8.9 s  user     step 2  Then you get an export button, that saves every widget to on
  04   13.2 s  codebase step 2  At the same time, the same export from the command line, for
  05   18.1 s  user     step 3  Last, an export page, that lists your past exports.
spec-sample.mp4: 22.1 s, 5 moments, voice espeak-ng; sheet build/sheet.png
no warnings
```

ffprobe: one H.264 video stream, 1280x720 at 30/1 fps, and one AAC audio
stream; 22.111 s; 340,885 bytes. volumedetect: mean -24.9 dB, max -4.2 dB.

- [sample-spec.mp4](sample-spec.mp4): the video.
- [sample-sheet.png](sample-sheet.png): its five frames in order: the title,
  then code and user changes at steps 1, 2, 2 and 3. No graph and no bench.
