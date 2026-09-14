"""Strict validation, contextual vocabulary, frozen normalization and exact mining.

Python 3.10+, standard library. This module never reads evaluation expectations.
The exact matcher follows fumin0ri/structuring@7491317 (see docs/provenance.md).
"""
from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
from dataclasses import dataclass
from itertools import combinations
import hashlib
import json
import math
from pathlib import Path
import re

COMMON = {'id', 'type', 'surface'}
FIELDS = {
    'ENTITY': set(), 'ACTION': {'meaning', 'polarity'},
    'QUANTITY': {'meaning', 'unit'}, 'CHANGE': {'direction', 'polarity'},
    'STATE': {'form', 'meaning', 'comparator', 'value', 'value_unit', 'polarity'},
    'CLAIM': {'predicate', 'polarity'}, 'LOGIC': {'operator'},
}
TERMS = {'ACTION', 'STATE', 'CHANGE', 'LOGIC'}
ROLES = {
    'AGENT': ({'ACTION'}, {'ENTITY'}),
    'TARGET': ({'ACTION'}, {'ENTITY', 'QUANTITY'}),
    'ORIGIN': ({'ACTION'}, {'ENTITY'}), 'DESTINATION': ({'ACTION'}, {'ENTITY'}),
    'BEARER': ({'QUANTITY'}, {'ENTITY'}), 'QUANTITY': ({'CHANGE'}, {'QUANTITY'}),
    'SUBJECT': ({'STATE'}, {'ENTITY', 'QUANTITY'}),
    'FROM': ({'CLAIM'}, TERMS), 'TO': ({'CLAIM'}, TERMS),
    'CONDITION': ({'CLAIM'}, TERMS), 'MEMBER': ({'LOGIC'}, TERMS),
}
ENUMS = {
    'polarity': {'POSITIVE', 'NEGATIVE'},
    'direction': {'INCREASE', 'DECREASE', 'OTHER'},
    'form': {'QUALITATIVE', 'COMPARISON'},
    'predicate': {'CAUSES', 'SIGNALS', 'REQUIRES', 'PREVENTS', 'PRECEDES'},
    'operator': {'AND', 'OR', 'NOT'},
}
PROFILES = {'surface', 'strict', 'no_concepts', 'no_conditions', 'no_polarity', 'no_units'}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def read_json(path):
    def unique_object(pairs):
        result = {}
        for k, v in pairs:
            require(k not in result, f'duplicate JSON property: {k}')
            result[k] = v
        return result
    return json.loads(Path(path).read_text(encoding='utf-8-sig'),
                      object_pairs_hook=unique_object,
                      parse_constant=lambda s: (_ for _ in ()).throw(ValueError(f'invalid JSON number {s}')))


def write_json(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def digest(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def is_term(n):
    return n['type'] in {'ACTION', 'QUANTITY'} or (n['type'] == 'STATE' and n.get('form') == 'QUALITATIVE')


def validate_dictionary(dictionary):
    require(set(dictionary) == {'version', 'concepts'}, 'dictionary fields')
    require(isinstance(dictionary['version'], str) and dictionary['version'], 'dictionary version')
    require(isinstance(dictionary['concepts'], list), 'concepts must be an array')
    registry = {}
    for c in dictionary['concepts']:
        require(set(c) == {'id', 'node_type', 'name', 'definition', 'examples', 'distinctions'}, 'concept fields')
        require(c['node_type'] in {'ACTION', 'QUANTITY', 'STATE'}, 'concept type')
        for k in ('id', 'name', 'definition', 'distinctions'):
            require(isinstance(c[k], str) and c[k].strip(), f'empty concept {k}')
        require(isinstance(c['examples'], list) and c['examples'] and
                all(isinstance(x, str) and x for x in c['examples']), 'concept examples')
        require(c['id'] not in registry, 'duplicate concept ID')
        registry[c['id']] = c
    return registry


def validate_document(doc, text, registry=None, normalized=False):
    require(isinstance(doc, dict) and set(doc) == {'document_id', 'nodes', 'relations'}, 'document fields')
    docid = doc['document_id']
    require(isinstance(docid, str) and docid, 'document_id')
    require(isinstance(text, str), f'{docid}: missing source text')
    require(isinstance(doc['nodes'], list) and isinstance(doc['relations'], list), f'{docid}: arrays required')
    nodes = {}
    for n in doc['nodes']:
        require(isinstance(n, dict), f'{docid}: node object required')
        t = n.get('type')
        require(isinstance(t, str) and t in FIELDS, f'{docid}: node type')
        extra = {'concept_id'} if normalized and is_term(n) else set()
        require(set(n) == COMMON | FIELDS[t] | extra, f'{docid}: {n.get("id")}: fields')
        nid = n['id']
        require(isinstance(nid, str) and re.fullmatch(r'n[1-9][0-9]*', nid), f'{docid}: node ID')
        require(nid not in nodes, f'{docid}: duplicate node ID')
        nodes[nid] = n
        require(isinstance(n['surface'], str) and n['surface'] and n['surface'] in text,
                f'{docid}/{nid}: surface must be a contiguous source substring: {n["surface"]}')
        for k, vals in ENUMS.items():
            if k in n:
                require(isinstance(n[k], str) and n[k] in vals, f'{docid}/{nid}: invalid {k}')
        if t in {'ACTION', 'QUANTITY'} or (t == 'STATE' and n['form'] == 'QUALITATIVE'):
            require(isinstance(n['meaning'], str) and n['meaning'].strip(), f'{docid}/{nid}: meaning')
        for k in ('unit', 'value_unit'):
            if k in n:
                require(n[k] is None or (isinstance(n[k], str) and n[k].strip()), f'{docid}/{nid}: {k}')
        if t == 'STATE':
            if n['form'] == 'QUALITATIVE':
                require(all(n[k] is None for k in ('comparator', 'value', 'value_unit')), f'{docid}/{nid}: qualitative fields')
            else:
                require(n['meaning'] is None and isinstance(n['comparator'], str) and
                        n['comparator'] in {'EQ', 'NE', 'LT', 'LE', 'GT', 'GE'}, f'{docid}/{nid}: comparison fields')
                value = n['value']
                require(type(value) in (str, int, float) and (not isinstance(value, float) or math.isfinite(value)),
                        f'{docid}/{nid}: comparison value')
        if extra:
            cid = n['concept_id']
            require(cid is None or (isinstance(cid, str) and registry is not None and
                    cid in registry and registry[cid]['node_type'] == t), f'{docid}/{nid}: unknown or wrong-type concept')
    outgoing = defaultdict(list)
    seen = set()
    for e in doc['relations']:
        require(isinstance(e, dict) and set(e) == {'from', 'role', 'to'}, f'{docid}: relation fields')
        require(all(isinstance(e[k], str) for k in e), f'{docid}: relation string fields')
        require(e['from'] in nodes and e['to'] in nodes, f'{docid}: dangling relation')
        require(e['role'] in ROLES, f'{docid}: role')
        src, dst = ROLES[e['role']]
        require(nodes[e['from']]['type'] in src and nodes[e['to']]['type'] in dst, f'{docid}: endpoint type')
        key = (e['from'], e['role'], e['to'])
        require(key not in seen, f'{docid}: duplicate relation')
        seen.add(key)
        outgoing[e['from']].append(e)
    for nid, n in nodes.items():
        es = outgoing[nid]
        counts = Counter(e['role'] for e in es)
        if n['type'] == 'CLAIM':
            require(counts['FROM'] == counts['TO'] == 1 and counts['CONDITION'] <= 1, f'{docid}/{nid}: CLAIM cardinality')
        if n['type'] == 'CHANGE':
            require(counts['QUANTITY'] == 1, f'{docid}/{nid}: CHANGE cardinality')
        require(counts['BEARER'] <= 1 and counts['SUBJECT'] <= 1, f'{docid}/{nid}: argument cardinality')
        if n['type'] == 'STATE' and n['form'] == 'COMPARISON':
            require(all(nodes[e['to']]['type'] == 'QUANTITY' for e in es), f'{docid}/{nid}: comparison SUBJECT type')
        if n['type'] == 'LOGIC':
            require(counts['MEMBER'] == 1 if n['operator'] == 'NOT' else counts['MEMBER'] >= 2,
                    f'{docid}/{nid}: LOGIC cardinality')
    visited, active = set(), set()
    def visit(nid):
        require(nid not in active, f'{docid}: cyclic LOGIC')
        if nid in visited:
            return
        active.add(nid)
        for e in outgoing[nid]:
            if nodes[e['to']]['type'] == 'LOGIC':
                visit(e['to'])
        active.remove(nid)
        visited.add(nid)
    for nid, n in nodes.items():
        if n['type'] == 'LOGIC':
            visit(nid)
    return nodes, outgoing


def validate_corpus(graphs, sources, registry=None, normalized=False):
    require(isinstance(graphs, list) and isinstance(sources, list), 'corpus arrays required')
    source_ids = [s['document_id'] for s in sources]
    require(len(source_ids) == len(set(source_ids)), 'duplicate source document_id')
    texts = {s['document_id']: s['text'] for s in sources}
    ids = [g['document_id'] for g in graphs]
    require(len(ids) == len(set(ids)), 'duplicate graph document_id')
    require(set(ids) == set(texts), 'graph/source document IDs must match exactly')
    for doc in graphs:
        validate_document(doc, texts[doc['document_id']], registry, normalized)
    return texts


def closure(roots, outgoing, include_conditions=True):
    found, edge_keys, pending = set(), set(), list(roots)
    while pending:
        nid = pending.pop()
        if nid in found:
            continue
        found.add(nid)
        for e in outgoing.get(nid, []):
            if not include_conditions and e['role'] == 'CONDITION':
                continue
            edge_keys.add((e['from'], e['role'], e['to']))
            pending.append(e['to'])
    return found, edge_keys


def collect_vocabulary(graphs, sources):
    texts = validate_corpus(graphs, sources)
    rows, no_claim = [], []
    splits = {s['document_id']: s['split'] for s in sources}
    for doc in graphs:
        did = doc['document_id']
        nodes, outgoing = validate_document(doc, texts[did])
        claims = [n['id'] for n in doc['nodes'] if n['type'] == 'CLAIM']
        if not claims:
            no_claim.append(did)
        scopes = {c: closure([c], outgoing)[0] for c in claims}
        selected = set().union(*scopes.values()) if scopes else set()
        for nid in sorted(selected):
            n = nodes[nid]
            if not is_term(n):
                continue
            related = sorted(c for c, scope in scopes.items() if nid in scope)
            context_ids = set().union(*(scopes[c] for c in related))
            offsets = [m.start() for m in re.finditer(re.escape(n['surface']), texts[did])]
            rows.append({
                'document_id': did, 'node_id': nid, 'split': splits[did], 'node_type': n['type'],
                'surface': n['surface'], 'meaning': n['meaning'], 'node_occurrence_count': 1,
                'source_surface_occurrence_count': len(offsets), 'surface_offsets': offsets,
                'claim_membership_count': len(related), 'related_claim_ids': related,
                'connections': [{**e, 'target_surface': nodes[e['to']]['surface']} for e in outgoing[nid]],
                'context': {'text': texts[did], 'nodes': [nodes[i] for i in sorted(context_ids)],
                            'relations': [e for e in doc['relations'] if e['from'] in context_ids and e['to'] in context_ids]},
            })
    return {'rows': rows, 'documents_without_claim': no_claim,
            'counting_policy': 'One row per document_id/node_id. Text occurrences and CLAIM memberships are separate counts.'}


def normalize(graphs, sources, vocabulary, dictionary, assignments):
    registry = validate_dictionary(dictionary)
    validate_corpus(graphs, sources)
    require(digest(vocabulary) == digest(collect_vocabulary(graphs, sources)), 'vocabulary does not match raw graphs/sources')
    expected = {(r['document_id'], r['node_id']) for r in vocabulary['rows']}
    require(assignments['dictionary_version'] == dictionary['version'] and
            assignments['dictionary_sha256'] == digest(dictionary), 'assignment dictionary version/hash mismatch')
    require(assignments['vocabulary_sha256'] == digest(vocabulary), 'assignment vocabulary hash mismatch')
    selected = {}
    for a in assignments['assignments']:
        require(set(a) == {'document_id', 'node_id', 'concept_id', 'rationale'}, 'assignment fields')
        key = (a['document_id'], a['node_id'])
        require(key not in selected and key in expected, 'duplicate/irrelevant assignment')
        require(isinstance(a['rationale'], str) and a['rationale'], 'assignment rationale')
        selected[key] = a['concept_id']
    require(set(selected) == expected, 'missing assignment')
    result = deepcopy(graphs)
    for doc in result:
        for n in doc['nodes']:
            if is_term(n):
                n['concept_id'] = selected.get((doc['document_id'], n['id']))
    validate_corpus(result, sources, registry, normalized=True)
    return {'dictionary_version': dictionary['version'], 'dictionary_sha256': digest(dictionary),
            'raw_graphs_sha256': digest(graphs), 'documents': result}


def validate_normalized_bundle(bundle, sources, dictionary):
    require(set(bundle) == {'dictionary_version', 'dictionary_sha256', 'raw_graphs_sha256', 'documents'}, 'normalized envelope fields')
    require(bundle['dictionary_version'] == dictionary['version'] and
            bundle['dictionary_sha256'] == digest(dictionary), 'normalized dictionary version/hash mismatch')
    registry = validate_dictionary(dictionary)
    validate_corpus(bundle['documents'], sources, registry, True)
    stripped = deepcopy(bundle['documents'])
    for doc in stripped:
        for n in doc['nodes']:
            n.pop('concept_id', None)
    require(digest(stripped) == bundle['raw_graphs_sha256'], 'normalized structure/surface/meaning changed')
    return bundle['documents']


def node_label(n, profile):
    t = n['type']
    label = {'type': t}
    fields = {
        'ENTITY': [], 'ACTION': ['polarity'], 'QUANTITY': ['unit'],
        'CHANGE': ['direction', 'polarity'],
        'STATE': ['form', 'comparator', 'value', 'value_unit', 'polarity'],
        'CLAIM': ['predicate', 'polarity'], 'LOGIC': ['operator'],
    }[t]
    if is_term(n) and profile != 'no_concepts':
        fields = fields + (['surface'] if profile == 'surface' else ['concept_id'])
    for k in fields:
        if k == 'polarity' and profile == 'no_polarity':
            continue
        if k in {'unit', 'value_unit'} and profile == 'no_units':
            continue
        label[k] = n[k]
    # JSON serialization keeps bool/numeric/string attributes distinct, units literal.
    return json.dumps(label, sort_keys=True, ensure_ascii=False, allow_nan=False)


@dataclass
class Fragment:
    document_id: str
    roots: tuple
    nodes: dict
    edges: list
    labels: dict

    @property
    def key(self):
        return self.document_id + ':' + ','.join(self.roots)


def fragments_for(doc, profile='strict', max_claims=2):
    require(profile in PROFILES, 'unknown profile')
    require(max_claims in (1, 2), 'max_claims must be 1 or 2')
    nodes = {n['id']: n for n in doc['nodes']}
    outgoing = defaultdict(list)
    for e in doc['relations']:
        outgoing[e['from']].append(e)
    claims = sorted(nid for nid, n in nodes.items() if n['type'] == 'CLAIM')
    scopes = {c: closure([c], outgoing)[0] for c in claims}
    roots_list = [(c,) for c in claims]
    if max_claims == 2:
        # Weak connection includes a shared ENTITY, as in the previous miner.
        roots_list += [(a, b) for a, b in combinations(claims, 2) if scopes[a] & scopes[b]]
    for roots in roots_list:
        full_ids, _ = closure(roots, outgoing)
        missing = [nid for nid in sorted(full_ids) if is_term(nodes[nid]) and nodes[nid].get('concept_id') is None]
        if profile not in {'surface', 'no_concepts'} and missing:
            yield None, {'document_id': doc['document_id'], 'claim_ids': list(roots), 'null_concept_nodes': missing}
            continue
        ids, keys = closure(roots, outgoing, include_conditions=profile != 'no_conditions')
        yield Fragment(doc['document_id'], roots, {i: nodes[i] for i in sorted(ids)},
                       [e for e in doc['relations'] if (e['from'], e['role'], e['to']) in keys],
                       {i: node_label(nodes[i], profile) for i in sorted(ids)}), None


def signature(f):
    return (len(f.nodes), len(f.edges), tuple(sorted(Counter(f.labels.values()).items())),
            tuple(sorted(Counter(e['role'] for e in f.edges).items())))


def adjacency(f):
    edges = defaultdict(Counter)
    neighbors = {n: Counter() for n in f.nodes}
    for e in f.edges:
        u, v, role = e['from'], e['to'], e['role']
        edges[u, v][role] += 1
        neighbors[u][('out', role, f.labels[v])] += 1
        neighbors[v][('in', role, f.labels[u])] += 1
    return edges, neighbors


def exact_mapping(a, b):
    """Complete directed attributed graph bijection; never accept a signature alone."""
    if signature(a) != signature(b):
        return None
    ea, na = adjacency(a)
    eb, nb = adjacency(b)
    choices = {u: [v for v in sorted(b.nodes) if a.labels[u] == b.labels[v] and na[u] == nb[v]] for u in a.nodes}
    if any(not options for options in choices.values()):
        return None
    mapping, used = {}, set()
    def compatible(u, v):
        return ea[u, u] == eb[v, v] and all(
            ea[u, x] == eb[v, y] and ea[x, u] == eb[y, v] for x, y in mapping.items())
    def search():
        if len(mapping) == len(a.nodes):
            return dict(mapping)
        remaining = {u: [v for v in choices[u] if v not in used and compatible(u, v)] for u in a.nodes if u not in mapping}
        u = min(remaining, key=lambda n: (len(remaining[n]), n))
        for v in remaining[u]:
            mapping[u] = v
            used.add(v)
            result = search()
            if result is not None:
                return result
            del mapping[u]
            used.remove(v)
        return None
    return search()


def mine(graphs, sources, dictionary=None, profile='strict', max_claims=2, min_support=2):
    require(profile in PROFILES and max_claims in (1, 2) and min_support >= 1, 'invalid mining parameters')
    normalized = dictionary is not None
    registry = validate_dictionary(dictionary) if normalized else None
    require(normalized or profile in {'surface', 'no_concepts'}, 'strict mining needs a frozen dictionary')
    texts = validate_corpus(graphs, sources, registry, normalized)
    buckets, patterns, deferred = defaultdict(list), [], []
    total = accepted = calls = 0
    for doc in graphs:
        for f, reason in fragments_for(doc, profile, max_claims):
            total += 1
            if reason:
                deferred.append(reason)
                continue
            accepted += 1
            bucket = signature(f)
            matched = None
            for p in buckets[bucket]:
                calls += 1
                mapping = exact_mapping(p['_fragment'], f)
                if mapping is not None:
                    matched = p
                    break
            if matched is None:
                matched = {'pattern_id': f'P{len(patterns)+1:03d}', '_fragment': f,
                           'claim_count': len(f.roots), 'representative_document': f.document_id,
                           'claim_ids': list(f.roots), 'nodes': list(f.nodes.values()),
                           'relations': f.edges, 'labels': {i: json.loads(v) for i, v in f.labels.items()}, 'occurrences': []}
                patterns.append(matched)
                buckets[bucket].append(matched)
                mapping = {n: n for n in f.nodes}
            matched['occurrences'].append({
                'key': f.key, 'document_id': f.document_id, 'claim_ids': list(f.roots),
                'node_mapping': mapping,
                'relation_mapping': [{'pattern': e, 'source': {'from': mapping[e['from']], 'role': e['role'], 'to': mapping[e['to']]}}
                                     for e in matched['_fragment'].edges],
                'entity_substitutions': [{'pattern_node': u, 'source_node': v, 'source_surface': f.nodes[v]['surface']}
                                         for u, v in mapping.items() if f.nodes[v]['type'] == 'ENTITY'],
                'source_text': texts[f.document_id],
            })
    for p in patterns:
        del p['_fragment']
        p['supporting_documents'] = sorted({o['document_id'] for o in p['occurrences']})
        p['support_count'] = len(p['supporting_documents'])
        p['occurrence_count'] = len(p['occurrences'])
    recurring = [p['pattern_id'] for p in patterns if p['support_count'] >= min_support]
    return {'profile': profile, 'input_sha256': digest(graphs),
            'dictionary_version': dictionary['version'] if dictionary else None,
            'dictionary_sha256': digest(dictionary) if dictionary else None,
            'max_claims': max_claims, 'min_support': min_support,
            'stats': {'documents': len(graphs), 'fragments_total': total, 'fragments_accepted': accepted,
                      'fragments_deferred': len(deferred), 'distinct_patterns': len(patterns),
                      'recurring_patterns': len(recurring), 'exact_isomorphism_calls': calls},
            'recurring_pattern_ids': recurring, 'patterns': patterns, 'deferred': deferred}
