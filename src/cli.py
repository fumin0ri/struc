"""Operate on saved JSON. LLM stages are external; see prompts/ and README."""
import argparse
from pathlib import Path
from .pipeline import (read_json, write_json, validate_corpus, collect_vocabulary,
                       normalize, mine, PROFILES, validate_normalized_bundle)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    for command in ('validate', 'collect', 'normalize', 'mine'):
        p = sub.add_parser(command)
        p.add_argument('graphs', type=Path)
        p.add_argument('--corpus', required=True, type=Path)
        if command != 'validate':
            p.add_argument('--output', required=True, type=Path)
        if command in {'normalize', 'mine'}:
            p.add_argument('--dictionary', type=Path, required=command == 'normalize')
        if command == 'normalize':
            p.add_argument('--vocabulary', required=True, type=Path)
            p.add_argument('--assignments', required=True, type=Path)
        if command == 'mine':
            p.add_argument('--profile', choices=sorted(PROFILES), default='strict')
            p.add_argument('--max-claims', type=int, choices=(1, 2), default=2)
            p.add_argument('--min-support', type=int, default=2)
    args = parser.parse_args()
    graphs, sources = read_json(args.graphs), read_json(args.corpus)
    if args.command == 'validate':
        validate_corpus(graphs, sources)
        print(f'{len(graphs)} raw documents valid')
        return
    if args.command == 'collect':
        result = collect_vocabulary(graphs, sources)
    elif args.command == 'normalize':
        result = normalize(graphs, sources, read_json(args.vocabulary), read_json(args.dictionary), read_json(args.assignments))
    else:
        dictionary = read_json(args.dictionary) if args.dictionary else None
        if dictionary:
            graphs = validate_normalized_bundle(graphs, sources, dictionary)
        result = mine(graphs, sources, dictionary, args.profile, args.max_claims, args.min_support)
    write_json(args.output, result)
    print(f'wrote {args.output}')


if __name__ == '__main__':
    main()
