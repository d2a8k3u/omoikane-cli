"""Spike — inspect interrupt/steer/clear_interrupt + step_callback shape."""
import inspect
from run_agent import AIAgent

for m in ('interrupt', 'steer', 'clear_interrupt', 'run_conversation', 'chat'):
    fn = getattr(AIAgent, m)
    sig = inspect.signature(fn)
    print(f"\n=== AIAgent.{m}{sig} ===")
    doc = (fn.__doc__ or '').strip().split('\n')
    for line in doc[:8]:
        print(f"  {line}")
