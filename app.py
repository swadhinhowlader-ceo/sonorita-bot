"""
Sonorita Telegram Bot - PRODUCTION VERSION
"""
import os, json, time, sqlite3, requests, re, sys
from datetime import datetime, timedelta
from flask import Flask, request, jsonify

# ═══ CONFIG ═══
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8652318426:AAHug3Gjns1JMRDMQ9hg6VHQsMBMbKVbwDk")
TG_API = f"https://api.telegram.org/bot{TOKEN}"

# Log config on start
print(f"🤖 Bot starting...", flush=True)
print(f"📡 Token set: {bool(TOKEN and len(TOKEN) > 10)}", flush=True)
print(f"🔑 OPENROUTER_KEY_1: {'SET' if os.environ.get('OPENROUTER_KEY_1') else 'NOT SET'}", flush=True)
print(f"🔑 GROQ_KEY_1: {'SET' if os.environ.get('GROQ_KEY_1') else 'NOT SET'}", flush=True)
sys.stdout.flush()

# ═══ FLASK ═══
app = Flask(__name__)

# ═══ DATABASE ═══
def init_db():
    try:
        conn = sqlite3.connect("bot.db")
        c = conn.cursor()
        c.execute("CREATE TABLE IF NOT EXISTS chat (id INTEGER PRIMARY KEY AUTOINCREMENT, uid INTEGER, role TEXT, msg TEXT, ts REAL)")
        c.execute("CREATE TABLE IF NOT EXISTS remind (id INTEGER PRIMARY KEY AUTOINCREMENT, uid INTEGER, msg TEXT, at REAL, cid INTEGER, done INTEGER DEFAULT 0)")
        conn.commit()
        conn.close()
        print("✅ DB initialized", flush=True)
    except Exception as e:
        print(f"❌ DB error: {e}", flush=True)

init_db()

def sql(q, p=()):
    try:
        conn = sqlite3.connect("bot.db")
        c = conn.cursor()
        c.execute(q, p)
        conn.commit()
        r = c.fetchall()
        conn.close()
        return r
    except Exception as e:
        print(f"SQL error: {e}", flush=True)
        return []

# ═══ SEND MESSAGE ═══
def send_msg(cid, text):
    """Send message to Telegram - always works."""
    try:
        r = requests.post(f"{TG_API}/sendMessage", json={
            "chat_id": cid, 
            "text": str(text)[:4096]
        }, timeout=15)
        print(f"[SEND] → {cid}: {r.status_code}", flush=True)
        return r.ok
    except Exception as e:
        print(f"[SEND] Error: {e}", flush=True)
        return False

# ═══ AI CALL ═══
def ask_ai(prompt, uid=None):
    """Call AI with fallback. Returns text or error message."""
    msgs = [{"role": "system", "content": "You are Sonorita, a helpful AI assistant. Reply in Bengali or English."}]
    
    # Add history
    if uid:
        for role, content in reversed(sql("SELECT role,msg FROM chat WHERE uid=? ORDER BY ts DESC LIMIT 10", (uid,))):
            msgs.append({"role": role, "content": content})
    msgs.append({"role": "user", "content": prompt})
    
    # Try providers
    providers = [
        ("openrouter", "https://openrouter.ai/api/v1/chat/completions", "meta-llama/llama-3.1-8b-instruct:free"),
        ("groq", "https://api.groq.com/openai/v1/chat/completions", "llama3-8b-8192"),
        ("openai", "https://api.openai.com/v1/chat/completions", "gpt-4o-mini"),
    ]
    
    for name, url, model in providers:
        key = os.environ.get(f"{name.upper()}_KEY_1") or os.environ.get(f"{name.upper()}_KEY")
        if not key:
            continue
        try:
            body = json.dumps({"model": model, "messages": msgs, "max_tokens": 2048})
            headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
            r = requests.post(url, headers=headers, data=body, timeout=30)
            if r.ok:
                resp = r.json()["choices"][0]["message"]["content"]
                # Save to history
                if uid:
                    sql("INSERT INTO chat (uid,role,msg,ts) VALUES (?,?,?,?)", (uid, "user", prompt, time.time()))
                    sql("INSERT INTO chat (uid,role,msg,ts) VALUES (?,?,?,?)", (uid, "assistant", resp, time.time()))
                print(f"[AI] {name} success!", flush=True)
                return resp
            else:
                print(f"[AI] {name} failed: {r.status_code}", flush=True)
        except Exception as e:
            print(f"[AI] {name} error: {e}", flush=True)
            continue
    
    return "⚠️ No AI API key found! Add OPENROUTER_KEY_1 on Render dashboard."

# ═══ REMINDER ═══
def parse_time(text):
    for pat, unit in [(r'(\d+)\s*(?:minute|min|মিনিট)', 'minutes'), (r'(\d+)\s*(?:hour|ghonta|ঘণ্টা)', 'hours')]:
        m = re.search(pat, text, re.I)
        if m:
            n = int(m.group(1))
            clean = re.sub(pat, '', text, flags=re.I)
            clean = re.sub(r'remind|reminder|dao|dibo|মনে|করিয়ে', '', clean, flags=re.I).strip()
            if not clean:
                clean = f"{n} {unit} reminder"
            return {"at": datetime.now() + timedelta(**{unit: n}), "msg": clean, "n": n, "unit": unit}
    return None

# ═══ ROUTES ═══
@app.route("/")
def index():
    return jsonify({"status": "ok", "bot": "Sonorita AI"})

@app.route("/health")
def health():
    return jsonify({"ok": True, "ts": time.time()})

@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.get_json(force=True)
        
        if not data or "message" not in data:
            return jsonify({"ok": True})
        
        msg = data["message"]
        cid = msg["chat"]["id"]
        uid = msg["from"]["id"]
        text = msg.get("text", "")
        
        if not text:
            send_msg(cid, "🤖 I can only read text messages.")
            return jsonify({"ok": True})
        
        print(f"[MSG] User {uid}: {text}", flush=True)
        low = text.lower().strip()
        
        # /start or help
        if low in ["/start", "start", "hi", "hello", "হ্যালো", "/help", "help"]:
            send_msg(cid, "🤖 Sonorita Bot Active!\n\n"
                "Just type anything = AI chat\n"
                "research [topic] = web research\n"
                "10 minute pore reminder dao = set reminder")
            return jsonify({"ok": True})
        
        # Reminder
        if "remind" in low or "মিনিট পর" in low or "মনে করিয়ে" in low:
            p = parse_time(text)
            if p:
                sql("INSERT INTO remind (uid,msg,at,cid) VALUES (?,?,?,?)", (uid, p["msg"], p["at"].timestamp(), cid))
                send_msg(cid, f"⏰ Reminder set! {p['n']} {p['unit']} pore: \"{p['msg']}\"")
            else:
                send_msg(cid, "⏰ Example: '10 minute pore reminder dao'")
            return jsonify({"ok": True})
        
        # Research
        if low.startswith("research ") or low.startswith("search "):
            q = text.split(" ", 1)[1] if " " in text else text
            try:
                sr = requests.get(f"https://api.duckduckgo.com/?q={q}&format=json&no_html=1", timeout=10).json()
                results = []
                if sr.get("Abstract"):
                    results.append(sr["Abstract"])
                for t in sr.get("RelatedTopics", [])[:3]:
                    if isinstance(t, dict) and t.get("Text"):
                        results.append(t["Text"])
                search_data = "\n".join(results)[:1500]
                if search_data:
                    resp = ask_ai(f"Research: {q}\n\n{search_data}\n\nSummarize.", uid)
                else:
                    resp = ask_ai(f"Research and explain: {q}", uid)
            except:
                resp = ask_ai(f"Research and explain: {q}", uid)
            send_msg(cid, resp)
            return jsonify({"ok": True})
        
        # Default: AI chat
        resp = ask_ai(text, uid)
        send_msg(cid, resp)
        
        return jsonify({"ok": True})
        
    except Exception as e:
        print(f"[WEBHOOK] Error: {e}", flush=True)
        return jsonify({"error": str(e)}), 500

@app.route("/check-reminders")
def check_reminders():
    now = time.time()
    for rid, uid, msg, cid in sql("SELECT id,uid,msg,cid FROM remind WHERE at<=? AND done=0", (now,)):
        send_msg(cid, f"⏰ REMINDER: {msg}")
        sql("UPDATE remind SET done=1 WHERE id=?", (rid,))
    return jsonify({"checked": True})

# ═══ START ═══
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    print(f"🚀 Running on port {port}", flush=True)
    
    # Set webhook
    try:
        r = requests.get(f"{TG_API}/getWebhookInfo", timeout=10)
        info = r.json().get("result", {})
        current_url = info.get("url", "")
        target_url = "https://sonorita-bot.onrender.com/webhook"
        
        if current_url != target_url:
            requests.get(f"{TG_API}/setWebhook?url={target_url}", timeout=10)
            print(f"✅ Webhook set: {target_url}", flush=True)
        else:
            print(f"✅ Webhook already set: {current_url}", flush=True)
    except Exception as e:
        print(f"Webhook error: {e}", flush=True)
    
    # Keep-alive ping
    import threading
    def keep_alive():
        while True:
            time.sleep(600)
            try:
                requests.get("https://sonorita-bot.onrender.com/health", timeout=10)
            except:
                pass
    threading.Thread(target=keep_alive, daemon=True).start()
    
    app.run(host="0.0.0.0", port=port)
