"""Official native convention is explicit; the strict historical gate remains."""
import ast
import inspect
import run_fundy_native as native
import run_additional_real as strict

def test_native_policy_never_claims_geographic_validation():
    assert native.POLICY['physical_direction_unverified'] is True
    assert native.POLICY['geographic_direction_validated'] is False
    assert native.POLICY['original_strict_gate_passed'] is False

def test_native_checks_differ_only_in_geography_acceptance():
    # Keep every native value/rotation/UTC assertion: only the authorized
    # geographic consistency check becomes a finite diagnostic.
    old=inspect.getsource(strict.native_controls)
    expected=old.replace("require(angle_error<2.,'ROMS angle does not follow physical xi direction')",
                         "require(np.isfinite(angle_error),'nonfinite ROMS orientation diagnostic')")
    assert ast.dump(ast.parse(expected))==ast.dump(ast.parse(inspect.getsource(native.native_controls)))
    assert "angle_error<2." in old
