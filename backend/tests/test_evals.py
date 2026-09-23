from evals.run import run


def test_offline_evaluation_gates() -> None:
    assert run()["passed"] == 18
