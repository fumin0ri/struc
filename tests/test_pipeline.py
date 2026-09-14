import unittest
from copy import deepcopy
from itertools import permutations
from pathlib import Path
from random import Random
import tempfile

from src.pipeline import (read_json, digest, validate_document, validate_corpus,
    validate_dictionary, collect_vocabulary, normalize, validate_normalized_bundle,
    fragments_for, exact_mapping, signature, Fragment, mine, node_label)

ROOT = Path(__file__).resolve().parents[1]


class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = read_json(ROOT / 'data/graphs.raw.json')
        cls.sources = read_json(ROOT / 'data/corpus.json')
        cls.texts = {s['document_id']: s['text'] for s in cls.sources}
        cls.vocab = read_json(ROOT / 'data/vocabulary.json')
        cls.dictionary = read_json(ROOT / 'data/dictionary.v2.json')
        cls.bundle = read_json(ROOT / 'data/graphs.normalized.v2.json')
        cls.assignments = read_json(ROOT / 'data/assignments.v2.json')
        cls.docs = {g['document_id']: g for g in cls.bundle['documents']}

    def invalid(self, doc):
        with self.assertRaises(ValueError):
            validate_document(doc, self.texts[doc['document_id']])

    def test_all_saved_graphs_and_normalized_integrity(self):
        validate_corpus(self.raw, self.sources)
        validate_normalized_bundle(self.bundle, self.sources, self.dictionary)

    def test_duplicate_node(self):
        doc = deepcopy(self.raw[0]); doc['nodes'].append(deepcopy(doc['nodes'][0]))
        self.invalid(doc)

    def test_dangling_relation(self):
        doc = deepcopy(self.raw[0]); doc['relations'][0]['to'] = 'n999'
        self.invalid(doc)

    def test_duplicate_relation(self):
        doc = deepcopy(self.raw[0]); doc['relations'].append(deepcopy(doc['relations'][0]))
        self.invalid(doc)

    def test_unknown_fields_and_raw_concepts(self):
        for key in ('details', 'modality', 'context', 'concept_id', 'evidence_ids'):
            doc = deepcopy(self.raw[0]); doc['nodes'][1][key] = None
            self.invalid(doc)

    def test_missing_fields_and_null_meaning(self):
        doc = deepcopy(self.raw[0]); del doc['nodes'][1]['meaning']; self.invalid(doc)
        doc = deepcopy(self.raw[0]); doc['nodes'][1]['meaning'] = None; self.invalid(doc)
        doc = deepcopy(self.raw[15]); del doc['nodes'][2]['form']; self.invalid(doc)

    def test_invalid_surface(self):
        doc = deepcopy(self.raw[0]); doc['nodes'][1]['surface'] = '原文にない操作'
        self.invalid(doc)

    def test_invalid_enums_and_unit(self):
        doc = deepcopy(self.raw[0]); doc['nodes'][1]['polarity'] = 'GOOD'; self.invalid(doc)
        doc = deepcopy(self.raw[0]); doc['nodes'][3]['unit'] = 3; self.invalid(doc)

    def test_claim_cardinality(self):
        doc = deepcopy(self.raw[0]); doc['relations'] = [e for e in doc['relations'] if e['role'] != 'FROM']
        self.invalid(doc)
        doc = deepcopy(self.raw[15]); doc['relations'].append({'from': 'n9', 'role': 'CONDITION', 'to': 'n5'})
        self.invalid(doc)

    def test_change_quantity_required(self):
        doc = deepcopy(self.raw[0]); doc['relations'] = [e for e in doc['relations'] if e['role'] != 'QUANTITY']
        self.invalid(doc)

    def test_endpoint_type(self):
        doc = deepcopy(self.raw[0]); doc['relations'][0]['role'] = 'BEARER'; self.invalid(doc)
        doc = deepcopy(self.raw[15]); next(e for e in doc['relations'] if e['role'] == 'SUBJECT')['to'] = 'n1'
        self.invalid(doc)

    def test_comparison_value_and_fields(self):
        for value in (True, None, float('inf'), []):
            doc = deepcopy(self.raw[15]); doc['nodes'][2]['value'] = value; self.invalid(doc)
        doc = deepcopy(self.raw[11]); doc['nodes'][1]['comparator'] = 'EQ'; self.invalid(doc)

    def test_logic_cardinality_and_cycle(self):
        doc = deepcopy(self.raw[17]); doc['relations'] = [e for e in doc['relations'] if not (e['role'] == 'MEMBER' and e['to'] == 'n4')]
        self.invalid(doc)
        doc = deepcopy(self.raw[17]); doc['relations'].append({'from': 'n5', 'role': 'MEMBER', 'to': 'n5'})
        self.invalid(doc)
        doc = deepcopy(self.raw[54]); doc['relations'].append({'from': 'n6', 'role': 'MEMBER', 'to': 'n5'})
        self.invalid(doc)

    def test_multiple_bearers_rejected_missing_bearer_allowed(self):
        doc = deepcopy(self.raw[0]); doc['relations'].append({'from': 'n4', 'role': 'BEARER', 'to': 'n1'})
        self.invalid(doc)
        doc = deepcopy(self.raw[0]); doc['relations'] = [e for e in doc['relations'] if e['role'] != 'BEARER']
        validate_document(doc, self.texts[doc['document_id']])

    def test_document_id_and_source_integrity(self):
        with self.assertRaises(ValueError):
            validate_corpus(self.raw + [self.raw[0]], self.sources)
        with self.assertRaises(ValueError):
            validate_corpus(self.raw, self.sources[:-1])

    def test_strict_json_rejects_duplicate_properties_nan(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'bad.json'
            for content in ('{"id":1,"id":2}', '{"value":NaN}', '{"value":Infinity}'):
                p.write_text(content, encoding='utf-8')
                with self.assertRaises(ValueError):
                    read_json(p)

    def test_dictionary_duplicate_and_wrong_type(self):
        dictionary = deepcopy(self.dictionary); dictionary['concepts'].append(deepcopy(dictionary['concepts'][0]))
        with self.assertRaises(ValueError):
            validate_dictionary(dictionary)
        doc = deepcopy(self.docs['D01']); doc['nodes'][1]['concept_id'] = 'Q001'
        with self.assertRaises(ValueError):
            validate_document(doc, self.texts['D01'], validate_dictionary(self.dictionary), True)

    def test_no_claim_documents_saved_not_collected(self):
        vocab = collect_vocabulary(self.raw, self.sources)
        self.assertEqual(vocab['documents_without_claim'], ['D24', 'D45', 'D46'])
        self.assertFalse(any(r['document_id'] in {'D24', 'D45', 'D46'} for r in vocab['rows']))
        for did in ('D24', 'D45', 'D46'):
            self.assertEqual(list(fragments_for(self.docs[did])), [])

    def test_vocabulary_dedup_context_and_condition(self):
        rows = self.vocab['rows']
        keys = [(r['document_id'], r['node_id']) for r in rows]
        self.assertEqual(len(keys), len(set(keys)))
        r = next(r for r in rows if (r['document_id'], r['node_id']) == ('D19', 'n2'))
        self.assertEqual(r['claim_membership_count'], 2)
        self.assertEqual(r['source_surface_occurrence_count'], 2)
        self.assertEqual(r['node_occurrence_count'], 1)
        self.assertIn(('D16', 'n2'), keys)  # comparison's QUANTITY below CONDITION
        self.assertTrue(all(r['context']['text'] == self.texts[r['document_id']] for r in rows))

    def test_closure_keeps_all_arguments_conditions_and_logic_members(self):
        f = next(f for f, _ in fragments_for(self.docs['D18']) if f)
        self.assertEqual(len(f.nodes), len(self.docs['D18']['nodes']))
        self.assertEqual(sum(e['role'] == 'MEMBER' for e in f.edges), 2)
        f = next(f for f, _ in fragments_for(self.docs['D16']) if f)
        self.assertIn('n1', f.nodes)  # room below CONDITION -> STATE -> QUANTITY -> BEARER
        self.assertIn('n2', f.nodes)

    def test_connected_two_claims_and_disconnected_claims(self):
        self.assertEqual(len(list(fragments_for(self.docs['D19']))), 3)
        self.assertEqual(len(list(fragments_for(self.docs['D42']))), 2)
        self.assertEqual(len(list(fragments_for(self.docs['D19'], max_claims=1))), 2)

    def test_fixed_dictionary_no_new_ids_and_assignment_completeness(self):
        for mutation in ('unknown', 'missing', 'duplicate', 'version', 'hash'):
            a = deepcopy(self.assignments)
            if mutation == 'unknown': a['assignments'][0]['concept_id'] = 'A999'
            if mutation == 'missing': a['assignments'].pop()
            if mutation == 'duplicate': a['assignments'].append(deepcopy(a['assignments'][0]))
            if mutation == 'version': a['dictionary_version'] = 'different'
            if mutation == 'hash': a['dictionary_sha256'] = 'bad'
            with self.assertRaises(ValueError, msg=mutation):
                normalize(self.raw, self.sources, self.vocab, self.dictionary, a)

    def test_normalization_preserves_original_and_never_mutates_input(self):
        before = digest(self.raw)
        b = normalize(self.raw, self.sources, self.vocab, self.dictionary, self.assignments)
        self.assertEqual(before, digest(self.raw))
        restored = deepcopy(b['documents'])
        for d in restored:
            for n in d['nodes']: n.pop('concept_id', None)
        self.assertEqual(restored, self.raw)
        b['documents'][0]['nodes'][1]['meaning'] = '変更'
        with self.assertRaises(ValueError):
            validate_normalized_bundle(b, self.sources, self.dictionary)

    def test_null_is_deferred_not_a_wildcard(self):
        b = read_json(ROOT / 'data/graphs.normalized.v1.json')
        d = next(d for d in b['documents'] if d['document_id'] == 'D43')
        f, why = next(fragments_for(d))
        self.assertIsNone(f); self.assertEqual(why['null_concept_nodes'], ['n2'])

    def test_null_in_condition_blocks_whole_fragment(self):
        doc = deepcopy(self.docs['D16']); doc['nodes'][1]['concept_id'] = None
        f, why = next(fragments_for(doc))
        self.assertIsNone(f); self.assertIn('n2', why['null_concept_nodes'])

    def test_literal_attributes_and_type_boundaries(self):
        n = deepcopy(self.docs['D16']['nodes'][2])
        for key, value in [('value', 40), ('value', '30'), ('comparator', 'GE'), ('value_unit', '℃'), ('polarity', 'NEGATIVE')]:
            changed = {**n, key: value}
            self.assertNotEqual(node_label(n, 'strict'), node_label(changed, 'strict'))
        self.assertNotEqual(node_label(self.docs['D01']['nodes'][1], 'strict'), node_label(self.docs['D51']['nodes'][1], 'strict'))

    def test_bijection_entity_identity(self):
        a = next(f for f, _ in fragments_for(self.docs['D01']) if f)
        b = next(f for f, _ in fragments_for(self.docs['D53']) if f)
        self.assertIsNone(exact_mapping(a, b))

    def test_support_documents_and_occurrences_differ(self):
        subset = [self.docs[d] for d in ('D01', 'D42')]
        sources = [s for s in self.sources if s['document_id'] in {'D01', 'D42'}]
        result = mine(subset, sources, self.dictionary)
        self.assertEqual(len(result['patterns']), 1)
        p = result['patterns'][0]
        self.assertEqual(p['support_count'], 2)
        self.assertEqual(p['occurrence_count'], 3)

    def test_role_direction_and_predicate_are_strict(self):
        a = next(f for f, _ in fragments_for(self.docs['D19']) if f and len(f.roots) == 2)
        b = next(f for f, _ in fragments_for(self.docs['D39']) if f and len(f.roots) == 2)
        self.assertIsNone(exact_mapping(a, b))
        doc = deepcopy(self.docs['D01']); doc['nodes'][-1]['predicate'] = 'SIGNALS'
        one = next(f for f, _ in fragments_for(self.docs['D01']) if f)
        other = next(f for f, _ in fragments_for(doc) if f)
        self.assertIsNone(exact_mapping(one, other))

    def test_known_representation_limits_are_visible(self):
        def matches(a, b):
            fa = next(f for f, _ in fragments_for(self.docs[a]) if f)
            fb = next(f for f, _ in fragments_for(self.docs[b]) if f)
            return exact_mapping(fa, fb) is not None
        self.assertTrue(matches('D49', 'D50'))  # OTHER collision, not a semantic success
        self.assertFalse(matches('D33', 'D55'))  # NOT vs node polarity
        self.assertTrue(matches('D01', 'D47'))  # modality is intentionally absent


def brute_bijection(a, b):
    """Independent oracle: all permutations, direct edge set comparison, no signatures."""
    if len(a.nodes) != len(b.nodes):
        return False
    left, right = sorted(a.nodes), sorted(b.nodes)
    expected = {(e['from'], e['role'], e['to']) for e in b.edges}
    for perm in permutations(right):
        mapping = dict(zip(left, perm))
        if any(a.labels[u] != b.labels[v] for u, v in mapping.items()):
            continue
        actual = {(mapping[e['from']], e['role'], mapping[e['to']]) for e in a.edges}
        if actual == expected:
            return True
    return False


class ExactMatcherTests(unittest.TestCase):
    def fragment(self, node_count, edges, labels=None):
        ids = [str(i) for i in range(node_count)]
        return Fragment('test', (), {i: {} for i in ids},
                        [{'from': str(u), 'role': role, 'to': str(v)} for u, role, v in edges],
                        dict(zip(ids, labels or ['same'] * node_count)))

    def test_same_signature_regular_graphs_are_not_necessarily_isomorphic(self):
        a = self.fragment(6, [(i, 'R', (i+1) % 6) for i in range(6)])
        b = self.fragment(6, [(i, 'R', (i//3)*3+(i+1)%3) for i in range(6)])
        self.assertEqual(signature(a), signature(b))
        self.assertIsNone(exact_mapping(a, b))
        self.assertFalse(brute_bijection(a, b))

    def test_random_graphs_against_all_permutations_100_pairs(self):
        random = Random(20260914)
        for case in range(100):
            n = random.randint(2, 6)
            labels = [random.choice(['A', 'B']) for _ in range(n)]
            edges = [(u, role, v) for u in range(n) for v in range(n) for role in ('R', 'S') if random.random() < .14]
            a = self.fragment(n, edges, labels)
            perm = list(range(n)); random.shuffle(perm)
            transformed = [(perm[u], r, perm[v]) for u, r, v in edges]
            other_labels = [None] * n
            for u, v in enumerate(perm): other_labels[v] = labels[u]
            if case % 2:
                candidate = (0, 'R', 1)
                if candidate in transformed: transformed.remove(candidate)
                else: transformed.append(candidate)
            b = self.fragment(n, transformed, other_labels)
            self.assertEqual(exact_mapping(a, b) is not None, brute_bijection(a, b), case)


if __name__ == '__main__':
    unittest.main()
