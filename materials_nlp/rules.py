"""Russian linguistic baseline; candidate extraction, not compliance assessment."""
import re
from .contracts import annotation,source_text,validate_input

NUM=r'(?:[+\-−–—]\s*|минус\s+|плюс\s+)?\d+(?:[.,]\d+)?'
DEG=r'(?:°\s*[CС]|градус\w*\s+Цельсия)'
RANGE=re.compile(r'от\s+(?P<low>'+NUM+r')\s*(?:'+DEG+r')?\s+до\s+(?P<high>'+NUM+r')\s*'+DEG,re.I)
BOUND=re.compile(r'(?P<op>не\s+ниже|не\s+выше|не\s+менее|не\s+более|свыше|выше|ниже)\s+(?P<value>'+NUM+r')\s*'+DEG,re.I)
SEGMENT=re.compile(r'[^\n;]+')
SENTENCE=re.compile(r'(?<=[.!?])\s+(?=[А-ЯA-Z])')
NEG=re.compile(r'не\s+допускается|не\s+допускаются|не\s+применя\w*|не\s+долж\w*|запрещ\w*',re.I)
NOT_RECOMMENDED=re.compile(r'не\s+рекомендуется|не\s+рекомендуются',re.I)
INTENDED=re.compile(r'предназнач\w*\s+для|применяется\s+для|применяются\s+для|используется\s+для|используются\s+для',re.I)
REQUIREMENT=re.compile(r'\b(?:долж\w*|следует|необходимо|допускается|допускаются|запрещ\w*)\b|не\s+допускается',re.I)
HEADINGS={'хранение':'storage_temperature','транспортировка':'transport_temperature',
    'транспортирование':'transport_temperature','производство работ':'application_temperature',
    'условия эксплуатации':'service_temperature','условия применения':'application_temperature'}


def decimal_value(value):
    value=re.sub(r'\s+','',value.lower()).replace('минус','-').replace('плюс','+')
    for minus in ['−','–','—']: value=value.replace(minus,'-')
    return float(value.replace(',','.'))


def segments(text):
    for line in SEGMENT.finditer(text):
        position=0
        for boundary in SENTENCE.finditer(line.group()):
            yield line.start()+position,line.start()+boundary.start(),line.group()[position:boundary.start()]
            position=boundary.end()
        if position<len(line.group()): yield line.start()+position,line.end(),line.group()[position:]


def temperature_context(text,default=None):
    lower=text.lower();contexts=[]
    patterns=[('storage_temperature',r'хран'),('transport_temperature',r'перевоз|транспорт'),
        ('service_temperature',r'эксплуатац'),('application_temperature',r'нанесен|примен|\bмонтаж(?:а|е|у|ом)?\b'),
        ('curing_temperature',r'отвержден|тверден'),('substrate_temperature',r'температур\w*\s+основан'),
        ('container_temperature',r'температур\w*\s+баллон|нагреван\w*\s+баллон')]
    for name,pattern in patterns:
        if re.search(pattern,lower): contexts.append(name)
    if len(contexts)==1: return contexts[0],[]
    if len(contexts)>1: return 'temperature_unspecified',['multiple_temperature_contexts']
    return (default or 'temperature_unspecified'),([] if default else ['temperature_context_unknown'])


def is_prohibited(text):
    # Double negation is not a prohibition. Abstain on a mixed sentence.
    return bool(NEG.search(text)) and not bool(re.search(r'не\s+запрещ',text,re.I))


def qualifiers(text):
    exceptions=[m.group().strip() for m in re.finditer(r'(?:за исключением|кроме)\b[^;\n]*',text,re.I)]
    conditions=[m.group().strip() for m in re.finditer(r'(?:при условии|если|при температуре)\b[^;\n]*',text,re.I)]
    return conditions,exceptions


def extract(record):
    validate_input(record);kind=record['record_type']
    if kind not in ['catalogue_chunk','document_chunk','property','applicability_statement']: return []
    text=source_text(record)
    if kind=='property': return property_annotation(record,text)
    default={'storage':'storage_temperature','transport':'transport_temperature','installation':'application_temperature'}.get(record.get('aspect'))
    normative=record.get('document_kind')=='normative_document';results=[]
    for start,end,part in segments(text):
        stripped=part.strip().lower().rstrip(': .')
        if stripped in HEADINGS:
            default=HEADINGS[stripped];continue
        context,issues=temperature_context(part,default)
        conditions,exceptions=qualifiers(part)
        clause_match=re.match(r'\s*(\d+(?:\.\d+)+)\s',part)
        clause=clause_match.group(1) if clause_match else None
        inherited=list(issues)
        if kind=='document_chunk': inherited.append('cross_line_and_chunk_context_not_resolved')
        temperature_polarity='prohibited' if is_prohibited(part) else 'not_recommended' if NOT_RECOMMENDED.search(part) else 'unknown'
        for match in RANGE.finditer(part):
            low,high=decimal_value(match['low']),decimal_value(match['high'])
            local_issues=inherited+(['reversed_range'] if low>high else [])
            results.append(annotation(record,context,start,end,{'min':low,'max':high,
                'min_inclusive':True,'max_inclusive':True},'degC','range',
                polarity=temperature_polarity,issues=local_issues,conditions=conditions,exceptions=exceptions,clause=clause))
        for match in BOUND.finditer(part):
            operator={'не ниже':'>=','не менее':'>=','не выше':'<=','не более':'<=',
                'свыше':'>','выше':'>','ниже':'<'}[re.sub(r'\s+',' ',match['op'].lower())]
            results.append(annotation(record,context,start,end,decimal_value(match['value']),'degC',operator,
                polarity=temperature_polarity,issues=inherited,conditions=conditions,exceptions=exceptions,clause=clause))
        prohibited=is_prohibited(part);discouraged=bool(NOT_RECOMMENDED.search(part))
        not_intended=bool(re.search(r'не\s+предназнач',part,re.I))
        if normative and REQUIREMENT.search(part):
            results.append(annotation(record,'normative_statement',start,end,
                polarity='prohibited' if prohibited else 'unknown' if re.search(r'не\s+запрещ',part,re.I) else 'permitted' if re.search(r'допускается|допускаются',part,re.I) else 'stated_requirement',
                issues=['edition_and_applicability_not_verified','statement_may_continue_on_next_line'],
                conditions=conditions,exceptions=exceptions,clause=clause))
        elif not normative:
            if prohibited or discouraged or not_intended:
                restriction={'storage_temperature':'storage_restriction','transport_temperature':'transport_restriction',
                    'service_temperature':'service_restriction','container_temperature':'container_restriction'}.get(context,'application_restriction')
                results.append(annotation(record,restriction,start,end,
                    polarity='prohibited' if prohibited else 'not_intended' if not_intended else 'not_recommended',conditions=conditions,exceptions=exceptions))
            if INTENDED.search(part) and not prohibited and not discouraged and not not_intended:
                results.append(annotation(record,'intended_use',start,end,polarity='stated_use',conditions=conditions,exceptions=exceptions))
            if exceptions and re.search(r'адгези|совместим',part,re.I):
                results.append(annotation(record,'compatibility_statement',start,end,polarity='conditional',exceptions=exceptions,conditions=conditions))
    return list({a['annotation_id']:a for a in results}.values())


UNITS={'мпа':'MPa','кпа':'kPa','па':'Pa','мм':'mm','см':'cm','м':'m','кг':'kg','л':'L',
       'мин':'min','с':'s','%':'%','°с':'degC','°c':'degC','кг/м³':'kg/m3','кг/м3':'kg/m3'}
OPERATORS={'не менее':'>=','не более':'<=','менее':'<','более':'>','≥':'>=','≤':'<='}


def property_annotation(record,text):
    raw=record.get('raw_value','');numeric=None
    if isinstance(raw,str) and re.fullmatch(r'[+\-]?\d+(?:[.,]\d+)?',raw.strip()): numeric=decimal_value(raw)
    label=record.get('name','');predicate=record.get('property_key') or 'unmapped_property'
    if 'температур' in label.lower(): predicate,_=temperature_context(label)
    raw_unit=record.get('unit');unit=UNITS.get((raw_unit or '').strip().lower())
    operator=record.get('comparator') or OPERATORS.get((record.get('raw_comparator') or '').lower())
    issues=[] if numeric is not None else ['complex_value_not_normalized']
    if raw_unit and unit is None: issues.append('unit_not_normalized')
    result=annotation(record,predicate,0,len(text),numeric,unit,operator,issues=issues)
    result.update(property_name=label,original_value=raw,original_unit=raw_unit,
                  test_method_raw=record.get('test_method_raw'),conditions_raw=record.get('conditions_raw'))
    return [result]
