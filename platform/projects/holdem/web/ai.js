/* KittenPuppy4Ever · 德州扑克 AI
 *
 * 输入只有 Game.aiView(seat)：自己的手牌、公共牌、底池、公开下注、人数。
 * 绝不接收其他玩家的手牌或牌堆；equity 用未知牌随机模拟，属于合法信息。
 */
(function () {
  const RANKS = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"];
  const VALUES = { "2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7, "8": 8, "9": 9, "10": 10, "J": 11, "Q": 12, "K": 13, "A": 14 };
  const SUITS = ["s", "h", "d", "c"];
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
  // 难度越高，胜率模拟次数越多；河牌单挑时可以直接精确枚举对手两张牌。
  const ITERATIONS = { easy: 16, medium: 120, hard: 480, hell: 1600 };
  function exactRiverEquity(view) {
    const known = new Set(view.hole.concat(view.board).map(key));
    const deck = makeDeck().filter((c) => !known.has(key(c)));
    const mine = Holdem.bestHand(view.hole.concat(view.board));
    let score = 0, total = 0;
    for (let i = 0; i < deck.length - 1; i++) for (let j = i + 1; j < deck.length; j++) {
      const other = Holdem.bestHand([deck[i], deck[j]].concat(view.board));
      const cmp = Holdem.compareRank(mine, other);
      total++;
      if (cmp > 0) score += 1;
      else if (cmp === 0) score += 0.5;
    }
    return total ? score / total : 0.5;
  }
  function equity(view, iterations) {
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
      let cursor = 0;
      const oppHands = opponents.map(() => [deck[cursor++], deck[cursor++]]);
      const board = view.board.slice();
      while (board.length < 5) board.push(deck[cursor++]);
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
    return exact ? exactRiverEquity(view) : score / sims;
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
    const toCall = view.toCall || 0;
    const pot = Math.max(view.pot, view.bb);
    const potOdds = toCall > 0 ? toCall / (pot + toCall) : 0;
    const iters = ITERATIONS[diff] || ITERATIONS.medium;
    const eq = equity(view, iters);
    const opponents = Math.max(1, view.players.filter((p) => p.seat !== view.seat && !p.folded).length);
    // 多人底池里 raw equity 天生接近 1/(人数+1)，用“相对平均胜率”判断牌力。
    const rel = eq * (opponents + 1);
    const canBet = canRaise(view);
    const canCheck = toCall === 0;
    const profile = {
      easy:   { fold: 0.36, raise: 1.62, bluff: 0.10, call: 0.18 },
      medium: { fold: 0.50, raise: 1.38, bluff: 0.08, call: 0.10 },
      hard:   { fold: 0.62, raise: 1.22, bluff: 0.07, call: 0.05 },
      hell:   { fold: 0.70, raise: 1.10, bluff: 0.06, call: 0.02 },
    }[diff] || { fold: 0.50, raise: 1.38, bluff: 0.08, call: 0.10 };

    // 只有牌力明显低于平均、且不够底池赔率时才弃牌，避免多人桌无脑弃牌。
    if (toCall > 0 && rel < profile.fold && eq < Math.max(0.10, potOdds - profile.call)) {
      if (diff === "easy" && Math.random() < 0.30) return { type: "call" };
      return { type: "fold" };
    }
    // 相对平均胜率明显更高时主动做大底池。
    if (canBet && rel > profile.raise && Math.random() < 0.72) {
      return actRaise(view, diff === "easy" ? 0.30 : diff === "medium" ? 0.50 : 0.68);
    }
    if (toCall > 0) {
      if (rel >= profile.fold || eq >= potOdds - profile.call) return { type: "call" };
      if (Math.random() < profile.bluff) return { type: "call" };
      return { type: "fold" };
    }
    // 无人下注时，强牌或少量诈唬下注。
    if (canBet && (rel > profile.raise * 0.92 || Math.random() < profile.bluff)) {
      return actRaise(view, diff === "hell" ? 0.55 : 0.42);
    }
    return { type: "check" };
  }
  window.HoldemAI = { decide, equity, ITERATIONS };
})();
