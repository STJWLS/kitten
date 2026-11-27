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
    const canBet = canRaise(view);
    const canCheck = toCall === 0;
    const aggression = diff === "hell" ? 1.18 : diff === "hard" ? 1.04 : diff === "medium" ? 0.9 : 0.7;
    const foldLine = diff === "easy" ? 0.24 : diff === "medium" ? 0.34 : diff === "hard" ? 0.38 : 0.40;
    const raiseLine = diff === "hell" ? 0.56 : diff === "hard" ? 0.63 : diff === "medium" ? 0.68 : 0.78;

    // 弱牌：面对下注时按难度和底池赔率弃牌。
    if (toCall > 0 && eq < Math.max(foldLine, potOdds * 0.92)) {
      if (diff === "easy" && Math.random() < 0.18) return canCheck ? { type: "check" } : { type: "call" };
      return { type: "fold" };
    }
    // 强牌：主动做大底池；地狱难度更愿意在翻牌后加压。
    if (canBet && eq > raiseLine * (1 - Math.min(0.12, aggression * 0.04))) {
      if (Math.random() < (diff === "easy" ? 0.45 : diff === "medium" ? 0.7 : 0.86)) {
        return actRaise(view, diff === "easy" ? 0.35 : diff === "medium" ? 0.55 : 0.72);
      }
    }
    // 中等牌：赔率合适就跟，否则过牌/弃牌。
    if (toCall > 0) {
      if (eq + (diff === "easy" ? -0.03 : 0.02) >= potOdds) {
        return { type: "call" };
      }
      if (diff === "easy" && Math.random() < 0.25) return { type: "call" };
      return { type: "fold" };
    }
    // 有位置/强牌的半诈唬。
    if (canBet && diff !== "easy" && Math.random() < (diff === "hell" ? 0.22 : diff === "hard" ? 0.12 : 0.06)) {
      return actRaise(view, diff === "hell" ? 0.6 : 0.45);
    }
    return { type: "check" };
  }
  window.HoldemAI = { decide, equity, ITERATIONS };
})();
