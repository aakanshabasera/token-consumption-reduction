import os
import re
import json
from datetime import datetime, timezone
import shutil

class TokenTrimManager:
    def __init__(self, workspace_path: str):
        self.workspace = os.path.abspath(workspace_path)
        self.memory_dir = os.path.join(self.workspace, "memory")
        self.domains_dir = os.path.join(self.memory_dir, "domains")
        self.daily_dir = os.path.join(self.memory_dir, "daily")
        self.meta_file = os.path.join(self.memory_dir, "_meta.json")
        self.stats_file = os.path.join(self.memory_dir, "_stats.json")
        self.root_index = os.path.join(self.memory_dir, "_index.md")
        self.purge_log_file = os.path.join(self.memory_dir, "_purge_log.json")
        self.memory_md = os.path.join(self.workspace, "MEMORY.md")
        
        # Ensure directories exist
        os.makedirs(self.memory_dir, exist_ok=True)
        os.makedirs(self.domains_dir, exist_ok=True)
        os.makedirs(self.daily_dir, exist_ok=True)
        
        # Initialize tiktoken
        try:
            import tiktoken
            self.encoding = tiktoken.get_encoding("cl100k_base")
        except Exception:
            self.encoding = None

    def count_tokens(self, text: str) -> int:
        """Returns token count using cl100k_base (or char count / 4 fallback)."""
        if not text:
            return 0
        if self.encoding:
            try:
                return len(self.encoding.encode(text))
            except Exception:
                pass
        # Fallback character count / 4
        return max(1, len(text) // 4)

    def parse_flat_markdown(self, filepath: str) -> list:
        """
        Parses a flat MEMORY.md file and splits it into sections by H2 (##) headings.
        Returns a list of dicts: {'heading': str, 'content': str}
        """
        if not os.path.exists(filepath):
            return []
            
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
            
        # Match H2 headings and capture content until the next H2 or end of file
        pattern = r"(^##\s+.*?)(?=(?:^##\s+)|$)"
        matches = re.findall(pattern, content, re.MULTILINE | re.DOTALL)
        
        sections = []
        # Also capture introduction before the first H2 if any
        intro_match = re.match(r"^(.*?)(?=^##\s+)", content, re.MULTILINE | re.DOTALL)
        if intro_match:
            intro_text = intro_match.group(1).strip()
            if intro_text:
                sections.append({
                    "heading": "Introduction",
                    "content": intro_text,
                    "is_intro": True
                })
                
        for match in matches:
            lines = match.strip().split("\n")
            heading_line = lines[0]
            heading = heading_line.replace("##", "").strip()
            body = "\n".join(lines[1:]).strip()
            
            sections.append({
                "heading": heading,
                "content": match.strip(), # Keep heading + body
                "body": body,
                "is_intro": False
            })
            
        return sections

    def slugify(self, text: str) -> str:
        """Converts heading text into a clean file slug."""
        text = text.lower()
        text = re.sub(r"[^\w\s-]", "", text)
        text = re.sub(r"[\s_]+", "-", text)
        text = re.sub(r"-+", "-", text).strip("-")
        return text[:60]

    def rule_based_classify(self, heading: str) -> str:
        """Falls back to simple keyword matching for domain classification."""
        h = heading.lower()
        keywords = {
            "identity": ["identity", "personal", "family", "personality", "preferences", "network", "professional"],
            "business": ["business", "revenue", "company", "seo", "events", "product", "brand", "pricing", "clients", "marketing", "billing", "invoice"],
            "infrastructure": ["infrastructure", "services", "cron", "voice", "api", "issues", "quirks", "config", "tools", "setup", "hosting"],
            "community": ["community", "directory", "meetup", "group"],
            "agents": ["agent", "task", "sub-agent", "monitoring", "subagent"],
            "legal": ["legal", "non-compete", "contract", "compliance"],
        }
        for domain, keys in keywords.items():
            for key in keys:
                if key in h:
                    return domain
        if "date" in h or "anniversary" in h or "birthday" in h:
            return "dates"
        return "general"

    def split_and_import(self, flat_filepath: str, llm_classifications: dict = None) -> dict:
        """
        Splits a flat MEMORY.md file, puts sections into domain folders, and runs reindex.
        llm_classifications maps heading string to {'domain': str, 'filename': str, 'summary': str}
        """
        # 1. Backup original
        backup_path = flat_filepath + ".bak"
        if os.path.exists(flat_filepath):
            shutil.copy2(flat_filepath, backup_path)
            
        sections = self.parse_flat_markdown(flat_filepath)
        imported_files = []
        
        # Ensure 'general' exists
        os.makedirs(os.path.join(self.domains_dir, "general"), exist_ok=True)
        
        for section in sections:
            if section.get("is_intro"):
                # Save intro as overview in general domain or root
                intro_file = os.path.join(self.memory_dir, "overview.md")
                with open(intro_file, "w", encoding="utf-8") as f:
                    f.write(section["content"])
                imported_files.append(intro_file)
                continue
                
            heading = section["heading"]
            content = section["content"]
            
            # Determine domain & filename
            domain = "general"
            filename_slug = self.slugify(heading)
            
            if llm_classifications and heading in llm_classifications:
                class_info = llm_classifications[heading]
                domain = class_info.get("domain", "general").lower()
                filename_slug = class_info.get("filename", filename_slug)
            else:
                domain = self.rule_based_classify(heading)
                
            # If classified as cross-cutting dates, goes to dates.md directly
            if domain == "dates":
                dates_file = os.path.join(self.memory_dir, "dates.md")
                mode = "a" if os.path.exists(dates_file) else "w"
                with open(dates_file, mode, encoding="utf-8") as f:
                    f.write("\n\n" + content)
                imported_files.append(dates_file)
                continue
                
            # Make sure domain dir exists
            domain_path = os.path.join(self.domains_dir, domain)
            os.makedirs(domain_path, exist_ok=True)
            
            # Write markdown file
            filepath = os.path.join(domain_path, f"{filename_slug}.md")
            with open(filepath, "w", encoding="utf-8") as f:
                # Add domain frontmatter for self-documentation
                f.write(f"---\ndomain: {domain}\ntitle: {heading}\n---\n\n{content}\n")
                
            imported_files.append(filepath)
            
        # Move any existing YYYY-MM-DD.md daily logs in workspace/memory to daily/
        for item in os.listdir(self.memory_dir):
            if re.match(r"^\d{4}-\d{2}-\d{2}\.md$", item):
                shutil.move(os.path.join(self.memory_dir, item), os.path.join(self.daily_dir, item))
                
        # Run reindex
        stats = self.reindex()
        return {
            "backup": backup_path,
            "imported_files_count": len(imported_files),
            "stats": stats
        }

    def reindex(self) -> dict:
        """
        Scans domains directory, generates index files, stats, meta, and rewrites MEMORY.md.
        """
        total_files = 0
        total_tokens = 0
        domain_files_count = {}
        domain_tokens_count = {}
        general_age_violations = 0
        domain_tree = {}
        
        now_str = datetime.now(timezone.utc).isoformat()
        now_epoch = int(datetime.now().timestamp())
        
        # Traverse domain folders
        for domain in os.listdir(self.domains_dir):
            domain_path = os.path.join(self.domains_dir, domain)
            if not os.path.isdir(domain_path):
                continue
                
            domain_files_count[domain] = 0
            domain_tokens_count[domain] = 0
            domain_tree[domain] = []
            
            # Scan files inside domain
            for filename in sorted(os.listdir(domain_path)):
                if not filename.endswith(".md") or filename == "_index.md":
                    continue
                    
                filepath = os.path.join(domain_path, filename)
                with open(filepath, "r", encoding="utf-8") as f:
                    file_content = f.read()
                    
                tokens = self.count_tokens(file_content)
                domain_files_count[domain] += 1
                domain_tokens_count[domain] += tokens
                total_files += 1
                total_tokens += tokens
                
                # Check age violations for general domain
                is_general_violation = False
                if domain == "general" and not filename.startswith("_"):
                    file_mtime = os.path.getmtime(filepath)
                    age_days = (now_epoch - file_mtime) / 86400
                    if age_days > 30:
                        general_age_violations += 1
                        is_general_violation = True
                        
                domain_tree[domain].append({
                    "name": filename,
                    "tokens": tokens,
                    "age_days": int((now_epoch - os.path.getmtime(filepath)) / 86400),
                    "violation": is_general_violation
                })
                
        # Generate per-domain _index.md files
        for domain, files in domain_tree.items():
            domain_index_path = os.path.join(self.domains_dir, domain, "_index.md")
            with open(domain_index_path, "w", encoding="utf-8") as f:
                f.write(f"# {domain.capitalize()} Index\n")
                f.write(f"_Last indexed: {now_str}_\n")
                f.write(f"_Estimated tokens: ~{domain_tokens_count[domain]}_\n\n")
                
                for file_info in files:
                    fname = file_info["name"]
                    fpath = os.path.join(self.domains_dir, domain, fname)
                    
                    # Extract first meaningful line
                    first_line = ""
                    with open(fpath, "r", encoding="utf-8") as f_in:
                        in_frontmatter = False
                        for line in f_in:
                            stripped = line.strip()
                            if stripped == "---":
                                in_frontmatter = not in_frontmatter
                                continue
                            if in_frontmatter:
                                continue
                            if not stripped:
                                continue
                            if stripped.startswith("#") and len(stripped) < 10:
                                continue
                            first_line = stripped[:250]
                            break
                            
                    f.write(f"### {fname} (~{file_info['tokens']} tokens)\n")
                    f.write(f"{first_line or '[No content]'}\n\n")

        # Generate root _index.md
        with open(self.root_index, "w", encoding="utf-8") as f:
            f.write("# Memory Index\n")
            f.write(f"_Last indexed: {now_str}_\n")
            f.write(f"_Estimated tokens: ~{total_tokens}_\n\n")
            f.write("## Domains\n\n")
            
            for domain in sorted(domain_files_count.keys()):
                files = domain_tree[domain]
                files_str = ", ".join([fi["name"].replace(".md", "") for fi in files if not fi["name"].startswith("_")])
                f.write(f"### {domain.capitalize()} (~{domain_tokens_count[domain]} tokens, {domain_files_count[domain]} files)\n")
                if files_str:
                    f.write(f"_Files: {files_str}_\n")
                f.write("\n")
                
            # Add Daily logs count
            daily_count = 0
            if os.path.exists(self.daily_dir):
                daily_count = len([x for x in os.listdir(self.daily_dir) if x.endswith(".md")])
            if daily_count > 0:
                f.write(f"### Daily Logs ({daily_count} files in memory/daily/)\n")
                f.write("Searchable recursively under daily/ directory.\n\n")

        # Rewrite main MEMORY.md as a stub
        with open(self.memory_md, "w", encoding="utf-8") as f:
            f.write("# Memory Index (see memory/domains/ for full content)\n")
            f.write("# Auto-generated — do not edit directly\n")
            f.write(f"# Last regenerated: {now_str}\n\n")
            
            # Read and append root index content
            with open(self.root_index, "r", encoding="utf-8") as ri:
                f.write(ri.read())

        # Write _meta.json
        meta_data = {
            "last_reindex": now_str,
            "domain_count": len(domain_files_count),
            "total_tokens": total_tokens,
            "script_version": "1.0.0"
        }
        with open(self.meta_file, "w", encoding="utf-8") as f:
            json.dump(meta_data, f, indent=2)

        # Write _stats.json
        stats_data = {
            "domains": {
                domain: {
                    "files": domain_files_count[domain],
                    "tokens": domain_tokens_count[domain]
                } for domain in domain_files_count
            },
            "general_age_violations": general_age_violations
        }
        with open(self.stats_file, "w", encoding="utf-8") as f:
            json.dump(stats_data, f, indent=2)

        return {
            "meta": meta_data,
            "stats": stats_data,
            "tree": domain_tree
        }

    def status(self) -> dict:
        """Returns health status metrics."""
        if not os.path.exists(self.meta_file) or not os.path.exists(self.stats_file):
            return {
                "status": "UNINITIALIZED",
                "message": "Memory indices not yet created. Run reindex."
            }
            
        with open(self.meta_file, "r") as f:
            meta = json.load(f)
        with open(self.stats_file, "r") as f:
            stats = json.load(f)
            
        # Parse last reindex time
        last_reindex_str = meta.get("last_reindex")
        last_reindex = datetime.fromisoformat(last_reindex_str.replace("Z", "+00:00"))
        time_diff = datetime.now(timezone.utc) - last_reindex
        hours_since_reindex = time_diff.total_seconds() / 3600
        
        status_label = "HEALTHY"
        messages = []
        
        if hours_since_reindex > 24:
            status_label = "WARNING"
            messages.append(f"Reindex is overdue ({int(hours_since_reindex)} hours ago).")
            
        violations = stats.get("general_age_violations", 0)
        if violations > 0:
            status_label = "WARNING"
            messages.append(f"{violations} general/ domain files are older than 30 days and need migration.")
            if violations >= 5:
                status_label = "CRITICAL"
                
        # Check domain sizes and counts
        for domain, data in stats.get("domains", {}).items():
            if data["tokens"] > 8000:
                status_label = "WARNING"
                messages.append(f"Domain '{domain}' is very large ({data['tokens']} tokens). Suggest splitting.")
            if data["files"] > 25:
                status_label = "WARNING"
                messages.append(f"Domain '{domain}' has too many files ({data['files']} files). Suggest reorganizing.")

        # Check pending purges
        pending_purge_count = 0
        for domain in os.listdir(self.domains_dir):
            domain_path = os.path.join(self.domains_dir, domain)
            if os.path.isdir(domain_path):
                for f in os.listdir(domain_path):
                    if "__DELETE" in f:
                        pending_purge_count += 1
                        
        if pending_purge_count > 0:
            messages.append(f"{pending_purge_count} files are staged for purge (__DELETE).")

        return {
            "status": status_label,
            "last_reindex_hours": round(hours_since_reindex, 1),
            "total_tokens": meta["total_tokens"],
            "domain_count": meta["domain_count"],
            "general_age_violations": violations,
            "pending_purge_count": pending_purge_count,
            "messages": messages,
            "meta": meta,
            "stats": stats
        }

    def migrate_file(self, src_path: str, dest_domain: str) -> bool:
        """Moves a memory file from its current domain to another, updates domain frontmatter, and reindexes."""
        if not os.path.exists(src_path):
            return False
            
        filename = os.path.basename(src_path)
        dest_dir = os.path.join(self.domains_dir, dest_domain.lower())
        os.makedirs(dest_dir, exist_ok=True)
        dest_path = os.path.join(dest_dir, filename)
        
        # Read content and update domain metadata in frontmatter if exists
        with open(src_path, "r", encoding="utf-8") as f:
            content = f.read()
            
        if content.startswith("---"):
            # Update domain: field
            content = re.sub(r"domain:\s*\w+", f"domain: {dest_domain}", content, count=1)
        else:
            # Prepend frontmatter
            content = f"---\ndomain: {dest_domain}\n---\n\n{content}"
            
        # Write to destination and delete source
        with open(dest_path, "w", encoding="utf-8") as f:
            f.write(content)
            
        if os.path.abspath(src_path) != os.path.abspath(dest_path):
            os.remove(src_path)
            
        self.reindex()
        return True

    def archive_file(self, file_path: str) -> bool:
        """Renames a file to end with __DELETE.md, marking it for future purging."""
        if not os.path.exists(file_path):
            return False
        if "__DELETE" in file_path:
            return True
            
        dir_name = os.path.dirname(file_path)
        base_name = os.path.basename(file_path)
        new_base_name = base_name.replace(".md", "__DELETE.md")
        new_path = os.path.join(dir_name, new_base_name)
        
        os.rename(file_path, new_path)
        self.reindex()
        return True

    def purge(self, grace_period_days: int = 180) -> list:
        """
        Permanently deletes files ending in __DELETE.md that are older than grace_period_days.
        Logs actions to _purge_log.json.
        """
        purged_files = []
        now_epoch = int(datetime.now().timestamp())
        grace_seconds = grace_period_days * 86400
        
        # Read purge log
        purge_log = []
        if os.path.exists(self.purge_log_file):
            try:
                with open(self.purge_log_file, "r") as f:
                    purge_log = json.load(f)
            except Exception:
                pass
                
        for domain in os.listdir(self.domains_dir):
            domain_path = os.path.join(self.domains_dir, domain)
            if not os.path.isdir(domain_path):
                continue
                
            for filename in os.listdir(domain_path):
                if "__DELETE" in filename:
                    filepath = os.path.join(domain_path, filename)
                    file_mtime = os.path.getmtime(filepath)
                    age_seconds = now_epoch - file_mtime
                    
                    if age_seconds >= grace_seconds:
                        # Log it
                        purged_files.append({
                            "domain": domain,
                            "filename": filename,
                            "purged_at": datetime.now(timezone.utc).isoformat(),
                            "size_bytes": os.path.getsize(filepath)
                        })
                        # Delete file
                        os.remove(filepath)
                        
        if purged_files:
            purge_log.extend(purged_files)
            with open(self.purge_log_file, "w") as f:
                json.dump(purge_log, f, indent=2)
            self.reindex()
            
        return purged_files
