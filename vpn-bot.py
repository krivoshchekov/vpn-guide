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
