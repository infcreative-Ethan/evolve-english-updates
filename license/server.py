#!/usr/bin/env python3
"""Activation codes for the Go to America app, running on the family's server in Shanghai.

One code per person, bound to one phone. A phone without a code may be used for 3 days.

Service (started by systemd, behind nginx at http://<server>:8686/api/license/):
  POST trial    {device, model}        -> {start, now}          first time this phone was seen
  POST activate {code, device, model}  -> {ok} | {ok:false, reason}
  POST check    {code, device}         -> {ok} | {ok:false, reason}
  reasons: invalid (no such code), revoked (stopped), used (bound to another phone)

Commands (run on the server, e.g. `sudo evolve-key new 5 张三`):
  new N [note]   make N new codes      list           show all codes
  unbind CODE    free a code for a new phone      revoke CODE / restore CODE
"""
import json, os, secrets, sqlite3, sys, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DB = os.environ.get('EVOLVE_LICENSE_DB', '/var/lib/evolve-license/keys.db')
PORT = 8687
ABC = 'ABCDEFGHJKMNPQRSTUVWXYZ23456789'  # no 0/O, 1/I/L

def db():
    c = sqlite3.connect(DB, timeout=10)
    c.execute('create table if not exists codes(code text primary key, note text, device text, model text,'
              ' created int, activated int, revoked int default 0)')
    c.execute('create table if not exists devices(device text primary key, first int, model text)')
    return c

def clean(code):
    return ''.join(ch for ch in str(code or '').upper() if ch in ABC)

def pretty(code):
    return '-'.join(code[i:i + 4] for i in range(0, len(code), 4))

def check(c, code, device):
    row = c.execute('select device, revoked from codes where code=?', (code,)).fetchone()
    if not row: return 'invalid'
    if row[1]: return 'revoked'
    if row[0] and row[0] != device: return 'used'
    return None

tries = {}  # ip -> [window start, count]: slows down guessing
def limited(ip):
    now = time.time(); w = tries.get(ip)
    if not w or now - w[0] > 3600: tries[ip] = [now, 1]; return False
    w[1] += 1
    return w[1] > 40

class H(BaseHTTPRequestHandler):
    def reply(self, obj, code=200):
        b = json.dumps(obj).encode()
        self.send_response(code); self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(b))); self.end_headers(); self.wfile.write(b)

    def do_POST(self):
        try:
            n = min(int(self.headers.get('Content-Length') or 0), 4096)
            q = json.loads(self.rfile.read(n) or b'{}')
        except Exception:
            return self.reply({'ok': False, 'reason': 'bad request'}, 400)
        what = self.path.rstrip('/').rsplit('/', 1)[-1]
        device = str(q.get('device') or '')[:80]
        model = str(q.get('model') or '')[:80]
        now = int(time.time())
        if not device: return self.reply({'ok': False, 'reason': 'bad request'}, 400)
        c = db()
        try:
            if what == 'trial':
                c.execute('insert or ignore into devices(device, first, model) values (?,?,?)', (device, now, model))
                c.commit()
                first = c.execute('select first from devices where device=?', (device,)).fetchone()[0]
                return self.reply({'ok': True, 'start': first * 1000, 'now': now * 1000})
            ip = self.headers.get('X-Real-IP') or self.client_address[0]
            if what == 'activate' and limited(ip):
                return self.reply({'ok': False, 'reason': 'busy'})
            code = clean(q.get('code'))
            bad = check(c, code, device)
            if bad: return self.reply({'ok': False, 'reason': bad, 'now': now * 1000})
            if what == 'activate':
                c.execute('update codes set device=?, model=?, activated=coalesce(activated, ?) where code=?', (device, model, now, code))
                c.commit()
                return self.reply({'ok': True, 'code': pretty(code), 'now': now * 1000})
            if what == 'check':
                return self.reply({'ok': True, 'now': now * 1000})
            return self.reply({'ok': False, 'reason': 'bad request'}, 404)
        finally:
            c.close()

    def log_message(self, *a):
        pass

def main(a):
    if not a or a[0] == 'serve':
        ThreadingHTTPServer(('127.0.0.1', PORT), H).serve_forever()
    c = db()
    if a[0] == 'new':
        n = int(a[1]) if len(a) > 1 else 1; note = ' '.join(a[2:])
        for _ in range(n):
            code = ''.join(secrets.choice(ABC) for _ in range(12))
            c.execute('insert into codes(code, note, created) values (?,?,?)', (code, note, int(time.time())))
            print(pretty(code), note)
    elif a[0] == 'list':
        fmt = lambda t: time.strftime('%Y-%m-%d', time.localtime(t)) if t else '-'
        for code, note, dev, model, cr, act, rev in c.execute('select * from codes order by created'):
            st = '已停用' if rev else ('已激活 ' + fmt(act) + ' ' + (model or dev[:8]) if dev else '未使用')
            print(pretty(code), st, note or '')
    elif a[0] in ('unbind', 'revoke', 'restore'):
        code = clean(a[1] if len(a) > 1 else '')
        sql = {'unbind': 'update codes set device=null, model=null where code=?',
               'revoke': 'update codes set revoked=1 where code=?',
               'restore': 'update codes set revoked=0 where code=?'}[a[0]]
        if not c.execute(sql, (code,)).rowcount: print('没有这个码:', a[1:] and a[1]); sys.exit(1)
        print({'unbind': '已解绑，可以在新手机上激活', 'revoke': '已停用', 'restore': '已恢复'}[a[0]], pretty(code))
    else:
        print(__doc__); sys.exit(1)
    c.commit()

if __name__ == '__main__':
    main(sys.argv[1:])
