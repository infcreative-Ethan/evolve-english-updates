# Uploads the mirror folder to the China server.
# The link from GitHub to mainland China is throttled per connection (about 15 KB/s each),
# but several connections at once add up, so files are sent by many rsync processes in
# parallel, most-needed first. Only files missing on the server (or with another size) go.
#
# usage: mirror_push.py <folder> <user@host> <ssh command>
import os, subprocess, sys, threading, time

SRC, DEST, SSH = sys.argv[1], sys.argv[2], sys.argv[3]
WORKERS = 16


def rsync(args, files=None, timeout=1800):
    cmd = ['rsync', '-rt', '--partial', '--timeout=120', '-e', SSH] + args
    if files is not None:
        cmd = cmd[:1] + ['--files-from=-'] + cmd[1:]
    r = subprocess.run(cmd, input='\n'.join(files) if files is not None else None, capture_output=True, text=True, timeout=timeout)
    return r.returncode, r.stdout + r.stderr


# what the server already has: path -> size
code, out = rsync(['--list-only', DEST + ':/'], timeout=600)
have = {}
for line in out.splitlines():
    p = line.split(None, 4)
    if len(p) == 5 and p[0].startswith('-'):
        have[p[4]] = int(p[1].replace(',', ''))
print('server has', len(have), 'files')

local = {}
for root, _, names in os.walk(SRC):
    for n in names:
        f = os.path.relpath(os.path.join(root, n), SRC)
        local[f] = os.path.getsize(os.path.join(SRC, f))


def need(f):
    return f.endswith('.json') or have.get(f) != local[f]


def rank(f):
    # pronunciation audio (long readings first), installer, speech model, then listening audio
    if f.startswith('tts/') and f.endswith('.mp3'): return (0, -local[f])
    if f.startswith('releases/v'): return (2, 0)
    if f.startswith('releases/'): return (3, 0)
    if f.startswith('voa/') and f.endswith('.mp3'): return (4, f)
    return (1, f)


def send(files, label):
    files = sorted(files, key=rank)
    if not files: return
    total = sum(local[f] for f in files)
    print(f'{label}: {len(files)} files, {total // 1024} KB', flush=True)
    # batches of about 1 MB (a big file is a batch of its own), shared by the workers
    batches, cur, size = [], [], 0
    for f in files:
        cur.append(f); size += local[f]
        if size > 1_000_000 or len(cur) >= 40: batches.append(cur); cur, size = [], 0
    if cur: batches.append(cur)
    lock, fails, t0, sent = threading.Lock(), [], time.time(), [0]

    def work():
        while True:
            with lock:
                if not batches: return
                b = batches.pop(0)
            for attempt in range(4):
                try:
                    code, out = rsync([SRC + '/', DEST + ':/'], files=b)
                except subprocess.TimeoutExpired:
                    code, out = 1, 'timeout'
                if code == 0: break
                time.sleep(5 * (attempt + 1))
            with lock:
                if code: fails.append((b[0], out.strip()[-200:]))
                else: sent[0] += sum(local[f] for f in b)

    ts = [threading.Thread(target=work) for _ in range(WORKERS)]
    for t in ts: t.start()
    for t in ts: t.join()
    dt = max(1, time.time() - t0)
    print(f'  done in {dt:.0f}s, {sent[0] // 1024} KB at {sent[0] / dt / 1024:.0f} KB/s, {len(fails)} batches failed', flush=True)
    for f, err in fails[:5]: print('  failed:', f, err)
    return not fails


todo = [f for f in local if need(f)]
lists = {'latest.json', 'tts/index.json'}
ok = True
# 1. course texts, the installer and speech model, then the update list that points at them
#    (a new version reaches phones first; a big batch of re-recorded audio must not hold it up)
ok &= send([f for f in todo if rank(f)[0] == 1 and f not in lists], 'course texts') is not False
ok &= send([f for f in todo if rank(f)[0] in (2, 3)], 'installer and model') is not False
ok &= send(['latest.json'], 'update list') is not False
# 2. pronunciation audio, then the list that points at it
ok &= send([f for f in todo if rank(f)[0] == 0], 'pronunciation audio') is not False
ok &= send(['tts/index.json'], 'pronunciation list') is not False
# 3. listening audio
ok &= send([f for f in todo if rank(f)[0] == 4], 'listening audio') is not False
sys.exit(0 if ok else 1)
