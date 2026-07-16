# Wrapper scripts for external solvers

Place thin shims here that speak the platform wire contract:

- **stdin:** JSON task from `SolverTask.to_wire()` (no ground truth)
- **stdout:** `{"prediction": grid}` or `{"attempts": [grid, ...]}`
  (or any text the grid parser can scan)

Start from `examples/external_solver/cli_wrapper_template.py`.
Register the command in `configs/solvers.json` (`subprocess_cli`).

See `docs/SOLVER_ADAPTERS.md` and `docs/QUICKSTART_EXTERNAL_SOLVER.md`.
