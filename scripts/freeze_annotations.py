"""Materialize saved assistant choices; no model invocation or automatic classifier."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.pipeline import read_json, write_json, digest, validate_dictionary, normalize, require

ROOT = Path(__file__).resolve().parents[1]


def run():
    graphs = read_json(ROOT / 'data/graphs.raw.json')
    sources = read_json(ROOT / 'data/corpus.json')
    vocabulary = read_json(ROOT / 'data/vocabulary.json')
    idx = read_json(ROOT / 'data/annotation_index.json')
    dictionary = read_json(ROOT / 'data/dictionary.v1.json')
    validate_dictionary(dictionary)
    decisions = read_json(ROOT / 'data/classification_decisions.v1.json')
    assignments = []
    for group in decisions['groups']:
        for ref in group['refs'].split():
            did, name = ref.split('/')
            assignments.append({'document_id': did, 'node_id': idx[did][name],
                                'concept_id': group['concept_id'], 'rationale': group['rationale']})
    assignments.sort(key=lambda a: (a['document_id'], a['node_id']))
    selected = {'dictionary_version': dictionary['version'], 'dictionary_sha256': digest(dictionary),
                'vocabulary_sha256': digest(vocabulary), 'assignments': assignments}
    normalized = normalize(graphs, sources, vocabulary, dictionary, selected)
    write_json(ROOT / 'data/assignments.v1.json', selected)
    write_json(ROOT / 'data/graphs.normalized.v1.json', normalized)
    nulls = [a for a in assignments if a['concept_id'] is None]
    write_json(ROOT / 'results/unassigned.v1.json', {
        'dictionary_version': dictionary['version'], 'nodes': [
            {'assignment': a, 'context': next(r for r in vocabulary['rows'] if
              (r['document_id'], r['node_id']) == (a['document_id'], a['node_id']))} for a in nulls]})
    # Deliberate revision after reviewing both OOV contexts. Existing IDs/definitions unchanged.
    dictionary2 = read_json(ROOT / 'data/dictionary.v1.json')
    dictionary2['version'] = 'shared-1.1'
    dictionary2['concepts'].append({
        'id': 'A007', 'node_type': 'ACTION', 'name': '校正',
        'definition': '測定器の示す値と標準との対応関係を確かめて定める操作。',
        'examples': ['測定器を校正する', 'センサーの値と標準値との対応を定める'],
        'distinctions': '対象の数値を取得するA003、差異だけを求めるA004、適合判定A001と区別する。測定器を物理的に調整する操作を必須としない。'})
    validate_dictionary(dictionary2)
    # Full-corpus reclassification is replayed explicitly, including retained decisions.
    reselected = read_json(ROOT / 'data/assignments.v1.json')
    reselected['dictionary_version'] = dictionary2['version']
    reselected['dictionary_sha256'] = digest(dictionary2)
    for a in reselected['assignments']:
        if a['concept_id'] is None:
            require(a['document_id'] in {'D43', 'D44'}, 'unexpected new OOV; do not auto-assign')
            a['concept_id'] = 'A007'
            a['rationale'] = '固定した改訂辞書の校正に適合。標準と測定器の対応関係を定める。'
    write_json(ROOT / 'data/dictionary.v2.json', dictionary2)
    write_json(ROOT / 'data/assignments.v2.json', reselected)
    write_json(ROOT / 'data/graphs.normalized.v2.json', normalize(graphs, sources, vocabulary, dictionary2, reselected))
    write_json(ROOT / 'results/revision.json', {
        'from_version': dictionary['version'], 'to_version': dictionary2['version'],
        'reason': 'D43/D44の未登録操作を一つの校正概念として追加。頻度合わせで測定に統合しない。',
        'added_ids': ['A007'], 'changed_existing_definitions': [],
        'rechecked_nodes': len(assignments), 'changed_assignments': len(nulls),
        'method': 'assistant-authored revision choices, replayed by code; no independent LLM run'})
    print(f'{len(assignments)} assignments; v1 null={len(nulls)}; v2 new concept=A007')


if __name__ == '__main__':
    run()
