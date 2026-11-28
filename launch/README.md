# Record a fresh todo-demo

Use this kit for the owner’s launch recording in [OpenWiz #3542](https://github.com/openwizdev/OpenWiz/issues/3542). Use the verified OpenWiz 0.2.0 candidate from [#3538](https://github.com/openwizdev/OpenWiz/issues/3538) and a fresh demo repository.

## Before recording

1. From this kit’s checkout, confirm the signed-in GitHub account and choose a new repository name under a namespace you control. The script prints the name and creates an empty private repository only after you type `yes`.

   ```sh
   gh auth status --hostname github.com
   sh launch/reset.sh example/fresh-todo
   ```

2. Install the candidate using its verified install instructions. Open the new repository as its own project in T3 Code and run OpenWiz setup for that project. Give the fleet a default branch with only the initial project setup if setup has not already created one. Keep the demo app empty.
3. Check the factory settings on screen. Only `local` is on. No opt-in is on. Hide account details, tokens, private navigation, and private approval records from the capture.

## Run sheet

Start recording before the first prompt. Record its actual UTC time as you send it. For example, get the timestamp with `date -u +%Y-%m-%dT%H:%M:%SZ` just before pressing Send, then keep it with the recording.

| Step | What to show | What may be cut |
| --- | --- | --- |
| First prompt and grill | Show the fresh project and its settings. Ask Wiz to build a simple to-do page that lets you add an item, mark it done, and keep the list after a reload. Answer the grill in plain words. | Time spent waiting for a reply. |
| Spec and plan | Show the spec, the few tickets, and their order. Approve the spec and plan as the owner. | Time spent waiting for the plan or checks to finish. |
| Fleet | Start the fleet. Show the builders, the independent reviews, and the checks on the actual pull requests. Let the fleet finish the merges through its normal procedure. | Idle time between starts, checks, reviews, and merges. |
| Finished app | Show the last merge. Open the app from the merged default branch, add a task, mark it done, and reload to show it stayed done. | Time spent waiting for the app to open. |

Cut only waiting. Keep the actions and their order. Say or show **“Waiting was cut from this video.”** Use the measured elapsed time for the caption.

## Caption data

After the last merge, run the checker from the kit’s checkout. Substitute the fresh repository, the spec issue number, and the UTC time saved at the first prompt.

```sh
python3 -I launch/check.py --repo example/fresh-todo --spec 10 --first-prompt 2030-01-02T10:00:00Z
```

The checker uses the current GitHub login to read the spec, its sub-issues, and their closing pull requests. It prints JSON with their links, the first prompt, the last verified merge into the demo’s default branch, and the elapsed seconds. It refuses an incomplete read or a ticket still waiting for a merged pull request.

Keep the caption data and recording with the owner’s launch evidence. Review what is visible before using either in the launch video.

## Test the kit

```sh
python3 -I launch/test_launch.py -v
```

The tests use a fake `gh` and synthetic data.
