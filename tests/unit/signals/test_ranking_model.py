from hit_astocker.signals.ranking_model import RankingModel


def test_ranking_model_requires_quality_metadata(tmp_path):
    path = tmp_path / "ranking_model.pkl"

    model = RankingModel()
    model._model = {"kind": "dummy"}
    model._scaler = {"kind": "dummy"}
    model.save(path)

    loaded = RankingModel()
    assert loaded.load(path)
    assert loaded.metrics is None
    assert not loaded.is_usable()


def test_ranking_model_uses_saved_metrics_for_gating(tmp_path):
    path = tmp_path / "ranking_model.pkl"
    metrics = {"auc_mean": 0.61, "accuracy_mean": 0.57}

    model = RankingModel()
    model._model = {"kind": "dummy"}
    model._scaler = {"kind": "dummy"}
    model.save(path, metrics)

    loaded = RankingModel()
    assert loaded.load(path)
    assert loaded.metrics == metrics
    assert loaded.is_usable(0.55)
    assert not loaded.is_usable(0.65)
