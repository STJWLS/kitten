#!/usr/bin/env node
/*
 * 生成离线范围模型训练数据。
 * 用法:
 *   node generate_selfplay.js --hands=200 --out=training/data/selfplay.jsonl
 * 训练数据允许看到所有玩家手牌用于打标签；运行时不会使用这些标签。
 */
const fs = require('fs');
const path = require('path');
global.window = global;
global.setTimeout = () => 0;
require(path.join(__dirname, '..', 'web', 'engine.js'));
require(path.join(__dirname, '..', 'web', 'ai.js'));

const args = Object.fromEntries(process.argv.slice(2).map((a) => {
  const [k, v] = a.replace(/^--/, '').split('=');
  return [k, v === undefined ? true : v];
}));
const hands = Number(args.hands || 200);
const outPath = args.out || path.join(__dirname, 'data', 'selfplay.jsonl');
const fast = args.fast !== 'false';
if (fast) {
  HoldemAI.ITERATIONS.easy = 4;
  HoldemAI.ITERATIONS.medium = 12;
  HoldemAI.ITERATIONS.hard = 24;
  HoldemAI.ITERATIONS.hell = 32;
}
fs.mkdirSync(path.dirname(outPath), { recursive: true });
const out = fs.createWriteStream(outPath, { flags: 'w' });
const DIFFS = ['easy', 'medium', 'hard', 'hell'];
const RULES = ['nolimit', 'potlimit', 'fixedlimit'];
let samples = 0, handNo = 0;

function jsonLine(obj) { out.write(JSON.stringify(obj) + '\n'); }

for (let h = 0; h < hands; h++) {
  const n = 6 + Math.floor(Math.random() * 5);
  const diffMap = {};
  for (let i = 0; i < n; i++) diffMap[i] = DIFFS[Math.floor(Math.random() * DIFFS.length)];
  const betRule = RULES[Math.floor(Math.random() * RULES.length)];
  const stack = 500 + Math.floor(Math.random() * 20) * 100;
  const g = new Holdem.Game({ players: n, totalChips: stack * n, startingStack: stack, difficulties: diffMap, sb: 10, bb: 20, betRule });
  handNo++;
  g.start();
  let guard = 0;
  while (!g._lastHandResult && guard++ < 300) {
    const actor = g.actor;
    if (actor < 0) break;
    const view = g.aiView(actor);
    const activeTargets = g.players.filter((p) => p.seat !== actor && !p.folded);
    for (const target of activeTargets) {
      const targetHistory = view.history.filter((a) => a.seat === target.seat);
      jsonLine({
        version: 1,
        gameId: g.gameId,
        handNo,
        playerCount: n,
        observerSeat: actor,
        targetSeat: target.seat,
        observerDifficulty: view.difficulty,
        targetDifficulty: target.difficulty,
        betRule: g.betRule,
        sb: g.sb, bb: g.bb,
        street: view.street,
        board: view.board.map((c) => ({ r: c.r, s: c.s })),
        observerHole: view.hole.map((c) => ({ r: c.r, s: c.s })),
        targetHole: target.hole.map((c) => ({ r: c.r, s: c.s })),
        pot: view.pot,
        currentBet: view.currentBet,
        toCall: view.toCall,
        raisesThisStreet: view.raisesThisStreet,
        dealer: view.dealer,
        observer: { seat: view.seat, stack: view.stack, bet: view.bet },
        target: { seat: target.seat, stack: target.stack, bet: target.bet, lastAction: target.lastAction || "" },
        players: view.players.map((p) => ({ seat: p.seat, stack: p.stack, bet: p.bet, folded: p.folded, allIn: p.allIn, lastAction: p.lastAction || "" })),
        history: view.history,
        targetHistory,
      });
      samples++;
    }
    const action = HoldemAI.decide(view);
    if (!g.act(action)) {
      const p = g.players[actor];
      const toCall = Math.max(0, g.currentBet - p.bet);
      g.act(toCall > 0 ? { type: 'call' } : { type: 'check' });
    }
  }
}
out.end();
console.log(JSON.stringify({ hands: hands, samples: samples, out: outPath }));
