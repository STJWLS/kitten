/* 预训练范围先验的浏览器推理与特征提取。
 * 模型输出 91 个 rank-pair 概率；运行时再展开到 52×52 的具体组合矩阵。
 * 训练使用 Python，运行时只做前向；在线微调由 ai.js 的贝叶斯矩阵负责。
 */
(function () {
  const SUITS = ["s", "h", "d", "c"];
  const RANKS = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"];
  const CARD_INDEX = {};
  for (let si = 0; si < SUITS.length; si++) for (let ri = 0; ri < RANKS.length; ri++) CARD_INDEX[SUITS[si] + RANKS[ri]] = si * 13 + ri;
  const RANK_INDEX = {}; RANKS.forEach((r, i) => { RANK_INDEX[r] = i; });
  const PAIR_INDEX = Array.from({ length: 13 }, () => new Array(13).fill(-1));
  let pi = 0;
  for (let i = 0; i < 13; i++) for (let j = i; j < 13; j++) PAIR_INDEX[i][j] = pi++;
  const DIFFS = ["easy", "medium", "hard", "hell"];
  const STREETS = ["preflop", "flop", "turn", "river"];
  const ACTIONS = ["fold", "check", "call", "raise"];
  const RULES = ["nolimit", "potlimit", "fixedlimit"];
  const PRIOR_CACHE = new Map();
  const clip = (x, lo, hi) => Math.max(lo, Math.min(hi, x));

  function cardIdx(c) { return CARD_INDEX[c.s + c.r]; }

  function featurize(view, targetSeat) {
    const f = [];
    for (const c of view.hole) { const v = new Array(52).fill(0); v[cardIdx(c)] = 1; f.push(...v); }
    const board = view.board || [];
    for (let i = 0; i < 5; i++) { const v = new Array(52).fill(0); if (i < board.length) v[cardIdx(board[i])] = 1; f.push(...v); }
    const target = view.players.find((p) => p.seat === targetSeat) || {};
    for (const d of DIFFS) f.push(view.difficulty === d ? 1 : 0);
    for (const d of DIFFS) f.push(target.difficulty === d ? 1 : 0);
    for (const s of STREETS) f.push(view.street === s ? 1 : 0);
    const th = (view.history || []).filter((a) => a.seat === targetSeat && a.type !== "blind");
    const total = Math.max(1, th.length);
    const count = (arr, type) => arr.filter((a) => a.type === type).length;
    for (const a of ACTIONS) f.push(count(th, a) / total);
    const pre = th.filter((a) => a.street === "preflop");
    const post = th.filter((a) => a.street !== "preflop");
    const pt = Math.max(1, pre.length), qt = Math.max(1, post.length);
    for (const a of ACTIONS) f.push(count(pre, a) / pt);
    for (const a of ACTIONS) f.push(count(post, a) / qt);
    const last = th.length ? th[th.length - 1].type : "";
    for (const a of ACTIONS) f.push(last === a ? 1 : 0);
    f.push(Math.min(1, th.length / 10));
    const pot = Math.max(1, view.pot || 0);
    const amountSum = th.reduce((s, a) => s + (Number(a.amount) || 0), 0);
    f.push(clip(amountSum / pot, 0, 3));
    f.push(clip((th.length ? (Number(th[th.length - 1].amount) || 0) : 0) / pot, 0, 3));
    const bb = Math.max(1, view.bb || 20);
    const n = Math.max(6, view.players.length || 6);
    const active = view.players.filter((p) => !p.folded).length;
    f.push(clip(pot / bb / 20, 0, 3));
    f.push(clip((view.currentBet || 0) / bb / 10, 0, 3));
    f.push(clip((view.toCall || 0) / bb / 10, 0, 3));
    f.push(clip((view.stack || 0) / bb / 30, 0, 3));
    f.push(clip((target.stack || 0) / bb / 30, 0, 3));
    f.push(clip((view.bet || 0) / bb / 10, 0, 3));
    f.push(clip((target.bet || 0) / bb / 10, 0, 3));
    f.push(active / n);
    f.push(Math.min(1, (view.raisesThisStreet || 0) / 4));
    f.push(((view.seat - view.dealer + n) % n) / n);
    f.push(((targetSeat - view.dealer + n) % n) / n);
    f.push(board.length / 5);
    f.push(n / 10);
    for (const r of RULES) f.push(view.betRule === r ? 1 : 0);
    f.push(0); // training 数据中 target.allIn 未记录
    f.push(0); // training 数据中 observer.allIn 未记录
    return new Float32Array(f);
  }

  function softmax(logits) {
    let max = -Infinity;
    for (let i = 0; i < logits.length; i++) if (logits[i] > max) max = logits[i];
    let sum = 0; const out = new Float32Array(logits.length);
    for (let i = 0; i < logits.length; i++) { out[i] = Math.exp(logits[i] - max); sum += out[i]; }
    for (let i = 0; i < out.length; i++) out[i] /= sum;
    return out;
  }

  function expandRankPairPrior(view, targetSeat, pairProbs) {
    const matrix = new Float64Array(1326);
    const known = new Set(view.hole.concat(view.board || []).map((c) => c.s + c.r));
    let total = 0;
    // 内部顺序与训练 combo 顺序一致：s,h,d,c × 2..A
    const deck = [];
    for (const s of SUITS) for (const r of RANKS) deck.push({ s, r });
    for (let i = 0; i < 52; i++) {
      for (let j = i + 1; j < 52; j++) {
        const a = deck[i], b = deck[j];
        if (known.has(a.s + a.r) || known.has(b.s + b.r)) continue;
        const ia = RANK_INDEX[a.r], ib = RANK_INDEX[b.r];
        const lo = Math.min(ia, ib), hi = Math.max(ia, ib);
        const p = pairProbs[PAIR_INDEX[lo][hi]] || 0;
        matrix[matrixIndex(i, j)] = p;
        total += p;
      }
    }
    if (total > 0) for (let i = 0; i < matrix.length; i++) matrix[i] /= total;
    return matrix;
  }
  function matrixIndex(i, j) { return i * (103 - i) / 2 + (j - i - 1); }

  function modelPrior(view, targetSeat) {
    if (!window.HoldemRangeModel || !window.HOLDEM_RANGE_MODEL) return null;
    const depth = { easy: 0, medium: 1, hard: 2, hell: 3 }[view.difficulty] || 0;
    if (depth < 2) return null;
    const key = view.gameId + ":" + view.handNo + ":" + view.seat + ":" + targetSeat + ":" + view.street + ":" + (view.history || []).length;
    if (PRIOR_CACHE.has(key)) return PRIOR_CACHE.get(key).slice();
    const f = featurize(view, targetSeat);
    if (f.length !== window.HOLDEM_RANGE_MODEL.inputDim) return null;
    const logits = window.HoldemRangeModel.predict(f);
    const pairProbs = softmax(logits);
    const prior = expandRankPairPrior(view, targetSeat, pairProbs);
    // 与均匀先验混合，避免预训练模型过度自信。
    const known = new Set(view.hole.concat(view.board || []).map((c) => c.s + c.r));
    const deck = [];
    for (const s of SUITS) for (const r of RANKS) deck.push({ s, r });
    let valid = 0;
    for (let i = 0; i < 52; i++) for (let j = i + 1; j < 52; j++) if (!known.has(deck[i].s + deck[i].r) && !known.has(deck[j].s + deck[j].r)) valid++;
    const w = view.difficulty === "hell" ? 0.62 : 0.50;
    let total = 0;
    for (let i = 0; i < prior.length; i++) {
      prior[i] = prior[i] * w + (valid ? (1 - w) / valid : 0);
      total += prior[i];
    }
    if (total > 0) for (let i = 0; i < prior.length; i++) prior[i] /= total;
    PRIOR_CACHE.set(key, prior);
    if (PRIOR_CACHE.size > 300) PRIOR_CACHE.delete(PRIOR_CACHE.keys().next().value);
    return prior.slice();
  }

  window.HoldemRangePrior = { prior: modelPrior, featurize };
})();
