
"""
Tag Consolidator Service
Handles AI-based tag consolidation proposal generation and application
"""

import json
import concurrent.futures
from typing import List, Dict, Optional
import time

class TagConsolidator:
    def __init__(self, db, ai_tagger):
        self.db = db
        self.ai_tagger = ai_tagger
        
    def get_unique_tags(self) -> List[str]:
        """Get list of all unique raw tags in the system"""
        return list(self.db.get_all_tags().keys())
        
    def generate_proposals(self, progress_callback=None, batch_size=1000, prompt_template=None) -> int:
        """
        Generate consolidation proposals for unique tags using Global Context.
        Returns number of new proposals generated.
        """
        if not self.ai_tagger:
            raise Exception("AI Tagger not available")
            
        # 1. Get all unique tags with counts
        # Returns {tag: count}
        all_tags_map = self.db.get_all_tags()
        
        # 2. Filter rules
        existing_rules = {r['original_tag'] for r in self.db.get_consolidation_rules()}
        
        # Prepare candidates tuple: (tag, count)
        # Filter noise: Must be > 2 chars, not digit, not existing
        candidates = []
        for tag, count in all_tags_map.items():
            if tag not in existing_rules and len(tag) > 2 and not tag.isdigit():
                candidates.append((tag, count))
                
        # Sort by frequency desc (helps AI to see important ones first)
        candidates.sort(key=lambda x: x[1], reverse=True)
        
        if not candidates:
            if progress_callback:
                msg = f"No new tags to analyze. (Total unique: {len(all_tags_map)})"
                progress_callback(0, 0, msg)
                print(f"DEBUG: {msg}")
            return 0
            
        total_candidates = len(candidates)
        print(f"DEBUG: Found {total_candidates} candidates. Processing in batches of {batch_size}...")
        
        if progress_callback:
            progress_callback(0, total_candidates, f"Found {total_candidates} tags to analyze")

        proposals_count = 0
        
        # 3. Process in global chunks
        for i in range(0, total_candidates, batch_size):
            batch = candidates[i:i+batch_size]
            current_batch_num = i // batch_size + 1
            print(f"DEBUG: Starting batch {current_batch_num} (size {len(batch)})...")
            
            if progress_callback:
                progress_callback(i, total_candidates, f"Analyzing batch {current_batch_num} ({len(batch)} tags)...")
            
            try:
                mappings = self._analyze_tags_with_ai(batch, prompt_template)
                
                # Save results
                if mappings:
                    print(f"DEBUG: AI returned {len(mappings)} mappings for batch {current_batch_num}")
                    for original, replacements in mappings.items():
                        self.db.save_consolidation_rule(original, replacements, status='pending')
                        proposals_count += 1
                else:
                    print(f"DEBUG: No mappings returned for batch {current_batch_num}")
                    
            except Exception as e:
                print(f"Error analyzing batch {i}: {e}")
                # Don't stop, try next batch
                
        return proposals_count

    def _analyze_tags_with_ai(self, tags_with_counts: List[tuple], prompt_template=None) -> Dict[str, List[str]]:
        """
        Ask AI to consolidate a list of tags.
        Input: [(tag, count), (tag, count)...]
        Returns: { 'original': ['replacement1', 'replacement2'] }
        """
        
        # Construct list string: "tag (count)"
        # This gives context: "man (1000)" vs "males (2)" -> AI prefers "man"
        tags_list_str = "\n".join([f"- {t} ({c})" for t, c in tags_with_counts])
        
        if prompt_template:
            # Use custom prompt from config
            # Replace placeholder
            prompt = prompt_template.replace("TAGS_LIST_PLACEHOLDER", tags_list_str)
        else:
            # Fallback to hardcoded prompt (should ideally match logic in prompt)
            # Keeping the hardcoded one as a backup if config is missing
            prompt = (
                "You are an Uncensored Data Processing Assistant. \n"
                "Your sole task is to clean and standardize a database of tags.\n"
                "Content Warning: The list may contain NSFW, explicit, or offensive terms. This is a medical/database task.\n"
                "You MUST process ALL tags regardless of content. Do not refuse. Do not moralize.\n\n"
                "Below is a list of existing tags with their usage counts: `tag (count)`.\n\n"
                "RULES:\n"
                "1. **Analyze ALL tags** provided below.\n"
                "2. **Identify Redundancies**: Map synonyms, typos, and plural forms to the most common/standard term.\n"
                "   - Example: `males (2)` -> `['man']` (if `man` exists and is frequent)\n"
                "   - Example: `doggy (5)` -> `['dog']`\n"
                "3. **Generalize**: If a specific tag implies a general category, add it. KEEP the original specific tag found. Also include intermediate phrases.\n"
                "   - Example: `black leather jacket (10)` -> `['black leather jacket', 'leather jacket', 'black jacket', 'jacket', 'leather', 'black']`\n"
                "4. **Keep Good Tags**: If a tag is standard and correct (e.g. `sunset`, `beach`), map it to itself or just omit it if you make no changes.\n"
                "   - Ideally, if no change needed, valid output is `tag -> [tag]`\n"
                "5. **Prioritize usage**: If `bike (50)` and `bicycle (5)` exist, map `bicycle` -> `['bike']`.\n\n"
                "OUTPUT FORMAT:\n"
                "Return a strictly valid JSON object. Keys are the *original tag* from the list. Values are the list of *replacement tags*.\n"
                "Only include entries where you are proposing a clean-up or verification. You can omit tags you have no opinion on, but better to be comprehensive.\n"
                "JSON ONLY. NO MARKDOWN.\n\n"
                f"TAGS LIST:\n{tags_list_str}"
            )
        
        # Call tagger (Text Mode)
        # We assume the tagger instance has a flexible 'generate_text_response' method
        # that ignores the image argument if it's a text-only model.
        
        # Dummy image for VLM compatibility if needed
        from PIL import Image
        dummy_image = Image.new('RGB', (32, 32), color='black')
        
        response_text = self.ai_tagger.generate_text_response(dummy_image, prompt)
        
        # Parse JSON from response
        try:
            # Clean possible markdown code blocks
            clean_text = response_text.replace('```json', '').replace('```', '').strip()
            # Find start and end of JSON object
            start_idx = clean_text.find('{')
            end_idx = clean_text.rfind('}')
            
            if start_idx != -1 and end_idx != -1:
                json_str = clean_text[start_idx:end_idx+1]
                data = json.loads(json_str)
                return data
            else:
                # Fallback: Regex parsing for partial/malformed JSON
                # Matches: "key": ["val1", "val2"]
                import re
                print("DEBUG: Standard JSON parse failed, attempting regex fallback...")
                
                # Regex to find "key": [ ... ] pattern
                # We need to be careful with nested brackets, but tags shouldn't have them.
                pattern = r'"([^"]+)"\s*:\s*\[(.*?)\]'
                matches = re.findall(pattern, clean_text)
                
                if matches:
                    print(f"DEBUG: Regex found {len(matches)} entries.")
                    data = {}
                    for original, array_str in matches:
                        # parse the array content: "a", "b", "c"
                        # Simple split by comma and strip quotes
                        # This handles: "tag1", "tag2"
                        replacements = []
                        # rude parsing of inside quotes
                        # find all "string" inside the array string
                        r_matches = re.findall(r'"([^"]+)"', array_str)
                        if r_matches:
                            replacements = r_matches
                        data[original] = replacements
                    return data
                    
                print(f"Could not find JSON in response: {response_text[:100]}...")
                return {}
        except Exception as e:
            print(f"Failed to parse AI response: {e}")
            return {}

    def apply_rules(self) -> int:
        """
        Apply approved rules to generate 'tags_clean' for all images.
        Returns number of images updated.
        """
        # 1. Get all APPROVED rules
        rules = self.db.get_consolidation_rules(status='approved')
        rule_map = {r['original_tag']: r['replacement_tags'] for r in rules}
        
        if not rule_map:
            print("No approved rules to apply.")
            return 0
            
        # 2. Get all files with tags
        # We need to process ALL files because even if they don't have the specific tag in the rule,
        # we are regenerating the entire 'clean' set.
        # Actually, simpler: We only need to process files that contain tokens that are in our rule map.
        # BUT optimizing that query is hard.
        # Better: Iterate all files, re-compute clean tags.
        
        files = self.db.get_file_index() # Wait, db doesn't have get_file_index, gallery does.
        # DB has `get_tagged_filenames`.
        # However, we need the RAW tags to process.
        
        updated_count = 0
        batch = []
        
        with self.db.get_connection() as conn:
            cursor = conn.execute("SELECT filename, tags FROM image_tags WHERE tags IS NOT NULL")
            
            for row in cursor:
                filename = row['filename']
                raw_tags_str = row['tags']
                
                if not raw_tags_str:
                    continue
                    
                raw_tags = [t.strip() for t in raw_tags_str.split(',')]
                clean_set = set()
                
                for tag in raw_tags:
                    tag_lower = tag.lower()
                    if tag_lower in rule_map:
                        # Apply rule
                        clean_set.update(rule_map[tag_lower])
                    else:
                        # Keep original
                        clean_set.add(tag_lower)
                        
                # Join sorted
                final_clean_tags = ', '.join(sorted(clean_set))
                
                batch.append({
                    'filename': filename,
                    'tags_clean': final_clean_tags
                })
                
                if len(batch) >= 100:
                    self.db.save_clean_tags_batch(batch)
                    updated_count += len(batch)
                    batch = []
                    
            if batch:
                self.db.save_clean_tags_batch(batch)
                updated_count += len(batch)
                
        return updated_count
