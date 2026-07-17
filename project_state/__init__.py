"""
project_state package

Phase 89, Batch 1: a single, durable, manually-maintained record of
Jarvis's project context (see project_state_store.py) - branch, phase,
commit, suite result, and focus, each recorded only through Nathan's
own explicit "update jarvis project state: <field>=<value>" command.
Never populated from git, a subprocess, or the filesystem; not a
general key/value settings system.
"""
