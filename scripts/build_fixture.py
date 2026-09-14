"""Rebuild the assistant-authored synthetic annotations. NOT a text extractor.

Each call below encodes an explicit annotation decision made in the authoring
session. The helper only allocates IDs and serializes JSON; it knows no concepts.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.pipeline import write_json, validate_corpus, collect_vocabulary

ROOT = Path(__file__).resolve().parents[1]
corpus, graphs, index = [], [], {}


class Graph:
    def __init__(self, number, text, split=None):
        self.did = f'D{number:02d}'
        self.text = text
        self.split = split or ('discovery' if number <= 24 else 'additional' if number <= 46 else 'diagnostic')
        self.nodes, self.edges, self.names = [], [], {}

    def node(self, key, typ, surface, **attrs):
        nid = f'n{len(self.nodes)+1}'
        if typ in {'ACTION', 'CHANGE', 'STATE', 'CLAIM'}:
            attrs.setdefault('polarity', 'POSITIVE')
        if typ == 'QUANTITY':
            attrs.setdefault('unit', None)
        if typ == 'STATE':
            for k in ('comparator', 'value', 'value_unit'):
                attrs.setdefault(k, None)
        self.nodes.append({'id': nid, 'type': typ, 'surface': surface, **attrs})
        self.names[key] = nid
        return key

    def edge(self, src, role, dst):
        self.edges.append({'from': self.names[src], 'role': role, 'to': self.names[dst]})

    def entity(self, key, surface):
        return self.node(key, 'ENTITY', surface)

    def action(self, key, surface, meaning, target=None, polarity='POSITIVE'):
        self.node(key, 'ACTION', surface, meaning=meaning, polarity=polarity)
        if target:
            self.edge(key, 'TARGET', target)
        return key

    def quantity(self, key, surface, meaning, bearer=None, unit=None):
        self.node(key, 'QUANTITY', surface, meaning=meaning, unit=unit)
        if bearer:
            self.edge(key, 'BEARER', bearer)
        return key

    def change(self, key, surface, quantity, direction='DECREASE', polarity='POSITIVE'):
        self.node(key, 'CHANGE', surface, direction=direction, polarity=polarity)
        self.edge(key, 'QUANTITY', quantity)
        return key

    def state(self, key, surface, meaning, subject):
        self.node(key, 'STATE', surface, form='QUALITATIVE', meaning=meaning)
        self.edge(key, 'SUBJECT', subject)
        return key

    def logic(self, key, surface, operator, members):
        self.node(key, 'LOGIC', surface, operator=operator)
        for m in members:
            self.edge(key, 'MEMBER', m)
        return key

    def claim(self, key, surface, src, dst, predicate='CAUSES', condition=None, polarity='POSITIVE'):
        # These are fixture-specific annotation choices, not general extraction rules.
        if predicate == 'CAUSES':
            effect_surface = next(n['surface'] for n in self.nodes if n['id'] == self.names[dst])
            surface = '原因ではない' if polarity == 'NEGATIVE' else ('原因で' if '原因で' in surface else effect_surface)
        else:
            surface = {'REQUIRES': '必要だ', 'SIGNALS': '示す手がかり', 'PREVENTS': '防ぐ', 'PRECEDES': 'してから'}[predicate]
        self.node(key, 'CLAIM', surface, predicate=predicate, polarity=polarity)
        self.edge(key, 'FROM', src)
        self.edge(key, 'TO', dst)
        if condition:
            self.edge(key, 'CONDITION', condition)
        return key

    def save(self):
        corpus.append({'document_id': self.did, 'text': self.text, 'split': self.split,
                       'origin': 'synthetic; assistant-authored; not a factual effectiveness claim'})
        graphs.append({'document_id': self.did, 'nodes': self.nodes, 'relations': self.edges})
        index[self.did] = self.names


VERIFY = '対象が期待する状態や基準に合うか確かめる'
OBSERVE = '対象の様子を見て変化や特徴を捉える'
MEASURE = '対象の属性を数値として測り取る'
COMPARE = '複数の対象の共通点や相違点を調べる'
GATHER = '散在するものを一か所に集める'
USE = '手段や道具を作業に用いる'
ELAPSED = '活動の実行に実際にかかる時間'
AVAILABLE = '活動のために使える時間の枠'
REQUIRED = '活動を実行するために必要とされる時間'


def operation(g, target, act, meaning, bearer, qsurface, qmeaning=ELAPSED,
              change='減らす', direction='DECREASE', apol='POSITIVE', cpol='POSITIVE',
              rpol='POSITIVE', condition=None, prefix='', agent=None, same_entity=False,
              qunit=None, not_logic=False):
    k = lambda name: prefix + name
    g.entity(k('target'), target)
    g.action(k('action'), act, meaning, k('target'), apol)
    if agent:
        g.entity(k('agent'), agent)
        g.edge(k('action'), 'AGENT', k('agent'))
    if not same_entity:
        g.entity(k('bearer'), bearer)
    g.quantity(k('quantity'), qsurface, qmeaning, k('target') if same_entity else k('bearer'), unit=qunit)
    g.change(k('change'), change, k('quantity'), direction, cpol)
    src = k('action')
    if not_logic:
        src = g.logic(k('not'), '確認をしない', 'NOT', [src])
    # Relation surface is a contiguous phrase covering the described relation.
    g.claim(k('claim'), g.text, src, k('change'), condition=condition, polarity=rpol)


def simple(num, text, target, act, meaning, bearer, qs, **kw):
    g = Graph(num, text)
    operation(g, target, act, meaning, bearer, qs, **kw)
    g.save()


simple(1, '部品を確認することが、組立作業の所要時間を減らす。', '部品', '確認する', VERIFY, '組立作業', '所要時間')
simple(2, '申請書を点検することが、受付作業にかかる時間を短くする。', '申請書', '点検する', VERIFY, '受付作業', 'かかる時間', change='短くする')
simple(3, '稼働中の設備を観察することが、保守作業の所要時間を減らす。', '設備', '観察する', OBSERVE, '保守作業', '所要時間')
simple(4, '部材を測定することが、加工作業の所要時間を減らす。', '部材', '測定する', MEASURE, '加工作業', '所要時間')
simple(5, '複数の見積書を比較することが、選定作業の所要時間を減らす。', '複数の見積書', '比較する', COMPARE, '選定作業', '所要時間')
simple(6, '記録を集めることが、監査作業の所要時間を減らす。', '記録', '集める', GATHER, '監査作業', '所要時間')
simple(7, '各端末のログを収集することが、調査作業にかかる時間を短くする。', 'ログ', '収集する', GATHER, '調査作業', 'かかる時間', change='短くする')
simple(8, 'テンプレートを使用することが、文書作成の所要時間を減らす。', 'テンプレート', '使用する', USE, '文書作成', '所要時間')
simple(9, '治具を活用することが、組立作業にかかる時間を短くする。', '治具', '活用する', USE, '組立作業', 'かかる時間', change='短くする')
simple(10, '部品を確認することが、組立作業に使える時間を増やす。', '部品', '確認する', VERIFY, '組立作業', '使える時間', qmeaning=AVAILABLE, change='増やす', direction='INCREASE')
simple(11, '部品を確認することが、組立作業に必要な時間を減らす。', '部品', '確認する', VERIFY, '組立作業', '必要な時間', qmeaning=REQUIRED)


def state_effect(num, text, subject, ss, meaning, bearer, qs, change='増やす'):
    g = Graph(num, text)
    g.entity('subject', subject)
    g.state('state', ss, meaning, 'subject')
    g.entity('bearer', bearer)
    g.quantity('quantity', qs, ELAPSED, 'bearer')
    g.change('change', change, 'quantity', 'INCREASE')
    g.claim('claim', text, 'state', 'change')
    g.save()


state_effect(12, '設備が破損していることが、修復作業の所要時間を増やす。', '設備', '破損している', '物が壊れて機能や形が損なわれている', '修復作業', '所要時間')
state_effect(13, '装置が壊れていることが、復旧作業にかかる時間を増やす。', '装置', '壊れている', '物が壊れて機能や形が損なわれている', '復旧作業', 'かかる時間')
state_effect(14, '承認が遅れていることが、納品作業の所要時間を増やす。', '承認', '遅れている', '予定や期待した時点より進行が遅い', '納品作業', '所要時間')
simple(15, '送風機を使用することが、装置の温度を下げる。', '送風機', '使用する', USE, '装置', '温度', qmeaning='対象の熱さ冷たさを表す量', change='下げる')


def conditional(num, text, target, act, bearer, threshold=30, comparator='LE', ss='30度以下'):
    g = Graph(num, text)
    g.entity('room', '室内')
    g.quantity('temp', '温度', '対象の熱さ冷たさを表す量', 'room', '度')
    g.node('condition', 'STATE', ss, form='COMPARISON', meaning=None, comparator=comparator,
           value=threshold, value_unit='度')
    g.edge('condition', 'SUBJECT', 'temp')
    operation(g, target, act, VERIFY, bearer, '所要時間', condition='condition')
    g.save()


conditional(16, '室内の温度が30度以下のとき、部品を確認することが、組立作業の所要時間を減らす。', '部品', '確認する', '組立作業')
conditional(17, '室内の温度が30度以下のとき、伝票を点検することが、仕分作業の所要時間を減らす。', '伝票', '点検する', '仕分作業')


def joint(num, operator, text):
    g = Graph(num, text)
    g.entity('parts', '部品')
    g.entity('tools', '工具')
    g.action('verify', '確認する', VERIFY, 'parts')
    g.action('gather', '集める', GATHER, 'tools')
    g.logic('logic', '部品を確認することと工具を集めること' if operator == 'AND' else '部品を確認すること、または工具を集めること', operator, ['verify', 'gather'])
    g.entity('bearer', '組立作業')
    g.quantity('quantity', '所要時間', ELAPSED, 'bearer')
    g.change('change', '減らす', 'quantity')
    g.claim('claim', text, 'logic', 'change')
    g.save()


joint(18, 'AND', '部品を確認することと工具を集めることが共同で、組立作業の所要時間を減らす。')


def chain(num, text, target, verify, gather, bearer, qs, reverse=False):
    g = Graph(num, text)
    g.entity('target', target)
    g.action('verify', verify, VERIFY, 'target')
    g.action('gather', gather, GATHER, 'target')
    g.claim('requires', text.split('。')[0], 'gather' if reverse else 'verify', 'verify' if reverse else 'gather', 'REQUIRES')
    g.entity('bearer', bearer)
    g.quantity('quantity', qs, ELAPSED, 'bearer')
    g.change('change', '減らす', 'quantity')
    g.claim('causes', text.split('。')[1], 'verify', 'change')
    g.save()


chain(19, '記録を確認するには、記録を集めることが必要だ。記録を確認することが、監査作業の所要時間を減らす。', '記録', '確認する', '集める', '監査作業', '所要時間')
chain(20, 'ログを点検するには、ログを収集することが必要だ。ログを点検することが、調査作業にかかる時間を減らす。', 'ログ', '点検する', '収集する', '調査作業', 'かかる時間')
g = Graph(21, '部品を確認してから、部品を使用する。')
g.entity('target', '部品')
g.action('verify', '確認', VERIFY, 'target')
g.action('use', '使用する', USE, 'target')
g.claim('claim', g.text, 'verify', 'use', 'PRECEDES')
g.save()
g = Graph(22, '梱包材を使用することが、製品の破損を防ぐ。')
g.entity('target', '梱包材')
g.action('use', '使用する', USE, 'target')
g.entity('product', '製品')
g.state('damage', '破損', '物が壊れて機能や形が損なわれている', 'product')
g.claim('claim', g.text, 'use', 'damage', 'PREVENTS')
g.save()
g = Graph(23, '設備の異常音は、設備の破損を示す手がかりだ。')
g.entity('equipment', '設備')
g.state('noise', '異常音', '通常と異なる音が発生している', 'equipment')
g.state('damage', '破損', '物が壊れて機能や形が損なわれている', 'equipment')
g.claim('claim', g.text, 'noise', 'damage', 'SIGNALS')
g.save()
g = Graph(24, '検査員は部品を確認する。机の上に工具がある。')
g.entity('worker', '検査員')
g.entity('parts', '部品')
g.action('action', '確認する', VERIFY, 'parts')
g.edge('action', 'AGENT', 'worker')
g.entity('desk', '机')
g.entity('tools', '工具')
g.save()

simple(25, '請求書を確かめることが、支払処理に実際にかかる時間を短縮する。', '請求書', '確かめる', VERIFY, '支払処理', '実際にかかる時間', change='短縮する')
simple(26, '運転中の装置の様子を見ることが、保守作業にかかる時間を減らす。', '装置', '様子を見る', OBSERVE, '保守作業', 'かかる時間')
simple(27, '試料を計測することが、検査作業にかかる時間を減らす。', '試料', '計測する', MEASURE, '検査作業', 'かかる時間')
simple(28, '二つの設計案を比べることが、選定作業にかかる時間を減らす。', '二つの設計案', '比べる', COMPARE, '選定作業', 'かかる時間')
simple(29, '各支店の報告書を集約することが、決算作業にかかる時間を減らす。', '報告書', '集約する', GATHER, '決算作業', 'かかる時間')
simple(30, 'ひな型を用いることが、報告書作成にかかる時間を減らす。', 'ひな型', '用いる', USE, '報告書作成', 'かかる時間')
state_effect(31, '機械が損傷していることが、修理作業にかかる時間を増やす。', '機械', '損傷している', '物が壊れて機能や形が損なわれている', '修理作業', 'かかる時間')
state_effect(32, '配送が遅延していることが、補充作業にかかる時間を増やす。', '配送', '遅延している', '予定や期待した時点より進行が遅い', '補充作業', 'かかる時間')
simple(33, '部品を確認しないことが、組立作業の所要時間を減らす。', '部品', '確認', VERIFY, '組立作業', '所要時間', apol='NEGATIVE')
simple(34, '部品の確認が原因で、組立作業の所要時間が減らない。', '部品', '確認', VERIFY, '組立作業', '所要時間', change='減らない', cpol='NEGATIVE')
simple(35, '部品を確認することは、組立作業の所要時間が減る原因ではない。', '部品', '確認する', VERIFY, '組立作業', '所要時間', change='減る', rpol='NEGATIVE')
conditional(36, '室内の温度が40度以下のとき、部品を確認することが、組立作業の所要時間を減らす。', '部品', '確認する', '組立作業', 40, 'LE', '40度以下')
conditional(37, '室内の温度が30度以上のとき、部品を確認することが、組立作業の所要時間を減らす。', '部品', '確認する', '組立作業', 30, 'GE', '30度以上')
joint(38, 'OR', '部品を確認すること、または工具を集めることが、組立作業の所要時間を減らす。')
chain(39, '記録を集めるには、記録を確認することが必要だ。記録を確認することが、監査作業の所要時間を減らす。', '記録', '確認する', '集める', '監査作業', '所要時間', True)
simple(40, '作業員が部品を確認することが、組立作業の所要時間を減らす。', '部品', '確認する', VERIFY, '組立作業', '所要時間', agent='作業員')
chain(41, '報告書を確かめるには、報告書を集約することが必要だ。報告書を確かめることが、決算作業にかかる時間を減らす。', '報告書', '確かめる', '集約する', '決算作業', 'かかる時間')
g = Graph(42, '部品を確認することが、組立作業の所要時間を減らす。伝票を点検することが、仕分作業にかかる時間を短くする。')
operation(g, '部品', '確認する', VERIFY, '組立作業', '所要時間', prefix='first_')
operation(g, '伝票', '点検する', VERIFY, '仕分作業', 'かかる時間', change='短くする', prefix='second_')
g.save()
simple(43, '測定器を校正することが、検査作業の所要時間を減らす。', '測定器', '校正する', '標準とのずれを確かめ測定値の対応関係を定める', '検査作業', '所要時間')
simple(44, 'センサーの値と標準値との対応を定めることが、点検作業にかかる時間を減らす。', 'センサー', '標準値との対応を定める', '標準とのずれを確かめ測定値の対応関係を定める', '点検作業', 'かかる時間')
g = Graph(45, '製品の破損を防ぐため、梱包材を使用する。')
g.entity('product', '製品')
g.state('damage', '破損', '物が壊れて機能や形が損なわれている', 'product')
g.entity('target', '梱包材')
g.action('use', '使用する', USE, 'target')
g.save()
g = Graph(46, '部品を確認するなら、記録を集める。')
g.entity('parts', '部品')
g.action('verify', '確認する', VERIFY, 'parts')
g.entity('records', '記録')
g.action('gather', '集める', GATHER, 'records')
g.save()
simple(47, '部品を確認することが、組立作業の所要時間を減らすことがある。', '部品', '確認する', VERIFY, '組立作業', '所要時間')
simple(48, '部品の確認を推奨する。部品を確認することが、組立作業の所要時間を減らす。', '部品', '確認する', VERIFY, '組立作業', '所要時間')


def other_change(num, text, surface):
    g = Graph(num, text)
    g.entity('equipment', '装置')
    g.quantity('temp', '温度', '対象の熱さ冷たさを表す量', 'equipment')
    g.change('first_change', surface, 'temp', 'OTHER')
    g.entity('bearer', '組立作業')
    g.quantity('quantity', '所要時間', ELAPSED, 'bearer')
    g.change('change', '増やす', 'quantity', 'INCREASE')
    g.claim('claim', text, 'first_change', 'change')
    g.save()


other_change(49, '装置の温度が変動することが、組立作業の所要時間を増やす。', '変動する')
other_change(50, '装置の温度が一定になることが、組立作業の所要時間を増やす。', '一定になる')
simple(51, '二つの見積書について、差を確認することが、選定作業の所要時間を減らす。', '二つの見積書', '確認する', '複数の対象の差を調べる', '選定作業', '所要時間')
simple(52, '見積書について、基準に合うか確認することが、選定作業の所要時間を減らす。', '見積書', '確認する', '対象が基準に適合するか確かめる', '選定作業', '所要時間')
simple(53, '組立作業を確認することが、組立作業の所要時間を減らす。', '組立作業', '確認する', VERIFY, '組立作業', '所要時間', same_entity=True)
simple(54, '部品の確認が原因で、組立作業の所要時間が増えない。', '部品', '確認', VERIFY, '組立作業', '所要時間', change='増えない', direction='INCREASE', cpol='NEGATIVE')
simple(55, '部品の確認をしないことが、組立作業の所要時間を減らす。', '部品', '確認', VERIFY, '組立作業', '所要時間', not_logic=True)
simple(56, '部品を確認することが、分で表す組立作業の所要時間を減らす。', '部品', '確認する', VERIFY, '組立作業', '所要時間', qunit='分')

if __name__ == '__main__':
    validate_corpus(graphs, corpus)
    write_json(ROOT / 'data/corpus.json', corpus)
    write_json(ROOT / 'data/graphs.raw.json', graphs)
    write_json(ROOT / 'data/annotation_index.json', index)
    vocabulary = collect_vocabulary(graphs, corpus)
    write_json(ROOT / 'data/vocabulary.json', vocabulary)
    write_json(ROOT / 'data/vocabulary.discovery.json', {'rows': [r for r in vocabulary['rows'] if r['split'] == 'discovery']})
    lines = ['# 仮想ノウハウ56件', '', 'すべて実験用の創作です。記載した因果の有効性は主張しません。', '']
    for s in corpus:
        lines += [f'## {s["document_id"]} ({s["split"]})', '', s['text'], '']
    (ROOT / 'docs/corpus.md').write_text('\n'.join(lines), encoding='utf-8')
    print(f'{len(graphs)} documents; {len(vocabulary["rows"])} unique contextual terms; no CLAIM: {vocabulary["documents_without_claim"]}')
