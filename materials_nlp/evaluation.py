import json
from pathlib import Path
from .rules import extract


def key(item):
    return json.dumps({k:item.get(k) for k in ['predicate','normalized_value','unit','operator','polarity']},sort_keys=True,ensure_ascii=False)


def evaluate(path):
    tp=fp=fn=examples=0;failures=[]
    for line in Path(path).read_text(encoding='utf-8').splitlines():
        if not line.strip(): continue
        case=json.loads(line);expected={key(x) for x in case['expected']};predicted={key(x) for x in extract(case['record'])}
        examples+=1;tp+=len(expected&predicted);fp+=len(predicted-expected);fn+=len(expected-predicted)
        if expected!=predicted:
            failures.append({'id':case['record']['id'],'missing':[json.loads(x) for x in sorted(expected-predicted)],'extra':[json.loads(x) for x in sorted(predicted-expected)]})
    if not examples: raise ValueError('Evaluation dataset is empty')
    return {'examples':examples,'true_positive':tp,'false_positive':fp,'false_negative':fn,
        'precision':tp/(tp+fp) if tp+fp else None,'recall':tp/(tp+fn) if tp+fn else None,
        'f1':2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else None,'failures':failures,
        'metric':'exact predicate/value/unit/operator/polarity sets per example',
        'note':'Synthetic development cases do not measure real-corpus generalization'}
