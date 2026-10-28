from causaltrace.ml import evaluate,features,generate_fixture
from benchmarks.evaluate import evaluate_ranking

def test_train_validate_test_are_distinct():
    rows,labels=generate_fixture(1001,n=20,fault_rate=0)
    assert features(rows).shape==(20,3)
    assert sum(labels)==0
    model,result=evaluate()
    assert model is not None
    assert result['samples']==200
    assert result['train_seed']!=result['test_seed']
    assert 0<=result['f1']<=1

def test_ranking_ablation_reproducible():
    first=evaluate_ranking();second=evaluate_ranking()
    assert first==second
    assert first['cases']==80
