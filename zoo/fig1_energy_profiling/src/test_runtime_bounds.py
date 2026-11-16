import numpy as np
from collect_whole_run_bounds import interval_statistics,statistics

def test_whisker_covers_both_endpoint_sample_intervals():
 lo=np.arange(10,dtype=float)+10;hi=lo*2;mid=(lo+hi)/2
 m,c,l,h,a,b=interval_statistics(mid,lo,hi)
 lm,lc=statistics(lo);hm,hc=statistics(hi)
 assert a<=lm-lc and b>=hm+hc and a<=m-c and b>=m+c
 assert m==(l+h)/2 and a<l and b>h

def test_equal_bounds_preserve_ordinary_sample_ci():
 x=np.arange(10,dtype=float)+1
 m,c,l,h,a,b=interval_statistics(x,x,x)
 assert m==l==h and a==m-c and b==m+c
