import os
import json
import urllib.request
import urllib.error

class GeminiClient:
    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        # Default model
        self.model = "gemini-1.5-flash" 

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def _call_gemini_api(self, prompt: str, json_mode: bool = False) -> str:
        """Call Gemini API using raw HTTP requests to bypass package dependencies."""
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY is not configured.")

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"
        headers = {"Content-Type": "application/json"}
        
        req_data = {
            "contents": [{
                "parts": [{"text": prompt}]
            }]
        }
        
        if json_mode:
            req_data["generationConfig"] = {
                "responseMimeType": "application/json"
            }

        req = urllib.request.Request(
            url, 
            data=json.dumps(req_data).encode("utf-8"), 
            headers=headers, 
            method="POST"
        )
        
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                resp_data = json.loads(response.read().decode("utf-8"))
                
                # Extract text response
                candidates = resp_data.get("candidates", [])
                if not candidates:
                    raise ValueError(f"No response candidates. Raw: {resp_data}")
                    
                parts = candidates[0].get("content", {}).get("parts", [])
                if not parts:
                    raise ValueError(f"Empty content parts. Raw: {resp_data}")
                    
                return parts[0].get("text", "")
                
        except urllib.error.HTTPError as e:
            err_content = e.read().decode("utf-8")
            raise RuntimeError(f"Gemini API Error (HTTP {e.code}): {err_content}")
        except Exception as e:
            raise RuntimeError(f"Error calling Gemini API: {str(e)}")

    def classify_section(self, heading: str, content: str, existing_domains: list) -> dict:
        """
        Classifies a memory section into a domain using Gemini.
        Returns a dictionary with domain, filename, summary, and tags.
        """
        if not self.is_configured():
            # Fallback to local heuristic
            return None

        domains_str = ", ".join(existing_domains)
        prompt = f"""
You are an expert context-optimization system for AI Agents.
Your task is to classify a memory section into the most relevant domain to keep the context size minimal.

Section Heading: "{heading}"
Section Content:
\"\"\"
{content}
\"\"\"

Available domains: {domains_str}

Please categorize this section. You can use one of the existing domains above, or propose a new lowercase domain name if the content does not fit any of them (e.g. "finance", "writing").

Provide a response in JSON format matching this schema:
{{
  "domain": "string (lowercase domain name)",
  "filename": "string (slugified-filename-without-extension, e.g. company-branding)",
  "summary": "string (1-2 sentences summarizing the key facts in this memory)",
  "tags": ["string", "string"],
  "reasoning": "string (why you placed it in this domain)"
}}
"""
        try:
            resp_text = self._call_gemini_api(prompt, json_mode=True)
            return json.loads(resp_text)
        except Exception as e:
            print(f"LLM Classification failed: {e}. Falling back to rules.")
            return None

    def analyze_memory_tree(self, stats: dict, file_tree: dict) -> dict:
        """
        Analyzes the memory tree and returns optimization recommendations.
        """
        if not self.is_configured():
            return None

        # Clean structure for the model
        tree_summary = {}
        for domain, files in file_tree.items():
            tree_summary[domain] = [
                {
                    "name": f["name"],
                    "tokens": f["tokens"],
                    "age_days": f["age_days"]
                } for f in files if not f["name"].startswith("_")
            ]

        prompt = f"""
You are an AI Memory Pruner auditing an AI Agent's long-term memory.
The memory is split into domains and files to save tokens. We want to find:
1. Outdated files that should be archived (marked with __DELETE suffix).
2. Large files (>500 tokens) that should be split.
3. Domains with too many files (>15 files) that should be grouped or sub-divided.
4. Files in "general" domain older than 15 days that should be moved to a specific domain (e.g. business, identity, infrastructure).

Current Memory Statistics:
{json.dumps(stats, indent=2)}

File Tree details (showing tokens and age in days for files in each domain):
{json.dumps(tree_summary, indent=2)}

Please suggest recommendations to clean up and prune this memory tree.
Provide a response in JSON format matching this schema:
{{
  "recommendations": [
    {{
      "file": "string (path to file, e.g. memory/domains/general/old-notes.md)",
      "action": "string ('migrate' | 'archive' | 'split' | 'merge' | 'keep')",
      "suggested_domain": "string (if action is 'migrate', otherwise null)",
      "reason": "string (why you recommend this action)"
    }}
  ]
}}
"""
        try:
            resp_text = self._call_gemini_api(prompt, json_mode=True)
            return json.loads(resp_text)
        except Exception as e:
            print(f"LLM Reflection failed: {e}")
            return None
