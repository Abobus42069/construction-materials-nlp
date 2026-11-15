import json
import os
from pathlib import Path
import uuid
from collections import Counter
from .contracts import validate_input,validate_annotation,stable_id,MODEL_VERSION,CONTEXT_TYPES
from .rules import extract


def read_records(path):
    with Path(path).open(encoding='utf-8-sig') as stream:
        for index,line in enumerate(stream,1):
            if not line.strip(): continue
            try:
                record=json.loads(line);validate_input(record)
            except (ValueError,TypeError,KeyError) as exc: raise ValueError(f'Input line {index}: {exc}') from exc
            yield record


def process(source,destination):
    source,destination=Path(source),Path(destination)
    if source.resolve()==destination.resolve(): raise ValueError('Input and output paths must differ')
    destination.parent.mkdir(parents=True,exist_ok=True)
    temp=destination.with_name(destination.name+'.'+uuid.uuid4().hex+'.tmp')
    seen,annotation_ids={},set();counts,issues=Counter(),[]
    context_path=destination.with_name(destination.stem+'.contexts.jsonl')
    context_temp=temp.with_name(temp.name+'.contexts')
    report_path=destination.with_name(destination.stem+'.report.json')
    if source.resolve() in [context_path.resolve(),report_path.resolve()]:
        raise ValueError('Input collides with a generated sidecar path')
    try:
        with temp.open('w',encoding='utf-8') as output,context_temp.open('w',encoding='utf-8') as contexts:
            for record in read_records(source):
                fingerprint=stable_id(record)
                if record['id'] in seen:
                    if seen[record['id']]!=fingerprint: raise ValueError('Conflicting duplicate input ID: '+record['id'])
                    counts['duplicate_inputs']+=1;continue
                seen[record['id']]=fingerprint;counts['input_records']+=1
                if record['record_type'] in CONTEXT_TYPES:
                    contexts.write(json.dumps(record,ensure_ascii=False,allow_nan=False)+'\n');counts['context_records']+=1
                    if 'ocr_required' in record.get('quality_issues',[]): issues.append({'record_id':record['id'],'issue':'ocr_required'})
                    continue
                annotations=extract(record)
                if not annotations: counts['records_without_annotations']+=1
                for item in annotations:
                    validate_annotation(item,record)
                    if item['annotation_id'] in annotation_ids: continue
                    annotation_ids.add(item['annotation_id'])
                    output.write(json.dumps(item,ensure_ascii=False,allow_nan=False)+'\n')
                    counts['annotations']+=1;counts['predicate:'+item['predicate']]+=1
        os.replace(context_temp,context_path);os.replace(temp,destination)
    finally:
        for path in [temp,context_temp]:
            if path.exists(): path.unlink()
    report={'model_version':MODEL_VERSION,'input':str(source),'output':str(destination),'contexts':str(context_path),
        'counts':dict(counts),'issues':issues,'review_status':'candidate',
        'limitations':['rule_baseline_not_a_trained_model','normative_applicability_not_assessed','cross_chunk_relations_not_resolved']}
    report_path=destination.with_name(destination.stem+'.report.json');tmp=report_path.with_name(report_path.name+'.tmp')
    tmp.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');os.replace(tmp,report_path)
    return report
