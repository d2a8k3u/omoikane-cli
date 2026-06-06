"""Spike 0.1 — inspect SDK surface."""
import inspect

print("=== Available toolsets ===")
from tools.registry import registry, discover_builtin_tools
discover_builtin_tools()
toolsets = sorted(set(t.toolset for t in registry._tools.values()) if hasattr(registry, '_tools') else {})
if not toolsets:
    # try other attrs
    print("registry attrs:", [a for a in dir(registry) if not a.startswith('_')])
    # try direct attr
    for attr_name in ['tools', '_tools_by_name', 'all_tools']:
        if hasattr(registry, attr_name):
            print(f"  has {attr_name}:", type(getattr(registry, attr_name)).__name__)
print("toolsets:", toolsets)

print("\n=== Toolset contents ===")
if hasattr(registry, '_tools'):
    by_set = {}
    for name, tool in registry._tools.items():
        by_set.setdefault(tool.toolset, []).append(name)
    for ts, tools in sorted(by_set.items()):
        print(f"  [{ts}]: {tools}")

print("\n=== AIAgent signature ===")
from run_agent import AIAgent
sig = inspect.signature(AIAgent.__init__)
for pname, p in sig.parameters.items():
    default = '' if p.default is inspect.Parameter.empty else f' = {p.default!r}'
    print(f"  {pname}: {p.annotation}{default}")

print("\n=== AIAgent methods ===")
methods = [m for m in dir(AIAgent) if not m.startswith('_') and callable(getattr(AIAgent, m))]
print(methods)

print("\n=== registry.register signature ===")
if hasattr(registry, 'register'):
    sig = inspect.signature(registry.register)
    for pname, p in sig.parameters.items():
        default = '' if p.default is inspect.Parameter.empty else f' = {p.default!r}'
        print(f"  {pname}{default}")
