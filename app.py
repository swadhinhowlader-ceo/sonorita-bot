"""
Sonorita AI Telegram Bot - CLEAN VERSION
"""
import os, json, time, sqlite3, requests, re
from datetime import datetime, timedelta
from flask import Flask, request, jsonify

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8652318426:AAHug3Gjns1JMRDMQ9hg6VHQsMBMbKVbwDk")

API_KEYS = {
    "openrouter": [os.environ.get(f"OPENROUTER_KEY_{i}", "") for i in range(1,5)],
    "groq": [os.environ.get(f"GROQ_KEY_{i}", "") for i in range(1,5)],
    "openai": [os.environ.get("OPENAI_KEY", "")],
    "gemini": [os.environ.get("GEMINI_KEY", "")],
    "huggingface": [os.environ.get("HUGGINGFACE_KEY", "")],
}

SYSTEM_PROMPT = "You are Sonorita, a helpful AI assistant. Reply in Bengali or English."

DB = "sonorita.db"
def init_db():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS conversations (id INTEGER PRIMARY KEY, user_id INTEGER, role TEXT, content TEXT, ts REAL)")
    c.execute("CREATE TABLE IF NOT EXISTS reminders (id INTEGER PRIMARY KEY, user_id INTEGER, message TEXT, remind_at REAL, chat_id INTEGER, is_sent INTEGER DEFAULT 0)")
    conn.commit()
    conn.close()
def db(query, params=()):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute(query, params)
    conn.commit()
    r = c.fetchall()
    conn.close()
    return r
init_db()

def call_ai(prompt, user_id=None):
    messages = [{"role":"system","content":SYSTEM_PROMPT}]
    if user_id:
        for role, content in reversed(db("SELECT role,content FROM conversations WHERE user_id=? ORDER BY ts DESC LIMIT 10",(user_id,))):
            messages.append({"role":role,"content":content})
    messages.append({"role":"user","content":prompt})
    
    providers = [
        ("openrouter","https://openrouter.ai/api/v1/chat/completions","anthropic/claude-3.5-sonnet"),
        ("groq","https://api.groq.com/openai/v1/chat/completions","llama3-70b-8192"),
        ("openai","https://api.openai.com/v1/chat/completions","gpt-4o-mini"),
    ]
    for prov, url, model in providers:
        keys = [k for k in API_KEYS[prov] if k]
        for key in keys:
            try:
                body = json.dumps({"model":model,"messages":messages,"max_tokens":2048})
                h = {"Authorization":f"Bearer {key}","Content-Type":"application/json"}
                r = requests.post(url,headers=h,data=body,timeout=30)
                r.raise_for_status()
                resp = r.json()["choices"][0]["message"]["content"]
                if user_id:
                    db("INSERT INTO conversations (user_id,role,content,ts) VALUES (?,?,?,?)",(user_id,"user",prompt,time.time()))
                    db("INSERT INTO conversations (user_id,role,content,ts) VALUES (?,?,?,?)",(user_id,"assistant",resp,time.time()))
                return resp
            except Exception as e:
                print(f"[{prov}] Error: {e}")
                continue
    return "⚠️ API key missing! Set OPENROUTER_KEY_1 on Render."

def send_tg(chat_id, text):
    """Send message to Telegram with error logging."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={"chat_id": chat_id, "text": text[:4096]}, timeout=10)
        print(f"[TG] Send to {chat_id}: {r.status_code} {r.text[:100]}")
        return r.ok
    except Exception as e:
        print(f"[TG] Send error: {e}")
        return False

def parse_reminder(text):
    patterns = [(r'(\d+)\s*(minute|min|মিনিট)','minutes'),(r'(\d+)\s*(hour|ghonta|ঘণ্টা)','hours')]
    for pat, unit in patterns:
        m = re.search(pat, text, re.I)
        if m:
            n = int(m.group(1))
            msg = re.sub(pat,'',text,flags=re.I)
            msg = re.sub(r'remind|reminder|dao|dibo','',msg,flags=re.I).strip() or f"{n} {unit} reminder"
            d = timedelta(**{unit:n})
            return {"time":datetime.now()+d,"message":msg,"amount":n,"unit":unit}
    return None

app = Flask(__name__)

@app.route('/')
def home():
    return jsonify({"status":"running","bot":"Sonorita AI"})

@app.route('/health')
def health():
    return jsonify({"ok":True})

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.get_json()
        print(f"[WEBHOOK] Received: {json.dumps(data)[:200]}")
        
        if 'message' in data:
            msg = data['message']
            cid = msg['chat']['id']
            uid = msg['from']['id']
            text = msg.get('text', '')
            
            print(f"[WEBHOOK] From {uid}: {text}")
            
            if text:
                # Handle commands
                low = text.lower().strip()
                
                if low in ['/start', 'start', 'help', '/help']:
                    resp = "🤖 Sonorita Bot Active!\n\nCommands:\n• Just chat = AI responds\n• research [topic] = deep research\n• 10 minute pore reminder dao = set reminder"
                    send_tg(cid, resp)
                    return jsonify({"ok":True})
                
                # Reminder
                if any(w in low for w in ['remind','reminder','মিনিট পর']):
                    p = parse_reminder(text)
                    if p:
                        db("INSERT INTO reminders (user_id,message,remind_at,chat_id) VALUES (?,?,?,?)",(uid,p["message"],p["time"].timestamp(),cid))
                        send_tg(cid, f"⏰ {p['amount']} {p['unit']} pore reminder!")
                    else:
                        send_tg(cid, "⏰ Format: '10 minute pore reminder dao'")
                    return jsonify({"ok":True})
                
                # Research
                if low.startswith('research ') or low.startswith('search '):
                    q = text.split(' ',1)[1]
                    try:
                        r = requests.get(f"https://api.duckduckgo.com/?q={q}&format=json",timeout=10).json()
                        results = [r.get("Abstract","")] + [t.get("Text","") for t in r.get("RelatedTopics",[])[:3] if isinstance(t,dict)]
                        search_text = "\n".join([x for x in results if x])[:1000]
                        resp = call_ai(f"Research on '{q}':\n{search_text}\nSummarize.", uid)
                    except:
                        resp = "Search error."
                    send_tg(cid, resp)
                    return jsonify({"ok":True})
                
                # AI Chat
                resp = call_ai(text, uid)
                print(f"[WEBHOOK] AI response: {resp[:100]}")
                send_tg(cid, resp)
        
        return jsonify({"ok":True})
    except Exception as e:
        print(f"[WEBHOOK] Error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/check-reminders')
def check_rems():
    now = time.time()
    for rid, uid, msg, cid in db("SELECT id,user_id,message,chat_id FROM reminders WHERE remind_at<=? AND is_sent=0",(now,)):
        try:
            send_tg(cid, f"⏰ REMINDER: {msg}")
            db("UPDATE reminders SET is_sent=1 WHERE id=?",(rid,))
        except: pass
    return jsonify({"checked":True})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    print(f"🤖 Sonorita Bot starting on port {port}")
    webhook_url = os.environ.get("WEBHOOK_URL","")
    if webhook_url:
        try:
            requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook",json={"url":f"{webhook_url}/webhook"},timeout=10)
            print(f"✅ Webhook: {webhook_url}/webhook")
        except: pass
    # Self-ping
    import threading
    def ping():
        while True:
            time.sleep(600)
            try: requests.get(f"https://sonorita-bot.onrender.com/health",timeout=10)
            except: pass
    threading.Thread(target=ping,daemon=True).start()
    
    app.run(host='0.0.0.0', port=port)
