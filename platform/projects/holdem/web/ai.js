/* KittenPuppy4Ever · 德州扑克 AI
 *
 * 输入只有 Game.aiView(seat)：自己的手牌、公共牌、底池、公开下注、公开行动历史、人数。
 * 绝不接收其他玩家的手牌或牌堆；equity 用未知牌随机模拟，属于合法信息。
 *
 * 每个 AI 对每个对手维护一个 13×13 上三角手牌概率矩阵（91 个 rank-pair 类别）：
 *   - 初始按剩余牌组合数作为先验；
 *   - 根据对手公开行动做贝叶斯更新；
 *   - 用范围概率抽样对手手牌，并影响自己的下注策略。
 *
 * 难度对应“思考深度”：
 *   easy   depth 0：随机对手范围，维护矩阵但不使用历史范围
 *   medium depth 1：使用翻前范围矩阵
 *   hard   depth 2：加入翻后范围、加注历史、筹码深度
 *   hell   depth 3：更窄的范围、更强的历史修正与更多模拟
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

  function classHole(i, j, suited) {
    const hi = Math.max(i, j), lo = Math.min(i, j);
    if (hi === lo) return [{ r: RANKS[hi], v: RANK_VALUE[hi], s: "s" }, { r: RANKS[hi], v: RANK_VALUE[hi], s: "h" }];
    return [{ r: RANKS[hi], v: RANK_VALUE[hi], s: "s" }, { r: RANKS[lo], v: RANK_VALUE[lo], s: suited ? "s" : "h" }];
  }
  // 矩阵格子的代表手牌强度：不区分具体花色组合，取 suited/offsuit 平均。
  function classStrength(i, j, board) {
    if (i === j) {
      const pair = classHole(i, i, false);
      return (!board || board.length < 3) ? preflopStrength(pair) : postflopStrength(pair, board);
    }
    const suited = classHole(i, j, true);
    const off = classHole(i, j, false);
    if (!board || board.length < 3) {
      return (preflopStrength(suited) + preflopStrength(off)) / 2;
    }
    return (postflopStrength(suited, board) + postflopStrength(off, board)) / 2;
  }

  function makePriorMatrix(view) {
    const counts = new Array(13).fill(0);
    view.hole.concat(view.board).forEach((c) => {
      const idx = RANK_INDEX[c.r];
      if (idx !== undefined) counts[idx] += 1;
    });
    const matrix = Array.from({ length: 13 }, () => new Array(13).fill(0));
    let total = 0;
    for (let i = 0; i < 13; i++) {
      for (let j = i; j < 13; j++) {
        const ci = Math.max(0, 4 - counts[i]);
        const cj = Math.max(0, 4 - counts[j]);
        const combos = i === j ? ci * (ci - 1) / 2 : ci * cj;
        matrix[i][j] = combos;
        total += combos;
      }
    }
    if (!total) {
      for (let i = 0; i < 13; i++) for (let j = i; j < 13; j++) matrix[i][j] = 1;
      total = 91;
    }
    for (let i = 0; i < 13; i++) for (let j = i; j < 13; j++) matrix[i][j] /= total;
    return matrix;
  }

  function normalizeMatrix(matrix) {
    let total = 0;
    for (let i = 0; i < 13; i++) for (let j = i; j < 13; j++) total += matrix[i][j];
    if (!total) return matrix;
    for (let i = 0; i < 13; i++) for (let j = i; j < 13; j++) matrix[i][j] /= total;
    return matrix;
  }

  function actionLikelihood(type, strength, depth) {
    const sharp = 1 + depth * 0.18;
    if (type === "raise") return 0.04 + 0.96 * Math.pow(strength, sharp);
    if (type === "call") return 0.12 + 0.88 * strength;
    if (type === "check") return 0.90 - 0.45 * strength;
    if (type === "fold") return Math.max(0.02, 1 - strength);
    return 1;
  }

  function updateMatrix(matrix, action, view, depth) {
    const board = action.street === "preflop" ? [] : view.board;
    for (let i = 0; i < 13; i++) {
      for (let j = i; j < 13; j++) {
        if (matrix[i][j] <= 0) continue;
        const s = classStrength(i, j, board);
        matrix[i][j] *= actionLikelihood(action.type, s, depth);
      }
    }
    return normalizeMatrix(matrix);
  }

  function rangeState(view) {
    const key = view.gameId + ":" + view.handNo + ":" + view.seat;
    let state = RANGE_STATE.get(key);
    if (!state) {
      state = { matrices: view.players.map(() => null), last: 0, depth: DEPTH[view.difficulty] || 0 };
      RANGE_STATE.set(key, state);
      if (RANGE_STATE.size > 120) RANGE_STATE.delete(RANGE_STATE.keys().next().value);
    }
    const depth = DEPTH[view.difficulty] || 0;
    for (let k = state.last; k < view.history.length; k++) {
      const a = view.history[k];
      if (!a || a.seat === view.seat || a.type === "blind") continue;
      if (!state.matrices[a.seat]) state.matrices[a.seat] = makePriorMatrix(view);
      updateMatrix(state.matrices[a.seat], a, view, depth);
    }
    state.last = view.history.length;
    return state;
  }

  function matrixFor(state, view, seat) {
    return state.matrices[seat] || (state.matrices[seat] = makePriorMatrix(view));
  }

  function matrixMean(matrix, view) {
    let total = 0, sum = 0;
    for (let i = 0; i < 13; i++) {
      for (let j = i; j < 13; j++) {
        const p = matrix[i][j];
        if (p <= 0) continue;
        total += p;
        sum += p * classStrength(i, j, view.board);
      }
    }
    return total ? sum / total : 0;
  }

  function buildCells(matrix) {
    const cells = [];
    for (let i = 0; i < 13; i++) {
      for (let j = i; j < 13; j++) {
        if (matrix[i][j] > 0) cells.push({ i, j, p: matrix[i][j] });
      }
    }
    return cells;
  }

  function takeRandom(deck) {
    return [deck.pop(), deck.pop()];
  }

  // 按范围矩阵抽对手两张牌；找不到对应 rank 的可用牌时退回随机。
  function sampleRangeHole(deck, cells) {
    if (!cells || !cells.length) return takeRandom(deck);
    const total = cells.reduce((s, c) => s + c.p, 0);
    for (let attempt = 0; attempt < 14; attempt++) {
      let r = Math.random() * total, chosen = cells[cells.length - 1];
      for (const c of cells) { r -= c.p; if (r <= 0) { chosen = c; break; } }
      const need = chosen.i === chosen.j ? 2 : 1;
      const idxHi = [], idxLo = [];
      deck.forEach((c, idx) => {
        const ri = RANK_INDEX[c.r];
        if (ri === chosen.i) idxHi.push(idx);
        if (ri === chosen.j) idxLo.push(idx);
      });
      let indices = [];
      if (chosen.i === chosen.j) {
        if (idxHi.length >= 2) indices = [idxHi[Math.floor(Math.random() * idxHi.length)], idxHi[Math.floor(Math.random() * idxHi.length)]];
      } else if (idxHi.length && idxLo.length) {
        indices = [idxHi[Math.floor(Math.random() * idxHi.length)], idxLo[Math.floor(Math.random() * idxLo.length)]];
      }
      indices = [...new Set(indices)];
      if (indices.length === 2) {
        const hole = indices.map((ix) => deck[ix]);
        indices.sort((a, b) => b - a).forEach((ix) => deck.splice(ix, 1));
        return hole;
      }
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

    // 对手范围越强，越谨慎；加注历史越重，越少继续加注。
    const raiseThreshold = profile.raise + Math.min(0.42, raises * 0.09) + rangeP * 0.22;
    const raiseChance = Math.max(0.12, 0.72 - raises * 0.14 - (depth >= 2 ? 0.04 : 0) - rangeP * 0.18);
    const foldLine = profile.fold + rangeP * 0.10;

    if (toCall > 0 && !allInCall && rel < foldLine && eq < Math.max(0.10, potOdds - profile.call)) {
      if (diff === "easy" && Math.random() < 0.30) return { type: "call" };
      return { type: "fold" };
    }

    if (canBet && rel > raiseThreshold && Math.random() < raiseChance) {
      // 已经面对很大的跟注额时，边际牌优先跟注，保留筹码。
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

  window.HoldemAI = { decide, equity, ITERATIONS, DEPTH, preflopStrength, postflopStrength };
})();
