# Heuristics book (version 367)

40 active rules; 550 proposals from 184 heuristic jobs: 45 accepted, 505 rejected. Rules are written by the model (heuristic jobs), checked by the rule language (gotree/heurdsl.py), and kept only when the learner's prior with the rule predicts held-out hybrid-search visit distributions better than without it, the tactical guards hold and the regression set does not get worse.

## Rules

### R1 third-line-knight-from-lone-stone

In open areas, the empty third-line point a knight's move from an opponent stone, with no stone around it, is a strong developing move.

```
? ? ? ? ?
? . . . ?
? . * . ?
? . . . ?
? O ? ? ?
```
- rule: `????? / ?...? / ?.*.? / ?...? / ?O??? ; line 3`
- weight: +1.086 now; proposed +0.600 by the model; history: hl-v005 +0.113, hl-v007 +0.045, hl-v008 +0.245, hl-v013 +0.145, hl-v031 +0.302, hl-v032 +0.340, hl-v035 +0.364, hl-v036 +0.392, hl-v038 +0.417, hl-v039 +0.427, hl-v041 +0.444, hl-v044 +0.464, hl-v045 +0.475, hl-v046 +0.507, hl-v048 +0.522, hl-v049 +0.536, hl-v050 +0.551, hl-v051 +0.578, hl-v053 +0.620, hl-v054 +0.591, hl-v055 +0.647, hl-v058 +0.623, hl-v060 +0.640, hl-v066 +0.683, hl-v067 +0.664, hl-v068 +0.688, hl-v071 +0.734, hl-v075 +0.836, hl-v077 +0.846, hl-v079 +0.749, hl-v082 +0.764, hl-v083 +0.808, hl-v085 +0.742, hl-v086 +0.706, hl-v089 +0.802, hl-v091 +0.714, hl-v092 +0.769, hl-v093 +0.705, hl-v095 +0.758, hl-v096 +0.740, hl-v097 +0.720, hl-v098 +0.733, hl-v100 +0.757, hl-v101 +0.726, hl-v102 +0.789, hl-v104 +0.733, hl-v105 +0.750, hl-v106 +0.721, hl-v107 +0.737, hl-v108 +0.676, hl-v109 +0.721, hl-v110 +0.759, hl-v113 +0.742, hl-v115 +0.791, hl-v126 +0.948, hl-v128 +1.005, hl-v129 +1.045, hl-v133 +0.959, hl-v141 +0.918, hl-v143 +1.034, hl-v146 +1.016, hl-v149 +1.036, hl-v151 +1.008, hl-v152 +1.096, hl-v154 +1.037, hl-v157 +0.908, hl-v158 +1.078, hl-v159 +1.037, hl-v161 +1.095, hl-v168 +1.128, hl-v182 +1.050, hl-v184 +1.196, hl-v187 +1.130, hl-v190 +1.052, hl-v192 +1.078, hl-v195 +1.104, hl-v197 +1.120, hl-v198 +1.107, hl-v203 +1.044, hl-v207 +1.152, hl-v212 +1.093, hl-v215 +1.139, hl-v217 +1.227, hl-v218 +1.144, hl-v220 +1.130, hl-v221 +1.153, hl-v223 +1.097, hl-v224 +1.086
- held-out effect at acceptance: CE 3.3597 without, 3.3576 with the rule at its fitted weight +0.113 (gain +0.00213 nats, 90% CI +0.00038 .. +0.00409 over nodes); at the model's weight +0.600: gain +0.00063; held-out positions matched 352 from 3 searches
- hits: {"positions": 14079, "moves": 29417, "top": 1012, "mass": 0.0758, "heldout_positions": 2790}
- rationale (model): S1: C5 (knight's move from D3, one-point jump from own E5) got 0.92 of visits but prior rank 6. S2: F7 (knight's move from Black E5) got 0.79 of visits but prior rank 19, and most other matches (C6, G6, C4, C3) were the next candidates. It also fires on unvisited points in S3/S5/S6, so the weight is small.
- provenance: heuristic job 119 after decision g0p2, surprises S1, S2, lessons G6, L8; proposal P6, accepted in hl-v005

### R2 third-line-knight-facing-opp-stone

On a third-line point with all eight neighbours empty, the knight's move from a lone opponent stone two lines further in (approach or corner point) is a big quiet move.

```
? O . ? ?
? . . . ?
? . * . ?
? . . . ?
? ? ? ? ?
```
- rule: `?O.?? / ?...? / ?.*.? / ?...? / ????? ; line 3`
- weight: +1.151 now; proposed +1.000 by the model; history: hl-v006 +0.036, hl-v007 +0.198, hl-v031 +0.225, hl-v036 +0.237, hl-v042 +0.249, hl-v045 +0.284, hl-v051 +0.309, hl-v054 +0.288, hl-v058 +0.302, hl-v060 +0.342, hl-v066 +0.444, hl-v067 +0.485, hl-v068 +0.563, hl-v071 +0.590, hl-v075 +0.531, hl-v077 +0.558, hl-v079 +0.596, hl-v082 +0.606, hl-v083 +0.576, hl-v085 +0.626, hl-v086 +0.637, hl-v087 +0.594, hl-v091 +0.621, hl-v092 +0.637, hl-v094 +0.605, hl-v095 +0.580, hl-v096 +0.656, hl-v097 +0.635, hl-v100 +0.692, hl-v101 +0.668, hl-v102 +0.628, hl-v104 +0.680, hl-v105 +0.668, hl-v109 +0.697, hl-v110 +0.653, hl-v115 +0.693, hl-v119 +0.729, hl-v126 +0.671, hl-v128 +0.653, hl-v129 +0.638, hl-v130 +0.721, hl-v132 +0.748, hl-v133 +0.777, hl-v136 +0.815, hl-v140 +0.872, hl-v141 +0.845, hl-v143 +0.767, hl-v146 +0.833, hl-v149 +0.747, hl-v150 +0.771, hl-v151 +0.787, hl-v154 +0.768, hl-v157 +0.818, hl-v158 +0.843, hl-v159 +0.944, hl-v161 +0.905, hl-v168 +0.951, hl-v174 +1.088, hl-v182 +1.129, hl-v184 +1.247, hl-v187 +1.270, hl-v190 +1.175, hl-v192 +1.152, hl-v195 +1.093, hl-v197 +1.109, hl-v203 +1.149, hl-v207 +1.235, hl-v212 +1.160, hl-v217 +1.208, hl-v218 +1.296, hl-v220 +1.269, hl-v223 +1.258, hl-v224 +1.151
- held-out effect at acceptance: CE 3.3576 without, 3.3570 with the rule at its fitted weight +0.036 (gain +0.00058 nats, 90% CI +0.00001 .. +0.00121 over nodes); at the model's weight +1.000: gain -0.02137; held-out positions matched 344 from 3 searches
- hits: {"positions": 10706, "moves": 21658, "top": 945, "mass": 0.0902, "heldout_positions": 2130}
- rationale (model): S2 F7 (share 0.79, prior rank 19) and S4 C5 (share 0.72, prior rank 7) are top moves of this shape; S6 D7 and F7 (shares 0.12 each, prior rank 16) and S5 D3 also match. The prior ranked all of them low behind contact moves.
- provenance: heuristic job 160 after decision g0p3, surprises S2, S4, S5, S6, lessons G5, G6, L8; proposal P9, accepted in hl-v006

### R3 atari-on-runaway-lone-stone

Putting a lone opponent stone with two liberties into atari when it escapes the ladder usually just helps it run, so treat such ataris with suspicion.

```
? ? ?
? * ?
? ? ?
```
- rule: `??? / ?*? / ??? ; atari, not ladder_capture, adj_opp(libs 2, size 1)`
- weight: +0.370 now; proposed -0.600 by the model; history: hl-v011 +0.109, hl-v031 +0.346, hl-v032 +0.388, hl-v034 +0.403, hl-v038 +0.435, hl-v039 +0.448, hl-v040 +0.475, hl-v041 +0.497, hl-v042 +0.459, hl-v045 +0.478, hl-v046 +0.465, hl-v047 +0.504, hl-v048 +0.491, hl-v049 +0.477, hl-v050 +0.489, hl-v051 +0.499, hl-v052 +0.462, hl-v053 +0.519, hl-v054 +0.573, hl-v058 +0.507, hl-v059 +0.484, hl-v060 +0.570, hl-v066 +0.503, hl-v067 +0.454, hl-v068 +0.410, hl-v075 +0.460, hl-v077 +0.436, hl-v079 +0.388, hl-v082 +0.441, hl-v086 +0.412, hl-v087 +0.471, hl-v089 +0.393, hl-v091 +0.327, hl-v092 +0.400, hl-v093 +0.291, hl-v096 +0.266, hl-v097 +0.371, hl-v098 +0.287, hl-v100 +0.306, hl-v102 +0.328, hl-v104 +0.367, hl-v105 +0.329, hl-v106 +0.358, hl-v107 +0.343, hl-v108 +0.328, hl-v109 +0.439, hl-v110 +0.281, hl-v113 +0.342, hl-v119 +0.384, hl-v128 +0.297, hl-v129 +0.260, hl-v130 +0.314, hl-v132 +0.372, hl-v133 +0.410, hl-v136 +0.371, hl-v139 +0.415, hl-v140 +0.439, hl-v141 +0.362, hl-v143 +0.273, hl-v146 +0.351, hl-v149 +0.540, hl-v150 +0.498, hl-v151 +0.521, hl-v152 +0.426, hl-v154 +0.411, hl-v157 +0.352, hl-v159 +0.286, hl-v161 +0.332, hl-v168 +0.370, hl-v182 +0.355, hl-v184 +0.453, hl-v187 +0.389, hl-v190 +0.330, hl-v192 +0.315, hl-v195 +0.453, hl-v197 +0.383, hl-v198 +0.338, hl-v203 +0.269, hl-v207 +0.354, hl-v212 +0.316, hl-v215 +0.291, hl-v217 +0.409, hl-v218 +0.449, hl-v220 +0.377, hl-v221 +0.428, hl-v223 +0.370  
  **The learned weight has the opposite sign to the model's proposal: the search does not support the direction the rule's text states; the rule stays only as a feature.**
- held-out effect at acceptance: CE 3.1574 without, 3.1568 with the rule at its fitted weight +0.109 (gain +0.00061 nats, 90% CI +0.00013 .. +0.00122 over searches); at the model's weight -0.600: gain -0.00768; held-out positions matched 127 from 3 searches
- hits: {"positions": 36781, "moves": 86362, "top": 5449, "mass": 0.1369, "heldout_positions": 7294}
- rationale (model): All 5 matches are moves the search rejected. In S4, D6 (prior 0.22, 0.002 of the visits) and C5 (0.16 vs 0.019) were the prior's top two moves, and F4 got 0.003. In S1, C5 got 0.022 of the visits against a prior of 0.050. The extension or hane was always better.
- provenance: heuristic job 236 after decision g0p5, surprises S1, S4, lessons -; proposal P16, accepted in hl-v011

### R4 descend-past-parallel-pair-when-short-of-libs

When your two-stone line runs beside an opponent two-stone line toward the edge and your chain has only two or three liberties, descend to the second line just past the end of their line to win the liberty race.

```
? ? X O ?
? ? X O ?
? ? * . ?
? ? . ? ?
? ? ? ? ?
```
- rule: `??XO? / ??XO? / ??*.? / ??.?? / ????? ; line 2, adj_own(libs 2-3), not self_atari`
- weight: +0.755 now; proposed +1.000 by the model; history: hl-v018 +1.047, hl-v031 +0.966, hl-v032 +0.922, hl-v034 +0.885, hl-v035 +0.875, hl-v038 +0.859, hl-v042 +0.844, hl-v045 +0.824, hl-v046 +0.792, hl-v047 +0.821, hl-v048 +0.783, hl-v049 +0.769, hl-v050 +0.729, hl-v051 +0.715, hl-v052 +0.674, hl-v053 +0.753, hl-v055 +0.724, hl-v058 +0.685, hl-v059 +0.699, hl-v066 +0.670, hl-v068 +0.644, hl-v071 +0.687, hl-v075 +0.574, hl-v077 +0.687, hl-v079 +0.698, hl-v082 +0.688, hl-v085 +0.773, hl-v086 +0.672, hl-v087 +0.717, hl-v089 +0.702, hl-v091 +0.612, hl-v092 +0.645, hl-v093 +0.586, hl-v094 +0.656, hl-v095 +0.601, hl-v096 +0.666, hl-v097 +0.708, hl-v098 +0.690, hl-v100 +0.657, hl-v101 +0.714, hl-v105 +0.646, hl-v107 +0.656, hl-v108 +0.712, hl-v109 +0.608, hl-v110 +0.771, hl-v113 +0.601, hl-v115 +0.739, hl-v126 +0.720, hl-v129 +0.595, hl-v130 +0.608, hl-v133 +0.679, hl-v136 +0.611, hl-v139 +0.718, hl-v140 +0.683, hl-v141 +0.650, hl-v143 +0.594, hl-v146 +0.463, hl-v149 +0.608, hl-v150 +0.598, hl-v151 +0.517, hl-v152 +0.619, hl-v154 +0.510, hl-v158 +0.454, hl-v159 +0.563, hl-v161 +0.584, hl-v168 +0.514, hl-v174 +0.714, hl-v182 +0.598, hl-v184 +0.645, hl-v187 +0.573, hl-v190 +0.680, hl-v192 +0.664, hl-v197 +0.633, hl-v198 +0.623, hl-v207 +0.712, hl-v212 +0.735, hl-v215 +0.599, hl-v217 +0.772, hl-v218 +0.858, hl-v220 +0.732, hl-v221 +0.766, hl-v223 +0.723, hl-v224 +0.755
- held-out effect at acceptance: CE 2.9282 without, 2.9219 with the rule at its fitted weight +1.047 (gain +0.00626 nats, 90% CI +0.00120 .. +0.01193 over searches); at the model's weight +1.000: gain +0.00615; held-out positions matched 206 from 6 searches
- hits: {"positions": 2057, "moves": 2189, "top": 355, "mass": 0.1527, "heldout_positions": 413}
- rationale (model): S2 and S5: Black's D4-D3 pair with 3 liberties sits beside White's E4-E3 pair. The search's top move, D2, got 84% and 98% of visits at 0.48 and 0.55. The learned prior gave it 0.023 and 0.029 (rank 9-10) and preferred the pushes E6/G5, which score 0.39-0.44. This narrows P22 (line 2 only) and P26 (liberty condition only) by requiring both. It matches 3 of 418 moves here, and 2 of those are the search's choice.
- provenance: heuristic job 376 after decision g0p10, surprises S2, S5, lessons -; proposal P29, accepted in hl-v018

### R5 extend-at-head-of-own-two-vs-contact

Extend at the head of your two-stone line when an opponent stone already touches that point; otherwise they hane at the head of your two stones.

```
? ? ? ? ?
? . . . ?
? . * O ?
? . X ? ?
? ? X ? ?
```
- rule: `????? / ?...? / ?.*O? / ?.X?? / ??X?? ; not self_atari`
- weight: +0.333 now; proposed +0.900 by the model; history: hl-v025 +0.426, hl-v031 +0.453, hl-v032 +0.426, hl-v034 +0.457, hl-v035 +0.512, hl-v036 +0.548, hl-v038 +0.565, hl-v040 +0.577, hl-v042 +0.565, hl-v043 +0.365, hl-v044 +0.556, hl-v045 +0.567, hl-v049 +0.543, hl-v051 +0.530, hl-v053 +0.478, hl-v054 +0.457, hl-v055 +0.425, hl-v058 +0.518, hl-v060 +0.560, hl-v066 +0.495, hl-v075 +0.464, hl-v077 +0.498, hl-v082 +0.483, hl-v083 +0.453, hl-v085 +0.405, hl-v086 +0.489, hl-v087 +0.502, hl-v091 +0.424, hl-v093 +0.461, hl-v094 +0.477, hl-v095 +0.406, hl-v096 +0.468, hl-v097 +0.425, hl-v098 +0.455, hl-v100 +0.485, hl-v102 +0.470, hl-v105 +0.508, hl-v106 +0.522, hl-v107 +0.476, hl-v108 +0.495, hl-v109 +0.478, hl-v110 +0.499, hl-v113 +0.552, hl-v115 +0.484, hl-v119 +0.512, hl-v128 +0.487, hl-v129 +0.545, hl-v130 +0.507, hl-v133 +0.486, hl-v136 +0.468, hl-v139 +0.254, hl-v140 +0.335, hl-v146 +0.258, hl-v149 +0.237, hl-v151 +0.301, hl-v152 +0.269, hl-v157 +0.231, hl-v158 +0.298, hl-v161 +0.224, hl-v168 +0.324, hl-v174 +0.410, hl-v182 +0.263, hl-v184 +0.320, hl-v187 +0.412, hl-v190 +0.357, hl-v192 +0.266, hl-v195 +0.311, hl-v197 +0.365, hl-v203 +0.304, hl-v207 +0.364, hl-v212 +0.278, hl-v215 +0.310, hl-v217 +0.427, hl-v218 +0.385, hl-v220 +0.486, hl-v221 +0.438, hl-v223 +0.354, hl-v224 +0.333
- held-out effect at acceptance: CE 2.7605 without, 2.7581 with the rule at its fitted weight +0.426 (gain +0.00244 nats, 90% CI +0.00046 .. +0.00462 over searches); at the model's weight +0.900: gain -0.00007; held-out positions matched 482 from 16 searches
- hits: {"positions": 6883, "moves": 7958, "top": 1846, "mass": 0.2327, "heldout_positions": 1341}
- rationale (model): S5: White's B7, at the head of its B6-B5 line next to Black's C7, took 93% of 498k visits at 0.616, but the prior ranked it 14th (0.016). S6: the same point (here the head of Black's C7-D7 line, touched by White's B6) was Black's second choice, at 25% and 0.405, against a 0.024 prior. It matches only B7 in all six positions (0.8% of legal moves). L17 and G18: the head of the stones in contact is the urgent point, and leaving it lets the opponent hane there twice.
- provenance: heuristic job 524 after decision g1p1, surprises S5, S6, lessons G18, L17; proposal P36, accepted in hl-v025

### R6 save-lone-armpit-stone

Extending your lone 2-liberty stone out of the armpit of the opponent's connected bend is usually a slow, heavy move; leave it and take a big point or vital point instead.

```
? ? ? ? ?
? ? ? ? ?
? ? * ? ?
? . X O ?
? ? O O ?
```
- rule: `????? / ????? / ??*?? / ?.XO? / ??OO? ; adj_own(libs 2, size 1), not self_atari`
- weight: +0.490 now; proposed -1.000 by the model; history: hl-v033 -0.777, hl-v034 -0.928, hl-v035 -0.826, hl-v036 -0.794, hl-v039 -0.762, hl-v040 -0.773, hl-v042 -0.808, hl-v046 -0.788, hl-v047 -0.798, hl-v048 -0.838, hl-v049 -0.810, hl-v052 -0.833, hl-v053 -0.857, hl-v054 -0.844, hl-v058 -0.831, hl-v059 -0.854, hl-v066 -0.775, hl-v067 -0.721, hl-v068 -0.788, hl-v071 -0.772, hl-v077 -0.667, hl-v079 -0.696, hl-v082 -0.672, hl-v083 -0.581, hl-v085 -0.617, hl-v086 -0.633, hl-v087 -0.722, hl-v091 -0.665, hl-v092 -0.545, hl-v093 -0.534, hl-v094 -0.475, hl-v095 -0.495, hl-v096 -0.547, hl-v097 -0.478, hl-v101 -0.425, hl-v104 -0.374, hl-v105 -0.404, hl-v106 -0.417, hl-v107 -0.433, hl-v108 -0.420, hl-v109 -0.369, hl-v113 -0.403, hl-v115 -0.361, hl-v128 -0.328, hl-v129 -0.358, hl-v130 -0.257, hl-v132 -0.289, hl-v133 -0.194, hl-v136 -0.234, hl-v140 -0.135, hl-v143 -0.166, hl-v146 -0.094, hl-v149 -0.054, hl-v150 +0.008, hl-v151 -0.102, hl-v152 -0.021, hl-v154 +0.041, hl-v157 +0.057, hl-v158 +0.115, hl-v159 +0.145, hl-v161 +0.172, hl-v168 +0.148, hl-v174 +0.180, hl-v182 +0.195, hl-v184 +0.174, hl-v187 +0.185, hl-v190 +0.170, hl-v192 +0.208, hl-v195 +0.193, hl-v197 +0.229, hl-v198 +0.164, hl-v203 +0.182, hl-v207 +0.194, hl-v212 +0.209, hl-v215 +0.197, hl-v217 +0.276, hl-v218 +0.224, hl-v220 +0.273, hl-v221 +0.385, hl-v224 +0.490  
  **The learned weight has the opposite sign to the model's proposal: the search does not support the direction the rule's text states; the rule stays only as a feature.**
- held-out effect at acceptance: CE 2.6789 without, 2.6765 with the rule at its fitted weight -0.777 (gain +0.00247 nats, 90% CI +0.00019 .. +0.00464 over searches); at the model's weight -1.000: gain +0.00198; held-out positions matched 346 from 16 searches
- hits: {"positions": 17102, "moves": 36236, "top": 3136, "mass": 0.1693, "heldout_positions": 3335}
- rationale (model): S2, S3, S4: White's save F7 of the armpit stone F6 had learned priors of 0.099, 0.070 and 0.061 but got only 0.2%, 0.5% and 0.1% of visits, scoring 0.61-0.65 against 0.69-0.72 for the search's choices. Lessons G57 and L59 found the same: direct saves of the armpit stone scored 0.55-0.57 against 0.61 for the best move.
- provenance: heuristic job 674 after decision g1p8, surprises S2, S3, S4, lessons G57, L59, L62; proposal P56, accepted in hl-v033

### R7 first-line-hane-under-crawling-second-line-chain

Hane on the first line under the end stone of an opponent's second-line chain that crawls beneath your third-line wall, next to your own second-line blocker; it shrinks their edge eye space, usually with tempo.

```
? ? X ? ?
? O O X ?
? . * . ?
# # # # #
# # # # #
```
- rule: `??X?? / ?OOX? / ?.*.? / ##### / ##### ; not self_atari`
- weight: +0.306 now; proposed +0.600 by the model; history: hl-v037 +0.488, hl-v038 +0.515, hl-v039 +0.557, hl-v040 +0.569, hl-v041 +0.581, hl-v044 +0.691, hl-v046 +0.722, hl-v047 +0.691, hl-v048 +0.705, hl-v049 +0.685, hl-v050 +0.647, hl-v051 +0.671, hl-v052 +0.690, hl-v053 +0.643, hl-v054 +0.748, hl-v055 +0.719, hl-v058 +0.697, hl-v059 +0.686, hl-v060 +0.659, hl-v062 +0.359, hl-v066 +0.445, hl-v067 +0.407, hl-v068 +0.461, hl-v071 +0.472, hl-v077 +0.409, hl-v079 +0.480, hl-v082 +0.518, hl-v083 +0.484, hl-v085 +0.451, hl-v086 +0.570, hl-v087 +0.502, hl-v089 +0.583, hl-v091 +0.613, hl-v092 +0.676, hl-v094 +0.621, hl-v095 +0.566, hl-v096 +0.670, hl-v098 +0.533, hl-v100 +0.518, hl-v102 +0.345, hl-v104 +0.317, hl-v105 +0.409, hl-v106 +0.234, hl-v107 +0.246, hl-v108 +0.227, hl-v109 +0.257, hl-v110 +0.242, hl-v115 +0.092, hl-v119 +0.264, hl-v126 +0.203, hl-v128 +0.267, hl-v129 +0.219, hl-v130 +0.270, hl-v132 +0.336, hl-v140 +0.317, hl-v141 +0.366, hl-v143 +0.417, hl-v146 +0.429, hl-v149 +0.385, hl-v151 +0.417, hl-v152 +0.166, hl-v154 +0.345, hl-v157 +0.311, hl-v159 +0.358, hl-v161 +0.442, hl-v168 +0.353, hl-v174 +0.458, hl-v182 +0.261, hl-v184 +0.287, hl-v187 +0.166, hl-v190 +0.227, hl-v192 +0.110, hl-v195 +0.022, hl-v198 +0.104, hl-v203 +0.152, hl-v207 +0.280, hl-v212 +0.311, hl-v215 +0.195, hl-v217 +0.292, hl-v218 +0.220, hl-v220 +0.286, hl-v221 +0.333, hl-v223 +0.274, hl-v224 +0.306
- held-out effect at acceptance: CE 2.6567 without, 2.6564 with the rule at its fitted weight +0.488 (gain +0.00030 nats, 90% CI +0.00000 .. +0.00073 over searches); at the model's weight +0.600: gain +0.00033; held-out positions matched 289 from 13 searches
- hits: {"positions": 19151, "moves": 22387, "top": 633, "mass": 0.0383, "heldout_positions": 3852}
- rationale (model): S6: J4 was the search's top move (0.556 share of 25.8M) while the prior gave 0.0054 (rank 23). S4's main line (C1 D2 J4) plays it as soon as the lower-left exchange is settled. Our wall stone on the third line above their end stone lies outside the 3x3 window. It matches 1.6% of legal moves.
- provenance: heuristic job 723 after decision g1p11, surprises S4, S6, lessons -; proposal P69, accepted in hl-v037

### R8 second-line-descent-at-head-vs-contact

Descending to the second line at the head of your line that runs toward the edge, beside their touching stone, is a slow endgame move, not an urgent head-of-two extension.

```
# # # # #
? . . . ?
? . * O ?
? . X ? ?
? ? X ? ?
```
- rule: `##### / ?...? / ?.*O? / ?.X?? / ??X?? ; not self_atari`
- weight: -0.237 now; proposed -0.700 by the model; history: hl-v056 -0.148, hl-v058 -0.305, hl-v059 -0.288, hl-v060 -0.337, hl-v066 -0.303, hl-v067 -0.328, hl-v068 -0.362, hl-v071 -0.318, hl-v075 -0.265, hl-v077 -0.223, hl-v082 -0.246, hl-v083 -0.229, hl-v085 -0.212, hl-v086 -0.231, hl-v089 -0.248, hl-v091 -0.126, hl-v092 -0.188, hl-v093 -0.249, hl-v094 -0.211, hl-v095 -0.190, hl-v096 -0.263, hl-v097 -0.233, hl-v098 -0.252, hl-v100 -0.362, hl-v101 -0.185, hl-v102 -0.247, hl-v104 -0.144, hl-v105 -0.229, hl-v106 -0.247, hl-v107 -0.329, hl-v108 -0.265, hl-v109 -0.196, hl-v110 -0.257, hl-v113 -0.281, hl-v119 -0.268, hl-v126 -0.350, hl-v128 -0.270, hl-v130 -0.217, hl-v132 -0.264, hl-v133 -0.215, hl-v136 -0.225, hl-v139 -0.114, hl-v140 -0.084, hl-v141 -0.228, hl-v143 -0.209, hl-v146 -0.146, hl-v149 -0.060, hl-v150 -0.141, hl-v151 -0.043, hl-v152 -0.118, hl-v154 -0.088, hl-v157 -0.040, hl-v158 -0.130, hl-v159 -0.221, hl-v161 -0.083, hl-v168 -0.199, hl-v174 -0.297, hl-v184 -0.316, hl-v187 -0.359, hl-v190 -0.323, hl-v192 -0.375, hl-v195 -0.256, hl-v197 -0.323, hl-v198 -0.307, hl-v207 -0.383, hl-v212 -0.342, hl-v215 -0.321, hl-v217 -0.431, hl-v220 -0.374, hl-v221 -0.349, hl-v223 -0.292, hl-v224 -0.237
- held-out effect at acceptance: CE 2.5896 without, 2.5891 with the rule at its fitted weight -0.148 (gain +0.00051 nats, 90% CI +0.00010 .. +0.00090 over searches); at the model's weight -0.700: gain -0.00120; held-out positions matched 1016 from 39 searches
- hits: {"positions": 3661, "moves": 3691, "top": 761, "mass": 0.1844, "heldout_positions": 705}
- rationale (model): R5 makes H7 (descent from F7-G7 toward the right edge beside White H8) the learned prior's top or second move in S1 (0.198), S2 (0.217), S4 (0.157) and S6 (0.185). The search gave it at most 1.1% of visits and scores of 0.27-0.31 against 0.40-0.45 for the best moves. In S1's main line it is played only after the top exchange.
- provenance: heuristic job 1010 after decision g2p10, surprises S1, S2, S4, S6, lessons -; proposal P118, accepted in hl-v056

### R9 slow-capture-of-abandoned-edge-stones

Capturing 1-3 opponent edge stones that they left in atari while playing elsewhere is usually slow; they are already dead, so take the vital or big point first.

```
? ? ?
? * ?
? ? ?
```
- rule: `??? / ?*? / ??? ; captures 1-3, dist_last 7-24, line 1-2, not escape`
- weight: -1.006 now; proposed -1.000 by the model; history: hl-v063 -0.713, hl-v066 -0.908, hl-v067 -0.919, hl-v068 -0.941, hl-v071 -0.975, hl-v075 -0.945, hl-v077 -1.029, hl-v079 -0.952, hl-v083 -0.917, hl-v085 -0.884, hl-v086 -0.828, hl-v087 -0.918, hl-v089 -0.829, hl-v091 -0.790, hl-v092 -0.766, hl-v094 -0.903, hl-v095 -0.849, hl-v096 -0.820, hl-v097 -0.793, hl-v098 -0.883, hl-v100 -0.859, hl-v102 -0.881, hl-v105 -0.965, hl-v106 -0.810, hl-v107 -0.934, hl-v108 -0.772, hl-v109 -0.826, hl-v110 -0.761, hl-v115 -0.863, hl-v119 -0.815, hl-v128 -0.714, hl-v129 -0.761, hl-v132 -0.744, hl-v133 -0.731, hl-v136 -0.823, hl-v139 -0.895, hl-v140 -1.004, hl-v141 -0.950, hl-v143 -0.913, hl-v146 -0.939, hl-v149 -0.870, hl-v150 -0.994, hl-v151 -0.892, hl-v152 -0.909, hl-v154 -0.827, hl-v157 -0.734, hl-v159 -0.749, hl-v161 -0.775, hl-v168 -0.733, hl-v174 -0.749, hl-v182 -0.841, hl-v184 -0.752, hl-v187 -0.706, hl-v190 -0.805, hl-v192 -0.836, hl-v195 -0.922, hl-v197 -0.886, hl-v198 -1.021, hl-v203 -0.954, hl-v207 -1.000, hl-v212 -0.914, hl-v215 -1.060, hl-v217 -1.014, hl-v218 -1.074, hl-v220 -1.002, hl-v221 -1.061, hl-v223 -1.006
- held-out effect at acceptance: CE 2.5849 without, 2.5836 with the rule at its fitted weight -0.713 (gain +0.00126 nats, 90% CI +0.00039 .. +0.00224 over searches); at the model's weight -1.000: gain +0.00123; held-out positions matched 195 from 21 searches
- hits: {"positions": 11386, "moves": 11995, "top": 2394, "mass": 0.1736, "heldout_positions": 2332}
- rationale (model): S1 and S4: capturing the abandoned C8-D8 pair at D9 was the learned prior's top move (0.28) but got only 0.001-0.003 of visits. Extending at D9 leaves the pair one liberty, so the capture can wait. S2: capturing the ladder-dead C2 at C1 was the prior's top move (0.32), share 0.001. The search preferred B9, D5 and H9. The rule matches exactly these three captures and no other move in the six positions (1% of legal moves). It excludes captures that rescue our own chain (escape) and captures right next to the opponent's last move, such as throw-ins (L149, G150).
- provenance: heuristic job 1098 after decision g2p16, surprises S1, S2, S4, lessons G150, L149; proposal P140, accepted in hl-v063

### R10 fill-own-knight-link-gap-in-centre

In the centre, fill a gap point of your own knight's-move link between a lone stone and your other stones, when no opponent stone touches it, before they can wedge and cut.

```
. . X
X * .
o o o
```
- rule: `..X / X*. / ooo ; line 3-9, not self_atari, adj_own(size 1)`
- weight: +0.161 now; proposed +0.600 by the model; history: hl-v065 -0.143, hl-v066 -0.369, hl-v067 -0.430, hl-v068 -0.416, hl-v071 -0.358, hl-v075 -0.445, hl-v077 -0.423, hl-v079 -0.344, hl-v082 -0.309, hl-v083 -0.277, hl-v085 -0.320, hl-v086 -0.302, hl-v087 -0.176, hl-v091 -0.303, hl-v092 -0.266, hl-v093 -0.462, hl-v094 -0.473, hl-v095 -0.538, hl-v096 -0.689, hl-v097 -0.717, hl-v098 -0.815, hl-v100 -0.715, hl-v101 -0.851, hl-v102 -0.765, hl-v104 -0.715, hl-v105 -0.757, hl-v106 -0.697, hl-v108 -0.721, hl-v109 -0.699, hl-v110 -0.625, hl-v113 -0.689, hl-v126 -0.675, hl-v129 -0.653, hl-v130 -0.623, hl-v132 -0.741, hl-v133 -0.727, hl-v136 -0.682, hl-v139 -0.708, hl-v140 -0.685, hl-v141 -0.644, hl-v143 -0.594, hl-v146 -0.569, hl-v149 -0.590, hl-v151 -0.531, hl-v152 -0.608, hl-v154 -0.540, hl-v157 -0.500, hl-v158 -0.534, hl-v159 -0.501, hl-v161 -0.416, hl-v168 -0.319, hl-v174 -0.289, hl-v182 -0.303, hl-v184 -0.107, hl-v187 -0.148, hl-v190 -0.276, hl-v195 -0.203, hl-v197 -0.088, hl-v198 +0.022, hl-v203 +0.054, hl-v207 +0.018, hl-v212 +0.068, hl-v215 -0.005, hl-v217 +0.162, hl-v218 +0.175, hl-v221 +0.241, hl-v223 +0.175, hl-v224 +0.161
- held-out effect at acceptance: CE 2.5804 without, 2.5801 with the rule at its fitted weight -0.143 (gain +0.00028 nats, 90% CI +0.00017 .. +0.00041 over searches); at the model's weight +0.600: gain -0.00270; held-out positions matched 1176 from 32 searches
- hits: {"positions": 2052, "moves": 2424, "top": 41, "mass": 0.0286, "heldout_positions": 403}
- rationale (model): S6: F5 (gap of E5-G4, joining E5 to the F6 wall) took 0.994 of the visits with prior 0.053 (rank 4); the other gap points F4/G5 were 2nd/3rd. S3: F4 (gap of E5-G4) took 0.997 with prior 0.044 (rank 4); F5 was 3rd. The prior instead favoured edge connections and B3.
- provenance: heuristic job 1124 after decision g2p18, surprises S3, S6, lessons L51; proposal P145, accepted in hl-v065

### R11 stretch-head-of-own-two-vs-side-press

When an opponent stone presses beside the head stone of your two-stone line, stretch one point straight out at the head so they cannot hane at the head of two stones.

```
? ? ? ? ?
? . . . ?
? . * . ?
? . X O ?
? ? X ? ?
```
- rule: `????? / ?...? / ?.*.? / ?.XO? / ??X?? ; not self_atari, line 3-9`
- weight: +0.548 now; proposed +0.600 by the model; history: hl-v072 +0.392, hl-v075 +0.432, hl-v079 +0.359, hl-v082 +0.448, hl-v083 +0.427, hl-v085 +0.389, hl-v086 +0.415, hl-v087 +0.491, hl-v089 +0.454, hl-v091 +0.397, hl-v092 +0.379, hl-v093 +0.450, hl-v094 +0.353, hl-v095 +0.434, hl-v097 +0.399, hl-v098 +0.475, hl-v100 +0.526, hl-v102 +0.451, hl-v104 +0.441, hl-v106 +0.465, hl-v108 +0.481, hl-v109 +0.471, hl-v110 +0.414, hl-v113 +0.427, hl-v115 +0.473, hl-v119 +0.530, hl-v126 +0.543, hl-v128 +0.458, hl-v130 +0.473, hl-v133 +0.495, hl-v136 +0.579, hl-v139 +0.651, hl-v140 +0.472, hl-v141 +0.517, hl-v143 +0.489, hl-v146 +0.447, hl-v149 +0.392, hl-v150 +0.547, hl-v151 +0.509, hl-v152 +0.484, hl-v154 +0.473, hl-v157 +0.570, hl-v158 +0.587, hl-v161 +0.556, hl-v168 +0.677, hl-v174 +0.758, hl-v182 +0.700, hl-v184 +0.835, hl-v187 +0.760, hl-v190 +0.615, hl-v192 +0.565, hl-v195 +0.514, hl-v197 +0.563, hl-v198 +0.513, hl-v203 +0.560, hl-v207 +0.651, hl-v212 +0.614, hl-v215 +0.529, hl-v217 +0.596, hl-v220 +0.541, hl-v223 +0.595, hl-v224 +0.548
- held-out effect at acceptance: CE 2.5835 without, 2.5830 with the rule at its fitted weight +0.392 (gain +0.00053 nats, 90% CI +0.00001 .. +0.00120 over searches); at the model's weight +0.600: gain +0.00056; held-out positions matched 251 from 29 searches
- hits: {"positions": 2504, "moves": 2536, "top": 299, "mass": 0.1149, "heldout_positions": 473}
- rationale (model): S2: C7 stretches White's C5-C6 pair past Black's D6; it took 0.71 of visits at the best winrate while the prior put the hane D7 first (0.20 vs 0.17). Complements R5 (opponent touching the stretch point itself); line 3+ excludes the second-line case of S1 B5, which was bad.
- provenance: heuristic job 1238 after decision A0g1p3, surprises S2, lessons G21, L19; proposal P156, accepted in hl-v072

### R12 capture-abandoned-armpit-stone

Capturing a lone opponent stone left in atari in the armpit of your own bend, after they played far away, is usually slow; take the big point first.

```
? ? ? ? ?
? ? ? ? ?
? ? * ? ?
? ? O X ?
? ? X X ?
```
- rule: `????? / ????? / ??*?? / ??OX? / ??XX? ; captures 1, dist_last 7-30`
- weight: -0.560 now; proposed -1.000 by the model; history: hl-v081 -0.621, hl-v082 -0.540, hl-v083 -0.501, hl-v085 -0.662, hl-v086 -0.710, hl-v087 -0.628, hl-v089 -0.695, hl-v091 -0.660, hl-v092 -0.567, hl-v093 -0.704, hl-v094 -0.765, hl-v096 -0.734, hl-v097 -0.660, hl-v098 -0.614, hl-v100 -0.679, hl-v102 -0.647, hl-v104 -0.691, hl-v105 -0.820, hl-v106 -0.734, hl-v107 -0.705, hl-v108 -0.781, hl-v109 -0.748, hl-v110 -0.952, hl-v113 -0.819, hl-v115 -0.904, hl-v119 -0.754, hl-v126 -0.792, hl-v128 -0.867, hl-v129 -0.904, hl-v130 -0.930, hl-v132 -0.948, hl-v133 -0.908, hl-v136 -0.934, hl-v139 -0.896, hl-v140 -0.954, hl-v143 -0.901, hl-v146 -0.928, hl-v149 -1.106, hl-v150 -0.941, hl-v152 -1.090, hl-v154 -1.004, hl-v157 -0.888, hl-v158 -0.936, hl-v159 -1.019, hl-v161 -1.061, hl-v168 -1.049, hl-v174 -0.904, hl-v182 -0.932, hl-v184 -0.948, hl-v187 -0.901, hl-v192 -0.861, hl-v195 -0.770, hl-v197 -0.785, hl-v198 -0.757, hl-v203 -0.853, hl-v207 -0.818, hl-v212 -0.787, hl-v215 -0.759, hl-v217 -0.802, hl-v218 -0.722, hl-v221 -0.739, hl-v223 -0.689, hl-v224 -0.560
- held-out effect at acceptance: CE 2.6030 without, 2.6025 with the rule at its fitted weight -0.621 (gain +0.00055 nats, 90% CI +0.00010 .. +0.00103 over searches); at the model's weight -1.000: gain +0.00041; held-out positions matched 146 from 33 searches
- hits: {"positions": 3982, "moves": 4157, "top": 661, "mass": 0.1511, "heldout_positions": 833}
- rationale (model): S2, S4: Black's capture at C4 of the abandoned C5 stone had learned prior 0.38-0.39 (rank 1) and model 0.82-0.88, but got only 0.6-0.9% of visits at 0.47-0.48. Instead the search took G7 or F3/G3 at 0.50-0.52. White had played elsewhere (dist_last 9 and 11), so the stone was already light, and capturing leaves Black's stone with 2 liberties between B4 and C3. This is R9's abandoned-stone logic for stones off the edge, limited to the armpit shape.
- provenance: heuristic job 1430 after decision A0g1p11, surprises S2, S4, lessons L99; proposal P171, accepted in hl-v081

### R13 kosumi-link-extension-of-lone-two-lib-stone

Extend your lone two-liberty stone onto a point diagonal to another of your stones, with both linking points empty, so it gains a liberty and is miai-connected instead of being chased alone.

```
X . ?
. * X
? ? ?
```
- rule: `X.? / .*X / ??? ; not self_atari, adj_own(libs 2, size 1), libs_after 3-4`
- weight: +0.884 now; proposed +0.500 by the model; history: hl-v099 +0.417, hl-v100 +0.648, hl-v101 +0.613, hl-v102 +0.678, hl-v104 +0.730, hl-v106 +0.754, hl-v107 +0.723, hl-v108 +0.755, hl-v109 +0.804, hl-v110 +0.766, hl-v115 +0.796, hl-v119 +0.843, hl-v126 +0.873, hl-v128 +0.789, hl-v129 +0.819, hl-v130 +0.776, hl-v132 +0.709, hl-v133 +0.692, hl-v136 +0.755, hl-v140 +0.860, hl-v143 +0.847, hl-v146 +0.799, hl-v149 +0.885, hl-v150 +0.915, hl-v152 +0.983, hl-v157 +0.952, hl-v158 +0.893, hl-v159 +0.997, hl-v168 +1.016, hl-v174 +1.114, hl-v182 +1.075, hl-v184 +1.136, hl-v187 +1.260, hl-v190 +1.196, hl-v192 +1.127, hl-v198 +1.050, hl-v203 +0.919, hl-v207 +0.942, hl-v212 +0.900, hl-v215 +0.778, hl-v217 +0.955, hl-v218 +0.870, hl-v220 +0.801, hl-v221 +0.691, hl-v223 +0.858, hl-v224 +0.884
- held-out effect at acceptance: CE 2.6309 without, 2.6304 with the rule at its fitted weight +0.417 (gain +0.00047 nats, 90% CI +0.00008 .. +0.00093 over searches); at the model's weight +0.500: gain +0.00050; held-out positions matched 669 from 55 searches
- hits: {"positions": 812, "moves": 950, "top": 243, "mass": 0.2581, "heldout_positions": 167}
- rationale (model): S3: E9 (extends the ladder-capturable F9 diagonal to own D8) took 0.356 of visits with prior 0.0098 (rank 21). S4: E9 took 0.971 with prior 0.008 (rank 24). It matches only E9 in S1, S3 and S4 (1% of legal moves); S1 is the one counter-case, where J6 had just created other urgent points.
- provenance: heuristic job 1700 after decision B0g1p29, surprises S3, S4, lessons -; proposal P206, accepted in hl-v099

### R14 one-two-point-contact-in-corner

On the corner 1-2 point, with the 1-1 point empty, a first-line move touching an opponent stone (a block of their edge crawl or a hane under their 2-2 stone) is often the key liberty or eye-space point of a corner fight.

```
# ? ? ? ?
# ? ? ? ?
# . * ? ?
# # # # #
# # # # #
```
- rule: `#???? / #???? / #.*?? / ##### / ##### ; not self_atari, adj_opp(size 1-40)`
- weight: +0.786 now; proposed +0.800 by the model; history: hl-v111 +0.461, hl-v113 +0.559, hl-v115 +0.513, hl-v119 +0.664, hl-v128 +0.639, hl-v129 +0.655, hl-v132 +0.669, hl-v133 +0.604, hl-v136 +0.699, hl-v139 +0.659, hl-v140 +0.711, hl-v141 +0.657, hl-v143 +0.682, hl-v146 +0.648, hl-v149 +0.530, hl-v150 +0.694, hl-v151 +0.599, hl-v154 +0.546, hl-v158 +0.477, hl-v159 +0.449, hl-v161 +0.521, hl-v182 +0.578, hl-v184 +0.529, hl-v187 +0.512, hl-v192 +0.523, hl-v195 +0.564, hl-v197 +0.532, hl-v198 +0.672, hl-v207 +0.496, hl-v212 +0.690, hl-v215 +0.735, hl-v217 +0.804, hl-v218 +0.673, hl-v220 +0.826, hl-v221 +0.725, hl-v223 +0.840, hl-v224 +0.786
- held-out effect at acceptance: CE 2.6605 without, 2.6570 with the rule at its fitted weight +0.461 (gain +0.00346 nats, 90% CI +0.00100 .. +0.00593 over searches); at the model's weight +0.800: gain +0.00276; held-out positions matched 6273 from 92 searches
- hits: {"positions": 25254, "moves": 50309, "top": 2768, "mass": 0.0918, "heldout_positions": 5140}
- rationale (model): S1 A8 (prior 0.036 rank 7, share 0.997), S3 B9 (0.0045 rank 28, share 0.841), S5 J8 (0.013 rank 20, share 0.980) are all corner 1-2 point contact moves. S4 B9 also got more visits than its prior (0.012 vs 0.004), and S1 J8 had the second-best winrate. The 3x3 shape plus line:1 cannot see the corner, so these moves are under-rated.
- provenance: heuristic job 1825 after decision A0g1p35, surprises S1, S3, S4, S5, lessons -; proposal P227, accepted in hl-v111

### R15 corner-2-1-under-crowded-2-2-block

In a crowded corner where the 2-2, 3-2, 2-3 and 3-3 points are all occupied, the empty 2-1 point beneath them is a vital eye and liberty point for both sides.

```
# ? s s ?
# . s s ?
# . * . ?
# # # # #
# # # # #
```
- rule: `#?ss? / #.ss? / #.*.? / ##### / ##### ; not self_atari`
- weight: +0.426 now; proposed +0.600 by the model; history: hl-v112 +0.320, hl-v113 +0.421, hl-v119 +0.462, hl-v126 +0.253, hl-v128 +0.379, hl-v129 +0.317, hl-v130 +0.279, hl-v132 +0.391, hl-v133 +0.305, hl-v136 +0.184, hl-v139 +0.304, hl-v140 +0.335, hl-v141 +0.450, hl-v143 +0.487, hl-v146 +0.414, hl-v149 +0.456, hl-v150 +0.545, hl-v152 +0.514, hl-v154 +0.502, hl-v157 +0.375, hl-v158 +0.233, hl-v159 +0.426, hl-v161 +0.346, hl-v168 +0.316, hl-v174 +0.384, hl-v182 +0.371, hl-v187 +0.355, hl-v190 +0.339, hl-v192 +0.357, hl-v195 +0.326, hl-v197 +0.370, hl-v198 +0.462, hl-v203 +0.439, hl-v207 +0.378, hl-v215 +0.403, hl-v217 +0.487, hl-v218 +0.398, hl-v220 +0.541, hl-v221 +0.508, hl-v223 +0.394, hl-v224 +0.426
- held-out effect at acceptance: CE 2.6570 without, 2.6565 with the rule at its fitted weight -0.290 (gain +0.00049 nats, 90% CI +0.00012 .. +0.00089 over searches); at the model's weight +0.600: gain -0.00292; held-out positions matched 2161 from 50 searches
- hits: {"positions": 19990, "moves": 20950, "top": 1434, "mass": 0.0728, "heldout_positions": 3962}
- rationale (model): B1 was the search's top move for White in S2 and S6 and for Black in S3 (shares 0.997, 0.50, 0.98) at prior rank 20-26. The mirror point A2 took 0.46 of the visits in S6 at prior rank 36. Both sides fight for the 2-1 point in the corner capturing race.
- provenance: heuristic job 1827 after decision B0g1p33, surprises S2, S3, S6, lessons -; proposal P229, accepted in hl-v112

### R16 connect-cut-lone-two-lib-stone-to-line

When the opponent already holds one link point between your lone two-liberty stone and your line of stones, connect solidly at the other link point before they atari and cut there.

```
O X ?
X * ?
X ? ?
```
- rule: `OX? / X*? / X?? ; not self_atari, adj_own(libs 2, size 1)`
- weight: +0.320 now; proposed +0.600 by the model; history: hl-v112 +0.320
- held-out effect at acceptance: CE 2.6570 without, 2.6566 with the rule at its fitted weight +0.322 (gain +0.00045 nats, 90% CI +0.00001 .. +0.00094 over searches); at the model's weight +0.600: gain +0.00031; held-out positions matched 2513 from 72 searches
- hits: {"positions": 25342, "moves": 27512, "top": 870, "mass": 0.0329, "heldout_positions": 5026}
- rationale (model): S1: J7 joins the two-liberty stone J8 to the H7-H6 wall after Black has taken H8. J8 presses Black's three-liberty top group, and the search gave J7 0.97 of the visits at prior rank 20. White also plays J7 later in the main lines of S2, S5 and S6. The third X keeps the rule off weak two-stone links like F2 in S6.
- provenance: heuristic job 1827 after decision B0g1p33, surprises S1, S2, S5, S6, lessons -; proposal P230, accepted in hl-v112

### R17 first-line-block-end-of-opp-crawl-under-wall

Block on the first line at the end of the opponent's first-line crawl of two or more stones, when your own second-line stone sits right above their end stone, so they cannot push further along the edge.

```
X ? ?
O * .
# # #
```
- rule: `X?? / O*. / ### ; line 1, not self_atari, adj_opp(libs 3-4, size 2-8)`
- weight: +0.844 now; proposed +0.800 by the model; history: hl-v114 +0.890, hl-v115 +1.176, hl-v126 +1.139, hl-v128 +1.115, hl-v129 +1.074, hl-v130 +1.090, hl-v132 +1.225, hl-v133 +1.144, hl-v136 +1.098, hl-v139 +1.087, hl-v141 +1.006, hl-v143 +1.163, hl-v146 +1.035, hl-v149 +1.072, hl-v150 +0.975, hl-v151 +1.068, hl-v152 +1.142, hl-v157 +1.071, hl-v159 +1.047, hl-v161 +0.989, hl-v168 +1.030, hl-v174 +1.095, hl-v182 +1.025, hl-v184 +1.003, hl-v187 +1.161, hl-v190 +1.012, hl-v195 +0.872, hl-v197 +1.084, hl-v198 +1.024, hl-v203 +0.943, hl-v207 +0.903, hl-v212 +0.914, hl-v217 +0.868, hl-v218 +0.851, hl-v220 +0.701, hl-v221 +0.599, hl-v223 +0.640, hl-v224 +0.844
- held-out effect at acceptance: CE 2.6567 without, 2.6557 with the rule at its fitted weight +0.890 (gain +0.00107 nats, 90% CI +0.00010 .. +0.00224 over searches); at the model's weight +0.800: gain +0.00105; held-out positions matched 396 from 32 searches
- hits: {"positions": 1634, "moves": 1645, "top": 250, "mass": 0.1468, "heldout_positions": 288}
- rationale (model): S5 E1 (0.946 of 244k visits, winrate 0.552 against 0.520 for the next move) at prior 0.014 rank 12. It is the first-line block at the end of Black's crawl B1-C1-D1 under White's D2. The line:1 penalty holds it down although it is the standard endgame stop.
- provenance: heuristic job 1852 after decision B0g1p37, surprises S5, lessons -; proposal P243, accepted in hl-v114

### R18 edge-hane-under-strong-opp-boundary-stone

On the first line, play directly under the opponent's second-line stone of a big safe chain when your own stone touches it diagonally; this edge hane or push settles the boundary and is bigger than it looks.

```
? ? ? ? ?
? ? O X ?
? . * ? ?
# # # # #
# # # # #
```
- rule: `????? / ??OX? / ?.*?? / ##### / ##### ; not self_atari, captures 0, adj_opp(libs 4, size 3-40)`
- weight: +0.434 now; proposed +0.600 by the model; history: hl-v118 +0.316, hl-v119 +0.610, hl-v126 +0.644, hl-v129 +0.624, hl-v130 +0.698, hl-v133 +0.628, hl-v139 +0.617, hl-v140 +0.689, hl-v141 +0.665, hl-v143 +0.742, hl-v146 +0.662, hl-v149 +0.712, hl-v150 +0.691, hl-v151 +0.660, hl-v152 +0.630, hl-v154 +0.580, hl-v157 +0.616, hl-v158 +0.639, hl-v159 +0.529, hl-v161 +0.619, hl-v168 +0.590, hl-v174 +0.613, hl-v182 +0.689, hl-v184 +0.611, hl-v187 +0.689, hl-v190 +0.529, hl-v192 +0.575, hl-v195 +0.531, hl-v197 +0.560, hl-v198 +0.547, hl-v203 +0.534, hl-v207 +0.554, hl-v212 +0.407, hl-v215 +0.447, hl-v217 +0.464, hl-v218 +0.420, hl-v220 +0.442, hl-v221 +0.491, hl-v223 +0.461, hl-v224 +0.434
- held-out effect at acceptance: CE 2.6257 without, 2.6241 with the rule at its fitted weight +0.316 (gain +0.00161 nats, 90% CI +0.00071 .. +0.00260 over searches); at the model's weight +0.600: gain +0.00154; held-out positions matched 5542 from 81 searches
- hits: {"positions": 31094, "moves": 46400, "top": 1308, "mass": 0.0486, "heldout_positions": 6154}
- rationale (model): S3 and S4: Black's edge hane J6, under White's H6 (part of a 10-stone chain) and diagonal to Black's H5 blocker, took 0.95 and 0.46 of visits at prior 0.028. S1: White's A6 under Black's B6, next to White's B5, took 0.31 at prior 0.008. If Black plays C9 instead, White descends to J6. L83 describes the same edge hane beside the bottom stone, diagonal to your blocker.
- provenance: heuristic job 1895 after decision B0g1p41, surprises S1, S3, S4, lessons L83; proposal P256, accepted in hl-v118

### R19 complete-cut-through-knights-move

When your stone already sits on one of the two middle points of the opponent's knight's move, play the other middle point to cut their stones apart.

```
? ? O
? * X
? O ?
```
- rule: `??O / ?*X / ?O? ; not self_atari`
- weight: +1.068 now; proposed +0.600 by the model; history: hl-v124 +0.483, hl-v126 +0.698, hl-v128 +0.774, hl-v129 +0.817, hl-v130 +0.798, hl-v136 +0.912, hl-v139 +0.850, hl-v140 +0.875, hl-v141 +0.907, hl-v143 +0.879, hl-v146 +0.850, hl-v149 +0.829, hl-v150 +0.903, hl-v151 +0.845, hl-v152 +0.899, hl-v154 +0.879, hl-v161 +0.911, hl-v168 +0.881, hl-v174 +0.926, hl-v182 +0.940, hl-v184 +0.973, hl-v190 +0.960, hl-v192 +0.980, hl-v195 +1.049, hl-v197 +1.017, hl-v198 +0.961, hl-v203 +0.874, hl-v207 +0.903, hl-v212 +0.946, hl-v217 +1.001, hl-v218 +1.020, hl-v220 +1.046, hl-v221 +1.065, hl-v223 +0.977, hl-v224 +1.068
- held-out effect at acceptance: CE 2.5901 without, 2.5852 with the rule at its fitted weight +0.484 (gain +0.00481 nats, 90% CI +0.00291 .. +0.00671 over searches); at the model's weight +0.600: gain +0.00452; held-out positions matched 4166 from 94 searches
- hits: {"positions": 16623, "moves": 21832, "top": 6268, "mass": 0.3283, "heldout_positions": 3294}
- rationale (model): S5 and S6: Black's E6 is wedged between White's D5 and E7. Black D6 completes the cut and took 92-95% of visits (0.45 vs 0.38 for the model's favourite E5). The learned prior ranked it only 2nd or 4th, and the model ranked it 6th or 7th.
- provenance: heuristic job 2040 after decision B0g2p6, surprises S5, S6, lessons -; proposal P282, accepted in hl-v124

### R20 attach-lone-stone-with-jump-support

Attach beside a lone opponent stone when your own stone sits a one-point jump behind the contact point, perpendicular to the contact, so the attachment is backed up and claims the side.

```
? ? ? ? ?
? . . . ?
? O * . ?
? . . . ?
? ? X ? ?
```
- rule: `????? / ?...? / ?O*.? / ?...? / ??X?? ; adj_opp(libs 4, size 1), line 3-9, not self_atari`
- weight: +0.793 now; proposed +0.700 by the model; history: hl-v125 +0.624, hl-v126 +0.762, hl-v128 +0.797, hl-v129 +0.815, hl-v130 +0.768, hl-v132 +0.804, hl-v133 +0.854, hl-v136 +0.763, hl-v140 +0.786, hl-v141 +0.719, hl-v143 +0.757, hl-v146 +0.790, hl-v149 +0.725, hl-v150 +0.779, hl-v151 +0.801, hl-v152 +0.820, hl-v154 +0.894, hl-v157 +0.698, hl-v158 +0.738, hl-v159 +0.855, hl-v161 +0.832, hl-v168 +0.806, hl-v174 +1.000, hl-v182 +0.894, hl-v184 +0.853, hl-v187 +0.919, hl-v190 +0.879, hl-v192 +0.902, hl-v195 +0.856, hl-v197 +0.874, hl-v198 +0.899, hl-v203 +0.915, hl-v207 +0.883, hl-v212 +0.792, hl-v215 +0.764, hl-v217 +0.823, hl-v218 +0.908, hl-v220 +0.767, hl-v221 +0.793
- held-out effect at acceptance: CE 2.5810 without, 2.5802 with the rule at its fitted weight +0.624 (gain +0.00077 nats, 90% CI +0.00018 .. +0.00145 over searches); at the model's weight +0.700: gain +0.00076; held-out positions matched 1526 from 47 searches
- hits: {"positions": 7993, "moves": 9356, "top": 416, "mass": 0.0523, "heldout_positions": 1564}
- rationale (model): S1: F7, attaching to E7 with F5 a one-point jump behind, took 0.89 of 8.6M visits at the best winrate. The learned prior ranked it 8th (0.038), and the model never proposed it. L19 describes the same supported attachment as the start of the best line.
- provenance: heuristic job 2001 after decision B0g2p4, surprises S1, lessons L19, L4; proposal P286, accepted in hl-v125

### R21 atari-crosscut-stone-from-outside

Ataring the opponent's lone two-liberty crosscutting stone from outside is usually slow even when the ladder works, because your own cut stones stay weak; take the big shape point instead.

```
? ? ? ? ?
? . ? ? ?
X O * ? ?
O X ? ? ?
? ? ? ? ?
```
- rule: `????? / ?.??? / XO*?? / OX??? / ????? ; atari, adj_opp(libs 2, size 1)`
- weight: -0.377 now; proposed -0.800 by the model; history: hl-v131 -0.180, hl-v133 -0.256, hl-v136 -0.281, hl-v139 -0.196, hl-v140 -0.310, hl-v141 -0.333, hl-v143 -0.288, hl-v149 -0.359, hl-v150 -0.397, hl-v151 -0.371, hl-v152 -0.333, hl-v154 -0.381, hl-v157 -0.349, hl-v159 -0.299, hl-v161 -0.433, hl-v168 -0.411, hl-v174 -0.434, hl-v182 -0.364, hl-v184 -0.451, hl-v190 -0.298, hl-v192 -0.365, hl-v195 -0.377, hl-v197 -0.418, hl-v198 -0.397, hl-v203 -0.301, hl-v207 -0.363, hl-v212 -0.298, hl-v215 -0.280, hl-v217 -0.495, hl-v218 -0.480, hl-v223 -0.444, hl-v224 -0.377
- held-out effect at acceptance: CE 2.5718 without, 2.5713 with the rule at its fitted weight -0.180 (gain +0.00059 nats, 90% CI +0.00009 .. +0.00116 over searches); at the model's weight -0.800: gain -0.00225; held-out positions matched 1795 from 84 searches
- hits: {"positions": 10845, "moves": 25655, "top": 2758, "mass": 0.2348, "heldout_positions": 2145}
- rationale (model): In S1 and S3 the ataris G6/F7 on the ladder-dead cutter F6 were the learned prior's top two (0.27-0.38, via R5 and the ladder/atari features) and the model's favourite (0.80/0.86). They scored only 0.34 against 0.43-0.45 for the left-side moves. In S4 G6 scored 0.43 against 0.54 for C7.
- provenance: heuristic job 2135 after decision A0g2p12, surprises S1, S3, S4, lessons G271; proposal P300, accepted in hl-v131

### R22 hane-head-of-parallel-opp-two

When your two-stone line and their two-stone line stand side by side, hane at the head of their pair, diagonally beyond your own head stone, before they hane at yours.

```
? ? ? ? ?
? . . . ?
? . * . ?
? X O ? ?
? X O ? ?
```
- rule: `????? / ?...? / ?.*.? / ?XO?? / ?XO?? ; not self_atari`
- weight: +0.620 now; proposed +0.600 by the model; history: hl-v135 +0.152, hl-v136 +0.200, hl-v139 +0.216, hl-v140 +0.305, hl-v141 +0.240, hl-v143 +0.333, hl-v146 +0.293, hl-v150 +0.333, hl-v151 +0.434, hl-v152 +0.268, hl-v154 +0.332, hl-v157 +0.286, hl-v158 +0.210, hl-v159 +0.179, hl-v161 +0.295, hl-v168 +0.330, hl-v174 +0.288, hl-v182 +0.349, hl-v184 +0.386, hl-v187 +0.298, hl-v190 +0.348, hl-v192 +0.368, hl-v197 +0.433, hl-v207 +0.343, hl-v212 +0.372, hl-v217 +0.455, hl-v218 +0.468, hl-v220 +0.456, hl-v221 +0.480, hl-v224 +0.620
- held-out effect at acceptance: CE 2.5602 without, 2.5599 with the rule at its fitted weight +0.152 (gain +0.00028 nats, 90% CI +0.00002 .. +0.00056 over searches); at the model's weight +0.600: gain -0.00073; held-out positions matched 1603 from 59 searches
- hits: {"positions": 4936, "moves": 5295, "top": 971, "mass": 0.1716, "heldout_positions": 980}
- rationale (model): S1: G4, the hane at the head of White's E4-F4 pair beside Black's E3-F3, took 99.6% of 15.5M visits. Its prior was only 0.30, while R11 gave the stretch a combined 0.29. S6: White's D3, the hane at the other head of Black's E3-F3 below White's E4-F4, got a 0.13 share against a 0.06 prior. It is also the search's main-line reply to G4 in S1. L135 found the same hane at the head was best.
- provenance: heuristic job 2172 after decision B0g2p12, surprises S1, S6, lessons L135; proposal P310, accepted in hl-v135

### R23 diagonal-move-beside-own-atari-stone-liberty

When your lone stone is in atari, a move diagonal to it right beside its last liberty neither saves it nor threatens much; the opponent simply captures, so escape or play elsewhere.

```
? ? ? ? ?
? ? ? ? ?
? O * ? ?
O X . ? ?
? O ? ? ?
```
- rule: `????? / ????? / ?O*?? / OX.?? / ?O??? ; captures 0`
- weight: -0.566 now; proposed -0.800 by the model; history: hl-v142 -0.177, hl-v143 -0.362, hl-v146 -0.326, hl-v149 -0.447, hl-v151 -0.416, hl-v152 -0.436, hl-v154 -0.382, hl-v157 -0.396, hl-v159 -0.420, hl-v161 -0.389, hl-v168 -0.461, hl-v174 -0.300, hl-v182 -0.333, hl-v184 -0.281, hl-v187 -0.175, hl-v190 -0.464, hl-v192 -0.364, hl-v195 -0.419, hl-v197 -0.310, hl-v198 -0.393, hl-v203 -0.437, hl-v207 -0.356, hl-v212 -0.403, hl-v215 -0.359, hl-v217 -0.252, hl-v218 -0.326, hl-v220 -0.303, hl-v221 -0.388, hl-v223 -0.478, hl-v224 -0.566
- held-out effect at acceptance: CE 2.5168 without, 2.5150 with the rule at its fitted weight -0.774 (gain +0.00175 nats, 90% CI +0.00103 .. +0.00245 over searches); at the model's weight -0.800: gain +0.00174; held-out positions matched 2298 from 79 searches
- hits: {"positions": 98668, "moves": 205160, "top": 1284, "mass": 0.0173, "heldout_positions": 19466}
- rationale (model): S3, S4, S6: with White's lone F6 in atari, the prior's top move G7 (diagonal to F6, beside its last liberty) got 0.47/0.48/0.33 prior but only 1.1%/4.3%/0.3% of visits at lower winrates; the search tenuki'd to B3/B6. In S5 it also matches the counter-atari D9 and B9 beside Black's atari'd C8, which the search ignored. L268 found the same: such a counter-move scored 0.46 against 0.58.
- provenance: heuristic job 2264 after decision A0g2p18, surprises S3, S4, S5, S6, lessons G285, L268; proposal P316, accepted in hl-v142

### R24 second-line-kosumi-under-opp-third-line-stone

On the second line, the empty point diagonally under an opponent's third-line stone, with the points between them and toward the edge empty, undermines its base and is a big quiet move.

```
# ? ? ? ?
# . . O ?
# . * . ?
# . . . ?
# ? ? ? ?
```
- rule: `#???? / #..O? / #.*.? / #...? / #???? ; not self_atari`
- weight: -0.177 now; proposed +0.600 by the model; history: hl-v142 -0.177  
  **The learned weight has the opposite sign to the model's proposal: the search does not support the direction the rule's text states; the rule stays only as a feature.**
- held-out effect at acceptance: CE 2.5168 without, 2.5164 with the rule at its fitted weight -0.173 (gain +0.00034 nats, 90% CI +0.00009 .. +0.00058 over searches); at the model's weight +0.600: gain -0.00458; held-out positions matched 8980 from 73 searches
- hits: {"positions": 89754, "moves": 215346, "top": 838, "mass": 0.015, "heldout_positions": 17960}
- rationale (model): S2: B6 under White's C7 took 93% of visits with a prior of 0.004 (rank 23). S3/S4: B3 under the end of Black's C4-C6 wall took 83-85% with a prior of 0.007 (rank 19). The rule matches 16 of 359 legal moves, 3 of them search top moves.
- provenance: heuristic job 2264 after decision A0g2p18, surprises S2, S3, S4, lessons G276; proposal P317, accepted in hl-v142

### R25 extend-two-lib-group-to-three-libs

When your chain of two or more stones is down to two liberties, extending it so it has three or more liberties is usually more urgent than a hane or a move elsewhere.

```
? ? ?
? * ?
? ? ?
```
- rule: `??? / ?*? / ??? ; adj_own(libs 2, size 2-40), libs_after 3-4`
- weight: +0.680 now; proposed +0.800 by the model; history: hl-v144 +0.780, hl-v146 +0.805, hl-v149 +0.784, hl-v150 +0.809, hl-v152 +0.832, hl-v154 +0.790, hl-v157 +0.769, hl-v159 +0.709, hl-v168 +0.826, hl-v174 +0.813, hl-v182 +0.799, hl-v184 +0.643, hl-v187 +0.612, hl-v190 +0.715, hl-v192 +0.731, hl-v195 +0.649, hl-v197 +0.614, hl-v198 +0.514, hl-v203 +0.633, hl-v207 +0.528, hl-v212 +0.472, hl-v215 +0.490, hl-v217 +0.451, hl-v218 +0.552, hl-v220 +0.516, hl-v221 +0.658, hl-v223 +0.733, hl-v224 +0.680
- held-out effect at acceptance: CE 2.5105 without, 2.5092 with the rule at its fitted weight +0.780 (gain +0.00134 nats, 90% CI +0.00016 .. +0.00259 over searches); at the model's weight +0.800: gain +0.00131; held-out positions matched 1219 from 72 searches
- hits: {"positions": 18995, "moves": 30662, "top": 3207, "mass": 0.1573, "heldout_positions": 3746}
- rationale (model): S5: Black's eyeless 4-stone group had 2 liberties. The extension F8 gave it 3 liberties and took 97% of visits at 0.19, but the prior ranked it 11th (0.017). The prior's hane G8 scored 0.10. Base features reward escapes only from atari, so nothing in the prior covers this. In the S1 and S6 lines the same point was the key point for both sides.
- provenance: heuristic job 2265 after decision A0g2p20, surprises S1, S5, lessons G150; proposal P323, accepted in hl-v144

### R26 fill-liberty-of-big-three-lib-chain

When a large opponent chain of five or more stones is down to three liberties, taking one of those liberties (without self-atari) is usually the urgent move of a capturing race, ahead of side ataris on small chains.

```
? ? ?
? * ?
? ? ?
```
- rule: `??? / ?*? / ??? ; adj_opp(libs 3, size 5-40), not self_atari`
- weight: +1.577 now; proposed +0.900 by the model; history: hl-v148 +0.892, hl-v149 +0.981, hl-v150 +1.114, hl-v151 +1.173, hl-v152 +1.113, hl-v154 +1.364, hl-v157 +1.700, hl-v158 +1.720, hl-v159 +1.681, hl-v161 +1.710, hl-v168 +1.839, hl-v174 +1.736, hl-v184 +1.709, hl-v187 +1.699, hl-v190 +1.797, hl-v192 +1.704, hl-v195 +1.747, hl-v197 +1.571, hl-v198 +1.502, hl-v203 +1.436, hl-v207 +1.536, hl-v212 +1.668, hl-v215 +1.413, hl-v217 +1.472, hl-v218 +1.523, hl-v220 +1.541, hl-v221 +1.507, hl-v223 +1.577
- held-out effect at acceptance: CE 2.4901 without, 2.4890 with the rule at its fitted weight +0.892 (gain +0.00111 nats, 90% CI +0.00022 .. +0.00208 over searches); at the model's weight +0.900: gain +0.00111; held-out positions matched 298 from 26 searches
- hits: {"positions": 2873, "moves": 5948, "top": 831, "mass": 0.2667, "heldout_positions": 584}
- rationale (model): In S3, S4 and S5 the search's top move (G1, D4, G1; 91-99% of visits, winrate 0.92-0.95) took a liberty of White's eyeless 10-stone chain with 3 liberties. The learned prior ranked it 10th. The prior's favourite side atari (G6) scored 0.31 because White then extended at D4 and won the race. Lessons G237, G296 and G308 likewise say to count and settle the big chain's liberty race before ataris elsewhere.
- provenance: heuristic job 2323 after decision A0g2p28, surprises S3, S4, S5, lessons G237, G296, G308; proposal P341, accepted in hl-v148

### R27 edge-connect-across-opp-cut

On the first line, connect your edge stone to your own stone directly above it when an opponent stone sits on the cutting diagonal and one of the chains is short of liberties; it removes the cut and atari before capturing elsewhere.

```
O X ?
X * ?
# # #
```
- rule: `OX? / X*? / ### ; not self_atari, adj_own(libs 1-2)`
- weight: +1.095 now; proposed +0.800 by the model; history: hl-v155 +0.256, hl-v157 +0.810, hl-v158 +1.053, hl-v159 +0.988, hl-v161 +1.046, hl-v168 +1.173, hl-v174 +1.157, hl-v182 +1.169, hl-v184 +1.149, hl-v187 +1.169, hl-v190 +1.200, hl-v192 +1.227, hl-v195 +1.125, hl-v197 +1.064, hl-v203 +1.112, hl-v207 +1.196, hl-v212 +1.290, hl-v215 +1.430, hl-v217 +1.378, hl-v218 +1.439, hl-v220 +1.341, hl-v221 +1.351, hl-v223 +1.322, hl-v224 +1.095
- held-out effect at acceptance: CE 2.4780 without, 2.4774 with the rule at its fitted weight +0.256 (gain +0.00057 nats, 90% CI +0.00005 .. +0.00121 over searches); at the model's weight +0.800: gain -0.00138; held-out positions matched 3295 from 62 searches
- hits: {"positions": 12609, "moves": 13980, "top": 926, "mass": 0.0695, "heldout_positions": 2528}
- rationale (model): S1: D9 joining C9 (2 libs) to D8-E8 under White's C8 took 0.955 of visits at 0.725, but the prior had it at 0.026 (rank 6) and preferred the slow capture D4 (0.660). S3/S6: C9 saving D9 from atari and joining B9 and C8 across Black's B8/D8 took 0.89/0.83 of visits, but the prior had it at 0.021 (rank 4-5) and preferred capturing A8, which allows a ko at C9/D9. Rule-test: 5 matches in 312 legal moves, 3 of them the search's top move.
- provenance: heuristic job 2427 after decision B0g2p28, surprises S1, S3, S6, lessons G311, G314; proposal P361, accepted in hl-v155

### R28 lone-stone-in-armpit-of-strong-chain

A lone stone dropped into the inner corner of a strong opponent chain's bend, with no friendly stone around, gets only two liberties and is simply ataried; it is a poor invasion or reduction point.

```
x . x
. * O
x O O
```
- rule: `x.x / .*O / xOO ; libs_after 2, captures 0, adj_opp(libs 4)`
- weight: -0.981 now; proposed -0.800 by the model; history: hl-v166 -0.681, hl-v168 -0.786, hl-v174 -0.846, hl-v182 -0.973, hl-v187 -1.029, hl-v190 -1.073, hl-v192 -1.104, hl-v195 -1.093, hl-v197 -1.145, hl-v198 -1.133, hl-v203 -1.073, hl-v212 -1.091, hl-v218 -1.070, hl-v220 -0.993, hl-v221 -0.930, hl-v223 -0.999, hl-v224 -0.981
- held-out effect at acceptance: CE 2.4763 without, 2.4760 with the rule at its fitted weight -0.681 (gain +0.00031 nats, 90% CI +0.00007 .. +0.00051 over searches); at the model's weight -0.800: gain +0.00027; held-out positions matched 1669 from 73 searches
- hits: {"positions": 11237, "moves": 12839, "top": 149, "mass": 0.0154, "heldout_positions": 2216}
- rationale (model): S4: C3 into the armpit of White's D3-D2-C2 bend was the learned prior's top move (0.141) but got 0.080 share at the worst winrate (0.000); S5: C6 into the armpit of the C7-D7-D6 bend was again the prior's top (0.184) but got only 0.038 share. In both the search preferred invasion points with room (B6, C4, B4, B3). The rule fires on just 1.1% of legal moves in the surprises.
- provenance: heuristic job 2607 after decision B0g2p38, surprises S4, S5, lessons G323; proposal P388, accepted in hl-v166

### R29 butt-between-own-and-opp-jump-stones

In open space, the empty point directly between your healthy stone and a healthy opponent stone a one-point jump away butts head-on into their stone; it strengthens both and is usually a poor move.

```
x . x
X * O
x . x
```
- rule: `x.x / X*O / x.x ; adj_opp(libs 4), adj_own(libs 4)`
- weight: -0.791 now; proposed -0.800 by the model; history: hl-v171 -0.511, hl-v174 -0.554, hl-v182 -0.620, hl-v184 -0.640, hl-v187 -0.692, hl-v190 -0.665, hl-v195 -0.641, hl-v197 -0.684, hl-v198 -0.706, hl-v207 -0.741, hl-v212 -0.700, hl-v217 -0.757, hl-v220 -0.807, hl-v221 -0.725, hl-v223 -0.746, hl-v224 -0.791
- held-out effect at acceptance: CE 2.4764 without, 2.4761 with the rule at its fitted weight -0.511 (gain +0.00023 nats, 90% CI +0.00004 .. +0.00043 over searches); at the model's weight -0.800: gain +0.00002; held-out positions matched 2162 from 63 searches
- hits: {"positions": 12105, "moves": 16484, "top": 136, "mass": 0.0179, "heldout_positions": 2353}
- rationale (model): S6: E6 (between E5 and White's E7) was the learned prior's top move (0.065) but got 0.001 of 11M visits. S5: F5 (between E5 and White's G5) had prior 0.064 and share 0.005. C4/D3, proposed by the model in S2, S4 and S5, each got at most 0.003 of visits. The search plays big points or shape moves instead of butting.
- provenance: heuristic job 2731 after decision B1g1p6, surprises S2, S4, S5, S6, lessons L254; proposal P405, accepted in hl-v171

### R30 second-line-base-under-own-fourth-line-stone

A second-line move with all eight neighbours empty, two lines below your own fourth-line stone (straight or one point along), makes a base for a weak group and is bigger than nearby contact moves.

```
? X ? ? ?
? . . . ?
? . * . ?
? . . . ?
# # # # #
```
- rule: `?X??? / ?...? / ?.*.? / ?...? / ##### ; line 2, captures 0`
- weight: -0.206 now; proposed +0.600 by the model; history: hl-v173 -0.149, hl-v182 -0.246, hl-v184 -0.094, hl-v187 -0.135, hl-v190 -0.191, hl-v192 -0.239, hl-v197 -0.201, hl-v198 -0.237, hl-v203 -0.319, hl-v207 -0.137, hl-v212 -0.110, hl-v215 -0.226, hl-v217 -0.069, hl-v218 -0.083, hl-v220 -0.199, hl-v221 -0.138, hl-v223 -0.171, hl-v224 -0.206  
  **The learned weight has the opposite sign to the model's proposal: the search does not support the direction the rule's text states; the rule stays only as a feature.**
- held-out effect at acceptance: CE 2.4800 without, 2.4796 with the rule at its fitted weight -0.149 (gain +0.00032 nats, 90% CI +0.00021 .. +0.00044 over searches); at the model's weight +0.600: gain -0.00289; held-out positions matched 8855 from 66 searches
- hits: {"positions": 50203, "moves": 122730, "top": 125, "mass": 0.0039, "heldout_positions": 9931}
- rationale (model): S2 and S3: H6 under own F7/F6 took 0.64 and 0.96 of the visits at learned prior 0.006 (rank 27); S4: B4 two lines below D3 took 0.86 at prior 0.005 (rank 35); S5: B2 took 0.82 at prior 0.005 (rank 33). In S2 the other matches B4 and B2 were also in the search's top six.
- provenance: heuristic job 2739 after decision A1g1p11, surprises S2, S3, S4, S5, lessons -; proposal P408, accepted in hl-v173

### R31 bare-second-line-cut-at-sole-link-two-libs

Cutting directly at the single second-line link point between their edge stone and their third-line stone, when the cutting stone gets only two liberties, is premature: they atari from the open side and the cutter dies.

```
# # # # #
? . . . ?
? O * . ?
? X O ? ?
? ? ? ? ?
```
- rule: `##### / ?...? / ?O*.? / ?XO?? / ????? ; captures 0, libs_after 2, not atari`
- weight: -1.143 now; proposed -0.700 by the model; history: hl-v186 -0.688, hl-v187 -0.898, hl-v190 -0.939, hl-v192 -1.041, hl-v195 -0.965, hl-v197 -1.041, hl-v198 -1.023, hl-v203 -1.008, hl-v207 -0.969, hl-v215 -1.014, hl-v217 -1.103, hl-v218 -1.079, hl-v220 -1.206, hl-v221 -1.173, hl-v223 -1.127, hl-v224 -1.143
- held-out effect at acceptance: CE 2.4537 without, 2.4519 with the rule at its fitted weight -0.688 (gain +0.00181 nats, 90% CI +0.00107 .. +0.00266 over searches); at the model's weight -0.700: gain +0.00181; held-out positions matched 2552 from 76 searches
- hits: {"positions": 11663, "moves": 12444, "top": 173, "mass": 0.03, "heldout_positions": 2342}
- rationale (model): F8 was the learned prior's 2nd or 4th choice for Black in S1 (0.093), S4 (0.060), S5 (0.073) and S6 (0.091), but got only 0.001-0.01 of the visits. After F8 G8 the cutter is in atari with just F9 left (checked with gtree try), and running out loses the race against D8-E8. The cut only works after the preparing move beyond the link point (S1 main line, L386). Rule-test: it matches F8 in S1, S4, S5 and S6, plus the analogous bare cut H4 in S2 (not among White's preferred moves).
- provenance: heuristic job 2965 after decision A1g1p23, surprises S1, S2, S4, S5, S6, lessons L386; proposal P438, accepted in hl-v186

### R32 corner-2-2-under-own-pincered-2-3-stone

Play the corner 2-2 point directly under your own lone stone on the 2-3 point when an opponent stone stands a one-point jump from it along the third line; it gives the invading stone a base and eye shape in their corner.

```
# ? ? ? ?
# . X . O
# . * . ?
# . . . ?
# # # # #
```
- rule: `#???? / #.X.O / #.*.? / #...? / ##### ; adj_own(libs 3-4, size 1), captures 0, not self_atari`
- weight: +1.238 now; proposed +0.700 by the model; history: hl-v188 +0.864, hl-v192 +1.036, hl-v195 +0.960, hl-v197 +1.076, hl-v198 +1.019, hl-v203 +0.986, hl-v207 +1.112, hl-v212 +1.035, hl-v215 +1.202, hl-v217 +1.147, hl-v218 +1.102, hl-v220 +1.007, hl-v221 +1.101, hl-v223 +1.251, hl-v224 +1.238
- held-out effect at acceptance: CE 2.4540 without, 2.4536 with the rule at its fitted weight +0.864 (gain +0.00038 nats, 90% CI +0.00002 .. +0.00084 over searches); at the model's weight +0.700: gain +0.00034; held-out positions matched 328 from 33 searches
- hits: {"positions": 2047, "moves": 2060, "top": 80, "mass": 0.0329, "heldout_positions": 424}
- rationale (model): In S1 and S6 the search put 95% of visits on B2, the 2-2 point under Black's lone B3 invader with White D3 a jump away, while the prior ranked it 23rd and 21st (0.005, 0.015). In S2 White took the same point first, and in S4 Black already held it, so it is a key point for both sides. G392 and L390 likewise find that the 2-2 point of a contested corner beats local replies. S3 and S5 also match without B2 being the top move (an urgent race or C3 instead), so the weight is moderate.
- provenance: heuristic job 2991 after decision A1g1p25, surprises S1, S2, S4, S6, lessons G392, L390; proposal P440, accepted in hl-v188

### R33 block-under-own-3rd-line-stone-vs-gap-probe

When their second-line probe sits diagonally under your third-line stone, block on the second line directly under your own stone, beside the probe, so it cannot slide under you.

```
? ? ? ? ?
? . X . ?
? O * . ?
? . . . ?
# # # # #
```
- rule: `????? / ?.X.? / ?O*.? / ?...? / ##### ; captures 0, not self_atari`
- weight: +0.415 now; proposed +0.600 by the model; history: hl-v193 +0.330, hl-v195 +0.319, hl-v197 +0.377, hl-v198 +0.357, hl-v212 +0.295, hl-v215 +0.379, hl-v217 +0.321, hl-v218 +0.356, hl-v220 +0.291, hl-v221 +0.276, hl-v223 +0.300, hl-v224 +0.415
- held-out effect at acceptance: CE 2.4636 without, 2.4626 with the rule at its fitted weight +0.330 (gain +0.00107 nats, 90% CI +0.00034 .. +0.00189 over searches); at the model's weight +0.600: gain +0.00132; held-out positions matched 743 from 60 searches
- hits: {"positions": 5503, "moves": 5669, "top": 1520, "mass": 0.2124, "heldout_positions": 1035}
- rationale (model): S1: after White's under-gap probe D2, Black's block E2 took 22.8M of 22.9M visits (0.996) but the learned prior put the atari B7 above it and the model never proposed it. L401's main line answers the probe with exactly this block. In S2 the search also chose E2 (0.53) to pre-empt the slide.
- provenance: heuristic job 3035 after decision B1g1p22, surprises S1, S2, lessons L401; proposal P452, accepted in hl-v193

### R34 slow-capture-of-sealed-dead-stones

Capturing opponent stones in atari whose last liberty lies between two of your own stones is usually slow: extending there would not save them, so they are already dead; play the big or vital point first.

```
? O ?
X * X
? ? ?
```
- rule: `?O? / X*X / ??? ; captures 1-5, not escape, line 3-9, dist_last 3-30`
- weight: -0.893 now; proposed -1.000 by the model; history: hl-v201 -0.713, hl-v203 -0.748, hl-v207 -0.717, hl-v212 -0.759, hl-v215 -0.773, hl-v217 -0.736, hl-v218 -0.769, hl-v220 -0.853, hl-v221 -0.750, hl-v223 -0.817, hl-v224 -0.893
- held-out effect at acceptance: CE 2.4574 without, 2.4569 with the rule at its fitted weight -0.713 (gain +0.00044 nats, 90% CI +0.00012 .. +0.00084 over searches); at the model's weight -1.000: gain +0.00043; held-out positions matched 130 from 11 searches
- hits: {"positions": 647, "moves": 648, "top": 213, "mass": 0.3112, "heldout_positions": 130}
- rationale (model): S2, S3, S5: F3 captures White's F4-G4 pair, whose last liberty is sealed between Black E3 and G3. It was the learned prior's top move (0.81, 0.58, 0.45) but got only 1.9%, 0.4% and 5.7% of visits. The search spent tempo on the corner (A2/B1) instead. R9 and R12 cover this only on lines 1-2 and in an armpit; this rule covers line 3+. It does not match when the last move touches the point.
- provenance: heuristic job 3099 after decision B1g1p28, surprises S2, S3, S5, lessons G328, G403; proposal P474, accepted in hl-v201

### R35 atari-dead-chain-between-own-stones

Ataring an opponent chain of 2-5 stones that is already ladder-dead, on a point between two of your own stones and away from their last move, is usually a slow gote move; the stones are dead anyway.

```
? X ?
? * O
? X ?
```
- rule: `?X? / ?*O / ?X? ; atari, ladder_capture, adj_opp(libs 2, size 2-5), dist_last 5-30`
- weight: -0.608 now; proposed -0.800 by the model; history: hl-v202 -0.318, hl-v203 -0.484, hl-v207 -0.473, hl-v212 -0.499, hl-v215 -0.575, hl-v218 -0.498, hl-v221 -0.523, hl-v223 -0.536, hl-v224 -0.608
- held-out effect at acceptance: CE 2.4569 without, 2.4562 with the rule at its fitted weight -0.663 (gain +0.00075 nats, 90% CI +0.00011 .. +0.00161 over searches); at the model's weight -0.800: gain +0.00071; held-out positions matched 367 from 11 searches
- hits: {"positions": 5158, "moves": 5560, "top": 2078, "mass": 0.3723, "heldout_positions": 1062}
- rationale (model): White's F4-G4 pair could already be captured and could not escape (both its liberties lie between Black stones). Yet the atari E4 was the learned prior's favourite in S1 (0.48), S2 (0.30) and S5 (0.33; model 0.63). It scored 0.44, 0.41 and 0.46 against 0.58, 0.53 and 0.60 for the search's choices. The other atari F3 (S5 0.18, S1) also lost. Atari, ladder capture and own-shape features stack up and overrate such moves.
- provenance: heuristic job 3100 after decision B1g1p30, surprises S1, S2, S5, lessons G396, G403; proposal P479, accepted in hl-v202

### R36 slow-capture-of-abandoned-inland-stones

Capturing 1-3 inland opponent stones that they left in atari while playing elsewhere is usually slow; they were given up, so play the urgent point first.

```
? ? ?
? * ?
? ? ?
```
- rule: `??? / ?*? / ??? ; captures 1-3, dist_last 5-30, line 3-9, not escape`
- weight: -0.318 now; proposed -0.600 by the model; history: hl-v202 -0.318
- held-out effect at acceptance: CE 2.4569 without, 2.4564 with the rule at its fitted weight -0.272 (gain +0.00056 nats, 90% CI +0.00011 .. +0.00108 over searches); at the model's weight -0.600: gain +0.00044; held-out positions matched 595 from 49 searches
- hits: {"positions": 5786, "moves": 6206, "top": 2526, "mass": 0.3892, "heldout_positions": 1190}
- rationale (model): S6: the 2-stone capture F3 of White's abandoned, already-dead F4-G4 had prior 0.58 (rank 1) but scored 0.36, against 0.41 for the corner move B1. S1: capturing the abandoned D5 at D6 (prior 0.34, rank 2) scored 0.49 against 0.58 for C8. This is the inland counterpart of book rule R9 (edge only). G403 says the same: gote clean-up captures of already-dead stones lose to the big point.
- provenance: heuristic job 3100 after decision B1g1p30, surprises S1, S6, lessons G396, G403; proposal P480, accepted in hl-v202

### R37 open-jump-cap-of-older-lone-opp-stone

In an open area, the empty third- or fourth-line point a one-point jump straight out from a lone opponent stone they did not just play, with the point between and the stone's sides empty and no other opponent stone near, is a strong cap or approach.

```
. . O . .
o . . . o
o . * . o
o . . . o
o o o o o
```
- rule: `..O.. / o...o / o.*.o / o...o / ooooo ; line 3-4, captures 0, dist_last 5-30`
- weight: +1.409 now; proposed +1.200 by the model; history: hl-v205 +1.479, hl-v207 +1.454, hl-v212 +1.527, hl-v215 +1.474, hl-v217 +1.379, hl-v218 +1.537, hl-v220 +1.549, hl-v221 +1.437, hl-v223 +1.377, hl-v224 +1.409
- held-out effect at acceptance: CE 2.4537 without, 2.4530 with the rule at its fitted weight +1.479 (gain +0.00074 nats, 90% CI +0.00004 .. +0.00160 over searches); at the model's weight +1.200: gain +0.00070; held-out positions matched 631 from 16 searches
- hits: {"positions": 3045, "moves": 3635, "top": 45, "mass": 0.0128, "heldout_positions": 626}
- rationale (model): S4: G5, the third-line one-point jump from Black's tengen stone, took 0.885 of 37.6M visits at 0.53 while the learned prior gave it 0.004 (rank 38). S5: E3, the same jump below the tengen stone, took 0.902 of 18.4M visits at 0.55 with prior 0.009 (rank 24). L248: the one-point-jump cap of a lone off-centre stone was best (0.53, 15.6M visits) with code prior 0.02. The rule matches only 4 of 463 legal moves in the surprises. The dist_last condition drops the jump at a just-played stone (S3 G6, 0.41).
- provenance: heuristic job 3231 after decision A0g1p3, surprises S4, S5, lessons L248; proposal P498, accepted in hl-v205

### R38 open-third-line-knight-approach-empty-area

On the third line, in an otherwise empty 5x5 area with none of your stones, the point a knight's move from an opponent stone (or pair) is a big approach or corner move. It is often better than a contact reply near the last move.

```
. . . . .
. . . . .
. . * . .
. . . . .
. O x . .
```
- rule: `..... / ..... / ..*.. / ..... / .Ox.. ; line 3, captures 0`
- weight: +0.384 now; proposed +0.800 by the model; history: hl-v208 +0.359, hl-v212 +0.371, hl-v215 +0.331, hl-v217 +0.371, hl-v218 +0.398, hl-v220 +0.465, hl-v221 +0.482, hl-v223 +0.384
- held-out effect at acceptance: CE 2.4393 without, 2.4387 with the rule at its fitted weight +0.359 (gain +0.00067 nats, 90% CI +0.00022 .. +0.00119 over searches); at the model's weight +0.800: gain +0.00066; held-out positions matched 847 from 13 searches
- hits: {"positions": 3371, "moves": 7309, "top": 321, "mass": 0.0963, "heldout_positions": 692}
- rationale (model): In S5 the search put 0.58 and 0.42 of its visits on F7 and G4, both matched (learned prior 0.016/0.024). It preferred them to the contact moves D4/C3 near the last move, which the prior favoured at 0.21 each. In S6 G6 took 0.86 at prior 0.015 (matched via the E6-E5 pair). R1/R2 matches with other opponent stones nearby (S1 G3/E7, S2 F7) were rejected, and this rule excludes them. Lessons L8 and L10 also say the knight's-move corner point beside the opponent's centre stone deserves a normal prior.
- provenance: heuristic job 3555 after decision A0g1p7, surprises S5, S6, lessons L10, L8; proposal P503, accepted in hl-v208

### R39 first-line-atari-chasing-escaping-chain

A first-line atari on an opponent chain of two or more stones that escapes the ladder only pushes it out to join its friends; the atari stone gains nothing, so it is usually a slow gote move.

```
? ? ?
? * ?
# # #
```
- rule: `??? / ?*? / ### ; atari, not ladder_capture, captures 0, adj_opp(libs 2, size 2-40)`
- weight: +0.292 now; proposed -0.800 by the model; history: hl-v222 +0.077, hl-v223 +0.321, hl-v224 +0.292  
  **The learned weight has the opposite sign to the model's proposal: the search does not support the direction the rule's text states; the rule stays only as a feature.**
- held-out effect at acceptance: CE 2.4545 without, 2.4543 with the rule at its fitted weight +0.077 (gain +0.00015 nats, 90% CI +0.00007 .. +0.00025 over searches); at the model's weight -0.800: gain -0.00243; held-out positions matched 1992 from 54 searches
- hits: {"positions": 10655, "moves": 12238, "top": 414, "mass": 0.0396, "heldout_positions": 2158}
- rationale (model): J3 (a first-line atari on H4-J4) was the learned prior's favourite in S1 (0.338), S2 (0.181), S3 (0.165) and S4 (0.101). The search gave it at most 0.002 of the visits. Black extends to G4 and joins G5 and F4 with four liberties. R3 covers only lone stones, so this size-2+ first-line case is not handled. The rule matches 2% of legal moves.
- provenance: heuristic job 4408 after decision A0g1p33, surprises S1, S2, S3, S4, lessons -; proposal P543, accepted in hl-v222

### R40 slow-fill-of-touched-diagonal-link

Do not fill one cutting point of your own diagonal link when the other cutting point is still empty and opponent stones touch the point from both other sides: the link is miai, so the connection is slow even if it also takes a liberty.

```
? O ?
X * O
. X ?
```
- rule: `?O? / X*O / .X? ; captures 0, not atari, adj_own(libs 2-3)`
- weight: -0.239 now; proposed -0.800 by the model; history: hl-v225 -0.239
- held-out effect at acceptance: CE 2.4588 without, 2.4585 with the rule at its fitted weight -0.239 (gain +0.00036 nats, 90% CI +0.00005 .. +0.00077 over searches); at the model's weight -0.800: gain +0.00012; held-out positions matched 1670 from 56 searches
- hits: {"positions": 8481, "moves": 9068, "top": 296, "mass": 0.0412, "heldout_positions": 1670}
- rationale (model): S4, S5, S6: White's G7 joins its 2-liberty G6-H6-H5-J5 chain to F7 while F6 is still empty. The learned prior gave it 0.120 / 0.180 / 0.116 (R25+R26 both fire), but the search gave it 0.001 / 0.000 / 0.000 of visits, and in S5 it scored 0.258 against 0.756 for H9. Because F6 still connects, G7 is a gote fill. The right move was the corner first-line point (H9 or J8). The rule matches only G7 in those three positions.
- provenance: heuristic job 4527 after decision A0g1p37, surprises S4, S5, S6, lessons G243; proposal P550, accepted in hl-v225

## Accepted weight nudges

- line:3 +0.20 (job 75, hl-v002): held-out gain +0.01426. Five of the six top moves (S1 C5, S2 G5, S3 E7, S5 C4, S6 G5) are on the third line, while the prior favoured fourth-line points around the centre stone (S1 D4/E4, S3 E6, S5 D5, S6 D6/E6).
- R1 +0.20 (job 195, hl-v008): held-out gain +0.00079. S2: R1/R2 hits C4 and D3 took 0.19 and 0.12 of 12M root visits at prior 0.024 and 0.026; S5 E3 (R1) was 0.074 at prior 0.018 and S3 C4 was 0.043 at prior 0.027.
- R1 -0.10 (job 260, hl-v013): held-out gain +0.00048. In S3 and S5 R1 boosted the third-line knight's move C7 in a middlegame contact fight (prior 0.056 and 0.050). The search gave it 0.000 and 0.007 of the visits.
- R5 -0.20 (job 806, hl-v043): held-out gain +0.00018. B7 (R5) was one of the prior's top 3 in S1, S2, S3 and S6 (0.07-0.19) but got under 0.01 of visits each time. It shows up later in the main lines, so it is a good but non-urgent move.
- R7 -0.30 (job 1070, hl-v062): held-out gain +0.00024. R7 fires on both first-line ataris of the C8-D8 pair. In S2 C9+D9 held 0.466 of the prior and got 0.004 of the search (B5 0.94). In S3 only C9 was right and D9 (prior 0.232) got 0.001. In S5 D1 (R7, 0.077) got 0.002. So R7 overrates on net.

## Lessons behind accepted rules

- G6 -> R1, R2
- L8 -> R1, R2, R38
- G5 -> R2
- G18 -> R5
- L17 -> R5
- G57 -> R6
- L59 -> R6
- L62 -> R6
- G150 -> R9, R25
- L149 -> R9
- L51 -> R10
- G21 -> R11
- L19 -> R11, R20
- L99 -> R12
- L83 -> R18
- L4 -> R20
- G271 -> R21
- L135 -> R22
- G285 -> R23
- L268 -> R23
- G276 -> R24
- G237 -> R26
- G296 -> R26
- G308 -> R26
- G311 -> R27
- G314 -> R27
- G323 -> R28
- L254 -> R29
- L386 -> R31
- G392 -> R32
- L390 -> R32
- L401 -> R33
- G328 -> R34
- G403 -> R34, R35, R36
- G396 -> R35, R36
- L248 -> R37
- L10 -> R38
- G243 -> R40

## Proposals

| id | job | kind | name / feature | status | reason |
|---|---|---|---|---|---|
| P1 | 75 | nudge | line:3 | accepted | held-out CE improved (+0.01426 nats) |
| P2 | 75 | rule | third-line-jump-from-own-stone | rejected | held-out CE gain +0.00411 nats (90% CI -0.00457 .. +0.01400) is not enough; matches only 133 held-out positions from 1 searches (needs 5 from 2) |
| P3 | 75 | rule | third-line-jump-attaching-lone-stone | rejected | held-out CE gain +0.00539 nats (90% CI -0.00097 .. +0.01403) is not enough; matches only 32 held-out positions from 1 searches (needs 5 from 2) |
| P4 | 119 | rule | stand-beside-attached-stone | rejected | held-out CE gain +0.00037 nats (90% CI -0.00071 .. +0.00151) is not enough |
| P5 | 119 | rule | attach-third-line-to-lone-approach | rejected | held-out CE gain +0.00000 nats (90% CI -0.00000 .. +0.00000) is not enough |
| P6 | 119 | rule | third-line-knight-from-lone-stone | accepted | held-out CE gain +0.00213 nats (90% CI +0.00038 .. +0.00409), guards and regression set pass |
| P7 | 160 | rule | third-line-jump-facing-opp-centre | rejected | held-out CE gain -0.00091 nats (90% CI -0.00282 .. +0.00102) is not enough |
| P8 | 160 | rule | third-line-jump-from-own-stone | rejected | held-out CE gain +0.00170 nats (90% CI -0.00086 .. +0.00467) is not enough |
| P9 | 160 | rule | third-line-knight-facing-opp-stone | accepted | held-out CE gain +0.00058 nats (90% CI +0.00001 .. +0.00121), guards and regression set pass |
| P10 | 195 | nudge | R1 | accepted | held-out CE improved (+0.00079 nats) |
| P11 | 195 | nudge | dist_last:2 | rejected | held-out CE did not improve (-0.00234 nats) |
| P12 | 195 | rule | extend-centre-stone-facing-older-approach | rejected | held-out CE gain +0.00083 nats (90% CI -0.00083 .. +0.00366) is not enough |
| P13 | 195 | rule | attach-under-centre-stone-toward-own-approach | rejected | held-out CE gain +0.00126 nats (90% CI -0.00049 .. +0.00339) is not enough |
| P14 | 236 | rule | extend-contact-chain-short-of-libs | rejected | held-out CE gain +0.00149 nats (90% CI -0.00164 .. +0.00414) is not enough |
| P15 | 236 | rule | hane-at-head-of-two-stones | rejected | held-out CE gain +0.00205 nats (90% CI -0.00018 .. +0.00429) is not enough |
| P16 | 236 | rule | atari-on-runaway-lone-stone | accepted | held-out CE gain +0.00061 nats (90% CI +0.00013 .. +0.00122), guards and regression set pass |
| P17 | 260 | nudge | R1 | accepted | held-out CE improved (+0.00048 nats) |
| P18 | 260 | rule | open-side-bottom-of-facing-walls | rejected | held-out CE gain +0.00135 nats (90% CI -0.00049 .. +0.00362) is not enough |
| P19 | 260 | rule | block-head-of-two-from-own-stone | rejected | held-out CE gain +0.00001 nats (90% CI -0.00044 .. +0.00069) is not enough |
| P20 | 295 | rule | second-line-hane-under-contact-stone | rejected | held-out CE gain +0.00249 nats (90% CI -0.00147 .. +0.00797) is not enough |
| P21 | 295 | rule | hane-cut-into-diagonal-with-support | rejected | held-out CE gain -0.00018 nats (90% CI -0.00041 .. -0.00001) is not enough |
| P22 | 330 | rule | descend-under-parallel-contact-pair | rejected | held-out CE gain +0.00611 nats (90% CI -0.00016 .. +0.01361) is not enough |
| P23 | 330 | rule | second-line-jump-from-fourth-line-stone | rejected | held-out CE gain +0.00006 nats (90% CI +0.00003 .. +0.00009) is not enough |
| P24 | 330 | rule | wedge-diagonal-with-own-peep | rejected | held-out CE gain -0.00011 nats (90% CI -0.00017 .. -0.00005) is not enough |
| P25 | 357 | nudge | R1 | rejected | held-out CE did not improve (+0.00010 nats) |
| P26 | 357 | rule | extend-past-end-of-parallel-two | rejected | held-out CE gain +0.00436 nats (90% CI -0.00028 .. +0.01139) is not enough |
| P27 | 357 | rule | second-line-jump-from-blocked-fourth-line-pair | rejected | held-out CE gain -0.00044 nats (90% CI -0.00070 .. -0.00018) is not enough |
| P28 | 376 | nudge | R3 | rejected | held-out CE did not improve (-0.00465 nats) |
| P29 | 376 | rule | descend-past-parallel-pair-when-short-of-libs | accepted | held-out CE gain +0.00626 nats (90% CI +0.00120 .. +0.01193), guards and regression set pass |
| P30 | 398 | rule | hane-at-head-from-parallel-wall | rejected | held-out CE gain -0.00095 nats (90% CI -0.00235 .. +0.00001) is not enough |
| P31 | 398 | rule | thin-atari-on-escaping-pair | rejected | held-out CE gain +0.00002 nats (90% CI -0.00013 .. +0.00018) is not enough |
| P32 | 398 | rule | extend-ahead-after-opponent-pushes-level | rejected | held-out CE gain -0.00006 nats (90% CI -0.00076 .. +0.00074) is not enough |
| P33 | 434 | rule | second-line-hane-at-head-of-parallel-column | rejected | held-out CE gain -0.00102 nats (90% CI -0.00291 .. +0.00007) is not enough |
| P34 | 524 | nudge | dist_last:11+ | rejected | held-out CE did not improve (-0.00330 nats) |
| P35 | 524 | rule | undercut-beside-pinned-opp-pair | rejected | held-out CE gain -0.00041 nats (90% CI -0.00064 .. -0.00019) is not enough |
| P36 | 524 | rule | extend-at-head-of-own-two-vs-contact | accepted | held-out CE gain +0.00244 nats (90% CI +0.00046 .. +0.00462), guards and regression set pass |
| P37 | 555 | nudge | line:2 | rejected | held-out CE did not improve (-0.00225 nats) |
| P38 | 555 | rule | descend-past-parallel-pair-strong-chain | rejected | held-out CE gain +0.00147 nats (90% CI -0.00125 .. +0.00461) is not enough |
| P39 | 555 | rule | second-line-hane-around-touching-lone-stone | rejected | held-out CE gain +0.00111 nats (90% CI -0.00125 .. +0.00366) is not enough |
| P40 | 555 | rule | ladder-atari-on-sealed-lone-stone | rejected | held-out CE gain -0.00016 nats (90% CI -0.00085 .. +0.00043) is not enough |
| P41 | 589 | nudge | line:2 | rejected | held-out CE did not improve (-0.00007 nats) |
| P42 | 589 | rule | edge-extend-past-opp-parallel-pair-many-libs | rejected | same pattern and conditions as rejected proposal P38 (held-out CE gain +0.00147 nats (90% CI -0.00125 .. +0.00461) is not enough) |
| P43 | 608 | rule | hane-head-of-second-line-pair | rejected | held-out CE gain +0.00285 nats (90% CI -0.00018 .. +0.00840) is not enough |
| P44 | 608 | rule | extend-second-line-pair-before-hane | rejected | held-out CE gain +0.00256 nats (90% CI -0.00055 .. +0.00625) is not enough |
| P45 | 608 | rule | thin-cut-atari-on-doomed-lone-stone | rejected | held-out CE gain +0.00250 nats (90% CI -0.00068 .. +0.00581) is not enough |
| P46 | 639 | nudge | R3 | rejected | held-out CE did not improve (-0.00325 nats) |
| P47 | 639 | rule | block-head-of-opp-second-line-crawl | rejected | held-out CE gain +0.00154 nats (90% CI -0.00086 .. +0.00560) is not enough |
| P48 | 639 | rule | open-side-second-line-descent | rejected | held-out CE gain +0.00076 nats (90% CI -0.00112 .. +0.00282) is not enough |
| P49 | 639 | rule | thin-ladder-atari-between-opp-stones | rejected | held-out CE gain +0.00329 nats (90% CI -0.00114 .. +0.00775) is not enough |
| P50 | 656 | rule | block-under-wall-end-second-line | rejected | held-out CE gain +0.00002 nats (90% CI -0.00014 .. +0.00020) is not enough |
| P51 | 656 | rule | descend-from-wall-end-beside-opp-stone | rejected | held-out CE gain -0.00017 nats (90% CI -0.00040 .. +0.00006) is not enough |
| P52 | 656 | rule | second-line-extend-along-edge-vs-contact | rejected | held-out CE gain +0.00077 nats (90% CI -0.00051 .. +0.00233) is not enough |
| P53 | 656 | rule | two-two-under-own-pressed-three-three | rejected | held-out CE gain +0.00264 nats (90% CI -0.00215 .. +0.00870) is not enough |
| P54 | 668 | rule | two-two-point-of-contested-three-three | rejected | held-out CE gain +0.00267 nats (90% CI -0.00302 .. +0.00978) is not enough |
| P55 | 674 | rule | atari-on-lone-armpit-stone | rejected | held-out CE gain +0.00035 nats (90% CI -0.00124 .. +0.00170) is not enough |
| P56 | 674 | rule | save-lone-armpit-stone | accepted | held-out CE gain +0.00247 nats (90% CI +0.00019 .. +0.00464), guards and regression set pass |
| P57 | 686 | nudge | line:1 | rejected | held-out CE did not improve (-0.00150 nats) |
| P58 | 686 | rule | slow-atari-on-armpit-cutting-stone | rejected | held-out CE gain -0.00023 nats (90% CI -0.00073 .. +0.00025) is not enough |
| P59 | 686 | rule | slow-extension-of-armpit-cutting-stone | rejected | held-out CE gain +0.00016 nats (90% CI -0.00037 .. +0.00068) is not enough |
| P60 | 686 | rule | edge-hanging-connection-under-diagonal-cut | rejected | held-out CE gain +0.00098 nats (90% CI -0.00043 .. +0.00251) is not enough |
| P61 | 686 | rule | second-line-undercut-below-opp-third-line | rejected | held-out CE gain +0.00171 nats (90% CI -0.00036 .. +0.00429) is not enough |
| P62 | 702 | nudge | ladder:capture | rejected | held-out CE did not improve (-0.00127 nats) |
| P63 | 702 | rule | ladder-atari-on-enclosed-lone-stone | rejected | held-out CE gain -0.00009 nats (90% CI -0.00064 .. +0.00040) is not enough |
| P64 | 702 | rule | net-point-beyond-armpit-stone | rejected | held-out CE gain +0.00174 nats (90% CI -0.00030 .. +0.00432) is not enough |
| P65 | 723 | nudge | R5 | rejected | held-out CE did not improve (-0.00020 nats) |
| P66 | 723 | nudge | R3 | rejected | held-out CE did not improve (-0.00112 nats) |
| P67 | 723 | rule | first-line-probe-under-opp-cutting-point | rejected | held-out CE gain -0.00008 nats (90% CI -0.00038 .. +0.00027) is not enough |
| P68 | 723 | rule | first-line-attach-under-lone-second-line-stone | rejected | held-out CE gain -0.00037 nats (90% CI -0.00055 .. -0.00021) is not enough |
| P69 | 723 | rule | first-line-hane-under-crawling-second-line-chain | accepted | held-out CE gain +0.00030 nats (90% CI +0.00000 .. +0.00073), guards and regression set pass |
| P70 | 738 | rule | edge-extend-own-stone-under-opp | rejected | held-out CE gain +0.00076 nats (90% CI -0.00021 .. +0.00222) is not enough |
| P71 | 738 | rule | edge-attach-under-lone-second-line-stone | rejected | held-out CE gain -0.00041 nats (90% CI -0.00056 .. -0.00026) is not enough |
| P72 | 752 | rule | edge-point-beside-opp-diagonal-cut | rejected | held-out CE gain -0.00041 nats (90% CI -0.00059 .. -0.00024) is not enough |
| P73 | 752 | rule | edge-contact-under-lone-opp-second-line-stone | rejected | held-out CE gain -0.00026 nats (90% CI -0.00073 .. +0.00028) is not enough |
| P74 | 760 | nudge | line:1 | rejected | held-out CE did not improve (-0.00349 nats) |
| P75 | 760 | rule | second-line-head-extension-is-small | rejected | held-out CE gain -0.00028 nats (90% CI -0.00065 .. +0.00011) is not enough |
| P76 | 760 | rule | edge-tiger-mouth-on-real-second-line-cut | rejected | held-out CE gain +0.00143 nats (90% CI -0.00011 .. +0.00302) is not enough |
| P77 | 778 | nudge | line:1 | rejected | held-out CE did not improve (-0.00171 nats) |
| P78 | 778 | rule | edge-hanging-connection-at-real-cut | rejected | held-out CE gain +0.00165 nats (90% CI -0.00005 .. +0.00347) is not enough |
| P79 | 778 | rule | second-line-atari-on-dead-first-line-stones | rejected | held-out CE gain +0.00033 nats (90% CI -0.00007 .. +0.00077) is not enough |
| P80 | 778 | rule | edge-atari-on-dead-first-line-stones | rejected | held-out CE gain +0.00019 nats (90% CI -0.00012 .. +0.00057) is not enough |
| P81 | 806 | nudge | ladder:capture | rejected | held-out CE did not improve (-0.00171 nats) |
| P82 | 806 | nudge | R5 | accepted | held-out CE improved (+0.00018 nats) |
| P83 | 806 | rule | edge-crawl-own-chain-under-opp-stone | rejected | held-out CE gain -0.00002 nats (90% CI -0.00014 .. +0.00011) is not enough |
| P84 | 806 | rule | edge-contact-on-opp-first-line-chain | rejected | held-out CE gain +0.00500 nats (90% CI -0.00292 .. +0.01417) is not enough |
| P85 | 806 | rule | edge-hane-under-opp-from-own-diagonal | rejected | held-out CE gain -0.00006 nats (90% CI -0.00065 .. +0.00055) is not enough |
| P86 | 832 | rule | first-line-extend-over-opp-second-line-stone | rejected | held-out CE gain +0.00036 nats (90% CI -0.00141 .. +0.00249) is not enough |
| P87 | 832 | rule | first-line-block-beside-opp-edge-stone | rejected | held-out CE gain +0.00053 nats (90% CI -0.00206 .. +0.00321) is not enough |
| P88 | 832 | rule | do-not-escape-thrown-in-lone-stone | rejected | held-out CE gain -0.00008 nats (90% CI -0.00032 .. +0.00013) is not enough |
| P89 | 832 | rule | capture-of-surrounded-throw-in-is-slow | rejected | held-out CE gain -0.00026 nats (90% CI -0.00058 .. +0.00002) is not enough |
| P90 | 848 | nudge | R3 | rejected | held-out CE did not improve (-0.00176 nats) |
| P91 | 848 | rule | second-line-attach-under-opp-third-line-end | rejected | held-out CE gain +0.00002 nats (90% CI +0.00001 .. +0.00003) is not enough |
| P92 | 871 | rule | second-line-attach-on-gapped-approach-stone | rejected | held-out CE gain +0.00028 nats (90% CI -0.00055 .. +0.00129) is not enough |
| P93 | 871 | rule | second-line-guard-over-own-gapped-approach | rejected | held-out CE gain -0.00036 nats (90% CI -0.00054 .. -0.00020) is not enough |
| P94 | 871 | rule | slow-descent-beside-parallel-pair-ample-libs | rejected | held-out CE gain -0.00000 nats (90% CI -0.00035 .. +0.00033) is not enough |
| P95 | 871 | rule | slow-hane-under-parallel-pair-ample-libs | rejected | held-out CE gain -0.00038 nats (90% CI -0.00085 .. +0.00008) is not enough |
| P96 | 892 | rule | extend-second-line-toward-open-side | rejected | held-out CE gain +0.00018 nats (90% CI -0.00019 .. +0.00058) is not enough |
| P97 | 892 | rule | hane-under-attached-second-line-stone | rejected | held-out CE gain +0.00096 nats (90% CI -0.00005 .. +0.00207) is not enough |
| P98 | 892 | rule | block-hane-under-stone-from-corner-side | rejected | held-out CE gain -0.00008 nats (90% CI -0.00012 .. -0.00004) is not enough |
| P99 | 892 | rule | second-line-placement-at-wall-end-cut | rejected | held-out CE gain -0.00016 nats (90% CI -0.00067 .. +0.00038) is not enough |
| P100 | 917 | rule | edge-hane-under-opp-second-line-hane-stone | rejected | held-out CE gain -0.00058 nats (90% CI -0.00103 .. -0.00009) is not enough |
| P101 | 917 | rule | second-line-head-of-wall-beside-diagonal-cut | rejected | held-out CE gain +0.00022 nats (90% CI -0.00017 .. +0.00084) is not enough |
| P102 | 935 | nudge | line:1 | rejected | held-out CE did not improve (-0.00099 nats) |
| P103 | 935 | rule | first-line-hane-under-lone-hane-stone | rejected | held-out CE gain -0.00000 nats (90% CI -0.00038 .. +0.00044) is not enough |
| P104 | 935 | rule | crosscut-between-two-lone-stones | rejected | held-out CE gain +0.00016 nats (90% CI -0.00027 .. +0.00061) is not enough |
| P105 | 979 | nudge | R5 | rejected | held-out CE did not improve (+0.00002 nats) |
| P106 | 979 | rule | premature-cut-behind-second-line-hane-stone | rejected | held-out CE gain +0.00001 nats (90% CI -0.00007 .. +0.00010) is not enough |
| P107 | 979 | rule | connect-second-line-hane-stone-at-cut | rejected | held-out CE gain +0.00003 nats (90% CI -0.00012 .. +0.00022) is not enough |
| P108 | 988 | rule | slow-head-extension-own-stone-caps-contact | rejected | held-out CE gain -0.00004 nats (90% CI -0.00013 .. +0.00006) is not enough |
| P109 | 988 | rule | edge-throw-in-cutting-diagonal-link | rejected | held-out CE gain +0.00026 nats (90% CI -0.00011 .. +0.00080) is not enough |
| P110 | 1001 | nudge | R5 | rejected | held-out CE did not improve (-0.00054 nats) |
| P111 | 1001 | nudge | R7 | rejected | held-out CE did not improve (+0.00010 nats) |
| P112 | 1001 | rule | edge-cut-diagonal-atari-two-lib-stone | rejected | held-out CE gain -0.00036 nats (90% CI -0.00122 .. +0.00061) is not enough |
| P113 | 1001 | rule | connect-diagonal-cut-of-two-lib-chain | rejected | held-out CE gain +0.00116 nats (90% CI -0.00013 .. +0.00264) is not enough |
| P114 | 1001 | rule | second-line-attach-beside-opp-cut-point | rejected | held-out CE gain +0.00015 nats (90% CI -0.00027 .. +0.00088) is not enough |
| P115 | 1010 | nudge | R7 | rejected | held-out CE did not improve (+0.00009 nats) |
| P116 | 1010 | rule | first-line-cut-atari-on-hane-over-wedge | rejected | held-out CE gain +0.00021 nats (90% CI -0.00069 .. +0.00135) is not enough |
| P117 | 1010 | rule | first-line-connect-hane-over-wedge | rejected | held-out CE gain +0.00074 nats (90% CI -0.00013 .. +0.00225) is not enough |
| P118 | 1010 | rule | second-line-descent-at-head-vs-contact | accepted | held-out CE gain +0.00051 nats (90% CI +0.00010 .. +0.00090), guards and regression set pass |
| P119 | 999 | rule | slow-block-at-head-vs-lone-contact-stone | rejected | held-out CE gain +0.00011 nats (90% CI -0.00037 .. +0.00052) is not enough |
| P120 | 999 | rule | connect-shared-liberty-of-two-weak-chains | rejected | held-out CE gain +0.00055 nats (90% CI -0.00017 .. +0.00181) is not enough |
| P121 | 999 | rule | push-cut-through-opp-diagonal-from-own-stone | rejected | held-out CE gain +0.00034 nats (90% CI -0.00041 .. +0.00121) is not enough |
| P122 | 999 | rule | second-line-support-for-crosscut-point | rejected | held-out CE gain +0.00014 nats (90% CI -0.00027 .. +0.00087) is not enough |
| P123 | 1012 | nudge | R3 | rejected | held-out CE did not improve (-0.00187 nats) |
| P124 | 1012 | rule | first-line-sacrifice-atari | rejected | held-out CE gain -0.00019 nats (90% CI -0.00081 .. +0.00052) is not enough |
| P125 | 1026 | rule | hanging-connection-open-side-of-gap | rejected | held-out CE gain -0.00050 nats (90% CI -0.00073 .. -0.00029) is not enough |
| P126 | 1026 | rule | wedge-into-gap-between-opp-lines | rejected | held-out CE gain -0.00002 nats (90% CI -0.00010 .. +0.00005) is not enough |
| P127 | 1026 | rule | slow-solid-connection-in-wall-gap | rejected | held-out CE gain -0.00009 nats (90% CI -0.00031 .. +0.00010) is not enough |
| P128 | 1026 | rule | first-line-guard-under-probe-stone | rejected | held-out CE gain +0.00022 nats (90% CI -0.00021 .. +0.00100) is not enough |
| P129 | 1043 | nudge | R8 | rejected | held-out CE did not improve (-0.00043 nats) |
| P130 | 1043 | rule | first-line-block-under-own-two-lib-crawl | rejected | held-out CE gain +0.00008 nats (90% CI -0.00043 .. +0.00067) is not enough |
| P131 | 1043 | rule | loose-diagonal-link-across-cut-gap | rejected | held-out CE gain -0.00018 nats (90% CI -0.00027 .. -0.00010) is not enough |
| P132 | 1062 | nudge | R6 | rejected | held-out CE did not improve (-0.00079 nats) |
| P133 | 1062 | rule | extend-weak-crosscut-stone | rejected | held-out CE gain +0.00097 nats (90% CI -0.00008 .. +0.00208) is not enough |
| P134 | 1062 | rule | slow-solid-connection-in-wall-gap | rejected | held-out CE gain +0.00001 nats (90% CI -0.00000 .. +0.00002) is not enough |
| P135 | 1062 | rule | unsevere-wedge-cut-in-wall-gap | rejected | held-out CE gain +0.00002 nats (90% CI -0.00004 .. +0.00008) is not enough |
| P136 | 1070 | nudge | dist_last:2 | rejected | held-out CE did not improve (-0.00456 nats) |
| P137 | 1070 | nudge | R7 | accepted | held-out CE improved (+0.00024 nats) |
| P138 | 1070 | rule | second-line-extend-pinched-lone-stone | rejected | held-out CE gain -0.00008 nats (90% CI -0.00133 .. +0.00103) is not enough |
| P139 | 1098 | nudge | R7 | rejected | held-out CE did not improve (-0.00052 nats) |
| P140 | 1098 | rule | slow-capture-of-abandoned-edge-stones | accepted | held-out CE gain +0.00126 nats (90% CI +0.00039 .. +0.00224), guards and regression set pass |
| P141 | 1111 | rule | edge-capture-of-pinned-stones-is-slow | rejected | held-out CE gain +0.00060 nats (90% CI -0.00023 .. +0.00154) is not enough |
| P142 | 1111 | rule | eye-point-connect-of-ko-stone | rejected | held-out CE gain -0.00011 nats (90% CI -0.00059 .. +0.00026) is not enough |
| P143 | 1124 | nudge | R9 | rejected | held-out CE did not improve (-0.00021 nats) |
| P144 | 1124 | rule | slow-connect-lone-stone-at-crosscut | rejected | held-out CE gain -0.00010 nats (90% CI -0.00103 .. +0.00084) is not enough |
| P145 | 1124 | rule | fill-own-knight-link-gap-in-centre | accepted | held-out CE gain +0.00028 nats (90% CI +0.00017 .. +0.00041), guards and regression set pass |
| P146 | 1175 | rule | extend-lone-centre-stone-facing-approach | rejected | held-out CE gain +0.00021 nats (90% CI -0.00022 .. +0.00068) is not enough |
| P147 | 1175 | rule | diagonal-step-from-centre-stone-onto-approach | rejected | held-out CE gain -0.00015 nats (90% CI -0.00039 .. +0.00003) is not enough |
| P148 | 1178 | rule | centre-stone-jump-to-third-line-vs-corner-stone | rejected | held-out CE gain -0.00003 nats (90% CI -0.00024 .. +0.00020) is not enough |
| P149 | 1178 | rule | attach-centre-stone-from-supported-side | rejected | held-out CE gain +0.00002 nats (90% CI -0.00014 .. +0.00021) is not enough |
| P150 | 1178 | rule | diagonal-contact-on-isolated-centre-stone | rejected | held-out CE gain +0.00002 nats (90% CI -0.00010 .. +0.00015) is not enough |
| P151 | 1254 | rule | attach-free-end-of-opp-centre-two | rejected | held-out CE gain +0.00009 nats (90% CI -0.00007 .. +0.00028) is not enough |
| P152 | 1254 | rule | extend-centre-stone-sideways-from-approach | rejected | held-out CE gain +0.00004 nats (90% CI -0.00028 .. +0.00039) is not enough |
| P153 | 1238 | nudge | R2 | rejected | held-out CE did not improve (-0.00086 nats) |
| P154 | 1238 | rule | opening-second-line-under-third-line-stone | rejected | held-out CE gain +0.00002 nats (90% CI -0.00010 .. +0.00014) is not enough |
| P155 | 1238 | rule | crosscut-hane-back-at-head-of-their-two | rejected | held-out CE gain +0.00008 nats (90% CI -0.00025 .. +0.00045) is not enough |
| P156 | 1238 | rule | stretch-head-of-own-two-vs-side-press | accepted | held-out CE gain +0.00053 nats (90% CI +0.00001 .. +0.00120), guards and regression set pass |
| P157 | 1279 | nudge | R1 | rejected | held-out CE did not improve (-0.00089 nats) |
| P158 | 1279 | nudge | R2 | rejected | held-out CE did not improve (-0.00041 nats) |
| P159 | 1279 | rule | opening-block-beside-lone-own-stone | rejected | held-out CE gain +0.00022 nats (90% CI -0.00007 .. +0.00050) is not enough |
| P160 | 1279 | rule | push-into-opp-diagonal-from-lone-stone | rejected | held-out CE gain -0.00023 nats (90% CI -0.00059 .. +0.00011) is not enough |
| P161 | 1282 | nudge | R2 | rejected | held-out CE did not improve (-0.00084 nats) |
| P162 | 1282 | rule | quiet-contact-between-lone-diagonal-pair | rejected | held-out CE gain -0.00002 nats (90% CI -0.00008 .. +0.00002) is not enough |
| P163 | 1341 | rule | second-line-slide-under-opp-4th-line | rejected | held-out CE gain -0.00018 nats (90% CI -0.00037 .. +0.00003) is not enough |
| P164 | 1341 | rule | second-line-knight-slide-opp-4th-line | rejected | held-out CE gain +0.00012 nats (90% CI -0.00010 .. +0.00038) is not enough |
| P165 | 1337 | rule | third-line-push-under-diagonal-shoulder | rejected | held-out CE gain +0.00013 nats (90% CI -0.00029 .. +0.00064) is not enough |
| P166 | 1391 | nudge | R5 | rejected | held-out CE did not improve (-0.00102 nats) |
| P167 | 1391 | rule | second-line-slide-beside-attached-opp-stone | rejected | held-out CE gain -0.00018 nats (90% CI -0.00027 .. -0.00009) is not enough |
| P168 | 1370 | rule | second-line-jump-under-own-4th-line-stone | rejected | held-out CE gain +0.00001 nats (90% CI -0.00028 .. +0.00036) is not enough |
| P169 | 1370 | rule | second-line-knight-slide-from-own-3rd-line | rejected | held-out CE gain -0.00012 nats (90% CI -0.00029 .. +0.00009) is not enough |
| P170 | 1430 | rule | save-armpit-stone-in-atari | rejected | held-out CE gain +0.00043 nats (90% CI -0.00008 .. +0.00092) is not enough |
| P171 | 1430 | rule | capture-abandoned-armpit-stone | accepted | held-out CE gain +0.00055 nats (90% CI +0.00010 .. +0.00103), guards and regression set pass |
| P172 | 1437 | rule | fill-third-line-two-space-gap | rejected | held-out CE gain +0.00029 nats (90% CI -0.00027 .. +0.00103) is not enough |
| P173 | 1437 | rule | second-line-guard-beside-own-third-line-stone | rejected | held-out CE gain -0.00028 nats (90% CI -0.00042 .. -0.00012) is not enough |
| P174 | 1437 | rule | attach-edge-side-of-opp-stone-facing-own | rejected | held-out CE gain -0.00019 nats (90% CI -0.00047 .. +0.00016) is not enough |
| P175 | 1437 | rule | bare-two-liberty-cut-in-their-sphere | rejected | held-out CE gain +0.00016 nats (90% CI -0.00004 .. +0.00036) is not enough |
| P176 | 1469 | rule | dont-pull-out-pocketed-lone-stone | rejected | held-out CE gain -0.00005 nats (90% CI -0.00020 .. +0.00009) is not enough |
| P177 | 1488 | rule | block-head-of-opp-straight-two-beside-own-diag | rejected | held-out CE gain +0.00047 nats (90% CI -0.00071 .. +0.00164) is not enough |
| P178 | 1510 | nudge | R3 | rejected | held-out CE did not improve (-0.00164 nats) |
| P179 | 1510 | nudge | line:2 | rejected | held-out CE did not improve (-0.00279 nats) |
| P180 | 1510 | rule | atari-drives-lone-stone-home | rejected | held-out CE gain -0.00020 nats (90% CI -0.00046 .. +0.00003) is not enough |
| P181 | 1510 | rule | second-line-knight-closes-own-open-corner | rejected | held-out CE gain -0.00007 nats (90% CI -0.00010 .. -0.00005) is not enough |
| P182 | 1554 | rule | two-two-probe-under-opp-lone-three-three | rejected | held-out CE gain -0.00065 nats (90% CI -0.00119 .. -0.00002) is not enough |
| P183 | 1554 | rule | second-line-crawl-under-opp-third-line-pair | rejected | held-out CE gain -0.00000 nats (90% CI -0.00002 .. +0.00002) is not enough |
| P184 | 1554 | rule | second-line-jump-from-own-side-wall-end | rejected | held-out CE gain +0.00012 nats (90% CI -0.00001 .. +0.00027) is not enough |
| P185 | 1542 | nudge | line:2 | rejected | held-out CE did not improve (-0.00837 nats) |
| P186 | 1542 | nudge | dist_last:2 | rejected | held-out CE did not improve (-0.00264 nats) |
| P187 | 1542 | rule | corner-2-2-between-3-3-and-2-4 | rejected | held-out CE gain +0.00038 nats (90% CI -0.00188 .. +0.00295) is not enough |
| P188 | 1542 | rule | block-on-top-of-second-line-probe | rejected | held-out CE gain -0.00021 nats (90% CI -0.00058 .. +0.00017) is not enough |
| P189 | 1547 | nudge | line:2 | rejected | held-out CE did not improve (-0.00564 nats) |
| P190 | 1547 | rule | second-line-diagonal-under-lone-third-line-stone | rejected | held-out CE gain +0.00002 nats (90% CI +0.00001 .. +0.00004) is not enough |
| P191 | 1547 | rule | solid-second-line-extension-under-4th-line-stone | rejected | held-out CE gain -0.00010 nats (90% CI -0.00015 .. -0.00005) is not enough |
| P192 | 1547 | rule | second-line-jump-below-end-of-opp-line | rejected | held-out CE gain -0.00007 nats (90% CI -0.00026 .. +0.00016) is not enough |
| P193 | 1573 | rule | second-line-crawl-under-opp-stones | rejected | held-out CE gain -0.00002 nats (90% CI -0.00008 .. +0.00003) is not enough |
| P194 | 1573 | rule | peep-under-third-line-jump-gap | rejected | held-out CE gain -0.00008 nats (90% CI -0.00018 .. +0.00004) is not enough |
| P195 | 1573 | rule | second-line-under-diagonal-cut-point | rejected | held-out CE gain +0.00003 nats (90% CI -0.00050 .. +0.00058) is not enough |
| P196 | 1573 | rule | edge-hane-splits-stones-around-wall-end | rejected | held-out CE gain -0.00016 nats (90% CI -0.00067 .. +0.00034) is not enough |
| P197 | 1585 | rule | hane-at-head-of-opp-two-beside-own-stone | rejected | held-out CE gain +0.00010 nats (90% CI -0.00041 .. +0.00061) is not enough |
| P198 | 1585 | rule | fill-knight-gap-to-pressed-lone-stone | rejected | held-out CE gain -0.00001 nats (90% CI -0.00020 .. +0.00028) is not enough |
| P199 | 1599 | rule | first-line-clamp-under-opp-second-line-chain | rejected | held-out CE gain -0.00036 nats (90% CI -0.00075 .. -0.00001) is not enough |
| P200 | 1691 | rule | corner-2-2-between-diagonal-contact | rejected | held-out CE gain +0.00127 nats (90% CI -0.00009 .. +0.00291) is not enough |
| P201 | 1691 | rule | first-line-placement-in-second-line-gap | rejected | held-out CE gain -0.00002 nats (90% CI -0.00002 .. -0.00001) is not enough |
| P202 | 1699 | rule | first-line-placement-on-confined-edge-group | rejected | held-out CE gain +0.00036 nats (90% CI -0.00015 .. +0.00124) is not enough |
| P203 | 1699 | rule | block-stale-probe-beside-own-two | rejected | held-out CE gain -0.00013 nats (90% CI -0.00045 .. +0.00026) is not enough |
| P204 | 1700 | nudge | R3 | rejected | held-out CE did not improve (-0.00211 nats) |
| P205 | 1700 | rule | first-line-hane-under-opp-second-line-end | rejected | held-out CE gain -0.00007 nats (90% CI -0.00027 .. +0.00017) is not enough |
| P206 | 1700 | rule | kosumi-link-extension-of-lone-two-lib-stone | accepted | held-out CE gain +0.00047 nats (90% CI +0.00008 .. +0.00093), guards and regression set pass |
| P207 | 1725 | nudge | line:1 | rejected | held-out CE did not improve (-0.00225 nats) |
| P208 | 1725 | nudge | R6 | rejected | held-out CE did not improve (-0.00021 nats) |
| P209 | 1725 | rule | first-line-hane-under-perpendicular-opp-line | rejected | held-out CE gain +0.00046 nats (90% CI -0.00007 .. +0.00105) is not enough |
| P210 | 1725 | rule | second-line-hane-under-strong-opp-chain | rejected | held-out CE gain -0.00008 nats (90% CI -0.00062 .. +0.00048) is not enough |
| P211 | 1727 | nudge | R3 | rejected | held-out CE did not improve (-0.00158 nats) |
| P212 | 1727 | nudge | R6 | rejected | held-out CE did not improve (-0.00011 nats) |
| P213 | 1727 | nudge | capture:1 | rejected | held-out CE did not improve (-0.00018 nats) |
| P214 | 1727 | nudge | escape:size1:libs3+ | rejected | held-out CE did not improve (-0.00035 nats) |
| P215 | 1727 | rule | edge-descent-at-end-of-line-vs-contact | rejected | held-out CE gain +0.00009 nats (90% CI -0.00037 .. +0.00063) is not enough |
| P216 | 1727 | rule | edge-hane-around-end-of-opp-line | rejected | held-out CE gain +0.00032 nats (90% CI -0.00009 .. +0.00078) is not enough |
| P217 | 1736 | rule | stale-ladder-atari-on-abandoned-lone-stone | rejected | held-out CE gain +0.00015 nats (90% CI -0.00030 .. +0.00058) is not enough |
| P218 | 1736 | rule | corner-2-1-placement-under-opp-chain-into-corner | rejected | held-out CE gain +0.00003 nats (90% CI -0.00002 .. +0.00012) is not enough |
| P219 | 1807 | nudge | ladder:capture | rejected | held-out CE did not improve (-0.00296 nats) |
| P220 | 1807 | nudge | R3 | rejected | held-out CE did not improve (-0.00169 nats) |
| P221 | 1807 | nudge | line:1 | rejected | held-out CE did not improve (-0.00545 nats) |
| P222 | 1807 | rule | first-line-hane-beside-own-second-line-stone | rejected | held-out CE gain -0.00010 nats (90% CI -0.00020 .. +0.00000) is not enough |
| P223 | 1807 | rule | extend-two-lib-first-line-cutting-stone | rejected | held-out CE gain -0.00010 nats (90% CI -0.00052 .. +0.00035) is not enough |
| P224 | 1830 | rule | first-line-placement-under-opp-second-line-chain | rejected | held-out CE gain -0.00007 nats (90% CI -0.00053 .. +0.00047) is not enough |
| P225 | 1830 | rule | slow-capture-of-stone-in-own-tiger-mouth | rejected | held-out CE gain -0.00001 nats (90% CI -0.00016 .. +0.00012) is not enough |
| P226 | 1825 | rule | first-line-descent-from-armpit-stone | rejected | held-out CE gain -0.00002 nats (90% CI -0.00019 .. +0.00020) is not enough |
| P227 | 1825 | rule | one-two-point-contact-in-corner | accepted | held-out CE gain +0.00346 nats (90% CI +0.00100 .. +0.00593), guards and regression set pass |
| P228 | 1827 | rule | hane-under-end-of-perpendicular-2nd-line-chain | rejected | held-out CE gain +0.00010 nats (90% CI -0.00030 .. +0.00054) is not enough |
| P229 | 1827 | rule | corner-2-1-under-crowded-2-2-block | accepted | held-out CE gain +0.00049 nats (90% CI +0.00012 .. +0.00089), guards and regression set pass |
| P230 | 1827 | rule | connect-cut-lone-two-lib-stone-to-line | accepted | held-out CE gain +0.00045 nats (90% CI +0.00001 .. +0.00094), guards and regression set pass |
| P231 | 1834 | rule | capture-enclosed-lone-stone-near-edge | rejected | held-out CE gain -0.00002 nats (90% CI -0.00042 .. +0.00039) is not enough |
| P232 | 1848 | nudge | dist_last:2 | rejected | held-out CE did not improve (-0.00135 nats) |
| P233 | 1848 | rule | edge-push-under-opp-second-line-stone | rejected | held-out CE gain +0.00129 nats (90% CI -0.00026 .. +0.00309) is not enough |
| P234 | 1848 | rule | first-line-slide-under-opp-to-own-edge-stone | rejected | held-out CE gain -0.00013 nats (90% CI -0.00036 .. +0.00010) is not enough |
| P235 | 1848 | rule | first-line-pinch-of-opp-edge-stone | rejected | held-out CE gain -0.00011 nats (90% CI -0.00065 .. +0.00038) is not enough |
| P236 | 1848 | rule | escape-into-own-eye-is-slow | rejected | held-out CE gain +0.00006 nats (90% CI -0.00011 .. +0.00024) is not enough |
| P237 | 1847 | rule | first-line-hane-at-foot-of-own-column | rejected | held-out CE gain -0.00007 nats (90% CI -0.00022 .. +0.00008) is not enough |
| P238 | 1847 | rule | second-line-hane-after-first-line-hane | rejected | held-out CE gain +0.00019 nats (90% CI -0.00039 .. +0.00086) is not enough |
| P239 | 1847 | rule | first-line-placement-under-pinned-invader | rejected | held-out CE gain -0.00021 nats (90% CI -0.00028 .. -0.00014) is not enough |
| P240 | 1852 | nudge | ladder:capture | rejected | held-out CE did not improve (-0.00078 nats) |
| P241 | 1852 | rule | first-line-throw-in-atari-under-opp-stone | rejected | held-out CE gain -0.00017 nats (90% CI -0.00049 .. +0.00020) is not enough |
| P242 | 1852 | rule | second-line-block-over-head-of-first-line-crawl | rejected | held-out CE gain +0.00041 nats (90% CI -0.00019 .. +0.00103) is not enough |
| P243 | 1852 | rule | first-line-block-end-of-opp-crawl-under-wall | accepted | held-out CE gain +0.00107 nats (90% CI +0.00010 .. +0.00224), guards and regression set pass |
| P244 | 1850 | rule | slow-ko-connection-escape | rejected | same pattern and conditions as rejected proposal P236 (held-out CE gain +0.00006 nats (90% CI -0.00011 .. +0.00024) is not enough) |
| P245 | 1850 | rule | first-line-placement-between-opp-second-line | rejected | held-out CE gain -0.00058 nats (90% CI -0.00107 .. +0.00005) is not enough |
| P246 | 1850 | rule | corner-sacrifice-two-against-enclosed-chain | rejected | held-out CE gain -0.00011 nats (90% CI -0.00018 .. -0.00003) is not enough |
| P247 | 1866 | nudge | R14 | rejected | held-out CE did not improve (-0.00119 nats) |
| P248 | 1866 | rule | slow-ko-connect-escape | rejected | same pattern and conditions as rejected proposal P244 (same pattern and conditions as rejected proposal P236 (held-out CE gain +0.00006 nats (90% CI -0.00011 .. +0.00024) is n) |
| P249 | 1866 | rule | stand-from-wall-toward-opp-stone-two-away | rejected | held-out CE gain +0.00030 nats (90% CI -0.00053 .. +0.00140) is not enough |
| P250 | 1866 | rule | first-line-crawl-under-opp-stone | rejected | held-out CE gain +0.00189 nats (90% CI -0.00007 .. +0.00415) is not enough |
| P251 | 1887 | rule | centre-stand-next-to-own-off-centre-stone | rejected | held-out CE gain -0.00012 nats (90% CI -0.00037 .. +0.00000) is not enough |
| P252 | 1898 | rule | first-line-block-under-own-wall-vs-crawl | rejected | held-out CE gain +0.00029 nats (90% CI -0.00036 .. +0.00100) is not enough |
| P253 | 1898 | rule | take-the-ko | rejected | held-out CE gain -0.00019 nats (90% CI -0.00059 .. +0.00015) is not enough |
| P254 | 1895 | rule | edge-connect-linking-stone-under-wall | rejected | held-out CE gain +0.00003 nats (90% CI -0.00026 .. +0.00036) is not enough |
| P255 | 1895 | rule | slow-rescue-of-abandoned-edge-stone | rejected | held-out CE gain +0.00003 nats (90% CI -0.00021 .. +0.00034) is not enough |
| P256 | 1895 | rule | edge-hane-under-strong-opp-boundary-stone | accepted | held-out CE gain +0.00161 nats (90% CI +0.00071 .. +0.00260), guards and regression set pass |
| P257 | 1888 | rule | atari-on-dead-armpit-stone | rejected | held-out CE gain +0.00003 nats (90% CI -0.00023 .. +0.00026) is not enough |
| P258 | 1888 | rule | dumpling-fill-against-enclosed-chain | rejected | held-out CE gain +0.00013 nats (90% CI -0.00010 .. +0.00039) is not enough |
| P259 | 1888 | rule | first-line-push-under-opp-second-line-stone | rejected | held-out CE gain +0.00025 nats (90% CI -0.00037 .. +0.00097) is not enough |
| P260 | 1923 | rule | edge-climb-into-eye-space-of-weak-big-chain | rejected | held-out CE gain +0.00069 nats (90% CI -0.00005 .. +0.00141) is not enough |
| P261 | 1923 | rule | atari-from-own-walled-point | rejected | held-out CE gain +0.00018 nats (90% CI -0.00008 .. +0.00052) is not enough |
| P262 | 1942 | nudge | line:5+ | rejected | held-out CE did not improve (-0.00043 nats) |
| P263 | 1942 | nudge | R3 | rejected | held-out CE did not improve (-0.00432 nats) |
| P264 | 1942 | rule | extend-outer-stone-after-push-into-diagonal-cut | rejected | held-out CE gain +0.00006 nats (90% CI -0.00028 .. +0.00040) is not enough |
| P265 | 1942 | rule | one-point-jump-approach-on-fourth-line | rejected | held-out CE gain +0.00015 nats (90% CI -0.00003 .. +0.00046) is not enough |
| P266 | 1916 | nudge | R6 | rejected | held-out CE did not improve (-0.00112 nats) |
| P267 | 1916 | nudge | escape:size1:libs3+ | rejected | held-out CE did not improve (-0.00034 nats) |
| P268 | 1916 | rule | edge-block-opp-push-into-short-lib-block | rejected | held-out CE gain +0.00026 nats (90% CI -0.00015 .. +0.00077) is not enough |
| P269 | 1916 | rule | first-line-between-opp-and-own-2nd-line-stones | rejected | held-out CE gain -0.00019 nats (90% CI -0.00025 .. -0.00013) is not enough |
| P270 | 1933 | rule | atari-on-lone-crosscut-stone | rejected | held-out CE gain +0.00006 nats (90% CI -0.00032 .. +0.00044) is not enough |
| P271 | 1933 | rule | crosscut-extend-away-toward-centre | rejected | held-out CE gain +0.00019 nats (90% CI -0.00012 .. +0.00056) is not enough |
| P272 | 1933 | rule | push-into-mutual-head-point | rejected | held-out CE gain +0.00004 nats (90% CI -0.00021 .. +0.00033) is not enough |
| P273 | 1933 | rule | capture-lone-stone-in-own-pocket | rejected | held-out CE gain +0.00030 nats (90% CI -0.00002 .. +0.00064) is not enough |
| P274 | 1968 | rule | undercut-below-far-end-of-blocked-opp-pair | rejected | held-out CE gain -0.00009 nats (90% CI -0.00014 .. -0.00003) is not enough |
| P275 | 1968 | rule | slow-atari-on-ladder-dead-wedge-beside-own-two | rejected | held-out CE gain +0.00026 nats (90% CI -0.00034 .. +0.00083) is not enough |
| P276 | 2019 | nudge | R12 | rejected | held-out CE did not improve (-0.00012 nats) |
| P277 | 2019 | nudge | R4 | rejected | held-out CE did not improve (-0.00014 nats) |
| P278 | 2019 | nudge | R6 | rejected | held-out CE did not improve (-0.00056 nats) |
| P279 | 2019 | rule | capture-armpit-stone-after-nearby-reply | rejected | held-out CE gain +0.00012 nats (90% CI -0.00026 .. +0.00049) is not enough |
| P280 | 2019 | rule | hane-at-head-of-parallel-opp-two | rejected | held-out CE gain -0.00032 nats (90% CI -0.00084 .. +0.00022) is not enough |
| P281 | 2040 | rule | atari-forcing-connect-at-half-cut-link | rejected | held-out CE gain -0.00003 nats (90% CI -0.00013 .. +0.00006) is not enough |
| P282 | 2040 | rule | complete-cut-through-knights-move | accepted | held-out CE gain +0.00481 nats (90% CI +0.00291 .. +0.00671), guards and regression set pass |
| P283 | 2001 | rule | tengen-push-between-own-and-opp-stone | rejected | held-out CE gain -0.00011 nats (90% CI -0.00034 .. +0.00006) is not enough |
| P284 | 2001 | rule | wedge-keima-beside-own-contact-stone | rejected | held-out CE gain +0.00007 nats (90% CI -0.00027 .. +0.00047) is not enough |
| P285 | 2001 | rule | edge-counter-hane-around-hane-stone | rejected | held-out CE gain +0.00016 nats (90% CI -0.00001 .. +0.00034) is not enough |
| P286 | 2001 | rule | attach-lone-stone-with-jump-support | accepted | held-out CE gain +0.00077 nats (90% CI +0.00018 .. +0.00145), guards and regression set pass |
| P287 | 2066 | nudge | R3 | rejected | held-out CE did not improve (-0.00158 nats) |
| P288 | 2066 | rule | hane-on-head-of-lone-stone-beside-own-two | rejected | held-out CE gain -0.00004 nats (90% CI -0.00019 .. +0.00011) is not enough |
| P289 | 2066 | rule | connect-surrounded-stone-in-atari-to-group | rejected | held-out CE gain -0.00015 nats (90% CI -0.00049 .. +0.00017) is not enough |
| P290 | 2097 | nudge | R3 | rejected | held-out CE did not improve (-0.00233 nats) |
| P291 | 2097 | rule | atari-pushing-stone-into-diagonal-friend | rejected | held-out CE gain -0.00021 nats (90% CI -0.00043 .. -0.00001) is not enough |
| P292 | 2097 | rule | undercut-jump-below-opp-knight-stone | rejected | held-out CE gain +0.00003 nats (90% CI -0.00033 .. +0.00037) is not enough |
| P293 | 2097 | rule | second-line-attach-under-opp-with-jump-support | rejected | held-out CE gain +0.00029 nats (90% CI -0.00004 .. +0.00063) is not enough |
| P294 | 2141 | nudge | R8 | rejected | held-out CE did not improve (-0.00043 nats) |
| P295 | 2141 | nudge | R4 | rejected | held-out CE did not improve (-0.00025 nats) |
| P296 | 2141 | rule | wedge-knights-move-of-lone-stones | rejected | held-out CE gain -0.00008 nats (90% CI -0.00028 .. +0.00013) is not enough |
| P297 | 2141 | rule | block-end-of-opp-second-line-chain | rejected | held-out CE gain -0.00012 nats (90% CI -0.00033 .. +0.00007) is not enough |
| P298 | 2135 | rule | hane-seal-opp-column-pinned-by-own-stones | rejected | held-out CE gain +0.00007 nats (90% CI -0.00038 .. +0.00060) is not enough |
| P299 | 2135 | rule | extend-lone-crosscut-stone | rejected | held-out CE gain -0.00010 nats (90% CI -0.00032 .. +0.00009) is not enough |
| P300 | 2135 | rule | atari-crosscut-stone-from-outside | accepted | held-out CE gain +0.00059 nats (90% CI +0.00009 .. +0.00116), guards and regression set pass |
| P301 | 2180 | rule | atari-ladder-dead-crosscut-stone-from-outside | rejected | held-out CE gain +0.00001 nats (90% CI -0.00011 .. +0.00010) is not enough |
| P302 | 2180 | rule | tenuki-extend-own-lone-crosscut-stone | rejected | held-out CE gain -0.00007 nats (90% CI -0.00046 .. +0.00031) is not enough |
| P303 | 2180 | rule | first-line-guard-under-pressed-second-line-stone | rejected | held-out CE gain -0.00002 nats (90% CI -0.00014 .. +0.00013) is not enough |
| P304 | 2200 | nudge | R21 | rejected | held-out CE did not improve (-0.00055 nats) |
| P305 | 2200 | rule | hane-head-of-opp-pair-beside-own-pair | rejected | held-out CE gain +0.00022 nats (90% CI -0.00019 .. +0.00064) is not enough |
| P306 | 2200 | rule | extend-attached-lone-second-line-stone | rejected | held-out CE gain +0.00003 nats (90% CI -0.00025 .. +0.00031) is not enough |
| P307 | 2172 | rule | stretch-beside-parallel-opp-two | rejected | held-out CE gain -0.00008 nats (90% CI -0.00019 .. +0.00002) is not enough |
| P308 | 2172 | rule | open-corner-third-line-boundary-point | rejected | held-out CE gain -0.00009 nats (90% CI -0.00027 .. +0.00009) is not enough |
| P309 | 2172 | rule | slow-capture-of-enclosed-edge-stone | rejected | held-out CE gain +0.00002 nats (90% CI -0.00007 .. +0.00009) is not enough |
| P310 | 2172 | rule | hane-head-of-parallel-opp-two | accepted | held-out CE gain +0.00028 nats (90% CI +0.00002 .. +0.00056), guards and regression set pass |
| P311 | 2241 | nudge | R9 | rejected | held-out CE did not improve (-0.00061 nats) |
| P312 | 2241 | rule | atari-on-cut-point-of-opp-diagonal-link | rejected | held-out CE gain +0.00003 nats (90% CI -0.00016 .. +0.00024) is not enough |
| P313 | 2241 | rule | connect-around-opp-stone-already-in-atari | rejected | held-out CE gain +0.00059 nats (90% CI -0.00009 .. +0.00130) is not enough |
| P314 | 2264 | nudge | ladder:capture | rejected | held-out CE did not improve (-0.00099 nats) |
| P315 | 2264 | rule | kosumi-between-libs-of-own-hit-lone-stone | rejected | held-out CE gain -0.00017 nats (90% CI -0.00042 .. +0.00009) is not enough |
| P316 | 2264 | rule | diagonal-move-beside-own-atari-stone-liberty | accepted | held-out CE gain +0.00175 nats (90% CI +0.00103 .. +0.00245), guards and regression set pass |
| P317 | 2264 | rule | second-line-kosumi-under-opp-third-line-stone | accepted | held-out CE gain +0.00034 nats (90% CI +0.00009 .. +0.00058), guards and regression set pass |
| P318 | 2265 | nudge | R12 | rejected | held-out CE did not improve (-0.00053 nats) |
| P319 | 2265 | nudge | R9 | rejected | held-out CE did not improve (-0.00058 nats) |
| P320 | 2265 | nudge | R19 | rejected | held-out CE did not improve (-0.00172 nats) |
| P321 | 2265 | rule | abandoned-single-stone-capture-is-slow | rejected | held-out CE gain -0.00001 nats (90% CI -0.00003 .. +0.00001) is not enough |
| P322 | 2265 | rule | loose-seal-beside-weak-opp-wall | rejected | held-out CE gain -0.00021 nats (90% CI -0.00037 .. -0.00005) is not enough |
| P323 | 2265 | rule | extend-two-lib-group-to-three-libs | accepted | held-out CE gain +0.00134 nats (90% CI +0.00016 .. +0.00259), guards and regression set pass |
| P324 | 2285 | nudge | R3 | rejected | held-out CE did not improve (-0.00521 nats) |
| P325 | 2285 | nudge | R8 | rejected | held-out CE did not improve (-0.00086 nats) |
| P326 | 2285 | nudge | R9 | rejected | held-out CE did not improve (-0.00107 nats) |
| P327 | 2285 | rule | extend-wedged-edge-cutter-to-first-line | rejected | held-out CE gain -0.00055 nats (90% CI -0.00097 .. -0.00015) is not enough |
| P328 | 2285 | rule | edge-hane-under-blocker-of-own-second-line-two | rejected | held-out CE gain -0.00001 nats (90% CI -0.00065 .. +0.00074) is not enough |
| P329 | 2297 | rule | second-line-invasion-under-opp-fourth-line | rejected | held-out CE gain +0.00016 nats (90% CI -0.00036 .. +0.00070) is not enough |
| P330 | 2297 | rule | corner-two-two-inside-opp-hane-stone | rejected | held-out CE gain +0.00006 nats (90% CI -0.00021 .. +0.00040) is not enough |
| P331 | 2289 | rule | first-line-extend-sandwiched-stone-in-atari | rejected | held-out CE gain +0.00002 nats (90% CI -0.00058 .. +0.00067) is not enough |
| P332 | 2277 | rule | move-on-open-side-of-netted-pair | rejected | held-out CE gain +0.00011 nats (90% CI -0.00031 .. +0.00052) is not enough |
| P333 | 2277 | rule | throw-in-atari-on-lone-two-lib-stone | rejected | held-out CE gain -0.00000 nats (90% CI -0.00001 .. +0.00001) is not enough |
| P334 | 2277 | rule | knight-cut-point-already-joined-by-own-stones | rejected | held-out CE gain -0.00019 nats (90% CI -0.00039 .. +0.00000) is not enough |
| P335 | 2301 | rule | corner-2-2-invasion-under-opp-diagonal-pair | rejected | held-out CE gain +0.00004 nats (90% CI -0.00012 .. +0.00030) is not enough |
| P336 | 2301 | rule | second-line-jump-slide-under-opp-third-line | rejected | held-out CE gain -0.00015 nats (90% CI -0.00052 .. +0.00020) is not enough |
| P337 | 2301 | rule | second-line-block-of-slide-under-own-wall | rejected | held-out CE gain +0.00058 nats (90% CI -0.00024 .. +0.00158) is not enough |
| P338 | 2307 | nudge | R8 | rejected | held-out CE did not improve (-0.00143 nats) |
| P339 | 2307 | rule | second-line-under-fourth-line-wall | rejected | held-out CE gain +0.00001 nats (90% CI -0.00000 .. +0.00001) is not enough |
| P340 | 2307 | rule | edge-atari-on-wedge-joining-own-stones | rejected | held-out CE gain -0.00019 nats (90% CI -0.00035 .. -0.00004) is not enough |
| P341 | 2323 | rule | fill-liberty-of-big-three-lib-chain | accepted | held-out CE gain +0.00111 nats (90% CI +0.00022 .. +0.00208), guards and regression set pass |
| P342 | 2316 | rule | corner-2-2-inside-opp-loose-enclosure | rejected | held-out CE gain -0.00004 nats (90% CI -0.00026 .. +0.00031) is not enough |
| P343 | 2316 | rule | stretch-pressed-two-toward-own-diagonal-stone | rejected | held-out CE gain +0.00031 nats (90% CI -0.00062 .. +0.00126) is not enough |
| P344 | 2316 | rule | connect-diagonal-taking-lib-of-short-opp-chain | rejected | held-out CE gain -0.00049 nats (90% CI -0.00075 .. -0.00028) is not enough |
| P345 | 2316 | rule | second-line-slide-under-weak-opp-third-line-pair | rejected | held-out CE gain +0.00003 nats (90% CI -0.00003 .. +0.00011) is not enough |
| P346 | 2350 | nudge | R21 | rejected | held-out CE did not improve (-0.00219 nats) |
| P347 | 2350 | rule | edge-descent-beside-opp-double-atari-point | rejected | held-out CE gain +0.00030 nats (90% CI -0.00024 .. +0.00094) is not enough |
| P348 | 2350 | rule | atari-driving-stone-into-its-friends | rejected | held-out CE gain +0.00000 nats (90% CI -0.00000 .. +0.00001) is not enough |
| P349 | 2386 | nudge | R3 | rejected | held-out CE did not improve (-0.00247 nats) |
| P350 | 2386 | nudge | R14 | rejected | held-out CE did not improve (-0.00109 nats) |
| P351 | 2386 | nudge | capture:1 | rejected | held-out CE did not improve (-0.00021 nats) |
| P352 | 2386 | rule | solid-connect-lone-two-lib-stone-at-junction | rejected | held-out CE gain +0.00001 nats (90% CI -0.00005 .. +0.00009) is not enough |
| P353 | 2386 | rule | crosscut-connect-and-atari-point-overrated | rejected | held-out CE gain +0.00012 nats (90% CI -0.00014 .. +0.00038) is not enough |
| P354 | 2386 | rule | first-line-descent-of-wedge-in-atari | rejected | held-out CE gain -0.00006 nats (90% CI -0.00019 .. +0.00008) is not enough |
| P355 | 2364 | rule | slow-atari-on-abandoned-ladder-dead-stone | rejected | held-out CE gain +0.00025 nats (90% CI -0.00015 .. +0.00065) is not enough |
| P356 | 2364 | rule | knight-cut-atari-on-ladder-dead-stone | rejected | held-out CE gain +0.00027 nats (90% CI -0.00030 .. +0.00094) is not enough |
| P357 | 2364 | rule | diagonal-beside-cuttable-liberty-of-own-group | rejected | held-out CE gain -0.00018 nats (90% CI -0.00026 .. -0.00010) is not enough |
| P358 | 2406 | nudge | R26 | rejected | held-out CE did not improve (-0.00017 nats) |
| P359 | 2406 | rule | first-line-lib-fill-under-own-wall | rejected | held-out CE gain +0.00001 nats (90% CI -0.00022 .. +0.00025) is not enough |
| P360 | 2406 | rule | atari-big-ladder-dead-chain | rejected | held-out CE gain +0.00136 nats (90% CI -0.00064 .. +0.00371) is not enough |
| P361 | 2427 | rule | edge-connect-across-opp-cut | accepted | held-out CE gain +0.00057 nats (90% CI +0.00005 .. +0.00121), guards and regression set pass |
| P362 | 2439 | rule | first-line-block-by-opp-edge-stone-under-wall | rejected | held-out CE gain +0.00009 nats (90% CI -0.00050 .. +0.00076) is not enough |
| P363 | 2439 | rule | slow-atari-on-ladder-dead-two-stone-chain | rejected | held-out CE gain +0.00053 nats (90% CI -0.00042 .. +0.00164) is not enough |
| P364 | 2439 | rule | first-line-atari-on-big-two-lib-chain | rejected | held-out CE gain +0.00000 nats (90% CI -0.00039 .. +0.00045) is not enough |
| P365 | 2459 | rule | first-line-block-beside-probe-diagonal-own | rejected | held-out CE gain -0.00011 nats (90% CI -0.00035 .. +0.00014) is not enough |
| P366 | 2459 | rule | first-line-descent-under-lone-stone-vs-contact | rejected | held-out CE gain -0.00001 nats (90% CI -0.00001 .. -0.00000) is not enough |
| P367 | 2454 | rule | atari-from-own-two-lib-chain | rejected | held-out CE gain -0.00020 nats (90% CI -0.00064 .. +0.00024) is not enough |
| P368 | 2454 | rule | edge-capture-of-enclosed-second-line-stone | rejected | held-out CE gain +0.00010 nats (90% CI -0.00016 .. +0.00039) is not enough |
| P369 | 2454 | rule | first-line-crawl-of-two-lib-stone | rejected | held-out CE gain -0.00012 nats (90% CI -0.00039 .. +0.00011) is not enough |
| P370 | 2454 | rule | corner-2-1-placement-under-opp-3-2-stone | rejected | held-out CE gain -0.00005 nats (90% CI -0.00010 .. +0.00003) is not enough |
| P371 | 2492 | nudge | R20 | rejected | held-out CE did not improve (-0.00053 nats) |
| P372 | 2492 | nudge | R1 | rejected | held-out CE did not improve (-0.00030 nats) |
| P373 | 2492 | rule | third-line-extension-from-centre-under-knight | rejected | held-out CE gain +0.00019 nats (90% CI -0.00002 .. +0.00043) is not enough |
| P374 | 2484 | nudge | R27 | rejected | held-out CE did not improve (-0.00133 nats) |
| P375 | 2484 | rule | capture-enclosed-stone-with-lone-stone | rejected | held-out CE gain +0.00008 nats (90% CI -0.00013 .. +0.00028) is not enough |
| P376 | 2484 | rule | connect-own-mouth-against-peep | rejected | held-out CE gain -0.00006 nats (90% CI -0.00012 .. -0.00001) is not enough |
| P377 | 2508 | nudge | R14 | rejected | held-out CE did not improve (-0.00275 nats) |
| P378 | 2508 | nudge | R3 | rejected | held-out CE did not improve (-0.00387 nats) |
| P379 | 2508 | rule | corner-2-2-behind-own-second-line-stone | rejected | held-out CE gain -0.00017 nats (90% CI -0.00038 .. +0.00008) is not enough |
| P380 | 2508 | rule | edge-false-eye-connect-weak-stone | rejected | held-out CE gain -0.00015 nats (90% CI -0.00146 .. +0.00144) is not enough |
| P381 | 2549 | rule | side-midpoint-jump-from-opp-centre-knight-backed | rejected | held-out CE gain +0.00009 nats (90% CI -0.00020 .. +0.00051) is not enough |
| P382 | 2549 | rule | side-midpoint-jump-from-own-centre-vs-knight | rejected | held-out CE gain +0.00006 nats (90% CI -0.00012 .. +0.00025) is not enough |
| P383 | 2549 | rule | split-opp-gap-from-own-stone | rejected | held-out CE gain +0.00026 nats (90% CI -0.00005 .. +0.00070) is not enough |
| P384 | 2560 | nudge | R27 | rejected | held-out CE did not improve (-0.00098 nats) |
| P385 | 2560 | nudge | R25 | rejected | held-out CE did not improve (-0.00007 nats) |
| P386 | 2560 | rule | capture-dead-stone-in-own-mouth | rejected | matches no legal move in 600 training positions |
| P387 | 2560 | rule | self-atari-atari-throw-in | rejected | held-out CE gain -0.00024 nats (90% CI -0.00074 .. +0.00017) is not enough |
| P388 | 2607 | rule | lone-stone-in-armpit-of-strong-chain | accepted | held-out CE gain +0.00031 nats (90% CI +0.00007 .. +0.00051), guards and regression set pass |
| P389 | 2593 | nudge | R22 | rejected | held-out CE did not improve (-0.00082 nats) |
| P390 | 2593 | rule | third-line-point-in-empty-area | rejected | held-out CE gain -0.00008 nats (90% CI -0.00017 .. -0.00000) is not enough |
| P391 | 2593 | rule | no-open-side-hane-under-contact-stone | rejected | held-out CE gain -0.00011 nats (90% CI -0.00027 .. +0.00002) is not enough |
| P392 | 2593 | rule | stretch-beside-own-stone-over-their-low-stone | rejected | held-out CE gain +0.00019 nats (90% CI -0.00020 .. +0.00062) is not enough |
| P393 | 2593 | rule | stand-over-their-low-stone-beside-own-stone | rejected | held-out CE gain +0.00027 nats (90% CI -0.00012 .. +0.00071) is not enough |
| P394 | 2631 | rule | third-line-jump-from-own-lone-stone | rejected | held-out CE gain +0.00010 nats (90% CI -0.00024 .. +0.00049) is not enough |
| P395 | 2631 | rule | knight-from-own-stone-under-opp-centre-stone | rejected | held-out CE gain +0.00012 nats (90% CI -0.00003 .. +0.00029) is not enough |
| P396 | 2646 | rule | open-between-diagonal-of-own-and-opp-stone | rejected | held-out CE gain -0.00015 nats (90% CI -0.00025 .. -0.00005) is not enough |
| P397 | 2646 | rule | between-diagonal-of-own-and-opp-opposite-corners | rejected | held-out CE gain +0.00008 nats (90% CI +0.00000 .. +0.00017) is not enough |
| P398 | 2695 | rule | corner-2-2-diagonal-under-opp-3-3-stone | rejected | same pattern and conditions as rejected proposal P182 (held-out CE gain -0.00065 nats (90% CI -0.00119 .. -0.00002) is not enough) |
| P399 | 2695 | rule | second-line-knight-slide-from-lone-3rd-line | rejected | held-out CE gain +0.00003 nats (90% CI -0.00027 .. +0.00038) is not enough |
| P400 | 2702 | nudge | R20 | rejected | held-out CE did not improve (-0.00082 nats) |
| P401 | 2702 | rule | diagonal-step-into-empty-quarter | rejected | held-out CE gain +0.00001 nats (90% CI -0.00017 .. +0.00020) is not enough |
| P402 | 2702 | rule | extend-from-own-stone-into-empty-side | rejected | held-out CE gain +0.00002 nats (90% CI -0.00001 .. +0.00005) is not enough |
| P403 | 2702 | rule | no-press-on-lone-stone-from-centre-side | rejected | held-out CE gain -0.00004 nats (90% CI -0.00021 .. +0.00012) is not enough |
| P404 | 2731 | rule | third-line-check-two-from-opp-side-stone | rejected | held-out CE gain +0.00001 nats (90% CI -0.00046 .. +0.00052) is not enough |
| P405 | 2731 | rule | butt-between-own-and-opp-jump-stones | accepted | held-out CE gain +0.00023 nats (90% CI +0.00004 .. +0.00043), guards and regression set pass |
| P406 | 2739 | rule | second-line-knight-from-own-third-line-stone | rejected | held-out CE gain -0.00014 nats (90% CI -0.00022 .. -0.00006) is not enough |
| P407 | 2739 | rule | slow-second-line-connect-vs-edge-cut | rejected | held-out CE gain +0.00003 nats (90% CI -0.00024 .. +0.00030) is not enough |
| P408 | 2739 | rule | second-line-base-under-own-fourth-line-stone | accepted | held-out CE gain +0.00032 nats (90% CI +0.00021 .. +0.00044), guards and regression set pass |
| P409 | 2770 | nudge | line:2 | rejected | held-out CE did not improve (-0.00347 nats) |
| P410 | 2770 | rule | second-line-base-under-own-fourth-line-stone | rejected | held-out CE gain -0.00014 nats (90% CI -0.00067 .. +0.00044) is not enough |
| P411 | 2770 | rule | second-line-undermine-opp-fourth-line-stone | rejected | held-out CE gain -0.00004 nats (90% CI -0.00017 .. +0.00010) is not enough |
| P412 | 2768 | nudge | dist_last:2 | rejected | held-out CE did not improve (-0.00169 nats) |
| P413 | 2768 | rule | second-line-hane-vs-lone-probe-under-own-stone | rejected | held-out CE gain -0.00003 nats (90% CI -0.00013 .. +0.00006) is not enough |
| P414 | 2768 | rule | third-line-stretch-toward-opp-knight-stone | rejected | held-out CE gain -0.00019 nats (90% CI -0.00035 .. -0.00004) is not enough |
| P415 | 2810 | nudge | R30 | rejected | held-out CE did not improve (-0.00297 nats) |
| P416 | 2810 | rule | second-line-base-straight-under-own-fourth | rejected | held-out CE gain -0.00001 nats (90% CI -0.00031 .. +0.00032) is not enough |
| P417 | 2810 | rule | second-line-undermine-straight-under-opp-fourth | rejected | held-out CE gain -0.00006 nats (90% CI -0.00022 .. +0.00012) is not enough |
| P418 | 2822 | nudge | R3 | rejected | held-out CE did not improve (-0.00521 nats) |
| P419 | 2822 | rule | second-line-probe-beside-pincer-of-own-stone | rejected | held-out CE gain -0.00059 nats (90% CI -0.00104 .. -0.00013) is not enough |
| P420 | 2822 | rule | connect-ladderable-stone-across-one-point-gap | rejected | held-out CE gain -0.00008 nats (90% CI -0.00019 .. +0.00002) is not enough |
| P421 | 2863 | nudge | atari:size2+ | rejected | held-out CE did not improve (-0.00068 nats) |
| P422 | 2863 | rule | fill-miai-diagonal-of-two-lib-chain | rejected | held-out CE gain +0.00001 nats (90% CI -0.00001 .. +0.00003) is not enough |
| P423 | 2863 | rule | atari-leaving-own-stone-two-libs | rejected | held-out CE gain +0.00009 nats (90% CI +0.00001 .. +0.00017) is not enough |
| P424 | 2862 | nudge | R3 | rejected | held-out CE did not improve (-0.00177 nats) |
| P425 | 2862 | rule | corner-2-2-beside-3-4-stone | rejected | held-out CE gain -0.00001 nats (90% CI -0.00043 .. +0.00049) is not enough |
| P426 | 2862 | rule | jump-guard-making-tiger-mouth | rejected | held-out CE gain -0.00003 nats (90% CI -0.00010 .. +0.00005) is not enough |
| P427 | 2881 | rule | slow-capture-of-enclosed-edge-stone | rejected | held-out CE gain -0.00024 nats (90% CI -0.00080 .. +0.00037) is not enough |
| P428 | 2924 | nudge | R21 | rejected | held-out CE did not improve (-0.00318 nats) |
| P429 | 2924 | rule | second-line-undercut-beside-opp-pincer | rejected | held-out CE gain -0.00018 nats (90% CI -0.00046 .. +0.00009) is not enough |
| P430 | 2924 | rule | second-line-block-under-own-pincer | rejected | held-out CE gain +0.00018 nats (90% CI -0.00014 .. +0.00052) is not enough |
| P431 | 2925 | rule | corner-2-2-under-approach-stone | rejected | held-out CE gain +0.00004 nats (90% CI -0.00031 .. +0.00046) is not enough |
| P432 | 2932 | nudge | R6 | rejected | held-out CE did not improve (-0.00099 nats) |
| P433 | 2932 | rule | second-line-base-opposite-fourth-line-pair-end | rejected | held-out CE gain -0.00016 nats (90% CI -0.00047 .. +0.00018) is not enough |
| P434 | 2966 | rule | fill-one-point-gap-beside-diagonal-opp-stone | rejected | held-out CE gain -0.00004 nats (90% CI -0.00025 .. +0.00017) is not enough |
| P435 | 2966 | rule | armpit-stone-connect-out-to-diagonal-stone | rejected | held-out CE gain +0.00030 nats (90% CI -0.00002 .. +0.00061) is not enough |
| P436 | 2965 | rule | second-line-prep-beyond-sole-link-of-edge-pair | rejected | held-out CE gain +0.00065 nats (90% CI -0.00047 .. +0.00195) is not enough |
| P437 | 2965 | rule | early-connect-at-sole-second-line-link | rejected | held-out CE gain +0.00005 nats (90% CI -0.00027 .. +0.00032) is not enough |
| P438 | 2965 | rule | bare-second-line-cut-at-sole-link-two-libs | accepted | held-out CE gain +0.00181 nats (90% CI +0.00107 .. +0.00266), guards and regression set pass |
| P439 | 2991 | nudge | R19 | rejected | held-out CE did not improve (-0.00246 nats) |
| P440 | 2991 | rule | corner-2-2-under-own-pincered-2-3-stone | accepted | held-out CE gain +0.00038 nats (90% CI +0.00002 .. +0.00084), guards and regression set pass |
| P441 | 3000 | nudge | R25 | rejected | held-out CE did not improve (-0.00058 nats) |
| P442 | 3000 | rule | fill-centre-gap-linking-contacted-pair | rejected | held-out CE gain +0.00072 nats (90% CI -0.00007 .. +0.00169) is not enough |
| P443 | 3000 | rule | second-line-stand-under-lone-stone-vs-approach | rejected | held-out CE gain +0.00004 nats (90% CI -0.00014 .. +0.00025) is not enough |
| P444 | 3011 | nudge | dist_last:2 | rejected | held-out CE did not improve (-0.00225 nats) |
| P445 | 3011 | rule | corner-1-2-point-by-3-2-and-2-3-stones | rejected | held-out CE gain -0.00043 nats (90% CI -0.00063 .. -0.00023) is not enough |
| P446 | 3011 | rule | second-line-hane-under-opp-third-line-wall | rejected | held-out CE gain +0.00004 nats (90% CI -0.00017 .. +0.00024) is not enough |
| P447 | 3011 | rule | second-line-block-under-opp-hane-point | rejected | held-out CE gain -0.00014 nats (90% CI -0.00035 .. +0.00007) is not enough |
| P448 | 3035 | nudge | R9 | rejected | held-out CE did not improve (-0.00056 nats) |
| P449 | 3035 | nudge | R11 | rejected | held-out CE did not improve (-0.00010 nats) |
| P450 | 3035 | rule | slow-atari-on-ladder-dead-lone-stone | rejected | same pattern and conditions as rejected proposal P217 (held-out CE gain +0.00015 nats (90% CI -0.00030 .. +0.00058) is not enough) |
| P451 | 3035 | rule | second-line-under-gap-of-opposing-3rd-line-pair | rejected | held-out CE gain -0.00017 nats (90% CI -0.00046 .. +0.00012) is not enough |
| P452 | 3035 | rule | block-under-own-3rd-line-stone-vs-gap-probe | accepted | held-out CE gain +0.00107 nats (90% CI +0.00034 .. +0.00189), guards and regression set pass |
| P453 | 3034 | rule | corner-1-2-eye-point-of-bent-three | rejected | held-out CE gain +0.00022 nats (90% CI -0.00046 .. +0.00131) is not enough |
| P454 | 3068 | nudge | R3 | rejected | held-out CE did not improve (-0.00397 nats) |
| P455 | 3068 | nudge | R15 | rejected | held-out CE did not improve (-0.00023 nats) |
| P456 | 3068 | rule | corner-placement-diagonal-to-enclosed-bent-three | rejected | held-out CE gain +0.00055 nats (90% CI -0.00018 .. +0.00168) is not enough |
| P457 | 3069 | rule | knight-cut-that-joins-into-two-libs | rejected | held-out CE gain +0.00021 nats (90% CI -0.00012 .. +0.00056) is not enough |
| P458 | 3069 | rule | shared-liberty-extension-vs-big-chain | rejected | held-out CE gain -0.00020 nats (90% CI -0.00037 .. -0.00003) is not enough |
| P459 | 3069 | rule | second-line-push-into-kosumi-gap | rejected | held-out CE gain +0.00020 nats (90% CI -0.00015 .. +0.00060) is not enough |
| P460 | 3069 | rule | stretch-head-of-bent-wall-vs-side-press | rejected | held-out CE gain -0.00007 nats (90% CI -0.00021 .. +0.00012) is not enough |
| P461 | 3073 | nudge | R18 | rejected | held-out CE did not improve (-0.00068 nats) |
| P462 | 3073 | nudge | R15 | rejected | held-out CE did not improve (-0.00012 nats) |
| P463 | 3073 | nudge | R14 | rejected | held-out CE did not improve (-0.00053 nats) |
| P464 | 3073 | nudge | R6 | rejected | held-out CE did not improve (-0.00121 nats) |
| P465 | 3073 | rule | corner-2-1-placement-under-opp-2-2-eye | rejected | held-out CE gain +0.00041 nats (90% CI -0.00027 .. +0.00145) is not enough |
| P466 | 3074 | nudge | R18 | rejected | held-out CE did not improve (-0.00044 nats) |
| P467 | 3074 | rule | corner-1-2-placement-in-opp-bent-three | rejected | held-out CE gain +0.00054 nats (90% CI -0.00013 .. +0.00138) is not enough |
| P468 | 3074 | rule | first-line-under-gap-of-facing-2nd-line-stones | rejected | held-out CE gain +0.00026 nats (90% CI -0.00018 .. +0.00083) is not enough |
| P469 | 3074 | rule | corner-1-2-contact-on-big-healthy-chain | rejected | held-out CE gain +0.00001 nats (90% CI -0.00021 .. +0.00020) is not enough |
| P470 | 3098 | rule | corner-1-2-beside-own-contacted-2-2-stone | rejected | held-out CE gain +0.00050 nats (90% CI -0.00066 .. +0.00196) is not enough |
| P471 | 3099 | nudge | ladder:capture | rejected | held-out CE did not improve (-0.00149 nats) |
| P472 | 3099 | nudge | R3 | rejected | held-out CE did not improve (-0.00322 nats) |
| P473 | 3099 | rule | corner-descent-under-own-lone-2-2-stone | rejected | held-out CE gain -0.00041 nats (90% CI -0.00115 .. +0.00058) is not enough |
| P474 | 3099 | rule | slow-capture-of-sealed-dead-stones | accepted | held-out CE gain +0.00044 nats (90% CI +0.00012 .. +0.00084), guards and regression set pass |
| P475 | 3101 | rule | edge-hane-from-own-edge-pair-under-opp-stone | rejected | held-out CE gain +0.00007 nats (90% CI -0.00083 .. +0.00103) is not enough |
| P476 | 3101 | rule | cut-and-atari-on-ladder-dead-chain | rejected | held-out CE gain +0.00016 nats (90% CI -0.00040 .. +0.00078) is not enough |
| P477 | 3100 | rule | extend-own-2-2-stone-to-1-2-under-opp-3-3 | rejected | held-out CE gain +0.00152 nats (90% CI -0.00079 .. +0.00454) is not enough |
| P478 | 3100 | rule | hane-1-2-under-opp-2-2-from-own-3-3 | rejected | held-out CE gain +0.00025 nats (90% CI -0.00042 .. +0.00105) is not enough |
| P479 | 3100 | rule | atari-dead-chain-between-own-stones | accepted | held-out CE gain +0.00075 nats (90% CI +0.00011 .. +0.00161), guards and regression set pass |
| P480 | 3100 | rule | slow-capture-of-abandoned-inland-stones | accepted | held-out CE gain +0.00056 nats (90% CI +0.00011 .. +0.00108), guards and regression set pass |
| P481 | 3097 | nudge | R9 | rejected | held-out CE did not improve (-0.00277 nats) |
| P482 | 3097 | rule | descend-embedded-own-2-2-under-opp-3-3 | rejected | held-out CE gain +0.00090 nats (90% CI -0.00090 .. +0.00322) is not enough |
| P483 | 3097 | rule | hane-under-opp-2-2-stone-below-own-3-3 | rejected | held-out CE gain +0.00013 nats (90% CI -0.00062 .. +0.00100) is not enough |
| P484 | 3097 | rule | connect-lone-stone-hit-by-hane-to-group | rejected | held-out CE gain +0.00055 nats (90% CI -0.00006 .. +0.00128) is not enough |
| P485 | 3106 | rule | first-line-extend-own-2-2-stone-under-opp-3-3 | rejected | held-out CE gain +0.00141 nats (90% CI -0.00167 .. +0.00527) is not enough |
| P486 | 3106 | rule | first-line-kill-opp-2-2-stone-under-own-3-3 | rejected | held-out CE gain +0.00002 nats (90% CI -0.00096 .. +0.00113) is not enough |
| P487 | 3110 | nudge | R12 | rejected | held-out CE did not improve (-0.00032 nats) |
| P488 | 3110 | nudge | R25 | rejected | held-out CE did not improve (-0.00008 nats) |
| P489 | 3110 | rule | second-line-base-beside-4th-line-contact | rejected | held-out CE gain -0.00026 nats (90% CI -0.00042 .. -0.00006) is not enough |
| P490 | 3110 | rule | edge-block-under-own-wall-vs-first-line-stone | rejected | held-out CE gain +0.00065 nats (90% CI -0.00014 .. +0.00155) is not enough |
| P491 | 3110 | rule | connect-lone-two-lib-stone-at-their-atari-point | rejected | held-out CE gain -0.00006 nats (90% CI -0.00014 .. +0.00003) is not enough |
| P492 | 3110 | rule | capture-armpit-stone-mid-distance | rejected | held-out CE gain +0.00022 nats (90% CI -0.00005 .. +0.00049) is not enough |
| P493 | 3108 | rule | capture-stone-boxed-on-three-sides | rejected | held-out CE gain +0.00006 nats (90% CI -0.00024 .. +0.00036) is not enough |
| P494 | 3108 | rule | atari-on-abandoned-ladder-dead-chain | rejected | held-out CE gain +0.00019 nats (90% CI -0.00005 .. +0.00042) is not enough |
| P495 | 3159 | rule | shoulder-between-own-centre-and-opp-stone | rejected | held-out CE gain +0.00002 nats (90% CI -0.00008 .. +0.00010) is not enough |
| P496 | 3159 | rule | low-kosumi-beside-own-opp-jump-gap | rejected | held-out CE gain -0.00035 nats (90% CI -0.00064 .. -0.00007) is not enough |
| P497 | 3159 | rule | third-line-knight-approach-lone-opp-stone | rejected | held-out CE gain +0.00017 nats (90% CI -0.00004 .. +0.00039) is not enough |
| P498 | 3231 | rule | open-jump-cap-of-older-lone-opp-stone | accepted | held-out CE gain +0.00074 nats (90% CI +0.00004 .. +0.00160), guards and regression set pass |
| P499 | 3259 | rule | third-line-undercut-below-opp-stone-own-knight | rejected | held-out CE gain -0.00006 nats (90% CI -0.00032 .. +0.00022) is not enough |
| P500 | 3259 | rule | kosumi-under-attached-stone-knight-backed | rejected | held-out CE gain -0.00006 nats (90% CI -0.00021 .. +0.00013) is not enough |
| P501 | 3555 | nudge | R22 | rejected | held-out CE did not improve (-0.00064 nats) |
| P502 | 3555 | nudge | dist_last:2 | rejected | held-out CE did not improve (-0.00103 nats) |
| P503 | 3555 | rule | open-third-line-knight-approach-empty-area | accepted | held-out CE gain +0.00067 nats (90% CI +0.00022 .. +0.00119), guards and regression set pass |
| P504 | 3664 | nudge | R8 | rejected | held-out CE did not improve (-0.00062 nats) |
| P505 | 3664 | nudge | line:4 | rejected | held-out CE did not improve (-0.00049 nats) |
| P506 | 3664 | rule | second-line-base-straight-under-own-lone-4th | rejected | held-out CE gain -0.00007 nats (90% CI -0.00032 .. +0.00020) is not enough |
| P507 | 3664 | rule | second-line-hane-beside-lone-opp-slide | rejected | held-out CE gain +0.00015 nats (90% CI -0.00004 .. +0.00035) is not enough |
| P508 | 3664 | rule | draw-back-capped-lone-stone-to-third-line | rejected | held-out CE gain -0.00036 nats (90% CI -0.00049 .. -0.00025) is not enough |
| P509 | 3664 | rule | second-line-head-stretch-beside-parallel-opp | rejected | held-out CE gain -0.00001 nats (90% CI -0.00006 .. +0.00004) is not enough |
| P510 | 3767 | rule | second-line-base-straight-under-lone-4th-tenuki | rejected | held-out CE gain +0.00021 nats (90% CI -0.00019 .. +0.00068) is not enough |
| P511 | 3767 | rule | second-line-crawl-at-head-of-own-edge-two | rejected | held-out CE gain -0.00008 nats (90% CI -0.00017 .. -0.00000) is not enough |
| P512 | 3835 | rule | stand-under-attached-third-line-stone | rejected | held-out CE gain +0.00003 nats (90% CI -0.00013 .. +0.00022) is not enough |
| P513 | 3835 | rule | edge-hane-on-attacher-leaves-crosscut | rejected | held-out CE gain +0.00006 nats (90% CI +0.00001 .. +0.00011) is not enough |
| P514 | 3835 | rule | probe-beyond-cut-point-of-opp-diagonal | rejected | held-out CE gain +0.00038 nats (90% CI -0.00021 .. +0.00102) is not enough |
| P515 | 3894 | nudge | line:2 | rejected | held-out CE did not improve (-0.00008 nats) |
| P516 | 3894 | rule | corner-2-2-under-opp-3-4-stone-open-corner | rejected | held-out CE gain +0.00020 nats (90% CI -0.00029 .. +0.00074) is not enough |
| P517 | 3894 | rule | cut-through-opp-jump-backed-from-behind | rejected | held-out CE gain +0.00029 nats (90% CI -0.00039 .. +0.00098) is not enough |
| P518 | 3975 | nudge | R33 | rejected | held-out CE did not improve (-0.00057 nats) |
| P519 | 3975 | rule | attach-beside-invader-under-own-4th-line | rejected | held-out CE gain +0.00016 nats (90% CI -0.00033 .. +0.00073) is not enough |
| P520 | 3975 | rule | hane-head-of-two-with-cut-covered | rejected | held-out CE gain +0.00040 nats (90% CI -0.00013 .. +0.00105) is not enough |
| P521 | 4047 | nudge | R6 | rejected | held-out CE did not improve (-0.00065 nats) |
| P522 | 4047 | nudge | R14 | rejected | held-out CE did not improve (-0.00070 nats) |
| P523 | 4047 | rule | edge-side-clamp-on-lone-invader | rejected | held-out CE gain +0.00037 nats (90% CI -0.00036 .. +0.00128) is not enough |
| P524 | 4120 | rule | jump-under-opp-4th-line-stone-open-corner | rejected | held-out CE gain -0.00022 nats (90% CI -0.00037 .. -0.00005) is not enough |
| P525 | 4120 | rule | contact-block-under-opp-stone-open-corner | rejected | held-out CE gain -0.00004 nats (90% CI -0.00019 .. +0.00010) is not enough |
| P526 | 4120 | rule | second-line-block-under-own-pair-vs-lone-stone | rejected | held-out CE gain -0.00007 nats (90% CI -0.00012 .. -0.00003) is not enough |
| P527 | 4184 | nudge | R3 | rejected | held-out CE did not improve (-0.00304 nats) |
| P528 | 4184 | nudge | R21 | rejected | held-out CE did not improve (-0.00102 nats) |
| P529 | 4184 | rule | third-line-jump-under-diagonal-opp-stone | rejected | held-out CE gain -0.00018 nats (90% CI -0.00044 .. +0.00010) is not enough |
| P530 | 4184 | rule | second-line-base-under-opp-4th-and-3rd-line | rejected | held-out CE gain +0.00031 nats (90% CI -0.00009 .. +0.00077) is not enough |
| P531 | 4260 | rule | edge-capture-capturer-left-two-libs | rejected | held-out CE gain -0.00021 nats (90% CI -0.00055 .. +0.00009) is not enough |
| P532 | 4260 | rule | slow-rescue-of-abandoned-lone-stone | rejected | held-out CE gain +0.00016 nats (90% CI -0.00029 .. +0.00063) is not enough |
| P533 | 4325 | rule | point-beyond-open-link-of-their-diagonal | rejected | held-out CE gain +0.00006 nats (90% CI -0.00043 .. +0.00058) is not enough |
| P534 | 4325 | rule | slow-fill-of-own-unpeeped-diagonal-link | rejected | held-out CE gain -0.00004 nats (90% CI -0.00009 .. +0.00000) is not enough |
| P535 | 4389 | rule | mouth-of-opp-hollow-three | rejected | held-out CE gain -0.00068 nats (90% CI -0.00113 .. -0.00020) is not enough |
| P536 | 4389 | rule | edge-descent-beside-lone-stone-for-weak-chain | rejected | held-out CE gain +0.00001 nats (90% CI -0.00019 .. +0.00023) is not enough |
| P537 | 4391 | nudge | R14 | rejected | held-out CE did not improve (-0.00033 nats) |
| P538 | 4391 | rule | edge-throw-in-on-big-chain-short-of-libs | rejected | held-out CE gain -0.00016 nats (90% CI -0.00030 .. -0.00005) is not enough |
| P539 | 4391 | rule | corner-1-2-atari-on-lone-2-lib-stone | rejected | held-out CE gain -0.00024 nats (90% CI -0.00041 .. -0.00007) is not enough |
| P540 | 4391 | rule | edge-double-atari-split-by-own-diagonal | rejected | held-out CE gain -0.00024 nats (90% CI -0.00038 .. -0.00011) is not enough |
| P541 | 4408 | rule | corner-1-2-placement-in-opp-enclosure | rejected | held-out CE gain +0.00116 nats (90% CI -0.00004 .. +0.00261) is not enough |
| P542 | 4408 | rule | corner-1-1-under-opp-2-2-stone | rejected | held-out CE gain -0.00050 nats (90% CI -0.00065 .. -0.00035) is not enough |
| P543 | 4408 | rule | first-line-atari-chasing-escaping-chain | accepted | held-out CE gain +0.00015 nats (90% CI +0.00007 .. +0.00025), guards and regression set pass |
| P544 | 4465 | nudge | atari:size1 | rejected | held-out CE did not improve (-0.00168 nats) |
| P545 | 4465 | rule | fill-own-third-line-two-gap-under-pressure | rejected | held-out CE gain +0.00010 nats (90% CI -0.00028 .. +0.00049) is not enough |
| P546 | 4465 | rule | corner-2-2-under-opp-fourth-line-pair | rejected | held-out CE gain -0.00016 nats (90% CI -0.00053 .. +0.00028) is not enough |
| P547 | 4527 | nudge | R25 | rejected | held-out CE did not improve (-0.00008 nats) |
| P548 | 4527 | rule | corner-1-2-throw-in-into-two-point-eye | rejected | held-out CE gain +0.00358 nats (90% CI +0.00000 .. +0.00816) is not enough |
| P549 | 4527 | rule | corner-1-1-seal-own-two-point-eye | rejected | held-out CE gain +0.00019 nats (90% CI -0.00002 .. +0.00058) is not enough |
| P550 | 4527 | rule | slow-fill-of-touched-diagonal-link | accepted | held-out CE gain +0.00036 nats (90% CI +0.00005 .. +0.00077), guards and regression set pass |
