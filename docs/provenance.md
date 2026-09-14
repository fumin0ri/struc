# 既存実装との関係・実験の来歴

参照したリポジトリは [fumin0ri/structuring](https://github.com/fumin0ri/structuring)、確認したコミットは [`7491317bdb7479618bd02219deabc79399024642`](https://github.com/fumin0ri/structuring/tree/7491317bdb7479618bd02219deabc79399024642) です。

参照箇所は `experiment20/mine_patterns.py`、`experiment20/README.md`、既存の比較方式です。
本リポジトリの `src/pipeline.py` の候補署名・近傍集計・完全バックトラックによる同型判定は、この既存探索器をもとにしています。実験の原文・新形式の注釈・辞書・評価ペアは今回新しく作成しました。

## 変更点

| 処理 | 旧実装 | 今回 |
|---|---|---|
| 構造化JSON | evidence、辞書版、concept_id、modality、contextなどを含む | document_id / nodes / relationsのみ。型別の指定フィールドを厳密検査 |
| 語彙 | 構造化時のconcept_idを前提 | CLAIMの引数閉包から文脈付きで収集 |
| 正規化 | 既存core辞書と追加辞書 | 複数事例から作成した固定辞書を後付け。版・ハッシュで検査 |
| ENTITY | 名前等を保存し、比較では変数化 | 元のsurfaceを保持し、一対一の変数として比較 |
| ACTION | concept_idとscope | concept_id・polarity |
| QUANTITY | concept_id・dimension・unit | concept_id・unit |
| 定性的STATE | concept_id等 | concept_id・polarity。formも保持 |
| 比較STATE | comparator・value・value_unit等 | SUBJECTの構造・comparator・value・value_unit・polarity |
| CHANGE / CLAIM / LOGIC | 属性とscope等 | direction/predicate/operatorと該当型のpolarity |
| 比較保留 | 未登録概念、未解決のqualifier、scope、OTHER等 | 必須概念がnullの断片を保留。OTHERは指定された比較規則どおり一致し得るため外部監査で問題を示す |
| 集計 | 文書支持数と出現数 | 同じ方針を保持。ノード・接続対応表と原文へのリンク情報を保存 |

旧データを新形式へ機械的に変換して精度比較した実験ではありません。旧方式の数値と今回の数値を直接比較できません。

## 誰が何を作ったか

2026-09-14のこのタスクで、現在のAIアシスタントが原文、構造化注釈、概念定義、割当判断、期待ペア、原文上のレビューを作成しました。
`build_fixture.py` は指定した注釈のJSONを組み立てる補助コードです。日本語を自動解析する抽出器ではありません。
`freeze_annotations.py` は保存した分類判断をJSONへ展開するコードです。実行時に意味を推論したりモデルに問い合わせたりしません。

したがって、保存されているのは**アシスタント作成の統制注釈と、その後段の実行結果**です。外部LLM APIを56回呼び出した実験、独立したモデルによる抽出・辞書生成・再分類、複数seedによる再現性試験ではありません。API呼び出し数は0です。モデルの生レスポンス、token数、sampling設定を取得したという主張もしません。

初版辞書の該当例はD01〜D24の51語彙ノードから作成しています。しかし、原文・辞書・注釈を同じ作者が同じ会話で設計しており、D25以降は**追加事例**であって、情報が遮断されたブラインドholdoutではありません。共通のmeaning文、整った構造テンプレートにより、正規化に有利な条件になっています。

初版辞書に校正はなく、D43・D44をnullにしました。両例を見直して校正A007を追加し、全118ノードについて保持／変更の判断を保存しました。既存の13概念のIDと定義は変えていません。

`prompts/01_structure.txt` はユーザー提示の構造化プロンプトを保存したものです。Markdownのエスケープを通常のフィールド表記へ戻し、改行を整えています。02〜05は今回作成した後工程用プロンプトです。この一連のプロンプトを隔離したAPIリクエストとして実行したという意味ではありません。

## 再現できる範囲

保存済みJSONを入力にした入力検査、文脈収集、辞書と割当の整合性検査、正規化、断片列挙、完全同型判定、集計、指定ペアの採点、レポート生成を再実行できます。

原文から同じJSONを得られる確率、自由な原文に対するLLMの構造化精度、辞書の自動誘導品質、割当の安定性、実際のノウハウへの有効性は、この再実行では検証できません。
