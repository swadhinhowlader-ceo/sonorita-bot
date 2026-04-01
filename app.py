"""
Sonorita AI Telegram Bot
Multi-API fallback: OpenRouter → Groq → OpenAI → Gemini → HuggingFace
Features: Research, Reminders, Skills, Web Interface
"""
import os
import json
import time
import sqlite3
import threading
import requests
import re
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, render_template_string

# ═══════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8652318426:AAHug3Gjns1JMRDMQ9hg6VHQsMBMbKVbwDk")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")

# API Keys (multiple per provider for fallback)
API_KEYS = {
    "openrouter": [
        os.getenv("OPENROUTER_KEY_1", ""),
        os.getenv("OPENROUTER_KEY_2", ""),
        os.getenv("OPENROUTER_KEY_3", ""),
        os.getenv("OPENROUTER_KEY_4", ""),
    ],
    "groq": [
        os.getenv("GROQ_KEY_1", ""),
        os.getenv("GROQ_KEY_2", ""),
        os.getenv("GROQ_KEY_3", ""),
        os.getenv("GROQ_KEY_4", ""),
    ],
    "openai": [os.getenv("OPENAI_KEY", "")],
    "gemini": [os.getenv("GEMINI_KEY", "")],
    "huggingface": [os.getenv("HUGGINGFACE_KEY", "")],
}

# API Endpoints & Models
API_CONFIG = {
    "openrouter": {
        "url": "https://openrouter.ai/api/v1/chat/completions",
        "model": "anthropic/claude-3.5-sonnet",
        "headers": lambda key: {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    },
    "groq": {
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "model": "llama3-70b-8192",
        "headers": lambda key: {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    },
    "openai": {
        "url": "https://api.openai.com/v1/chat/completions",
        "model": "gpt-4o-mini",
        "headers": lambda key: {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    },
    "gemini": {
        "url": "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent",
        "model": "gemini-1.5-flash",
        "headers": lambda key: {"Content-Type": "application/json"},
    },
    "huggingface": {
        "url": "https://api-inference.huggingface.co/models/mistralai/Mistral-7B-Instruct-v0.2",
        "model": "mistral-7b",
        "headers": lambda key: {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    },
}

PROVIDER_ORDER = ["openrouter", "groq", "openai", "gemini", "huggingface"]

SYSTEM_PROMPT = """You are Sonorita, a helpful, friendly AI assistant created by Swadhin.
You can speak both Bengali (Bangla) and English. Reply in the same language the user uses.
Be concise, helpful, and engaging. You can do research, answer questions, help with code,
write documents, set reminders, and much more. You are always learning and improving."""

# ═══════════════════════════════════════════
# DATABASE
# ═══════════════════════════════════════════

DB_PATH = "sonorita.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Conversations
    c.execute("""CREATE TABLE IF NOT EXISTS conversations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        role TEXT,
        content TEXT,
        timestamp REAL
    )""")
    
    # Reminders
    c.execute("""CREATE TABLE IF NOT EXISTS reminders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        message TEXT,
        remind_at REAL,
        chat_id INTEGER,
        is_sent INTEGER DEFAULT 0
    )""")
    
    # User preferences
    c.execute("""CREATE TABLE IF NOT EXISTS user_prefs (
        user_id INTEGER,
        key TEXT,
        value TEXT,
        PRIMARY KEY (user_id, key)
    )""")
    
    # Skills
    c.execute("""CREATE TABLE IF NOT EXISTS skills (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE,
        description TEXT,
        code TEXT,
        is_active INTEGER DEFAULT 1
    )""")
    
    conn.commit()
    conn.close()

def db_execute(query, params=()):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(query, params)
    conn.commit()
    result = c.fetchall()
    conn.close()
    return result

def db_fetch(query, params=()):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(query, params)
    result = c.fetchall()
    conn.close()
    return result

init_db()

# ═══════════════════════════════════════════
# AI ENGINE (Multi-API Fallback)
# ═══════════════════════════════════════════

def call_ai(prompt, user_id=None, conversation_history=None):
    """Call AI with fallback. Tries each provider until one succeeds."""
    
    # Build messages
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    
    # Add conversation history
    if user_id:
        history = db_fetch(
            "SELECT role, content FROM conversations WHERE user_id = ? ORDER BY timestamp DESC LIMIT 20",
            (user_id,)
        )
        for role, content in reversed(history):
            messages.append({"role": role, "content": content})
    
    messages.append({"role": "user", "content": prompt})
    
    # Try each provider
    for provider in PROVIDER_ORDER:
        config = API_CONFIG[provider]
        keys = [k for k in API_KEYS[provider] if k]  # Filter empty keys
        
        for key in keys:
            try:
                response = _call_provider(provider, config, key, messages)
                if response:
                    # Save to history
                    if user_id:
                        db_execute(
                            "INSERT INTO conversations (user_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
                            (user_id, "user", prompt, time.time())
                        )
                        db_execute(
                            "INSERT INTO conversations (user_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
                            (user_id, "assistant", response, time.time())
                        )
                    return response
            except Exception as e:
                print(f"[{provider}] Error: {e}")
                continue  # Try next key
    
    return "⚠️ Shob AI providers fail hoyeche. API keys check koro."

def _call_provider(provider, config, key, messages):
    """Call a specific AI provider."""
    headers = config["headers"](key)
    
    if provider == "gemini":
        # Gemini has different format
        contents = []
        for msg in messages:
            if msg["role"] == "system":
                contents.append({"role": "user", "parts": [{"text": msg["content"]}]})
            else:
                contents.append({"role": msg["role"], "parts": [{"text": msg["content"]}]})
        
        body = json.dumps({
            "contents": contents,
            "generationConfig": {"temperature": 0.7, "maxOutputTokens": 4096}
        })
        url = f"{config['url']}?key={key}"
    else:
        body = json.dumps({
            "model": config["model"],
            "messages": messages,
            "max_tokens": 4096,
            "temperature": 0.7
        })
        url = config["url"]
    
    resp = requests.post(url, headers=headers, data=body, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    
    # Parse response
    if provider == "gemini":
        return data["candidates"][0]["content"]["parts"][0]["text"]
    elif provider == "huggingface":
        return data[0]["generated_text"][-1]["content"] if isinstance(data, list) else data.get("generated_text", "")
    else:
        return data["choices"][0]["message"]["content"]

# ═══════════════════════════════════════════
# WEB SEARCH (Research)
# ═══════════════════════════════════════════

def web_search(query):
    """Search the web using DuckDuckGo."""
    try:
        url = f"https://api.duckduckgo.com/?q={query}&format=json&no_html=1&skip_disambig=1"
        resp = requests.get(url, timeout=10)
        data = resp.json()
        
        results = []
        if data.get("Abstract"):
            results.append(data["Abstract"])
        for topic in data.get("RelatedTopics", [])[:5]:
            if isinstance(topic, dict) and topic.get("Text"):
                results.append(topic["Text"])
        
        return "\n".join(results) if results else "Search results pai ni."
    except Exception as e:
        return f"Search error: {e}"

def research_topic(topic):
    """Deep research: search + summarize."""
    search_results = web_search(topic)
    
    # Ask AI to summarize
    prompt = f"""Research results for "{topic}":

{search_results}

Based on these results, provide a comprehensive, well-organized summary. 
Include key facts, insights, and conclusions. Reply in the same language the topic is written in."""
    
    return call_ai(prompt)

# ═══════════════════════════════════════════
# REMINDER SYSTEM
# ═══════════════════════════════════════════

def parse_reminder(text):
    """Parse reminder from text like '10 minute pore reminder dao'."""
    patterns = [
        (r'(\d+)\s*(minute|min|মিনিট)', 'minutes'),
        (r'(\d+)\s*(hour|ghonta|ঘণ্টা)', 'hours'),
        (r'(\d+)\s*(day|din|দিন)', 'days'),
        (r'(\d+)\s*(second|sec|সেকেন্ড)', 'seconds'),
    ]
    
    for pattern, unit in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            amount = int(match.group(1))
            reminder_text = re.sub(pattern, '', text, flags=re.IGNORECASE)
            reminder_text = re.sub(r'remind|reminder|dao|dibo|mone koro', '', reminder_text, flags=re.IGNORECASE).strip()
            
            if not reminder_text:
                reminder_text = f"{amount} {unit} reminder"
            
            delta = timedelta()
            if unit == 'minutes':
                delta = timedelta(minutes=amount)
            elif unit == 'hours':
                delta = timedelta(hours=amount)
            elif unit == 'days':
                delta = timedelta(days=amount)
            elif unit == 'seconds':
                delta = timedelta(seconds=amount)
            
            return {
                "time": datetime.now() + delta,
                "message": reminder_text,
                "amount": amount,
                "unit": unit
            }
    
    return None

def set_reminder(user_id, chat_id, text):
    """Set a reminder."""
    parsed = parse_reminder(text)
    if not parsed:
        return "⏰ Reminder set korte parlam na. Example: '10 minute pore reminder dao'"
    
    remind_at = parsed["time"].timestamp()
    db_execute(
        "INSERT INTO reminders (user_id, message, remind_at, chat_id) VALUES (?, ?, ?, ?)",
        (user_id, parsed["message"], remind_at, chat_id)
    )
    
    return f"⏰ Reminder set! {parsed['amount']} {parsed['unit']} pore: \"{parsed['message']}\""

def check_reminders(bot_url):
    """Check and send due reminders. Called by cron."""
    now = time.time()
    due = db_fetch(
        "SELECT id, user_id, message, chat_id FROM reminders WHERE remind_at <= ? AND is_sent = 0",
        (now,)
    )
    
    for rem_id, user_id, message, chat_id in due:
        # Send reminder via Telegram
        try:
            url = f"{bot_url}/sendMessage"
            requests.post(url, json={
                "chat_id": chat_id,
                "text": f"⏰ REMINDER: {message}"
            }, timeout=10)
            db_execute("UPDATE reminders SET is_sent = 1 WHERE id = ?", (rem_id,))
        except Exception as e:
            print(f"Reminder send error: {e}")

# ═══════════════════════════════════════════
# SKILLS SYSTEM
# ═══════════════════════════════════════════

def add_skill(name, description, code):
    """Add a new skill."""
    try:
        db_execute(
            "INSERT OR REPLACE INTO skills (name, description, code, is_active) VALUES (?, ?, ?, 1)",
            (name, description, code)
        )
        return f"🧩 Skill '{name}' added!"
    except Exception as e:
        return f"Skill add error: {e}"

def list_skills():
    """List all skills."""
    skills = db_fetch("SELECT name, description, is_active FROM skills")
    if not skills:
        return "No skills installed."
    
    result = "🧩 Installed Skills:\n"
    for name, desc, active in skills:
        status = "🟢" if active else "🔴"
        result += f"{status} {name}: {desc}\n"
    return result

def execute_skill(name, input_text):
    """Execute a skill."""
    skill = db_fetch("SELECT code FROM skills WHERE name = ? AND is_active = 1", (name,))
    if not skill:
        return f"Skill '{name}' not found or inactive."
    
    try:
        # Safe execution (sandboxed)
        local_vars = {"input": input_text, "result": ""}
        exec(skill[0][0], {"__builtins__": {}}, local_vars)
        return local_vars.get("result", "Skill executed but no result.")
    except Exception as e:
        return f"Skill execution error: {e}"

# ═══════════════════════════════════════════
# DOCUMENT GENERATION
# ═══════════════════════════════════════════

def generate_document(doc_type, topic):
    """Generate various types of documents."""
    prompts = {
        "report": f"Write a detailed report on: {topic}. Include introduction, findings, analysis, and conclusion.",
        "essay": f"Write a well-structured essay on: {topic}. Include introduction, body paragraphs, and conclusion.",
        "summary": f"Write a concise summary of: {topic}. Key points only.",
        "letter": f"Write a professional letter about: {topic}.",
        "email": f"Write a professional email about: {topic}.",
        "code": f"Write production-ready code for: {topic}. Include comments.",
        "plan": f"Create a detailed project plan for: {topic}. Include milestones, tasks, and timeline.",
    }
    
    prompt = prompts.get(doc_type, f"Write a document about: {topic}")
    return call_ai(prompt)

# ═══════════════════════════════════════════
# COMMAND HANDLER
# ═══════════════════════════════════════════

def handle_command(text, user_id, chat_id):
    """Handle bot commands."""
    lower = text.lower().strip()
    
    # Reminder
    if any(word in lower for word in ['remind', 'reminder', 'মনে করিয়ে দাও', 'মিনিট পর']):
        return set_reminder(user_id, chat_id, text)
    
    # Research
    if lower.startswith('research ') or lower.startswith('খোঁজো ') or lower.startswith('বিস্তারিত '):
        topic = text.split(' ', 1)[1] if ' ' in text else text
        return research_topic(topic)
    
    # Document generation
    if lower.startswith('doc ') or lower.startswith('লেখো '):
        parts = text.split(' ', 2)
        if len(parts) >= 3:
            doc_type = parts[1]
            topic = parts[2]
            return generate_document(doc_type, topic)
        return "📝 Usage: doc [type] [topic]. Types: report, essay, summary, letter, email, code, plan"
    
    # Skills
    if lower.startswith('skill add '):
        return "🧩 Skill adding: Use web interface or send code."
    if lower == 'skills' or lower == 'শিল্প':
        return list_skills()
    
    # Search
    if lower.startswith('search ') or lower.startswith('খোঁজো '):
        query = text.split(' ', 1)[1]
        return web_search(query)
    
    # Help
    if lower in ['help', 'সাহায্য', '/help', '/start']:
        return """🤖 **Sonorita AI Bot**

**Commands:**
• Just chat — AI will respond
• `research [topic]` — Deep research
• `search [query]` — Web search
• `doc [type] [topic]` — Generate documents
• `10 minute pore reminder dao` — Set reminder
• `skills` — List installed skills
• `skill add [name]` — Add a skill

**Document Types:** report, essay, summary, letter, email, code, plan

**Supported Languages:** বাংলা + English

**API Providers:** OpenRouter → Groq → OpenAI → Gemini → HuggingFace (auto-fallback)"""
    
    # Default: AI chat
    return None  # Will be handled by AI

# ═══════════════════════════════════════════
# TELEGRAM BOT (Webhook Mode)
# ═══════════════════════════════════════════

app = Flask(__name__)

@app.route('/')
def home():
    return render_template_string("""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Sonorita AI Bot</title>
        <style>
            body { font-family: Arial; background: #0A0A0F; color: white; padding: 40px; text-align: center; }
            h1 { color: #8B5CF6; }
            .status { color: #4CAF50; }
            .features { text-align: left; max-width: 600px; margin: 20px auto; }
            .feature { padding: 10px; background: #151520; margin: 5px 0; border-radius: 8px; }
        </style>
    </head>
    <body>
        <h1>🤖 Sonorita AI Bot</h1>
        <p class="status">✅ Bot is running!</p>
        <div class="features">
            <div class="feature">🧠 Multi-API AI (OpenRouter, Groq, OpenAI, Gemini, HuggingFace)</div>
            <div class="feature">🔍 Deep Research & Web Search</div>
            <div class="feature">⏰ Reminders (any time)</div>
            <div class="feature">📝 Document Generation</div>
            <div class="feature">🧩 Skills & Plugins</div>
            <div class="feature">🌐 Bengali + English Support</div>
        </div>
        <p>Use the Telegram bot: <a href="https://t.me/YOUR_BOT_USERNAME" style="color: #06B6D4;">@SonoritaBot</a></p>
    </body>
    </html>
    """)

@app.route('/webhook', methods=['POST'])
def webhook():
    """Handle Telegram webhook."""
    data = request.get_json()
    
    if 'message' in data:
        msg = data['message']
        chat_id = msg['chat']['id']
        user_id = msg['from']['id']
        text = msg.get('text', '')
        
        if text:
            # Handle command first
            response = handle_command(text, user_id, chat_id)
            
            if response is None:
                # Default: AI chat
                response = call_ai(text, user_id=user_id)
            
            # Send response
            send_message(chat_id, response)
    
    return jsonify({"ok": True})

@app.route('/chat', methods=['POST'])
def web_chat():
    """Web interface chat endpoint."""
    data = request.get_json()
    text = data.get('message', '')
    user_id = data.get('user_id', 'web_user')
    
    response = handle_command(text, user_id, 0)
    if response is None:
        response = call_ai(text, user_id=user_id)
    
    return jsonify({"response": response})

@app.route('/check-reminders', methods=['GET', 'POST'])
def check_reminders_endpoint():
    """Cron endpoint to check reminders."""
    bot_url = f"https://api.telegram.org/bot{BOT_TOKEN}"
    check_reminders(bot_url)
    return jsonify({"status": "checked"})

@app.route('/health')
def health():
    return jsonify({"status": "healthy", "timestamp": time.time()})

def send_message(chat_id, text):
    """Send message to Telegram."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    
    # Split long messages
    if len(text) > 4096:
        chunks = [text[i:i+4096] for i in range(0, len(text), 4096)]
        for chunk in chunks:
            requests.post(url, json={
                "chat_id": chat_id,
                "text": chunk,
                "parse_mode": "Markdown"
            }, timeout=10)
    else:
        requests.post(url, json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown"
        }, timeout=10)

def set_webhook():
    """Set Telegram webhook."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook"
    webhook_url = f"{WEBHOOK_URL}/webhook" if WEBHOOK_URL else ""
    if webhook_url:
        resp = requests.post(url, json={"url": webhook_url})
        print(f"Webhook set: {resp.json()}")

# ═══════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════

if __name__ == '__main__':
    print("🤖 Sonorita AI Bot starting...")
    print(f"📡 Port: 8080")
    print(f"🔗 Bot Token: {BOT_TOKEN[:10]}...")
    
    # Set webhook on start
    set_webhook()
    
    # Run Flask app
    port = int(os.getenv("PORT", 8080))
    app.run(host='0.0.0.0', port=port, debug=False)
