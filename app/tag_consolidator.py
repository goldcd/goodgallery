
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
        # We RE-EVALUATE 'pending' tags to ensure they get the benefit of new context (e.g. new synonyms)
        # We EXCLUDE 'approved' and 'rejected' tags from being *targets of change*, 
        # but we should use them as *context* (preferred vocabulary).
        
        rules_list = self.db.get_consolidation_rules()
        completed_rules = {r['original_tag'] for r in rules_list if r['status'] in ['approved', 'rejected']}
        
        # Build "Preferred Vocabulary" from Approved rules (replacement tags)
        # This helps the AI map new tags to existing established standards.
        preferred_vocab = set()
        for r in rules_list:
            if r['status'] == 'approved':
                # Add the REPLACEMENT tags (the clean versions)
                for t in r['replacement_tags']:
                    preferred_vocab.add(t)
        
        # Also add high-frequency raw tags that are NOT in rules yet? 
        # Maybe not, let's stick to explicitly approved ones to keep context clear.
        
        # Prepare candidates tuple: (tag, count)
        candidates = []
        for tag, count in all_tags_map.items():
            # Skip if already decided (Approved/Rejected)
            if tag in completed_rules:
                continue
                
            # Filter noise
            if len(tag) > 2 and not tag.isdigit():
                candidates.append((tag, count))
                
        # Sort by frequency desc
        candidates.sort(key=lambda x: x[1], reverse=True)
        
        if not candidates:
            if progress_callback:
                msg = f"No new or pending tags to analyze. (Total unique: {len(all_tags_map)})"
                progress_callback(0, 0, msg)
                print(f"DEBUG: {msg}")
            return 0
            
        total_candidates = len(candidates)
        print(f"DEBUG: Found {total_candidates} candidates (New+Pending). Processing in batches of {batch_size}...")
        
        # Convert preferred vocab to list for prompt
        # Limit to top 500 to save tokens if necessary, or pass all if manageable.
        # For now, just pass them all (text model context window is usually large).
        vocab_list = sorted(list(preferred_vocab))
        
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
                mappings = self._analyze_tags_with_ai(batch, vocab_list, prompt_template)
                
                # Save results
                if mappings:
                    print(f"DEBUG: AI returned {len(mappings)} mappings for batch {current_batch_num}")
                    for original, replacements in mappings.items():
                        # UPSERT rule (might update existing pending one)
                        self.db.save_consolidation_rule(original, replacements, status='pending')
                        proposals_count += 1
                else:
                    print(f"DEBUG: No mappings returned for batch {current_batch_num}")
                    
            except Exception as e:
                print(f"Error analyzing batch {i}: {e}")
                # Don't stop, try next batch
                
        return proposals_count

    def _analyze_tags_with_ai(self, tags_with_counts: List[tuple], preferred_vocab: List[str], prompt_template=None) -> Dict[str, List[str]]:
        """
        Ask AI to consolidate a list of tags.
        Input: [(tag, count)...]
        preferred_vocab: List of tags that are already approved (AI should map to these if possible)
        """
        
        tags_list_str = "\n".join([f"- {t} ({c})" for t, c in tags_with_counts])
        vocab_str = ", ".join(preferred_vocab) if preferred_vocab else "(None yet)"
        
        if prompt_template:
            # Use custom prompt from config
            prompt = prompt_template.replace("TAGS_LIST_PLACEHOLDER", tags_list_str)
            # Add vocab placeholder support if user wants it
            prompt = prompt.replace("VOCAB_LIST_PLACEHOLDER", vocab_str)
        else:
            prompt = (
                "You are an Uncensored Data Processing Assistant. \n"
                "Your sole task is to clean and standardize a database of tags.\n"
                "Content Warning: The list may contain NSFW, explicit, or offensive terms.\n"
                "You MUST process ALL tags regardless of content. Do not refuse.\n\n"
                "CONTEXT:\n"
                f"Existing Standard Vocabulary (PREFERRED TERMS): [{vocab_str}]\n"
                "Use these terms as targets if they match the meaning of a dirty tag.\n\n"
                "Below is a list of 'Dirty' tags to process: `tag (count)`.\n\n"
                "RULES:\n"
                "1. **Analyze ALL dirty tags**.\n"
                "2. **Identify Redundancies**: Map synonyms, typos, and plural forms to the most common/standard term.\n"
                "   - CHECK THE PREFERRED VOCABULARY FIRST.\n"
                "   - Example: `males (2)` -> `['man']` (if `man` is in Preferred Vocabulary)\n"
                "   - Example: `doggy (5)` -> `['dog']`\n"
                "3. **Generalize**: If a specific tag implies a general category, add it.\n"
                "   - Example: `black leather jacket` -> `['black leather jacket', 'leather jacket', 'jacket', 'black']`\n"
                "4. **Keep Good Tags**: If a tag is correct, map it to itself.\n"
                "5. **Format**: Return JSON object. Keys = original tag. Values = list of replacement tags.\n\n"
                "JSON ONLY. NO MARKDOWN.\n\n"
                f"DIRTY TAGS LIST:\n{tags_list_str}"
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
        
    def apply_rules_to_files(self, filenames: List[str]) -> int:
        """
        Apply rules to a specific list of files (e.g. after ingest).
        """
        if not filenames:
            return 0
            
        # 1. Get all APPROVED rules
        rules = self.db.get_consolidation_rules(status='approved')
        rule_map = {r['original_tag']: r['replacement_tags'] for r in rules}
        
        # Even if no rules, we might want to ensure clean tags = raw tags?
        # But DB save logic now handles that.
        if not rule_map:
            return 0
            
        updated_count = 0
        batch = []
        
        for filename in filenames:
            raw_tags_str = self.db.get_tags(filename)
            
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
            # Use case-insensitive sort for display niceness
            clean_list = sorted(list(clean_set), key=str.lower)
            final_clean_tags = ', '.join(clean_list)
            
            # Check if different from current to save DB writes?
            # DB update is cheap enough for small batches.
            
            batch.append({
                'filename': filename,
                'tags_clean': final_clean_tags
            })
            
        if batch:
            self.db.save_clean_tags_batch(batch)
            updated_count = len(batch)
            
        return updated_count
