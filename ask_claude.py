import requests
import google.generativeai as genai
import os

# ── CONFIG ──────────────────────────────────────────────
GEMINI_API_KEY = "AIzaSyDoW9OiUEPbNLDT9aq8ohgKcGDStLRFt04"
TOKENTRIM_URL  = "http://127.0.0.1:8000"
WORKSPACE      = "/Users/aakanshabasera/.gemini/antigravity/scratch/tokentrim/tokentrim"
# ────────────────────────────────────────────────────────

genai.configure(api_key=GEMINI_API_KEY)
gemini = genai.GenerativeModel("gemini-2.0-flash")

def count_tokens(text):
    return len(text.split())

def get_full_memory():
    all_text = ""
    domains_path = os.path.join(WORKSPACE, "memory", "domains")
    if not os.path.exists(domains_path):
        return ""
    for domain in os.listdir(domains_path):
        domain_dir = os.path.join(domains_path, domain)
        if os.path.isdir(domain_dir):
            for fname in os.listdir(domain_dir):
                if fname.endswith(".md"):
                    fpath = os.path.join(domain_dir, fname)
                    with open(fpath) as f:
                        all_text += f.read() + "\n\n"
    return all_text

def get_smart_context(question):
    tree_resp = requests.get(f"{TOKENTRIM_URL}/api/tree")
    tree = tree_resp.json().get("domains", {})

    question_lower = question.lower()
    domain_scores = {}

    for domain, val in tree.items():
        score = 0
        if domain.lower() in question_lower:
            score += 10
        files = val if isinstance(val, list) else []
        for item in files:
            if isinstance(item, dict):
                text = " ".join(str(v) for v in item.values())
            else:
                text = str(item)
            words = text.replace("-", " ").replace("_", " ").replace("/", " ")
            for word in words.split():
                if len(word) > 3 and word.lower() in question_lower:
                    score += 3
        domain_scores[domain] = score

    if not domain_scores:
        return "No memory found.", "none"

    best_domain = max(domain_scores, key=domain_scores.get)

    context = f"# Memory Context (domain: {best_domain})\n\n"
    files = tree.get(best_domain, [])

    for item in files:
        if isinstance(item, dict):
            fname = item.get("name") or item.get("path") or item.get("file") or ""
            filepath = f"memory/domains/{best_domain}/{fname}"
        else:
            filepath = str(item)

        file_resp = requests.get(
            f"{TOKENTRIM_URL}/api/file",
            params={"path": filepath}
        )
        if file_resp.status_code == 200:
            context += file_resp.json().get("content", "") + "\n\n"

    return context, best_domain

def ask_gemini(question):
    print("\n" + "="*50)
    print(f"YOUR QUESTION: {question}")
    print("="*50)

    full_memory   = get_full_memory()
    tokens_before = count_tokens(full_memory)

    smart_context, domain_used = get_smart_context(question)
    tokens_after  = count_tokens(smart_context)

    saved   = tokens_before - tokens_after
    percent = round((saved / max(1, tokens_before)) * 100, 1)

    print(f"\n📊 TOKEN REPORT")
    print(f"   Without TokenTrim : {tokens_before} tokens (full memory)")
    print(f"   With TokenTrim    : {tokens_after} tokens (domain: {domain_used})")
    print(f"   Saved             : {saved} tokens ({percent}% reduction)")
    print(f"\n⏳ Asking Gemini...\n")

    prompt = f"{smart_context}\n\nAnswer this question using only the context above:\n{question}"
    response = gemini.generate_content(prompt)

    print(f"🤖 GEMINI SAYS:\n{response.text}")
    print("="*50 + "\n")

if __name__ == "__main__":
    print("\nTokenTrim + Gemini Integration")
    print("Type your question (or 'quit' to exit)\n")
    while True:
        q = input("Your question: ").strip()
        if q.lower() in ("quit", "exit", "q"):
            break
        if q:
            ask_gemini(q)