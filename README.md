# Sonorita AI Telegram Bot

## Environment Variables (Set on Render)

```
TELEGRAM_BOT_TOKEN=8652318426:AAHug3Gjns1JMRDMQ9hg6VHQsMBMbKVbwDk
WEBHOOK_URL=https://your-app.onrender.com

# API Keys (multiple for fallback)
OPENROUTER_KEY_1=sk-...
OPENROUTER_KEY_2=sk-...
OPENROUTER_KEY_3=sk-...
OPENROUTER_KEY_4=sk-...

GROQ_KEY_1=gsk_...
GROQ_KEY_2=gsk_...
GROQ_KEY_3=gsk_...
GROQ_KEY_4=gsk_...

OPENAI_KEY=sk-...
GEMINI_KEY=AIza...
HUGGINGFACE_KEY=hf_...
```

## Deploy to Render

1. Push this repo to GitHub
2. Go to render.com → New Web Service
3. Connect GitHub repo
4. Set environment variables
5. Deploy!

## Cron-job.org Setup

1. Go to cron-job.org
2. Create new cron job
3. URL: https://your-app.onrender.com/check-reminders
4. Schedule: Every 1 minute
5. This keeps the bot alive and checks reminders
