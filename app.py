"""
Sonorita Bot - FAST VERSION (responds immediately)
"""
import os, json, time, sqlite3, requests, re, threading
from datetime import datetime, timedelta
from flask import Flask, request, jsonify

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8652318426:AAHug3Gjns1JMRDMQ9hg6VHQsMBMbKVbwDk")
TG = f"https://api.telegram.org/bot{TOKEN}"

app = Flask(__name__)

# DB
def init():
    try:
        c = sqlite3.connect("bot.db")
        c.cursor().execute("CREATE TABLE IF NOT EXISTS chat (id INTEGER PRIMARY KEY AUTOINCREMENT, uid INTEGER, role TEXT, msg TEXT, ts REAL)")
        c.cursor().execute("CREATE TABLE IF NOT EXISTS remind (id INTEGER PRIMARY KEY AUTOINCREMENT, uid INTEGER, msg TEXT, at REAL, cid INTEGER, done INTEGER DEFAULT 0)")
        c.commit(); c.close()
    except: pass
init()

def sql(q, p=()):
    try:
        c = sqlite3.connect("bot.db"); cur = c.cursor()
        cur.execute(q, p); c.commit()
        r = cur.fetchall(); c.close(); return r
    except: return []

# Send immediately (no timeout issues)
def send(cid, text):
    try:
        requests.post(f"{TG}/sendMessage", json={"chat_id": cid, "text": str(text)[:4096]}, timeout=5)
    except: pass

# AI call (background)
def ai(prompt, uid=None):
    msgs = [{"role":"system","content":"You are Sonorita, helpful AI assistant. Reply in Bengali or English."}]
    if uid:
        for r, m in reversed(sql("SELECT role,msg FROM chat WHERE uid=? ORDER BY ts DESC LIMIT 8",(uid,))):
            msgs.append({"role":r,"content":m})
    msgs.append({"role":"user","content":prompt})
    
    for name in ["OPENROUTER", "GROQ", "OPENAI"]:
        key = os.environ.get(f"{name}_KEY_1") or os.environ.get(f"{name}_KEY")
        if not key: continue
        url = {"OPENROUTER":"https://openrouter.ai/api/v1/chat/completions",
               "GROQ":"https://api.groq.com/openai/v1/chat/completions",
               "OPENAI":"https://api.openai.com/v1/chat/completions"}[name]
        model = {"OPENROUTER":"meta-llama/llama-3.1-8b-instruct:free",
                 "GROQ":"llama3-8b-8192","OPENAI":"gpt-4o-mini"}[name]
        try:
            r = requests.post(url, headers={"Authorization":f"Bearer {key}","Content-Type":"application/json"},
                            json={"model":model,"messages":msgs,"max_tokens":2048}, timeout=25)
            if r.ok:
                resp = r.json()["choices"][0]["message"]["content"]
                if uid:
                    sql("INSERT INTO chat (uid,role,msg,ts) VALUES (?,?,?,?)",(uid,"user",prompt,time.time()))
                    sql("INSERT INTO chat (uid,role,msg,ts) VALUES (?,?,?,?)",(uid,"assistant",resp,time.time()))
                return resp
        except: continue
    return "⚠️ AI API key not set! Add OPENROUTER_KEY_1 on Render."

# Background processor
def process_msg(cid, uid, text):
    low = text.lower().strip()
    
    if low in ["/start","start","hi","hello","হ্যালো","/help","help"]:
        send(cid, "🤖 Sonorita Bot Active!\n\nJust type = AI chat\nresearch [topic] = research\n10 min pore reminder dao = reminder")
        return
    
    if "remind" in low or "মিনিট পর" in low:
        for pat, unit in [(r'(\d+)\s*(?:minute|min|মিনিট)','minutes'),(r'(\d+)\s*(?:hour|ghonta|ঘণ্টা)','hours')]:
            m = re.search(pat, text, re.I)
            if m:
                n = int(m.group(1))
                msg = re.sub(pat,'',text,flags=re.I)
                msg = re.sub(r'remind|reminder|dao|dibo|মনে|করিয়ে','',msg,flags=re.I).strip() or f"{n} {unit} reminder"
                at = datetime.now() + timedelta(**{unit:n})
                sql("INSERT INTO remind (uid,msg,at,cid) VALUES (?,?,?,?)",(uid,msg,at.timestamp(),cid))
                send(cid, f"⏰ {n} {unit} pore: \"{msg}\"")
                return
        send(cid, "⏰ Example: '10 minute pore reminder dao'")
        return
    
    if low.startswith("research ") or low.startswith("search "):
        q = text.split(" ",1)[1] if " " in text else text
        try:
            sr = requests.get(f"https://api.duckduckgo.com/?q={q}&format=json&no_html=1",timeout=8).json()
            results = [sr.get("Abstract","")] + [t.get("Text","") for t in sr.get("RelatedTopics",[])[:3] if isinstance(t,dict)]
            data = "\n".join([x for x in results if x])[:1500]
            resp = ai(f"Research: {q}\n{data}\nSummarize.", uid) if data else ai(f"Explain: {q}", uid)
        except:
            resp = ai(f"Research: {q}", uid)
        send(cid, resp)
        return
    
    # Default: AI chat
    resp = ai(text, uid)
    send(cid, resp)

# Routes
@app.route("/")
def home(): return jsonify({"ok":True,"bot":"Sonorita"})

@app.route("/health")
def health(): return jsonify({"ok":True,"ts":time.time()})

@app.route("/webhook", methods=["POST"])
def webhook():
    """Respond immediately (200 OK), process in background."""
    try:
        data = request.get_json(silent=True)
        if data and "message" in data:
            msg = data["message"]
            cid = msg["chat"]["id"]
            uid = msg["from"]["id"]
            text = msg.get("text","")
            if text:
                # Process in background thread (webhook returns immediately)
                threading.Thread(target=process_msg, args=(cid, uid, text), daemon=True).start()
    except: pass
    return jsonify({"ok": True})  # Always return immediately

@app.route("/check-reminders")
def check():
    now = time.time()
    for rid, uid, msg, cid in sql("SELECT id,uid,msg,cid FROM remind WHERE at<=? AND done=0",(now,)):
        send(cid, f"⏰ REMINDER: {msg}")
        sql("UPDATE remind SET done=1 WHERE id=?",(rid,))
    return jsonify({"ok":True})

if __name__ == "__main__":
    port = int(os.environ.get("PORT",8080))
    # Set webhook
    try:
        r = requests.get(f"{TG}/getWebhookInfo",timeout=5)
        url = r.json().get("result",{}).get("url","")
        target = "https://sonorita-bot.onrender.com/webhook"
        if url != target:
            requests.get(f"{TG}/setWebhook?url={target}",timeout=5)
    except: pass
    # Keep alive
    def ping():
        while True:
            time.sleep(600)
            try: requests.get("https://sonorita-bot.onrender.com/health",timeout=5)
            except: pass
    threading.Thread(target=ping,daemon=True).start()
    app.run(host="0.0.0.0",port=port)
