"""Preemption-tolerant KataGo analysis service (stdlib only).

backend   runs inside a Slurm GPU job: one KataGo analysis process shared by many
          authenticated TCP clients on 127.0.0.1, query ids namespaced per connection.
client    drop-in `KATAGO_BIN` for goarena (`bin/kg-client`): speaks KataGo's JSON lines
          on stdio and fails over between backends, resending only unfinished work.
keepalive keeps a backend for a model alive across the 1 h job limit and preemption.

Backends announce themselves through rendezvous files in engines/run/backends/ (mode 600).
"""
