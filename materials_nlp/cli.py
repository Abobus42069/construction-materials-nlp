import argparse
import json
from pathlib import Path
from .pipeline import process
from .evaluation import evaluate


def main(argv=None):
    parser=argparse.ArgumentParser(description='Russian materials NLP: evidence-backed rule baseline')
    commands=parser.add_subparsers(dest='command',required=True)
    p=commands.add_parser('extract');p.add_argument('input',type=Path);p.add_argument('--out',type=Path,required=True)
    p=commands.add_parser('evaluate');p.add_argument('dataset',type=Path);p.add_argument('--out',type=Path)
    args=parser.parse_args(argv)
    try:
        result=process(args.input,args.out) if args.command=='extract' else evaluate(args.dataset)
        if args.command=='evaluate' and args.out:
            args.out.parent.mkdir(parents=True,exist_ok=True)
            args.out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    except (ValueError,OSError,KeyError,TypeError) as exc: parser.exit(2,str(exc)+'\n')
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0
