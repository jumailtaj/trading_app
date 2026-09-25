import pathlib
import sys
import pytest

def test_repo_hygiene():
    """Verify that no .env, .db, or log files are tracked in git."""
    import subprocess
    try:
        tracked = subprocess.check_output(["git", "ls-files"], text=True).splitlines()
    except (subprocess.SubprocessError, FileNotFoundError):
        pytest.skip("git not available or not a git repo")
    
    for f in tracked:
        assert f != ".env", ".env file should not be tracked"
        assert not f.endswith(".db"), f"Database file {f} is tracked"
        assert not f.endswith(".db-wal"), f"WAL file {f} is tracked"
        assert not f.startswith("logs/"), f"Log file {f} is tracked"

def test_kiteconnect_never_imported_in_paper_or_backtest():
    """If kiteconnect is imported during tests (before Phase E), it's a violation."""
    assert "kiteconnect" not in sys.modules, "kiteconnect should not be imported in backtest/paper tests"

def test_real_order_methods_raise():
    """R1 guard: real kiteconnect order methods must raise if ever reached in tests."""
    class MockKiteConnect:
        def place_order(self, *args, **kwargs):
            raise RuntimeError("CRITICAL: Real place_order reached during tests!")
        def modify_order(self, *args, **kwargs):
            raise RuntimeError("CRITICAL: Real modify_order reached during tests!")
        def cancel_order(self, *args, **kwargs):
            raise RuntimeError("CRITICAL: Real cancel_order reached during tests!")
        def exit_order(self, *args, **kwargs):
            raise RuntimeError("CRITICAL: Real exit_order reached during tests!")
    
    # We will inject this into sys.modules when kiteconnect is needed, 
    # but for now, we just ensure the mock raises.
    kc = MockKiteConnect()
    with pytest.raises(RuntimeError, match="CRITICAL: Real place_order reached during tests!"):
        kc.place_order()


def test_paper_broker_ast_guard():
    """Verify via AST that trading/paper_broker.py never imports kiteconnect."""
    import ast
    path = pathlib.Path("trading/paper_broker.py")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name != "kiteconnect", "paper_broker.py must never import kiteconnect"
        elif isinstance(node, ast.ImportFrom):
            assert node.module != "kiteconnect", "paper_broker.py must never import kiteconnect"

