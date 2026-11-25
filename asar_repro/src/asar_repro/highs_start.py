"""Opt-in adapter to SciPy's bundled HiGHS for a complete primal MIP start.

This private SciPy API is isolated here and fails closed if unavailable. No
dependency installation, silent cold fallback, or change to model coefficients.
"""
from time import perf_counter

import numpy as np
from scipy.optimize import OptimizeResult


def milp_with_start(c, *, integrality, bounds, constraints, options, start, stats):
    from scipy.optimize._highspy import _core as h

    begun = perf_counter()
    solver = h._Highs()
    stats['native_backend'] = 'scipy.optimize._highspy._core (private, opt-in)'
    stats['native_highs_version'] = solver.version()

    def accepted(status, operation):
        if status != h.HighsStatus.kOk:
            raise RuntimeError(f'HiGHS {operation} not accepted: {status}')

    accepted(solver.setOptionValue('output_flag', bool(options.get('disp', False))), 'output_flag')
    for key, value in options.items():
        if key == 'disp':
            continue
        if key == 'presolve':
            value = 'on' if value else 'off'
        if key == 'node_limit':
            key = 'mip_max_nodes'
        accepted(solver.setOptionValue(key, value), 'option '+key)

    A = constraints.A.tocsc()
    lp = h.HighsLp()
    lp.num_col_, lp.num_row_ = A.shape[1], A.shape[0]
    lp.col_cost_ = c
    lp.col_lower_, lp.col_upper_ = bounds.lb, bounds.ub
    lp.row_lower_, lp.row_upper_ = constraints.lb, constraints.ub
    lp.a_matrix_.num_col_, lp.a_matrix_.num_row_ = A.shape[1], A.shape[0]
    lp.a_matrix_.format_ = h.MatrixFormat.kColwise
    lp.a_matrix_.start_ = A.indptr
    lp.a_matrix_.index_ = A.indices
    lp.a_matrix_.value_ = A.data
    lp.integrality_ = [h.HighsVarType(int(i)) for i in integrality]
    accepted(solver.passModel(lp), 'passModel')
    seed = h.HighsSolution()
    seed.col_value = start
    seed.row_value = np.asarray(A @ start).ravel()
    seed.value_valid = True
    accepted(solver.setSolution(seed), 'setSolution')
    # Verify the native object contains the full vector, not just Python-side
    # bookkeeping of an external incumbent.
    echoed = solver.getSolution()
    if not echoed.value_valid or not np.array_equal(np.asarray(echoed.col_value), start):
        raise RuntimeError('native MIP start roundtrip mismatch')
    stats.update(mip_start_submitted=True, mip_start_roundtrip_verified=True,
                 mip_start_variables=len(start), mip_start_native_objective=float(c @ start))
    remaining = options['time_limit'] - (perf_counter()-begun)
    if remaining <= 0:
        return OptimizeResult(status=1, message='Time limit reached during native setup',
                              x=None, fun=None, mip_dual_bound=None, mip_node_count=0, mip_gap=None)
    accepted(solver.setOptionValue('time_limit', remaining), 'remaining time_limit')
    stats['native_remaining_seconds'] = remaining
    run_status = solver.run()
    model_status = solver.getModelStatus()
    info = solver.getInfo()
    stats.update(native_run_status=str(run_status), native_model_status=int(model_status),
                 native_primal_solution_status=int(info.primal_solution_status))
    if run_status == h.HighsStatus.kError:
        raise RuntimeError('native run failed: '+solver.modelStatusToString(model_status))
    limits = (h.HighsModelStatus.kTimeLimit, h.HighsModelStatus.kIterationLimit,
              h.HighsModelStatus.kSolutionLimit)
    status = 0 if model_status == h.HighsModelStatus.kOptimal else 1 if model_status in limits else 4
    message = f'HiGHS Status {int(model_status)}: {solver.modelStatusToString(model_status)}'
    solution = solver.getSolution()
    # Native SolutionStatus uses 2 for feasible, as reported by the native enum.
    feasible = info.valid and int(info.primal_solution_status) == 2 and solution.value_valid
    return OptimizeResult(status=status, message=message,
        x=np.asarray(solution.col_value, dtype=float) if feasible else None,
        fun=float(info.objective_function_value) if feasible else None,
        mip_node_count=int(info.mip_node_count),
        mip_dual_bound=float(info.mip_dual_bound) if info.valid and status in (0, 1) else None,
        mip_gap=float(info.mip_gap) if info.valid else None)
