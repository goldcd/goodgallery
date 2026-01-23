
from transformers import AutoConfig
model_id = "prithivMLmods/Qwen2.5-VL-7B-Abliterated-Caption-it"
print(f"Loading config for {model_id}...")
try:
    config = AutoConfig.from_pretrained(model_id, trust_remote_code=True)
    print(config)
except Exception as e:
    print(f"Error: {e}")
