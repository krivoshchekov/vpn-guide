# Свой VPN через российский сервер: пошаговая инструкция

Схема проверена в ноябре 2026 года и работает на мобильном интернете и домашнем Wi‑Fi в Москве. Обстановка с блокировками меняется быстро, поэтому что-то может потребовать доработки.

## Как это устроено

Телефон или компьютер → **ваш домен на российском сервере** (порт 443, обычный TLS с настоящим сертификатом) → **Shadowsocks** → **зарубежный сервер** → интернет.

- Для провайдера это выглядит как заход на обычный российский сайт: российский домен, российский IP, честный сертификат. Кто откроет домен в браузере, увидит страницу входа на «портал».
- Зарубежный сервер — это выход в интернет. Его IP видят сайты, к нему напрямую никто из пользователей не подключается.
- Ссылки у пользователей привязаны к домену. Если российский сервер придется сменить, достаточно поменять DNS-запись, пользователям ничего делать не нужно.

## Что понадобится

| Что | Где брать | Примерная цена |
|---|---|---|
| Российский VPS (вход) | например, firstbyte.ru — тариф MSK-KVM-SSD (1 ядро, 1 ГБ, Москва) | ~190 ₽/мес |
| Зарубежный VPS (выход) | любой хостер в Европе, например adminvps.ru (Германия/Финляндия) | ~300–600 ₽/мес |
| Домен в зоне .ru | Timeweb, reg.ru, 2domains.ru | несколько сотен ₽/год |
| Telegram-бот | @BotFather | бесплатно |

На обоих серверах — **Ubuntu 22.04 или 24.04**, обязательно с **публичным IPv4**. Все команды ниже выполняются от root.

**Обозначения.** Везде, где написано `<...>`, подставьте свое значение:
- `<IP_RU>` — IP российского сервера;
- `<IP_ZA>` — IP зарубежного сервера;
- `<ДОМЕН>` — ваш домен, например `my-dacha.ru`.

---

## Шаг 1. Зарубежный сервер (выход)

Зайдите на него по SSH. Если из дома SSH не пускает, заходите через любой работающий VPN.

```bash
apt update && apt upgrade -y
bash -c "$(curl -L https://github.com/XTLS/Xray-install/raw/main/install-release.sh)" @ install

SS_KEY=$(openssl rand -base64 16)
echo "Ключ Shadowsocks: $SS_KEY   <- сохраните, понадобится на российском сервере"

cat > /usr/local/etc/xray/config.json <<EOF
{"log":{"loglevel":"warning"},
 "inbounds":[{"port":23456,"protocol":"shadowsocks",
   "settings":{"method":"2022-blake3-aes-128-gcm","password":"$SS_KEY","network":"tcp,udp"}}],
 "outbounds":[{"protocol":"freedom"}]}
EOF
xray run -test -c /usr/local/etc/xray/config.json && systemctl restart xray && systemctl enable xray && systemctl is-active xray
```

Должно быть `Configuration OK` и `active`. **Запишите ключ Shadowsocks.**

---

## Шаг 2. Домен

1. Купите домен в зоне `.ru`. Имя любое, не связанное с VPN.
2. В DNS-записях домена:
   - `A` → `<IP_RU>`;
   - удалите все остальные записи `A` и `AAAA`, которые поставил регистратор (заглушки/парковка).
3. Если регистратор не дает удалить свою `AAAA` (так бывает у Timeweb на тарифе «Парковка»), **добавьте свою** `AAAA` с IPv6 российского сервера. Его можно узнать на сервере командой `ip -6 addr show scope global`.

Через 10–30 минут проверьте на российском сервере:
```bash
getent ahostsv4 <ДОМЕН> | head -1   # должен быть <IP_RU>
getent ahostsv6 <ДОМЕН> | head -1   # пусто или IPv6 вашего российского сервера
```
Дальше идти только после этого.

---

## Шаг 3. Российский сервер (вход)

### 3.1. Установка и сертификат

Подставьте домен в первой строке:

```bash
DOMAIN=<ДОМЕН>

apt update && apt install -y certbot nginx qrencode python3
bash -c "$(curl -L https://github.com/XTLS/Xray-install/raw/main/install-release.sh)" @ install

# сайт-заглушка на внутреннем порту
cat > /etc/nginx/sites-enabled/default <<'EOF'
server { listen 127.0.0.1:8080; root /var/www/html; index index.html; }
EOF
systemctl restart nginx

# сертификат Let's Encrypt
systemctl stop xray
certbot certonly --standalone -d $DOMAIN --agree-tos --register-unsafely-without-email -n
mkdir -p /usr/local/etc/xray/cert
cp -L /etc/letsencrypt/live/$DOMAIN/fullchain.pem /etc/letsencrypt/live/$DOMAIN/privkey.pem /usr/local/etc/xray/cert/
chmod 644 /usr/local/etc/xray/cert/*

# автопродление сертификата
cat > /etc/letsencrypt/renewal-hooks/deploy/xray.sh <<EOF
#!/bin/sh
cp -L /etc/letsencrypt/live/$DOMAIN/fullchain.pem /etc/letsencrypt/live/$DOMAIN/privkey.pem /usr/local/etc/xray/cert/
chmod 644 /usr/local/etc/xray/cert/*
systemctl restart xray
EOF
chmod +x /etc/letsencrypt/renewal-hooks/deploy/xray.sh
ls -l /usr/local/etc/xray/cert/
```

В выводе certbot должно быть `Successfully received certificate`, в конце два файла `fullchain.pem` и `privkey.pem`.

### 3.2. Страница-заглушка

Это то, что увидит человек или проверяющая система, если откроет ваш домен в браузере: форма входа, которая на любые данные отвечает «Неверный логин или пароль». Форма ничего никуда не отправляет и не сохраняет.

```bash
cat > /var/www/html/index.html <<'EOF'
<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Портал — вход</title><meta name="robots" content="noindex,nofollow">
<style>
:root{--bg:#f5f3ee;--card:#fffdf8;--ink:#2b2a27;--muted:#76726a;--accent:#5f7a4a;--line:#e3dfd4;--err:#b4412f}
@media (prefers-color-scheme:dark){:root{--bg:#1c1d1a;--card:#24261f;--ink:#ecebe6;--muted:#a3a097;--accent:#9dbb84;--line:#34362f;--err:#e58a78}}
*{box-sizing:border-box}html,body{margin:0;height:100%}
body{background:var(--bg);color:var(--ink);font:16px/1.5 -apple-system,"Segoe UI",Roboto,Arial,sans-serif;display:flex;align-items:center;justify-content:center;padding:24px}
main{max-width:400px;width:100%;background:var(--card);border:1px solid var(--line);border-radius:18px;padding:36px 32px}
h1{font-size:26px;margin:0;text-align:center}.sub{color:var(--muted);margin:2px 0 20px;text-align:center}
label{display:block;font-size:14px;color:var(--muted);margin:14px 0 6px}
input{width:100%;padding:11px 12px;font:inherit;color:var(--ink);background:transparent;border:1px solid var(--line);border-radius:10px}
button{width:100%;margin-top:22px;padding:12px;font:inherit;font-weight:600;color:#fff;background:var(--accent);border:0;border-radius:10px;cursor:pointer}
.msg{min-height:22px;margin-top:12px;text-align:center;font-size:14px;color:var(--err)}
</style></head><body><main>
<h1>Портал</h1><p class="sub">Вход для сотрудников</p>
<form id="f" autocomplete="off"><label>Логин</label><input id="u"><label>Пароль</label><input id="p" type="password">
<button id="b">Войти</button><div class="msg" id="m"></div></form></main>
<script>
var f=document.getElementById('f'),b=document.getElementById('b'),m=document.getElementById('m'),p=document.getElementById('p');
f.onsubmit=function(e){e.preventDefault();m.textContent='';b.disabled=true;b.textContent='Проверка…';
setTimeout(function(){b.disabled=false;b.textContent='Войти';p.value='';m.textContent='Неверный логин или пароль';},900+Math.random()*700);};
</script></body></html>
EOF
```

Название «Портал» поменяйте на что-то свое, подходящее к домену.

### 3.3. Настройка Xray

Подставьте домен, IP зарубежного сервера и ключ Shadowsocks из шага 1:

```bash
DOMAIN=<ДОМЕН>
IP_ZA=<IP_ZA>
SS_KEY='<ключ Shadowsocks из шага 1>'

python3 - "$DOMAIN" "$IP_ZA" "$SS_KEY" <<'EOF'
import json, sys, uuid
domain, ip_za, ss_key = sys.argv[1:]
me, mon = str(uuid.uuid4()), str(uuid.uuid4())
cfg = {
 "log": {"loglevel": "warning"},
 "inbounds": [
  {"tag": "in", "listen": "::", "port": 443, "protocol": "vless",
   "settings": {"clients": [{"id": me, "flow": "xtls-rprx-vision", "email": "me"},
                            {"id": mon, "flow": "xtls-rprx-vision", "email": "monitor"}],
                "decryption": "none", "fallbacks": [{"dest": "127.0.0.1:8080"}]},
   "streamSettings": {"network": "tcp", "security": "tls",
     "tlsSettings": {"serverName": domain, "alpn": ["http/1.1"], "minVersion": "1.2",
       "certificates": [{"certificateFile": "/usr/local/etc/xray/cert/fullchain.pem",
                         "keyFile": "/usr/local/etc/xray/cert/privkey.pem"}]}},
   "sniffing": {"enabled": True, "destOverride": ["http", "tls", "quic"]}},
  {"tag": "monitor", "listen": "127.0.0.1", "port": 10808, "protocol": "socks", "settings": {"udp": False}}],
 "outbounds": [
  {"tag": "za", "protocol": "shadowsocks", "settings": {"servers": [{"address": ip_za, "port": 23456,
     "method": "2022-blake3-aes-128-gcm", "password": ss_key, "uot": True, "UoTVersion": 2}]}},
  {"tag": "direct", "protocol": "freedom"},
  {"tag": "block", "protocol": "blackhole"}]}
json.dump(cfg, open("/usr/local/etc/xray/config.json", "w"), separators=(",", ":"))
print("MON_UUID =", mon)
print("Ваша ссылка:")
print(f"vless://{me}@{domain}:443?type=tcp&encryption=none&security=tls&sni={domain}&fp=firefox&alpn=http%2F1.1&flow=xtls-rprx-vision#me")
EOF
xray run -test -c /usr/local/etc/xray/config.json && systemctl restart xray && systemctl enable xray && systemctl is-active xray
```

Скрипт напечатает `MON_UUID` (запишите, он нужен для мониторинга) и **вашу первую ссылку `vless://…`**.

Проверка:
```bash
curl -s -m 15 -x socks5h://127.0.0.1:10808 https://ifconfig.me; echo   # должен быть <IP_ZA>
```
И снаружи: откройте `https://<ДОМЕН>` в браузере — должна показаться страница входа.

### 3.4. Удобный вход по SSH (на своем Mac/ПК)

```bash
cat >> ~/.ssh/config <<'EOF'
Host vpn-ru
    HostName <IP_RU>
    User root
EOF
```
Дальше заходить командой `ssh vpn-ru`.

---

## Шаг 4. Подключение устройств

- **iPhone / Android:** приложение **v2RayTun** → «+» → вставить ссылку из буфера (или сканировать QR).
- **Mac / Windows:** v2RayTun, Hiddify или v2rayN → импорт ссылки из буфера.

Проверка: подключиться, открыть 2ip.ru — должен показываться `<IP_ZA>` (зарубежный IP).

Клиентов удобнее всего добавлять через бота (шаг 6).

---

## Шаг 5. Мониторинг и уведомления в Telegram

### 5.1. Создать бота и узнать chat_id
1. В Telegram: @BotFather → `/newbot` → имя и логин (на `bot`). Сохраните **токен**, никому его не пересылайте.
2. Откройте своего бота, нажмите **«Старт»** и напишите ему что-нибудь. Бот не ответит — это нормально.
3. Из российского дата-центра Telegram напрямую часто недоступен, поэтому запросы идут через туннель:

```bash
TOKEN='<токен бота>'
curl -s -m 20 -x socks5h://127.0.0.1:10808 "https://api.telegram.org/bot$TOKEN/getUpdates" | grep -o '"chat":{"id":[0-9-]*'
```
Число после `"id":` — ваш **chat_id**. Если пусто — напишите боту еще раз и повторите.

### 5.2. Настройки мониторинга (российский сервер)

```bash
cat > /etc/vpn-monitor.env <<'EOF'
BOT_TOKEN='<токен бота>'
CHAT_ID='<chat_id>'
DOMAIN='<ДОМЕН>'
EXIT_IP='<IP_ZA>'
MON_UUID='<MON_UUID из шага 3.3>'
EOF
chmod 600 /etc/vpn-monitor.env

cat > /usr/local/bin/vpn-monitor.sh <<'EOF'
#!/bin/bash
source /etc/vpn-monitor.env
STATE=/var/lib/vpn-monitor; mkdir -p $STATE
problems=()
systemctl is-active --quiet xray || problems+=("Xray не запущен")
ip=$(curl -s -m 15 -x socks5h://127.0.0.1:10808 https://ifconfig.me 2>/dev/null)
[ "$ip" = "$EXIT_IP" ] || problems+=("Нет связи с зарубежным сервером (ответ: ${ip:-нет})")
code=$(curl --noproxy "*" -s -o /dev/null -m 10 -w '%{http_code}' --resolve $DOMAIN:443:127.0.0.1 https://$DOMAIN 2>/dev/null)
[ "$code" = "200" ] || problems+=("Вход https://$DOMAIN не отвечает (код ${code:-нет})")
end=$(echo | openssl s_client -connect 127.0.0.1:443 -servername $DOMAIN 2>/dev/null | openssl x509 -noout -enddate 2>/dev/null | cut -d= -f2)
if [ -n "$end" ]; then
  days=$(( ($(date -d "$end" +%s) - $(date +%s)) / 86400 ))
  [ "$days" -lt 10 ] && problems+=("Сертификат истекает через $days дн.")
fi
send() {
  curl --noproxy "*" -s -m 15 "https://api.telegram.org/bot$BOT_TOKEN/sendMessage" -d chat_id="$CHAT_ID" --data-urlencode text="$1" >/dev/null && return
  curl -s -m 20 -x socks5h://127.0.0.1:10808 "https://api.telegram.org/bot$BOT_TOKEN/sendMessage" -d chat_id="$CHAT_ID" --data-urlencode text="$1" >/dev/null
}
prev=$(cat $STATE/status 2>/dev/null || echo ok)
fails=$(cat $STATE/fails 2>/dev/null || echo 0)
if [ ${#problems[@]} -eq 0 ]; then
  echo 0 > $STATE/fails
  if [ "$prev" = "down" ]; then send "✅ VPN снова работает ($(TZ=Europe/Moscow date '+%d.%m %H:%M') МСК)"; echo ok > $STATE/status; fi
else
  fails=$((fails+1)); echo $fails > $STATE/fails
  last=$(cat $STATE/last_alert 2>/dev/null || echo 0)
  if [ $fails -ge 2 ] && { [ "$prev" != "down" ] || [ $(( $(date +%s) - last )) -ge 7200 ]; }; then
    msg="⚠️ Проблема с VPN ($(TZ=Europe/Moscow date '+%d.%m %H:%M') МСК):"
    for p in "${problems[@]}"; do msg+=$'\n'"• $p"; done
    send "$msg"; echo down > $STATE/status; date +%s > $STATE/last_alert
  fi
fi
EOF
chmod +x /usr/local/bin/vpn-monitor.sh
echo '*/5 * * * * root /usr/local/bin/vpn-monitor.sh' > /etc/cron.d/vpn-monitor

bash -x /usr/local/bin/vpn-monitor.sh 2>&1 | grep -E "ip=|code=|days="
```
Должно быть `ip=<IP_ZA>`, `code=200` и число дней сертификата. Тревога приходит после 2 неудачных проверок подряд (~10 минут), напоминание раз в 2 часа, плюс сообщение о восстановлении.

### 5.3. Мониторинг с зарубежного сервера (рекомендуется)

Российский сервер шлет уведомления через туннель, поэтому если упадет он сам или туннель, он промолчит. Зарубежный сервер каждые 5 минут подключается к VPN как обычный клиент и пишет в Telegram напрямую.

На **зарубежном** сервере:
```bash
cat > /etc/vpn-monitor.env <<'EOF'
BOT_TOKEN='<токен бота>'
CHAT_ID='<chat_id>'
DOMAIN='<ДОМЕН>'
EXIT_IP='<IP_ZA>'
MON_UUID='<MON_UUID>'
EOF
chmod 600 /etc/vpn-monitor.env
source /etc/vpn-monitor.env

cat > /etc/vpn-monitor-client.json <<EOF
{"log":{"loglevel":"none"},"inbounds":[{"listen":"127.0.0.1","port":10809,"protocol":"socks"}],
 "outbounds":[{"protocol":"vless","settings":{"vnext":[{"address":"$DOMAIN","port":443,
   "users":[{"id":"$MON_UUID","flow":"xtls-rprx-vision","encryption":"none"}]}]},
   "streamSettings":{"network":"tcp","security":"tls","tlsSettings":{"serverName":"$DOMAIN","fingerprint":"firefox","alpn":["http/1.1"]}}}]}
EOF

cat > /usr/local/bin/vpn-monitor.sh <<'EOF'
#!/bin/bash
source /etc/vpn-monitor.env
STATE=/var/lib/vpn-monitor; mkdir -p $STATE
problems=()
code=$(curl --noproxy "*" -s -o /dev/null -m 15 -w '%{http_code}' https://$DOMAIN 2>/dev/null)
[ "$code" = "200" ] || problems+=("Российский сервер $DOMAIN не отвечает (код ${code:-нет})")
/usr/local/bin/xray run -c /etc/vpn-monitor-client.json >/dev/null 2>&1 & XP=$!; sleep 3
ip=$(curl -s -m 20 -x socks5h://127.0.0.1:10809 https://ifconfig.me 2>/dev/null)
kill $XP 2>/dev/null
[ "$ip" = "$EXIT_IP" ] || problems+=("Подключение через VPN не работает (ответ: ${ip:-нет})")
send() { curl --noproxy "*" -s -m 15 "https://api.telegram.org/bot$BOT_TOKEN/sendMessage" -d chat_id="$CHAT_ID" --data-urlencode text="$1" >/dev/null; }
prev=$(cat $STATE/status 2>/dev/null || echo ok)
fails=$(cat $STATE/fails 2>/dev/null || echo 0)
if [ ${#problems[@]} -eq 0 ]; then
  echo 0 > $STATE/fails
  if [ "$prev" = "down" ]; then send "✅ [Заграница] VPN снова работает ($(TZ=Europe/Moscow date '+%d.%m %H:%M') МСК)"; echo ok > $STATE/status; fi
else
  fails=$((fails+1)); echo $fails > $STATE/fails
  last=$(cat $STATE/last_alert 2>/dev/null || echo 0)
  if [ $fails -ge 2 ] && { [ "$prev" != "down" ] || [ $(( $(date +%s) - last )) -ge 7200 ]; }; then
    msg="⚠️ [Заграница] Проблема с VPN ($(TZ=Europe/Moscow date '+%d.%m %H:%M') МСК):"
    for p in "${problems[@]}"; do msg+=$'\n'"• $p"; done
    send "$msg"; echo down > $STATE/status; date +%s > $STATE/last_alert
  fi
fi
EOF
chmod +x /usr/local/bin/vpn-monitor.sh
echo '*/5 * * * * root /usr/local/bin/vpn-monitor.sh' > /etc/cron.d/vpn-monitor

curl -s -m 15 "https://api.telegram.org/bot$BOT_TOKEN/sendMessage" -d chat_id="$CHAT_ID" -d text="[Заграница] Мониторинг включен" | head -c 11; echo
bash -x /usr/local/bin/vpn-monitor.sh 2>&1 | grep -E "code=|ip="
```
Должно быть `{"ok":true`, `code=200`, `ip=<IP_ZA>`.

---

## Шаг 6. Бот-администратор

Тот же бот будет отвечать на команды (только вам — по chat_id):
- `тест` — проверить всю цепочку и показать, кто был активен за 15 минут;
- **логин латиницей** (например `petrov-mob`) или `добавить логин` — создать клиента, бот пришлет ссылку и QR-код;
- `ключ логин` — прислать ключ существующего клиента;
- `удалить логин` — отключить клиента;
- `список` — все клиенты.

При добавлении и удалении Xray перезапускается, VPN у всех прерывается на 1–2 секунды.

На **российском** сервере (токен, chat_id, домен, IP и MON_UUID бот берет из `/etc/vpn-monitor.env`, созданного в шаге 5.2):

```bash
cat > /usr/local/bin/vpn-bot.py <<'EOF'
#!/usr/bin/env python3
# Бот проверки VPN: на сообщение «тест» проверяет цепочку и показывает активных клиентов.
import json, os, re, shutil, subprocess, time, datetime, uuid

ENV = dict(l.strip().split("=", 1) for l in open("/etc/vpn-monitor.env") if "=" in l)
TOKEN = ENV["BOT_TOKEN"].strip("'\"")
CHAT = ENV["CHAT_ID"].strip("'\"")
API = f"https://api.telegram.org/bot{TOKEN}"
SOCKS = "socks5h://127.0.0.1:10808"
DOMAIN = ENV["DOMAIN"].strip("'\"")
EXIT_IP = ENV["EXIT_IP"].strip("'\"")
MON_UUID = ENV["MON_UUID"].strip("'\"")
CONFIG = "/usr/local/etc/xray/config.json"
LOGIN_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,31}$")
CLEAN = {k: v for k, v in os.environ.items() if k.lower() not in ("http_proxy", "https_proxy")}


def sh(cmd, timeout=40):
    try:
        return subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout, env=CLEAN).stdout.strip()
    except subprocess.TimeoutExpired:
        return ""


def tg(method, data=None, timeout=60):
    args = ["curl", "-s", "-m", str(timeout), "-x", SOCKS, f"{API}/{method}"]
    for k, v in (data or {}).items():
        args += ["--data-urlencode", f"{k}={v}"]
    try:
        out = subprocess.run(args, capture_output=True, text=True, timeout=timeout + 5, env=CLEAN).stdout
        return json.loads(out) if out else {}
    except Exception:
        return {}


def full_chain():
    cfg = {"log": {"loglevel": "none"},
           "inbounds": [{"listen": "127.0.0.1", "port": 10811, "protocol": "socks"}],
           "outbounds": [{"protocol": "vless", "settings": {"vnext": [{"address": "127.0.0.1", "port": 443,
                          "users": [{"id": MON_UUID, "flow": "xtls-rprx-vision", "encryption": "none"}]}]},
                          "streamSettings": {"network": "tcp", "security": "tls",
                                             "tlsSettings": {"serverName": DOMAIN, "fingerprint": "firefox", "alpn": ["http/1.1"]}}}]}
    open("/tmp/vpn-bot-client.json", "w").write(json.dumps(cfg))
    p = subprocess.Popen(["xray", "run", "-c", "/tmp/vpn-bot-client.json"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(2)
    ip = sh("curl -s -m 20 -x socks5h://127.0.0.1:10811 https://ifconfig.me")
    p.terminate()
    return ip


def link(uid, login):
    return (f"vless://{uid}@{DOMAIN}:443?type=tcp&encryption=none&security=tls&sni={DOMAIN}"
            f"&fp=firefox&alpn=http%2F1.1&flow=xtls-rprx-vision#{login}")


def clients():
    c = json.load(open(CONFIG))
    inb = [i for i in c["inbounds"] if i.get("port") == 443][0]
    return c, inb["settings"]["clients"]


def apply(c):
    shutil.copy(CONFIG, CONFIG + ".bak")
    json.dump(c, open(CONFIG, "w"), separators=(",", ":"))
    if subprocess.run(["xray", "run", "-test", "-c", CONFIG], capture_output=True).returncode != 0:
        shutil.copy(CONFIG + ".bak", CONFIG)
        return False
    sh("systemctl restart xray")
    time.sleep(2)
    return sh("systemctl is-active xray") == "active"


def send_key(login, uid, title):
    url = link(uid, login)
    tg("sendMessage", {"chat_id": CHAT, "text": f"{title}\n\n{url}"})
    png = f"/tmp/qr-{login}.png"
    if shutil.which("qrencode") and subprocess.run(["qrencode", "-s", "8", "-o", png, url]).returncode == 0:
        subprocess.run(["curl", "-s", "-m", "60", "-x", SOCKS, f"{API}/sendPhoto", "-F", f"chat_id={CHAT}",
                        "-F", f"photo=@{png}", "-F", f"caption={login}"], capture_output=True, env=CLEAN)
        os.remove(png)


def cmd_add(login):
    if not LOGIN_RE.match(login):
        return "Логин: латиница, цифры, точка, дефис или подчеркивание, 2–32 символа. Например: petrov-mob"
    c, cl = clients()
    for x in cl:
        if x.get("email") == login:
            send_key(login, x["id"], f"ℹ️ {login} уже есть, вот его ключ:")
            return None
    uid = str(uuid.uuid4())
    cl.append({"id": uid, "flow": "xtls-rprx-vision", "email": login})
    if not apply(c):
        return "❌ Не удалось применить настройки, ничего не изменено."
    send_key(login, uid, f"✅ Клиент {login} добавлен. Ключ:")
    return None


def cmd_key(login):
    _, cl = clients()
    for x in cl:
        if x.get("email") == login:
            send_key(login, x["id"], f"🔑 Ключ {login}:")
            return None
    return f"Клиента {login} нет. Список — команда «список»."


def cmd_del(login):
    if login == "monitor":
        return "Это служебный клиент мониторинга, его удалять нельзя."
    c, cl = clients()
    left = [x for x in cl if x.get("email") != login]
    if len(left) == len(cl):
        return f"Клиента {login} нет."
    cl[:] = left
    return f"🗑 Клиент {login} удален, его ключ больше не работает." if apply(c) else "❌ Не удалось применить настройки, ничего не изменено."


def cmd_list():
    _, cl = clients()
    names = [x.get("email", "?") for x in cl if x.get("email") != "monitor"]
    return f"👥 Клиентов: {len(names)}\n" + "\n".join(names)


HELP = ("Команды:\n"
        "тест — проверить VPN и показать активных\n"
        "логин (латиницей) или «добавить логин» — новый клиент, пришлю ключ и QR\n"
        "ключ логин — прислать ключ существующего\n"
        "удалить логин — отключить клиента\n"
        "список — все клиенты\n\n"
        "При добавлении и удалении VPN у всех прерывается на 1–2 секунды.")


def report():
    lines, ok = [], True

    def chk(good, text_ok, text_bad):
        nonlocal ok
        ok &= good
        lines.append(("✅ " + text_ok) if good else ("❌ " + text_bad))

    chk(sh("systemctl is-active xray") == "active", "Xray на российском сервере запущен", "Xray на российском сервере не запущен")
    code = sh(f"curl --noproxy '*' -s -o /dev/null -m 10 -w '%{{http_code}}' --resolve {DOMAIN}:443:127.0.0.1 https://{DOMAIN}")
    chk(code == "200", f"Вход {DOMAIN} отвечает", f"Вход {DOMAIN} не отвечает (код {code or 'нет'})")
    ip = sh(f"curl -s -m 15 -x {SOCKS} https://ifconfig.me")
    chk(ip == EXIT_IP, "Связь с зарубежным сервером есть", f"Нет связи с зарубежным сервером (ответ {ip or 'нет'})")
    ip2 = full_chain()
    chk(ip2 == EXIT_IP, f"Полная цепочка как у клиента: выход {EXIT_IP}", f"Полная цепочка не работает (ответ {ip2 or 'нет'})")
    end = sh(f"echo | openssl s_client -connect 127.0.0.1:443 -servername {DOMAIN} 2>/dev/null | openssl x509 -noout -enddate | cut -d= -f2")
    if end:
        days = (datetime.datetime.strptime(end, "%b %d %H:%M:%S %Y %Z") - datetime.datetime.utcnow()).days
        chk(days >= 10, f"Сертификат: еще {days} дн.", f"Сертификат истекает через {days} дн.")

    log = sh("journalctl -u xray --since '-15 min' --no-pager")
    users = sorted(set(re.findall(r"email: (\S+)", log)) - {"monitor"})
    ips = sh("ss -tnH state established '( sport = :443 )' | awk '{print $4}' | sed 's/:[0-9]*$//' | sort -u | grep -v -e 127.0.0.1 -e '\\[::1\\]' | wc -l")

    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=3))).strftime("%d.%m %H:%M")
    head = f"{'🟢 Все в порядке' if ok else '🔴 Есть проблемы'} ({now} МСК)"
    body = "\n".join(lines)
    cl = f"\n\n👥 Активны за 15 минут: {len(users)}" + (f"\n{', '.join(users)}" if users else "") + f"\nОткрытых подключений сейчас: с {ips or 0} адресов"
    return head + "\n\n" + body + cl


def main():
    offset = 0
    while True:
        r = tg("getUpdates", {"offset": offset, "timeout": 50}, timeout=60)
        if not r.get("ok"):
            time.sleep(10)
            continue
        for u in r.get("result", []):
            offset = u["update_id"] + 1
            m = u.get("message") or {}
            if str(m.get("chat", {}).get("id")) != CHAT:
                continue
            t = " ".join((m.get("text") or "").strip().lower().split())
            cmd, _, arg = t.partition(" ")
            try:
                if t in ("тест", "test", "/test", "/status", "статус"):
                    tg("sendMessage", {"chat_id": CHAT, "text": "⏳ Проверяю..."})
                    ans = report()
                elif cmd in ("добавить", "/add", "+") and arg:
                    ans = cmd_add(arg)
                elif cmd in ("ключ", "/key") and arg:
                    ans = cmd_key(arg)
                elif cmd in ("удалить", "/del", "-") and arg:
                    ans = cmd_del(arg)
                elif t in ("список", "/list", "клиенты"):
                    ans = cmd_list()
                elif LOGIN_RE.match(t):
                    ans = cmd_add(t)
                else:
                    ans = HELP
            except Exception as e:
                ans = f"❌ Ошибка: {e}"
            if ans:
                tg("sendMessage", {"chat_id": CHAT, "text": ans})


if __name__ == "__main__":
    main()
EOF
```

```bash
chmod +x /usr/local/bin/vpn-bot.py
cat > /etc/systemd/system/vpn-bot.service <<'EOF'
[Unit]
Description=VPN check bot
After=network-online.target xray.service

[Service]
ExecStart=/usr/bin/python3 /usr/local/bin/vpn-bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload && systemctl enable --now vpn-bot && sleep 2 && systemctl is-active vpn-bot
```
Напишите боту `тест` — через 5–10 секунд придет отчет.

---

## Если не работает

1. **Что пишет бот?** Сообщение без пометки — от российского сервера, `[Заграница]` — от зарубежного.
2. **Проверьте на той же сети другой VPN.** Если другие VPN работают, а ваш нет — оператор, вероятно, режет адреса вашего российского хостера: возьмите VPS у другого российского хостера, перенесите настройки (шаг 3) и поменяйте DNS-запись `A`. Ссылки у людей менять не придется. Если не работает вообще ничего — у оператора, скорее всего, режим «белых списков»; ждать или использовать Wi‑Fi.
3. **На российском сервере:**
   ```bash
   systemctl is-active xray
   journalctl -u xray --since "5 min ago" --no-pager | grep -v accepted | tail -20
   curl -s -m 15 -x socks5h://127.0.0.1:10808 https://ifconfig.me; echo
   ```

## Чего не делать (проверено на практике)

- **Reality** (маскировка под чужой сайт: microsoft, ya.ru, vk.com и т.п.) — мобильные операторы и фильтры на выходе из дата-центров его режут. Используйте свой домен с настоящим сертификатом, как в этой инструкции.
- **Простой проброс портов** (iptables DNAT) с российского сервера на зарубежный — режется.
- **VLESS без шифрования** между серверами — новые версии Xray его не запускают. Shadowsocks 2022 проходит.
- **«Российские сайты напрямую» на сервере** (маршрутизация по geosite/geoip) — в простом варианте с `IPIfNonMatch` у нас сломала все сайты. Если очень нужно — включайте только аккуратно, на тестовом порту, с `IPOnDemand` и правилом «заблокированные сайты выше российских».
- **Прокси в окружении сервера.** Если в `~/.bashrc` прописан `HTTPS_PROXY`, все `curl`-проверки начнут врать — уберите.
- **Не пересылайте никому** токен бота, ключ Shadowsocks и ссылки других пользователей. Каждому человеку — свой ключ.

## Возможные улучшения

- Второй IP или второй зарубежный сервер как запасной выход — на случай блокировки основного.
- Транспорт XHTTP вместо TCP, если начнутся «заморозки» соединений (потребует обновить ссылки у всех).
