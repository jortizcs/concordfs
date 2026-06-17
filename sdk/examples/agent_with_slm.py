#!/usr/bin/env python3
"""
Concord agent with Small Language Model (SLM) integration

This agent:
1. Watches /tmp/concord/demo/inbox/ for intent files
2. Processes each intent by calling a small LLM (Qwen2.5-Coder-3B)
3. Appends an event to outbox/events.jsonl with model stats
4. Tombstones the intent with .done to prevent reprocessing

Now measures REAL model latency vs substrate latency!
"""

import sys
from pathlib import Path

# Add SDK to path for development
sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from concord import Agent, Intent, Event
import time
import subprocess
import json


class SLMAgent(Agent):
    """Agent that processes intents using a small language model"""
    
    def __init__(self, name: str, model_path: str, base_path: str = "/tmp/concord"):
        super().__init__(name, base_path)
        self.model_path = model_path
        self.llama_bin = "/opt/homebrew/bin/llama-cli"
        
        print(f"SLM Agent initialized")
        print(f"  Model: {Path(model_path).name}")
        print(f"  Size: {Path(model_path).stat().st_size / (1024**3):.2f} GB")
    
    def call_llm(self, prompt: str, max_tokens: int = 64) -> dict:
        """Call llama.cpp and measure latency"""
        t_start = time.time()
        
        try:
            # Call llama-cli with the prompt
            result = subprocess.run([
                self.llama_bin,
                "-m", self.model_path,
                "-p", prompt,
                "-n", str(max_tokens),
                "--temp", "0.7",
                "--no-warmup",
                "--no-cnv",  # No conversation mode
                "--log-disable",  # Disable logging for cleaner output
            ], capture_output=True, text=True, timeout=30)
            
            t_end = time.time()
            latency_ms = (t_end - t_start) * 1000
            
            # Extract the generated text (after the prompt)
            output = result.stdout.strip()
            
            # Count tokens (rough estimate from output)
            tokens_generated = len(output.split())
            
            return {
                "output": output[:200],  # Truncate for logging
                "latency_ms": latency_ms,
                "tokens": tokens_generated,
                "engine": "qwen2.5-coder-3b",
                "success": result.returncode == 0,
            }
        except subprocess.TimeoutExpired:
            return {
                "output": "ERROR: LLM timeout",
                "latency_ms": 30000,
                "tokens": 0,
                "engine": "qwen2.5-coder-3b",
                "success": False,
            }
        except Exception as e:
            return {
                "output": f"ERROR: {str(e)}",
                "latency_ms": 0,
                "tokens": 0,
                "engine": "qwen2.5-coder-3b",
                "success": False,
            }
    
    def handle_intent(self, intent: Intent) -> None:
        """Handle an intent by calling the SLM"""
        t1 = time.time()
        
        print(f"  Intent {intent.id[:8]}: op={intent.op}")
        
        # Build prompt from intent
        prompt = f"Task: {intent.op}\n"
        if intent.args:
            prompt += f"Args: {json.dumps(intent.args)}\n"
        prompt += "Response:"
        
        # Call the LLM
        llm_result = self.call_llm(prompt, max_tokens=64)
        
        # Emit event with full stats
        self.emit_event(Event(
            id=intent.id,
            event="completed" if llm_result["success"] else "error",
            t=time.time(),
            t1=t1,
            artifact=llm_result["output"],
            engine=llm_result["engine"],
            tokens=llm_result["tokens"],
        ))
        
        print(f"    -> LLM latency: {llm_result['latency_ms']:.1f}ms, tokens: {llm_result['tokens']}")


def main():
    # Path to the model
    model_path = Path(__file__).parent.parent.parent / "models" / "qwen2.5-coder-3b-instruct-q4_k_m.gguf"
    
    if not model_path.exists():
        print(f"ERROR: Model not found at {model_path}")
        print("Please download the model first:")
        print("  cd ../../models")
        print("  curl -L -o qwen2.5-coder-3b-instruct-q4_k_m.gguf \\")
        print("    'https://huggingface.co/Qwen/Qwen2.5-Coder-3B-Instruct-GGUF/resolve/main/qwen2.5-coder-3b-instruct-q4_k_m.gguf'")
        return 1
    
    agent = SLMAgent(name="demo", model_path=str(model_path))
    agent.run()


if __name__ == "__main__":
    exit(main() or 0)

