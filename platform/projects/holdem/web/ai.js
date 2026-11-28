/* KittenPuppy4Ever · 德州扑克 AI
 *
 * 输入只有 Game.aiView(seat)：自己的手牌、公共牌、底池、公开下注、公开行动历史、人数。
 * 绝不接收其他玩家的手牌或牌堆；equity 用未知牌随机模拟，属于合法信息。
 *
 * 每个 AI 对每个对手维护 52×52 上三角的具体两张牌组合概率矩阵：
 *   - 有效格子 C(52,2)=1326；
 *   - 每格是 P(对手恰好持有这两张牌 | 已知牌 + 公开行动)；
 *   - 花色、blocker、同花听牌都进入更新和抽样。
 *
 * 难度对应“思考深度”：
 *   easy   depth 0：维护矩阵，但使用随机对手范围
 *   medium depth 1：使用翻前范围矩阵
 *   hard   depth 2：加入翻后范围、加注历史、筹码深度
 *   hell   depth 3：更强历史修正、更多模拟
 */
(function () {
  const RANKS = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"];
  const RANK_INDEX = {};
  RANKS.forEach((r, i) => { RANK_INDEX[r] = i; });
  const RANK_VALUE = RANKS.map((_, i) => i + 2);
  const SUITS = ["s", "h", "d", "c"];
  const ITERATIONS = { easy: 16, medium: 120, hard: 480, hell: 1600 };
  const DEPTH = { easy: 0, medium: 1, hard: 2, hell: 3 };
  const RANGE_STATE = new Map();
  const STRENGTH_CACHE = new Map();
  const LEARNING_STATE = new Map();

  function makeDeck() {
    const out = [];
    for (const s of SUITS) for (const r of RANKS) out.push({ r, v: RANK_VALUE[RANK_INDEX[r]], s });
    return out;
  }
  function key(c) { return c.r + c.s; }
  function shuffle(a) {
    for (let i = a.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [a[i], a[j]] = [a[j], a[i]];
    }
    return a;
  }
  const clamp = (x, lo, hi) => Math.max(lo, Math.min(hi, x));

  // 52×52 上三角：只保存具体两张牌的有效组合。
  const CARD_DECK = makeDeck();
  const COMBOS = [];
  const COMBO_BY_KEY = new Map();
  for (let i = 0; i < CARD_DECK.length; i++) {
    for (let j = i + 1; j < CARD_DECK.length; j++) {
      const combo = { a: CARD_DECK[i], b: CARD_DECK[j], k: COMBOS.length };
      COMBOS.push(combo);
      COMBO_BY_KEY.set(key(combo.a) + "|" + key(combo.b), combo.k);
    }
  }

  function preflopStrength(hole) {
    if (!hole || hole.length !== 2) return 0;
    const hi = Math.max(hole[0].v, hole[1].v);
    const lo = Math.min(hole[0].v, hole[1].v);
    const pair = hi === lo;
    const suited = hole[0].s === hole[1].s;
    let s = (hi + lo) / 28 * 0.55;
    if (pair) s += 0.40;
    else if (suited) s += 0.08;
    const gap = hi - lo;
    if (gap <= 1) s += 0.06;
    else if (gap <= 2) s += 0.03;
    return clamp(s, 0, 1);
  }

  function postflopStrength(hole, board) {
    if (!hole || hole.length !== 2) return 0;
    if (!board || board.length < 3) return preflopStrength(hole);
    const made = Holdem.bestHand(hole.concat(board));
    let s = made ? made.cat / 8 : 0;
    const suit = {};
    hole.concat(board).forEach((c) => { suit[c.s] = (suit[c.s] || 0) + 1; });
    if (Math.max(0, ...Object.values(suit)) >= 4) s += 0.12;
    const vals = [...new Set(hole.concat(board).map((c) => c.v))].sort((a, b) => a - b);
    for (let i = 0; i + 3 < vals.length; i++) {
      if (vals[i + 3] - vals[i] <= 4) { s += 0.07; break; }
    }
    return clamp(s, 0, 1);
  }

  function boardKey(board) {
    return board && board.length ? board.map(key).sort().join("|") : "preflop";
  }
  // 同一公共牌下 1326 个组合的强度只计算一次，后续行动更新直接查表。
  function strengthTable(board) {
    const bk = boardKey(board);
    let table = STRENGTH_CACHE.get(bk);
    if (table) return table;
    table = new Float32Array(COMBOS.length);
    for (const c of COMBOS) {
      table[c.k] = board && board.length >= 3
        ? postflopStrength([c.a, c.b], board)
        : preflopStrength([c.a, c.b]);
    }
    STRENGTH_CACHE.set(bk, table);
    if (STRENGTH_CACHE.size > 128) STRENGTH_CACHE.delete(STRENGTH_CACHE.keys().next().value);
    return table;
  }
  function actionLikelihood(type, strength, depth) {
    const sharp = 1 + depth * 0.24;
    if (type === "raise") return 0.04 + 0.96 * Math.pow(strength, sharp);
    if (type === "call") return 0.12 + 0.88 * strength;
    if (type === "check") return 0.90 - 0.45 * strength;
    if (type === "fold") return Math.max(0.02, 1 - strength);
    return 1;
  }

  function learningState(view) {
    const k = view.gameId + ":" + view.seat;
    let st = LEARNING_STATE.get(k);
    if (!st) {
      st = { global: {}, byOpp: {}, lastHand: 0 };
      LEARNING_STATE.set(k, st);
      if (LEARNING_STATE.size > 80) LEARNING_STATE.delete(LEARNING_STATE.keys().next().value);
    }
    return st;
  }
  function learnBucket(strength) {
    return Math.max(0, Math.min(9, Math.floor(strength * 10)));
  }
  function learnKey(street, action, bucket, facing, raises) {
    return street + "|" + action + "|" + bucket + "|" + facing + "|" + Math.min(2, raises || 0);
  }
  function learnInc(table, key, action) {
    if (!table[key]) table[key] = { fold: 0, check: 0, call: 0, raise: 0, total: 0 };
    table[key][action] = (table[key][action] || 0) + 1;
    table[key].total += 1;
  }
  // 轻量在线训练：只使用摊牌后公开的手牌，学习“手牌强度 → 行动”的似然。
  function processShowdown(view, learn) {
    const sd = view.lastShowdown;
    if (!sd || !sd.hands || sd.handNo === learn.lastHand) return;
    for (const h of sd.hands) {
      if (!h.hole || h.hole.length !== 2) continue;
      const oppTable = learn.byOpp[h.seat] || (learn.byOpp[h.seat] = {});
      for (const a of sd.history || []) {
        if (a.seat !== h.seat || a.type === "blind" || a.type === "fold") continue;
        const street = a.street === "preflop" ? "pre" : "post";
        const board = street === "pre" ? [] : (sd.board || []).slice(0, a.boardLength || 0);
        const strength = street === "pre" ? preflopStrength(h.hole) : postflopStrength(h.hole, board);
        const bucket = learnBucket(strength);
        const facing = (a.toCallBefore || 0) > 0 ? 1 : 0;
        const key = learnKey(street, a.type, bucket, facing, a.raisesBefore || 0);
        learnInc(learn.global, key, a.type);
        learnInc(oppTable, key, a.type);
      }
    }
    learn.lastHand = sd.handNo;
  }
  function learnedProb(table, street, action, strength, facing, raises, depth) {
    if (!table || depth < 1) return null;
    const bucket = learnBucket(strength);
    const key = learnKey(street, action, bucket, facing, raises || 0);
    const row = table[key];
    if (!row || row.total < 6) return null;
    const alpha = 0.8;
    const p = ((row[action] || 0) + alpha) / (row.total + 4 * alpha);
    const trust = Math.min(0.70, row.total / 70);
    return { p, trust, samples: row.total };
  }
  function actionContextFactor(action, view, depth) {
    if (depth < 2) return 1;
    let f = 1;
    const pot = Math.max(1, Number(action.potBefore) || view.pot || view.bb);
    const size = Math.max(0, Number(action.amount) || 0);
    if (action.type === "raise") {
      const ratio = size / pot;
      f *= clamp(0.62 + 0.72 * Math.min(ratio, 2.2), 0.50, 2.10);
    } else if (action.type === "call") {
      const ratio = size / pot;
      f *= clamp(0.82 + 0.42 * Math.min(ratio, 2.0), 0.72, 1.55);
    }
    if (depth >= 3) {
      const n = view.players.length || 6;
      const rel = (action.seat - view.dealer + n) % n;
      const late = rel >= Math.ceil(n / 2);
      if (action.type === "raise" && !late) f *= 1.10;
      if (action.type === "call" && late) f *= 0.95;
      if ((action.raisesBefore || 0) >= 1 && action.type === "raise") f *= 1.14;
      if ((action.raisesBefore || 0) >= 2 && action.type === "call") f *= 0.95;
    }
    return f;
  }
  function makePriorMatrix(view, targetSeat) {
    if (targetSeat !== undefined && window.HoldemRangePrior) {
      try {
        const p = window.HoldemRangePrior.prior(view, targetSeat);
        if (p && p.length === COMBOS.length) return p;
      } catch (e) {}
    }
    const matrix = new Float64Array(COMBOS.length);
    const known = new Set(view.hole.concat(view.board).map(key));
    let total = 0;
    for (const c of COMBOS) {
      if (known.has(key(c.a)) || known.has(key(c.b))) continue;
      matrix[c.k] = 1;
      total += 1;
    }
    if (!total) {
      matrix.fill(1);
      total = COMBOS.length;
    }
    for (let i = 0; i < matrix.length; i++) matrix[i] /= total;
    return matrix;
  }

  function normalizeMatrix(matrix) {
    let total = 0;
    for (let i = 0; i < matrix.length; i++) total += matrix[i];
    if (!total) return matrix;
    for (let i = 0; i < matrix.length; i++) matrix[i] /= total;
    return matrix;
  }

  function updateMatrix(matrix, action, view, depth) {
    const board = action.street === "preflop" ? [] : view.board;
    const table = strengthTable(board);
    const context = actionContextFactor(action, view, depth);
    const learn = learningState(view);
    const street = action.street === "preflop" ? "pre" : "post";
    const facing = (action.toCallBefore || 0) > 0 ? 1 : 0;
    const raises = action.raisesBefore || 0;
    const oppTable = depth >= 3 ? (learn.byOpp[action.seat] || null) : null;
    const globalTable = learn.global;
    for (const c of COMBOS) {
      const p = matrix[c.k];
      if (p <= 0) continue;
      let like = actionLikelihood(action.type, table[c.k], depth);
      if (depth >= 1) {
        const g = learnedProb(globalTable, street, action.type, table[c.k], facing, raises, depth);
        const l = oppTable ? learnedProb(oppTable, street, action.type, table[c.k], facing, raises, depth) : null;
        let use = g;
        if (l) {
          const w = Math.min(0.60, l.samples / 30);
          const base = g || { p: 0.25, trust: 0 };
          use = {
            p: l.p * w + base.p * (1 - w),
            trust: Math.max(l.trust, base.trust),
            samples: (l.samples || 0) + (base.samples || 0),
          };
        }
        if (use) like = like * (1 - use.trust * 0.58) + use.p * (use.trust * 0.58);
      }
      matrix[c.k] = p * like * context;
    }
    return normalizeMatrix(matrix);
  }

  function rangeState(view) {
    const stateKey = view.gameId + ":" + view.handNo + ":" + view.seat;
    let state = RANGE_STATE.get(stateKey);
    if (!state) {
      state = { matrices: view.players.map(() => null), last: 0 };
      RANGE_STATE.set(stateKey, state);
      if (RANGE_STATE.size > 120) RANGE_STATE.delete(RANGE_STATE.keys().next().value);
    }
    const depth = DEPTH[view.difficulty] || 0;
    const learn = learningState(view);
    processShowdown(view, learn);
    for (let k = state.last; k < view.history.length; k++) {
      const a = view.history[k];
      if (!a || a.seat === view.seat || a.type === "blind") continue;
      // 简单 AI 只保留先验；中等只用翻前信息；困难/地狱才使用翻后行动。
      if (depth <= 0) continue;
      if (depth === 1 && a.street !== "preflop") continue;
      if (!state.matrices[a.seat]) state.matrices[a.seat] = makePriorMatrix(view, a.seat);
      updateMatrix(state.matrices[a.seat], a, view, depth);
    }
    state.last = view.history.length;
    return state;
  }

  function matrixFor(state, view, seat) {
    return state.matrices[seat] || (state.matrices[seat] = makePriorMatrix(view, seat));
  }

  function matrixMean(matrix, view) {
    const table = strengthTable(view.board && view.board.length >= 3 ? view.board : []);
    let total = 0, sum = 0;
    for (const c of COMBOS) {
      const p = matrix[c.k];
      if (p <= 0) continue;
      total += p;
      sum += p * table[c.k];
    }
    return total ? sum / total : 0;
  }

  function buildCells(matrix) {
    const cells = [];
    for (const c of COMBOS) {
      if (matrix[c.k] > 0) cells.push({ k: c.k, a: c.a, b: c.b, p: matrix[c.k] });
    }
    return cells;
  }

  function takeRandom(deck) {
    return [deck.pop(), deck.pop()];
  }

  function sampleRangeHole(deck, cells) {
    if (!cells || !cells.length) return takeRandom(deck);
    const total = cells.reduce((s, c) => s + c.p, 0);
    for (let attempt = 0; attempt < 18; attempt++) {
      let r = Math.random() * total, chosen = cells[cells.length - 1];
      for (const c of cells) { r -= c.p; if (r <= 0) { chosen = c; break; } }
      const ia = deck.findIndex((c) => key(c) === key(chosen.a));
      const ib = deck.findIndex((c) => key(c) === key(chosen.b));
      if (ia < 0 || ib < 0 || ia === ib) continue;
      const a = deck[ia], b = deck[ib];
      [ia, ib].sort((x, y) => y - x).forEach((idx) => deck.splice(idx, 1));
      return [a, b];
    }
    return takeRandom(deck);
  }

  function rangePressure(view, state, depth) {
    if (depth <= 0) return 0;
    const opps = view.players.filter((p) => p.seat !== view.seat && !p.folded);
    if (!opps.length) return 0;
    let sum = 0;
    for (const o of opps) sum += matrixMean(matrixFor(state, view, o.seat), view);
    return sum / opps.length;
  }

  function equity(view, iterations, depth, state) {
    const known = new Set(view.hole.concat(view.board).map(key));
    const base = makeDeck().filter((c) => !known.has(key(c)));
    const opponents = view.players.filter((p) => p.seat !== view.seat && !p.folded);
    if (!opponents.length) return { equity: 1, rangePressure: 0 };
    const useRange = depth >= 1;
    const cells = useRange ? opponents.map((o) => buildCells(matrixFor(state, view, o.seat))) : null;
    const rangeP = useRange ? rangePressure(view, state, depth) : 0;
    let score = 0;
    for (let it = 0; it < iterations; it++) {
      const deck = base.slice();
      shuffle(deck);
      const oppHands = opponents.map((o, idx) => useRange ? sampleRangeHole(deck, cells[idx]) : takeRandom(deck));
      const board = view.board.slice();
      while (board.length < 5) board.push(deck.pop());
      const mine = Holdem.bestHand(view.hole.concat(board));
      let best = mine, tie = false;
      for (const h of oppHands) {
        const other = Holdem.bestHand(h.concat(board));
        const cmp = Holdem.compareRank(other, best);
        if (cmp > 0) { best = other; tie = false; }
        else if (cmp === 0) tie = true;
      }
      if (best === mine && !tie) score += 1;
      else if (tie && Holdem.compareRank(mine, best) === 0) score += 0.5;
    }
    return { equity: score / Math.max(1, iterations), rangePressure: rangeP };
  }

  function canRaise(view) {
    return view.maxRaiseTo > view.currentBet && view.maxRaiseTo >= view.minRaiseTo;
  }
  function raiseTo(view, fraction) {
    let target = Math.max(view.minRaiseTo, view.currentBet + Math.max(view.minRaise, Math.round(view.pot * fraction)));
    target = Math.round(target / 10) * 10;
    return Math.min(view.maxRaiseTo, target);
  }
  function actRaise(view, fraction) {
    return { type: "raise", amount: raiseTo(view, fraction) };
  }

  function decide(view) {
    if (!view || !view.hole || view.hole.length !== 2) return { type: "check" };
    const diff = view.difficulty || "medium";
    const depth = DEPTH[diff] || 0;
    const iters = ITERATIONS[diff] || ITERATIONS.medium;
    const state = rangeState(view);
    const ev = equity(view, iters, depth, state);
    const eq = ev.equity;
    const rangeP = ev.rangePressure;
    const toCall = view.toCall || 0;
    const pot = Math.max(view.pot, view.bb);
    const potOdds = toCall > 0 ? toCall / (pot + toCall) : 0;
    const opponents = Math.max(1, view.players.filter((p) => p.seat !== view.seat && !p.folded).length);
    const rel = eq * (opponents + 1);
    const canBet = canRaise(view);
    const stack = Math.max(0, view.stack || 0);
    const spr = stack / Math.max(1, pot);
    const raises = view.raisesThisStreet || 0;
    const shortStack = stack <= Math.max(view.bb * 8, pot * 0.6);
    const allInCall = toCall >= stack;
    const profile = {
      easy:   { fold: 0.36, raise: 1.62, bluff: 0.10, call: 0.18 },
      medium: { fold: 0.50, raise: 1.38, bluff: 0.08, call: 0.10 },
      hard:   { fold: 0.62, raise: 1.22, bluff: 0.07, call: 0.05 },
      hell:   { fold: 0.70, raise: 1.10, bluff: 0.06, call: 0.02 },
    }[diff] || { fold: 0.50, raise: 1.38, bluff: 0.08, call: 0.10 };

    const raiseThreshold = profile.raise + Math.min(0.42, raises * 0.09) + rangeP * 0.22;
    const raiseChance = Math.max(0.12, 0.72 - raises * 0.14 - (depth >= 2 ? 0.04 : 0) - rangeP * 0.18);
    const foldLine = profile.fold + rangeP * 0.10;

    if (toCall > 0 && !allInCall && rel < foldLine && eq < Math.max(0.10, potOdds - profile.call)) {
      if (diff === "easy" && Math.random() < 0.30) return { type: "call" };
      return { type: "fold" };
    }

    if (canBet && rel > raiseThreshold && Math.random() < raiseChance) {
      if (toCall >= stack * 0.65 && stack > 0) {
        if (rel < raiseThreshold + 0.30) return { type: "call" };
      }
      let fraction = diff === "easy" ? 0.30 : diff === "medium" ? 0.50 : 0.68;
      if (spr < 1.2) fraction = 1.0;
      else if (spr < 2) fraction = Math.max(fraction, 0.75);
      if (raises >= 1) fraction = Math.min(fraction, 0.45);
      if (shortStack) fraction = Math.min(fraction, 0.65);
      return actRaise(view, fraction);
    }

    if (toCall > 0) {
      if (allInCall) return { type: "call" };
      if (rel >= foldLine || eq >= potOdds - profile.call) return { type: "call" };
      if (Math.random() < Math.max(0.02, profile.bluff - rangeP * 0.03)) return { type: "call" };
      return { type: "fold" };
    }

    if (canBet && (rel > raiseThreshold * 0.92 || Math.random() < Math.max(0.02, profile.bluff - rangeP * 0.03))) {
      let fraction = diff === "hell" ? 0.55 : 0.42;
      if (spr < 1.2) fraction = 1.0;
      if (shortStack) fraction = Math.min(fraction, 0.65);
      return actRaise(view, fraction);
    }
    return { type: "check" };
  }

  // 给可视化/调试用：把 1326 个具体组合聚合回 13×13 rank-pair 矩阵。
  function debugRange(view, opponentSeat) {
    const state = rangeState(view);
    const matrix = matrixFor(state, view, opponentSeat);
    const out = Array.from({ length: 13 }, () => new Array(13).fill(0));
    for (const c of COMBOS) {
      const p = matrix[c.k];
      if (p <= 0) continue;
      const i = RANK_INDEX[c.a.r], j = RANK_INDEX[c.b.r];
      const lo = Math.min(i, j), hi = Math.max(i, j);
      out[lo][hi] += p;
    }
    return out;
  }
  function debugRange52(view, opponentSeat) {
    const state = rangeState(view);
    return Array.from(matrixFor(state, view, opponentSeat));
  }

  function comboIndexOf(cardA, cardB) {
    const ka = key(cardA), kb = key(cardB);
    const k = COMBO_BY_KEY.get(ka + "|" + kb);
    return k === undefined ? COMBO_BY_KEY.get(kb + "|" + ka) : k;
  }
  function debugComboRank(view, opponentSeat, cardA, cardB) {
    const state = rangeState(view);
    const matrix = matrixFor(state, view, opponentSeat);
    const k = comboIndexOf(cardA, cardB);
    if (k === undefined) return { probability: 0, rank: matrix.length, percentile: 0 };
    const p = matrix[k];
    let above = 0;
    for (let i = 0; i < matrix.length; i++) if (matrix[i] > p) above++;
    return { probability: p, rank: above + 1, percentile: 1 - above / (matrix.length - 1) };
  }
  function debugComboProb(view, opponentSeat, cardA, cardB) {
    const state = rangeState(view);
    const matrix = matrixFor(state, view, opponentSeat);
    const ka = key(cardA), kb = key(cardB);
    const k = COMBO_BY_KEY.get(ka + "|" + kb) !== undefined
      ? COMBO_BY_KEY.get(ka + "|" + kb)
      : COMBO_BY_KEY.get(kb + "|" + ka);
    return k === undefined ? 0 : matrix[k];
  }

  window.HoldemAI = {
    decide, equity, ITERATIONS, DEPTH, preflopStrength, postflopStrength,
    debugRange, debugRange52, debugComboProb, debugComboRank, COMBO_COUNT: COMBOS.length, strengthTable,
  };
})();
