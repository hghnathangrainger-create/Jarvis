"""
agents

AI Agent System for the Jarvis AI Operating System (Chapter 20).

Specialised agents that perform focused tasks under Jarvis Core's coordination.
Each agent handles a specific type of task: research, coding, content creation,
learning, trading analysis, and planner support.

Does NOT:
    - Execute actions directly (delegates to tools and subsystems).
    - Override the Planner or Security Manager.
    - Make financial decisions (trading agent is research/education only).
"""
