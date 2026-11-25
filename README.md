# cryo

Sprites drop running processes when they go cold, move hosts, or get restored
from a checkpoint. Only the disk survives. cryo freezes processes to disk with
CRIU and brings them back after the machine restarts.

Work in progress for Fly.io Hacksgiving 2026.

```
sudo apt-get install -y criu tmux
sudo ./cryo run counter -- python3 -c 'import time,itertools;[print(i,flush=True) or time.sleep(1) for i in itertools.count()]'
sudo ./cryo freeze counter --keep    # snapshot, keep running
sudo ./cryo ls
# ...sprite restarts...
sudo ./cryo boot                     # thaws everything that died
sudo ./cryo watch --interval 30      # snapshot loop + auto thaw
```

Notes from testing on Sprites (kernel 6.12.87-fly):
- root has no CAP_SYS_PTRACE, so CRIU can only freeze processes owned by the
  same user. cryo starts everything as root for that reason.
- no CAP_SYS_TIME, so time namespace restore fails. cryo drops the timens image
  and the process just sees its monotonic clock jump.
- io_uring can't be dumped. cryo sets UV_USE_IO_URING=0 for node/libuv.
