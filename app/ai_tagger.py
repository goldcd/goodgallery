"""
Good Gallery AI Tagger
LLaVA-based image tagging using HuggingFace Transformers
Ported STRICTLY from tagger_client_v2.py
"""

import os
import re
import concurrent.futures
from typing import List, Dict, Optional
from PIL import Image
import torch
from transformers import AutoProcessor, LlavaForConditionalGeneration

# Global device detection
def get_device():
    if torch.cuda.is_available():
        return "cuda"
    elif torch.backends.mps.is_available():
        return "mps"
    return "cpu"

class AITagger:
    def __init__(self, model_id: str = "llava-hf/llava-1.5-7b-hf", use_quantization: bool = True, batch_size: int = 15, tagging_prompt: str = None, cache_dir: str = None):
        self.model_id = model_id
        self.use_quantization = use_quantization
        self.batch_size = batch_size
        self.cache_dir = cache_dir
        self.device = get_device()
        
        # Disable quantization on non-CUDA devices (BitsAndBytes is CUDA-only)
        if self.device != "cuda" and self.use_quantization:
            print(f"[{self.device}] 4-bit quantization disabled (requires CUDA). Using float16 instead.")
            self.use_quantization = False
            
        # Default comprehensive prompt if not provided
        default_prompt = (
            "USER: <image>\n"
            "Analyze the image and generate a single, comprehensive, comma-separated list of keywords, "
            "listed in their descending importance as a description of the image\n"
            "Include keywords for: main objects, people (including names of famous figures if recognized), "
            "actions, location, time of day, lighting, artistic style, mood, fictional characters, memes, "
            "distinctive features and anything else that seems to be a relevant keyword to search on this image by.\n"
            "Do not transcribe text. Do not use categories or labels. Just keywords.\n"
            "Example: car, woman, running, beach, sunny, sketch, vintage, afternoon\n"
            "ASSISTANT:"
        )
        self.tagging_prompt = tagging_prompt or default_prompt
        self.model = None
        self.processor = None
        self.is_loaded = False
    
    def load_model(self):
        """
        Load LLaVA model into memory
        Matches 'get_model' in tagger_client_v2.py
        """
        if self.is_loaded:
            return
        
        print(f"Loading LLaVA model on {self.device.upper()} (this may take a while)...")
        print(f"  Using tagging prompt: {self.tagging_prompt[:80]}..." if len(self.tagging_prompt) > 80 else f"  Using tagging prompt: {self.tagging_prompt}")
        
        try:
            quantization_config = None
            
            # Windows/CUDA: Use BitsAndBytes if requested
            if self.device == "cuda" and self.use_quantization:
                try:
                    from transformers import BitsAndBytesConfig
                    quantization_config = BitsAndBytesConfig(
                        load_in_4bit=True,
                        bnb_4bit_compute_dtype=torch.float16
                    )
                except ImportError:
                    print("Warning: bitsandbytes not installed, falling back to float16")
            
            # Load Processor
            self.processor = AutoProcessor.from_pretrained(
                self.model_id, 
                use_fast=True,
                cache_dir=self.cache_dir
            )
            
            # Load Model
            if quantization_config:
                # 4-bit customized load (CUDA only)
                self.model = LlavaForConditionalGeneration.from_pretrained(
                    self.model_id,
                    quantization_config=quantization_config,
                    device_map="auto",
                    cache_dir=self.cache_dir
                )
            else:
                # Standard load (Mac M1/M2/M3, CPU, or non-quantized CUDA)
                self.model = LlavaForConditionalGeneration.from_pretrained(
                    self.model_id,
                    device_map=self.device, # Explicitly map to mps/cpu/cuda
                    torch_dtype=torch.float16, # Use float16 for efficiency on Mac too
                    cache_dir=self.cache_dir
                )
            
            print("[OK] Model loaded successfully!")
            self.is_loaded = True
            
            # Optional: Log memory just for confirmation
            try:
                footprint = self.model.get_memory_footprint() / 1024**3
                print(f"  Memory footprint: {footprint:.2f} GB")
            except:
                pass
            
        except Exception as e:
            print(f"Error loading model: {e}")
            if self.device == "cuda":
                print("Ensure you have installed: torch transformers accelerate bitsandbytes")
            raise

    def _load_image_worker(self, path: str):
        """Reference: tagger_client_v2.py:79-84"""
        try:
            return Image.open(path).convert("RGB"), path
        except Exception as e:
            print(f"Error loading {path}: {e}")
            return None, path
    
    def tag_batch(self, image_paths: List[str]) -> List[Dict[str, any]]:
        """
        Process batch - Matches 'process_batch' in tagger_client_v2.py
        """
        if not self.is_loaded:
            raise RuntimeError("Model not loaded")
        
        if not image_paths:
            return []
        
        results = []
        valid_images = []
        valid_paths = []
        
        try:
            # 1. Load images
            with concurrent.futures.ThreadPoolExecutor(max_workers=self.batch_size) as executor:
                loaded_data = list(executor.map(self._load_image_worker, image_paths))
            
            for img, path in loaded_data:
                if img:
                    valid_images.append(img)
                    valid_paths.append(path)
                else:
                    results.append({"filename": os.path.basename(path), "tags": ["error_loading"]})
            
            if not valid_images:
                return results
            
            # 2. Prompts - use configured prompt
            prompts = [self.tagging_prompt] * len(valid_images)
            
            # 3. Tokenize
            inputs = self.processor(
                text=prompts,
                images=valid_images,
                return_tensors="pt",
                padding=True
            ).to(self.device) # Dynamic device mapping
            
            # 4. Generate
            generate_ids = self.model.generate(
                **inputs,
                max_new_tokens=60,
                do_sample=True,
                temperature=0.6,
                top_p=0.9
            )
            
            # 5. Decode
            outputs = self.processor.batch_decode(
                generate_ids,
                skip_special_tokens=True,
                clean_up_tokenization_spaces=False
            )
            
            # 6. Parse
            # Reference: tagger_client_v2.py:138-201
            for i, output in enumerate(outputs):
                original_path = valid_paths[i]
                filename = os.path.basename(original_path)
                
                if "ASSISTANT:" in output:
                    response = output.split("ASSISTANT:")[-1].strip()
                else:
                    response = output.strip()
                
                # Cleanup Logic
                tags = self._clean_tags(response)
                
                # Truncate Logic
                tags = self._truncate_tags(tags)
                
                results.append({"filename": filename, "tags": tags})
                
        except Exception as e:
            print(f"Batch Processing Error: {e}")
            for path in valid_paths:
                if not any(r['filename'] == os.path.basename(path) for r in results):
                    results.append({"filename": os.path.basename(path), "tags": []})
        
        return results

    def _clean_tags(self, response: str) -> List[str]:
        """Reference: tagger_client_v2.py:147-183"""
        # Replace newlines with commas to handle list formats
        response = response.replace('\n', ',')
        
        # Remove common chatty prefixes/headers
        remove_patterns = [
            r'main objects\s*(&\s*people)?\s*:', 
            r'actions\s*(&\s*activities)?\s*:', 
            r'exact location\s*(&\s*landmarks)?\s*:', 
            r'time\s*(of day)?\s*(&\s*lighting)?\s*:',
            r'art style\s*(&\s*mood)?\s*:',
            r'distinctive features\s*:',
            r'keywords\s*:',
            # Remove numbering patterns like "1.", "1)", "[1]", or "- "
            r'\b\d+\.\s*', 
            r'\b\d+\)\s*',
            r'\[\d+\]\s*',
            r'-\s*'
        ]
        
        clean_response = response
        for pat in remove_patterns:
            clean_response = re.sub(pat, '', clean_response, flags=re.IGNORECASE)
            
        # Split by comma
        raw_tags = [tag.strip() for tag in clean_response.split(',')]
        
        seen = set()
        tags = []
        
        for tag in raw_tags:
            tag_lower = tag.lower().strip()
            
            # Skip empty or weird tags
            if not tag_lower: continue
            if ':' in tag_lower: continue # Skip ignored categories
            
            # Skip tags that are JUST numbers (e.g. "12", "11")
            if tag_lower.isdigit(): continue
            
            # Skip single characters (unless it's something meaningful, but usually noise)
            if len(tag_lower) < 2: continue
            
            if tag_lower not in seen:
                seen.add(tag_lower)
                tags.append(tag_lower)
        
        return tags

    def _truncate_tags(self, tags: List[str], max_length: int = 255) -> List[str]:
        """Reference: tagger_client_v2.py:191-201"""
        final_str = ",".join(tags)
        if len(final_str) <= max_length:
            return tags
            
        cut_str = final_str[:max_length]
        if "," in cut_str:
            cut_str = cut_str.rsplit(',', 1)[0]
        return cut_str.split(',')

    def unload_model(self):
        """
        Comprehensive GPU memory cleanup following PyTorch best practices.
        
        The key issue: PyTorch's memory allocator caches memory for reuse.
        Even after del + empty_cache(), nvidia-smi may show cached memory.
        This is normal, BUT we want to truly release it for other applications.
        """
        if self.model is not None:
            print("🧹 Unloading model and releasing GPU memory...")
            
            # Step 1: Move model to CPU first
            # This forces PyTorch to transfer all tensors from GPU->CPU,
            # which triggers GPU memory deallocation
            try:
                self.model = self.model.to('cpu')
                print("  [OK] Model moved to CPU")
            except Exception as e:
                print(f"  Warning during CPU transfer: {e}")
            
            # Step 2: Delete all references explicitly
            # Remove both model and processor references
            del self.model
            self.model = None
            
            if hasattr(self, 'processor') and self.processor is not None:
                del self.processor
            self.processor = None
            
            self.is_loaded = False
            
            # Step 3: Force Python garbage collection TWICE
            # First gc.collect() might not catch circular references
            # Second pass ensures everything is truly freed
            import gc
            gc.collect()
            gc.collect()
            print("  [OK] Python GC completed")
            
            # Step 4: CUDA cleanup sequence
            if torch.cuda.is_available():
                # Wait for all CUDA operations to complete
                torch.cuda.synchronize()
                
                # Empty the CUDA cache (frees cached but unused blocks)
                torch.cuda.empty_cache()
                
                # Additional cleanup for multi-process scenarios
                try:
                    torch.cuda.ipc_collect()
                except:
                    pass  # Not all PyTorch versions have this
                
                # Reset memory stats (helps with fragmentation tracking)
                try:
                    torch.cuda.reset_peak_memory_stats()
                    torch.cuda.reset_accumulated_memory_stats()
                except:
                    pass
                
                print("  [OK] CUDA cache cleared")
            
            print("[CLEANUP] Model unloaded - GPU memory should be released")
            print("          (Note: nvidia-smi may show small residual PyTorch overhead)")
