"""Generate Japanese report from measured results and explicit semantic reviews."""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.pipeline import read_json, write_json


def main():
    validation = read_json(ROOT / 'results/validation.json')
    evals = read_json(ROOT / 'results/evaluation.json')
    usage = read_json(ROOT / 'results/concept_usage.json')
    manifest = read_json(ROOT / 'results/run_manifest.json')
    tests = read_json(ROOT / 'results/test_run.json')
    results = {name: read_json(ROOT / f'results/{name}.json') for name in evals}
    strict = results['strict_v2']
    patterns = [p for p in strict['patterns'] if p['support_count'] >= 2]
    reviews = {
        'D01': ('適合確認 → 実行所要時間の減少', '言い換えの統合は注釈意図に合う。D47の可能性・D48の推奨は原文での区別が必要。D39は1CLAIMだけ一致し、2CLAIM全体は一致しない。'),
        'D03': ('観察 → 実行所要時間の減少', '観察する／様子を見るを統合。確認や測定とは別概念。'),
        'D04': ('測定 → 実行所要時間の減少', '測定する／計測するを統合。校正とは別概念。'),
        'D05': ('比較 → 実行所要時間の減少', '比較する／比べる／差を確認するを文脈に従って統合。'),
        'D06': ('収集 → 実行所要時間の減少', '集める／収集する／集約するを統合。ただし集約の意味は原文次第で、要約なら別概念。'),
        'D08': ('使用 → 実行所要時間の減少', '使用する／活用する／用いるを統合。道具の転用可能性までは分からない。'),
        'D12': ('破損 → 実行所要時間の増加', '破損している／壊れている／損傷しているを統合。'),
        'D14': ('遅延 → 実行所要時間の増加', '遅れている／遅延しているを統合。破損と区別。'),
        'D16': ('温度≦30度という条件下の適合確認 → 時間減少', '条件の量・値・単位・比較演算子と対象まで一致。D36/D37の条件違いは不一致。'),
        'D43': ('校正 → 実行所要時間の減少', '初版で保留した二例を、改訂版の一つの追加概念で分類。'),
        'D49': ('温度のOTHER変化 → 実行所要時間の増加', '意味上の誤一致。変動することと一定になることを同じ変化として扱っている。原理候補として自動採用しない。'),
    }
    audit = []
    for p in patterns:
        if p['representative_document'] == 'D19':
            title = '適合確認には収集が必要' if p['claim_count'] == 1 else '適合確認には収集が必要 ＋ 適合確認が時間を減らす'
            note = 'REQUIRESのFROMは成立・実行する内容、TOは必要な操作。D39の逆向きとは一致しない。'
        else:
            title, note = reviews[p['representative_document']]
        audit.append({'pattern_id': p['pattern_id'], 'summary': title, 'claim_count': p['claim_count'],
                      'documents': p['supporting_documents'], 'support_count': p['support_count'],
                      'occurrence_count': p['occurrence_count'],
                      'review': note, 'reviewer': 'same assistant that authored data; not independent',
                      'semantic_false_match': p['representative_document'] == 'D49'})
    write_json(ROOT / 'results/semantic_review.json', audit)
    lines = [
        '# 構造化後に共通概念辞書を作る方式の実験', '',
        '実施日：2026-09-14。仮想ノウハウ56件による統制実験。', '',
        '## 結論', '',
        '**構造化が意図どおりにできた場合、後から共通概念辞書を作る方式は、表現の違いを吸収しながら重要な意味の違いを保つ手段として有望です。** '
        'ただし、辞書だけでは表現形式の情報損失や構造化の揺れを解決できません。', '',
        '改訂辞書では、指定した一致候補19組をすべて検出し、区別すべき24組をすべて区別しました。'
        '**別枠の意味診断を含めると、45組中、正しい一致19・誤一致1・正しい不一致24・見逃し1です。** '
        'OTHERの意味が潰れる問題と、NOT／polarityの表現差が残っています。', '',
        '原文・グラフ・辞書・割当・期待ペアを同じAIアシスタントが作った実験です。'
        '外部LLM API呼び出しは0回で、構造化プロンプトの独立した自動抽出精度や、実データでの性能を測ったものではありません。'
        '構造テンプレートと共通のmeaning文により、正規化に有利な条件になっています。詳細は[実験の来歴](provenance.md)を参照してください。', '',
        '## 実験の構成', '',
        '| 区分 | 文書 | CLAIM関連の語彙ノード | 用途 |', '|---|---:|---:|---|',
        '| D01〜D24 | 24 | 51 | 初版辞書の概念定義用 |',
        '| D25〜D46 | 22 | 47 | 言い換え、否定、条件、未登録操作などの追加事例 |',
        '| D47〜D56 | 10 | 20 | modality/context、OTHER、同じsurfaceの多義性、対象の同一性、NOT、単位の診断 |', '',
        '追加事例はブラインドholdoutではありません。文書一覧は[仮想ノウハウ](corpus.md)、期待ペアは'
        '[evaluation_pairs.json](../data/evaluation_pairs.json)です。関係の有効性そのものは創作であり、実務上の効果を主張していません。', '',
        '## 1. 入力検査と語彙収集', '',
        f'- {validation["documents_passed"]}文書、{validation["nodes"]}ノード、{validation["relations"]}接続を検査し、形式違反は{validation["documents_failed"]}件でした。',
        f'- CLAIMは{validation["claim_nodes"]}個。CLAIMのないD24・D45・D46は原文とグラフを保存して比較から除外しました。',
        f'- CLAIMごとの語彙所属は{validation["claim_memberships_before_deduplication"]}件、document_id/node_idで重複を除くと{validation["unique_collected_nodes"]}ノードでした。',
        '- D19の確認ノードはREQUIRESとCAUSESの両方に所属しますが、語彙としては1行です。文字列の出現回数、ノード数、CLAIM所属数を別項目に記録しています。',
        '- 条件の下にある温度QUANTITYとそのBEARER、AND/OR/NOTの全MEMBERまで含めました。surfaceが原文の連続部分であることも検査しています。', '',
        '形式が正しいことは、原文の意味に忠実であることの証明ではありません。元グラフには根拠引用等を追加せず、原文台帳と後工程の文脈ファイルから確認できます。', '',
        '## 2. 辞書固定・正規化・改訂', '',
        '| 辞書 | 概念数 | 未登録ノード | null率（118ノード） | 探索可能な断片 |', '|---|---:|---:|---:|---:|',
    ]
    for version, name in [('v1', 'strict_v1'), ('v2', 'strict_v2')]:
        u, s = usage[version], results[name]['stats']
        lines.append(f'| {version} | {u["concept_count"]} | {u["null_nodes"]} | {u["null_rate"]:.2%} | {s["fragments_accepted"]}/{s["fragments_total"]} |')
    lines += ['',
        '初版は13概念。D43「校正する」とD44「標準値との対応を定める」は、測定・比較・適合確認のどれかに押し込まずnullにしました。'
        '追加事例47ノードだけでの初版null率は2/47＝4.26%です。二例をまとめて検討し、改訂版に校正A007を追加しました。'
        '既存13概念のID・定義は維持し、全118ノードについて保持／変更を確認し、2ノードの割当を変更しました。', '',
        'この改訂は追加事例を利用した開発結果です。改訂後のnull率0%は未知データでの網羅性を意味しません。'
        '各段階の辞書版、辞書と語彙のハッシュ、未登録時の文脈、分類理由、改訂理由を保存しています。', '',
        '## 3. 比較方式ごとの実測結果', '',
        '次の表は43統制ペア（一致19、不一致24）の結果です。保留は、不一致と決めつけず別に数えます。', '',
        '| 比較方式 | 探索断片 | 繰り返しパターン | 正しい一致 TP | 誤一致 FP | 正しい不一致 TN | 見逃し FN | 保留ペア |',
        '|---|---:|---:|---:|---:|---:|---:|---:|',
    ]
    names = {'surface': '対象語彙のsurface', 'strict_v1': '初版辞書・厳密', 'strict_v2': '改訂辞書・厳密',
             'no_concepts': '概念の区別を除去', 'no_conditions': '条件を除去', 'no_polarity': '否定を除去', 'no_units': '単位を除去'}
    for name, ev in evals.items():
        c, s = ev['counts'], results[name]['stats']
        lines.append(f'| {names[name]} | {s["fragments_accepted"]}/{s["fragments_total"]} | {s["recurring_patterns"]} | {c["tp"]} | {c["fp"]} | {c["tn"]} | {c["fn"]} | {c["abstained"]} |')
    lines += ['',
        'surface方式はACTION・QUANTITY・定性的STATEの比較キーだけをsurfaceにし、ENTITYの変数化と他の属性は同じにしています。'
        '概念の区別を除くと12組が誤一致し、条件を除くと3組、否定を除くと3組、単位を除くと1組が誤一致しました。'
        '頻度を増やすための乱暴な統合ではなく、意味の境界を持つ辞書が必要であることを示す統制結果です。', '',
        '**探索の母数が常に増えたわけではありません。** surface方式は最初から62断片を比較できます。'
        '辞書の主な効果は言い換えによる分断の解消であり、初版から改訂版への母数増加は未登録2断片の解消（60→62）です。', '',
        'OTHERとNOT／polarityの意味診断2組も含めた45ペアの結果は次のとおりです。可能性・推奨の2例は、仕様で一致を許しているため別の注意事項として扱います。', '',
        '| 方式 | TP | FP | TN | FN | 保留 |', '|---|---:|---:|---:|---:|---:|',
    ]
    for name, ev in evals.items():
        c = ev['including_semantic_diagnostics']['counts']
        lines.append(f'| {names[name]} | {c["tp"]} | {c["fp"]} | {c["tn"]} | {c["fn"]} | {c["abstained"]} |')
    lines += ['',
        'この45組も同じ作者が設定した少数の統制例です。一般的な精度の推定値や統計的な汎化性能として解釈しません。', '',
        '## 4. 検出した繰り返し構造を原文で確認', '',
        '最低支持文書数は2。以下は改訂辞書の繰り返しパターンすべてです。ノードと接続の対応表は'
        '[strict_v2.json](../results/strict_v2.json)、原文レビューは[semantic_review.json](../results/semantic_review.json)に保存しています。', '',
        '| ID | CLAIM数 | 構造の要約 | 支持文書数 | 出現数 | 文書 |', '|---|---:|---|---:|---:|---|',
    ]
    for a in audit:
        lines.append(f'| {a["pattern_id"]} | {a["claim_count"]} | {a["summary"]} | {a["support_count"]} | {a["occurrence_count"]} | {", ".join(a["documents"])} |')
    lines += ['',
        'P001は11文書・12出現です。D42には互いに独立した同型CLAIMが2つあり、支持文書数では1、出現数では2と数えています。'
        'P014・P015のような1CLAIMと上位の2CLAIMは重なり、P029は誤一致です。したがって13パターン＝13個の有効な独立原理ではありません。', '',
        '### 言い換えが一致した例', '',
        '> D01：部品を確認することが、組立作業の所要時間を減らす。', '>',
        '> D25：請求書を確かめることが、支払処理に実際にかかる時間を短縮する。', '',
        '操作はA001、量はQ001です。部品↔請求書、組立作業↔支払処理という二つのENTITYを一対一で対応させ、'
        'ACTION→TARGET、CHANGE→QUANTITY→BEARER、CAUSESのFROM/TOまで同型になります。対象の具体名が違うだけではconceptを分けません。', '',
        '### 同じsurfaceを区別した例', '',
        '> D51：二つの見積書について、差を確認することが、選定作業の所要時間を減らす。', '>',
        '> D52：見積書について、基準に合うか確認することが、選定作業の所要時間を減らす。', '',
        'ACTIONのsurfaceは両方「確認する」。surface方式では誤一致しました。文脈を読むとD51は比較A004、D52は適合確認A001であり、辞書方式では区別できました。', '',
        '## 5. 概念ごとの使用状況', '',
        '| ID | 名称 | ノード数 | 支持文書数 |', '|---|---|---:|---:|',
    ]
    for c in usage['v2']['concepts']:
        lines.append(f'| {c["id"]} | {c["name"]} | {c["node_count"]} | {c["document_count"]} |')
    lines += ['',
        '未使用概念は0、1ノードだけの概念はQ002・Q003・S003の3個です。意味的に異なるため、頻度を増やす目的で統合しません。'
        'ACTIONでは適合確認が29/53＝54.7%、QUANTITYでは実行所要時間が48/57＝84.2%を占めます。'
        'この偏りは、操作の境界を同じ時間減少の形で比較する実験設計によるものです。実データで同じ偏りが出るかは不明です。', '',
        '## 6. 残った失敗と仕様上の注意', '',
        '### OTHERで異なる変化が一致する', '',
        '> D49：装置の温度が変動することが、組立作業の所要時間を増やす。', '>',
        '> D50：装置の温度が一定になることが、組立作業の所要時間を増やす。', '',
        'CHANGEの比較ラベルがdirection=OTHERとpolarityだけなので、P029として一致します。'
        '概念IDを改善しても、この違いは復元されません。当面はOTHERを含む一致を原理候補として自動採用せず、'
        '別ファイルの監査対象にします。比較対象を広げるなら、将来の仕様としてCHANGEの意味を別途正規化する必要があります。今回のraw仕様は変更していません。', '',
        '### 否定の表現方法で一致を見逃す', '',
        'D33「確認しない」はACTION.polarity=NEGATIVE、D55「確認をしない」はNOT[肯定ACTION]と注釈しました。'
        '意味は近くてもノード数・接続が違い、厳密比較では一致しません。どちらも形式上は有効です。'
        '単一要素の否定はpolarityへ、論理のまとまりへの否定はNOTへ寄せる追補ルールが候補です。'
        'これは未実験の改善案であり、元の構造化プロンプトへ無断で反映していません。', '',
        '### 可能性・推奨・対象変数の意味は原文に戻る', '',
        'D47「減らすことがある」とD01の断定形、D48の推奨を含む原文はP001として一致します。'
        'ユーザー指定どおりmodality/contextを保持していないためです。D48は推奨の周辺記述の差の例であり、推奨と実施済みを独立評価した例ではありません。'
        'ENTITYの具体名・種類も比較していないので、対象の置換が実務上妥当かは別の確認が必要です。', '',
        '### 似ていても引数・単位が違えば不一致', '',
        '- D01とD40はAGENTの有無が違い、不一致です。引数をすべて含める設計では、主体が省略された事例と明示された事例は一致しにくくなります。',
        '- D01とD53は対象と量のBEARERの同一性が違います。二つのENTITYを一つに潰さず、不一致になります。',
        '- D01とD56はunit=nullと「分」が違います。推測や換算をしないため不一致です。',
        '- D19とD39はCAUSESだけなら一致しますが、REQUIRESの向きが逆なので2CLAIM断片は不一致です。部分一致を文書全体の同義性と解釈しません。',
        '- D45は防止目的だけなのでPREVENTSを作らず、D46は「AならB」だけなのでCAUSESを作りません。これらを辞書で比較可能にすることはできません。', '',
        '## 7. 次に検証すると判断が進むこと', '',
        '1. 実際の原文を用意し、構造化用モデルに01_structure.txtを独立したリクエストとして渡す。JSON形式成功率と意味の忠実度を分けて測る。',
        '2. 辞書作成用文書と未知文書を別にし、初版辞書を固定後に未知文書を初めて分類する。割当時に期待グループや探索結果を見せない。',
        '3. 一致・不一致・nullを別の評価者が原文で確認する。文書作成者と同じAIだけで正解を決めない。',
        '4. 単一否定の表現統一、OTHERの扱い、ACTIONの分割粒度、対象の共参照、欠落引数を優先して調べる。今回の構造テンプレートでは操作の分割揺れは十分に評価できていない。',
        '5. 辞書を改訂したら影響範囲のノードを再分類し、null率に加え、探索可能断片数、概念集中、原文上の誤一致、似た事例の見逃しを追う。', '',
        '## 実行と検証の記録', '',
        f'- Python {manifest["python_version"]}、{manifest["platform"]}。実行日時UTC：{manifest["run_utc"]}。',
        f'- {tests["tests_run"]}テスト、失敗{tests["failures"]}、エラー{tests["errors"]}。同型判定は独立した全順列判定と100組で一致。',
        f'- 改訂辞書の形式検査＋探索：{manifest["timings_seconds"]["strict_v2"]:.4f}秒。この56件の単回実行であり、LLM待ち時間、注釈作成、ファイルIOを含みません。大規模性能は未測定です。',
        '- 入力・プロンプト・コードのSHA-256：[run_manifest.json](../results/run_manifest.json)。テストの実出力：[test_output.txt](../results/test_output.txt)。',
        '- 再実行方法：[README](../README.md)。旧形式からの変更点：[provenance.md](provenance.md)。', '',
    ]
    (ROOT / 'docs/experiment_report.md').write_text('\n'.join(lines), encoding='utf-8')
    print('wrote docs/experiment_report.md and results/semantic_review.json')


if __name__ == '__main__':
    main()
