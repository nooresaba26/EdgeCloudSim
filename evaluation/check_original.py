"""Compare offered tasks one by one against the stdout of the original thesis scenario."""
import argparse
import csv
import gzip
import os
from pathlib import Path
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor

from run import JAVA, MAIN, SEEDS, cell, compile_java, csv_write, key

event=re.compile(r"^([0-9.]+) task=(\d+) host=(\d+) (ASSIGNED|RESOLVED_\w+) ")
refused=re.compile(r"^([0-9.]+) task=(\d+) (CAP_FULL|NO_FEASIBLE)$")

def replay(seed,repo,out,cp):
    raw=subprocess.run([*JAVA,"-Dedgecloudsim.seed="+str(seed),"-cp",cp,MAIN],
                       cwd=repo,check=True,capture_output=True,text=True).stdout
    times,terminal={},{}
    for line in raw.splitlines():
        m=event.match(line)
        if m:
            t,i,host,e=m.groups()
            if e=="ASSIGNED": times[int(i)]=(int(host),float(t))
            else: terminal[int(i)]=(e.removeprefix("RESOLVED_"),float(t))
        m=refused.match(line)
        if m: terminal[int(m[2])]=(m[3],None)
    branch=out/"pilot" if seed==42 else out
    with gzip.open(branch/"raw"/key(cell("FULL"))/f"seed-{seed}.csv.gz","rt",newline="") as f:
        rows=list(csv.DictReader(f))
    if len(rows)!=len(terminal): raise ValueError(f"Task count mismatch, seed {seed}")
    for r in rows:
        i=int(r["task"])
        cause,observed=terminal[i]
        if r["terminal"]!=cause or bool(r["host"])!=(i in times): raise ValueError((seed,i,"decision"))
        if i in times:
            h,t=times[i]
            if int(r["host"])!=h or abs(float(r["assigned_s"])-t)>0.00005001 or abs(float(r["observed_s"])-observed)>0.00005001:
                raise ValueError((seed,i,"host or clock differs"))
    return dict(seed=seed,offered_checked=len(rows),assignments_checked=len(times),terminal_outcomes_checked=len(terminal),status="match")

if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo",type=Path,required=True)
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--jobs",type=int,default=2)
    a=p.parse_args()
    repo=a.repo.resolve()
    out=a.out.resolve()
    jars=sorted((repo/"lib").glob("*.jar"))
    build=out/".original"
    compile_java(repo,build,jars,original=True)
    cp=os.pathsep.join(map(str,[build,*jars]))
    with ThreadPoolExecutor(max_workers=a.jobs) as pool:
        result=list(pool.map(lambda s: replay(s,repo,out,cp),[42,*SEEDS]))
    csv_write(out/"original_event_check.csv",result)
    print(sum(r["offered_checked"] for r in result),"tasks matched across",len(result),"original runs.")
