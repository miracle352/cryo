<!-- This report was written by the overnight demo agent: Claude Code running
under cryo on cryo-lab, asked to audit cryo itself (demo/overnight.sh). The
Sprite was restarted from the site while it worked; it came back and emailed
this through the Resend connector 19 seconds later. Kept as it arrived. -->

# What we did with it

| # | Issue | Status |
|---|---|---|
| 1 | Image swap can leave no snapshot | fixed: a half-done swap is recovered before every freeze and thaw |
| 2 | No locking between freezers | fixed: one lock per agent, meta re-read inside it, status written before the dump |
| 3 | `high_pids()` did nothing with pid_max 32768 | fixed: agents start in the top quarter of the PID range |
| 4 | Every dead agent thawed, forever | fixed: only a restart brings agents back; others are marked `exited`; failed thaws back off and give up with an email |
| 5 | `freeze --stop` undone | fixed: `frozen` is parked; `stop` saves its status before killing |
| 6 | Local thaws ignore the clock | the thaw now says when the clock went back and by how much |
| 7 | `alive(pid)` fooled by a reused PID | fixed: an agent counts as alive only if its PID is from this boot |
| 8 | Freezing from inside an agent fails | clear error instead of criu's |
| 9 | One exception kills `watch` | fixed: per-agent errors are logged and skipped; config writes are atomic |
| 10 | criu has no timeout | fixed: 10 minutes |
| 11 | CPU of exited children not counted | fixed: cutime/cstime included |
| 12 | Teleported agent thawed without its cgroup fix | fixed: `thaw()` adds it whenever the agent came from another Sprite |
| 13 | A failed import can land silently later | fixed: it stays parked until `cryo thaw`, which tells the source |
| 14 | Import overwrites local state | open |
| low | old snapshot after `cryo run`, bundles left on recall, events log unbounded | fixed |

---

# cryo audit: freeze / thaw

Scope: `/home/sprite/cryo/cryo` (1486 lines, commit 0d26658) and `README.md`.

## Summary

cryo's main path works on this Sprite. `events.jsonl` has 517 successful freezes and 30 thaws across 21 detected restarts, including one real kernel reboot. The risky parts are in the code around that path:

- **No locking.** Four separate code paths can freeze the same agent at once. They share one `images.new` directory and write back stale `meta.json` copies. As a result, a stop or teleport can be undone, or the agent can end up running in two places.
- **The image swap isn't crash-safe.** A restart at the wrong moment leaves no `images/` directory, and the next freeze deletes the copy that was still good.
- **PID handling is weaker than the README says.** On this Sprite `pid_max` is 32768, so `high_pids()` does nothing. The live agents run at PIDs 266 and 621, the same range that boot-time processes get after a restart.
- **cryo brings back everything that dies, every 2 s, forever.** That includes deliberate kills, clean exits and crash loops. I confirmed this: I killed a test agent with `kill -9` and `cryo watch` thawed it about 6 s later.
- **`freeze --stop` doesn't stop anything while `watch` runs.** The status `frozen` isn't in `PARKED`.
- **Local thaws never check the clock.** The README's own finding 7 (timers stall when the clock is behind) also applies after a kernel reboot on the same Sprite, and one has already happened here.
- **cryo can't freeze from inside an agent it manages.** criu fails there with `suspending seccomp failed: Operation not permitted`. I reproduced this.

Each issue below has its line numbers, why it matters and a suggested fix. They are ordered roughly by severity. "Verified" means I reproduced it or saw it in live state on this Sprite. Everything else comes from reading the code.

---

## High

### 1. The image swap can leave an agent with no snapshot (lines 399–405)

```python
shutil.rmtree(old, ignore_errors=True)
if os.path.exists(cur):
    os.rename(cur, old)      # <- a restart here leaves no images/
os.rename(new, cur)
```

**Why it matters:**
- Freezes happen constantly (517 so far), and the CLAUDE.md says the machine can restart at any moment.
- If a restart lands between the two renames, `thaw()` (line 440) sees no `images/` directory and reports "nothing frozen to thaw".
- The next `freeze()` then runs `rmtree(images.new)` (line 375) and `rmtree(images.old)` (line 401), which deletes the only good copy.
- Nothing is fsynced either. After a hard stop, `images/` can hold image files that were never fully written to disk.

**Fix:**
- Write each dump to `images.<timestamp>/`, fsync its files and the directory, then atomically repoint a symlink (`os.symlink` to a temp name, then `os.replace` onto `images`). Delete older directories only after that.
- Alternatively, have `thaw()` fall back to `images.old`, then to `images.new` if it has a complete `inventory.img` and `stats-dump`.

### 2. No locking between freezers and meta writers (lines 369–410, 547–609, 612, 708, 1083–1090, 1210, 1336)

Four code paths can call `freeze()` on the same agent at the same time:
- `cryo watch`
- the API's restart button (`restart_sprite`) and `/api/freeze`
- the CLI (`cryo freeze`, `cryo teleport`)
- `cryo doctor`

They all use the same `images.new` path, and each one first `rmtree`s it, possibly under another criu that is still writing there. `freeze()` also saves the `meta` dict the caller loaded earlier. `watch` loaded it up to one full dump earlier (about 4 s for Claude Code), so whatever status was written in between gets overwritten.

**What can go wrong:**
- **`cryo stop` is undone.** You run `cryo stop cc` while `watch` is dumping cc. The agent dies once criu releases it. Then `watch`'s `freeze()` saves `status: running` over `stopped`. On its next pass, `watch` sees a dead agent marked running and thaws it.
- **A teleported agent also keeps running on the source.** `cmd_teleport` calls `freeze(leave_running=False, status="leaving")`. On disk the status stays `running` until line 410. Between criu killing the tree and that save, there is a `crit` call (timeout 10 s) and a `dir_size` walk, about a second in practice. `watch` polls every 2 s, so it has a real chance of seeing a dead agent marked running, and it thaws it on the source. Then teleport writes `away`, which hides the source copy from cryo while it keeps running. The destination lands its own copy, so two agents do the same work and send the same emails.

**Fix:**
- Take `fcntl.flock` on `agents/<name>/lock` around every freeze, thaw and meta read-modify-write.
- Inside the lock, re-`load()` the meta and re-check its status before acting, so stale dicts are never saved.
- Write the target status, for example `leaving`, **before** the dump starts.
- Use a unique temp directory for each dump.

### 3. `high_pids()` does nothing on this Sprite, so thawed PIDs collide with boot processes (lines 199–211, 442)

`base = min(pid_max - 100000, 300000)`. Here `pid_max` is 32768, so `base` is negative and the function returns without changing anything. **Verified:** `keeper` runs as PID 266 and `overnight` as PID 621. After a restart, boot processes fill exactly that range. The cryo services themselves currently sit at PIDs 561–574.

On top of that, line 442 checks only the root PID. A Claude Code tree has many PIDs (tmux server, claude, shells, tool processes). If any of them is taken, `criu restore` fails.

**Fix:**
- Choose `base` relative to `pid_max`, for example `pid_max * 3 // 4` with a random offset, whenever `pid_max` is small.
- Before thawing, read every PID from the image (`crit show pstree.img`) and check all of them.
- If one is taken, send an alert rather than retrying silently (see 4).

### 4. A dead agent is always thawed, with no backoff (lines 573–578, 513–518)

`watch` thaws any agent it finds dead, whether or not the Sprite restarted. **Verified:** I ran a test agent, `kill -9`'d it, and `watch` brought it back about 6 s later.

**Why it matters:**
- **Clean exits are reverted.** A batch job that finishes is restored to its last snapshot and repeats its final work.
- **Side effects are replayed.** Anything done after the last snapshot (emails, `git push`, API calls) runs again. The overnight agent's `cryo report` email is exposed to this.
- **Crash loops never end.** A crash at or right after the snapshot point repeats forever. Each failure runs a full `criu restore` and appends a `thaw_failed` event every 2 s, with no alert. `events.jsonl` grows without limit, and `/api/events` reads the whole file each time (`readlines()`, line 1063).
- **Failing freezes retry too.** With no image yet, a failing freeze retries every 2 s (line 597) and pauses the agent each time.

**Fix:**
- Auto-thaw only when `boot_id` has changed. Otherwise, record the exit and leave the agent alone, or make that an explicit `--restart-on-exit` policy.
- Add exponential backoff and a maximum number of attempts per agent, then send one "did NOT come back" alert.
- Rotate `events.jsonl`.

### 5. `cryo freeze --stop` is undone within 2 s (line 92, 409, 570–575)

`freeze(..., leave_running=False)` sets `status="frozen"`. `PARKED` doesn't include `frozen`, so `watch` immediately sees a dead agent that isn't parked and thaws it. The README says `--stop` "also stops it".

`cmd_stop` (lines 614–617) has the same problem on a smaller scale: it kills the agent first and saves `stopped` afterwards.

**Fix:**
- Add `"frozen"` to `PARKED`, or have `--stop` set `stopped`.
- In `cmd_stop`, save the status before sending the kill.

### 6. Local thaws ignore the clock after a kernel reboot (lines 508–523, 434)

`cmd_import` refuses to land an agent whose `CLOCK_MONOTONIC` would be behind, because its timers stall (README finding 7). `cmd_boot` and `watch` do no such check, yet a cold wake or host move reboots the kernel and resets `CLOCK_MONOTONIC` to about zero.

**Evidence:** `events.jsonl` shows the kernel `boot_id` changed from `d362…` to `6d48…` at 07:51. The old kernel had been up for at least 14 h, since its first event is at Nov 25 17:56. `cc` and `overnight` were thawed onto the new clock with no warning. I could not confirm from outside whether their timers actually stalled; `cc` is sitting idle at a prompt. The risk follows directly from the README's own finding 7.

**Fix:**
- Store `time.monotonic()` and the wall-clock time in `meta.json` at each freeze.
- On thaw, compute how far behind the clock is, as `cmd_import` already does (line 813).
- If it's behind by more than a few seconds, send an alert ("timers will stall about N h"), and consider holding the agent in a parked state.

### 7. `alive(pid)` doesn't check that the PID is still the agent's (lines 134–148, 513, 573)

After a restart, `cmd_boot` checks `alive(m["pid"])` before anything else. Because of issue 3, an unrelated boot process may now hold that PID. In that case cryo:
- treats the agent as alive and never thaws it
- has `watch` take CPU samples of, and `criu dump --leave-running`, the unrelated process tree, then overwrite the agent's real images with it.

**Fix:**
- Store the root process's start time (field 22 of `/proc/<pid>/stat`) together with `boot_id`.
- Count the agent as alive only when both still match. When `boot_id` has changed, treat the agent as dead no matter what holds the PID.

---

## Medium

### 8. Freezing fails from inside a cryo-managed agent (lines 83–86, 391)

**Verified:** in this shell, which runs inside the `overnight` agent (`Seccomp: 2`), `cryo freeze` on a test agent failed with:

```
Error (compel/src/lib/ptrace.c:27): suspending seccomp failed: Operation not permitted
```

The kernel refuses `PTRACE_O_SUSPEND_SECCOMP` from a tracer that is itself under seccomp. So an agent under cryo cannot use `cryo freeze`, `teleport` or `doctor`, and the API `/api/freeze` works only because `cryo serve` runs outside the filter. The test process survived the failed dump.

**Fix:**
- If `/proc/self/status` shows `Seccomp: 2`, send the request to `cryo serve` (with the token) instead of running criu directly, or at least print a clear error.
- Document this.

### 9. One exception kills the whole `watch` service (lines 99–104, 121–123, 127–131, 567–609, 920–923)

The loop body has no `try`, so a single error stops freezing and thawing for every agent. Ways to trigger it:
- `load()` calls `sys.exit` if `meta.json` disappears between `all_agents()`'s `exists` check and its `open`.
- A truncated or corrupt JSON file raises an exception.
- `event()` raises on ENOSPC.
- `int(pidfile)` raises if the pidfile is partial.
- `save_config()` is not atomic (it opens the file `"w"` and writes in place). A crash mid-write corrupts `config.json`, and then `restart_alert()` → `load_config()` raises during `cmd_boot`, which kills `watch` at startup on every boot.

**Fix:**
- Wrap each agent's iteration in `try/except Exception`, log the error, and continue.
- Make `save_config` use the same tmp-file-plus-`os.replace` pattern as `save`, and fsync it.
- Have `load_config` survive bad JSON.

### 10. criu runs with no timeout (line 181)

If a dump hangs (a task stuck in D state, a slow disk), `watch` blocks forever, so no other agent is frozen or thawed. The agent being dumped can stay frozen the whole time.

**Fix:** pass `subprocess.run(..., timeout=...)` with a timeout that scales with image size, kill criu on expiry (seized tasks resume when the tracer exits), and record a `freeze_failed` event.

### 11. Activity detection misses some real work (lines 279–292, 587–597)

`tree_cpu` adds up `utime+stime` of the processes alive at sample time. It ignores `cutime`/`cstime` (fields 13–14), so CPU spent by short-lived children that have already exited isn't counted. Examples are a shell script that runs many quick commands, or tool subprocesses.

Work that stays under 5% CPU in each 2 s check (`--burst 10`) is never counted either, and streaming model output can fall in that range.

Either way, snapshots then come only from `drift`, every 900 s. That contradicts the README's "usually a few seconds".

**Fix:**
- Include `cutime+cstime` of each sampled process.
- Also treat any change in the set of PIDs, or in `/proc/<pid>/io` write bytes, as activity.

### 12. A teleported agent restarted before its first local freeze can't thaw (lines 491 vs 518, 574)

`cmd_thaw` passes `MOVED_ARGS` (`--manage-cgroups=ignore`) to criu when `came_from` is set, but `cmd_boot` and `watch` call `thaw(m)` without it. The agent's image keeps the other Sprite's cgroups until `watch` freezes it locally. Because the thaw re-baselines `cpu_at_freeze`, that first local freeze waits for a burst of work. If the Sprite restarts before then, the thaw fails and is retried every 2 s (issue 4).

**Fix:** have `thaw()` add `MOVED_ARGS` itself whenever the current image was taken on a different Sprite (record the Sprite name inside the images directory), or force a local freeze right after landing.

### 13. A failed import can land silently later, leaving two copies (lines 861–868)

When an import's thaw fails, the status is set to `frozen`, which is not parked. `watch` on the destination then retries the thaw every 2 s. If it eventually succeeds, for example after a transient PID collision clears, `landed()` is never called. The source is never told, its ticket stays valid, and the printed advice ("on the source, `cryo thaw` brings it back") produces a second running copy.

**Fix:** keep a failed import in `arriving` or another parked status, and have any successful thaw of an agent with `landing` set call `landed()`.

### 14. Import overwrites local state with no backup (lines 806, 840–853)

`import` refuses only if an agent with the same name is *running*. It overwrites the `images/` and `meta.json` of a stopped or frozen local agent with that name. It also replaces any carried file at its absolute path, for example the destination's own `~/.claude` session files, and makes it root-owned.

**Fix:**
- Refuse if that name exists locally at all, unless `--force` is given.
- Back up replaced files to `incoming/<name>/backup/`.
- Preserve the original uid and gid.

---

## Low

- **`cryo run` keeps an old snapshot (line 218).** Running a name that already exists leaves the previous run's `images/`. Until `watch` takes the first freeze (usually within about 2 s), a restart would bring back the *old* session. **Fix:** move the old images aside in `cmd_run`.
- **Teleport bundles stay on disk (lines 732–751, 1168).** Bundles hold the full process memory, including credentials. If an agent never lands, its bundle stays in `outgoing/` forever, and expired tickets are never pruned. **Fix:** delete them on expiry and on recall (the recall path at line 497 deletes tickets but not the bundle).
- **Import trusts the bundle.** Import writes `files/…` members to absolute paths and runs criu restore as root. That is inherent to the design, but it should be stated plainly. On Python < 3.12, `images/` members are also extracted without `filter="data"` (line 845). This Sprite runs Python 3.13, so it isn't exposed.

## What I checked that turned out fine

- `boot_id()` reads the right field for PID 1's start time.
- `#{pid}` really is the tmux server PID, so the whole tmux tree gets dumped.
- A non-tmux agent whose `output.log` grows after the snapshot still restores. I tested this through the live `watch` service with a throwaway agent called `zz-sizetest`, then stopped it and removed it. No other agent was touched.
