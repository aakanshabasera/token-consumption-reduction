import os
import json
import shutil
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import List, Dict, Optional

from tokentrim.core import TokenTrimManager
from tokentrim.llm import GeminiClient

app = FastAPI(title="TokenTrim Dashboard")

# Resolve workspace path from environment
def get_manager() -> TokenTrimManager:
    workspace = os.environ.get("TOKENTRIM_WORKSPACE", os.getcwd())
    return TokenTrimManager(workspace)

def get_client() -> GeminiClient:
    api_key = os.environ.get("GEMINI_API_KEY")
    return GeminiClient(api_key)

class ConfigSave(BaseModel):
    api_key: str

class SplitPreviewRequest(BaseModel):
    markdown_text: str
    use_llm: bool

class SplitItem(BaseModel):
    heading: str
    content: str
    proposed_domain: str
    proposed_filename: str
    tokens: int
    is_intro: bool

class ApplySplitRequest(BaseModel):
    items: List[SplitItem]

class FileEditRequest(BaseModel):
    filepath: str
    content: str

class ReflectionActionRequest(BaseModel):
    file: str
    action: str  # 'keep' | 'migrate' | 'archive'
    suggested_domain: Optional[str] = None

# Serving UI
@app.get("/", response_class=HTMLResponse)
async def get_index():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    template_path = os.path.join(current_dir, "templates", "index.html")
    if not os.path.exists(template_path):
        raise HTTPException(status_code=404, detail="Template index.html not found.")
        
    with open(template_path, "r", encoding="utf-8") as f:
        html_content = f.read()
    return html_content

@app.get("/api/status")
async def get_status():
    try:
        manager = get_manager()
        status_info = manager.status()
        
        # Calculate token savings comparison
        flat_size = 0
        if os.path.exists(manager.memory_md):
            with open(manager.memory_md, "r", encoding="utf-8") as f:
                flat_size = manager.count_tokens(f.read())
                
        # Calculate original backup size if available to show total progress
        original_size = flat_size
        backup_path = manager.memory_md + ".bak"
        if os.path.exists(backup_path):
            with open(backup_path, "r", encoding="utf-8") as f:
                original_size = manager.count_tokens(f.read())
                
        # Total size in tree
        total_tokens = 0
        if status_info.get("status") != "UNINITIALIZED":
            total_tokens = status_info.get("total_tokens", 0)

        # Staging file status
        staging_file = os.path.join(manager.memory_dir, "_reflect_staging.json")
        has_staging = os.path.exists(staging_file)
        
        return {
            "status": status_info.get("status"),
            "workspace": manager.workspace,
            "api_key_configured": bool(os.environ.get("GEMINI_API_KEY")),
            "last_reindex_hours": status_info.get("last_reindex_hours", 0),
            "original_tokens": original_size,
            "active_boot_tokens": flat_size,
            "total_store_tokens": total_tokens,
            "savings_percent": round((1 - (flat_size / max(1, original_size))) * 100, 1) if original_size > 0 else 0,
            "general_age_violations": status_info.get("general_age_violations", 0),
            "pending_purge_count": status_info.get("pending_purge_count", 0),
            "messages": status_info.get("messages", []),
            "has_staging": has_staging
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/tree")
async def get_tree():
    try:
        manager = get_manager()
        if not os.path.exists(manager.meta_file):
            return {"domains": {}}
            
        res = manager.reindex()
        return {"domains": res["tree"]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/save-config")
async def save_config(cfg: ConfigSave):
    # Set the environment variable for this session
    os.environ["GEMINI_API_KEY"] = cfg.api_key
    return {"status": "SUCCESS", "message": "API key updated."}

@app.post("/api/split-preview", response_model=List[SplitItem])
async def split_preview(req: SplitPreviewRequest):
    try:
        manager = get_manager()
        client = get_client()
        
        # Temp file to read markdown structure
        temp_file = os.path.join(manager.memory_dir, "_temp_import.md")
        with open(temp_file, "w", encoding="utf-8") as f:
            f.write(req.markdown_text)
            
        sections = manager.parse_flat_markdown(temp_file)
        
        if os.path.exists(temp_file):
            os.remove(temp_file)
            
        preview_items = []
        existing_domains = ["identity", "business", "infrastructure", "community", "agents", "legal", "general"]
        
        for sec in sections:
            if sec.get("is_intro"):
                preview_items.append(SplitItem(
                    heading="Introduction",
                    content=sec["content"],
                    proposed_domain="general",
                    proposed_filename="overview",
                    tokens=manager.count_tokens(sec["content"]),
                    is_intro=True
                ))
                continue
                
            heading = sec["heading"]
            content = sec["content"]
            tokens = manager.count_tokens(content)
            
            domain = "general"
            filename_slug = manager.slugify(heading)
            
            if req.use_llm and client.is_configured():
                llm_res = client.classify_section(heading, content, existing_domains)
                if llm_res:
                    domain = llm_res.get("domain", "general").lower()
                    filename_slug = llm_res.get("filename", filename_slug)
                    if domain not in existing_domains:
                        existing_domains.append(domain)
            else:
                domain = manager.rule_based_classify(heading)
                
            preview_items.append(SplitItem(
                heading=heading,
                content=content,
                proposed_domain=domain,
                proposed_filename=filename_slug,
                tokens=tokens,
                is_intro=False
            ))
            
        return preview_items
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/apply-split")
async def apply_split(req: ApplySplitRequest):
    try:
        manager = get_manager()
        
        # Backup existing MEMORY.md if it exists
        if os.path.exists(manager.memory_md):
            shutil.copy2(manager.memory_md, manager.memory_md + ".bak")
            
        # Ensure 'general' exists
        os.makedirs(os.path.join(manager.domains_dir, "general"), exist_ok=True)
        
        for item in req.items:
            if item.is_intro:
                intro_file = os.path.join(manager.memory_dir, "overview.md")
                with open(intro_file, "w", encoding="utf-8") as f:
                    f.write(item.content)
                continue
                
            # If dates
            if item.proposed_domain == "dates":
                dates_file = os.path.join(manager.memory_dir, "dates.md")
                mode = "a" if os.path.exists(dates_file) else "w"
                with open(dates_file, mode, encoding="utf-8") as f:
                    f.write("\n\n" + item.content)
                continue
                
            domain_path = os.path.join(manager.domains_dir, item.proposed_domain)
            os.makedirs(domain_path, exist_ok=True)
            
            filepath = os.path.join(domain_path, f"{item.proposed_filename}.md")
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(f"---\ndomain: {item.proposed_domain}\ntitle: {item.heading}\n---\n\n{item.content}\n")
                
        # Reindex
        stats = manager.reindex()
        return {"status": "SUCCESS", "message": "Split applied successfully", "stats": stats}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/file")
async def get_file(path: str = Query(..., description="Absolute or relative path to file")):
    manager = get_manager()
    # Security: resolve path within workspace
    full_path = os.path.abspath(os.path.join(manager.workspace, path))
    if not full_path.startswith(manager.workspace):
        raise HTTPException(status_code=403, detail="Access denied. Path outside workspace.")
        
    if not os.path.exists(full_path):
        raise HTTPException(status_code=404, detail="File not found.")
        
    with open(full_path, "r", encoding="utf-8") as f:
        content = f.read()
        
    return {
        "path": path,
        "content": content,
        "tokens": manager.count_tokens(content)
    }

@app.put("/api/file")
async def edit_file(req: FileEditRequest):
    manager = get_manager()
    full_path = os.path.abspath(os.path.join(manager.workspace, req.filepath))
    if not full_path.startswith(manager.workspace):
        raise HTTPException(status_code=403, detail="Access denied. Path outside workspace.")
        
    with open(full_path, "w", encoding="utf-8") as f:
        f.write(req.content)
        
    # Trigger auto-reindex
    manager.reindex()
    return {"status": "SUCCESS", "message": "File updated successfully."}

@app.get("/api/reflection-staging")
async def get_reflection_staging():
    manager = get_manager()
    staging_file = os.path.join(manager.memory_dir, "_reflect_staging.json")
    if not os.path.exists(staging_file):
        return {"candidates": []}
        
    with open(staging_file, "r") as f:
        data = json.load(f)
    return data

@app.post("/api/resolve-reflection")
async def resolve_reflection(actions: List[ReflectionActionRequest]):
    try:
        manager = get_manager()
        staging_file = os.path.join(manager.memory_dir, "_reflect_staging.json")
        
        for act in actions:
            # File is relative path
            full_file_path = os.path.abspath(os.path.join(manager.workspace, act.file))
            if not os.path.exists(full_file_path):
                continue
                
            if act.action == "archive":
                manager.archive_file(full_file_path)
            elif act.action == "migrate" and act.suggested_domain:
                manager.migrate_file(full_file_path, act.suggested_domain)
            # 'keep' action is no-op
            
        # Reindex and delete staging file
        manager.reindex()
        if os.path.exists(staging_file):
            os.remove(staging_file)
            
        return {"status": "SUCCESS", "message": "Staged optimizations resolved successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/run-action")
async def run_action(action: str = Query(..., description="Action to run: reindex, purge, reflect")):
    try:
        manager = get_manager()
        client = get_client()
        
        if action == "reindex":
            stats = manager.reindex()
            return {"status": "SUCCESS", "message": "Reindexed successfully", "stats": stats}
        elif action == "purge":
            purged = manager.purge(grace_period_days=180)
            return {"status": "SUCCESS", "message": f"Purged {len(purged)} files.", "purged": purged}
        elif action == "reflect":
            if not client.is_configured():
                raise HTTPException(status_code=400, detail="Gemini API Key not configured. Reflection requires LLM.")
            res_reindex = manager.reindex()
            reflection = client.analyze_memory_tree(res_reindex["stats"], res_reindex["tree"])
            
            if reflection and "recommendations" in reflection:
                staging_file = os.path.join(manager.memory_dir, "_reflect_staging.json")
                with open(staging_file, "w") as f:
                    json.dump(reflection, f, indent=2)
                return {"status": "SUCCESS", "message": "Staged LLM reflection successfully.", "reflection": reflection}
            else:
                raise HTTPException(status_code=500, detail="Failed to get recommendations from LLM.")
        else:
            raise HTTPException(status_code=400, detail="Invalid action name.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

from openai import OpenAI

class ChatRequest(BaseModel):
    question: str
    api_key: str

@app.post("/api/chat")
async def chat(req: ChatRequest):
    try:
        manager = get_manager()
        
        # Get tree
        res = manager.reindex()
        tree = res["tree"]
        
        # Pick best domain
        question_lower = req.question.lower()
        domain_scores = {}
        for domain, files in tree.items():
            score = 0
            if domain.lower() in question_lower:
                score += 10
            for item in files:
                if isinstance(item, dict):
                    text = " ".join(str(v) for v in item.values())
                else:
                    text = str(item)
                words = text.replace("-", " ").replace("_", " ")
                for word in words.split():
                    if len(word) > 3 and word.lower() in question_lower:
                        score += 3
            domain_scores[domain] = score

        best_domain = max(domain_scores, key=domain_scores.get) if domain_scores else "general"
        
        # Load context
        context = f"# Memory Context (domain: {best_domain})\n\n"
        files = tree.get(best_domain, [])
        tokens_after = 0
        
        for item in files:
            fname = item.get("name") if isinstance(item, dict) else str(item)
            filepath = os.path.join(manager.workspace, "memory", "domains", best_domain, fname)
            if os.path.exists(filepath):
                with open(filepath) as f:
                    content = f.read()
                    context += content + "\n\n"
                    tokens_after += len(content.split())

        # Count total tokens
        all_text = ""
        domains_path = os.path.join(manager.workspace, "memory", "domains")
        for domain in os.listdir(domains_path):
            domain_dir = os.path.join(domains_path, domain)
            if os.path.isdir(domain_dir):
                for fname in os.listdir(domain_dir):
                    if fname.endswith(".md"):
                        with open(os.path.join(domain_dir, fname)) as f:
                            all_text += f.read()
        tokens_before = len(all_text.split())
        saved = tokens_before - tokens_after
        percent = round((saved / max(1, tokens_before)) * 100, 1)

        # Call OpenRouter
        client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=req.api_key
        )
        response = client.chat.completions.create(
            model="google/gemini-2.5-flash",
            messages=[
                {"role": "system", "content": context},
                {"role": "user", "content": req.question}
            ]
        )
        answer = response.choices[0].message.content

        return {
            "answer": answer,
            "domain_used": best_domain,
            "tokens_before": tokens_before,
            "tokens_after": tokens_after,
            "saved": saved,
            "percent": percent
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
