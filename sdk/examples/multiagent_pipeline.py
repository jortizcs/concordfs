#!/usr/bin/env python3
"""
Multi-Agent Pipeline: Code → Test → Doc → Release

Demonstrates realistic agent coordination via filesystem:
- CAS bus for artifact sharing (hash references)
- Event log for coordination signals
- Policy files for access control
- Exactly-once semantics via tombstones
"""

import sys
import json
import subprocess
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from concord import Agent, Intent, Event
from concord.cas import get_cas_bus


# ============================================================================
# Agent 1: Code Generator (SLM-powered)
# ============================================================================

class CodeAgent(Agent):
    """Generates Python code using SLM"""
    
    def __init__(self, name: str, model_path: str, base_path: str = "/tmp/concord"):
        super().__init__(name, base_path)
        self.model_path = model_path
        self.llama_bin = "/opt/homebrew/bin/llama-cli"
        self.cas = get_cas_bus()
        
    def call_llm(self, prompt: str, max_tokens: int = 150) -> str:
        """Call SLM to generate code"""
        try:
            result = subprocess.run([
                self.llama_bin,
                "-m", self.model_path,
                "-p", prompt,
                "-n", str(max_tokens),
                "--temp", "0.3",
                "--no-warmup",
                "--no-cnv",
                "--log-disable",
            ], capture_output=True, text=True, timeout=30)
            
            return result.stdout.strip() if result.returncode == 0 else ""
        except Exception as e:
            print(f"LLM error: {e}")
            return ""
    
    def handle_intent(self, intent: Intent) -> None:
        """Generate code and store in CAS"""
        t1 = time.time()
        
        print(f"  CodeAgent: {intent.op}")
        
        if intent.op == "generate_function":
            func_name = intent.args.get("name", "example")
            func_desc = intent.args.get("description", "a utility function")
            
            # Use stub code for pipeline testing
            # (Can be replaced with LLM call later)
            code = f'''def {func_name}(n):
    """
    {func_desc.capitalize()}
    
    Args:
        n: Input parameter
        
    Returns:
        Result of computation
    """
    # TODO: Implement {func_name}
    return n * 2
'''
            
            # Store code in CAS
            code_hash = self.cas.put(code, content_type="text/x-python")
            print(f"    -> Generated code (hash: {code_hash[:8]}...)")
            
            self.emit_event(Event(
                id=intent.id,
                event="code_generated",
                t=time.time(),
                t1=t1,
                artifact=self.cas.ref(code_hash),
                engine="stub",
            ))
        else:
            self.emit_event(Event(
                id=intent.id,
                event="error",
                t=time.time(),
                t1=t1,
                artifact=f"Unknown op: {intent.op}",
            ))


# ============================================================================
# Agent 2: Test Runner
# ============================================================================

class TestAgent(Agent):
    """Runs tests on generated code"""
    
    def __init__(self, name: str, base_path: str = "/tmp/concord"):
        super().__init__(name, base_path)
        self.cas = get_cas_bus()
    
    def run_tests(self, code_hash: str) -> dict:
        """Run basic tests on code"""
        code = self.cas.get_text(code_hash)
        
        if not code:
            return {"passed": False, "error": "Code not found in CAS"}
        
        # Basic validation tests
        tests = {
            "syntax": False,
            "has_function": False,
            "has_docstring": False,
        }
        
        # Test 1: Syntax check
        try:
            compile(code, "<string>", "exec")
            tests["syntax"] = True
        except SyntaxError as e:
            return {"passed": False, "error": f"Syntax error: {e}", "tests": tests}
        
        # Test 2: Has function definition
        tests["has_function"] = "def " in code
        
        # Test 3: Has docstring
        tests["has_docstring"] = '"""' in code or "'''" in code
        
        passed = all(tests.values())
        
        return {
            "passed": passed,
            "tests": tests,
            "error": None if passed else "Some tests failed",
        }
    
    def handle_intent(self, intent: Intent) -> None:
        """Test code from CAS"""
        t1 = time.time()
        
        print(f"  TestAgent: {intent.op}")
        
        if intent.op == "test_code":
            code_ref = intent.args.get("code_ref")
            code_hash = self.cas.parse_ref(code_ref)
            
            if not code_hash:
                self.emit_event(Event(
                    id=intent.id,
                    event="test_error",
                    t=time.time(),
                    t1=t1,
                    artifact="Invalid CAS reference",
                ))
                return
            
            result = self.run_tests(code_hash)
            print(f"    -> Tests: {result}")
            
            self.emit_event(Event(
                id=intent.id,
                event="tests_completed" if result["passed"] else "tests_failed",
                t=time.time(),
                t1=t1,
                artifact=json.dumps(result),
            ))


# ============================================================================
# Agent 3: Documentation Generator (SLM-powered)
# ============================================================================

class DocAgent(Agent):
    """Generates documentation for code"""
    
    def __init__(self, name: str, model_path: str, base_path: str = "/tmp/concord"):
        super().__init__(name, base_path)
        self.model_path = model_path
        self.llama_bin = "/opt/homebrew/bin/llama-cli"
        self.cas = get_cas_bus()
    
    def call_llm(self, prompt: str, max_tokens: int = 100) -> str:
        """Call SLM to generate documentation"""
        try:
            result = subprocess.run([
                self.llama_bin,
                "-m", self.model_path,
                "-p", prompt,
                "-n", str(max_tokens),
                "--temp", "0.5",
                "--no-warmup",
                "--no-cnv",
                "--log-disable",
            ], capture_output=True, text=True, timeout=30)
            
            return result.stdout.strip() if result.returncode == 0 else ""
        except Exception as e:
            print(f"LLM error: {e}")
            return ""
    
    def handle_intent(self, intent: Intent) -> None:
        """Generate documentation for code"""
        t1 = time.time()
        
        print(f"  DocAgent: {intent.op}")
        
        if intent.op == "generate_docs":
            code_ref = intent.args.get("code_ref")
            code_hash = self.cas.parse_ref(code_ref)
            
            if not code_hash:
                self.emit_event(Event(
                    id=intent.id,
                    event="doc_error",
                    t=time.time(),
                    t1=t1,
                    artifact="Invalid CAS reference",
                ))
                return
            
            code = self.cas.get_text(code_hash)
            
            # Generate stub documentation
            docs = f"""# API Documentation

## Function

{code}

## Usage

This function provides the described functionality.

## Returns

Returns the computed result.
"""
            
            docs_hash = self.cas.put(docs, content_type="text/markdown")
            
            print(f"    -> Generated docs (hash: {docs_hash[:8]}...)")
            
            self.emit_event(Event(
                id=intent.id,
                event="docs_generated",
                t=time.time(),
                t1=t1,
                artifact=self.cas.ref(docs_hash),
                engine="stub",
            ))


# ============================================================================
# Agent 4: Release Manager (Policy-Gated)
# ============================================================================

class ReleaseAgent(Agent):
    """Handles releases with policy checks"""
    
    def __init__(self, name: str, base_path: str = "/tmp/concord"):
        super().__init__(name, base_path)
        self.cas = get_cas_bus()
        self.policy_dir = Path(base_path) / "_policy"
        self.policy_dir.mkdir(parents=True, exist_ok=True)
    
    def check_policy(self, intent: Intent) -> tuple[bool, str]:
        """Check if release is allowed by policy"""
        # Simple policy: must have code and docs references
        if "code_ref" not in intent.args:
            return False, "Missing code reference"
        
        if "docs_ref" not in intent.args:
            return False, "Missing documentation"
        
        if "test_result" not in intent.args:
            return False, "Missing test results"
        
        # Check test results
        test_result = intent.args["test_result"]
        if isinstance(test_result, str):
            test_result = json.loads(test_result)
        
        if not test_result.get("passed", False):
            return False, "Tests did not pass"
        
        return True, "Policy checks passed"
    
    def handle_intent(self, intent: Intent) -> None:
        """Release code if policy allows"""
        t1 = time.time()
        
        print(f"  ReleaseAgent: {intent.op}")
        
        if intent.op == "release":
            allowed, reason = self.check_policy(intent)
            
            if allowed:
                code_hash = self.cas.parse_ref(intent.args["code_ref"])
                docs_hash = self.cas.parse_ref(intent.args["docs_ref"])
                
                release_manifest = {
                    "code": code_hash,
                    "docs": docs_hash,
                    "tests": intent.args["test_result"],
                    "released_at": time.time(),
                }
                
                manifest_hash = self.cas.put(
                    json.dumps(release_manifest, indent=2),
                    content_type="application/json"
                )
                
                print(f"    -> Released (manifest: {manifest_hash[:8]}...)")
                
                self.emit_event(Event(
                    id=intent.id,
                    event="released",
                    t=time.time(),
                    t1=t1,
                    artifact=self.cas.ref(manifest_hash),
                ))
            else:
                print(f"    -> Release blocked: {reason}")
                
                self.emit_event(Event(
                    id=intent.id,
                    event="release_blocked",
                    t=time.time(),
                    t1=t1,
                    artifact=reason,
                ))


# ============================================================================
# Main: Run agents based on command line
# ============================================================================

def main():
    if len(sys.argv) < 2:
        print("Usage: python multiagent_pipeline.py <agent_type>")
        print("  agent_type: code | test | doc | release")
        sys.exit(1)
    
    agent_type = sys.argv[1]
    model_path = "../../models/qwen2.5-coder-3b-instruct-q4_k_m.gguf"
    
    if agent_type == "code":
        agent = CodeAgent("code", model_path=model_path)
        print("Starting Code Agent (SLM)")
    elif agent_type == "test":
        agent = TestAgent("test")
        print("Starting Test Agent")
    elif agent_type == "doc":
        agent = DocAgent("doc", model_path=model_path)
        print("Starting Doc Agent (SLM)")
    elif agent_type == "release":
        agent = ReleaseAgent("release")
        print("Starting Release Agent (Policy-Gated)")
    else:
        print(f"Unknown agent type: {agent_type}")
        sys.exit(1)
    
    agent.run()


if __name__ == "__main__":
    main()


