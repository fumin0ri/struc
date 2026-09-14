"""Replay frozen annotations, run ablations, then score predeclared pairs."""
import sys
from pathlib import Path
from collections import Counter, defaultdict
from time import perf_counter
from datetime import datetime, timezone
import hashlib
import platform

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.pipeline import read_json, write_json, digest, mine, require, validate_corpus, collect_vocabulary, validate_normalized_bundle


def resolve(ref, index):
    did, names = ref.split('/')
    ids = sorted(index[did][name] for name in names.split(','))
    return did + ':' + ','.join(ids)


def lookup(result):
    return {o['key']: p['pattern_id'] for p in result['patterns'] for o in p['occurrences']}


def pair_match(a, b, table):
    return None if a not in table or b not in table else table[a] == table[b]


def score(result, evaluation, index):
    table = lookup(result)
    counts = Counter({'tp': 0, 'fp': 0, 'tn': 0, 'fn': 0, 'abstained': 0})
    details = []
    for pair in evaluation['pairs']:
        a, b = resolve(pair['a'], index), resolve(pair['b'], index)
        got = pair_match(a, b, table)
        counts['abstained' if got is None else ('tp' if pair['expected'] else 'fp') if got else ('fn' if pair['expected'] else 'tn')] += 1
        details.append({**pair, 'a_key': a, 'b_key': b, 'actual': got,
                        'status': 'abstained' if got is None else 'correct' if got == pair['expected'] else 'incorrect'})
    # End-to-end recall counts abstained positives as unrecovered, but not as forced mismatches.
    positives = sum(p['expected'] for p in evaluation['pairs'])
    risks = [{**p, 'actual': pair_match(resolve(p['a'], index), resolve(p['b'], index), table)}
             for p in evaluation['risk_probes']]
    semantic_counts = counts.copy()
    for probe in risks:
        if 'semantic_match_target' not in probe:
            continue
        got, expected = probe['actual'], probe['semantic_match_target']
        semantic_counts['abstained' if got is None else ('tp' if expected else 'fp') if got else ('fn' if expected else 'tn')] += 1
    return {'counts': dict(counts), 'pair_count': len(details),
            'precision_on_predicted_matches': counts['tp'] / (counts['tp'] + counts['fp']) if counts['tp'] + counts['fp'] else None,
            'positive_pair_recovery': counts['tp'] / positives if positives else None,
            'including_semantic_diagnostics': {'counts': dict(semantic_counts), 'pair_count': sum(semantic_counts.values()),
                'note': 'The 43 controlled pairs plus OTHER and NOT/polarity probes; same-author semantic expectations, not independent ground truth.'},
            'details': details, 'risk_probes': risks}


def main():
    sources = read_json(ROOT / 'data/corpus.json')
    raw = read_json(ROOT / 'data/graphs.raw.json')
    vocabulary = collect_vocabulary(raw, sources)
    require(digest(vocabulary) == digest(read_json(ROOT / 'data/vocabulary.json')), 'stale vocabulary; rerun build_fixture')
    index = read_json(ROOT / 'data/annotation_index.json')
    results, timing = {}, {}
    for name, profile, version in [('surface', 'surface', None), ('strict_v1', 'strict', 1), ('strict_v2', 'strict', 2),
                                   ('no_concepts', 'no_concepts', 2), ('no_conditions', 'no_conditions', 2),
                                   ('no_polarity', 'no_polarity', 2), ('no_units', 'no_units', 2)]:
        if version:
            dictionary = read_json(ROOT / f'data/dictionary.v{version}.json')
            bundle = read_json(ROOT / f'data/graphs.normalized.v{version}.json')
            require(bundle['dictionary_sha256'] == digest(dictionary) and bundle['dictionary_version'] == dictionary['version'], 'mixed dictionary')
            require(bundle['raw_graphs_sha256'] == digest(raw), 'stale normalized input')
            graphs = validate_normalized_bundle(bundle, sources, dictionary)
        else:
            dictionary, graphs = None, raw
        start = perf_counter()
        results[name] = mine(graphs, sources, dictionary=dictionary, profile=profile)
        timing[name] = perf_counter() - start
        write_json(ROOT / f'results/{name}.json', results[name])
    # Evaluation expectations are deliberately loaded only after every mining run.
    evaluation = read_json(ROOT / 'data/evaluation_pairs.json')
    scored = {name: score(result, evaluation, index) for name, result in results.items()}
    write_json(ROOT / 'results/evaluation.json', scored)
    usage = {}
    for version in (1, 2):
        assignments = read_json(ROOT / f'data/assignments.v{version}.json')['assignments']
        dictionary = read_json(ROOT / f'data/dictionary.v{version}.json')
        counts = Counter(a['concept_id'] for a in assignments)
        by_split = defaultdict(Counter)
        splits = {s['document_id']: s['split'] for s in sources}
        by_type = defaultdict(Counter)
        row_types = {(r['document_id'], r['node_id']): r['node_type'] for r in vocabulary['rows']}
        for a in assignments:
            by_split[splits[a['document_id']]]['nodes'] += 1
            by_split[splits[a['document_id']]]['nulls'] += a['concept_id'] is None
            by_type[row_types[a['document_id'], a['node_id']]][a['concept_id']] += 1
        concepts = [{**c, 'node_count': counts[c['id']],
                     'document_count': len({a['document_id'] for a in assignments if a['concept_id'] == c['id']})}
                    for c in dictionary['concepts']]
        usage[f'v{version}'] = {
            'nodes': len(assignments), 'null_nodes': counts[None], 'null_rate': counts[None] / len(assignments),
            'concept_count': len(concepts), 'singleton_concepts': [c['id'] for c in concepts if c['node_count'] == 1],
            'unused_concepts': [c['id'] for c in concepts if c['node_count'] == 0],
            'split_counts': dict(by_split),
            'type_concentration': {t: {'nodes': sum(cs.values()), 'largest_concept_share': max(cs.values()) / sum(cs.values())}
                                   for t, cs in by_type.items()}, 'concepts': concepts}
    write_json(ROOT / 'results/concept_usage.json', usage)
    raw_rows = vocabulary['rows']
    write_json(ROOT / 'results/validation.json', {
        'documents_passed': len(raw), 'documents_failed': 0,
        'nodes': sum(len(g['nodes']) for g in raw), 'relations': sum(len(g['relations']) for g in raw),
        'claim_nodes': sum(n['type'] == 'CLAIM' for g in raw for n in g['nodes']),
        'documents_without_claim': vocabulary['documents_without_claim'],
        'unique_collected_nodes': len(raw_rows),
        'claim_memberships_before_deduplication': sum(r['claim_membership_count'] for r in raw_rows),
        'semantic_fidelity_checked_by': 'same author; not independently verified'})
    # Enumerate every newly recurring pattern, not just favorable examples.
    old = lookup(results['surface'])
    new_groups = []
    for p in results['strict_v2']['patterns']:
        if p['support_count'] < 2:
            continue
        old_groups = sorted({old[o['key']] for o in p['occurrences']})
        new_groups.append({'pattern_id': p['pattern_id'], 'claim_count': p['claim_count'],
                           'documents': p['supporting_documents'], 'support_count': p['support_count'],
                           'occurrence_count': p['occurrence_count'], 'surface_group_count': len(old_groups),
                           'merged_surface_groups': old_groups})
    write_json(ROOT / 'results/normalization_effect.json', new_groups)
    files = list((ROOT / 'data').glob('*.json')) + list((ROOT / 'prompts').glob('*.txt'))
    files += list((ROOT / 'src').glob('*.py')) + list((ROOT / 'scripts').glob('*.py')) + list((ROOT / 'tests').glob('*.py'))
    write_json(ROOT / 'results/run_manifest.json', {
        'run_utc': datetime.now(timezone.utc).isoformat(), 'python_version': platform.python_version(),
        'platform': platform.system(), 'timings_seconds': timing,
        'timing_scope': 'Single local run; validation+mining only; excludes file IO, annotation, prompts, model latency.',
        'llm_provenance': {'executor': 'current Codex assistant', 'api_calls': 0, 'independent_extraction_runs': 0,
                           'method': 'assistant-authored synthetic texts, graph annotations, dictionary and assignments; helpers serialize the saved choices',
                           'blind_holdout': False, 'raw_provider_responses': None, 'model_version_and_sampling_parameters': 'not captured; no provider API experiment'},
        'file_sha256': {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)},
    })
    print('profile           accepted/total  recurring  TP FP TN FN abstained')
    for name, r in results.items():
        s, c = r['stats'], scored[name]['counts']
        print(f'{name:17s} {s["fragments_accepted"]:2}/{s["fragments_total"]:<3} {s["recurring_patterns"]:10} '
              f'{c["tp"]:3} {c["fp"]:2} {c["tn"]:2} {c["fn"]:2} {c["abstained"]:9}')


if __name__ == '__main__':
    main()
