# Online learner of the ablation run (python3 -m mcts hl-report --run runs/move47/mcts-ablation-20261007/hl --every 50)

run runs/move47/mcts-ablation-20261007/hl: 30000 samples, final held-out nodes 5912, 383 updates, 157 accepted

| version | parent | samples at fit | held-out CE | held-out top-1 | regression CE | regression top-1 | guards |
|---|---|---|---|---|---|---|---|
| default-v1 | - | - | 2.5833 | 0.3315 | 2.6815 | 0.4333 | pass |
| hl-v050 | hl-v049 | 16963 | 2.4593 | 0.3518 | 2.6462 | 0.4000 | pass |
| hl-v100 | hl-v099 | 30000 | 2.4062 | 0.3730 | 2.6016 | 0.3533 | pass |
| hl-v150 | hl-v149 | 30000 | 2.2818 | 0.4061 | 2.5903 | 0.3800 | pass |
| hl-v157 | hl-v156 | 30000 | 2.2771 | 0.4070 | 2.5953 | 0.3733 | pass |

tree reuse: {"moves": 0, "version_changes_between_moves": 0, "changes_with_reused_tree": 0, "moves_with_reused_tree": 0, "mean_reused_root_n": 0}
update time: {"mean": 2.8271984334203655, "max": 5.614}
value model: {"status": "fitted", "version": "value-u0383", "n": 30000, "labelled": 25242, "heldout_q": {"n": 5912, "mse_model": 0.017002479037272294, "mse_playouts": 0.016508374036685626, "mse_const": 0.11584596351818172}, "heldout_game": {"n": 4972, "mse_model": 0.16151403821824323, "mse_playouts": 0.20105481320394208, "mse_const": 0.25000000000000017}}
mix: {"lam": {"status": "default", "pairs": 0, "lam": 0.5, "raw": null}, "beta": {"status": "default", "pairs": 0, "beta": 0.5, "raw": null}, "calib": {"status": "default", "pairs": 0, "a": 1.0, "b": 0.0, "raw_a": null, "raw_b": null}}
