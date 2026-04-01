"""
Sonorita AI Telegram Bot - CLEAN VERSION
Multi-API fallback: OpenRouter → Groq → OpenAI → Gemini → HuggingFace
"""
import os, json, time, sqlite3, threading, requests, re
from datetime import datetime, timedelta
from flask import Flask, request, jsonify

# ═══ CONFIG ═══
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8652318426:AAHug3Gjns1JMRDMQ9hg6VHQsMBMbKVbwDk")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "")

API_KEYS = {
    "openrouter": [os.environ.get(f"OPENROUTER_KEY_{i}", "") for i in range(1,5)],
    "groq": [os.environ.get(f"GROQ_KEY_{i}", "") for i in range(1,5)],
    "openai": [os.environ.get("OPENAI_KEY", "")],
    "gemini": [os.environ.get("GEMINI_KEY", "")],
    "huggingface": [os.environ.get("HUGGINGFACE_KEY", "")],
}

SYSTEM_PROMPT = "You are Sonorita, a helpful AI assistant by Swadhin. Reply in Bengali or English."

# ═══ DATABASE ═══
DB = "sonorita.db"
def init_db():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS conversations (id INTEGER PRIMARY KEY, user_id INTEGER, role TEXT, content TEXT, ts REAL)")
    c.execute("CREATE TABLE IF NOT EXISTS reminders (id INTEGER PRIMARY KEY, user_id INTEGER, message TEXT, remind_at REAL, chat_id INTEGER, is_sent INTEGER DEFAULT 0)")
    c.execute("CREATE TABLE IF NOT EXISTS skills (id INTEGER PRIMARY KEY, name TEXT UNIQUE, description TEXT, code TEXT, active INTEGER DEFAULT 1)")
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

# ═══ AI ENGINE ═══
def call_ai(prompt, user_id=None):
    messages = [{"role":"system","content":SYSTEM_PROMPT}]
    if user_id:
        for role, content in reversed(db("SELECT role,content FROM conversations WHERE user_id=? ORDER BY ts DESC LIMIT 20",(user_id,))):
            messages.append({"role":role,"content":content})
    messages.append({"role":"user","content":prompt})

    providers = [
        ("openrouter","https://openrouter.ai/api/v1/chat/completions","anthropic/claude-3.5-sonnet"),
        ("groq","https://api.groq.com/openai/v1/chat/completions","llama3-70b-8192"),
        ("openai","https://api.openai.com/v1/chat/completions","gpt-4o-mini"),
        ("gemini",None,None),
        ("huggingface","https://api-inference.huggingface.co/models/mistralai/Mistral-7B-Instruct-v0.2",None),
    ]

    for prov, url, model in providers:
        keys = [k for k in API_KEYS[prov] if k]
        for key in keys:
            try:
                if prov == "gemini":
                    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={key}"
                    contents = [{"role":"user","parts":[{"text":m["content"]}]} for m in messages]
                    body = json.dumps({"contents":contents,"generationConfig":{"maxOutputTokens":4096}})
                    r = requests.post(url,headers={"Content-Type":"application/json"},data=body,timeout=60)
                    r.raise_for_status()
                    resp = r.json()["candidates"][0]["content"]["parts"][0]["text"]
                else:
                    body = json.dumps({"model":model,"messages":messages,"max_tokens":4096})
                    h = {"Authorization":f"Bearer {key}","Content-Type":"application/json"}
                    r = requests.post(url,headers=h,data=body,timeout=60)
                    r.raise_for_status()
                    resp = r.json()["choices"][0]["message"]["content"]

                if user_id:
                    db("INSERT INTO conversations (user_id,role,content,ts) VALUES (?,?,?,?)",(user_id,"user",prompt,time.time()))
                    db("INSERT INTO conversations (user_id,role,content,ts) VALUES (?,?,?,?)",(user_id,"assistant",resp,time.time()))
                return resp
            except Exception as e:
                print(f"[{prov}] {e}")
                continue
    return "⚠️ All AI providers failed. Check API keys."

# ═══ REMINDERS ═══
def parse_reminder(text):
    patterns = [
        (r'(\d+)\s*(minute|min|মিনিট)','minutes'),
        (r'(\d+)\s*(hour|ghonta|ঘণ্টা)','hours'),
        (r'(\d+)\s*(day|din|দিন)','days'),
    ]
    for pat, unit in patterns:
        m = re.search(pat, text, re.I)
        if m:
            n = int(m.group(1))
            msg = re.sub(pat,'',text,flags=re.I)
            msg = re.sub(r'remind|reminder|dao|dibo','',msg,flags=re.I).strip() or f"{n} {unit} reminder"
            d = timedelta(**{unit:n})
            return {"time":datetime.now()+d,"message":msg,"amount":n,"unit":unit}
    return None

def set_reminder(uid, cid, text):
    p = parse_reminder(text)
    if not p: return "⏰ Format: '10 minute pore reminder dao'"
    db("INSERT INTO reminders (user_id,message,remind_at,chat_id) VALUES (?,?,?,?)",(uid,p["message"],p["time"].timestamp(),cid))
    return f"⏰ {p['amount']} {p['unit']} pore reminder: \"{p['message']}\""

def check_reminders():
    now = time.time()
    for rid, uid, msg, cid in db("SELECT id,user_id,message,chat_id FROM reminders WHERE remind_at<=? AND is_sent=0",(now,)):
        try:
            requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",json={"chat_id":cid,"text":f"⏰ REMINDER: {msg}"},timeout=10)
            db("UPDATE reminders SET is_sent=1 WHERE id=?",(rid,))
        except: pass

# ═══ COMMANDS ═══
def handle(text, uid, cid):
    low = text.lower()
    if any(w in low for w in ['remind','reminder','মিনিট পর']):
        return set_reminder(uid, cid, text)
    if low.startswith('research ') or low.startswith('search '):
        q = text.split(' ',1)[1]
        try:
            r = requests.get(f"https://api.duckduckgo.com/?q={q}&format=json",timeout=10).json()
            results = [r.get("Abstract","")] + [t.get("Text","") for t in r.get("RelatedTopics",[])[:5] if isinstance(t,dict)]
            search_text = "\n".join([x for x in results if x])
            return call_ai(f"Research on '{q}':\n{search_text}\nSummarize this.", uid) if search_text else "No results found."
        except: return "Search error."
    if low in ['help','সাহায্য','/help','/start']:
        return "🤖 Sonorita Bot\n\nJust chat = AI responds\nresearch [topic] = deep research\n10 minute pore reminder dao = set reminder\n\nBengali + English supported!"
    return None

# ═══ FLASK APP ═══
app = Flask(__name__)

@app.route('/')
def home():
    return jsonify({"status":"running","bot":"Sonorita AI","features":["chat","research","reminders","multi-api"]})

@app.route('/health')
def health():
    return jsonify({"ok":True,"ts":time.time()})

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    if 'message' in data:
        msg = data['message']
        cid, uid, text = msg['chat']['id'], msg['from']['id'], msg.get('text','')
        if text:
            resp = handle(text, uid, cid) or call_ai(text, uid)
            requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",json={"chat_id":cid,"text":resp[:4096]},timeout=10)
    return jsonify({"ok":True})

@app.route('/check-reminders', methods=['GET','POST'])
def check_rems():
    check_reminders()
    return jsonify({"checked":True})

# ═══ START ═══
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    print(f"🤖 Sonorita Bot on port {port}")
    # Set webhook
    webhook_url = os.environ.get("WEBHOOK_URL","")
    if webhook_url:
        try:
            requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook",json={"url":f"{webhook_url}/webhook"},timeout=10)
            print(f"✅ Webhook set: {webhook_url}/webhook")
        except Exception as e:
            print(f"Webhook error: {e}")
    app.run(host='0.0.0.0', port=port)
