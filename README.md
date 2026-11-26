# cryo

**Your agent died at 3am. It didn't notice.**

Put Claude Code on a Fly.io Sprite, give it a night's work, and walk away.
Sprites keep their disk forever but not their processes: a cold wake, a host
move or a checkpoint restore kills everything that was running, and the agent
forgets the whole session. Fly's own docs say to assume processes are lost.

cryo keeps the agent alive anyway. It freezes the running process to disk with
[CRIU](https://criu.org) whenever the agent has done some work, and thaws it
when the Sprite comes back: same memory, same terminal, same conversation, mid
sentence. It emails you through the Sprites Resend connector when that
happens, and the agent mails you its report the same way when it's done.

It can also **move a live agent to another Sprite**: Claude Code, frozen on one
machine, woke up on another and answered *"The codeword is TELEPORT-9. hostname
returned cryo-lab"*.

**Try it:** https://cryo-labs.vercel.app. Leave a word in a process's memory,
press *Kill our Sprite*, and watch every agent (and your word) come back.

Built for Fly.io Hacksgiving 2026. Along the way we hit [seven walls on
Sprites](#what-we-found-out-about-sprites) the docs don't mention.

## What it looks like

```
$ sudo cryo run cc --tmux -- claude
cryo: cc running as pid 315296
$ cryo say cc 'Remember this codeword: PINEAPPLE-42'
● OK
                    ...the Sprite is restored from a checkpoint;
                       every process on it dies...
cryo: cc: thawed in 0.17s as pid 315296            (the cryo service, on boot)
$ cryo say cc 'What was the codeword I gave you?'
● PINEAPPLE-42
```

And an email lands in your inbox: *"cryo: cc survived a restart"*, sent
through the Sprites Resend connector.

## Install

On a Sprite:

```
sudo apt-get install -y criu tmux
git clone https://github.com/miracle352/cryo && cd cryo
sudo ln -sf "$PWD/cryo" /usr/local/bin/cryo

# start something under cryo
sudo env PATH="$PATH" HOME=$HOME IS_SANDBOX=1 cryo run cc --tmux -- claude

# freeze on activity, thaw on every boot, serve the dashboard api
sudo env PATH="$PATH" HOME=$HOME cryo install --api --sprite <your-sprite-name>

# optional: email alerts through the Resend connector
sudo cryo alerts --email you@example.com --test
```

## Commands

| command | does |
|---|---|
| `cryo run NAME [--tmux] -- CMD` | start a process under cryo |
| `cryo freeze NAME [--stop]` | snapshot it to disk now (`--stop` also stops it) |
| `cryo thaw NAME` | bring it back |
| `cryo boot` | thaw everything that died in a restart |
| `cryo watch` | freeze on activity, thaw anything that died |
| `cryo install [--api]` | run `watch` (and the api) as Sprite services |
| `cryo say NAME TEXT` / `cryo peek NAME` | talk to / look at a tmux agent |
| `cryo report --subject S --file F` | email a report through the Resend connector |
| `cryo alerts --email E` | where restart alerts go |
| `cryo teleport NAME [--to SPRITE]` | move a running agent to another Sprite |
| `cryo import LINK` | receive it on the other Sprite |
| `cryo ls`, `cryo events` | status and history |

## The overnight agent

`demo/overnight.sh` starts Claude Code under cryo with a long task (by default:
audit cryo itself) and tells it to email its finished report through the
Resend connector. Restart the Sprite as often as you like while it works.

## Teleport

Move a running agent to another Sprite without stopping its work.

```sh
# on the Sprite it lives on (its URL must be public, cryo-api running)
sudo cryo teleport cc --url https://cryo-lab-xxxx.sprites.app

# on the other Sprite (same setup: criu, tmux, cryo cloned)
sudo cryo import https://cryo-lab-xxxx.sprites.app/api/bundle/<one-time link>
```

The source does a last freeze, packs the images with every non-system file the
agent had open or mapped, and hands out a link that lasts 2 hours or until the agent lands.
The other Sprite pulls it, checks that the PIDs are free and that every program
file it didn't carry is the same there, thaws it, and tells the source it landed.
Nothing is deleted on the source until then: `cryo thaw cc` there calls it back.

Both Sprites need the same versions of the programs the agent runs (claude,
node, python). If they differ, `import` says which file and changes nothing;
teleport again with `--carry-max 512` to bring the bigger files along.

Move agents toward the Sprite that has been up longer (finding 7 below):
`import` compares the two clocks and refuses to land an agent whose timers
would stall. Both Sprites also need Claude logged in, since Claude checks its
login against the machine it's on.

Tested: Claude Code moved from cryo-lab-2 to cryo-lab (49.8 MB bundle, 0.34 s
thaw) and answered "The codeword is TELEPORT-9. hostname returned cryo-lab".

## Try it without installing anything

On [the site](https://cryo-labs.vercel.app), type a word into **Leave a word
in its memory**, then press **Kill our Sprite**. Your word is held by
[`demo/keeper.py`](demo/keeper.py), a small program that keeps words in memory
and never writes them to a file. Every process on the Sprite dies; when the page
says everything came back, it reads your word back from the same process.

To run keeper on your own Sprite:

```sh
sudo cryo run keeper -- python3 ~/cryo/demo/keeper.py
```

## How it works

1. **Run.** cryo starts the agent as root inside a small seccomp filter that
   makes `io_uring_setup`, `inotify_init*` and `fanotify_init` fail with
   ENOSYS. Runtimes fall back (libuv/bun to epoll, file watchers turn off).
   Those are the kernel objects CRIU can't checkpoint on a Sprite (see below).
2. **Freeze.** `cryo watch` samples each agent's CPU time every two seconds.
   After a burst of real work followed by 5 quiet seconds it runs
   `criu dump --leave-running` into a fresh image directory and swaps it in
   atomically. Idle agents aren't re-dumped.
3. **Thaw.** On boot the service compares the stored environment id with the
   current one, and anything dead is restored with `criu restore`. Only a
   restart brings an agent back: one that exits or is killed while the Sprite
   is up is marked `exited` and left alone (`cryo thaw` brings it back by hand),
   and a thaw that keeps failing backs off and gives up with an email. Open TCP
   connections come back closed; clients reconnect.

The images live on the Sprite's disk, so a Sprite checkpoint carries them too.

## What we found out about Sprites

Tested on kernel `6.12.87-fly`, CRIU 4.2 from Ubuntu.

1. **No CAP_SYS_PTRACE.** Root can't ptrace processes owned by the `sprite`
   user, so CRIU can't freeze them. cryo runs agents as root.
2. **No CAP_SYS_TIME.** Restoring a time namespace fails ("Unable to set a
   monotonic clock offset"). cryo removes `timens-*.img` before restoring.
3. **No CAP_DAC_READ_SEARCH.** CRIU can't reopen inotify watches by file
   handle (`open_by_handle_at`).
4. **Overlay root mixes device numbers.** Directories report the overlay's
   `st_dev`, regular files report the lower layer's. Inotify records the
   overlay's, so watched files can't be found by CRIU's irmap scan either.
   Together with (3), any process watching a file can't be dumped. The seccomp
   filter avoids it.
5. **`boot_id` survives a checkpoint restore.** A restore restarts the
   container, not the kernel. cryo pairs `boot_id` with PID 1's start time.
6. **Timers count awake time.** A paused Sprite freezes every process, so a
   60 s timer can take much longer on the wall clock. cryo snapshots on
   activity instead.
7. **Clocks don't travel.** `CLOCK_MONOTONIC` counts from each Sprite's boot,
   and with (2) a moved process can't keep its old clock. We moved Claude Code
   to a Sprite that had booted 10 hours later: it restored fine and then sat
   frozen, every timer (including the one that redraws the screen) waiting for
   that Sprite's clock to catch up. Moved the other way, it answered at once.
   `cryo import` checks the two clocks first.

Also: there's no `iptables` on a Sprite, so cryo passes
`--network-lock skip` (sockets are restored closed anyway).

## Tested

| workload | state kept | freeze | thaw |
|---|---|---|---|
| Claude Code in tmux | the conversation | paused 0.26 s (4 s to write 184 MB) | 0.17 s |
| Node HTTP server | in-memory counter | 0.05 s | 0.04 s |
| Python | 2,000,000 floats | | |
| tmux + Python REPL | live variables | | |
| full Sprite checkpoint restore | all of the above, hands off | auto | auto |
| teleport to another Sprite | Claude's conversation | 0.32 s | 0.34 s |

## Limits

- Network connections are closed on thaw.
- Teleport only lands on a Sprite whose clock is ahead, with the same program
  versions (or `--carry-max`) and Claude logged in.
- Agents can't use inotify or io_uring while under cryo.
- Everything runs as root.
- A snapshot is as big as the process's memory (~190 MB for Claude Code).
- Work done after the last snapshot is lost if the Sprite goes cold before the
  next one (usually a few seconds).
