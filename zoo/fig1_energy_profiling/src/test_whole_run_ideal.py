"""First-use replay preserves compute, deduplicates words, and charges real occupancy."""
from types import SimpleNamespace as N
from whole_run_ideal import first_uses,write_stream
from lays.nocsim.sim import run_eventsim
from zoo.fig12_edp.nocsim.energycounts import parse_tc_csv

def tick(t,*addresses):return N(tick=t,cores=[N(core_id=0,weight_addresses=list(addresses))])
def trace(tiles):return N(workload_dims={'KH':1,'KW':1,'CIN':2,'COUT':128},tiles=tiles)
def tile(d,ticks,mac=4):return N(dram_i=d,noc_i=0,mac_cycles=mac,lif_cycles=1,ticks=ticks)
def test_first_use_words_and_spd_packet_padding(tmp_path):
 t=trace([tile(0,[tick(0,[0,0,0,0,16]),tick(2,[0,0,0,16,64])]),tile(1,[tick(0,[0,0,0,0,64]),tick(1,[0,0,0,64,128])])])
 events,n,work=first_uses(t)
 assert n==128
 assert [[u['words'] for u in e['first_uses']] for e in events]==[[16,48],[64]]
 assert events[0]['first_uses'][1]['word_spans']==[[16,64]]
 out=tmp_path/'tc.csv';C,p=write_stream(events,out,3)
 assert C==10 and p==[1,2,2]
 sim=run_eventsim(out,1,1,3,.25)
 assert sim['count_cycles']==10 and sim['dram_cycles']==3 and sim['total_cycles']==13
 counts=parse_tc_csv(out,X=1,Y=1,dram_port=3,gb_port=1)
 assert counts['dram_bytes']==192 and counts['l1_delivery_bytes']==160

def test_same_tick_words_share_transaction_rounding(tmp_path):
 events,n,_=first_uses(trace([tile(0,[tick(2,[0,0,0,0,128])])]))
 assert n==128
 out=tmp_path/'tc.csv';C,p=write_stream(events,out,3)
 assert C==5 and p==[4]
 sim=run_eventsim(out,1,1,3,.25)
 assert sim['total_cycles']==6 and sim['dram_cycles']==1
 lines=out.read_text().splitlines()
 assert 'mac_0_0__count_0_part_0' in lines[0]
 assert lines[1].split(',')[3]=='2'  # no first-use request before its native tick

def test_no_demand_keeps_native_work(tmp_path):
 events,n,_=first_uses(trace([tile(0,[],3)]));assert n==0
 p=tmp_path/'tc.csv';C,packets=write_stream(events,p,3);assert C==4 and not packets
 sim=run_eventsim(p,1,1,3,.25);assert sim['total_cycles']==4 and sim['dram_cycles']==0
