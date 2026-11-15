import hashlib
import json

MODEL_VERSION='rules-ru-0.1.0'
INPUT_TYPES={'catalogue_chunk','document_chunk','property','applicability_statement'}
CONTEXT_TYPES={'material_metadata','document_metadata','material_document_link','regulatory_reference','normative_registry_card'}


def stable_id(*parts):
    return hashlib.sha256(json.dumps(parts,ensure_ascii=False,sort_keys=True,allow_nan=False).encode()).hexdigest()


def source_text(record):
    if record['record_type']=='property': return record.get('evidence',{}).get('quote','')
    return record.get('text',record.get('raw_text',''))


def validate_input(record):
    if not isinstance(record,dict): raise ValueError('Record must be an object')
    if record.get('schema_version')!='2.0': raise ValueError('Expected parser schema_version 2.0')
    if not isinstance(record.get('id'),str) or not record['id']: raise ValueError('Nonempty id required')
    kind=record.get('record_type')
    if kind not in INPUT_TYPES|CONTEXT_TYPES: raise ValueError('Unsupported record_type: '+str(kind))
    if kind in INPUT_TYPES:
        text=source_text(record)
        if not isinstance(text,str) or not text.strip(): raise ValueError('Source text required')
        origin=record.get('evidence',{})
        for field in ['source_url','content_sha256','locator']:
            if not isinstance(origin.get(field),str) or not origin[field]: raise ValueError('Missing evidence.'+field)
        subject_key='document_id' if kind=='document_chunk' else 'material_id'
        if not isinstance(record.get(subject_key),str) or not record[subject_key]: raise ValueError('Missing '+subject_key)
        if kind in ['catalogue_chunk','document_chunk']:
            start,end=record.get('start_char'),record.get('end_char')
            if type(start) is not int or type(end) is not int or start<0 or end-start!=len(text):
                raise ValueError('Chunk offsets disagree with text')


def annotation(record,predicate,start,end,normalized=None,unit=None,operator=None,
               polarity='unknown',issues=(),conditions=(),exceptions=(),clause=None):
    text=source_text(record)
    if not 0<=start<end<=len(text): raise ValueError('Invalid annotation span')
    quote=text[start:end];source=record['evidence']
    offset=record.get('start_char') if record['record_type'] in ['catalogue_chunk','document_chunk'] else None
    evidence_id=stable_id(record['id'],start,end,source['content_sha256'])
    origin={**source,'quote':quote,'input_record_id':record['id'],'evidence_id':evidence_id,
        'record_start_char':start,'record_end_char':end,
        'source_start_char':offset+start if offset is not None else None,
        'source_end_char':offset+end if offset is not None else None,'offset_unit':'unicode_code_points'}
    subject=record.get('document_id') if record['record_type']=='document_chunk' else record.get('material_id')
    return {'schema_version':'1.0','record_type':'annotation',
        'annotation_id':stable_id(MODEL_VERSION,record['id'],predicate,start,end,normalized,polarity),
        'subject_id':subject,'subject_type':'document' if record['record_type']=='document_chunk' else 'material',
        'source_record_id':record['id'],'predicate':predicate,'raw_value':quote,'normalized_value':normalized,
        'unit':unit,'operator':operator,'polarity':polarity,'conditions':list(conditions),
        'exceptions':list(exceptions),'clause':clause,'evidence_ids':[evidence_id],'evidence':[origin],
        'model_version':MODEL_VERSION,'confidence':None,'review_status':'candidate',
        'quality_issues':list(issues),'source_quality_issues':record.get('quality_issues',[])}


def validate_annotation(value,record):
    if value.get('source_record_id')!=record['id'] or value.get('review_status')!='candidate':
        raise ValueError('Invalid provenance or status')
    text=source_text(record)
    for origin in value['evidence']:
        if text[origin['record_start_char']:origin['record_end_char']]!=origin['quote']:
            raise ValueError('Evidence does not match source')
        if origin['content_sha256']!=record['evidence']['content_sha256']: raise ValueError('Source hash changed')
