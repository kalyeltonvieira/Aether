#!/usr/bin/env python3
"""Render a compact latency/memory summary from the final phase-3 JSON."""
import argparse,json
from pathlib import Path
import matplotlib.pyplot as plt
import numpy as np


def main():
    p=argparse.ArgumentParser();p.add_argument('--summary',default='results/phase3/final_mixed/summary.json');p.add_argument('--out',default='results/phase3/phase3_results.png');a=p.parse_args()
    data=json.load(open(a.summary))['summary']; ns=['1000','10000','100000']; labels=['1 mil','10 mil','100 mil']
    baseline=[]; compact=[]; adaptive=[]; compact_labels=[]; rss_set=[];rss_comp=[]
    for n in ns:
        d=data[n]; baseline.append(d['sets+set']['total_ms'])
        key=min(('compact+set','compact+epoch'),key=lambda k:d[k]['total_ms'])
        compact.append(d[key]['total_ms']);compact_labels.append(key.replace('compact+',''))
        adaptive.append(d['compact+adaptive']['total_ms'])
        rss_set.append(d['sets+set']['rss_delta_after_build_bytes']/1e6)
        rss_comp.append(d[key]['rss_delta_after_build_bytes']/1e6)
    x=np.arange(len(ns));w=.24
    fig,(ax,mem)=plt.subplots(1,2,figsize=(12,5.6),gridspec_kw={'width_ratios':[1.55,1]})
    colors=['#52677d','#2d8a78','#d28d38']
    for i,(vals,label,color) in enumerate(zip((baseline,compact,adaptive),('sets + set BFS','array compacto + melhor rota','array compacto + adaptativo'),colors)):
        bars=ax.bar(x+(i-1)*w,vals,width=w,label=label,color=color)
        ax.bar_label(bars,fmt='%.1f',fontsize=8,padding=2)
    ax.set_yscale('log');ax.set_ylabel('Tempo total mediano (ms, escala log)')
    ax.set_xticks(x,[f'{label}\ncompact: {route}' for label,route in zip(labels,compact_labels)]);ax.set_title('Latência total: memória menor não garante menor tempo')
    ax.grid(axis='y',which='both',alpha=.2);ax.legend(fontsize=8,loc='upper left')
    b1=mem.bar(x-w/2,rss_set,width=w,label='sets: delta RSS',color=colors[0])
    b2=mem.bar(x+w/2,rss_comp,width=w,label='compacto: delta RSS',color=colors[1])
    mem.bar_label(b1,fmt='%.2f',fontsize=8,padding=2);mem.bar_label(b2,fmt='%.2f',fontsize=8,padding=2)
    mem.set_xticks(x,labels);mem.set_ylabel('Delta RSS após construir grafo (MB)')
    mem.set_title('RAM residente incremental')
    mem.grid(axis='y',alpha=.2);mem.legend(fontsize=8,loc='upper left')
    fig.suptitle('Projeto Aether — Fase 3 · 5 sementes por escala · exatidão validada',fontsize=13,fontweight='bold')
    fig.text(.5,.015,'Sintético e esparso; RSS inclui runtime. O controlador ficou atrás da rota fixa em todas as escalas.',ha='center',fontsize=9)
    fig.tight_layout(rect=(0,.05,1,.94));out=Path(a.out);out.parent.mkdir(parents=True,exist_ok=True);fig.savefig(out,dpi=180,bbox_inches='tight')
    print(out)
if __name__=='__main__':main()
