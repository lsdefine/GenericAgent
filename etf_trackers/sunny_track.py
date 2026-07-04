#!/usr/bin/env python3
"""阳光电源 300274 独立跟踪"""
import akshare as ak, pandas as pd, numpy as np, json, os, time
from datetime import datetime as dt

MSG_DIR = '/Users/ourgang/Agents/GenericAgent/etf_trackers'
CODE='300274'; NAME='阳光电源'

def fetch(retries=3):
    for i in range(retries):
        try:
            return ak.stock_zh_a_hist(symbol=CODE, period="daily", adjust="qfq")
        except Exception as e:
            if i < retries-1: time.sleep(2)
            else: raise

def get_signal():
    df = fetch()
    if df is None or len(df)<60: return None
    df['date']=pd.to_datetime(df['日期']); df=df.sort_values('date').reset_index(drop=True)
    c=df['收盘']; n=c.iloc[-1]
    ma5=c.rolling(5).mean().iloc[-1]; ma10=c.rolling(10).mean().iloc[-1]
    ma20=c.rolling(20).mean().iloc[-1]
    vol=df['成交量']; vrat=vol.iloc[-1]/vol.tail(20).mean()
    chg=df['涨跌幅']; cons_d=0
    for i in range(len(chg)-1,-1,-1):
        if chg.iloc[i]<0: cons_d+=1
        else: break
    if cons_d>=3 and vol.iloc[-1]<vol.tail(5).mean()*0.7:
        return f'🔴{NAME}买点A：连跌{cons_d}天+缩量，现价{n:.2f}'
    if n<ma20*0.85 and vrat<0.6:
        return f'🔴{NAME}买点B：超卖缩量(偏离MA20 {(n/ma20-1)*100:.1f}%)，现价{n:.2f}'
    if n>ma5 and ma5>ma10:
        return f'🟢{NAME}突破买点：MA5上拐，现价{n:.2f}'
    return None

now=dt.now().strftime('%Y-%m-%d %H:%M')
sig=get_signal()
price=None
try:
    df2=fetch(); df2=df2.sort_values('日期').reset_index(drop=True)
    price=float(df2['收盘'].iloc[-1])
except: pass
msg={'now':now,'code':CODE,'name':NAME,'price':price,'signal':sig}
with open(os.path.join(MSG_DIR,'sunny_latest.json'),'w') as f:
    json.dump(msg,f,ensure_ascii=False,indent=2)
print(json.dumps(msg,ensure_ascii=False))
