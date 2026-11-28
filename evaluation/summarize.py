"""Validate and summarize matched EdgeCloudSim runs without plotting."""
import argparse
from collections import Counter, defaultdict
import csv
import gzip
import hashlib
import json
import math
from pathlib import Path
from statistics import fmean, stdev

from run import FOCUS, SEEDS, cell, csv_write, design, key

END, SWITCH, LAST = 180.0, 75.0, 140.0
T95=[None,12.7062,4.3027,3.1824,2.7764,2.5706,2.4469,2.3646,2.3060,2.2622,
     2.2281,2.2010,2.1788,2.1604,2.1448,2.1314,2.1199,2.1098,2.1009,2.0930,
     2.0860,2.0796,2.0739,2.0687,2.0639,2.0595,2.0555,2.0518,2.0484,2.04523]
CONTRAST_METRICS=["offered_success_pct","assigned_success_pct","failed_pct_assigned","failed_per100_offered",
                  "cap_refused_pct","no_feasible_pct","useful_per_s","latency_mean_s","latency_p95_s",
                  "late_valid_pct_assigned","timeout_pct_assigned","mean_u_all","peak_u_all",
                  "h1_pre_per100_offered","h1_post_per100_offered","h1_post_share_pct","h1_post_assigned",
                  "h1_post_failed","h1_early_per100_offered","h1_until_first_bad_report","h1_first_bad_report_s","prediction_mae_s"]

def pct(a,b): return 100*a/b if b else None
def mean(v): return fmean(v) if v else None
def p95(v):
    if not v: return None
    a=sorted(v)
    p=(len(a)-1)*0.95
    i=int(p)
    return a[i]+(p-i)*(a[min(i+1,len(a)-1)]-a[i])

def interval(xs):
    n=len(xs)
    if not n: return (0,None,None,None)
    m=fmean(xs)
    if n==1: return n,m,None,None
    half=T95[n-1]*stdev(xs)/math.sqrt(n)
    return n,m,m-half,m+half

def check(ok,description):
    if not ok: raise ValueError(description)

def read_run(path,c):
    with gzip.open(path,"rt",newline="") as f: rows=list(csv.DictReader(f))
    h=hashlib.sha256()
    pre=hashlib.sha256()
    for i,r in enumerate(rows,1):
        check(int(r["task"])==i,"task IDs")
        names=("task","device","app","arrival_s","input_kb","output_kb","work_mi","cores","ram_mb","deadline_s")
        h.update((",".join(r[n] for n in names)+"\n").encode())
        if float(r["arrival_s"])<SWITCH:
            pre.update((",".join(r[n] for n in ("task","host","assigned_s","r_before","u_before","cap_before","h1_feasible","h1_admissible"))+"\n").encode())
        for k in ("host","u_before","cap_before","h1_feasible","h1_admissible","withheld","verified_correct","app"):
            r[k]=int(r[k]) if r[k]!="" else None
        for k in ("arrival_s","deadline_s","assigned_s","predicted_s","r_before","cpu_done_s","verified_s","terminal_s","observed_s"):
            r[k]=float(r[k]) if r[k]!="" else None
        check(r["arrival_s"]<=LAST,"arrival after cutoff")
        if r["host"] is None:
            check(r["terminal"] in ("CAP_FULL","NO_FEASIBLE") and r["observed_s"] is None,"refusal")
            if c["policy"] in ("RANDOM","SHORTEST","REP_ONLY"): check(r["terminal"]!="CAP_FULL","uncapped refusal")
            continue
        check(r["terminal"] in ("OK","INVALID","TIMEOUT","BANDWIDTH","EXEC_FAILURE"),"terminal status")
        check(r["observed_s"] is not None and r["observed_s"]<END,"undrained assignment")
        check(r["predicted_s"]<=r["deadline_s"]-r["assigned_s"]+1e-8,"predicted deadline")
        if c["policy"] in ("RANDOM","SHORTEST","REP_ONLY"): check(r["cap_before"] is None,"unexpected cap")
        else:
            expected=c["staticCap"] if c["policy"]=="STATIC" else 1+math.floor((c["bMax"]-1)*r["r_before"])
            check(r["cap_before"]==expected and r["u_before"]+1<=expected,"admission rule")
        epsilon=1e-6 if r["terminal"]=="TIMEOUT" else 0.0
        check(abs(r["observed_s"]-r["terminal_s"]-c["feedback"]-epsilon)<1e-7,"scheduler clock")
        good=(r["verified_s"] is not None and r["verified_correct"]==1 and r["verified_s"]<=r["deadline_s"])
        check((r["terminal"]=="OK")==good,"device deadline")
        if r["withheld"] or r["verified_correct"]==0:
            check(c["fault"]!="NORMAL" and r["host"]==1 and r["cpu_done_s"]>=SWITCH,"fault scope")
    # Independent reconstruction from terminal feedback already visible at each decision.
    for host in (0,1,2):
        jobs=[r for r in rows if r["host"]==host]
        reports=sorted(jobs,key=lambda r:r["observed_s"])
        count=0
        success=failure=last=0.0
        for assigned_before,r in enumerate(jobs):
            t=r["assigned_s"]
            while count<len(reports) and reports[count]["observed_s"]<t:
                q=reports[count]
                observed=q["observed_s"]
                decay=math.exp(-c["kappa"]*(observed-last))
                success*=decay
                failure*=decay
                weight=math.exp(-c["kappa"]*(observed-q["terminal_s"]))
                if q["terminal"]=="OK": success+=weight
                else: failure+=weight
                last=observed
                count+=1
            # At equal times CloudSim resolves according to its event insertion order.
            if count<len(reports) and reports[count]["observed_s"]==t: continue
            decay=math.exp(-c["kappa"]*(t-last))
            estimate=(1+decay*success)/(2+decay*(success+failure))
            check(abs(estimate-r["r_before"])<1e-10,"reputation reconstruction")
            check(assigned_before-count==r["u_before"],"unresolved reconstruction")
    return rows,h.hexdigest(),pre.hexdigest()

def metrics(rows):
    ass=[r for r in rows if r["host"] is not None]
    ok=[r for r in ass if r["terminal"]=="OK"]
    ver=[r for r in ass if r["verified_s"] is not None]
    counts=Counter(r["terminal"] for r in rows)
    n,a,s=len(rows),len(ass),len(ok)
    check(n==a+counts["CAP_FULL"]+counts["NO_FEASIBLE"] and a==sum(counts[t] for t in ("OK","INVALID","TIMEOUT","BANDWIDTH","EXEC_FAILURE")),"task conservation")
    late=sum(r["verified_correct"]==1 and r["verified_s"]>r["deadline_s"] for r in ver)
    latency=[r["verified_s"]-r["arrival_s"] for r in ok]
    errors=[r["verified_s"]-r["arrival_s"]-r["predicted_s"] for r in ver]
    events=sorted((t,step) for r in ass for t,step in ((r["assigned_s"],1),(r["observed_s"],-1)))
    peak=u=0
    for _,step in events:
        u+=step
        peak=max(peak,u)
    check(u==0,"nonzero unresolved at end")
    before=[r for r in rows if r["arrival_s"]<SWITCH]
    after=[r for r in rows if r["arrival_s"]>=SWITCH]
    early=[r for r in after if r["arrival_s"]<SWITCH+15]
    h=[r for r in ass if r["host"]==1]
    hpre=[r for r in h if r["assigned_s"]<SWITCH]
    hpost=[r for r in h if r["assigned_s"]>=SWITCH]
    first=min((r["observed_s"] for r in h if r["withheld"] or r["verified_correct"]==0),default=None)
    return dict(offered=n,assigned=a,accepted=s,failed=a-s,no_feasible=counts["NO_FEASIBLE"],cap_full=counts["CAP_FULL"],
        invalid=counts["INVALID"],timeout=counts["TIMEOUT"],bandwidth=counts["BANDWIDTH"],exec_failure=counts["EXEC_FAILURE"],
        withheld=sum(r["withheld"] for r in ass),verified_any=len(ver),late_valid=late,pending=u,
        offered_success_pct=pct(s,n),assigned_success_pct=pct(s,a),failed_pct_assigned=pct(a-s,a),
        failed_per100_offered=pct(a-s,n),cap_refused_pct=pct(counts["CAP_FULL"],n),no_feasible_pct=pct(counts["NO_FEASIBLE"],n),
        late_valid_pct_assigned=pct(late,a),timeout_pct_assigned=pct(counts["TIMEOUT"],a),
        useful_per_s=s/END,active_window_useful_per_s=sum(10<=r["verified_s"]<LAST for r in ok)/(LAST-10),
        latency_mean_s=mean(latency),latency_p95_s=p95(latency),prediction_mae_s=mean([abs(x) for x in errors]),
        prediction_bias_actual_minus_pred_s=mean(errors),
        mean_u_all=sum(r["observed_s"]-r["assigned_s"] for r in ass)/END,peak_u_all=peak,
        h1_pre_assigned=len(hpre),h1_pre_offered=len(before),h1_pre_per100_offered=pct(len(hpre),len(before)),
        h1_pre_failed=sum(r["terminal"]!="OK" for r in hpre),
        h1_post_assigned=len(hpost),h1_post_offered=len(after),h1_post_per100_offered=pct(len(hpost),len(after)),
        h1_post_share_pct=pct(len(hpost),sum(r["host"] is not None for r in after)),
        h1_post_failed=sum(r["terminal"]!="OK" for r in hpost),
        h1_early_per100_offered=pct(sum(r["host"]==1 for r in early),len(early)),
        h1_crossing_tasks=sum(r["cpu_done_s"] is not None and r["assigned_s"]<SWITCH<=r["cpu_done_s"] for r in h),
        h1_first_bad_report_s=first,h1_until_first_bad_report=(sum(SWITCH<=r["assigned_s"]<first for r in h) if first is not None else None),
        h1_feasible_post=sum(r["h1_feasible"] for r in after),h1_admissible_post=sum(r["h1_admissible"] for r in after))

def host_windows(rows,c,seed,ident):
    h=[r for r in rows if r["host"]==1]
    for t in range(0,180,5):
        end=t+5
        cohort=[r for r in rows if t<=r["arrival_s"]<end]
        jobs=[r for r in cohort if r["host"]==1]
        s=f=0.0
        for r in h:
            if r["observed_s"]<=t:
                w=math.exp(-c["kappa"]*(t-r["terminal_s"]))
                if r["terminal"]=="OK": s+=w
                else: f+=w
        reputation=(1+s)/(2+s+f)
        cap=None
        if c["policy"] in ("ADMISSION_ONLY","FULL"): cap=1+math.floor((c["bMax"]-1)*reputation)
        if c["policy"]=="STATIC": cap=c["staticCap"]
        yield dict(setting=ident,seed=seed,host=1,bin_start_s=t,bin_end_s=end,reputation_at_start=reputation,
                   unresolved_at_start=sum(r["assigned_s"]<=t<r["observed_s"] for r in h),cap_at_start=cap,
                   mean_unresolved_in_bin=sum(max(0,min(end,r["observed_s"])-max(t,r["assigned_s"])) for r in h)/5,
                   offered=len(cohort),all_assigned=sum(r["host"] is not None for r in cohort),h1_assigned=len(jobs),
                   h1_feasible=sum(r["h1_feasible"] for r in cohort),h1_admissible=sum(r["h1_admissible"] for r in cohort),
                   eventually_failed_h1=sum(r["terminal"]!="OK" for r in jobs),
                   ok_reports_h1=sum(t<=r["observed_s"]<end and r["terminal"]=="OK" for r in h),
                   failure_reports_h1=sum(t<=r["observed_s"]<end and r["terminal"]!="OK" for r in h))

def summarize(root,sel):
    stages=design()
    cells={key(c):c for e in sel for c in stages[e]}
    out=root/"tables"/("all" if sel=="ABCD" else sel)
    by=defaultdict(dict)
    traces=[]
    series=[]
    hashes={}
    prehashes={}
    for ident,c in cells.items():
        labels="".join(e for e in stages if c in stages[e])
        for seed in SEEDS:
            path=root/"raw"/ident/f"seed-{seed}.csv.gz"
            if not path.is_file(): raise FileNotFoundError(str(path)+" is missing. Run the matching experiment.")
            rows,h,pre=read_run(path,c)
            check(hashes.setdefault((seed,c["devices"]),h)==h,"workload mismatch")
            if "C" in labels:
                check(prehashes.setdefault((seed,c["policy"]),pre)==pre,"pre-change decisions differ by severity")
                series.extend(host_windows(rows,c,seed,ident))
            m=metrics(rows)
            by[ident][seed]=m
            traces.append(dict(setting=ident,experiments=labels,seed=seed,**c,workload_sha256=h,**m))
    csv_write(out/"run_metrics.csv",traces)
    csv_write(out/"server1_5s.csv",series)
    summaries=[]
    for ident,runs in by.items():
        for metric in next(iter(runs.values())):
            xs=[r[metric] for r in runs.values() if r[metric] is not None]
            n,mu,lo,hi=interval(xs)
            summaries.append(dict(setting=ident,**cells[ident],metric=metric,n=n,mean=mu,ci95_low=lo,ci95_high=hi))
    csv_write(out/"policy_summary.csv",summaries)
    summary_index={(r["setting"],r["metric"]):r for r in summaries}
    files={"A":"A_load","B":"B_feedback","C":"C_deterioration","D":"D_ablation"}
    core_metrics=["offered_success_pct","assigned_success_pct","failed_per100_offered","cap_refused_pct",
                  "no_feasible_pct","useful_per_s","latency_mean_s","latency_p95_s","late_valid_pct_assigned",
                  "mean_u_all","h1_pre_per100_offered","h1_post_per100_offered","h1_post_share_pct","h1_post_failed"]
    for e in sel:
        overview=[]
        for c in stages[e]:
            ident=key(c)
            row=dict(setting=ident,**c,seeds=len(SEEDS))
            for m in core_metrics:
                entry=summary_index[ident,m]
                row[m]=entry["mean"]
                if m in ("offered_success_pct","failed_per100_offered"):
                    row[m+"_ci95_low"]=entry["ci95_low"]
                    row[m+"_ci95_high"]=entry["ci95_high"]
            overview.append(row)
        csv_write(out/(files[e]+".csv"),overview)
    contrasts=[]
    def delta(e,c,b,metric,label):
        left,right=by[key(c)],by[key(b)]
        ds=[left[s][metric]-right[s][metric] for s in SEEDS if left[s][metric] is not None and right[s][metric] is not None]
        n,mu,lo,hi=interval(ds)
        return dict(experiment=e,first=key(c),second=key(b),contrast=label,metric=metric,n_pairs=n,mean_difference=mu,ci95_low=lo,ci95_high=hi)
    for e in sel:
        group=stages[e]
        pairs=([(cell("FULL"),b) for b in group if b!=cell("FULL")] if e=="D" else [
            (a,b) for a in group if a["policy"]=="FULL" for b in group
            if b["policy"]!="FULL" and all(a[k]==b[k] for k in a if k!="policy")])
        for a,b in pairs:
            for m in CONTRAST_METRICS: contrasts.append(delta(e,a,b,m,"full minus comparison"))
    csv_write(out/"paired_differences.csv",contrasts)
    if "C" in sel:
        csv_write(out/"fault_minus_normal.csv",(delta("C",cell(p,fault=f),cell(p,fault="NORMAL"),m,"fault minus normal")
            for p in FOCUS for f in ("MILD","SEVERE") for m in CONTRAST_METRICS))
    if "C" in sel:
        effects=[]
        for fault in ("MILD","SEVERE"):
            for p in ("REP_ONLY","STATIC"):
                for m in ("h1_post_per100_offered","h1_post_share_pct","h1_post_failed","offered_success_pct"):
                    a,b=by[key(cell("FULL",fault=fault))],by[key(cell(p,fault=fault))]
                    x,y=by[key(cell("FULL",fault="NORMAL"))],by[key(cell(p,fault="NORMAL"))]
                    n,mu,lo,hi=interval([(a[s][m]-x[s][m])-(b[s][m]-y[s][m]) for s in SEEDS])
                    effects.append(dict(fault=fault,comparison=p,metric=m,n=n,
                                        difference_in_fault_minus_normal_effect=mu,ci95_low=lo,ci95_high=hi))
        csv_write(out/"deterioration_interactions.csv",effects)
    if "B" in sel:
        interactions=[]
        for d in (1,3,6):
            for p in ("REP_ONLY","STATIC"):
                for m in ("offered_success_pct","failed_per100_offered","useful_per_s","mean_u_all"):
                    a,b=by[key(cell("FULL",feedback=d))],by[key(cell(p,feedback=d))]
                    x,y=by[key(cell("FULL",feedback=0))],by[key(cell(p,feedback=0))]
                    n,mu,lo,hi=interval([(a[s][m]-b[s][m])-(x[s][m]-y[s][m]) for s in SEEDS])
                    interactions.append(dict(delay_s=d,comparison=p,metric=m,n=n,change_in_full_advantage_vs_zero=mu,ci95_low=lo,ci95_high=hi))
        csv_write(out/"delay_interactions.csv",interactions)
    report=dict(settings=len(cells),runs=len(traces),load_seed_groups=len(hashes),unique_workload_hashes=len(set(hashes.values())),
                task_rows=sum(r["offered"] for r in traces),pending=sum(r["pending"] for r in traces),
                first_seed=SEEDS[0],last_seed=SEEDS[-1],server1_bin_records=len(series))
    (out/"checks.json").write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps(report))
if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--stage",choices=["all","A","B","C","D"],default="all")
    a=p.parse_args()
    summarize(a.out.resolve(),"ABCD" if a.stage=="all" else a.stage)
