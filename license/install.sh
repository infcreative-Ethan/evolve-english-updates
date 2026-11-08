#!/bin/bash
# Installs the activation-code service on the Shanghai server. Run once:  sudo bash install.sh
# Safe to run again (updates the program, keeps the codes).
set -e
SRC=$(dirname "$(readlink -f "$0")")
id evolve-license >/dev/null 2>&1 || useradd --system --no-create-home --shell /usr/sbin/nologin evolve-license
install -d -m 755 /opt/evolve-license
install -d -m 750 -o evolve-license -g evolve-license /var/lib/evolve-license
install -m 755 "$SRC/server.py" /opt/evolve-license/server.py
cat > /usr/local/bin/evolve-key <<'E'
#!/bin/sh
# manage activation codes: evolve-key new 5 张三 | list | unbind CODE | revoke CODE | restore CODE
exec sudo -u evolve-license python3 /opt/evolve-license/server.py "$@"
E
chmod 755 /usr/local/bin/evolve-key
cat > /etc/systemd/system/evolve-license.service <<'E'
[Unit]
Description=Go to America activation codes
After=network.target
[Service]
User=evolve-license
ExecStart=/usr/bin/python3 /opt/evolve-license/server.py serve
Restart=always
[Install]
WantedBy=multi-user.target
E
systemctl daemon-reload
systemctl enable --now evolve-license
systemctl restart evolve-license

# nginx: pass /api/license/ on the port-8686 site to the service
F=$(grep -rlE 'listen[^;]*8686' /etc/nginx/ 2>/dev/null | head -1)
[ -n "$F" ] || { echo "找不到 8686 端口的 nginx 设置"; exit 1; }
if ! grep -q '/api/license/' "$F"; then
  cp "$F" "/root/nginx-before-license.conf"
  python3 - "$F" <<'PY'
import re, sys
p = sys.argv[1]; s = open(p).read()
m = re.search(r'^[ \t]*listen[^;]*8686[^;]*;[^\n]*\n', s, re.M)
block = ('    location /api/license/ {\n        proxy_pass http://127.0.0.1:8687;\n'
         '        proxy_set_header X-Real-IP $remote_addr;\n        client_max_body_size 4k;\n    }\n')
open(p, 'w').write(s[:m.end()] + block + s[m.end():])
PY
  if ! nginx -t 2>/dev/null; then cp "/root/nginx-before-license.conf" "$F"; echo "nginx 设置出错，已还原"; exit 1; fi
fi
systemctl reload nginx
sleep 1
R=$(curl -s -X POST http://127.0.0.1:8686/api/license/trial -d '{"device":"install-test"}')
case "$R" in *start*) echo "激活服务装好了";; *) echo "激活服务没有回应: $R"; exit 1;; esac
