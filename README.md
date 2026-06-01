# 🎙️ Voca Demy — AI-Powered Alexa Skill for Kids

An educational Alexa skill that helps children learn through AI-generated lessons, interactive quizzes, and word explanations — all via voice.

---

## ✨ Features

- 📖 **Document reading** — Alexa reads chunked lesson content aloud to the child
- 🧠 **Interactive quiz** — Multiple-choice questions (A/B/C/D) with voice answers
- 💡 **Word explanations** — Child can ask "what is [word]?" mid-lesson and get a simple AI explanation
- 🏆 **Streak & score tracking** — Progress saved per session to Supabase
- 📊 **AI-generated performance reports** — End-of-quiz report written by an LLM for parents
- ⏸️ **Pause & resume** — Full session state persistence via Alexa session attributes
- 🔁 **Repeat intent** — Child can ask Alexa to repeat any question or lesson chunk

---

## 🛠️ Tech Stack

| Layer | Technology |
|---|---|
| Voice interface | Amazon Alexa Skills Kit |
| Backend | Python (serverless HTTP handlers) |
| Deployment | Vercel (serverless functions) |
| Database | Supabase (PostgreSQL + REST API) |
| AI / LLM | OpenRouter API (Mistral, Gemma, LLaMA fallback chain) |

---

## 🗂️ Project Structure

```
vocademy/
├── api/
│   ├── alexa.py        # Main Alexa intent handler
│   └── quiz.py         # Quiz data API endpoint
├── vercel.json         # Vercel routing config
├── requirements.txt    # Python dependencies
├── .env.example        # Environment variables template
└── .gitignore
```

---

## ⚙️ Environment Variables

Copy `.env.example` to `.env` and fill in your values:

```bash
SUPABASE_URL=your_supabase_project_url
SUPABASE_KEY=your_supabase_anon_key
OPENROUTER_KEY=your_openrouter_api_key
```

Set these same variables in your **Vercel project settings** under Environment Variables.

---

## 🚀 Deploy

```bash
git clone https://github.com/oblivion-core/vocademy.git
cd vocademy
# Install Vercel CLI
npm i -g vercel
# Deploy
vercel
```

Then point your Alexa skill's endpoint to:
```
https://your-vercel-url.vercel.app/api/alexa
```

---

## 🧠 How It Works

1. Parent creates a session in the app, assigns a kid and uploads a document
2. Child launches the Alexa skill → Alexa fetches the active session from Supabase
3. Alexa reads the document in chunks — child can ask for word explanations anytime
4. Child starts the quiz — answers A/B/C/D by voice
5. Quiz ends → LLM generates a performance report → saved to Supabase for parents

---

## 📦 Dependencies

```
requests
pdfminer.six
```

---

Built by **Bouslah Abdelkrim** · [github.com/oblivion-core](https://github.com/oblivion-core)
