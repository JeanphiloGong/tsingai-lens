import ast
from pathlib import Path


def test_worker_scripts_do_not_import_web_or_runtime():
    root=Path(__file__).resolve().parents[3]/"scripts"
    names=["feedback_analysis_worker", "correction_signal_analysis_worker", "tool_failure_analysis_worker", "dataset_sample_worker"]
    for name in names:
        source=(root/(name+".py")).read_text()
        tree=ast.parse(source)
        assert not any(isinstance(node,ast.ImportFrom) and node.module=="main" for node in ast.walk(tree)), name
        assert "build_application_runtime" not in source
