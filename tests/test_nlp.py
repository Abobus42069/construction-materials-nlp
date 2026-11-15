import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from materials_nlp.rules import extract
from materials_nlp.contracts import validate_annotation
from materials_nlp.pipeline import process
from materials_nlp.evaluation import evaluate


def record(text,**changes):
    value={'schema_version':'2.0','record_type':'catalogue_chunk','id':'example','material_id':'material1',
        'text':text,'start_char':50,'end_char':50+len(text),
        'evidence':{'source_url':'https://example.org/product','content_sha256':'synthetic-hash',
                    'locator':'/html/body/main','page':None,'quote':text}}
    value.update(changes);return value


class ExtractionTests(unittest.TestCase):
    def test_contexts_units_unicode_minus_and_offsets(self):
        for text,predicate,low,high in [
            ('Температура применения от минус 18 °С до плюс 35 °С.','application_temperature',-18,35),
            ('Температура эксплуатации от −40 до +80 °C.','service_temperature',-40,80),
            ('Хранить при температуре от +5°С до +25°С.','storage_temperature',5,25),
            ('Транспортируют при температуре от — 10 °С до +40 °С.','transport_temperature',-10,40),
            ('Температура баллона от +18 °С до +25 °С.','container_temperature',18,25)]:
            with self.subTest(text=text):
                source=record(text);items=extract(source)
                self.assertEqual(len(items),1);self.assertEqual(items[0]['predicate'],predicate)
                self.assertEqual(items[0]['normalized_value']['min'],low);self.assertEqual(items[0]['normalized_value']['max'],high)
                self.assertEqual(items[0]['evidence'][0]['source_start_char'],50);validate_annotation(items[0],source)

    def test_distinct_sentences_and_inherited_headings(self):
        items=extract(record('Производство работ:\nТемпература от -10 до +30 °C. Температура баллона от +18 до +25 °C.\nХранение:\nТемпература от +5 до +25 °C.'))
        self.assertEqual([x['predicate'] for x in items],['application_temperature','container_temperature','storage_temperature'])

    def test_ambiguous_transport_storage_abstains(self):
        item=extract(record('Хранить и перевозить при температуре от +5 до +25 °C.'))[0]
        self.assertEqual(item['predicate'],'temperature_unspecified');self.assertIn('multiple_temperature_contexts',item['quality_issues'])

    def test_negation_and_no_implicit_permission(self):
        a=extract(record('Не применять на полиэтилене.'))[0]
        b=extract(record('Не рекомендуется применять на влажном основании.'))[0]
        self.assertEqual(a['polarity'],'prohibited');self.assertEqual(b['polarity'],'not_recommended')
        self.assertEqual(extract(record('Материал белого цвета.')),[])

    def test_temperature_prohibition_and_storage_restriction(self):
        items=extract(record('Не применять при температуре от -10 до +5 °C.'))
        self.assertTrue(all(x['polarity']=='prohibited' for x in items))
        storage=extract(record('Запрещается хранение под солнцем.'))
        self.assertEqual(storage[0]['predicate'],'storage_restriction')
        self.assertEqual(storage[0]['polarity'],'prohibited')

    def test_negative_intended_use_and_double_negation(self):
        items=extract(record('Не предназначен для наружных работ.'))
        self.assertFalse(any(x['predicate']=='intended_use' for x in items))
        self.assertEqual(items[0]['polarity'],'not_intended')
        self.assertEqual(extract(record('Применение не запрещено.')),[])

    def test_normative_permission_and_negative_requirement(self):
        for text,polarity in [('1.2 Допускается применение материала.','permitted'),
                              ('1.2 Материал не должен применяться.','prohibited')]:
            item=extract(record(text,record_type='document_chunk',document_id='norm',document_kind='normative_document'))[0]
            self.assertEqual(item['polarity'],polarity)

    def test_exceptions_are_preserved(self):
        item=extract(record('Хорошая адгезия к основаниям, за исключением полиэтилена и силикона.'))[0]
        self.assertEqual(item['predicate'],'compatibility_statement');self.assertIn('полиэтилена',item['exceptions'][0])
        self.assertEqual(item['polarity'],'conditional')

    def test_normative_subject_not_transferred_to_product(self):
        source=record('1.2 Не допускается применение, кроме указанных исключений.',record_type='document_chunk',document_id='norm1',document_kind='normative_document')
        item=extract(source)[0]
        self.assertEqual(item['predicate'],'normative_statement');self.assertEqual(item['subject_id'],'norm1')
        self.assertEqual(item['subject_type'],'document');self.assertEqual(item['clause'],'1.2')
        self.assertIn('edition_and_applicability_not_verified',item['quality_issues']);self.assertIsNone(item['confidence'])

    def test_scalar_property_and_complex_values(self):
        source=record('test',record_type='property',raw_value='0,5',name='Адгезия',unit='МПа',property_key='adhesion',raw_comparator='не менее',test_method_raw='synthetic method')
        item=extract(source)[0]
        self.assertEqual(item['normalized_value'],0.5);self.assertEqual(item['unit'],'MPa');self.assertEqual(item['operator'],'>=')
        self.assertEqual(item['test_method_raw'],'synthetic method')
        source['unit']='unknown';source['raw_value']='от 1 до 2';item=extract(source)[0]
        self.assertIsNone(item['normalized_value']);self.assertIn('unit_not_normalized',item['quality_issues'])

    def test_tampered_evidence_rejected(self):
        source=record('Не применять на пластике.');item=extract(source)[0];item['evidence'][0]['quote']='altered'
        with self.assertRaises(ValueError):validate_annotation(item,source)

    def test_comparison_and_stable_ids(self):
        source=record('Температура применения не ниже -10 °C.');a=extract(source)[0]
        self.assertEqual(a['operator'],'>=');self.assertEqual(a['normalized_value'],-10)
        self.assertEqual(a['annotation_id'],extract(copy.deepcopy(source))[0]['annotation_id'])


class PipelineTests(unittest.TestCase):
    def test_invalid_input_keeps_existing_output(self):
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'input.jsonl';out=Path(directory)/'out.jsonl';out.write_text('original',encoding='utf-8')
            source.write_text(json.dumps(record('Не применять.'))+'\n{"bad":true}',encoding='utf-8')
            with self.assertRaises(ValueError):process(source,out)
            self.assertEqual(out.read_text(encoding='utf-8'),'original')

    def test_duplicates_contexts_ocr_and_cli(self):
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'input.jsonl';out=Path(directory)/'out.jsonl';r=record('Предназначен для заполнения швов.')
            context={'schema_version':'2.0','record_type':'document_metadata','id':'scan','quality_issues':['ocr_required']}
            source.write_text('\n'.join(json.dumps(x,ensure_ascii=False) for x in [r,r,context]),encoding='utf-8')
            report=process(source,out)
            self.assertEqual(report['counts']['annotations'],1);self.assertEqual(report['counts']['duplicate_inputs'],1)
            self.assertEqual(report['issues'][0]['issue'],'ocr_required')
            result=subprocess.run([sys.executable,'-B','-m','materials_nlp','extract',str(source),'--out',str(out)],capture_output=True)
            self.assertEqual(result.returncode,0,result.stderr)

    def test_conflicting_ids_and_same_path_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'in.jsonl';source.write_text('\n'.join(json.dumps(record(s)) for s in ['Первый текст.','Другой текст.']),encoding='utf-8')
            with self.assertRaises(ValueError):process(source,Path(directory)/'out.jsonl')
            with self.assertRaises(ValueError):process(source,source)

    def test_smoke_dataset(self):
        self.assertEqual(evaluate(Path(__file__).resolve().parents[1]/'data/smoke_gold.jsonl')['failures'],[])


if __name__=='__main__':unittest.main()
