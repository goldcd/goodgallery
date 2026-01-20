import requests
import os
import json
import time
import torch
import re
from PIL import Image
from transformers import AutoProcessor, LlavaForConditionalGeneration, BitsAndBytesConfig

# --- CONFIGURATION ---
SERVER_URL = "https://bobpitch.com/anon/api.php" 
LOCAL_IMAGE_PATH = r"W:\anon"               
BATCH_SIZE = 20

def configure():
    global SERVER_URL, LOCAL_IMAGE_PATH
    print("\n--- Configuration Setup ---")
    if "localhost" in SERVER_URL:
        new_url = input(f"Enter Server URL [{SERVER_URL}]: ").strip()
        if new_url: SERVER_URL = new_url
    if not os.path.exists(LOCAL_IMAGE_PATH):
        new_path = input(f"Enter Local Image Path [{LOCAL_IMAGE_PATH}]: ").strip()
        if new_path: LOCAL_IMAGE_PATH = new_path
    print("---------------------------\n")

def get_model():
    print("Loading LLaVA model (this may take a while)...")
    
    # Quantization config for 4-bit loading (fits in ~6GB VRAM)
    quantization_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_compute_dtype=torch.float16
    )
    
    model_id = "llava-hf/llava-1.5-7b-hf"
    
    try:
        processor = AutoProcessor.from_pretrained(model_id, use_fast=True)
        model = LlavaForConditionalGeneration.from_pretrained(
            model_id, 
            quantization_config=quantization_config, 
            device_map="auto"
        )
        print("Model loaded successfully!")
        return model, processor
    except Exception as e:
        print(f"Error loading model: {e}")
        print("Ensure you have installed: torch transformers accelerate bitsandbytes")
        raise

def get_stats(session):
    try:
        resp = session.get(f"{SERVER_URL}?action=get_stats")
        resp.raise_for_status()
        data = resp.json()
        if "status" in data and data["status"] == "ok":
            print(f"\n[{data['tagged']} images tagged] - [{data['untagged']} remaining]")
            return data['untagged']
        return 0
    except Exception as e:
        print(f"Stats Error: {e}")
        return 0

def get_untagged_images(session, limit=100):
    try:
        resp = session.get(f"{SERVER_URL}?action=get_untagged&limit={limit}")
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            print(f"Server Error: {data['error']}")
            return []
        return data.get("files", [])
    except Exception as e:
        print(f"Connection Error: {e}")
        return []

import concurrent.futures

def load_image_worker(path):
    try:
        return Image.open(path).convert("RGB"), path
    except Exception as e:
        print(f"Error loading {path}: {e}")
        return None, path

def process_batch(model, processor, img_paths):
    if not img_paths: return []
    
    results = []
    valid_images = []
    valid_paths = []
    
    try:
        # 1. Load all images in parallel to speed up network drive reads
        with concurrent.futures.ThreadPoolExecutor(max_workers=BATCH_SIZE) as executor:
            loaded_data = list(executor.map(load_image_worker, img_paths))
        
        for img, p in loaded_data:
            if img:
                valid_images.append(img)
                valid_paths.append(p)
            else:
                results.append({"filename": os.path.basename(p), "tags": ["error_loading"]}) # Fail gracefully with explicit error tag

        if not valid_images: return results

        # 2. Prepare Prompts (One per image)
        # Detailed prompt asking for specific categories + distinctive features
        # Explicitly ask for NO labels to fix the "1. Category:" issue
        # Flattened prompt to avoid triggering list-mode in LLM
        prompt = (
            "USER: <image>\n"
            "Analyze the image and generate a single, comprehensive, comma-separated list of keywords, listed in their descending importance as a description of the image\n"
            "Include keywords for: main objects, people (including names of famous figures if recognized), actions, location, time of day, lighting, artistic style, mood, fictional characters, memes, distinctive features and anything else that seems to be a relevant keyword to search on this image by.\n"
            "Do not transcribe text. Do not use categories or labels. Just keywords.\n"
            "Example: car, woman, running, beach, sunny, sketch, vintage, afternoon\n"
            "ASSISTANT:"
        )
        prompts = [prompt] * len(valid_images)

        # 3. Batch Tokenize/Process
        # padding=True ensures all sequences are same length
        inputs = processor(text=prompts, images=valid_images, return_tensors="pt", padding=True).to("cuda")

        # 4. Generate
        generate_ids = model.generate(
            **inputs, 
            max_new_tokens=60,
            do_sample=True,
            temperature=0.6,
            top_p=0.9
        )

        # 5. Decode
        outputs = processor.batch_decode(generate_ids, skip_special_tokens=True, clean_up_tokenization_spaces=False)

        # 6. Parse Results
        for i, output in enumerate(outputs):
            original_path = valid_paths[i]
            filename = os.path.basename(original_path)

            if "ASSISTANT:" in output:
                response = output.split("ASSISTANT:")[-1].strip()
            else:
                response = output.strip()
            
            # Deduplicate logic AND cleanup
            # 1. Replace newlines with commas
            response = response.replace('\n', ',')

            # 2. AGGRESSIVE CLEANING: Strip known category headers logic
            # The LLM keeps outputting "Main objects:", "Actions:", etc. despite instructions.
            # We will regex remove them globally.
            # Pattern: matches "text & text:" or "text:" case insensitive
            # catch common ones from our prompt
            remove_patterns = [
                r'main objects\s*(&\s*people)?\s*:', 
                r'actions\s*(&\s*activities)?\s*:', 
                r'exact location\s*(&\s*landmarks)?\s*:', 
                r'time\s*(of day)?\s*(&\s*lighting)?\s*:',
                r'art style\s*(&\s*mood)?\s*:',
                r'distinctive features\s*:',
                r'\d+\.\s*', # "1. "
                r'-\s*'      # "- "
            ]
            
            clean_response = response
            for pat in remove_patterns:
                clean_response = re.sub(pat, '', clean_response, flags=re.IGNORECASE)
            
            raw_tags = [tag.strip() for tag in clean_response.split(',')]
            seen = set()
            tags = []
            
            for tag in raw_tags:
                tag_lower = tag.lower().strip()
                # Final sanity check: if tag still contains a colon, drop it (it's likely a label we missed)
                if ':' in tag_lower: continue 
                
                if tag_lower and tag_lower not in seen and len(tag_lower) > 1:
                    seen.add(tag_lower)
                    tags.append(tag_lower)
            
            # Print preview AFTER cleanup so user sees the real result
            print(f"  [{filename}] -> {tags[:5] + ['...'] if len(tags) > 5 else tags}")

            results.append({"filename": filename, "tags": tags})
            
            # --- TRUNCATION logic for 255 char limit ---
            # Re-join to check length, then cut if needed
            final_str = ",".join(tags)
            if len(final_str) > 255:
                # Cut to 255
                cut_str = final_str[:255]
                # If we cut in middle of word, trim to last comma
                if "," in cut_str:
                    cut_str = cut_str.rsplit(',', 1)[0]
                # Re-split to list
                tags = cut_str.split(',')
                # Update in result
                results[-1]["tags"] = tags # Update the last appended item

    except Exception as e:
        print(f"Batch Processing Error: {e}")
        # If batch fails, return empty tags for these files to avoid stalling
        for p in valid_paths:
             if not any(r['filename'] == os.path.basename(p) for r in results):
                results.append({"filename": os.path.basename(p), "tags": []})

    return results

def main():
    configure()
    model, processor = get_model()
    session = requests.Session()
    
    # 1. Startup Stats
    print("\nChecking server stats...")
    initial_untagged = get_stats(session)
    print(f"Images to process in this session: {initial_untagged}")
    
    total_processed_session = 0
    start_time_session = time.time()
    
    API_BATCH_SIZE = 150 # Fetch from server
    GPU_BATCH_SIZE = 15  # Process on GPU

    while True:
        # Rebuild cache before fetching the next batch (if we have processed anything)
        if total_processed_session > 0:
             print(f"  -> Triggering search index rebuild (Processed {total_processed_session})...")
             try: session.get(f"{SERVER_URL}?action=get_tags&rebuild=1")
             except: pass

        print(f"\nFetching next {API_BATCH_SIZE} untagged images...")
        files = get_untagged_images(session, limit=API_BATCH_SIZE)
        
        if not files:
            # Trigger rebuild on completion (if we processed anything this session)
            if total_processed_session > 0:
                 print(f"  -> Triggering final search index rebuild...")
                 try: session.get(f"{SERVER_URL}?action=get_tags&rebuild=1")
                 except: pass
            
            print("No untagged images found. Exiting...")
            break
            
        print(f"Fetched {len(files)} images. Processing in GPU batches of {GPU_BATCH_SIZE}...")
        
        # Process in chunks of GPU_BATCH_SIZE
        for i in range(0, len(files), GPU_BATCH_SIZE):
            batch_start_time = time.time()
            batch_files = files[i : i + GPU_BATCH_SIZE]
            
            # Filter for local existence
            batch_paths = []
            skipped_files = []
            for filename in batch_files:
                full_path = os.path.join(LOCAL_IMAGE_PATH, filename)
                if os.path.exists(full_path):
                    batch_paths.append(full_path)
                else:
                    print(f"Skipping missing file: {full_path}")
                    skipped_files.append(filename)
            
            if not batch_paths and not skipped_files: continue

            # Run Batch Inference
            current_batch_count = len(batch_paths)
            batch_results = []
            if batch_paths:
                print(f"Processing Batch {i//GPU_BATCH_SIZE + 1} ({current_batch_count} images)...")
                batch_results = process_batch(model, processor, batch_paths)
            
            # Add skipped files (Report as empty/missing to server to clear queue)
            for f in skipped_files:
                batch_results.append({"filename": f, "tags": ["error_missing"]})
            
            # Upload
            if batch_results:
                print(f"  -> Uploading batch results...")
                try:
                    resp = session.post(f"{SERVER_URL}?action=save_tags", json=batch_results)
                    print(f"  [DEBUG] Status: {resp.status_code}") 
                    print(f"  [DEBUG] Response: {resp.text[:500]}") # Print first 500 chars

                    if resp.ok and resp.json().get("status") == "ok":
                        # Logic to track stats
                        # Use batch_results length to include both processed AND skipped files
                        total_processed_session += len(batch_results)
                        
                        # ETA Calculation
                        elapsed = time.time() - start_time_session
                        if total_processed_session > 0:
                            avg_time_per_img = elapsed / total_processed_session
                        else:
                            avg_time_per_img = 0

                        remaining_in_session = max(0, initial_untagged - total_processed_session)
                        
                        # If we fetch more than initial (e.g. database grew), dynamic adjust
                        # For now, simplistic ETA based on initial snapshot
                        
                        eta_seconds = remaining_in_session * avg_time_per_img
                        check_mins = eta_seconds / 60
                        
                        print(f"  -> Saved. Session Total: {total_processed_session} | Avg: {avg_time_per_img:.2f}s/img | ETA: {check_mins:.1f} mins")
                        
                    else:
                        print(f"  -> Upload failed: {resp.text}")
                except Exception as e:
                    print(f"  -> Connection Error: {e}")
            


    # End of while loop logic (Completion)
    # We can't reach here in the current infinite loop, but we can do it when no files found


if __name__ == "__main__":
    main()
