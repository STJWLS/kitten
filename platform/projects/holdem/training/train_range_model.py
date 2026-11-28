#!/usr/bin/env python3
"""Train a small opponent-range belief model from generated self-play data.

Usage:
  python train_range_model.py --data training/data/selfplay.jsonl --out training/out
"""
import argparse, json, math, os, random
from collections import Counter, defaultdict
import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader

SUITS = ["s", "h", "d", "c"]
RANKS = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]
CARD_INDEX = {s + r: si * 13 + ri for si, s in enumerate(SUITS) for ri, r in enumerate(RANKS)}
RANK_INDEX = {r: i for i, r in enumerate(RANKS)}
COMBO_INDEX = {}
for i in range(52):
    for j in range(i + 1, 52):
        COMBO_INDEX[(i, j)] = len(COMBO_INDEX)
COMBO_COUNT = len(COMBO_INDEX)
RANK_PAIR_INDEX = {}
for i in range(13):
    for j in range(i, 13):
        RANK_PAIR_INDEX[(i, j)] = len(RANK_PAIR_INDEX)
RANK_PAIR_COUNT = len(RANK_PAIR_INDEX)
DIFFS = ["easy", "medium", "hard", "hell"]
STREETS = ["preflop", "flop", "turn", "river"]
ACTIONS = ["fold", "check", "call", "raise"]
RULES = ["nolimit", "potlimit", "fixedlimit"]

def card_idx(c):
    return CARD_INDEX[c["s"] + c["r"]]

def combo_idx(hole):
    a, b = sorted(card_idx(c) for c in hole)
    return COMBO_INDEX[(a, b)]

def rank_pair_idx(hole):
    a, b = sorted(RANK_INDEX[c["r"]] for c in hole)
    return RANK_PAIR_INDEX[(a, b)]

def clip(x, lo, hi):
    return max(lo, min(hi, x))

# Feature layout must match web/range-model.js.
def featurize(row):
    f = []
    # observer hole: 2 x 52
    for c in row["observerHole"]:
        v = [0.0] * 52
        v[card_idx(c)] = 1.0
        f.extend(v)
    # board: 5 x 52
    board = row.get("board", [])
    for i in range(5):
        v = [0.0] * 52
        if i < len(board):
            v[card_idx(board[i])] = 1.0
        f.extend(v)
    # observer / target difficulty one-hot
    for d in DIFFS:
        f.append(1.0 if row.get("observerDifficulty") == d else 0.0)
    for d in DIFFS:
        f.append(1.0 if row.get("targetDifficulty") == d else 0.0)
    # street one-hot
    for s in STREETS:
        f.append(1.0 if row.get("street") == s else 0.0)
    # target action aggregation
    th = [a for a in row.get("targetHistory", []) if a.get("type") != "blind"]
    total = max(1, len(th))
    counts = Counter(a.get("type") for a in th)
    for a in ACTIONS:
        f.append(counts.get(a, 0) / total)
    pre = [a for a in th if a.get("street") == "preflop"]
    post = [a for a in th if a.get("street") != "preflop"]
    ptotal = max(1, len(pre)); qtotal = max(1, len(post))
    pc = Counter(a.get("type") for a in pre); qc = Counter(a.get("type") for a in post)
    for a in ACTIONS:
        f.append(pc.get(a, 0) / ptotal)
    for a in ACTIONS:
        f.append(qc.get(a, 0) / qtotal)
    last = th[-1]["type"] if th else ""
    for a in ACTIONS:
        f.append(1.0 if last == a else 0.0)
    f.append(min(1.0, len(th) / 10.0))
    pot = max(1.0, float(row.get("pot", 0)))
    amount_sum = sum(float(a.get("amount", 0)) for a in th)
    f.append(clip(amount_sum / pot, 0.0, 3.0))
    f.append(clip((float(th[-1].get("amount", 0)) if th else 0.0) / pot, 0.0, 3.0))
    # global context
    bb = max(1.0, float(row.get("bb", 20)))
    observer = row.get("observer", {}); target = row.get("target", {})
    n = max(6, int(row.get("playerCount", 6)))
    players = row.get("players", [])
    active = sum(1 for p in players if not p.get("folded"))
    f.append(clip(pot / bb / 20.0, 0.0, 3.0))
    f.append(clip(float(row.get("currentBet", 0)) / bb / 10.0, 0.0, 3.0))
    f.append(clip(float(row.get("toCall", 0)) / bb / 10.0, 0.0, 3.0))
    f.append(clip(float(observer.get("stack", 0)) / bb / 30.0, 0.0, 3.0))
    f.append(clip(float(target.get("stack", 0)) / bb / 30.0, 0.0, 3.0))
    f.append(clip(float(observer.get("bet", 0)) / bb / 10.0, 0.0, 3.0))
    f.append(clip(float(target.get("bet", 0)) / bb / 10.0, 0.0, 3.0))
    f.append(active / n)
    f.append(min(1.0, float(row.get("raisesThisStreet", 0)) / 4.0))
    dealer = int(row.get("dealer", 0))
    f.append(((int(row.get("observerSeat", 0)) - dealer) % n) / n)
    f.append(((int(row.get("targetSeat", 0)) - dealer) % n) / n)
    f.append(len(board) / 5.0)
    f.append(n / 10.0)
    rule = row.get("betRule", "nolimit")
    for r in RULES:
        f.append(1.0 if rule == r else 0.0)
    f.append(1.0 if target.get("allIn") else 0.0)
    f.append(1.0 if observer.get("allIn") else 0.0)
    return f

class RowDataset(Dataset):
    def __init__(self, rows, label_mode="combo"):
        self.rows = rows
        self.x = torch.tensor([featurize(r) for r in rows], dtype=torch.float32)
        fn = rank_pair_idx if label_mode == "rankpair" else combo_idx
        self.y = torch.tensor([fn(r["targetHole"]) for r in rows], dtype=torch.long)
    def __len__(self): return len(self.rows)
    def __getitem__(self, i): return self.x[i], self.y[i]

class RangeNet(nn.Module):
    def __init__(self, input_dim, hidden=256, out_dim=COMBO_COUNT):
        super().__init__()
        self.trunk = nn.Sequential(
            nn.Linear(input_dim, hidden), nn.ReLU(), nn.Dropout(0.08),
            nn.Linear(hidden, hidden), nn.ReLU(),
        )
        self.head = nn.Linear(hidden, out_dim)
    def forward(self, x):
        h = self.trunk(x)
        return self.head(h)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="training/data/selfplay.jsonl")
    ap.add_argument("--out", default="training/out")
    ap.add_argument("--epochs", type=int, default=8)
    ap.add_argument("--batch", type=int, default=128)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--hidden", type=int, default=256)
    ap.add_argument("--label-mode", choices=["combo", "rankpair"], default="combo")
    args = ap.parse_args()
    random.seed(args.seed); np.random.seed(args.seed); torch.manual_seed(args.seed)
    os.makedirs(args.out, exist_ok=True)
    rows = []
    with open(args.data, encoding="utf-8") as f:
        for line in f:
            if args.limit and len(rows) >= args.limit: break
            try: rows.append(json.loads(line))
            except Exception: pass
    print("rows", len(rows))
    # split by game/hand group to avoid leakage
    groups = sorted(set(r["gameId"] for r in rows))
    random.shuffle(groups)
    nval = max(1, int(len(groups) * 0.15))
    val_groups = set(groups[:nval])
    train_rows = [r for r in rows if r["gameId"] not in val_groups]
    val_rows = [r for r in rows if r["gameId"] in val_groups]
    print("train", len(train_rows), "val", len(val_rows), "groups", len(groups))
    train_ds = RowDataset(train_rows, args.label_mode); val_ds = RowDataset(val_rows, args.label_mode)
    out_dim = RANK_PAIR_COUNT if args.label_mode == "rankpair" else COMBO_COUNT
    input_dim = train_ds.x.shape[1]
    print("input_dim", input_dim, "output", COMBO_COUNT)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = RangeNet(input_dim, hidden=args.hidden, out_dim=out_dim).to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-4)
    loss_fn = nn.CrossEntropyLoss(label_smoothing=0.02)
    train_loader = DataLoader(train_ds, batch_size=args.batch, shuffle=True, num_workers=0)
    val_loader = DataLoader(val_ds, batch_size=args.batch, shuffle=False)
    best = 99.0
    for epoch in range(1, args.epochs + 1):
        model.train(); total = 0.0; n = 0
        for x, y in train_loader:
            x, y = x.to(device), y.to(device)
            opt.zero_grad()
            out = model(x)
            loss = loss_fn(out, y)
            loss.backward(); opt.step()
            total += loss.item() * len(y); n += len(y)
        model.eval(); vt = 0.0; vn = 0; top1 = 0; top5 = 0
        with torch.no_grad():
            for x, y in val_loader:
                x, y = x.to(device), y.to(device)
                out = model(x)
                vt += loss_fn(out, y).item() * len(y); vn += len(y)
                top = out.topk(5, dim=1).indices
                top1 += (top[:, 0] == y).sum().item()
                top5 += (top == y[:, None]).any(dim=1).sum().item()
        tr_loss = total / max(1, n); va_loss = vt / max(1, vn)
        print(f"epoch {epoch}: train {tr_loss:.4f} val {va_loss:.4f} top1 {top1/max(1,vn):.4f} top5 {top5/max(1,vn):.4f}")
        if va_loss < best:
            best = va_loss
            torch.save({"state_dict": model.state_dict(), "input_dim": input_dim, "combo_count": COMBO_COUNT}, os.path.join(args.out, "range_model.pt"))
    # export best / final weights
    model.load_state_dict(torch.load(os.path.join(args.out, "range_model.pt"), map_location="cpu")["state_dict"])
    sd = {k: v.detach().cpu().numpy() for k, v in model.state_dict().items()}
    payload = {
        "version": 1,
        "inputDim": int(input_dim),
        "hidden": int(args.hidden),
        "comboCount": int(out_dim),
        "labelMode": args.label_mode,
        "cards": [s + r for s in SUITS for r in RANKS],
        "weights": {k: sd[k].reshape(-1).round(6).tolist() for k in sd},
    }
    js = "window.HOLDEM_RANGE_MODEL=" + json.dumps(payload, separators=(",", ":")) + ";\n"
    js += r''';(function(){
  const M=window.HOLDEM_RANGE_MODEL;
  function dense(x,w,b,out){ for(let o=0;o<out;o++){let s=b[o]; const off=o*x.length; for(let i=0;i<x.length;i++) s+=x[i]*w[off+i]; x[o]=s;} }
  window.HoldemRangeModel={ predict(features){
    let h=new Float32Array(M.hidden);
    const w0=M.weights['trunk.0.weight'], b0=M.weights['trunk.0.bias'];
    for(let o=0;o<M.hidden;o++){let s=b0[o];const off=o*features.length;for(let i=0;i<features.length;i++)s+=features[i]*w0[off+i];h[o]=Math.max(0,s);}
    const w2=M.weights['trunk.3.weight'], b2=M.weights['trunk.3.bias']; let h2=new Float32Array(M.hidden);
    for(let o=0;o<M.hidden;o++){let s=b2[o];const off=o*M.hidden;for(let i=0;i<M.hidden;i++)s+=h[i]*w2[off+i];h2[o]=Math.max(0,s);}
    const wh=M.weights['head.weight'], bh=M.weights['head.bias']; let logits=new Float32Array(M.comboCount);
    for(let o=0;o<M.comboCount;o++){let s=bh[o];const off=o*M.hidden;for(let i=0;i<M.hidden;i++)s+=h2[i]*wh[off+i];logits[o]=s;}
    return logits;
  }};
})();'''
    open(os.path.join(args.out, "range-model.js"), "w", encoding="utf-8").write(js)
    open(os.path.join(args.out, "feature_schema.json"), "w", encoding="utf-8").write(json.dumps({"inputDim": input_dim, "cards": payload["cards"]}, indent=2))
    print("saved", os.path.join(args.out, "range_model.pt"), "and range-model.js")

if __name__ == "__main__":
    main()
