"""Online Heuristic Learning for MCTS v2 (node move47::mcts-hl): see learner.py and the README
section "MCTS v2 online learning".

    from mcts.hl import OnlineLearner
    learner = OnlineLearner(run_dir)                       # resumes if run_dir has a state.json
    eng = MCTS(board, weights=learner.provider, learner=learner)
    ...; learner.update()                                  # after each decision
"""
from .learner import DEFAULTS, LearnerProvider, OnlineLearner

__all__ = ["OnlineLearner", "LearnerProvider", "DEFAULTS"]
