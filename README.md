
# TokenTrim 🌿
### Context Optimizer for Agentic AI Apps

TokenTrim reduces token consumption in AI applications by **70–95%** by replacing flat memory files with a smart hierarchical memory tree. Instead of loading your entire memory on every API call, TokenTrim loads only the relevant domain.



## The Problem

Every time you call an AI API with a memory/context file:
Full MEMORY.md = 549 tokens × 1000 calls/day = 549,000 tokens/day

Most of that context is irrelevant to the current question. You're paying for tokens the AI doesn't need.


## The Solution

TokenTrim splits your flat memory into domain folders and loads only what's relevant:
Question: "who am i?"
→ Loads only: identity domain (58 tokens)
→ Saves: 491 tokens (89.4% reduction)


## Features

- 🧠 **LLM-based smart classification** — Gemini automatically sorts memory into domains
- 🌳 **Hierarchical memory tree** — identity, business, infrastructure, community, general
- 💬 **Built-in chat interface** — ask questions directly in the browser
- 📊 **Token report** — shows before/after token count on every message
- 🔌 **Works with any LLM** — Claude, GPT-4, Gemini, Llama via OpenRouter
- 🖥️ **Web dashboard** — Tree Explorer, Import Splitter, Reflection Board


## How It Works
Your flat MEMORY.md (549 tokens)
↓
LLM classifier reads each section
↓
Splits into domain folders on disk
↓
On each question → loads only relevant domain
↓
AI gets 58 tokens instead of 549
↓
89.4% reduction. Every. Single. Call.


## Quick Start

### 1. Clone the repo

```bash
git clone https://github.com/YOUR_USERNAME/tokentrim.git
cd tokentrim
```

### 2. Install dependencies

```bash
pip install fastapi uvicorn openai google-generativeai requests python-dotenv
```

### 3. Set your API keys

```bash
export GEMINI_API_KEY="your-gemini-key"
export TOKENTRIM_WORKSPACE="/path/to/your/workspace"
```

### 4. Start the server

```bash
python -m uvicorn tokentrim.server:app --reload --port 8000
```

### 5. Open the dashboard
http://127.0.0.1:8000


## Using the Dashboard

| Tab | What it does |
|---|---|
| **Tree Explorer** | Browse your memory domains and files |
| **Import Splitter** | Paste flat memory → AI splits into domains |
| **Reflection Board** | AI suggests memory cleanup and reorganization |
| **Settings** | Configure API keys |
| **💬 Chat** | Ask questions using your optimized memory |


## Using the Chat Tab

1. Click **💬 Chat** tab
2. Enter your OpenRouter API key
3. Type any question about your memory
4. See the token report at the bottom showing your savings


## Using ask_claude.py (Terminal)

```bash
python ask_claude.py
```
Your question: what is my current project?
📊 TOKEN REPORT
Without TokenTrim : 549 tokens (full memory)
With TokenTrim    : 58 tokens (domain: business)
Saved             : 491 tokens (89.4% reduction)
🤖 ANSWER:
Your current project is TokenTrim — an AI token optimization tool...


## What to Put in Your Memory

Go to Import Splitter and paste markdown with ## headings:

```markdown
## About Me
My name is... I am a developer...

## My Project
Building X using Y stack...

## Infrastructure
Database is... Server runs on...

## Goals
I want to...
```

TokenTrim automatically classifies each section into the right domain.

---

## Tech Stack

- **Backend** — FastAPI (Python)
- **LLM Classification** — Gemini API
- **Chat** — OpenRouter (supports Claude, GPT-4, Gemini, Llama)
- **Frontend** — Vanilla HTML/CSS/JS
- **Token Counting** — Word-based estimation

---

## Token Savings Example

| Memory Size | Without TokenTrim | With TokenTrim | Saving |
|---|---|---|---|
| 549 tokens | 549 per call | 58 per call | 89.4% |
| 2,000 tokens | 2,000 per call | ~150 per call | 92.5% |
| 10,000 tokens | 10,000 per call | ~200 per call | 98% |

---

## Project Structure
tokentrim/
├── server.py          # FastAPI backend + all API endpoints
├── core.py            # Memory tree management
├── llm.py             # Gemini LLM classifier
├── cli.py             # Command line interface
├── ask_claude.py      # Terminal chat script
├── init.py        # Package init
└── templates/
└── index.html     # Full web dashboard UI




