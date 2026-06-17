"""
Tests for Concord Agent semantics
"""
import json
import tempfile
import time
from pathlib import Path
import pytest

from concord import Agent, Intent, Event


class TestAgent(Agent):
    """Test agent that tracks calls"""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.handled = []
    
    def handle_intent(self, intent: Intent):
        self.handled.append(intent)
        super().handle_intent(intent)


def test_agent_initialization():
    """Test agent creates required directories"""
    with tempfile.TemporaryDirectory() as tmpdir:
        agent = TestAgent("test", base_path=tmpdir)
        
        assert agent.inbox.exists()
        assert agent.outbox.exists()
        assert agent.events_log.parent.exists()


def test_intent_processing():
    """Test agent processes intent and creates tombstone"""
    with tempfile.TemporaryDirectory() as tmpdir:
        agent = TestAgent("test", base_path=tmpdir)
        
        # Create an intent file
        intent_id = "test-123"
        intent_path = agent.inbox / f"{intent_id}.json"
        
        intent_data = {
            "id": intent_id,
            "op": "test_op",
            "args": {"foo": "bar"},
            "t0": time.time(),
        }
        
        with open(intent_path, "w") as f:
            json.dump(intent_data, f)
        
        # Process it
        agent.process_intent_file(intent_path)
        
        # Check tombstone exists
        assert not intent_path.exists()
        assert (agent.inbox / f"{intent_id}.json.done").exists()
        
        # Check event was emitted
        assert agent.events_log.exists()
        with open(agent.events_log) as f:
            event = json.loads(f.read().strip())
        assert event["id"] == intent_id
        assert event["event"] == "ack"


def test_exactly_once_semantics():
    """Test tombstones prevent reprocessing"""
    with tempfile.TemporaryDirectory() as tmpdir:
        agent = TestAgent("test", base_path=tmpdir)
        
        # Create and process an intent
        intent_id = "test-456"
        intent_path = agent.inbox / f"{intent_id}.json"
        
        intent_data = {
            "id": intent_id,
            "op": "test",
            "args": {},
            "t0": time.time(),
        }
        
        with open(intent_path, "w") as f:
            json.dump(intent_data, f)
        
        agent.process_intent_file(intent_path)
        
        # Simulate restart - agent should skip .done files
        agent2 = TestAgent("test", base_path=tmpdir)
        
        # Manually call poll once (not infinite loop)
        for path in agent2.inbox.iterdir():
            if (path.is_file() and 
                not str(path).endswith(".done") and
                path.name not in agent2.seen):
                agent2.seen.add(path.name)
                agent2.process_intent_file(path)
        
        # Should not have processed the .done file
        assert len(agent2.handled) == 0


def test_event_ordering():
    """Test events are appended in order"""
    with tempfile.TemporaryDirectory() as tmpdir:
        agent = TestAgent("test", base_path=tmpdir)
        
        # Emit multiple events
        events = [
            Event(id="1", event="a", t=time.time()),
            Event(id="2", event="b", t=time.time()),
            Event(id="3", event="c", t=time.time()),
        ]
        
        for event in events:
            agent.emit_event(event)
        
        # Read back and verify order
        with open(agent.events_log) as f:
            lines = f.readlines()
        
        assert len(lines) == 3
        for i, line in enumerate(lines):
            event = json.loads(line.strip())
            assert event["id"] == str(i + 1)
            assert event["event"] == ["a", "b", "c"][i]

