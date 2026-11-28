# Holdem 范围模型预训练

这条流水线用于预训练对手范围信念模型，并把小模型导出到浏览器。

## 1. 生成自对弈数据

```bash
cd platform/projects/holdem
node training/generate_selfplay.js --hands=3000 --out=training/data/selfplay.jsonl --fast=false
```

- 训练数据允许看到所有玩家手牌，用于生成标签；
- 运行时绝不读取这些标签；
- `--fast=false` 使用完整 AI 搜索；小规模冒烟测试可用默认 `--fast`。

## 2. Torch 训练

```bash
python training/train_range_model.py \
  --data training/data/selfplay.jsonl \
  --out training/out \
  --epochs=20 \
  --hidden=128 \
  --label-mode=rankpair
```

当前模型输出 91 个 rank-pair 类；运行时再展开成 52×52 / 1326 具体组合。
花色级别的后验仍由 `ai.js` 的在线 52×52 贝叶斯矩阵负责。

## 3. 导出到浏览器

训练脚本会生成：

```text
training/out/range-model.js
```

复制到：

```text
web/range-model.js
```

页面已经按以下顺序加载：

```text
engine.js
range-model.js
range-model-runtime.js
ai.js
```

## 4. 运行时

- 简单/中等：不加载预训练先验；
- 困难/地狱：预训练模型先验 + 在线 52×52 贝叶斯矩阵；
- 在线矩阵继续根据公开行动和摊牌更新，作为轻量微调层；
- 预训练权重在浏览器中只做前向推理，不反传。

## 5. 数据规模与质量

当前仓库内包含一个 300 手牌的冒烟模型，只用于验证流水线。

要得到真正更强的模型，建议：

- 至少 10 万～50 万决策；
- 包含不同人数、规则、筹码深度；
- 保留独立验证集；
- 用验证 log loss / Top-K 选择模型；
- 再导出到 `web/range-model.js`。
