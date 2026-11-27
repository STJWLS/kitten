/* KittenPuppy4Ever · 德州扑克 AI
 *
 * 输入只有 Game.aiView(seat)：自己的手牌、公共牌、底池、公开下注、公开行动历史、人数。
 * 绝不接收其他玩家的手牌或牌堆；equity 用未知牌随机模拟，属于合法信息。
 *
 * 难度对应“思考深度”：
 *   easy   depth 0：随机对手范围，不做行动历史修正
 *   medium depth 1：翻前行动范围
 *   hard   depth 2：翻前 + 翻后行动范围、加注历史、筹码深度
 *   hell   depth 3：更窄的范围、更深的加注历史和 SPR 修正
 */
(function () {
  const RANKS = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"];
  const VALUES = { "2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7, "8": 8, "9": 9, "10": 10, "J": 11, "Q": 12, "K": 13, "A": 14 };
  const SUITS = ["s", "h", "d", "c"];
  const ITERATIONS = { easy: 16, medium: 120, hard: 480, hell: 1600 };
  const DEPTH = { easy: 0, medium: 1, hard: 2, hell: 3 };
  const RANGE_ATTEMPTS = { easy: 1, medium: 4, hard: 7, hell: 10 };

  function makeDeck() {
    const out = [];
    for (const s of SUITS) for (const r of RANKS) out.push({ r, v: VALUES[r], s });
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

  // 起手牌强度 0~1，用于按公开行动筛对手范围。
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

  // 翻后牌力 0~1：成牌等级 + 同花/顺子听牌。
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

  function opponentThresholds(view, opp, depth) {
    let pre = 0, post = 0;
    if (!view.history || depth <= 0) return { pre, post };
    const acts = view.history.filter((h) => h.seat === opp.seat);
    if (depth >= 1) {
      if (acts.some((h) => h.street === "preflop" && h.type === "raise")) pre = 0.62;
      else if (acts.some((h) => h.street === "preflop" && h.type === "call")) pre = 0.42;
      else if (acts.some((h) => h.street === "preflop" && h.type === "check")) pre = 0.30;
    }
    if (depth >= 2) {
      if (acts.some((h) => h.street !== "preflop" && h.type === "raise")) post = Math.max(post, 0.36);
      else if (acts.some((h) => h.street !== "preflop" && h.type === "call")) post = Math.max(post, 0.16);
      else if (acts.some((h) => h.street !== "preflop" && h.type === "check")) post = Math.max(post, 0.05);
    }
    if (depth >= 3) { pre = Math.min(0.90, pre + 0.04); post = Math.min(0.90, post + 0.05); }
    return { pre, post };
  }

  function takePair(deck, i, j) {
    const hole = [deck[i], deck[j]];
    const idx = [i, j].sort((a, b) => b - a);
    idx.forEach((k) => deck.splice(k, 1));
    return hole;
  }

  // 按对手公开行动范围抽两张牌，而非无条件随机。
  function drawOpponentHole(deck, view, opp, depth) {
    if (!deck || deck.length < 2) return [];
    if (depth <= 0) return takePair(deck, 0, 1);
    const t = opponentThresholds(view, opp, depth);
    if (!t.pre && !t.post) return takePair(deck, 0, 1);
    const attempts = RANGE_ATTEMPTS[view.difficulty] || 4;
    let fallback = [0, 1];
    for (let a = 0; a < attempts; a++) {
      const i = Math.floor(Math.random() * deck.length);
      let j = Math.floor(Math.random() * (deck.length - 1));
      if (j >= i) j++;
      const hole = [deck[i], deck[j]];
      if (a === 0) fallback = [i, j];
      if (preflopStrength(hole) >= t.pre && (view.board.length < 3 || postflopStrength(hole, view.board) >= t.post)) {
        return takePair(deck, i, j);
      }
    }
    return takePair(deck, fallback[0], fallback[1]);
  }

  function exactRiverEquity(view, depth) {
    const known = new Set(view.hole.concat(view.board).map(key));
    const deck = makeDeck().filter((c) => !known.has(key(c)));
    const mine = Holdem.bestHand(view.hole.concat(view.board));
    const opp = view.players.find((p) => p.seat !== view.seat && !p.folded);
    if (!opp) return 0.5;
    const t = depth > 0 ? opponentThresholds(view, opp, depth) : { pre: 0, post: 0 };
    let score = 0, total = 0;
    for (let i = 0; i < deck.length - 1; i++) for (let j = i + 1; j < deck.length; j++) {
      const hole = [deck[i], deck[j]];
      if (t.pre && preflopStrength(hole) < t.pre) continue;
      if (t.post && postflopStrength(hole, view.board) < t.post) continue;
      const other = Holdem.bestHand(hole.concat(view.board));
      const cmp = Holdem.compareRank(mine, other);
      total++;
      if (cmp > 0) score += 1;
      else if (cmp === 0) score += 0.5;
    }
    return total ? score / total : 0.5;
  }

  function equity(view, iterations, depth) {
    const known = new Set(view.hole.concat(view.board).map(key));
    const base = makeDeck().filter((c) => !known.has(key(c)));
    const opponents = view.players.filter((p) => p.seat !== view.seat && !p.folded);
    if (!opponents.length) return 1;
    const exact = view.board.length === 5 && opponents.length === 1 && iterations >= 400;
    const sims = exact ? 0 : Math.max(1, iterations);
    let score = 0;
    for (let it = 0; it < sims; it++) {
      const deck = base.slice();
      shuffle(deck);
      const oppHands = opponents.map((opp) => drawOpponentHole(deck, view, opp, depth));
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
    return exact ? exactRiverEquity(view, depth) : score / sims;
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
    const toCall = view.toCall || 0;
    const pot = Math.max(view.pot, view.bb);
    const potOdds = toCall > 0 ? toCall / (pot + toCall) : 0;
    const iters = ITERATIONS[diff] || ITERATIONS.medium;
    const eq = equity(view, iters, depth);
    const opponents = Math.max(1, view.players.filter((p) => p.seat !== view.seat && !p.folded).length);
    // 多人底池里 raw equity 天生接近 1/(人数+1)，用“相对平均胜率”判断牌力。
    const rel = eq * (opponents + 1);
    const canBet = canRaise(view);
    const canCheck = toCall === 0;
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

    // 加注历史越重，门槛越高、频率越低；避免 AI 自己把底池无限滚大。
    const raiseThreshold = profile.raise + Math.min(0.42, raises * 0.09);
    const raiseChance = Math.max(0.16, 0.72 - raises * 0.14 - (depth >= 2 ? 0.04 : 0));

    // 只有牌力明显低于平均、且不够底池赔率时才弃牌，避免多人桌无脑弃牌。
    if (toCall > 0 && !allInCall && rel < profile.fold && eq < Math.max(0.10, potOdds - profile.call)) {
      if (diff === "easy" && Math.random() < 0.30) return { type: "call" };
      return { type: "fold" };
    }

    // 加注：结合 SPR、剩余筹码、加注历史决定尺度与是否值得继续做大。
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
      if (rel >= profile.fold || eq >= potOdds - profile.call) return { type: "call" };
      if (Math.random() < profile.bluff) return { type: "call" };
      return { type: "fold" };
    }

    // 无人下注时，强牌或少量诈唬下注。
    if (canBet && (rel > profile.raise * 0.92 || Math.random() < profile.bluff)) {
      let fraction = diff === "hell" ? 0.55 : 0.42;
      if (spr < 1.2) fraction = 1.0;
      if (shortStack) fraction = Math.min(fraction, 0.65);
      return actRaise(view, fraction);
    }
    return { type: "check" };
  }

  window.HoldemAI = { decide, equity, ITERATIONS, DEPTH, preflopStrength, postflopStrength };
})();
