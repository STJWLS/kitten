import argparse, json, random, sys
import numpy as np
import torch
from train_range_model import RowDataset, RangeNet, RANK_PAIR_COUNT, COMBO_COUNT, RANK_PAIR_INDEX, RANK_INDEX
from torch.utils.data import DataLoader
import math

ap=argparse.ArgumentParser(); ap.add_argument('--data',default='training/data/selfplay300.jsonl'); ap.add_argument('--model',default='training/out91/range_model.pt'); ap.add_argument('--seed',type=int,default=7); ap.add_argument('--hidden',type=int,default=128)
a=ap.parse_args(); random.seed(a.seed); np.random.seed(a.seed); torch.manual_seed(a.seed)
rows=[]
with open(a.data,encoding='utf-8') as f:
 for line in f:
  try: rows.append(json.loads(line))
  except: pass
groups=sorted(set(r['gameId'] for r in rows)); random.shuffle(groups); nval=max(1,int(len(groups)*.15)); val=set(groups[:nval])
val_rows=[r for r in rows if r['gameId'] in val]
ds=RowDataset(val_rows,'rankpair'); dl=DataLoader(ds,batch_size=128,shuffle=False)
sd=torch.load(a.model,map_location='cpu'); dim=sd['input_dim']; out=sd['state_dict']['head.weight'].shape[0]
model=RangeNet(dim,hidden=a.hidden,out_dim=out); model.load_state_dict(sd['state_dict']); model.eval()
loss=0; n=0; top1=top5=top10=0; ranks=[]; probs_true=[]
with torch.no_grad():
 for x,y in dl:
  logits=model(x); loss+=torch.nn.functional.cross_entropy(logits,y,reduction='sum').item(); n+=len(y)
  order=logits.argsort(dim=1,descending=True)
  pos=(order==y[:,None]).float().argmax(dim=1)
  ranks.extend((pos+1).tolist())
  top1+=(pos==0).sum().item(); top5+=(pos<5).sum().item(); top10+=(pos<10).sum().item()
  p=torch.softmax(logits,dim=1); probs_true.extend(p[torch.arange(len(y)),y].tolist())
print(json.dumps({'n':n,'loss':loss/n,'top1':top1/n,'top5':top5/n,'top10':top10/n,'random_top1':1/out,'random_top5':5/out,'random_top10':10/out,'mean_true_prob':sum(probs_true)/len(probs_true),'mean_rank':sum(ranks)/len(ranks),'median_rank':float(np.median(ranks)),'out':out},ensure_ascii=False,indent=2))
