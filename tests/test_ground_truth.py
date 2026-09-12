from pathlib import Path
from vitaguard_do.validation.ground_truth import validate_ground_truth_folder


def test_ground_truth_files_validate():
    root = Path(__file__).resolve().parents[1]
    files = validate_ground_truth_folder(root / "tests" / "ground_truth")
    assert len(files) == 2
