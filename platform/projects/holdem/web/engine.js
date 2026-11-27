/* KittenPuppy4Ever · 无限注德州扑克规则引擎
 *
 * 规则层只处理牌、下注、边池、淘汰；AI 只能通过 aiView() 看到自己的手牌
 * 与公共牌/公开下注信息，不能读取其它玩家的手牌或牌堆。
 */
(function () {
  const RANKS = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"];
  const VALUES = { "2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7, "8": 8, "9": 9, "10": 10, "J": 11, "Q": 12, "K": 13, "A": 14 };
  const SUITS = ["s", "h", "d", "c"];
  const SUIT_NAME = { s: "♠", h: "♥", d: "♦", c: "♣" };
  const DIFFICULTY_LABEL = { easy: "简单", medium: "中等", hard: "困难", hell: "地狱" };

  function makeDeck() {
    const out = [];
    for (const s of SUITS) for (const r of RANKS) out.push({ r, v: VALUES[r], s, label: r + SUIT_NAME[s] });
    return out;
  }
  function shuffle(a) {
    for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; }
    return a;
  }
  function cardKey(c) { return c.r + c.s; }

  function rank5(cards) {
    const vals = cards.map((c) => c.v).sort((a, b) => b - a);
    const suits = cards.map((c) => c.s);
    const flush = suits.every((s) => s === suits[0]);
    const counts = {};
    for (const v of vals) counts[v] = (counts[v] || 0) + 1;
    const groups = Object.keys(counts).map((v) => ({ v: Number(v), n: counts[v] })).sort((a, b) => (b.n - a.n) || (b.v - a.v));
    const unique = [...new Set(vals)];
    let straight = 0;
    if (unique.length === 5) {
      if (unique[0] - unique[4] === 4) straight = unique[0];
      else if (unique[0] === 14 && unique[1] === 5 && unique[4] === 2) straight = 5;
    }
    if (flush && straight) return { cat: 8, rank: [straight], name: "同花顺" };
    if (groups[0].n === 4) return { cat: 7, rank: [groups[0].v, groups[1].v], name: "四条" };
    if (groups[0].n === 3 && groups[1].n === 2) return { cat: 6, rank: [groups[0].v, groups[1].v], name: "葫芦" };
    if (flush) return { cat: 5, rank: vals, name: "同花" };
    if (straight) return { cat: 4, rank: [straight], name: "顺子" };
    if (groups[0].n === 3) return { cat: 3, rank: [groups[0].v].concat(groups.slice(1).map((g) => g.v)), name: "三条" };
    if (groups[0].n === 2 && groups[1] && groups[1].n === 2) return { cat: 2, rank: [groups[0].v, groups[1].v].concat(groups.slice(2).map((g) => g.v)), name: "两对" };
    if (groups[0].n === 2) return { cat: 1, rank: [groups[0].v].concat(groups.slice(1).map((g) => g.v)), name: "一对" };
    return { cat: 0, rank: vals, name: "高牌" };
  }
  function compareRank(a, b) {
    if (a.cat !== b.cat) return a.cat - b.cat;
    for (let i = 0; i < Math.max(a.rank.length, b.rank.length); i++) {
      const x = a.rank[i] || 0, y = b.rank[i] || 0;
      if (x !== y) return x - y;
    }
    return 0;
  }
  function bestHand(cards) {
    let best = null;
    const n = cards.length;
    for (let a = 0; a < n - 4; a++) for (let b = a + 1; b < n - 3; b++)
      for (let c = b + 1; c < n - 2; c++) for (let d = c + 1; d < n - 1; d++)
        for (let e = d + 1; e < n; e++) {
          const h = rank5([cards[a], cards[b], cards[c], cards[d], cards[e]]);
          if (!best || compareRank(h, best) > 0) best = h;
        }
    return best;
  }

  class Game {
    constructor(opts) {
      this.playerCount = Math.max(6, Math.min(10, Number(opts.players) || 6));
      this.totalChips = Math.max(600, Number(opts.totalChips) || 6000);
      this.startingStack = Math.max(100, Math.floor((Number(opts.startingStack) || Math.floor(this.totalChips / this.playerCount)) / 10) * 10);
      // 初始筹码按每人完全相等分配；不再有“余数给 1 号位”。
      this.totalChips = this.startingStack * this.playerCount;
      this.humanName = opts.humanName || "你";
      this.sb = Number(opts.sb) || 10;
      this.bb = Number(opts.bb) || 20;
      this.difficulties = opts.difficulties || {};
      this.players = [];
      this.deck = [];
      this.board = [];
      this.pot = 0;
      this.street = "idle";
      this.actor = -1;
      this.dealer = Math.floor(Math.random() * this.playerCount);
      this.currentBet = 0;
      this.minRaise = this.bb;
      this.lastAggressor = -1;
      this.handNo = 0;
      this.onUpdate = null; this.onLog = null; this.onHandLog = null; this.onGameOver = null; this.onAiAction = null; this.onHandResult = null; this.onHandStart = null; this.onChipMove = null; this.onRoundEnd = null; this._lastHandResult = null;
      this._over = false;
      for (let i = 0; i < this.playerCount; i++) {
        const diff = i === 0 ? "" : (this.difficulties[i] || "medium");
        this.players.push({
          seat: i, name: i === 0 ? this.humanName : "AI " + i, isHuman: i === 0,
          difficulty: diff, difficultyLabel: i === 0 ? "YOU" : (DIFFICULTY_LABEL[diff] || "中等"),
          stack: this.startingStack, hole: [], bet: 0, contribution: 0,
          folded: false, allIn: false, acted: false,
        });
      }
    }
    total() { return this.players.reduce((s, p) => s + p.stack + p.bet, 0); }
    activePlayers() { return this.players.filter((p) => !p.folded); }
    canActPlayers() { return this.players.filter((p) => !p.folded && !p.allIn); }
    start() {
      this.handNo = 0;
      this.dealer = Math.floor(Math.random() * this.playerCount);
      this._over = false;
      this.startHand();
    }
    log(text, cls) { if (this.onLog) this.onLog(text, cls); }
    update() { if (this.onUpdate) this.onUpdate(); }
    startHand() {
      if (this._over) return;
      const live = this.players.filter((p) => p.stack > 0);
      if (live.length < 2) return this.finishTournament();
      this.handNo++;
      this.board = [];
      this._lastHandResult = null;
      this.deck = shuffle(makeDeck());
      this.pot = 0;
      this.currentBet = 0;
      this.minRaise = this.bb;
      this.lastAggressor = -1;
      this.players.forEach((p) => {
        p.hole = []; p.bet = 0; p.contribution = 0;
        p.folded = p.stack <= 0; p.allIn = false; p.acted = false;
      });
      this.street = "preflop";
      this.dealer = (this.dealer + 1) % this.playerCount;
      const sbSeat = (this.dealer + 1) % this.playerCount;
      const bbSeat = (this.dealer + 2) % this.playerCount;
      // 从 SB 开始，每人 2 张；不暴露给其他玩家。
      for (let k = 0; k < 2; k++) {
        for (let off = 0; off < this.playerCount; off++) {
          const p = this.players[(sbSeat + off) % this.playerCount];
          if (!p.folded) p.hole.push(this.deck.pop());
        }
      }
      this.log("—— 第 " + this.handNo + " 手 · 庄位 " + (this.dealer + 1) + " 号位 ——");
      if (this.onHandLog) this.onHandLog("第 " + this.handNo + " 手开始 · 盲注 " + this.sb + "/" + this.bb);
      this.postBlind(sbSeat, this.sb, "小盲");
      this.postBlind(bbSeat, this.bb, "大盲");
      this.currentBet = Math.max(...this.players.map((p) => p.bet));
      this.actor = this.nextSeat(bbSeat);
      this.players.forEach((p) => { p.acted = false; });
      if (this.onHandStart) this.onHandStart({ handNo: this.handNo, dealer: this.dealer, sbSeat, bbSeat, humanStartStack: this.players[0].stack });
      this.updateAndRun();
    }
    postBlind(seat, amount, label) {
      const p = this.players[seat];
      if (p.folded) return;
      const pay = Math.min(p.stack, amount);
      p.stack -= pay; p.bet += pay; p.contribution += pay;
      if (p.stack === 0) p.allIn = true;
      if (pay && this.onChipMove) this.onChipMove({ seat, amount: pay, kind: "bet" });
      this.log(p.name + " 下" + label + " " + pay);
    }
    nextSeat(from) {
      for (let k = 1; k <= this.playerCount; k++) {
        const i = (from + k) % this.playerCount;
        const p = this.players[i];
        if (!p.folded && !p.allIn && p.stack > 0) return i;
      }
      return -1;
    }
    nextActor(from) {
      for (let k = 1; k <= this.playerCount; k++) {
        const i = (from + k) % this.playerCount;
        const p = this.players[i];
        if (p.folded || p.allIn) continue;
        if (!p.acted || p.bet < this.currentBet) return i;
      }
      return -1;
    }
    minRaiseTo() {
      return Math.max(this.bb, this.currentBet + Math.max(this.minRaise, this.bb));
    }
    aiView(seat) {
      const p = this.players[seat];
      if (!p) return null;
      return {
        seat,
        difficulty: p.difficulty,
        hole: p.hole.map((c) => ({ ...c })),
        board: this.board.map((c) => ({ ...c })),
        street: this.street,
        pot: this.pot + this.players.reduce((s, x) => s + x.bet, 0),
        currentBet: this.currentBet,
        minRaise: this.minRaise,
        minRaiseTo: Math.min(this.minRaiseTo(), p.bet + p.stack),
        maxRaiseTo: p.bet + p.stack,
        toCall: Math.max(0, this.currentBet - p.bet),
        dealer: this.dealer,
        players: this.players.map((x) => ({
          seat: x.seat, name: x.name, stack: x.stack, bet: x.bet, folded: x.folded, allIn: x.allIn, isHuman: x.isHuman,
        })),
        bb: this.bb,
      };
    }
    act(action) {
      if (this._over || this.street === "ended" || this.street === "showdown") return false;
      const i = this.actor;
      const p = this.players[i];
      if (!p || p.folded || p.allIn || p.isHuman === false && !action) return false;
      const type = action && action.type;
      const toCall = Math.max(0, this.currentBet - p.bet);
      if (type === "fold") {
        if (toCall === 0) return false;
        p.folded = true; p.acted = true;
        this.log(p.name + " 弃牌");
      } else if (type === "check") {
        if (toCall > 0) return false;
        p.acted = true;
        this.log(p.name + " 过牌");
      } else if (type === "call") {
        if (toCall <= 0) return false;
        const pay = Math.min(p.stack, toCall);
        p.stack -= pay; p.bet += pay; p.contribution += pay;
        if (p.stack === 0) p.allIn = true;
        p.acted = true;
        if (pay && this.onChipMove) this.onChipMove({ seat: i, amount: pay, kind: "bet" });
        this.log(p.name + " 跟注 " + pay);
      } else if (type === "raise") {
        let amount = Number(action.amount);
        const maxTo = p.bet + p.stack;
        if (!Number.isFinite(amount)) return false;
        amount = Math.min(maxTo, Math.max(this.minRaiseTo(), Math.floor(amount)));
        if (amount <= this.currentBet) return false;
        const pay = Math.min(p.stack, amount - p.bet);
        if (pay <= 0) return false;
        const raiseSize = amount - this.currentBet;
        p.stack -= pay; p.bet += pay; p.contribution += pay;
        if (p.stack === 0) p.allIn = true;
        if (pay && this.onChipMove) this.onChipMove({ seat: i, amount: pay, kind: "bet" });
        this.currentBet = p.bet;
        this.minRaise = Math.max(this.minRaise, raiseSize);
        this.lastAggressor = i;
        this.players.forEach((x, k) => { if (k !== i && !x.folded && !x.allIn) x.acted = false; });
        p.acted = true;
        this.log(p.name + " " + (p.allIn ? "全下 " : "加注到 ") + amount);
      } else return false;
      this.update();
      this.advance();
      return true;
    }
    advance() {
      if (this._over) return;
      const live = this.activePlayers();
      if (live.length <= 1) return this.awardUncontested(live[0]);
      const need = this.players.filter((p) => !p.folded && !p.allIn && (!p.acted || p.bet < this.currentBet));
      if (need.length) {
        this.actor = this.nextActor(this.actor);
        if (this.actor < 0) this.actor = need[0].seat;
        this.updateAndRun();
        return;
      }
      this.endRound();
    }
    endRound() {
      const endedStreet = this.street;
      this.players.forEach((p) => { this.pot += p.bet; p.bet = 0; p.acted = false; });
      if (this.onRoundEnd) this.onRoundEnd({ pot: this.pot, street: endedStreet });
      this.currentBet = 0;
      this.minRaise = this.bb;
      if (this.street === "preflop") this.street = "flop";
      else if (this.street === "flop") this.street = "turn";
      else if (this.street === "turn") this.street = "river";
      else if (this.street === "river") return this.showdown();
      if (this.street === "flop") this.dealBoard(3);
      else this.dealBoard(1);
      const live = this.activePlayers();
      const nonAllIn = live.filter((p) => !p.allIn);
      if (live.length > 1 && nonAllIn.length <= 1) {
        // 其余人都已全下：不再有下注轮，直接发完公共牌摊牌。
        while (this.board.length < 5) this.board.push(this.deck.pop());
        return this.showdown();
      }
      this.actor = this.nextSeat(this.dealer);
      if (this.actor < 0) return this.showdown();
      this.log("—— " + this.street.toUpperCase() + " · " + this.board.map((c) => c.label).join(" ") + " ——");
      this.updateAndRun();
    }
    dealBoard(n) {
      for (let i = 0; i < n; i++) this.board.push(this.deck.pop());
    }
    awardUncontested(winner) {
      if (!winner) return;
      const amount = this.pot + this.players.reduce((s, p) => s + p.bet, 0);
      this.players.forEach((p) => { this.pot += p.bet; p.bet = 0; });
      winner.stack += this.pot;
      this.log(winner.name + " 赢得底池 " + this.pot, "win");
      this.pot = 0;
      this.street = "ended";
      this.actor = -1;
      const human = this.players[0];
      const result = {
        winners: [winner.seat], showdown: false, pot: amount,
        board: this.board.map((c) => ({ ...c })),
        humanHand: null, humanFolded: human.folded, humanAllIn: human.allIn,
        humanBlind: human.seat === (this.dealer + 1) % this.playerCount ? "sb" : human.seat === (this.dealer + 2) % this.playerCount ? "bb" : "",
        humanStack: human.stack, players: this.players.map((p) => ({ seat: p.seat, stack: p.stack, folded: p.folded, allIn: p.allIn })),
      };
      this._lastHandResult = result;
      this.update();
      this.endHand(winner.name + " 赢得 " + amount, result);
    }
    showdown() {
      this.players.forEach((p) => { this.pot += p.bet; p.bet = 0; });
      this.street = "showdown";
      this.actor = -1;
      this.players.forEach((p) => {
        if (!p.folded) p.hand = bestHand(p.hole.concat(this.board));
      });
      const contenders = this.players.filter((p) => !p.folded);
      this.log("—— 摊牌 ——");
      contenders.forEach((p) => this.log(p.name + "：" + p.hole.map((c) => c.label).join(" ") + " → " + p.hand.name));
      const levels = [...new Set(this.players.map((p) => p.contribution).filter((x) => x > 0))].sort((a, b) => a - b);
      let prev = 0;
      const payouts = this.players.map(() => 0);
      for (const level of levels) {
        const amount = this.players.reduce((s, p) => s + Math.max(0, Math.min(p.contribution, level) - prev), 0);
        const eligible = contenders.filter((p) => p.contribution >= level);
        if (amount > 0 && eligible.length) {
          let best = null;
          for (const p of eligible) if (!best || compareRank(p.hand, best.hand) > 0) best = p;
          const winners = eligible.filter((p) => compareRank(p.hand, best.hand) === 0);
          const share = Math.floor(amount / winners.length);
          let rem = amount - share * winners.length;
          winners.forEach((p, idx) => { payouts[p.seat] += share + (idx === 0 ? rem : 0); });
          this.log((winners.map((p) => p.name).join("、")) + " 赢得边池 " + amount, "win");
        }
        prev = level;
      }
      payouts.forEach((v, i) => { if (v) this.players[i].stack += v; });
      this.pot = 0;
      this.update();
      const winners = this.players.filter((p, i) => payouts[i] > 0);
      const human = this.players[0];
      const result = {
        winners: winners.map((p) => p.seat), showdown: true, pot: payouts.reduce((s, x) => s + x, 0),
        board: this.board.map((c) => ({ ...c })),
        humanHand: human.hand || null, humanFolded: human.folded, humanAllIn: human.allIn,
        humanBlind: human.seat === (this.dealer + 1) % this.playerCount ? "sb" : human.seat === (this.dealer + 2) % this.playerCount ? "bb" : "",
        humanStack: human.stack, players: this.players.map((p) => ({ seat: p.seat, stack: p.stack, folded: p.folded, allIn: p.allIn })),
      };
      this._lastHandResult = result;
      this.endHand(winners.length ? winners.map((p) => p.name).join("、") + " 赢得摊牌" : "无人赢得底池", result);
    }
    endHand(text, result) {
      this._lastHandResult = result || this._lastHandResult;
      if (this._lastHandResult && this.onHandResult) this.onHandResult(this._lastHandResult);
      const busted = this.players.filter((p) => p.stack <= 0);
      if (busted.length) return this.finishTournament(busted);
      this.update();
      const delay = 2200;
      setTimeout(() => {
        if (this._over) return;
        this.startHand();
      }, delay);
    }
    finishTournament(busted) {
      if (this._over) return;
      this._over = true;
      this.street = "ended";
      const alive = this.players.filter((p) => p.stack > 0);
      const winner = alive.length === 1 ? alive[0] : alive.sort((a, b) => b.stack - a.stack)[0];
      const text = (busted && busted.length ? busted.map((p) => p.name).join("、") + " 输光筹码。" : "") +
        (alive.length ? "最终筹码第一：" + winner.name + "（" + winner.stack.toLocaleString("zh-CN") + "）" : "全员出局");
      this.log("牌局结束：" + text, "win");
      this.update();
      if (this.onGameOver) this.onGameOver({ winner: winner ? winner.name : "", text });
    }
    updateAndRun() {
      this.update();
      if (!this._over && this.actor >= 0 && this.actor < this.playerCount) {
        const p = this.players[this.actor];
        if (!p.isHuman && this.onAiAction) this.onAiAction();
      }
    }
  }

  window.Holdem = { Game, makeDeck, bestHand, rank5, compareRank, RANKS, SUITS, SUIT_NAME, VALUES, DIFFICULTY_LABEL };
})();
