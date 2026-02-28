"""
matrixmouse/router.py

Manages which model is active for the current task and role. 

Responsibilities:
    - Maintaining the cascade ladder: [small_coder, medium_coder, large_coder, 
    large_general]
    - Assigning models to roles: summariser (smallest/fastest), implementer 
    (coding-specialised), designer/critic (largest general)
    - Escalating to the next model tier when stuck.py signals a stuck state
    - Constructing a clean handoff context when escalating (summary of what 
    was tried, what failed)
    - Optionally de-escalating after a successful write+test cycle
    - Batching tasks of the same type to amortise model load time


Model tiers (example, configurable):
    - Tier 0 (summarisation): qwen3:4b
    - Tier 1 (implementation): qwen2.5-coder:7b
    - Tier 2 (implementation): qwen2.5-coder:14b
    - Tier 3 (implementation): qwen2.5-coder:30b
    - Tier 4 (design/critique/fallback): glm-4.7-flash:q4_K_M
"""

